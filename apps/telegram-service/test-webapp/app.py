from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
from urllib.parse import urlencode, urljoin

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware


app = FastAPI(title="Telegram Gateway Tester", version="0.2.0")
app.add_middleware(SessionMiddleware, secret_key="replace-me-in-prod")


def _base(url: str) -> str:
    clean = (url or "").strip()
    return clean.rstrip("/") if clean else "http://127.0.0.1:8000"


def _oidc_token_claims(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        data = json.loads(decoded)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _json_pretty(payload: object) -> str:
    try:
        return json.dumps(payload, indent=2, ensure_ascii=True)
    except Exception:
        return str(payload)


def _get_state(request: Request) -> dict[str, str]:
    id_token = request.session.get("dex_id_token", "")
    claims = _oidc_token_claims(id_token) if id_token else {}
    default_gateway_url = os.getenv("TESTER_GATEWAY_URL", "http://127.0.0.1:8000")
    default_admin_username = os.getenv("TESTER_ADMIN_USERNAME", "")
    default_admin_password = os.getenv("TESTER_ADMIN_PASSWORD", "")
    default_issuer = os.getenv("TESTER_DEX_ISSUER", "https://magarathea.ddns.net/dex")
    default_client_id = os.getenv("TESTER_DEX_CLIENT_ID", "oauth2-proxy")
    default_client_secret = os.getenv(
        "TESTER_DEX_CLIENT_SECRET", os.getenv("TESTER_COOKIE_SECRET", "")
    )
    default_scopes = os.getenv("TESTER_DEX_SCOPES", "openid profile email")
    default_redirect_uri = os.getenv(
        "TESTER_DEX_REDIRECT_URI", "http://localhost:8090/dex/callback"
    )
    return {
        "gateway_url": request.session.get("gateway_url", default_gateway_url),
        "admin_username": request.session.get("admin_username", default_admin_username),
        "admin_password": request.session.get("admin_password", default_admin_password),
        "admin_cookie": request.session.get("admin_cookie", ""),
        "message": request.session.pop("message", ""),
        "error": request.session.pop("error", ""),
        "connection_id": request.session.get("connection_id", ""),
        "context_id": request.session.get("context_id", ""),
        "dex_issuer": request.session.get("dex_issuer", default_issuer),
        "dex_client_id": request.session.get("dex_client_id", default_client_id),
        "dex_client_secret": request.session.get(
            "dex_client_secret", default_client_secret
        ),
        "dex_scopes": request.session.get("dex_scopes", default_scopes),
        "dex_redirect_uri": request.session.get(
            "dex_redirect_uri_override", default_redirect_uri
        ),
        "dex_logged_in": "yes" if id_token else "no",
        "dex_subject": str(claims.get("sub", "")),
        "dex_email": str(claims.get("email", "")),
        "dex_aud": str(claims.get("aud", "")),
        "runtime_token": id_token,
        "last_response": request.session.get("last_response", ""),
    }


def _build_admin_headers(admin_cookie: str) -> dict[str, str]:
    return {"Cookie": f"tg_admin_session={admin_cookie}"}


def _build_runtime_headers(jwt_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt_token}"}


def _render(
    state: dict[str, str],
    connections: list[dict] | None = None,
    contexts: list[dict] | None = None,
    managed_secrets: list[dict] | None = None,
) -> HTMLResponse:
    connection_options = '<option value="">connection</option>'
    context_options = '<option value="">context</option>'
    secret_options = '<option value="">managed secret</option>'

    connection_rows = ""
    for item in connections or []:
        if item.get("is_active"):
            connection_options += (
                f'<option value="{item.get("id")}">'
                f"{item.get('id')} - {html.escape(str(item.get('name', '')))} ({html.escape(str(item.get('type', '')))})"
                "</option>"
            )
        connection_rows += (
            "<tr>"
            f"<td>{item.get('id')}</td>"
            f"<td>{html.escape(str(item.get('name', '')))}</td>"
            f"<td>{html.escape(str(item.get('type', '')))}</td>"
            f"<td>{html.escape(str(item.get('phone_number', '')))}</td>"
            f"<td>{html.escape(str(item.get('secret_ref_token', '')))}</td>"
            f"<td>{html.escape(str(item.get('secret_ref_session', '')))}</td>"
            f"<td>{html.escape(str(item.get('is_active', '')))}</td>"
            f"<td><form method='post' action='/delete-connection'><input type='hidden' name='connection_id' value='{item.get('id')}'><button type='submit'>Deactivate</button></form></td>"
            "</tr>"
        )

    context_rows = ""
    for item in contexts or []:
        if item.get("is_active"):
            context_options += (
                f'<option value="{item.get("id")}">'
                f"{item.get('id')} - {html.escape(str(item.get('name', '')))} (conn {item.get('connection_id')}, {html.escape(str(item.get('mode', '')))})"
                "</option>"
            )
        context_rows += (
            "<tr>"
            f"<td>{item.get('id')}</td>"
            f"<td>{item.get('connection_id')}</td>"
            f"<td>{html.escape(str(item.get('name', '')))}</td>"
            f"<td>{html.escape(str(item.get('mode', '')))}</td>"
            f"<td>{html.escape(str(item.get('chat_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('is_active', '')))}</td>"
            "</tr>"
        )

    secret_rows = ""
    for item in managed_secrets or []:
        if item.get("is_active"):
            secret_options += (
                f'<option value="managed://{html.escape(str(item.get("name", "")))}">'
                f"managed://{html.escape(str(item.get('name', '')))}"
                "</option>"
            )
        secret_rows += (
            "<tr>"
            f"<td>{item.get('id')}</td>"
            f"<td>managed://{html.escape(str(item.get('name', '')))}</td>"
            f"<td>{html.escape(str(item.get('secret_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('version', '')))}</td>"
            f"<td>{html.escape(str(item.get('is_active', '')))}</td>"
            f"<td><form method='post' action='/delete-managed-secret'><input type='hidden' name='name' value='{html.escape(str(item.get('name', '')))}'><button type='submit'>Deactivate</button></form></td>"
            "</tr>"
        )

    page = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Telegram Gateway Tester</title>
  <style>
    body {{ font-family: "Segoe UI", sans-serif; margin: 0; background: #f4f7fb; color: #1f2937; }}
    main {{ max-width: 1100px; margin: 24px auto; padding: 0 16px; }}
    .card {{ background: white; border: 1px solid #d1d5db; border-radius: 12px; padding: 16px; margin-bottom: 14px; }}
    h1, h2, h3 {{ margin-top: 0; }}
    input, button, select, textarea {{ padding: 8px; border-radius: 8px; border: 1px solid #cbd5e1; margin: 4px 6px 4px 0; font-size: 14px; }}
    button {{ background: #0f766e; color: white; border: none; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    td, th {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; font-size: 14px; }}
    .ok {{ color: #166534; }}
    .err {{ color: #b91c1c; }}
    .muted {{ color: #6b7280; }}
    pre {{ background: #0b1020; color: #c7d2fe; border-radius: 10px; padding: 12px; overflow: auto; }}
  </style>
</head>
<body>
  <main>
    <h1>Telegram Gateway Tester</h1>
    <p><a href="/">Main</a> | <a href="/onboarding">Onboarding Tab</a></p>
    <p class="muted">Full flow: admin setup + Dex OAuth login + runtime gateway interaction.</p>

    <div class="card">
      <h2>1) Gateway Admin Login</h2>
      <form method="post" action="/login-admin">
        <input name="gateway_url" placeholder="Gateway URL" value="{html.escape(state["gateway_url"])}" size="40" required>
        <input name="username" placeholder="Admin username" value="{html.escape(state["admin_username"])}" required>
        <input name="password" type="password" placeholder="Admin password" value="{html.escape(state["admin_password"])}" required>
        <button type="submit">Login</button>
      </form>
      <p class="muted">Admin logged in: {"yes" if state["admin_cookie"] else "no"}</p>
      {f'<p class="ok">{html.escape(state["message"])}</p>' if state["message"] else ""}
      {f'<p class="err">{html.escape(state["error"])}</p>' if state["error"] else ""}
    </div>

    <div class="card">
      <h2>2) Dex OAuth (Runtime JWT)</h2>
      <form method="post" action="/save-dex-config">
        <input name="dex_issuer" placeholder="Dex issuer base" value="{html.escape(state["dex_issuer"])}" size="35" required>
        <input name="dex_client_id" placeholder="Dex client id" value="{html.escape(state["dex_client_id"])}" required>
        <input name="dex_client_secret" type="password" placeholder="Dex client secret" value="{html.escape(state["dex_client_secret"])}">
        <input name="dex_scopes" placeholder="Scopes" value="{html.escape(state["dex_scopes"])}" size="24">
        <input name="dex_redirect_uri" placeholder="Redirect URI" value="{html.escape(state["dex_redirect_uri"])}" size="32" required>
        <button type="submit">Save Dex Config</button>
      </form>
      <form method="get" action="/dex/login">
        <button type="submit">Login with Dex</button>
      </form>
      <form method="post" action="/dex/logout">
        <button type="submit">Clear Dex Token</button>
      </form>
      <p class="muted">Dex logged in: {state["dex_logged_in"]}</p>
      <p class="muted">sub={html.escape(state["dex_subject"])} | email={html.escape(state["dex_email"])} | aud={html.escape(state["dex_aud"])}</p>
      <p class="muted">Dex redirect URI must exactly match a redirect URI configured for this client.</p>
    </div>

    <div class="card">
      <h2>3) Connections and Contexts</h2>
      <h3>Create Managed Secret (API-managed)</h3>
      <form method="post" action="/create-managed-secret">
        <input name="name" placeholder="secret name" required>
        <input name="value" placeholder="secret value" required>
        <input name="secret_type" placeholder="type" value="generic">
        <button type="submit">Create/Rotate Secret</button>
      </form>

      <h3>Create User Connection (for Telegram code flow)</h3>
      <form method="post" action="/create-user-connection">
        <input name="name" placeholder="user connection name" required>
        <input name="phone_number" placeholder="+3069..." required>
        <select name="secret_ref_session" required>{secret_options}</select>
        <button type="submit">Create User Connection</button>
      </form>

      <h3>Create Bot Connection (for send/receive)</h3>
      <form method="post" action="/create-bot-connection">
        <input name="name" placeholder="bot connection name" required>
        <select name="secret_ref_token" required>{secret_options}</select>
        <button type="submit">Create Bot Connection</button>
      </form>

      <h3>Create Messaging Context</h3>
      <form method="post" action="/create-context">
        <select name="connection_id" required>{connection_options}</select>
        <input name="name" placeholder="context name" required>
        <select name="mode">
          <option value="send_only">send_only</option>
          <option value="send_receive">send_receive</option>
          <option value="receive_only">receive_only</option>
        </select>
        <input name="chat_id" placeholder="chat id" required>
        <button type="submit">Create Context</button>
      </form>

      <form method="post" action="/refresh-data"><button type="submit">Refresh Connections + Contexts</button></form>

      <h3>Connections</h3>
      <table>
        <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Phone</th><th>Token Ref</th><th>Session Ref</th><th>Active</th><th>Action</th></tr></thead>
        <tbody>{connection_rows}</tbody>
      </table>

      <h3>Contexts</h3>
      <table>
        <thead><tr><th>ID</th><th>Conn ID</th><th>Name</th><th>Mode</th><th>Chat ID</th><th>Active</th></tr></thead>
        <tbody>{context_rows}</tbody>
      </table>

      <h3>Managed Secrets</h3>
      <table>
        <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Version</th><th>Active</th><th>Action</th></tr></thead>
        <tbody>{secret_rows}</tbody>
      </table>
    </div>

    <div class="card">
      <h2>4) Telegram User Login Flow</h2>
      <form method="post" action="/start-user-login">
        <select name="connection_id" required>{connection_options}</select>
        <button type="submit">Start Login (Send Code)</button>
      </form>
      <form method="post" action="/verify-user-login">
        <select name="connection_id" required>{connection_options}</select>
        <input name="code" placeholder="code from Telegram" required>
        <input name="password" placeholder="2FA password (optional)">
        <button type="submit">Verify Code</button>
      </form>
    </div>

    <div class="card">
      <h2>5) Runtime Gateway Calls (with Dex JWT)</h2>
      <p class="muted">Runtime send/updates support both bot and user contexts. Context mode rules still apply.</p>
      <form method="post" action="/runtime-whoami"><button type="submit">WhoAmI</button></form>
      <form method="post" action="/runtime-send">
        <select name="context_id" required>{context_options}</select>
        <input name="text" placeholder="message text" size="50" required>
        <button type="submit">Send Message</button>
      </form>
      <form method="post" action="/runtime-updates">
        <select name="context_id" required>{context_options}</select>
        <input name="offset" placeholder="offset (optional)">
        <button type="submit">Get Updates</button>
      </form>
    </div>

    <div class="card">
      <h2>6) OTP Flow (Issue + Verify)</h2>
      <form method="post" action="/runtime-otp-issue">
        <select name="context_id" required>{context_options}</select>
        <input name="target_label" placeholder="target label (optional)">
        <input name="purpose" placeholder="purpose" value="auth">
        <input name="ttl_seconds" type="number" value="300" min="60" max="1800">
        <input name="length" type="number" value="6" min="4" max="10">
        <button type="submit">Issue OTP</button>
      </form>
      <form method="post" action="/runtime-otp-verify">
        <input name="challenge_id" placeholder="challenge id" required>
        <input name="code" placeholder="OTP code" required>
        <button type="submit">Verify OTP</button>
      </form>
    </div>

    <div class="card">
      <h2>Last Response</h2>
      <pre>{html.escape(state["last_response"] or "(none yet)")}</pre>
    </div>
  </main>
</body>
</html>
"""
    return HTMLResponse(page)


def _render_onboarding_tab(
    state: dict[str, str],
    connections: list[dict] | None = None,
    onboarding_rows: list[dict] | None = None,
) -> HTMLResponse:
    bot_options = '<option value="">bot connection</option>'
    for c in connections or []:
        if str(c.get("type")) == "bot" and c.get("is_active"):
            bot_options += (
                f'<option value="{c.get("id")}">'
                f"{c.get('id')} - {html.escape(str(c.get('name', '')))}"
                "</option>"
            )

    rows = ""
    for item in onboarding_rows or []:
        link = str(item.get("deep_link") or "")
        qr = str(item.get("qr_data_url") or "")
        link_html = (
            f'<a href="{html.escape(link)}" target="_blank">{html.escape(link)}</a>'
            if link
            else "-"
        )
        qr_html = (
            f'<img src="{html.escape(qr)}" width="90" height="90" alt="qr">'
            if qr
            else "-"
        )
        rows += (
            "<tr>"
            f"<td>{item.get('id')}</td>"
            f"<td>{item.get('connection_id')}</td>"
            f"<td>{html.escape(str(item.get('target_label', '') or '-'))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('chat_id', '') or '-'))}</td>"
            f"<td>{html.escape(str(item.get('context_id', '') or '-'))}</td>"
            f"<td>{link_html}</td>"
            f"<td>{qr_html}</td>"
            f"<td><form method='post' action='/onboarding-delete-link'><input type='hidden' name='link_id' value='{item.get('id')}'><button type='submit'>Delete</button></form></td>"
            "</tr>"
        )

    page = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Onboarding Tab</title>
  <style>
    body {{ font-family: "Segoe UI", sans-serif; margin: 0; background: #f4f7fb; color: #1f2937; }}
    main {{ max-width: 980px; margin: 24px auto; padding: 0 16px; }}
    .card {{ background: white; border: 1px solid #d1d5db; border-radius: 12px; padding: 16px; margin-bottom: 14px; }}
    input, button, select {{ padding: 8px; border-radius: 8px; border: 1px solid #cbd5e1; margin: 4px 6px 4px 0; }}
    button {{ background: #0f766e; color: white; border: none; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    td, th {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; font-size: 14px; }}
    .ok {{ color: #166534; }}
    .err {{ color: #b91c1c; }}
  </style>
</head>
<body>
  <main>
    <h1>Onboarding Tab</h1>
    <p><a href="/">Main</a> | <a href="/onboarding">Onboarding Tab</a></p>
    {f'<p class="ok">{html.escape(state["message"])}</p>' if state["message"] else ""}
    {f'<p class="err">{html.escape(state["error"])}</p>' if state["error"] else ""}

    <div class="card">
      <h3>Create Onboarding Link</h3>
      <form method="post" action="/onboarding-create-link">
        <select name="connection_id" required>{bot_options}</select>
        <input name="target_label" placeholder="target label (optional)">
        <input name="ttl_seconds" type="number" value="900" min="60" max="86400">
        <button type="submit">Create Link</button>
      </form>
    </div>

    <div class="card">
      <h3>Process Bot Updates</h3>
      <form method="post" action="/onboarding-process">
        <select name="connection_id" required>{bot_options}</select>
        <input name="limit" type="number" value="50" min="1" max="100">
        <input name="offset" placeholder="offset optional">
        <button type="submit">Process</button>
      </form>
      <form method="post" action="/refresh-data?next=/onboarding"><button type="submit">Refresh</button></form>
    </div>

    <div class="card">
      <h3>Onboarding Links</h3>
      <table>
        <thead><tr><th>ID</th><th>Conn</th><th>Target</th><th>Status</th><th>Chat</th><th>Context</th><th>Link</th><th>QR</th><th>Actions</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </main>
</body>
</html>
"""
    return HTMLResponse(page)


async def _admin_get(request: Request, path: str) -> tuple[int, str, object]:
    base = _base(request.session.get("gateway_url", ""))
    cookie = request.session.get("admin_cookie", "")
    if not cookie:
        return 401, "Login admin first", {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            urljoin(f"{base}/", path), headers=_build_admin_headers(cookie)
        )

    data: object = response.text
    if response.headers.get("content-type", "").startswith("application/json"):
        data = response.json()
    return response.status_code, response.text, data


async def _admin_post(
    request: Request, path: str, payload: dict
) -> tuple[int, str, object]:
    base = _base(request.session.get("gateway_url", ""))
    cookie = request.session.get("admin_cookie", "")
    if not cookie:
        return 401, "Login admin first", {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            urljoin(f"{base}/", path),
            headers={
                **_build_admin_headers(cookie),
                "Content-Type": "application/json",
            },
            json=payload,
        )

    data: object = response.text
    if response.headers.get("content-type", "").startswith("application/json"):
        data = response.json()
    return response.status_code, response.text, data


async def _admin_delete(request: Request, path: str) -> tuple[int, str, object]:
    base = _base(request.session.get("gateway_url", ""))
    cookie = request.session.get("admin_cookie", "")
    if not cookie:
        return 401, "Login admin first", {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.delete(
            urljoin(f"{base}/", path),
            headers=_build_admin_headers(cookie),
        )

    data: object = response.text
    if (
        response.headers.get("content-type", "").startswith("application/json")
        and response.text.strip()
    ):
        data = response.json()
    return response.status_code, response.text, data


async def _runtime_call(
    request: Request, method: str, path: str, payload: dict | None = None
) -> tuple[int, str, object]:
    base = _base(request.session.get("gateway_url", ""))
    token = request.session.get("dex_id_token", "")
    if not token:
        return 401, "Login with Dex first", {}

    async with httpx.AsyncClient(timeout=25.0) as client:
        if method == "GET":
            response = await client.get(
                urljoin(f"{base}/", path),
                headers=_build_runtime_headers(token),
                params=payload or {},
            )
        else:
            response = await client.post(
                urljoin(f"{base}/", path),
                headers={
                    **_build_runtime_headers(token),
                    "Content-Type": "application/json",
                },
                json=payload or {},
            )

    data: object = response.text
    if response.headers.get("content-type", "").startswith("application/json"):
        data = response.json()
    return response.status_code, response.text, data


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return _render(
        _get_state(request),
        request.session.get("connections", []),
        request.session.get("contexts", []),
        request.session.get("managed_secrets", []),
    )


@app.get("/onboarding", response_class=HTMLResponse)
async def onboarding_tab(request: Request) -> HTMLResponse:
    return _render_onboarding_tab(
        _get_state(request),
        request.session.get("connections", []),
        request.session.get("onboarding_links", []),
    )


@app.post("/login-admin")
async def login_admin(
    request: Request,
    gateway_url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    base = _base(gateway_url)
    request.session["gateway_url"] = base
    request.session["admin_username"] = username
    request.session["admin_password"] = password
    async with httpx.AsyncClient(follow_redirects=False, timeout=15.0) as client:
        try:
            response = await client.post(
                urljoin(f"{base}/", "admin/login"),
                data={"username": username, "password": password},
            )
        except httpx.ConnectError:
            request.session["error"] = (
                "Cannot reach gateway. Ensure port-forward is running and Gateway URL is correct."
            )
            return RedirectResponse(url="/", status_code=303)

    cookie = response.cookies.get("tg_admin_session")
    if not cookie:
        request.session["error"] = "Admin login failed."
    else:
        request.session["admin_cookie"] = cookie
        request.session["message"] = "Admin login successful."
    return RedirectResponse(url="/", status_code=303)


@app.post("/save-dex-config")
async def save_dex_config(
    request: Request,
    dex_issuer: str = Form(...),
    dex_client_id: str = Form(...),
    dex_client_secret: str = Form(default=""),
    dex_scopes: str = Form(default="openid profile email"),
    dex_redirect_uri: str = Form(default="http://localhost:8090/dex/callback"),
) -> RedirectResponse:
    request.session["dex_issuer"] = _base(dex_issuer)
    request.session["dex_client_id"] = dex_client_id.strip()
    request.session["dex_client_secret"] = dex_client_secret
    request.session["dex_scopes"] = dex_scopes.strip() or "openid profile email"
    request.session["dex_redirect_uri_override"] = (
        dex_redirect_uri.strip() or "http://localhost:8090/dex/callback"
    )
    request.session["message"] = "Dex config saved."
    return RedirectResponse(url="/", status_code=303)


@app.get("/dex/login")
async def dex_login(request: Request) -> RedirectResponse:
    issuer = _base(request.session.get("dex_issuer", "https://magarathea.ddns.net/dex"))
    client_id = (request.session.get("dex_client_id", "oauth2-proxy") or "").strip()
    scopes = (
        request.session.get("dex_scopes", "openid profile email")
        or "openid profile email"
    ).strip()
    redirect_uri = (
        request.session.get("dex_redirect_uri_override", "")
        or os.getenv("TESTER_DEX_REDIRECT_URI", "http://localhost:8090/dex/callback")
    ).strip()
    if not client_id:
        request.session["error"] = "Set Dex client id first."
        return RedirectResponse(url="/", status_code=303)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )

    request.session["dex_state"] = state
    request.session["dex_verifier"] = verifier
    request.session["dex_redirect_uri"] = redirect_uri

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return RedirectResponse(url=f"{issuer}/auth?{urlencode(params)}", status_code=302)


@app.get("/dex/callback")
async def dex_callback(
    request: Request, code: str = "", state: str = ""
) -> RedirectResponse:
    expected_state = request.session.get("dex_state", "")
    verifier = request.session.get("dex_verifier", "")
    redirect_uri = request.session.get("dex_redirect_uri", "")
    issuer = _base(request.session.get("dex_issuer", "https://magarathea.ddns.net/dex"))
    client_id = request.session.get("dex_client_id", "")
    client_secret = request.session.get("dex_client_secret", "")

    if not code:
        request.session["error"] = "Dex callback missing code."
        return RedirectResponse(url="/", status_code=303)
    if not state or state != expected_state:
        request.session["error"] = "Dex state mismatch."
        return RedirectResponse(url="/", status_code=303)

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if client_secret:
        form["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{issuer}/token", data=form)

    if response.status_code != 200:
        request.session["error"] = (
            f"Dex token exchange failed: {response.status_code} {response.text}"
        )
        return RedirectResponse(url="/", status_code=303)

    data = response.json()
    id_token = data.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        request.session["error"] = "Dex response missing id_token."
        return RedirectResponse(url="/", status_code=303)

    request.session["dex_id_token"] = id_token
    request.session["message"] = "Dex login successful; runtime JWT stored."
    return RedirectResponse(url="/", status_code=303)


@app.post("/dex/logout")
async def dex_logout(request: Request) -> RedirectResponse:
    request.session.pop("dex_id_token", None)
    request.session.pop("dex_state", None)
    request.session.pop("dex_verifier", None)
    request.session.pop("dex_redirect_uri", None)
    request.session["message"] = "Dex token cleared."
    return RedirectResponse(url="/", status_code=303)


async def _refresh_data_impl(request: Request, next_url: str = "/") -> RedirectResponse:
    error = await _fetch_and_store_admin_lists(request)
    if error:
        request.session["error"] = error
        return RedirectResponse(url=next_url, status_code=303)
    request.session["message"] = "Connections and contexts refreshed."
    return RedirectResponse(url=next_url, status_code=303)


async def _fetch_and_store_admin_lists(request: Request) -> str | None:
    code1, text1, data1 = await _admin_get(request, "api/admin/connections")
    code2, text2, data2 = await _admin_get(request, "api/admin/contexts")
    code3, text3, data3 = await _admin_get(request, "api/admin/secrets")
    code4, text4, data4 = await _admin_get(request, "api/admin/onboarding-links")
    if code1 != 200:
        return f"Connections fetch failed: {code1} {text1}"
    if code2 != 200:
        return f"Contexts fetch failed: {code2} {text2}"
    if code3 != 200:
        return f"Secrets fetch failed: {code3} {text3}"
    if code4 != 200:
        return f"Onboarding links fetch failed: {code4} {text4}"
    request.session["connections"] = data1 if isinstance(data1, list) else []
    request.session["contexts"] = data2 if isinstance(data2, list) else []
    request.session["managed_secrets"] = data3 if isinstance(data3, list) else []
    request.session["onboarding_links"] = data4 if isinstance(data4, list) else []
    return None


@app.get("/refresh-data")
async def refresh_data_get(request: Request, next: str = "/") -> RedirectResponse:
    next_url = next if next.startswith("/") else "/"
    return await _refresh_data_impl(request, next_url=next_url)


@app.post("/refresh-data")
async def refresh_data_post(request: Request, next: str = "/") -> RedirectResponse:
    next_url = next if next.startswith("/") else "/"
    return await _refresh_data_impl(request, next_url=next_url)


@app.post("/create-user-connection")
async def create_user_connection(
    request: Request,
    name: str = Form(...),
    phone_number: str = Form(...),
    secret_ref_session: str = Form(...),
) -> RedirectResponse:
    code, text, data = await _admin_post(
        request,
        "api/admin/connections",
        {
            "name": name,
            "type": "user",
            "phone_number": phone_number,
            "secret_ref_session": secret_ref_session,
        },
    )
    if code not in (200, 201):
        request.session["error"] = f"Create user connection failed: {code} {text}"
        return RedirectResponse(url="/", status_code=303)
    if isinstance(data, dict):
        request.session["connection_id"] = str(data.get("id", ""))
    request.session["message"] = "User connection created."
    return RedirectResponse(url="/refresh-data", status_code=303)


@app.post("/create-managed-secret")
async def create_managed_secret(
    request: Request,
    name: str = Form(...),
    value: str = Form(...),
    secret_type: str = Form(default="generic"),
) -> RedirectResponse:
    code, text, _ = await _admin_post(
        request,
        "api/admin/secrets",
        {
            "name": name,
            "value": value,
            "secret_type": secret_type or "generic",
        },
    )
    if code not in (200, 201):
        request.session["error"] = f"Create managed secret failed: {code} {text}"
        return RedirectResponse(url="/", status_code=303)
    request.session["message"] = "Managed secret created/rotated."
    return RedirectResponse(url="/refresh-data", status_code=303)


@app.post("/delete-managed-secret")
async def delete_managed_secret(
    request: Request,
    name: str = Form(...),
) -> RedirectResponse:
    code, text, _ = await _admin_delete(request, f"api/admin/secrets/{name}")
    if code not in (200, 204):
        request.session["error"] = f"Deactivate managed secret failed: {code} {text}"
        return RedirectResponse(url="/", status_code=303)
    request.session["message"] = f"Managed secret '{name}' deactivated."
    return RedirectResponse(url="/refresh-data", status_code=303)


@app.post("/delete-connection")
async def delete_connection(
    request: Request,
    connection_id: str = Form(...),
) -> RedirectResponse:
    code, text, _ = await _admin_delete(
        request, f"api/admin/connections/{int(connection_id)}"
    )
    if code not in (200, 204):
        request.session["error"] = f"Deactivate connection failed: {code} {text}"
        return RedirectResponse(url="/", status_code=303)
    request.session["message"] = f"Connection {connection_id} deactivated."
    return RedirectResponse(url="/refresh-data", status_code=303)


@app.post("/onboarding-create-link")
async def onboarding_create_link(
    request: Request,
    connection_id: str = Form(...),
    target_label: str = Form(default=""),
    ttl_seconds: str = Form(default="900"),
) -> HTMLResponse:
    code, text, _ = await _admin_post(
        request,
        "api/admin/onboarding-links",
        {
            "connection_id": int(connection_id),
            "target_label": target_label or None,
            "ttl_seconds": int(ttl_seconds or "900"),
        },
    )
    if code not in (200, 201):
        request.session["error"] = f"Create onboarding link failed: {code} {text}"
    else:
        request.session["message"] = "Onboarding link created."

    refresh_error = await _fetch_and_store_admin_lists(request)
    if refresh_error:
        request.session["error"] = refresh_error

    state = _get_state(request)
    return _render_onboarding_tab(
        state,
        request.session.get("connections", []),
        request.session.get("onboarding_links", []),
    )


@app.post("/onboarding-process")
async def onboarding_process(
    request: Request,
    connection_id: str = Form(...),
    limit: str = Form(default="50"),
    offset: str = Form(default=""),
) -> HTMLResponse:
    payload: dict[str, int | None] = {
        "connection_id": int(connection_id),
        "limit": int(limit or "50"),
    }
    if offset.strip():
        payload["offset"] = int(offset.strip())
    code, text, data = await _admin_post(
        request, "api/admin/onboarding-links/process", payload
    )
    if code != 200:
        request.session["error"] = f"Process onboarding failed: {code} {text}"
    else:
        request.session["message"] = f"Processed onboarding updates: {data}"

    refresh_error = await _fetch_and_store_admin_lists(request)
    if refresh_error:
        request.session["error"] = refresh_error

    state = _get_state(request)
    return _render_onboarding_tab(
        state,
        request.session.get("connections", []),
        request.session.get("onboarding_links", []),
    )


@app.post("/onboarding-delete-link")
async def onboarding_delete_link(
    request: Request,
    link_id: str = Form(...),
) -> HTMLResponse:
    code, text, _ = await _admin_delete(
        request, f"api/admin/onboarding-links/{int(link_id)}"
    )
    if code not in (200, 204):
        request.session["error"] = f"Delete onboarding link failed: {code} {text}"
    else:
        request.session["message"] = f"Onboarding link {link_id} deleted."

    refresh_error = await _fetch_and_store_admin_lists(request)
    if refresh_error:
        request.session["error"] = refresh_error

    state = _get_state(request)
    return _render_onboarding_tab(
        state,
        request.session.get("connections", []),
        request.session.get("onboarding_links", []),
    )


@app.post("/create-bot-connection")
async def create_bot_connection(
    request: Request,
    name: str = Form(...),
    secret_ref_token: str = Form(...),
) -> RedirectResponse:
    code, text, _ = await _admin_post(
        request,
        "api/admin/connections",
        {
            "name": name,
            "type": "bot",
            "secret_ref_token": secret_ref_token,
        },
    )
    if code not in (200, 201):
        request.session["error"] = f"Create bot connection failed: {code} {text}"
        return RedirectResponse(url="/", status_code=303)
    request.session["message"] = "Bot connection created."
    return RedirectResponse(url="/refresh-data", status_code=303)


@app.post("/create-context")
async def create_context(
    request: Request,
    connection_id: str = Form(...),
    name: str = Form(...),
    mode: str = Form(...),
    chat_id: str = Form(...),
) -> RedirectResponse:
    code, text, data = await _admin_post(
        request,
        "api/admin/contexts",
        {
            "connection_id": int(connection_id),
            "name": name,
            "mode": mode,
            "chat_id": chat_id,
        },
    )
    if code not in (200, 201):
        request.session["error"] = f"Create context failed: {code} {text}"
        return RedirectResponse(url="/", status_code=303)
    if isinstance(data, dict):
        request.session["context_id"] = str(data.get("id", ""))
    request.session["message"] = "Context created."
    return RedirectResponse(url="/refresh-data", status_code=303)


@app.post("/start-user-login")
async def start_user_login(
    request: Request, connection_id: str = Form(...)
) -> RedirectResponse:
    code, text, data = await _admin_post(
        request,
        "api/admin/user-logins/start",
        {"connection_id": int(connection_id)},
    )
    request.session["connection_id"] = connection_id
    request.session["last_response"] = _json_pretty(data)
    if code != 200:
        request.session["error"] = f"Start login failed: {code} {text}"
    else:
        request.session["message"] = "Code sent. Verify it below."
    return RedirectResponse(url="/", status_code=303)


@app.post("/verify-user-login")
async def verify_user_login(
    request: Request,
    connection_id: str = Form(...),
    code: str = Form(...),
    password: str = Form(default=""),
) -> RedirectResponse:
    payload: dict[str, str | int] = {"connection_id": int(connection_id), "code": code}
    if password:
        payload["password"] = password
    status_code, text, data = await _admin_post(
        request, "api/admin/user-logins/verify", payload
    )
    request.session["connection_id"] = connection_id
    request.session["last_response"] = _json_pretty(data)
    if status_code != 200:
        request.session["error"] = f"Verify failed: {status_code} {text}"
    else:
        request.session["message"] = "User session stored in secret backend."
    return RedirectResponse(url="/", status_code=303)


@app.post("/runtime-whoami")
async def runtime_whoami(request: Request) -> RedirectResponse:
    code, text, data = await _runtime_call(request, "GET", "gateway/whoami")
    request.session["last_response"] = _json_pretty(data)
    if code != 200:
        request.session["error"] = f"whoami failed: {code} {text}"
    else:
        request.session["message"] = "whoami OK"
    return RedirectResponse(url="/", status_code=303)


@app.post("/runtime-send")
async def runtime_send(
    request: Request,
    context_id: str = Form(...),
    text: str = Form(...),
) -> RedirectResponse:
    code, raw, data = await _runtime_call(
        request,
        "POST",
        f"gateway/contexts/{int(context_id)}/send",
        {"text": text},
    )
    request.session["context_id"] = context_id
    request.session["last_response"] = _json_pretty(data)
    if code != 200:
        request.session["error"] = f"send failed: {code} {raw}"
    else:
        request.session["message"] = "Message sent."
    return RedirectResponse(url="/", status_code=303)


@app.post("/runtime-updates")
async def runtime_updates(
    request: Request,
    context_id: str = Form(...),
    offset: str = Form(default=""),
) -> RedirectResponse:
    query: dict[str, str] = {}
    if offset.strip():
        query["offset"] = offset.strip()

    code, raw, data = await _runtime_call(
        request,
        "GET",
        f"gateway/contexts/{int(context_id)}/updates",
        query,
    )
    request.session["context_id"] = context_id
    request.session["last_response"] = _json_pretty(data)
    if code != 200:
        request.session["error"] = f"updates failed: {code} {raw}"
    else:
        request.session["message"] = "Updates fetched."
    return RedirectResponse(url="/", status_code=303)


@app.post("/runtime-otp-issue")
async def runtime_otp_issue(
    request: Request,
    context_id: str = Form(...),
    target_label: str = Form(default=""),
    purpose: str = Form(default="auth"),
    ttl_seconds: str = Form(default="300"),
    length: str = Form(default="6"),
) -> RedirectResponse:
    code, raw, data = await _runtime_call(
        request,
        "POST",
        "gateway/otp/issue",
        {
            "context_id": int(context_id),
            "target_label": target_label or None,
            "purpose": purpose or "auth",
            "ttl_seconds": int(ttl_seconds or "300"),
            "length": int(length or "6"),
        },
    )
    request.session["context_id"] = context_id
    request.session["last_response"] = _json_pretty(data)
    if code != 200:
        request.session["error"] = f"otp issue failed: {code} {raw}"
    else:
        request.session["message"] = "OTP issued and sent through context."
    return RedirectResponse(url="/", status_code=303)


@app.post("/runtime-otp-verify")
async def runtime_otp_verify(
    request: Request,
    challenge_id: str = Form(...),
    code_value: str = Form(alias="code"),
) -> RedirectResponse:
    code, raw, data = await _runtime_call(
        request,
        "POST",
        "gateway/otp/verify",
        {"challenge_id": challenge_id, "code": code_value},
    )
    request.session["last_response"] = _json_pretty(data)
    if code != 200:
        request.session["error"] = f"otp verify failed: {code} {raw}"
    else:
        request.session["message"] = "OTP verify request completed."
    return RedirectResponse(url="/", status_code=303)
