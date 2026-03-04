> This is an example-oriented setup note for oauth2-proxy with ingress-nginx.
> Validate against current official docs before production use:
> `https://oauth2-proxy.github.io/oauth2-proxy/`
> and `https://kubernetes.github.io/ingress-nginx/examples/auth/oauth-external-auth/`.

* **Ingress A (no auth annotations):** routes `https://yourdomain.com/oauth2/*` → `oauth2-proxy`
* **Ingress B (protected):** routes `https://yourdomain.com/*` → your app, and uses `auth-url` / `auth-signin` to bounce users to `/oauth2/start`

That “two Ingress objects for one host” approach is exactly how ingress-nginx documents external OAuth authentication. ([kubernetes.github.io][1])

Below is a working, production-ish setup you can copy/paste and then tweak.

---

## 1) Create an OAuth client in your IdP

Whatever provider you choose (Google, Auth0, Azure AD, Keycloak, Okta…), set:

* **Redirect / callback URL:** `https://yourdomain.com/oauth2/callback` ([kubernetes.github.io][1])
* Note the **client id** and **client secret**

> For “login”, prefer an **OIDC** app/client (OpenID Connect).

---

## 2) Deploy oauth2-proxy (Helm)

Add the official chart repo: ([GitHub][2])

```bash
helm repo add oauth2-proxy https://oauth2-proxy.github.io/manifests
helm repo update
kubectl create namespace oauth2-proxy
```

Create a secret (cookie secret should be long/random):

```bash
# cookie secret: 32 bytes base64 is a common choice
COOKIE_SECRET="$(python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')"

kubectl -n oauth2-proxy create secret generic oauth2-proxy-secrets \
  --from-literal=client-id='YOUR_CLIENT_ID' \
  --from-literal=client-secret='YOUR_CLIENT_SECRET' \
  --from-literal=cookie-secret="$COOKIE_SECRET"
```

Create `oauth2-proxy-values.yaml`:

```yaml
config:
  # The chart supports providing config via a secret-mounted file too, but
  # keeping it simple here with extraArgs + env vars.
  existingSecret: oauth2-proxy-secrets
  existingSecretKey: "" # (leave empty; we’ll reference keys via env below)

extraEnv:
  - name: OAUTH2_PROXY_CLIENT_ID
    valueFrom:
      secretKeyRef:
        name: oauth2-proxy-secrets
        key: client-id
  - name: OAUTH2_PROXY_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: oauth2-proxy-secrets
        key: client-secret
  - name: OAUTH2_PROXY_COOKIE_SECRET
    valueFrom:
      secretKeyRef:
        name: oauth2-proxy-secrets
        key: cookie-secret

extraArgs:
  # --- Pick ONE provider style ---
  # Generic OIDC (works for Auth0 / AzureAD / Keycloak / Okta / etc.)
  - --provider=oidc
  - --oidc-issuer-url=https://YOUR_ISSUER/.well-known/openid-configuration # sometimes just https://issuer
  # If your issuer url is the base issuer (common), use:
  # - --oidc-issuer-url=https://YOUR_ISSUER

  # Required for being behind ingress:
  - --reverse-proxy=true

  # Mount oauth2-proxy at /oauth2
  - --proxy-prefix=/oauth2
  - --redirect-url=https://yourdomain.com/oauth2/callback

  # In “auth_request mode” (nginx auth-url), set identity headers:
  - --set-xauthrequest=true

  # Usually you want to restrict who can log in:
  - --email-domain=YOURDOMAIN.COM
  # or allow any email (not recommended):
  # - --email-domain=*

  # oauth2-proxy must have an upstream, but in this pattern it mainly serves /oauth2/*
  - --upstream=static://200

  # Cookie settings:
  - --cookie-secure=true
  - --cookie-samesite=lax

service:
  portNumber: 4180
```

Install:

```bash
helm install oauth2-proxy oauth2-proxy/oauth2-proxy \
  -n oauth2-proxy \
  -f oauth2-proxy-values.yaml
```

Notes:

* `--set-xauthrequest=true` makes oauth2-proxy emit headers like `X-Auth-Request-Email/User/...` which is exactly what NGINX auth_request setups often want. ([oauth2-proxy.github.io][3])

---

## 3) Create the two Ingress objects (NGINX Ingress)

