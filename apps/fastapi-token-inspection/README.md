# FastAPI Token Inspection

This app is a debugging utility for oauth-proxy protected traffic.
It accepts a Bearer token and prints the decoded JWT payload to pod logs.

## Files

- `deployment.yaml`: FastAPI deployment (`python:3.12-alpine`)
- `service.yaml`: ClusterIP service on port 80 -> container port 8000
- `ingress.yaml`: ingress-nginx route at `/token-inspection` with oauth2-proxy auth annotations
- `ingress.magarathea.yaml`: host-specific ingress for `magarathea.ddns.net` with TLS secret `magarathea-ddns-net-tls`

## Deploy

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

The ingress is configured to use oauth2-proxy auth endpoints on the same host:

- `/oauth2/auth`
- `/oauth2/start`

## Test request

If you already have an access token:

```bash
curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" "https://<your-host>/token-inspection"
```

Check decoded payload in logs:

```bash
kubectl -n alt-default logs deploy/fastapi-token-inspection --tail=100
```

## Tear down

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
- Do not use this app for production token validation.
