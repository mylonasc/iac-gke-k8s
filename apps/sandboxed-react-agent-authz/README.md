# Sandboxed React Agent Authz Component

This component is the authorization control plane for `sandboxed-react-agent`.

- `backend/`: policy API (`GET/PUT /api/policy/current`, `POST /api/policy/validate`)
- `frontend/`: simple policy editor UI
- `k8s/`: standalone deployment/service/ingress manifests

## Security model

- `GET /api/policy/current` is readable by default (for backend service polling).
- `PUT /api/policy/current`, `POST /api/policy/validate`, and `GET /api/policy/audit`
  require admin authorization.

Admin authorization accepts one of:

- `X-Auth-Request-Groups` intersecting `AUTHZ_ADMIN_GROUP_ALLOWLIST` (default: `sra-admins`)
- `X-Auth-Request-Email` in `AUTHZ_ADMIN_EMAIL_ALLOWLIST`
- `X-Auth-Request-User` in `AUTHZ_ADMIN_USER_ALLOWLIST`
- `Authorization: Bearer <token>` matching `AUTHZ_ADMIN_BEARER_TOKEN`

For write requests, optimistic concurrency is enforced via `If-Match` (ETag hash).
Policy update/validation events are written as JSONL audit entries at
`AUTHZ_POLICY_AUDIT_LOG_PATH`.

## Runtime contract with main backend

Main backend polls:

- `GET /api/policy/current`

Expected response payload:

- `policy_yaml`: YAML policy text
- `sha256`: snapshot hash
- `version`

The main backend keeps an in-memory cached policy and uses it for request-time
feature checks and sandbox constraints.

## Local run

Backend:

```bash
cd apps/sandboxed-react-agent-authz/backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8081
```

Frontend (static):

```bash
cd apps/sandboxed-react-agent-authz/frontend
python -m http.server 8082
```

Open `http://localhost:8082`.

When running frontend and backend on different local ports, pass backend API base:

- `http://localhost:8082/?api_base=http://localhost:8081/api`

### Docker Compose

```bash
cd apps/sandboxed-react-agent-authz
docker compose up --build
```

- backend: `http://localhost:8081/api/health`
- frontend: `http://localhost:8082/?api_base=http://localhost:8081/api`
