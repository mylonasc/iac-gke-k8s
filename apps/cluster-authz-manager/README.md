# Cluster Authz Manager

Authorization and role-management service used by cluster applications.

## Local run

Run default local stack:

```bash
docker compose up --build
```

### Local OIDC/JWKS auth mode

Run with local JWT validation enabled (Dex-compatible OIDC/JWKS behavior):

```bash
docker compose -f docker-compose.yml -f docker-compose.auth-local.yml up --build
```

Service endpoint:

- Frontend + proxied API: `http://127.0.0.1:8081`

Mint a local token:

```bash
./scripts/get-local-token.sh
```

The helper emits a token for audience `authz-manager-local` by default and uses
`mylonas.charilaos@gmail.com` as the default email (bootstrapped admin binding).
Override values as needed:

```bash
AUDIENCE=authz-manager-local SUBJECT=alice EMAIL=alice@example.com GROUPS=sra-admins ./scripts/get-local-token.sh
```

Example request:

```bash
TOKEN="$(./scripts/get-local-token.sh)"
curl -H "Authorization: Bearer ${TOKEN}" http://127.0.0.1:8081/api/users
```

Negative check (wrong audience should fail with `401`):

```bash
TOKEN="$(AUDIENCE=wrong-aud ./scripts/get-local-token.sh)"
curl -i -H "Authorization: Bearer ${TOKEN}" http://127.0.0.1:8081/api/users
```

## Auth behavior

- When `AUTH_ENABLED=true`, bearer JWTs are validated against issuer/JWKS.
- Claims `sub`, `email`, and `groups` are mapped to request identity.
- Legacy forwarded headers (`x-auth-request-*`) remain supported for compatibility.
