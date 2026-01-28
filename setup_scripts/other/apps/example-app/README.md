
# Helm README — `app-hello` (web app + Service + NGINX Ingress w/ optional external auth)

This Helm chart deploys a simple HTTP web application into a dedicated namespace, exposes it via a ClusterIP Service, and optionally publishes it externally via an NGINX Ingress with TLS and external auth (oauth2-proxy style).

## What gets installed

- **Namespace** (optional): `{{ .Values.namespace }}`
- **Deployment**: runs the container image and exposes a container port
- **Service**: stable in-cluster endpoint (`port` → `targetPort`)
- **Ingress** (optional): routes `https://<host>/` to the Service, with TLS and optional external auth annotations

## Prerequisites

- Kubernetes cluster access (`kubectl` configured)
- Helm v3
- If `ingress.enabled=true`:
  - An **NGINX Ingress Controller** installed and configured for the chosen class
  - DNS for the hostname pointing at the ingress controller
- If TLS is enabled:
  - A TLS secret must exist **in the release namespace**, unless you also use cert-manager to provision it
- If `auth.enabled=true`:
  - `/oauth2/auth` and `/oauth2/start` endpoints must exist on the same host (commonly via oauth2-proxy + its own routing)

## Install

### 1) Configure values
Create a values file (example: `values-prod.yaml`):

```yaml
namespace: app-hello

app:
  name: my-hello-website
  labels:
    app: hello
  image: gcr.io/google-samples/hello-app:1.0
  replicas: 1
  containerPort: 8080

service:
  name: my-hello-service
  port: 80
  targetPort: 8080

ingress:
  enabled: true
  className: nginx
  host: magarathea.ddns.net
  tlsSecretName: magarathea-ddns-net-tls
  path: /
  pathType: Prefix

auth:
  enabled: true
  url: "https://$host/oauth2/auth"
  signin: "https://$host/oauth2/start?rd=$escaped_request_uri"
  responseHeaders: "x-auth-request-user,x-auth-request-email"
````

### 2) Install / upgrade

```bash
helm upgrade --install app-hello ./chart -f values-prod.yaml
```

## Verify

```bash
kubectl get ns
kubectl -n app-hello get deploy,po,svc,ingress
```

Ingress endpoints (depends on controller):

```bash
kubectl -n app-hello describe ingress my-hello-website-ingress
```

## Common operations

### Swap the app image

```bash
helm upgrade --install app-hello ./chart \
  -f values-prod.yaml \
  --set app.image=ghcr.io/my-org/newapp:2.3.1
```

### Change the domain name

```bash
helm upgrade --install app-hello ./chart \
  -f values-prod.yaml \
  --set ingress.host=example.com \
  --set ingress.tlsSecretName=example-com-tls
```

### Change ports (container + service target)

If the new container listens on `5000`:

```bash
helm upgrade --install app-hello ./chart \
  -f values-prod.yaml \
  --set app.containerPort=5000 \
  --set service.targetPort=5000
```

### Scale replicas

```bash
helm upgrade --install app-hello ./chart \
  -f values-prod.yaml \
  --set app.replicas=3
```

### Disable ingress (internal-only Service)

```bash
helm upgrade --install app-hello ./chart \
  -f values-prod.yaml \
  --set ingress.enabled=false
```

### Disable external auth (no oauth2 gate)

```bash
helm upgrade --install app-hello ./chart \
  -f values-prod.yaml \
  --set auth.enabled=false
```

## Values reference (summary)

| Key                         | Meaning                                                    |
| --------------------------- | ---------------------------------------------------------- |
| `namespace`                 | Namespace to deploy into                                   |
| `app.name`                  | Base name for resources (deployment/ingress)               |
| `app.labels`                | Labels applied to Pods; Service selects these              |
| `app.image`                 | Container image to run                                     |
| `app.replicas`              | Deployment replica count                                   |
| `app.containerPort`         | Port the container listens on                              |
| `service.name`              | Service name                                               |
| `service.port`              | Service port exposed in-cluster                            |
| `service.targetPort`        | Target port on Pods (typically equals `app.containerPort`) |
| `ingress.enabled`           | Create Ingress when true                                   |
| `ingress.className`         | Ingress class (e.g., `nginx`)                              |
| `ingress.host`              | External hostname                                          |
| `ingress.tlsSecretName`     | TLS secret name (same namespace)                           |
| `ingress.path` / `pathType` | Path routing config                                        |
| `auth.enabled`              | Add NGINX external auth annotations                        |
| `auth.url` / `signin`       | NGINX auth endpoints                                       |
| `auth.responseHeaders`      | Headers to pass upstream from auth response                |

## Notes / gotchas

* TLS secret references are **namespace-scoped**: the secret must exist in the release namespace.
* If `auth.enabled=true`, ensure `/oauth2/*` endpoints are routable on the same host, or requests will fail/loop.
* Many clusters now prefer `spec.ingressClassName`; if your controller ignores `kubernetes.io/ingress.class`, set the chart to use `ingressClassName` (if supported by the templates).

## Uninstall

```bash
helm uninstall app-hello -n app-hello
# If the chart created the namespace and you want it removed:
kubectl delete ns app-hello
```