### A) Ingress for oauth2-proxy endpoints (NO auth annotations)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: oauth2-proxy
  namespace: oauth2-proxy
spec:
  ingressClassName: nginx
  tls:
  - hosts: [ "yourdomain.com" ]
    secretName: your-tls-secret
  rules:
  - host: yourdomain.com
    http:
      paths:
      - path: /oauth2
        pathType: Prefix
        backend:
          service:
            name: oauth2-proxy
            port:
              number: 4180
```

### B) Ingress for your app (protected by oauth2-proxy)

This is the key part: `auth-url` and `auth-signin`. ([kubernetes.github.io][1])

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp
  namespace: myapp
  annotations:
    nginx.ingress.kubernetes.io/auth-url: "https://$host/oauth2/auth"
    nginx.ingress.kubernetes.io/auth-signin: "https://$host/oauth2/start?rd=$escaped_request_uri"

    # Pass identity headers to your upstream (Python) app:
    nginx.ingress.kubernetes.io/auth-response-headers: "X-Auth-Request-User,X-Auth-Request-Email,X-Auth-Request-Preferred-Username,X-Auth-Request-Groups"

    # Optional: avoid “upstream sent too big header” if cookies get large:
    nginx.ingress.kubernetes.io/proxy-buffer-size: "16k"
spec:
  ingressClassName: nginx
  tls:
  - hosts: [ "yourdomain.com" ]
    secretName: your-tls-secret
  rules:
  - host: yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: myapp-svc
            port:
              number: 80
```

* The `auth-url` / `auth-signin` mechanism is the ingress-nginx documented pattern for external OAuth auth. ([kubernetes.github.io][1])
* `proxy-buffer-size` is a valid ingress-nginx annotation; increasing it can help when auth cookies/headers are bigger. ([GitHub][4])

Apply:

```bash
kubectl apply -f oauth2-proxy-ingress.yaml
kubectl apply -f myapp-ingress.yaml
```

---

## 4) Make your Python backend aware of the user (headers)

After login, your app will receive headers like:

* `X-Auth-Request-Email`
* `X-Auth-Request-User`
* `X-Auth-Request-Preferred-Username`
* `X-Auth-Request-Groups` (depends on provider/claims)

Those headers are produced by oauth2-proxy when `--set-xauthrequest=true`. ([oauth2-proxy.github.io][3])

**FastAPI example:**

```python
from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/whoami")
def whoami(req: Request):
    return {
        "email": req.headers.get("x-auth-request-email"),
        "user": req.headers.get("x-auth-request-user"),
        "preferred_username": req.headers.get("x-auth-request-preferred-username"),
        "groups": req.headers.get("x-auth-request-groups"),
    }
```

---

## 5) Quick debug checklist

1. oauth2-proxy pods healthy:

```bash
kubectl -n oauth2-proxy get pods
kubectl -n oauth2-proxy logs deploy/oauth2-proxy
```

2. Hitting your site redirects to login:

* Visit `https://yourdomain.com/` → should redirect to your IdP.

3. Common issues:

* **Redirect URI mismatch**: IdP must exactly match `https://yourdomain.com/oauth2/callback`
* **Login loop**: usually means `/oauth2/*` is also protected (fix by keeping oauth2-proxy on its own ingress without auth annotations) ([kubernetes.github.io][1])
* **401 from auth-url**: oauth2-proxy not reachable at `/oauth2/auth` on that host
* **502 “too big header”**: increase `proxy-buffer-size` ([GitHub][4])

---

If you tell me which IdP you’re using (Google, Auth0, Azure AD, Keycloak, …), I’ll plug in the exact oauth2-proxy flags for that provider (issuer URL format + the right scopes/claims to get groups/email cleanly).

[1]: https://kubernetes.github.io/ingress-nginx/examples/auth/oauth-external-auth/ "External OAUTH Authentication - Ingress-Nginx Controller"
[2]: https://github.com/oauth2-proxy/manifests?utm_source=chatgpt.com "oauth2-proxy/manifests: Helm charts to ..."
[3]: https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/?utm_source=chatgpt.com "Overview | OAuth2 Proxy"
[4]: https://github.com/kubernetes/ingress-nginx/blob/main/docs/user-guide/nginx-configuration/annotations.md?utm_source=chatgpt.com "ingress-nginx/docs/user-guide/nginx-configuration ..."
