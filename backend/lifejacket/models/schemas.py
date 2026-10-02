"""Domain vocabulary for LifeJacket, as Pydantic models.

These classes are the contract every other module speaks. The agents return
them, the API serialises them, the database stores them. If you want to
understand the system, read this file first.

Why Pydantic rather than plain dataclasses: the LLM agents return JSON, and
Pydantic validates that JSON at the boundary. A model that hallucinates a
confidence of 1.7 or an unknown mobility value fails loudly here rather than
silently corrupting a severity score downstream.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations
#
# String enums (not ints) so that database rows and JSON payloads stay readable
# when a human inspects them during debugging.
# ---------------------------------------------------------------------------


class IncidentStatus(str, Enum):
    """Lifecycle of an incident, in the order it normally progresses."""

    INTAKE = "intake"  # reporter is still answering questions
    IDENTIFYING = "identifying"  # identification agent is working
    ASSESSING = "assessing"  # assessment agent is deciding what to do
    AWAITING_DISPATCH = "awaiting_dispatch"  # report written, no responder yet
    DISPATCHED = "dispatched"  # a responder has been notified
    ACCEPTED = "accepted"  # a responder has claimed it
    EN_ROUTE = "en_route"
    ON_SCENE = "on_scene"
    RESOLVED = "resolved"  # responder closed it out with notes
    CANCELLED = "cancelled"  # duplicate, false report, or animal left
    GUIDANCE_ONLY = "guidance_only"  # healthy animal; reporter advised, no dispatch


class AnimalGroup(str, Enum):
    """Coarse taxonomic bucket.

    Dispatch routing cares about this more than exact species, because rescue
    organisations are permitted and equipped by group (a pinniped team is not
    necessarily a cetacean team).

    This classifies ANY non-human animal, not only marine ones -- a photo of
    a coyote or a pet dog gets a real, specific group here, not a shrug.
    `data/rescue_centers.csv` is currently a West Coast Marine Mammal
    Stranding Network directory only, so TERRESTRIAL and DOMESTIC_ANIMAL
    reports are identified and triaged correctly but `dispatch/matching.py`
    has no organisation in that directory to offer for them yet (see its
    module docstring). That is a gap in the *data*, not in the
    identification or assessment logic: adding a wildlife-rehab directory
    later needs no change here.
    """

    PINNIPED = "pinniped"  # seals, sea lions, walruses
    CETACEAN = "cetacean"  # whales, dolphins, porpoises
    SEA_TURTLE = "sea_turtle"
    SEABIRD = "seabird"
    OTHER_MARINE = "other_marine"  # sea otters, manatees, fish, jellyfish, ...
    TERRESTRIAL = "terrestrial"  # any wild land animal: deer, raccoon, hawk, snake, ...
    DOMESTIC_ANIMAL = "domestic_animal"  # a pet or livestock animal, not wildlife
    UNKNOWN = "unknown"


class MobilityConcern(str, Enum):
    NONE = "none"
    LIMITED = "limited"
    IMMOBILE = "immobile"
    UNKNOWN = "unknown"


class SeverityLevel(str, Enum):
    """Triage bands. These drive who gets notified and how loudly."""

    CRITICAL = "critical"  # immediate escalation, professional team
    RESPOND = "respond"  # rescue centre notified
    MONITOR = "monitor"  # trained volunteer observes
    GUIDANCE = "guidance"  # no response needed; reporter is advised


class ResponderKind(str, Enum):
    ORGANISATION = "organisation"  # a stranding network centre
    VOLUNTEER = "volunteer"  # a trained individual


class AssignmentStatus(str, Enum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EN_ROUTE = "en_route"
    ON_SCENE = "on_scene"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Location and environmental context
# ---------------------------------------------------------------------------


class GeoPoint(BaseModel):
    """A latitude/longitude pair, optionally with a human-readable place name."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_name: str | None = None
    # How we learned the location: device_gps, photo_exif, manual_entry.
    # Recorded because accuracy varies enormously between these.
    source: str = "device_gps"
    accuracy_meters: float | None = None


class WeatherConditions(BaseModel):
    """Current and near-term weather at the incident location."""

    temperature_c: float | None = None
    wind_speed_mph: float | None = None
    wind_gust_mph: float | None = None
    precipitation_probability: float | None = Field(default=None, ge=0, le=1)
    visibility_miles: float | None = None
    condition: str | None = None  # free text, e.g. "fog", "light rain"
    sunset_local: datetime | None = None  # responders need daylight
    retrieved_at: datetime | None = None


