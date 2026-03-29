from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StaticPasswordUser:
    email: str
    hash: str
    username: str
    user_id: str

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "StaticPasswordUser":
        return cls(
            email=str(raw.get("email", "")).strip(),
            hash=str(raw.get("hash", "")).strip(),
            username=str(raw.get("username", "")).strip(),
            user_id=str(raw.get("userID", "")).strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "email": self.email,
            "hash": self.hash,
            "username": self.username,
            "userID": self.user_id,
        }
