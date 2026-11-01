# Managed sign-in and organization memberships

Implemented backend foundation: `GET /access/me` validates a Firebase Authentication / Google Cloud Identity Platform ID token and resolves a current database-backed access context. This endpoint is authenticated. Existing incident, responder, media, transcript and mutation routes are still legacy routes and are **not protected by this increment**. Keep the service private; do not present this as a completed RBAC rollout.

## Configuration and rollout

1. Choose the managed identity project and enabled sign-in provider, authorized app domains and web/mobile client configuration. These external settings are not created by this code. Workbench login and Vertex credentials are not end-user sign-in.
2. Install backend requirements. Use workload Application Default Credentials on GCP with the permissions needed for managed user/revocation lookups; do not export service-account keys. Verify permissions against the selected project's configuration.
3. Back up the intended database, then run `PYTHONPATH=backend python scripts/network_access_admin.py init` against that database. This creates only the four additive access tables and grants nobody access. Do not run the default database configuration without checking the target first.
4. Configure `FIREBASE_AUTH_PROJECT_ID` and explicitly enable `NETWORK_AUTH_ENABLED=true` only for the intended private environment. The default is disabled. Emulator tokens are refused.
5. A client obtains a provider ID token and sends `Authorization: Bearer <token>` to `/access/me`. Missing/invalid tokens return 401; disabled/unconfigured or unavailable verification returns 503. The SDK checks signature, expiry, project issuer/audience and revocation/disabled users on every request.
6. First verified sign-in creates a personal reporter account, identified by issuer plus provider subject. Email matches, email domains, client role fields and token custom role claims grant no professional access. A verified email is also required before using professional membership.
7. Independently verify the actual organization, account holder and authority. A trusted operator can use `approve-organization` and `approve-member` with explicit state scope and `--verified-by`. Use each command's `--help` for arguments. The account ID comes from the person's authenticated session, not an arbitrary email search. There is no public grant endpoint.
8. Clients may select an approved organization using `X-LifeJacket-Organization`. Without it the session is personal reporter mode. NOAA membership requires an approved NOAA organization; center coordinators and rescuers require approved rescue-center membership and explicit state subsets. A failed/disabled/revoked/unapproved context is denied.
9. `revoke-member` records an audit event and removes professional access on the next request, including with an unchanged valid provider token. Disabling a local account denies personal and professional sessions. Provider revocation is checked separately by the SDK.

No real staff accounts or professional memberships have been provisioned. No cloud identity service/provider or IAM policy has been activated by this implementation. `verified_by` is an operator attestation, not independent identity evidence; protect database/CLI access and retain the actual review record through the organization's process.

## Data and remaining integration

Tables: `access_users`, `access_organizations`, `access_memberships`, `access_audit`. No passwords, ID tokens or phone/location data are stored by this slice. Session responses are private/no-store and contain only the caller's account and approved organization choices. Audit rows record account creation, organization/membership approval and membership revocation; database operators remain trusted.

Next: connect the frontend provider sign-in, map legacy responder identities and reporter ownership to authenticated account IDs, normalize verified case state, and apply shared authorization dependencies plus field projection to **every** case/list/detail/media/transcript/contact/mutation route. Add cross-user integration tests before exposing the network dashboard. NOAA nationwide reads and center state visibility are policy foundations, not live dashboard behavior yet. Existing California intake and isolated drone demos remain unchanged.

Official references: [Verify ID tokens](https://firebase.google.com/docs/auth/admin/verify-id-tokens), [Manage sessions and check revocation](https://firebase.google.com/docs/auth/admin/manage-sessions).
