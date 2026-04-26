# Onboarding Client

Python FastAPI onboarding gateway for invitation delivery, profile collection, and role assignment.

## Current scope

- Admin API for roles and invitations
- Email invitation delivery via Resend
- Public confirmation and profile submission flow
- Runtime role lookup for Dex-authenticated users
- SQLite-first persistence and automated tests

## Local run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
uvicorn onboarding_client.main:app --reload
```

## Test

```bash
pytest
```
