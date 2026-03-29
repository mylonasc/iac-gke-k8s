#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from passwords_manager.controller import PasswordsController, PasswordsError


def parse_args() -> argparse.Namespace:
    default_file = Path(__file__).with_name("static-passwords.yaml")
    parser = argparse.ArgumentParser(
        description="Manage Dex static passwords YAML file."
    )
    parser.add_argument(
        "--file",
        default=str(default_file),
        help="Path to static-passwords.yaml (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from passwords_manager.tui import PasswordsManagerApp
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            print("ERROR: Missing dependency: textual", file=sys.stderr)
            print("Install with: pip install textual", file=sys.stderr)
            return 1
        raise

    try:
        controller = PasswordsController(Path(args.file))
    except PasswordsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive startup guard
        print(f"ERROR: Failed to load file: {exc}", file=sys.stderr)
        return 1

    app = PasswordsManagerApp(controller)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