class TideConditions(BaseModel):
    """Tide state, which decides whether an animal is about to be refloated.

    This is the single most operationally important piece of context for a
    stranded marine mammal: a rising tide may free the animal without any
    intervention, while a falling tide strands it further up the beach and
    starts a heat-stress clock.
    """

    station_id: str | None = None
    station_name: str | None = None
    station_distance_km: float | None = None
    water_level_m: float | None = None
    # "rising" or "falling" -- derived from the next high/low event.
    trend: str | None = None
    next_high_tide: datetime | None = None
    next_low_tide: datetime | None = None
    # Wave context matters for whether volunteers can safely approach.
    wave_height_m: float | None = None
    sea_surface_temperature_c: float | None = None
    retrieved_at: datetime | None = None


class EnvironmentalContext(BaseModel):
    """Everything the assessment agent knows about the world around the animal.

    Assembled by `lifejacket.context.environment.gather_context`. Every field is
    optional: a failed weather API call must degrade the recommendation, never
    block a rescue.
    """

    location: GeoPoint
    weather: WeatherConditions | None = None
    tide: TideConditions | None = None
    is_coastal: bool = True
    local_time: datetime | None = None
    # Populated when an API call fails, so the report can say "tide unknown"
    # rather than implying the tide was checked and found unremarkable.
    unavailable: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------


class TaxonRank(str, Enum):
    """How specifically an animal has been identified, finest first.

    Ordering matters: `taxonomy.resolve_taxon` walks these top to bottom and
    stops at the first rank it is confident about.
    """

    SPECIES = "species"  # "Harbor seal" (Phoca vitulina)
    GENUS = "genus"  # "Bottlenose dolphins" (Tursiops)
    FAMILY = "family"  # "Oceanic dolphins" (Delphinidae)
    GROUP = "group"  # "Whale, dolphin, or porpoise" (our AnimalGroup)
    UNKNOWN = "unknown"


class SpeciesCandidate(BaseModel):
    """One hypothesis about what the animal is, with its place in the taxonomy.

    Genus and family are carried on every candidate so that probability can be
    pooled up the tree. If the agent says common dolphin 0.48 and bottlenose
    dolphin 0.41, neither species is confident -- but both are family
    Delphinidae, so "dolphin" is 0.89 confident, which is enough to route on.
    """

    common_name: str
    scientific_name: str | None = None
    confidence: float = Field(ge=0, le=1)
    animal_group: AnimalGroup = AnimalGroup.UNKNOWN

    genus: str | None = None  # e.g. "Tursiops"
    genus_common_name: str | None = None  # e.g. "bottlenose dolphins"
    family: str | None = None  # e.g. "Delphinidae"
    family_common_name: str | None = None  # e.g. "oceanic dolphins"


class TaxonResolution(BaseModel):
    """The answer the system settles on: the finest rank it is confident about.

    Computed in Python by `lifejacket.taxonomy.resolve_taxon` from the agent's
    per-species probabilities -- the model is never asked to pick the rank
    itself, so the rule is the same on every incident and can be unit-tested.
    """

    rank: TaxonRank
    #: Human label shown in reports and on the map, e.g. "Oceanic dolphins".
    name: str
    #: e.g. "Delphinidae" or "Phoca vitulina".
    scientific_name: str | None = None
    #: Probability the animal belongs to this taxon (sum over `members`).
    confidence: float = Field(ge=0, le=1)
    animal_group: AnimalGroup = AnimalGroup.UNKNOWN
    #: True when `confidence` reached the configured threshold.
    meets_threshold: bool = False
    #: The species inside this taxon, with their individual probabilities.
    #: This is where "common 0.48 / bottlenose 0.41" is reported.
    members: list[SpeciesCandidate] = Field(default_factory=list)


class ClarifyingQuestion(BaseModel):
    """A question the agent wants to put to the reporter.

    `options` is populated when the answer should be a tap rather than typing.
    On a phone, at a windy beach, with one hand holding the phone, multiple
    choice is far more reliable than free text.
    """

    question: str
    # Why this question discriminates -- shown to the team during evaluation,
    # not to the reporter. Keeps prompt debugging tractable.
    rationale: str | None = None
    options: list[str] = Field(default_factory=list)
    allows_free_text: bool = True
    # What this question is probing, e.g. "ear_flaps", "body_covering".
    # Used to avoid asking the same discriminating feature twice.
    feature: str | None = None


