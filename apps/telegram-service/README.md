# Telegram Service Gateway

Python FastAPI gateway and admin dashboard for managing multiple Telegram bot/user connections and messaging contexts.

## Highlights

- Multi-connection model (`bot` and `user`) with per-connection secret references.
- Messaging contexts with policy modes:
  - `send_only`
  - `send_receive`
  - `receive_only`
- Runtime messaging for both bot and user contexts.
- Built-in one-time-password lifecycle endpoints (`issue` + `verify`).
- Bot onboarding links with `/start <token>` chat binding and QR deep links.
- Runtime API secured by Dex-issued JWT verification (OIDC login stays external to this service).
- Dex-authenticated self-service API for tenant-owned connections, contexts, and onboarding links.
- Admin panel for connection/context/secrets metadata management.
- Secret model designed for GSM + External Secrets (DB stores references only, not raw bot tokens/sessions).
- Kubernetes-first deployment in dedicated namespace and `ClusterIP` service.

## Repo layout

- `src/telegram_service/main.py`: app entrypoint.
- `src/telegram_service/routers/admin_api.py`: admin/config API.
- `src/telegram_service/routers/config_api.py`: dedicated configuration endpoint group.
- `src/telegram_service/routers/runtime_gateway.py`: runtime gateway API.
- `src/telegram_service/routers/self_service_api.py`: tenant self-service API.
- `src/telegram_service/routers/admin_ui.py`: admin dashboard routes.
- `k8s/`: namespace/deployment/service/network policies/examples.
- `docker-compose.yml`: local stack.

## Local run

1) Copy envs:

```bash
cp .env.example .env.local
```

2) Start with Docker Compose:

```bash
docker compose up --build
```

3) Open admin UI:

- `http://localhost:8000/admin/login`
- Onboarding tab: `http://localhost:8000/admin/onboarding`

Default credentials come from `.env.local` (`ADMIN_USERNAME`, `ADMIN_PASSWORD`).

## Runtime auth (Dex JWT)

Runtime gateway endpoints (`/gateway/*`) validate bearer tokens against your existing Dex JWKS:

- `DEX_JWKS_URL`
- `DEX_ISSUERS`
- `DEX_AUDIENCE` (optional but recommended)
- `DEX_EMAIL_ALLOWLIST` (optional, comma-separated)
- `DEX_REQUIRED_GROUP` (optional)

Example:

```bash
curl -H "Authorization: Bearer $DEX_JWT" http://localhost:8000/gateway/whoami
```

Tenant self-service endpoints under `/api/self-service/*` use the same Dex bearer token and are scoped to resources owned by the caller.

OTP example:

```bash
curl -X POST http://localhost:8000/gateway/otp/issue \
  -H "Authorization: Bearer $DEX_JWT" \
  -H "Content-Type: application/json" \
  -d '{"context_id":1,"purpose":"login","ttl_seconds":300,"length":6}'
```

## Configure connections

Use admin API (`/api/admin/*`) or UI to create:

- users
- telegram connections
- messaging contexts

Dedicated config endpoint for provisioning connections is exposed at `/api/config/*`.

For tenant-owned provisioning, use `/api/self-service/*` instead. Self-service connection creation stores bot tokens and imported session strings into gateway-managed secrets scoped to the caller.

Connection secret references support:

- `managed://<name>` (gateway-managed encrypted secret)
- `env://ENV_VAR_NAME`
- `gsm://projects/<project>/secrets/<name>/versions/<version>`

If a reference has no scheme, it is treated as `managed://<name>`.

## Telegram user login flow (MTProto)

For `user` connections:

1) Create connection with `phone_number` and `secret_ref_session`.
2) Start login: `POST /api/admin/user-logins/start`
3) Verify code: `POST /api/admin/user-logins/verify`
4) Session string is stored in configured secret backend (GSM write path supported).

## Test webapp (user login flow)

A small local tester is included at `test-webapp/`.

Run:

```bash
./test-webapp/run.sh
```

Then open `http://localhost:8090` and point it to your gateway URL (default `http://127.0.0.1:8000`).

The tester includes a dedicated onboarding tab at `http://localhost:8090/onboarding`.

## Kubernetes deploy

```bash
./app_up.sh
```

This applies namespace, config, service account, PVC, deployment, service, and network policies.

Default deployment image follows repo convention:

- `docker.io/mylonasc/magarathea:telegram-service-<tag>`

Build and push a new tag:

```bash
./build_and_push_image.sh 0.1.1
```

Repo-style alias script is also available:

```bash
./push_images.sh 0.1.1
```

If tag changed, update the image in `k8s/deployment.yaml`.

Apply secrets either from static secret or ExternalSecret:

```bash
kubectl apply -f k8s/secrets.example.yaml
# or
kubectl apply -f k8s/externalsecret.example.yaml
```

Tear down:

```bash
./app_down.sh
```

## Notes

- Current default DB is SQLite for quick start. Models are SQLAlchemy-based and can move to Postgres by changing `DATABASE_URL`.
- Runtime access is now restricted to contexts whose owning connection belongs to the authenticated Dex principal.
- Service is intentionally `ClusterIP` and no public ingress is included.
- NetworkPolicy defaults to deny and allows ingress only from namespaces labeled `telegram-gateway-access=true`.
- Deployment expects pull secret `dockerhub-regcred` in namespace `telegram-gateway`.
