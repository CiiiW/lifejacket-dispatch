# Shared staging with Google sign-in

This is the prepared deployment path for a shared LifeJacket URL. It is **not
enabled yet**. The current private stack on `cpu-workbench` remains available
only through its loopback port, `18080`.

The proxy configuration was smoke-tested on the VM against the running
application: missing and wrong origin credentials returned `403`; the correct
credential returned API health `200`; both proxy hops served the frontend and
all 217 public NOAA density cells. Missing or malformed secrets stopped startup,
and both nginx configurations passed `nginx -t`. The checks used temporary
containers with no published host ports and removed them afterward. Cloud Run,
IAP sign-in, and VPC connectivity still require deployment and verification.

The shared deployment puts a small nginx service on Cloud Run with IAP enabled.
It forwards both the frontend and `/api` over Direct VPC egress to an origin
proxy on the existing VM. PostgreSQL, photos, and the imported NOAA aggregates
stay on the VM. Every request to the origin requires a random secret, including
requests from other machines in the VPC. The origin strips that secret before
forwarding to the application.

Google sign-in controls access to the whole staging application. Every allowed
team member can use the application's existing writable endpoints; this does
not add separate responder/admin roles or an audit trail.

## Verified project settings and permission blocker

The project is `spring-2026-lifejacket` (`430598861806`), region `us-central1`.
The VM is `cpu-workbench` in `us-central1-a`, private IP `10.10.0.2`. Its network
is `adsp-vpc`, subnet `adsp-us-central1` (`10.10.0.0/24`). Artifact Registry
already has a Docker repository named `docker-repo`. Cloud Run and IAP APIs are
enabled.

An effective permission check for `charlottez@uchicago.edu` found deployment,
image upload, service-account creation/attachment, and firewall creation
permissions. These policy permissions were absent:

| Permission | Needed for |
| --- | --- |
| `run.services.setIamPolicy` | Let the IAP service agent invoke this service |
| `iap.webServices.setIamPolicy` | Allow the named team Google accounts through IAP |
| `secretmanager.secrets.setIamPolicy` | Let only the proxy identity read the origin secret |

A project administrator must perform those policy changes, or grant the
appropriate permissions on the specific resources. Editor access alone did
not include them. An earlier SSH-over-IAP attempt also returned `4033: not
authorized`; SSH tunnel access and IAP web app access are separate permissions.

## Prepare and test the origin on the VM

From `/home/jupyter/lifejacket-staging`, with the current private stack running:

```bash
python3 deploy/team/prepare_origin.py
docker compose -p deploy --env-file deploy/staging.env --env-file deploy/team.env \
  -f deploy/compose.staging.yaml -f deploy/compose.team.yaml up -d origin
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18081/api/health
```

The unauthenticated request must return `403`. `deploy/team.env` contains the
generated secret, is created with mode `600`, and is ignored by Git and Docker.
The helper refuses to replace an existing file, so rerunning it cannot silently
rotate the credential. Keep the bind address at `127.0.0.1` during preparation.

Create a Secret Manager secret named `lifejacket-staging-origin` in the project.
From the VM, upload the value without displaying it (the active gcloud identity
must have permission to add a version):

```bash
set -o pipefail
python3 -c 'from pathlib import Path; print(next(line.split("=", 1)[1] for line in Path("deploy/team.env").read_text().splitlines() if line.startswith("ORIGIN_TOKEN=")), end="")' \
  | gcloud secrets versions add lifejacket-staging-origin \
      --project=spring-2026-lifejacket --data-file=-
```

Record the version number returned by this command. Do not copy the environment
file into an image, commit it, or put the secret directly in a shell command.

## Administrator: network and proxy identity

Create a dedicated service account with no project-wide roles:

```bash
gcloud iam service-accounts create lifejacket-staging-proxy \
  --project=spring-2026-lifejacket --display-name='LifeJacket staging proxy'
gcloud secrets add-iam-policy-binding lifejacket-staging-origin \
  --project=spring-2026-lifejacket \
  --member=serviceAccount:lifejacket-staging-proxy@spring-2026-lifejacket.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
gcloud compute instances add-tags cpu-workbench \
  --project=spring-2026-lifejacket --zone=us-central1-a \
  --tags=lifejacket-staging-origin
```

Inspect existing and inherited firewall policies first. The following new rules
limit the VM origin to the Cloud Run subnet and limit the proxy's private
egress to that origin. Direct VPC egress uses dynamic addresses from the subnet;
use its source range for VM ingress. The secret supplies the origin's request
authentication. No rule opens the VM origin to the internet.

```bash
gcloud compute firewall-rules create lifejacket-origin-from-run-subnet \
  --project=spring-2026-lifejacket --network=adsp-vpc --direction=INGRESS \
  --priority=800 --action=ALLOW --rules=tcp:18081 \
  --source-ranges=10.10.0.0/24 --target-tags=lifejacket-staging-origin
gcloud compute firewall-rules create lifejacket-origin-deny-other \
  --project=spring-2026-lifejacket --network=adsp-vpc --direction=INGRESS \
  --priority=900 --action=DENY --rules=tcp:18081 \
  --source-ranges=0.0.0.0/0 --target-tags=lifejacket-staging-origin
gcloud compute firewall-rules create lifejacket-edge-to-origin \
  --project=spring-2026-lifejacket --network=adsp-vpc --direction=EGRESS \
  --priority=800 --action=ALLOW --rules=tcp:18081 \
  --destination-ranges=10.10.0.2/32 --target-tags=lifejacket-staging-edge
gcloud compute firewall-rules create lifejacket-edge-deny-other-private \
  --project=spring-2026-lifejacket --network=adsp-vpc --direction=EGRESS \
  --priority=900 --action=DENY --rules=all \
  --destination-ranges=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 \
  --target-tags=lifejacket-staging-edge
```

