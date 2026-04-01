# Security Model

## Runtime authentication

- Runtime requests are authenticated using Dex-issued JWTs.
- Verification is done against `DEX_JWKS_URL`.
- Optional checks: `DEX_ISSUERS`, `DEX_AUDIENCE`, `DEX_EMAIL_ALLOWLIST`, `DEX_REQUIRED_GROUP`.
- Runtime access to contexts is restricted to resources owned by the authenticated Dex principal.

## Admin authentication

- Admin UI/API uses local username/password and signed session cookie.
- Intended for private internal usage.

## Secrets strategy

- Store bot tokens and MTProto session artifacts in Google Secret Manager.
- Sync bootstrap/admin secrets to Kubernetes through External Secrets.
- Keep only secret references in DB.
- Tenant self-service connection creation stores imported bot tokens and session strings as gateway-managed secrets.

Supported secret refs in v1:

- `managed://name` (gateway-managed encrypted secret store)
- `env://VAR_NAME`
- `gsm://projects/<project>/secrets/<name>/versions/<version>`

## Network posture

- Dedicated namespace: `telegram-gateway`.
- Service type `ClusterIP` only.
- No public ingress manifest.
- NetworkPolicy default deny; explicitly allows limited ingress and egress.
- If Telegram webhooks are enabled, configure `WEBHOOK_SHARED_SECRET` and send the matching `X-Telegram-Bot-Api-Secret-Token` header.

## Operational recommendations

- Rotate admin credentials and bot/session secrets regularly.
- Replace SQLite with Postgres before scaling replicas.
- Add TLS/mTLS at mesh or ingress-gateway layer for intra-cluster hops where needed.
