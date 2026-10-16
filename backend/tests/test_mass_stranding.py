"""Mass strandings: several cetaceans at one place and time.

Three layers, same as the feature:

1. The detection rule on its own (`dispatch/mass_stranding.py`).
2. The animal count travelling from the assessment agent to the report writer
   and the guardrail, so "three dolphins" is something the report may say.
3. Whole reports over HTTP, where the answer for an incident changes as other
   people report.

The rule being protected throughout: counts from reports of the *same*
incident are never added, and counts from *separate* incidents are.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from lifejacket.agents.assessment import AssessmentAgent
from lifejacket.agents.guardrail import GuardrailAgent
from lifejacket.agents.report import ReportAgent
from lifejacket.api.main import app
from lifejacket.config import settings
from lifejacket.dispatch.mass_stranding import StrandingReport, find_mass_strandings
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.llm.prompts import render_prompt
from lifejacket.models.db import get_session
from lifejacket.models.schemas import (
    AnimalGroup,
    AssessmentResult,
    EnvironmentalContext,
    IdentificationResult,
    IncidentReport,
    SpeciesCandidate,
)
from lifejacket.models.tables import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 5, 12, 0)
BEACH = (36.8000, -121.7900)

#: Degrees of latitude per kilometre, near enough for placing test points.
KM = 1 / 111.0


def stranding(
    incident_id: str,
    *,
    count: int = 1,
    km_north: float = 0.0,
    hours_ago: float = 0.0,
    group: AnimalGroup = AnimalGroup.CETACEAN,
    duplicate_of: str | None = None,
    active: bool | None = None,
) -> StrandingReport:
    return StrandingReport(
        incident_id=incident_id,
        latitude=BEACH[0] + km_north * KM,
        longitude=BEACH[1],
        reported_at=NOW - timedelta(hours=hours_ago),
        animal_group=group,
        animal_count=count,
        duplicate_of=duplicate_of,
        # A linked duplicate is cancelled, so it is not active unless a test says so.
        is_active=(duplicate_of is None) if active is None else active,
    )


# ---------------------------------------------------------------------------
# 1. The detection rule
# ---------------------------------------------------------------------------


class TestOneReport:
    def test_one_dolphin_is_not_a_mass_stranding(self):
        assert find_mass_strandings([stranding("A")]) == {}

    def test_one_report_of_three_dolphins_is(self):
        events = find_mass_strandings([stranding("A", count=3)])

        event = events["A"]
        assert event.animal_count == 3
        assert event.incident_ids == ["A"]
        assert event.report_count == 1
        assert event.animal_group is AnimalGroup.CETACEAN
        assert "one report" in event.reason

    def test_two_animals_are_flagged_with_the_cow_calf_caveat(self):
        """NOAA excludes a mother and calf. Nothing here can tell, so it says so."""
        event = find_mass_strandings([stranding("A", count=2)])["A"]
        assert "mother and calf" in event.reason

        bigger = find_mass_strandings([stranding("A", count=3)])["A"]
        assert "mother and calf" not in bigger.reason


class TestOnlyCetaceans:
    def test_several_seals_on_one_beach_is_a_haul_out(self):
        reports = [stranding("A", count=6, group=AnimalGroup.PINNIPED)]
        assert find_mass_strandings(reports) == {}

    def test_separate_seal_incidents_nearby_are_not_an_event_either(self):
        reports = [
            stranding("A", group=AnimalGroup.PINNIPED),
            stranding("B", group=AnimalGroup.PINNIPED, km_north=1.5),
        ]
        assert find_mass_strandings(reports) == {}

    def test_a_seal_next_to_a_dolphin_does_not_make_two(self):
        reports = [
            stranding("dolphin"),
            stranding("seal", group=AnimalGroup.PINNIPED, km_north=0.2),
        ]
        assert find_mass_strandings(reports) == {}

    def test_unknown_group_does_not_count(self):
        assert find_mass_strandings([stranding("A", count=4, group=AnimalGroup.UNKNOWN)]) == {}


class TestDuplicatesAreTheSameAnimals:
    def test_a_duplicate_does_not_add_an_animal(self):
        """Five people reporting one dolphin is one dolphin."""
        reports = [stranding("A")] + [stranding(f"dup{i}", duplicate_of="A") for i in range(4)]
        assert find_mass_strandings(reports) == {}

    def test_counts_within_one_incident_take_the_largest_not_the_sum(self):
        reports = [
            stranding("A", count=2),
            stranding("dup1", count=3, duplicate_of="A"),
            stranding("dup2", count=2, duplicate_of="A"),
        ]
        event = find_mass_strandings(reports)["A"]
        assert event.animal_count == 3  # not 7
        assert event.report_count == 3
        assert event.incident_ids == ["A"]  # duplicates are not listed as incidents

    def test_a_later_reporter_can_reveal_the_scale(self):
        """The first person saw one dolphin; the second saw the other four."""
        reports = [stranding("A", count=1), stranding("dup", count=5, duplicate_of="A")]
        events = find_mass_strandings(reports)

        assert events["A"].animal_count == 5
        # The duplicate's own page shows the event it belongs to.
        assert events["dup"] is events["A"]

    def test_a_duplicate_of_something_not_open_is_ignored(self):
        assert find_mass_strandings([stranding("dup", count=5, duplicate_of="gone")]) == {}


class TestSeparateIncidentsAreDifferentAnimals:
    def test_two_incidents_along_the_beach_add_up(self):
        reports = [stranding("A", hours_ago=2), stranding("B", km_north=1.5)]
        events = find_mass_strandings(reports)

        assert events["A"].animal_count == 2
        assert events["A"].incident_ids == ["A", "B"]  # oldest first
        assert events["A"].report_count == 2
        assert events["B"] is events["A"]
        assert "2 incidents" in events["A"].reason

    def test_counts_and_duplicates_combine(self):
        reports = [
            stranding("A", count=2),
            stranding("dupA", count=3, duplicate_of="A"),
            stranding("B", count=1, km_north=1.0),
        ]
        event = find_mass_strandings(reports)["B"]
        assert event.animal_count == 4  # max(2, 3) + 1
        assert event.report_count == 3

    def test_too_far_apart_is_two_single_animals(self):
        reports = [stranding("A"), stranding("B", km_north=3.0)]
        assert find_mass_strandings(reports) == {}

    def test_too_long_apart_is_two_single_animals(self):
        reports = [stranding("A", hours_ago=30), stranding("B", km_north=0.5)]
        assert find_mass_strandings(reports) == {}

    def test_an_event_runs_along_the_beach(self):
        """A to C is 3 km, further than the 2 km limit, but B joins them.

        Every incident in the event must report the same event, or the
        dashboard shows three different numbers for one stranding.
        """
        reports = [
            stranding("A"),
            stranding("B", km_north=1.5),
            stranding("C", km_north=3.0),
            stranding("elsewhere", km_north=40.0),
        ]
        events = find_mass_strandings(reports)

        assert events["A"].animal_count == 3
        assert events["A"] is events["B"] is events["C"]
        assert "elsewhere" not in events


class TestOnlyWhatIsBeingHandledNow:
    def test_an_ended_case_does_not_make_an_event(self):
        reports = [stranding("A"), stranding("resolved", km_north=0.5, active=False)]
        assert find_mass_strandings(reports) == {}

    def test_an_ended_case_does_not_bridge_two_others(self):
        reports = [
            stranding("A"),
            stranding("resolved", km_north=1.5, active=False),
            stranding("C", km_north=3.0),
        ]
        assert find_mass_strandings(reports) == {}

    def test_an_incident_with_no_location_is_skipped_not_fatal(self):
        nowhere = StrandingReport("X", None, None, NOW, AnimalGroup.CETACEAN, animal_count=1)
        events = find_mass_strandings([nowhere, stranding("A", count=2)])
        assert set(events) == {"A"}

    def test_a_nonsense_count_is_treated_as_one(self):
        assert find_mass_strandings([stranding("A", count=0)]) == {}


# ---------------------------------------------------------------------------
# 2. The count, from the assessment agent to the report and the guardrail
# ---------------------------------------------------------------------------


def rendered(agent_class, **kwargs) -> str:
    """The prompt an agent would send for these inputs."""
    agent = agent_class(ScriptedLLMClient())
    return render_prompt(agent.prompt_path, **agent.build_prompt_values(**kwargs))


DOLPHIN = IdentificationResult(
    candidates=[
        SpeciesCandidate(
            common_name="Common dolphin", confidence=0.95, animal_group=AnimalGroup.CETACEAN
        )
    ]
)


class TestAnimalCount:
    def test_the_model_must_give_a_count_of_at_least_one(self):
        schema = AssessmentAgent(ScriptedLLMClient()).output_schema
        assert "animal_count" in schema["required"]
        assert schema["properties"]["animal_count"] == {"type": "integer", "minimum": 1}

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (3, 3),
            (1, 1),
            (None, 1),  # a reply written before the field existed
            (0, 1),
            (-2, 1),
            ("3", 1),  # not a number: do not guess what was meant
            (True, 1),  # a bool is an int in Python
            (2.0, 2),
        ],
    )
    def test_anything_but_a_real_count_means_one(self, raw, expected):
        agent = AssessmentAgent(ScriptedLLMClient())
        reply = {} if raw is None else {"animal_count": raw}
        assert agent.parse(reply).animal_count == expected

    def test_the_assessment_prompt_asks_for_it_and_excludes_healthy_animals(self):
        prompt = rendered(AssessmentAgent, identification=DOLPHIN)
        assert "`animal_count`" in prompt
        assert "haul-out" in prompt  # healthy animals nearby do not count

    def test_the_report_writer_is_told_how_many(self):
        several = rendered(
            ReportAgent, identification=DOLPHIN, assessment=AssessmentResult(animal_count=3)
        )
        assert "Animals in trouble: 3" in several

        one = rendered(ReportAgent, identification=DOLPHIN, assessment=AssessmentResult())
        assert "Animals in trouble: 1 (do not state or imply there are others)" in one

    def test_the_guardrail_checks_against_the_same_count(self):
        """Otherwise a correct "three dolphins" is flagged as invented."""
        prompt = rendered(
            GuardrailAgent,
            report=IncidentReport(headline="3 dolphins stranded", summary="Three dolphins."),
            assessment=AssessmentResult(animal_count=3),
        )
        assert "ANIMAL COUNT (authoritative):" in prompt
        assert "animals in trouble: 3" in prompt


# ---------------------------------------------------------------------------
# 3. Whole reports over HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(settings, "photo_storage_dir", tmp_path / "photos")
    monkeypatch.setattr(
        "lifejacket.services.pipeline.gather_context",
        lambda location: EnvironmentalContext(location=location, unavailable=["tide"]),
    )
    monkeypatch.setattr("lifejacket.services.pipeline.reverse_geocode", lambda *a: None)

    current: dict[str, ScriptedLLMClient] = {}
    monkeypatch.setattr("lifejacket.agents.base.get_client", lambda: current["client"])

    def report(
        scenario: str, answers: list[str], *, animals: int = 1, km_north: float = 0.0
    ) -> str:
        """File one complete report and return its incident id."""
        scripted = ScriptedLLMClient.scenario(scenario)
        for reply in scripted.script["assessment"]:
            reply["animal_count"] = animals
        current["client"] = scripted

        client = TestClient(app)
        incident_id = client.post("/intake/start", json={}).json()["incident_id"]
        client.post(
            f"/intake/{incident_id}/photo",
            files={"file": ("animal.jpg", b"\xff\xd8\xff fake jpeg", "image/jpeg")},
        )
        location = {"latitude": BEACH[0] + km_north * KM, "longitude": BEACH[1]}
        turn = client.post(f"/intake/{incident_id}/location", json=location).json()
        for answer in answers:
            turn = client.post(f"/intake/{incident_id}/reply", json={"text": answer}).json()
        assert turn["complete"], f"scenario '{scenario}' needs more answers"
        return incident_id

    report.scripted = lambda: current["client"]

    yield TestClient(app), report
    app.dependency_overrides.clear()


DOLPHIN_ANSWERS = ("dolphin", ["long beak", "yes"])
SEA_LION_ANSWERS = ("sea_lion", ["yes, green netting"])


def pin(client: TestClient, incident_id: str) -> dict:
    return next(p for p in client.get("/incidents").json() if p["incident_id"] == incident_id)


def test_one_dolphin_is_an_ordinary_incident(api):
    client, report = api
    incident = report(*DOLPHIN_ANSWERS)

    detail = client.get(f"/incidents/{incident}").json()
    assert detail["animal_count"] == 1
    assert detail["mass_stranding"] is None
    assert pin(client, incident)["in_mass_stranding"] is False


def test_one_report_of_several_dolphins_is_flagged_everywhere(api):
    client, report = api
    incident = report(*DOLPHIN_ANSWERS, animals=3)

    detail = client.get(f"/incidents/{incident}").json()
    assert detail["animal_count"] == 3
    assert detail["mass_stranding"]["animal_count"] == 3
    assert detail["mass_stranding"]["incident_ids"] == [incident]
    assert pin(client, incident)["in_mass_stranding"] is True

    # The writer was told, and the checker was given the same number.
    prompts = {call.agent: call.prompt for call in report.scripted().calls}
    assert "Animals in trouble: 3" in prompts["report"]
    assert "animals in trouble: 3" in prompts["guardrail"]


def test_a_second_reporter_reveals_the_scale_of_the_first_incident(api):
    """The first incident is already with a coordinator when this arrives."""
    client, report = api
    first = report(*DOLPHIN_ANSWERS)
    assert client.get(f"/incidents/{first}").json()["mass_stranding"] is None

    second = report(*DOLPHIN_ANSWERS, animals=4)

    duplicate = client.get(f"/incidents/{second}").json()
    assert duplicate["duplicate_of"] == first  # still one dispatch, not two

    original = client.get(f"/incidents/{first}").json()
    assert original["animal_count"] == 1  # what its own reporter said
    assert original["mass_stranding"]["animal_count"] == 4
    assert original["mass_stranding"]["report_count"] == 2
    assert pin(client, first)["in_mass_stranding"] is True

    # Opened from the duplicate, the same event is shown.
    assert duplicate["mass_stranding"] == original["mass_stranding"]


def test_two_separate_dolphins_along_the_beach_are_one_event(api):
    client, report = api
    first = report(*DOLPHIN_ANSWERS)
    second = report(*DOLPHIN_ANSWERS, km_north=1.5)

    a = client.get(f"/incidents/{first}").json()
    b = client.get(f"/incidents/{second}").json()
    assert b["duplicate_of"] is None  # too far apart to be the same animal
    assert a["mass_stranding"]["animal_count"] == 2
    assert a["mass_stranding"]["incident_ids"] == [first, second]
    assert a["mass_stranding"] == b["mass_stranding"]


def test_the_event_ends_when_the_other_incident_does(api):
    client, report = api
    first = report(*DOLPHIN_ANSWERS)
    second = report(*DOLPHIN_ANSWERS, km_north=1.5)
    client.patch(f"/incidents/{first}/status", json={"status": "resolved"})

    assert client.get(f"/incidents/{second}").json()["mass_stranding"] is None
    assert client.get(f"/incidents/{first}").json()["mass_stranding"] is None


def test_several_sea_lions_are_counted_but_not_a_mass_stranding(api):
    client, report = api
    incident = report(*SEA_LION_ANSWERS, animals=4)

    detail = client.get(f"/incidents/{incident}").json()
    assert detail["animal_count"] == 4
    assert detail["mass_stranding"] is None
    assert pin(client, incident)["in_mass_stranding"] is False