After the rules are verified, change **only** `TEAM_BIND_IP` in the VM's private
`deploy/team.env` to `10.10.0.2` and rerun the Compose command above. Keep the
original application port on loopback. If this VM is replaced or its private
address changes, update the origin bind, egress destination, and Cloud Run URL
together.

## Administrator: deploy the shared service

The tested proxy image is already built in the project's existing Artifact
Registry repository. Its immutable reference is:

```bash
TEAM_IMAGE='us-central1-docker.pkg.dev/spring-2026-lifejacket/docker-repo/lifejacket-team-proxy@sha256:79972624798d22be9f4c3706a590b28367b6c7aa5614a9d382d846bff04f817c'
```

From a checkout of `charlotte`, build the small proxy image. The build context
contains only proxy source; it excludes the application and private dataset.
This rebuild is only needed after changing the proxy source:

```bash
TEAM_IMAGE="us-central1-docker.pkg.dev/spring-2026-lifejacket/docker-repo/lifejacket-team-proxy:$(git rev-parse --short HEAD)"
gcloud builds submit deploy/team --project=spring-2026-lifejacket --tag="$TEAM_IMAGE"
```

Deploy with IAP enabled at creation. Replace `VERSION_NUMBER` with the recorded
secret version. The startup probe checks the real upstream API, allowing time
for Direct VPC egress to become ready. Cloud Run scales to zero when idle;
Artifact Registry, builds, requests, and networking can incur charges.

```bash
gcloud run deploy lifejacket-staging --project=spring-2026-lifejacket \
  --region=us-central1 --image="$TEAM_IMAGE" --port=8080 \
  --service-account=lifejacket-staging-proxy@spring-2026-lifejacket.iam.gserviceaccount.com \
  --no-allow-unauthenticated --iap --ingress=all \
  --network=adsp-vpc --subnet=adsp-us-central1 --vpc-egress=private-ranges-only \
  --network-tags=lifejacket-staging-edge \
  --set-env-vars=ORIGIN_URL=http://10.10.0.2:18081 \
  --set-secrets=ORIGIN_TOKEN=lifejacket-staging-origin:VERSION_NUMBER \
  --cpu=1 --memory=256Mi --min-instances=0 --max-instances=2 \
  --concurrency=20 --timeout=300 \
  --startup-probe=httpGet.path=/api/health,httpGet.port=8080,periodSeconds=10,timeoutSeconds=5,failureThreshold=24
gcloud run services add-iam-policy-binding lifejacket-staging \
  --project=spring-2026-lifejacket --region=us-central1 \
  --member=serviceAccount:service-430598861806@gcp-sa-iap.iam.gserviceaccount.com \
  --role=roles/run.invoker
```

For **each explicitly approved Google email address**, add service-specific IAP
access. Replace `TEAM_MEMBER_EMAIL`; do not use `allUsers`, `allAuthenticatedUsers`,
or an entire university domain:

```bash
gcloud iap web add-iam-policy-binding --project=spring-2026-lifejacket \
  --region=us-central1 --resource-type=cloud-run --service=lifejacket-staging \
  --member=user:TEAM_MEMBER_EMAIL --role=roles/iap.httpsResourceAccessor
```

The Google-managed OAuth client supports accounts inside the project's
organization. If a team account belongs to another organization, an
administrator must configure a custom OAuth client using the Cloud Run/IAP
console before granting that account access.

## Acceptance and operations

- Confirm `gcloud run services describe lifejacket-staging` reports IAP enabled
  and the Run Invoker policy contains no public principal.
- Open the service URL in a signed-out browser: expect Google sign-in or access
  denial. Repeat against `/api/health` and `/api/historical-strandings/density`.
- Sign in as an allowed team member: the frontend, API health, and 217 public
  historical density cells should load. Test a signed-in account outside the
  allowlist and confirm it is denied.
- Requests to the VM origin without the secret must return `403`; the external
  VM address must not accept connections on port `18081`.
- Test the existing responder workflow with synthetic incidents. All team users
  share the same staging database. AI intake still needs its separate Google
  application credentials, as described in [private staging](staging.md).
- The VM must be running for the shared URL to serve the application. Workbench
  idle shutdown, VM replacement, or a private-IP change can interrupt service.
  Backups and schema migrations are still outstanding. Move application storage
  to managed services before treating this as an always-available deployment.
- To withdraw shared access, remove team IAP bindings or disable the Cloud Run
  service. Stop the origin container and remove these dedicated firewall rules
  when retiring the bridge. Preserve the existing database/photo volumes.

References: [IAP on Cloud Run](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run),
[Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc).
