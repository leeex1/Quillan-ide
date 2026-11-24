"""GitHub REST workflows via urllib (token taken from env, never stored)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


def _request(
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    api: str = DEFAULT_API,
) -> Any:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "quillancode/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        api.rstrip("/") + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        exc.close()
        raise GitHubError(f"GitHub HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc


def issues(repo: str, api: str = DEFAULT_API, limit: int = 10) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"state": "open", "per_page": limit})
    data = _request(f"/repos/{repo}/issues?{query}", api=api)
    return [{"number": i.get("number"), "title": i.get("title")} for i in data]


def pull_requests(
    repo: str, api: str = DEFAULT_API, limit: int = 10
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"state": "open", "per_page": limit})
    data = _request(f"/repos/{repo}/pulls?{query}", api=api)
    return [{"number": p.get("number"), "title": p.get("title")} for p in data]


def comment(
    repo: str, number: int, text: str, api: str = DEFAULT_API
) -> dict[str, Any]:
    return _request(
        f"/repos/{repo}/issues/{number}/comments",
        method="POST",
        body={"body": text},
        api=api,
    )
