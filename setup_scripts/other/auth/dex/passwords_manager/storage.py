from __future__ import annotations

import os
from pathlib import Path

import yaml

from .models import StaticPasswordUser


class PasswordStorage:
    def __init__(self, file_path: str | Path) -> None:
        self.path = Path(file_path)

    def load(self) -> list[StaticPasswordUser]:
        if not self.path.exists():
            return []

        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if data is None:
            return []
        if not isinstance(data, list):
            raise ValueError("static-passwords file must be a YAML list.")

        users: list[StaticPasswordUser] = []
        for idx, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"Entry #{idx} must be a YAML object.")
            users.append(StaticPasswordUser.from_dict(item))
        return users

    def save(self, users: list[StaticPasswordUser]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [u.to_dict() for u in users]
        serialized = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)

        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        tmp_path.write_text(serialized, encoding="utf-8")
        os.replace(tmp_path, self.path)
