# Deployment Guide

## Docker Compose (local)

```bash
cp .env.example .env.local
docker compose up --build
```

Service:

- Admin UI: `http://localhost:8000/admin/login`

## Kubernetes

1) Build and push image:

```bash
./build_and_push_image.sh <tag>
```

2) Update `k8s/deployment.yaml` image tag to match pushed image.

3) Deploy:

```bash
./app_up.sh
```

4) Apply secrets (choose one):

```bash
kubectl apply -f k8s/secrets.example.yaml
kubectl apply -f k8s/externalsecret.example.yaml
```

5) Verify:

```bash
kubectl -n telegram-gateway get deploy,svc,pvc,pods
kubectl -n telegram-gateway rollout status deploy/telegram-service --timeout=300s
```

6) Access internally (or port-forward for ops):

```bash
kubectl -n telegram-gateway port-forward svc/telegram-service 8000:8000
```

## Namespace access control

Only allow client namespaces with label:

```bash
kubectl label namespace <client-namespace> telegram-gateway-access=true
```

This is required by `k8s/networkpolicy.yaml` ingress rules.
