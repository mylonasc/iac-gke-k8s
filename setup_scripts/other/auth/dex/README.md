# Dex + oauth2-proxy setup (Microsoft + GitHub + Google)

This folder contains a concrete setup for running Dex as your identity broker,
then using oauth2-proxy (already present in this repo) to protect your app
ingress routes.

Result:

- User hits your app.
- ingress-nginx redirects unauthenticated users to oauth2-proxy.
- oauth2-proxy delegates login to Dex (OIDC provider).
- Dex shows Microsoft, GitHub, and Google login options.

## Files in this folder

- `01_create_dex_config_secret.sh`: creates/updates the Dex config Secret from env vars.
- `dex.yaml`: Dex Namespace + Deployment + Service.
- `dex-ingress.example.yaml`: example ingress for exposing Dex at `/dex`.

Related oauth2-proxy files:

- `../oauth2-proxy/oauth2-proxy-values.dex.example.yaml`
- `../oauth2-proxy/02_create_secret_from_env.sh`

## 0) Prerequisites

- ingress-nginx installed and serving your domain.
- TLS configured for your app host and Dex host.
- `kubectl` access to the target cluster.
- `helm` installed (for oauth2-proxy chart install/upgrade).

## 1) DNS + URL plan

Use one host for Dex and one for the app (recommended):

- Dex issuer URL: `https://auth.<your-domain>/dex`
- App URL: `https://app.<your-domain>`

Set these callback URLs in your OAuth apps (Microsoft/GitHub/Google):

- `https://auth.<your-domain>/dex/callback`

Set this callback URL for oauth2-proxy (in Dex static client config):

- `https://app.<your-domain>/oauth2/callback`

Important: these are two different callback types and both are required:

- IdP connector callback (configured in Microsoft/GitHub/Google app):
  `https://auth.<your-domain>/dex/callback`
- oauth2-proxy OIDC client callback (configured in Dex static client and oauth2-proxy):
  `https://app.<your-domain>/oauth2/callback`

## 2) Create Dex config Secret (includes connectors + oauth2-proxy client)

Export variables and run the script:

```bash
export DEX_ISSUER_URL="https://auth.<your-domain>/dex"
export DEX_OAUTH2_PROXY_REDIRECT_URI="https://app.<your-domain>/oauth2/callback"
export DEX_OAUTH2_PROXY_CLIENT_ID="oauth2-proxy"
export DEX_OAUTH2_PROXY_CLIENT_SECRET="<strong-random-secret>"

export DEX_GITHUB_CLIENT_ID="<github-client-id>"
export DEX_GITHUB_CLIENT_SECRET="<github-client-secret>"

export DEX_MICROSOFT_CLIENT_ID="<microsoft-client-id>"
export DEX_MICROSOFT_CLIENT_SECRET="<microsoft-client-secret>"
export DEX_MICROSOFT_TENANT="common"

export DEX_GOOGLE_CLIENT_ID="<google-client-id>"
export DEX_GOOGLE_CLIENT_SECRET="<google-client-secret>"

./01_create_dex_config_secret.sh
```

Notes:

- `DEX_MICROSOFT_TENANT=common` is multi-tenant; set your tenant ID to restrict.
- The script creates namespace `dex` and applies Secret `dex-config`.
- Current manifest uses SQLite on pod local storage (`emptyDir`) for Dex state.
  Because that storage is pod-local, run a single Dex replica in this mode.
  For HA/persistence, move Dex storage to a durable backend.

## 3) Deploy Dex

```bash
kubectl apply -f dex.yaml
```

Then expose it via ingress:

1. Copy `dex-ingress.example.yaml`.
2. Replace placeholders:
   - `auth.example.com`
   - `auth-example-com-tls`
3. Apply it:

```bash
kubectl apply -f dex-ingress.example.yaml
```

## 4) Configure oauth2-proxy to use Dex

Create/update oauth2-proxy secret using the same Dex static client credentials:

```bash
export OAUTH2_PROXY_CLIENT_ID="oauth2-proxy"
export OAUTH2_PROXY_CLIENT_SECRET="$DEX_OAUTH2_PROXY_CLIENT_SECRET"
export OAUTH2_PROXY_COOKIE_SECRET="<32-char-random-cookie-secret>"

../oauth2-proxy/02_create_secret_from_env.sh
```

Use `../oauth2-proxy/oauth2-proxy-values.dex.example.yaml` as your values file,
set the issuer and redirect URLs, then install/upgrade oauth2-proxy:

```bash
helm repo add oauth2-proxy https://oauth2-proxy.github.io/manifests
helm repo update

helm upgrade --install oauth2-proxy oauth2-proxy/oauth2-proxy \
  -n oauth2-proxy \
  -f ../oauth2-proxy/oauth2-proxy-values.dex.example.yaml

# ensure /oauth2 ingress points to oauth2-proxy service port name "http"
kubectl apply -f ../oauth2-proxy/oauth2-proxy-ingress.yaml
```

If you previously deployed oauth2-proxy from raw manifests in this repo
(`oauth2-proxy.yaml`), delete the old Deployment/Service first, then run the
Helm command again:

```bash
kubectl -n oauth2-proxy delete deployment oauth2-proxy service oauth2-proxy
```

Why this happens: Helm cannot adopt resources that were created without Helm
ownership labels/annotations.

## 5) Protect your app ingress

Your app ingress needs these annotations (already used in several repo manifests):

```yaml
nginx.ingress.kubernetes.io/auth-url: "https://$host/oauth2/auth"
nginx.ingress.kubernetes.io/auth-signin: "https://$host/oauth2/start?rd=$escaped_request_uri"
```

## 6) Verify

```bash
kubectl -n dex get pods,svc
kubectl -n dex logs deploy/dex
kubectl -n oauth2-proxy get pods
kubectl -n oauth2-proxy logs deploy/oauth2-proxy
```

Open your app URL and confirm Dex shows Microsoft/GitHub/Google buttons.

## Troubleshooting quick hits

- Redirect mismatch:
  - Connector callback must be `https://auth.<your-domain>/dex/callback`.
  - oauth2-proxy redirect must be `https://app.<your-domain>/oauth2/callback`.
- Login loop:
  - Keep `/oauth2/*` and `/dex/*` endpoints reachable and not self-protected.
- 401 from auth-url:
  - Verify oauth2-proxy ingress route and service health.
- Dex issuer mismatch:
  - `--oidc-issuer-url` in oauth2-proxy must exactly match Dex `issuer`.
