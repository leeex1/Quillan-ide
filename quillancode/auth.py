"""Interactive credential storage for user-supplied provider API keys.

Keys are written to ~/.quillancode/auth.json with owner-only permissions where
the OS supports it, are never echoed, and always lose to environment variables.
"""

from __future__ import annotations

import getpass
import json
import os
import stat
from pathlib import Path
from typing import Any

from .models import ProviderSpec


class AuthStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path).expanduser()
            if path
            else (Path.home() / ".quillancode" / "auth.json")
        )

    def read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        try:
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def set(self, provider: str, key: str) -> None:
        data = self.read()
        entries = data.setdefault("keys", {})
        entries[provider] = key
        self.write(data)

    def remove(self, provider: str) -> bool:
        data = self.read()
        entries = data.get("keys", {})
        if provider not in entries:
            return False
        del entries[provider]
        self.write(data)
        return True

    def get(self, provider: str) -> str:
        env_key = os.environ.get(f"QUILLANCODE_KEY_{provider.upper()}", "")
        if env_key:
            return env_key
        return str(self.read().get("keys", {}).get(provider, ""))

    def resolve(self, spec: ProviderSpec) -> str:
        env_value = os.environ.get(spec.api_key_env, "") if spec.api_key_env else ""
        return env_value or self.get(spec.name)

    def list(self) -> list[dict[str, str]]:
        return [
            {"provider": name, "key": "****" + str(value)[-4:]}
            for name, value in sorted(self.read().get("keys", {}).items())
        ]


def login(provider: str, store: AuthStore | None = None) -> str:
    store = store or AuthStore()
    key = getpass.getpass(f"API key for {provider}: ").strip()
    if not key:
        raise ValueError("empty key")
    store.set(provider, key)
    return f"stored key for {provider} in {store.path} (value withheld)"
