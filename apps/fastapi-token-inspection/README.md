# FastAPI Token Inspection

This app is a debugging utility for oauth2-proxy protected traffic.

It helps you retrieve the token that oauth2-proxy forwards upstream (for example
`X-Auth-Request-Access-Token`) and decode JWT payloads for verification.

Use this only for short-lived debugging sessions.

## Files

- `deployment.yaml`: FastAPI deployment (`python:3.12-alpine`)
- `service.yaml`: ClusterIP service on port 80 -> container port 8000
- `ingress.yaml`: ingress-nginx route at `/token-inspection` with oauth2-proxy auth annotations
- `ingress.magarathea.yaml`: host-specific ingress for `magarathea.ddns.net` with TLS secret `magarathea-ddns-net-tls`
- `manage.sh`: helper for intermittent lifecycle (`up`, `down`, `status`, `logs`, `url`)

## Deploy (intermittent)

From `apps/fastapi-token-inspection`:

```bash
./manage.sh up
```

Equivalent manual deploy:

```bash
kubectl apply -f apps/fastapi-token-inspection/deployment.yaml
kubectl apply -f apps/fastapi-token-inspection/service.yaml
kubectl apply -f apps/fastapi-token-inspection/ingress.yaml
```

For the `magarathea.ddns.net` host-specific ingress:

```bash
kubectl apply -f apps/fastapi-token-inspection/ingress.magarathea.yaml
```

Check rollout:

```bash
kubectl -n alt-default rollout status deploy/fastapi-token-inspection
kubectl -n alt-default get deploy,svc,ingress fastapi-token-inspection
```

## Reach it

Ingress path:

- `https://<your-host>/token-inspection`
- `https://<your-host>/token-inspection/raw` (returns full token values)

The ingress is configured to use oauth2-proxy auth endpoints on the same host:

- `/oauth2/auth`
- `/oauth2/start`

## Retrieve a token for backend testing

1. Open the raw endpoint in your browser while authenticated:

```text
https://magarathea.ddns.net/token-inspection/raw
```

2. Copy one token from JSON output:

- `token_sources.x_auth_request_access_token` (preferred)
- fallback: `token_sources.authorization_bearer`

3. Export and test against the sandboxed-react-agent API:

```bash
export BENCHMARK_AUTH_TOKEN='<copied-token>'
curl -sS "https://magarathea.ddns.net/sandboxed-react-agent/api/me" \
  -H "Authorization: Bearer ${BENCHMARK_AUTH_TOKEN}"
```

## Endpoints

- `GET /healthz`: readiness check
- `GET /token-inspection`: redacted token hints + decoded payload
- `GET /token-inspection/raw`: full token sources + decoded payload
- `GET /inspect-token`: alias for redacted inspection output

## Test request (manual bearer)

If you already have an access token:

```bash
curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" "https://<your-host>/token-inspection"
```

Check decoded payload in logs:

```bash
kubectl -n alt-default logs deploy/fastapi-token-inspection --tail=100
```

## Tear down

Recommended (intermittent cleanup):

```bash
./manage.sh down
```

Equivalent manual cleanup:

```bash
kubectl delete -f apps/fastapi-token-inspection/ingress.yaml
kubectl delete -f apps/fastapi-token-inspection/service.yaml
kubectl delete -f apps/fastapi-token-inspection/deployment.yaml
```

If you used the host-specific ingress, delete it as well:

```bash
kubectl delete -f apps/fastapi-token-inspection/ingress.magarathea.yaml
```

## Notes

- This decodes JWT payloads without signature verification and is intended for debugging only.
- Do not keep this app running continuously; deploy when needed and tear it down afterward.
- Treat `/token-inspection/raw` as sensitive because it returns full token strings.
