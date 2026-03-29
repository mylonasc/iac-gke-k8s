from __future__ import annotations

from pathlib import Path

from .models import StaticPasswordUser
from .security import hash_password, looks_like_bcrypt_hash
from .storage import PasswordStorage


class PasswordsError(ValueError):
    pass


class PasswordsController:
    def __init__(self, file_path: str | Path) -> None:
        self._storage = PasswordStorage(file_path)
        self._users: list[StaticPasswordUser] = []
        self._dirty = False
        self.reload()

    @property
    def file_path(self) -> Path:
        return self._storage.path

    @property
    def dirty(self) -> bool:
        return self._dirty

    def reload(self) -> None:
        self._users = self._storage.load()
        self._validate_all()
        self._dirty = False

    def save(self) -> None:
        self._validate_all()
        self._storage.save(self._users)
        self._dirty = False

    def list_users(self) -> list[StaticPasswordUser]:
        return list(self._users)

    def create_user(
        self, email: str, username: str, user_id: str, plain_password: str
    ) -> None:
        email = email.strip()
        username = username.strip()
        user_id = user_id.strip()

        self._validate_required(email=email, username=username, user_id=user_id)
        self._assert_uniqueness(email=email, username=username, user_id=user_id)

        try:
            password_hash = hash_password(plain_password)
        except (ValueError, RuntimeError) as exc:
            raise PasswordsError(str(exc)) from exc

        user = StaticPasswordUser(
            email=email,
            username=username,
            user_id=user_id,
            hash=password_hash,
        )
        self._users.append(user)
        self._dirty = True

    def update_user(
        self, current_user_id: str, email: str, username: str, user_id: str
    ) -> None:
        current_user = self._find_by_user_id(current_user_id)

        email = email.strip()
        username = username.strip()
        user_id = user_id.strip()

        self._validate_required(email=email, username=username, user_id=user_id)
        self._assert_uniqueness(
            email=email,
            username=username,
            user_id=user_id,
            ignore_user_id=current_user_id,
        )

        current_user.email = email
        current_user.username = username
        current_user.user_id = user_id
        self._dirty = True

    def update_password(self, user_id: str, plain_password: str) -> None:
        user = self._find_by_user_id(user_id)
        try:
            user.hash = hash_password(plain_password)
        except (ValueError, RuntimeError) as exc:
            raise PasswordsError(str(exc)) from exc
        self._dirty = True

    def delete_user(self, user_id: str) -> None:
        user = self._find_by_user_id(user_id)
        self._users.remove(user)
        self._dirty = True

    def _find_by_user_id(self, user_id: str) -> StaticPasswordUser:
        for user in self._users:
            if user.user_id == user_id:
                return user
        raise PasswordsError(f"User not found: {user_id}")

    def _validate_required(self, *, email: str, username: str, user_id: str) -> None:
        if not email:
            raise PasswordsError("Email is required.")
        if not username:
            raise PasswordsError("Username is required.")
        if not user_id:
            raise PasswordsError("userID is required.")

    def _assert_uniqueness(
        self,
        *,
        email: str,
        username: str,
        user_id: str,
        ignore_user_id: str | None = None,
    ) -> None:
        for user in self._users:
            if ignore_user_id and user.user_id == ignore_user_id:
                continue
            if user.email == email:
                raise PasswordsError(f"Email already exists: {email}")
            if user.username == username:
                raise PasswordsError(f"Username already exists: {username}")
            if user.user_id == user_id:
                raise PasswordsError(f"userID already exists: {user_id}")

    def _validate_all(self) -> None:
        seen_emails: set[str] = set()
        seen_usernames: set[str] = set()
        seen_user_ids: set[str] = set()
        for idx, user in enumerate(self._users, start=1):
            if not user.email:
                raise PasswordsError(f"Entry #{idx}: email is required.")
            if not user.username:
                raise PasswordsError(f"Entry #{idx}: username is required.")
            if not user.user_id:
                raise PasswordsError(f"Entry #{idx}: userID is required.")
            if not user.hash:
                raise PasswordsError(f"Entry #{idx}: hash is required.")
            if not looks_like_bcrypt_hash(user.hash):
                raise PasswordsError(
                    f"Entry #{idx}: hash does not look like a bcrypt hash."
                )
            if user.email in seen_emails:
                raise PasswordsError(f"Duplicate email found: {user.email}")
            if user.username in seen_usernames:
                raise PasswordsError(f"Duplicate username found: {user.username}")
            if user.user_id in seen_user_ids:
                raise PasswordsError(f"Duplicate userID found: {user.user_id}")

            seen_emails.add(user.email)
            seen_usernames.add(user.username)
            seen_user_ids.add(user.user_id)
