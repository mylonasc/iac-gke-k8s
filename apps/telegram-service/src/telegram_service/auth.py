from itsdangerous import BadSignature, URLSafeSerializer
from passlib.context import CryptContext

from telegram_service.config import get_settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
settings = get_settings()
session_signer = URLSafeSerializer(settings.admin_session_secret, salt="tg-admin")


def hash_password(raw_password: str) -> str:
    return pwd_context.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    return pwd_context.verify(raw_password, password_hash)


def create_admin_session(username: str) -> str:
    return session_signer.dumps({"username": username})


def decode_admin_session(token: str) -> str | None:
    try:
        payload = session_signer.loads(token)
    except BadSignature:
        return None
    return payload.get("username")
