# Local OIDC Mock

Lightweight local OIDC/JWKS service for development and integration testing.

## What it provides

- `GET /.well-known/openid-configuration`
- `GET /jwks`
- `POST /token` to mint RS256 bearer tokens with Dex-like claims

Default claims in minted tokens:

- `sub`
- `email`
- `groups`
- `iss`
- `aud`
- `iat`, `nbf`, `exp`, `jti`

## Runtime env vars

- `OIDC_ISSUER` (default: `http://local-oidc:9000`)
- `OIDC_DEFAULT_AUDIENCE` (default: `local-dev`)
- `OIDC_TOKEN_TTL_SECONDS` (default: `3600`)
- `OIDC_SIGNING_KID` (default: `local-dev-rs256`)

## Example token request

```bash
curl -sS -X POST http://127.0.0.1:19000/token \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "local-dev-user",
    "email": "local-dev@example.com",
    "audience": "janet-local",
    "groups": ["sra-admins"]
  }'
```
