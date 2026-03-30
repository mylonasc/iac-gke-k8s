# API Reference

## Auth models

- Runtime gateway endpoints use Dex JWT bearer tokens.
- Admin API endpoints use admin session cookie from `/admin/login`.

## Admin/config API

Base: `/api/admin`

- `GET /users`
- `POST /users`
- `GET /connections`
- `POST /connections`
- `GET /contexts`
- `POST /contexts`
- `GET /audit-logs`
- `POST /user-logins/start`
- `POST /user-logins/verify`
- `GET /secrets`
- `POST /secrets`
- `POST /secrets/{name}/rotate`
- `POST /secrets/{name}/validate`
- `DELETE /secrets/{name}`
- `GET /onboarding-links`
- `POST /onboarding-links`
- `POST /onboarding-links/process`

### Example: create connection

```json
{
  "name": "bot-main",
  "type": "bot",
  "secret_ref_token": "gsm://projects/myproj/secrets/bot-main-token/versions/latest"
}
```

`secret_ref_token` / `secret_ref_session` support:

- `managed://<name>`
- `env://ENV_VAR_NAME`
- `gsm://projects/<project>/secrets/<name>/versions/<version>`

### Example: create context

```json
{
  "connection_id": 1,
  "name": "alerts-send",
  "mode": "send_only",
  "chat_id": "-1001234567890"
}
```

## Runtime gateway API

Base: `/gateway`

- `GET /whoami`
- `POST /contexts/{context_id}/send`
- `GET /contexts/{context_id}/updates`
- `POST /webhook/{connection_name}`
- `POST /otp/issue`
- `POST /otp/verify`

## Configuration endpoint

Base: `/api/config`

- `GET /connections`
- `POST /connections`
- `POST /contexts`

This endpoint group is intended for provisioning new Telegram connections and contexts.

### Context mode rules

- `send_only`: `send` allowed, `updates` denied.
- `send_receive`: both allowed.
- `receive_only`: `updates` allowed, `send` denied.

Runtime send/updates work with both connection types:

- `bot`: uses Telegram Bot API.
- `user`: uses MTProto session from `secret_ref_session`.

## OTP endpoints

### Issue OTP

`POST /gateway/otp/issue`

```json
{
  "context_id": 3,
  "target_label": "user@example.com",
  "purpose": "login",
  "ttl_seconds": 300,
  "length": 6
}
```

## Onboarding endpoints

Create onboarding link for a bot connection:

`POST /api/admin/onboarding-links`

```json
{
  "connection_id": 5,
  "target_label": "user@example.com",
  "ttl_seconds": 900
}
```

Process pending `/start <token>` updates from Telegram for that bot:

`POST /api/admin/onboarding-links/process`

```json
{
  "connection_id": 5,
  "limit": 50
}
```

### Verify OTP

`POST /gateway/otp/verify`

```json
{
  "challenge_id": "<challenge-id>",
  "code": "123456"
}
```
