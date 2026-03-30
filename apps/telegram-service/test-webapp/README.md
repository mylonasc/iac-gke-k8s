# Telegram Gateway Test Webapp

Small local webapp that helps you test gateway admin flows and runtime gateway calls with a full Dex OAuth login.

## What it does

- Logs into gateway admin (`/admin/login`) and stores `tg_admin_session` cookie in local tester session.
- Performs full Dex OAuth2 Authorization Code + PKCE flow and stores Dex `id_token` locally.
- Creates a `user` connection with phone number + `secret_ref_session`.
- Creates API-managed secrets and uses `managed://` refs in connections.
- Starts Telegram user login (`/api/admin/user-logins/start`) to trigger verification code.
- Verifies code (`/api/admin/user-logins/verify`) and confirms session storage.
- Creates bot connections and messaging contexts.
- Calls runtime endpoints (`/gateway/whoami`, `/gateway/contexts/{id}/send`, `/gateway/contexts/{id}/updates`) for both bot and user contexts.
- Tests built-in OTP endpoints (`/gateway/otp/issue`, `/gateway/otp/verify`).

## Run

From repo root:

```bash
./apps/telegram-service/test-webapp/run.sh
```

Open:

- `http://localhost:8090`
- Onboarding tab: `http://localhost:8090/onboarding`

## Dex setup notes

For your selected approach (reuse existing `oauth2-proxy` Dex client), make sure Dex client redirect URIs include:

- `http://localhost:8090/dex/callback`

You can configure this from repo scripts by setting:

- `DEX_OAUTH2_PROXY_EXTRA_REDIRECT_URIS="http://localhost:8090/dex/callback"`

In the tester UI set:

- Dex issuer base: `https://magarathea.ddns.net/dex`
- Client id: `oauth2-proxy`
- Client secret: `<oauth2-proxy client secret>`
- Scopes: `openid profile email`

Optional env defaults for tester UI:

- `TESTER_DEX_ISSUER`
- `TESTER_DEX_CLIENT_ID`
- `TESTER_DEX_CLIENT_SECRET`
- `TESTER_DEX_SCOPES`
- `TESTER_DEX_REDIRECT_URI`
- `TESTER_ADMIN_USERNAME`
- `TESTER_ADMIN_PASSWORD`

`run.sh` now auto-loads these from cluster secrets when available.

The gateway currently validates runtime JWT audience as `oauth2-proxy`, so using that client id is important.

## Notes

- Gateway must already be reachable (for example via port-forward):

```bash
kubectl -n telegram-gateway port-forward svc/telegram-service 8000:80
```

- Default gateway URL in tester is `http://127.0.0.1:8000`.
- This tester is for local/dev use only.
