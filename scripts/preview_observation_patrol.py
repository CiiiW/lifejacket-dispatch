"""Run the shared planner for the isolated, loopback-only drone request demo."""

import json
import sys

from lifejacket.drones.observation_patrol import PatrolRequest, observation_patrol
from lifejacket.models.drone_requests import ObservationSearchArea

if __name__ == "__main__":
    data = json.loads(sys.argv[1])
    preview = observation_patrol(
        ObservationSearchArea.model_validate(data["area"]),
        PatrolRequest(
            plan_id=data.get("plan_id"),
            send_to_simulator=data.get("send_to_simulator", False),
        ),
        "Demo coordinator",
    )
    print(preview.model_dump_json())
