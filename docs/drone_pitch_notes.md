# Drone Integration — Pitch Notes

Talking points, not a script — adapt per slide.

## Slide: The gap drones close

- Identification and injury assessment today run off one bystander photo.
- README already documents the cost: ~54% species accuracy, injury flags
  never evaluated against labelled data.
- A drone at the scene is a second, better-controlled visual source —
  closer range, multiple angles, no change to the identification/assessment
  agents themselves.

## Slide: This is the autonomy piece, not just hardware

- The brief was to make the project read as more AI/autonomy-forward.
- We're not bolting on a gadget — the drone dispatch decision is written as
  a deterministic autopilot, the same pattern the backend already uses for
  triage severity: the model decides what it observes, a function decides
  what that means and whether the flight happens.
- That split is why a coordinator can see *why* a flight launched or
  didn't — "the model said so" isn't reviewable, this is.

## Slide: Three integration points

1. Multi-angle visual input — drone video frames feed the existing
   identification/assessment pipeline as an additional source.
2. Deterministic dispatch decision — distance, weather, time of day,
   airspace all feed a bounded flight plan or a documented "not viable."
3. Proactive scouting — patrol flights for early detection and mass-
   stranding head counts. Flagged as a stretch goal, not required for v1.

## Slide: Safety boundary

- MMPA sets minimum approach distances for marine mammals — this is a
  hard constraint in the flight plan, not a tunable default, the same way
  entanglement and bleeding wounds hard-rule to critical in triage today.
- Extends the system's existing rule that nothing dispatches without a
  human: a drone flight needs coordinator approval before launch, same as
  responder assignment does now.

## Slide: What we're asking for feedback on

- Is the deterministic-dispatch framing the right level of "autonomy," or
  does the course want something closer to live flight-path planning?
- Where should drone base / availability data come from for a demo?
- Live hardware vs. a scripted stand-in for the demo — same pattern as the
  model's own test stand-in — which is appropriate for scope/timeline?
