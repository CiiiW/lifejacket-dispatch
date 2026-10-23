# Drone observations and centers outside the app

Drone observations have their own intake and coordinator queue. Reviewed real
evidence links into the existing incident system. Rescue centers can be
contacted using directory details without an account, a seeded responder row,
or a duty toggle. The prototype prepares a packet and records human-reported
contact outcomes; it never sends an email, places a call, or claims delivery.

## Coordinator workflow

1. Open **Drone observations** in the web responder console. Upload a JPEG,
   PNG or WebP photo (at most 8 MiB / 20 MP), identify it as real or simulation,
   and provide operator, capture time with timezone, observation coordinates,
   local county/coverage terms, and a description including uncertainty.
2. Review the image and metadata. Verify or reject with a named reviewer and
   note. Review history and revisions are retained. Names are coordinator-entered,
   consistent with the existing unauthenticated prototype; they are not verified identities.
   Optionally use **Find animals in photo**, select a numbered animal, then
   **Identify and assess selected animal** before verifying. Screening uses the
   chatbot's DetectionAgent, IdentificationAgent, AssessmentAgent, shared
   AnimalGroup enum/taxonomy, and deterministic severity scorer. All eight
   groups are supported by the contract: pinniped, cetacean, sea_turtle,
   seabird, other_marine, terrestrial, domestic_animal and unknown. Operator
   group hints are separate from model findings; neither establishes a diagnosis.
   No animals detected means an uncertain observation, not proof of absence.
   Each new screening resets the observation to pending and requires fresh review.
3. Check for an existing case for the animal, then attach the verified real
   evidence or create a new case in **assessing**. Species and severity remain
   unknown; the case is flagged for further assessment. Linking does not dispatch.
   Reviewed advisory findings, when present, accompany a new case; the human
   assessment flag remains set. Attaching to an existing case preserves its
   existing assessment and records the evidence/analysis reference in history.
   Simulation evidence cannot create a live case or external handoff. A SITL run
   cannot be cited as provenance for a real observation.
4. Review the directory's local area matches. A state name alone does not qualify
   a center. Capability text is shown for human review; a geographic match does
   not establish permission, availability or suitability for the animal.
5. Confirm coverage/capability and current listed contact details against an
   authoritative source. Record the source URL and verification notes. Prepare a
   packet containing case ID, observation time/location, uncertainty and evidence
   reference. Download the original photo if attaching it to a manually reviewed
   handoff. Contact details are a frozen directory snapshot; refresh the source
   directory if they are outdated before preparing the packet.
6. Contact the center through the verified channel, then record **contact
   attempted → acknowledged → accepted**, or **declined / escalated**. Accepted
   handoffs may later be recorded completed. Notes, channel and actor are kept
   with every transition. An attempted contact is not proof of delivery or acceptance.

External-contact records are visible in the observation queue and incident event
history. They do not manufacture app assignments, on-duty status, rescue arrival
or an ETA. A coordinator still manages the incident's response/outcome state.
An active handoff must be resolved or escalated before preparing one for a
different center, avoiding conflicting requests. Repeat case-link requests return
the existing case rather than creating a duplicate; stale mutations return 409.

## Implementation and storage

- New database tables: `drone_observations`, `external_handoffs`. Existing columns
  are unchanged; `init_db()` creates the new tables when the API starts.
- `drone_analyses` keeps append-only analysis snapshots with the model, actor,
  evidence hash, detection boxes, selected animal, identity candidates, condition
  flags, severity reasons, limitations and call metrics. Review records identify
  the snapshot reviewed. Existing observation/evidence columns are unchanged.
- `GET /drone-intake/animal-groups` serves the chatbot's enum/labels to the UI.
  `POST .../{observation_id}/detect` locates animals; `POST .../analyze` requires
  the current detection ID and a 1-based animal selection. Both require a named
  actor and current observation revision; linked observations cannot be rerun.
  Calls use existing Vertex ADC configuration, and fail with 503 if the model
  is unavailable, preserving evidence and the last successful result.
- Screening is one still-photo pass with zero follow-up questions. The selected
  animal is cropped with the chatbot's existing helper; multiple animals are
  never silently combined into one assessment. Missing capture-time weather
  and tide remain unknown rather than being replaced with current conditions.
  Results are advisory and held for human review regardless of model confidence.
  No aerial accuracy, diagnostic accuracy or confidence calibration is claimed.
- The directory follows the chatbot's exclusion of terrestrial/domestic groups.
  Other local area matches still need manual capability/contact verification.
- Original image bytes are retained with SHA-256 and validated by actual format,
  not the client MIME/filename. `DRONE_EVIDENCE_DIR` defaults to
  `var/drone-evidence`; persist this alongside the application database.
- Routes under `/drone-intake/observations`: upload/list, photo/download,
  review, case link, directory candidates, and handoff list/preparation.
- Contact transitions: `POST /drone-intake/handoffs/{handoff_id}/status`.
- Mutations use optimistic revisions and transactional case/event writes.
- Photos are uploaded by an operator. Live camera capture, video ingestion,
  tracking across frames, automatic patrol alerts, outbound notification adapters, and production
  coordinator authentication are not implemented by this increment.
- Existing public deployment has not been changed. Use the normal project
  deployment workflow after reviewing the code, privacy/access controls and
  persistent-volume configuration.

Reference for the reporting model: NOAA directs marine-animal distress reports
to the local stranding network: https://www.fisheries.noaa.gov/report . Directory
inclusion or app registration does not guarantee a center will respond.

Validation before photo-screening increment: 329 offline backend tests passed, including account-free handoffs,
review history, stale revision handling, idempotent case linking, image/time
validation, real-vs-SITL provenance checks and transition gating. TypeScript and
the production web export passed. The new workflow has not been deployed and
no live observations or external messages were created during these tests.

Photo-screening validation includes every shared animal group, multi-animal
selection, advisory findings retained on cases, mandatory human review, stale
detection/revision rejection, simulation restrictions, no-animal results and
model failures. Offline scripted responses verify orchestration, not visual
accuracy. Real aerial footage with expert annotations is still needed for
per-group accuracy and false-alert evaluation before patrol use.

After this increment: 342 offline backend tests passed; changed Python files
passed Ruff, and the responder console passed TypeScript and its web export.
