## Notes:

to pull a submodule:
```bash
cd path/to/submodule 
git submodule update --init --recursive
```

## Local OIDC/JWKS testing

The `local-oidc-mock/` service provides local OIDC discovery, JWKS, and token minting.

- `janet/` uses `docker-compose.auth-local.yml` (OIDC on host port `19000`)
- `cluster-user-secrets-broker/` uses `docker-compose.auth-local.yml` (OIDC on host port `19001`)
- `cluster-authz-manager/` uses `docker-compose.auth-local.yml` (OIDC on host port `19002`)

Quick start examples:

```bash
# janet
cd janet
docker compose -f docker-compose.yml -f docker-compose.auth-local.yml up --build
TOKEN="$(./scripts/get-local-token.sh)"

# cluster-user-secrets-broker
cd ../cluster-user-secrets-broker
docker compose -f docker-compose.yml -f docker-compose.auth-local.yml up --build
TOKEN="$(./scripts/get-local-token.sh)"

# cluster-authz-manager
cd ../cluster-authz-manager
docker compose -f docker-compose.yml -f docker-compose.auth-local.yml up --build
TOKEN="$(./scripts/get-local-token.sh)"
```
