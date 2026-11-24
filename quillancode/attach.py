"""Client for a running quillancode HTTP server (`attach <url>` parity)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class AttachError(RuntimeError):
    pass


def health(base_url: str) -> dict[str, Any]:
    return _get(base_url.rstrip("/") + "/health")


def tools(base_url: str) -> list[dict[str, Any]]:
    return list(_get(base_url.rstrip("/") + "/tools").get("tools", []))


def chat(base_url: str, message: str, provider: str | None = None) -> str:
    payload: dict[str, Any] = {"message": message}
    if provider:
        payload["provider"] = provider
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise AttachError(f"server HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AttachError(f"cannot reach server: {exc}") from exc
    return str(data.get("answer", ""))


def _get(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        exc.close()
        raise AttachError(f"server HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AttachError(f"cannot reach server: {exc}") from exc
