from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lifejacket.drones.planner import demo_mission, plan_mission
from lifejacket.drones.sitl import mission_items, upload_mission


def message(kind, **values):
    return SimpleNamespace(
        get_type=lambda: kind, get_srcSystem=lambda: 1, get_srcComponent=lambda: 1, **values
    )


def connection(messages):
    result = Mock(target_system=1, target_component=1)
    result.recv_match.side_effect = messages
    return result


def test_translation_and_review_binding():
    plan = plan_mission(demo_mission())
    items = mission_items(plan, plan.plan_id)
    assert [items[i].command for i in (0, 1, -1)] == [16, 22, 21]
    assert items[0].latitude_int == 368000000
    with pytest.raises(ValueError, match="Plan changed"):
        mission_items(plan, "stale")
    changed = plan.model_copy(update={"waypoints": plan.waypoints[:-1]})
    with pytest.raises(ValueError, match="Plan changed"):
        mission_items(changed, plan.plan_id)


def test_upload_retries_and_ack():
    plan = plan_mission(demo_mission())
    items = mission_items(plan, plan.plan_id)
    requests = [message("MISSION_REQUEST_INT", seq=i) for i in range(len(items))]
    conn = connection([requests[0], *requests, message("MISSION_ACK", type=0)])
    upload_mission(conn, items)
    assert conn.mav.mission_item_int_send.call_count == len(items) + 1


@pytest.mark.parametrize(
    "responses,error",
    [
        ([message("MISSION_ACK", type=1)], RuntimeError),
        ([message("MISSION_ACK", type=0)], RuntimeError),
        ([message("MISSION_REQUEST_INT", seq=999)], RuntimeError),
        ([None], TimeoutError),
    ],
)
def test_upload_failure(responses, error):
    plan = plan_mission(demo_mission())
    with pytest.raises(error):
        upload_mission(connection(responses), mission_items(plan, plan.plan_id))


def test_broadcast_target_is_rejected_before_upload():
    plan = plan_mission(demo_mission())
    conn = connection([])
    conn.target_component = 0
    with pytest.raises(ValueError, match="heartbeat"):
        upload_mission(conn, mission_items(plan, plan.plan_id))
    conn.mav.mission_count_send.assert_not_called()