class IdentificationResult(BaseModel):
    """Output of Agent 1 (identification), plus the system's resolution of it.

    `candidates` is what the model said (per-species probabilities).
    `resolution` is what the system concluded from those probabilities -- see
    `lifejacket.taxonomy`. Downstream code should read `display_name` and
    `animal_group` rather than picking through candidates itself.
    """

    candidates: list[SpeciesCandidate] = Field(default_factory=list)
    resolution: TaxonResolution | None = None
    next_question: ClarifyingQuestion | None = None
    #: The agent's view of whether a question could still separate its top
    #: candidates from a safe distance. False for, e.g., common vs bottlenose
    #: dolphin in a distant photo -- the system then settles for the genus or
    #: family instead of spending questions that cannot help.
    species_distinguishable: bool = True
    # Set when the photo itself is the problem (too dark, too far, blurry).
    needs_new_photo: bool = False
    photo_quality_note: str | None = None
    reasoning: str | None = None

    @property
    def top_candidate(self) -> SpeciesCandidate | None:
        """Highest-confidence species, or None if the agent returned nothing."""
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda c: c.confidence)

    @property
    def is_confident(self) -> bool:
        """Whether the resolved taxon cleared the confidence threshold."""
        return bool(self.resolution and self.resolution.meets_threshold)

    @property
    def display_name(self) -> str:
        """What to call the animal: "Harbor seal", "Oceanic dolphins", ..."""
        if self.resolution:
            return self.resolution.name
        top = self.top_candidate
        return top.common_name if top else "unidentified animal"

    @property
    def confidence(self) -> float:
        if self.resolution:
            return self.resolution.confidence
        top = self.top_candidate
        return top.confidence if top else 0.0

    @property
    def animal_group(self) -> AnimalGroup:
        """The group that routes dispatch. Reliable even at family level."""
        if self.resolution:
            return self.resolution.animal_group
        top = self.top_candidate
        return top.animal_group if top else AnimalGroup.UNKNOWN


class InjuryAssessment(BaseModel):
    """Structured injury and distress flags.

    These are deliberately flat booleans rather than free text: the severity
    scorer needs to multiply them by weights, and a human coordinator needs to
    scan them in under two seconds.
    """

    injury_present: bool = False
    confidence: float = Field(default=0.0, ge=0, le=1)
    wound: bool = False
    bleeding: bool = False
    entanglement: bool = False  # net, line, plastic -- needs a cutting team
    swelling: bool = False
    abnormal_posture: bool = False
    respiratory_distress: bool = False
    unresponsive: bool = False
    emaciated: bool = False
    mobility_concern: MobilityConcern = MobilityConcern.UNKNOWN
    summary: str | None = None


class SituationHazards(BaseModel):
    """Threats from the surroundings rather than from the animal's condition."""

    near_people: bool = False
    near_dogs: bool = False
    near_road: bool = False
    in_surf: bool = False  # at risk of being swept out
    risk_of_being_stranded_further: bool = False
    notes: str | None = None


class AssessmentResult(BaseModel):
    """Output of Agent 2 (assessment): what is wrong and what should happen."""

    animal_group: AnimalGroup = AnimalGroup.UNKNOWN
    injury: InjuryAssessment = Field(default_factory=InjuryAssessment)
    hazards: SituationHazards = Field(default_factory=SituationHazards)

    severity_level: SeverityLevel = SeverityLevel.MONITOR
    severity_score: float = 0.0
    severity_confidence: float = Field(default=0.0, ge=0, le=1)

    recommended_action: str = ""
    # Short imperative steps the reporter should take right now.
    reporter_instructions: list[str] = Field(default_factory=list)
    # The safety line that must always be shown, e.g. keep 50 yards back.
    safety_guidance: str = ""

    # How the tide/weather changed the recommendation. Explicit because an
    # unexplained urgency bump erodes coordinator trust in the system.
    environmental_rationale: str | None = None
    time_sensitivity_hours: float | None = None

    is_confident: bool = True
    next_question: ClarifyingQuestion | None = None
    # True when a human coordinator must approve before anyone is dispatched.
    requires_human_review: bool = True


