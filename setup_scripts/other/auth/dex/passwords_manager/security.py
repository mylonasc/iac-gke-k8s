from __future__ import annotations

import re
import shutil
import subprocess

try:
    import bcrypt  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency at runtime
    bcrypt = None

_BCRYPT_RE = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")


def hash_password(plain_password: str, rounds: int = 10) -> str:
    if not plain_password:
        raise ValueError("Password cannot be empty.")

    if bcrypt is not None:
        return bcrypt.hashpw(
            plain_password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)
        ).decode("utf-8")

    if shutil.which("htpasswd"):
        proc = subprocess.run(
            ["htpasswd", "-bnBC", str(rounds), "", plain_password],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.replace(":", "").strip()

    raise RuntimeError(
        "No bcrypt backend available. Install 'bcrypt' (pip install bcrypt) or "
        "install 'htpasswd' and ensure it is on PATH."
    )


def looks_like_bcrypt_hash(value: str) -> bool:
    return bool(_BCRYPT_RE.match(value))