class IncidentReport(BaseModel):
    """Output of Agent 3 (report): the handoff artefact sent to responders.

    Written for someone reading a push notification while putting on boots.
    `headline` must stand alone.
    """

    headline: str  # e.g. "Entangled sea lion, Moss Landing, falling tide"
    summary: str  # 2-4 sentences
    # Ordered, concrete, each independently actionable.
    recommended_actions: list[str] = Field(default_factory=list)
    access_notes: str | None = None  # how to physically reach the animal
    equipment_suggestions: list[str] = Field(default_factory=list)
    hazard_warnings: list[str] = Field(default_factory=list)
    # Facts the agent could not establish, stated as gaps rather than omitted.
    unknowns: list[str] = Field(default_factory=list)
    reporter_contact_note: str | None = None


# ---------------------------------------------------------------------------
# Responders and dispatch
# ---------------------------------------------------------------------------


class RescueCenter(BaseModel):
    """A row of the stranding-network directory in `data/rescue_centers.csv`."""

    center_name: str
    hotline: str | None = None
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    response_area: str | None = None  # free-text county list
    response_type: str | None = None  # free-text capability list
    source: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class DispatchCandidate(BaseModel):
    """A scored responder option, ready for a coordinator to approve."""

    responder_id: str
    name: str
    kind: ResponderKind
    score: float = Field(ge=0, le=1)
    distance_km: float | None = None
    eta_minutes: float | None = None
    # Human-readable justification, e.g. "covers Monterey County; permitted for
    # cetacean response; 12 km away". Surfaced in the UI next to the score so
    # the coordinator is approving a reason, not a number.
    rationale: str = ""
    matched_capabilities: list[str] = Field(default_factory=list)
    contact_phone: str | None = None
    contact_email: str | None = None


class DuplicateMatch(BaseModel):
    """A previously-reported incident that may be the same animal."""

    incident_id: str
    confidence: float = Field(ge=0, le=1)
    distance_km: float
    hours_apart: float
    same_species: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class ChatRole(str, Enum):
    REPORTER = "reporter"
    AGENT = "agent"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str
    created_at: datetime = Field(default_factory=datetime.now)
    # Which agent produced this, for transcript analysis during evaluation.
    agent_name: str | None = None
    # Set on agent questions so the reply can be tied back to the feature probed.
    feature: str | None = None
    options: list[str] = Field(default_factory=list)


class ConversationStage(str, Enum):
    """Where the chatbot is in the conversation."""

    AWAITING_PHOTO = "awaiting_photo"
    AWAITING_LOCATION = "awaiting_location"
    IDENTIFYING = "identifying"
    ASSESSING = "assessing"
    COMPLETE = "complete"


# ---------------------------------------------------------------------------
# The aggregate: an incident
# ---------------------------------------------------------------------------


class Incident(BaseModel):
    """One report of one animal, from first photo to responder sign-off.

    This is the object the responder console lists on its map and the object the
    reporter watches for an ETA.
    """

    model_config = ConfigDict(use_enum_values=False)

    incident_id: str
    status: IncidentStatus = IncidentStatus.INTAKE
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    reporter_id: str | None = None
    reporter_phone: str | None = None
    location: GeoPoint | None = None
    photo_ids: list[str] = Field(default_factory=list)

    identification: IdentificationResult | None = None
    assessment: AssessmentResult | None = None
    report: IncidentReport | None = None
    environment: EnvironmentalContext | None = None

    dispatch_candidates: list[DispatchCandidate] = Field(default_factory=list)
    assigned_responder_id: str | None = None
    duplicate_of: str | None = None

    # Free-form bag for evaluation metadata (prompt version, latencies, token
    # counts). Kept separate from the fields above so research instrumentation
    # never changes the production contract.
    metrics: dict[str, Any] = Field(default_factory=dict)


class IncidentLogEntry(BaseModel):
    """A responder's write-up after the incident is closed.

    This is the training data for everything the project does next: it is the
    only place where ground truth about the animal and the outcome is recorded.
    """

    incident_id: str
    responder_id: str
    created_at: datetime = Field(default_factory=datetime.now)

    # What the animal actually turned out to be. Compared against
    # `identification` to measure real-world agent accuracy.
    confirmed_species: str | None = None
    confirmed_animal_group: AnimalGroup | None = None
    outcome: str | None = None  # rescued, released, deceased, not_found, no_action
    actions_taken: str | None = None
    notes: str | None = None
    # Did the generated report match what they found on the beach?
    report_was_accurate: bool | None = None
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
