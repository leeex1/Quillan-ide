"""Bridge to the compiled C++ hot-path core, with automatic Python fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

BINARY = Path(__file__).parent / "bin" / "qc_core.exe"


def enabled() -> bool:
    return BINARY.is_file()


def build_command() -> str | None:
    return shutil.which("clang++") or (
        r"C:\Program Files\LLVM\bin\clang++.exe"
        if Path(r"C:\Program Files\LLVM\bin\clang++.exe").is_file()
        else None
    )


def _run(args: list[str], timeout: int = 60, stdin: str | None = None) -> str | None:
    if not enabled():
        return None
    try:
        proc = subprocess.run(
            [str(BINARY), *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def glob(root: Path, pattern: str, limit: int = 1000) -> str | None:
    return _run(["glob", str(root), pattern, str(limit)])


def grep(
    root: Path, pattern: str, name_glob: str = "*", limit: int = 200
) -> str | None:
    return _run(["grep", str(root), pattern, name_glob, str(limit)])


def read(root: Path, target: str, offset: int = 0, limit: int = 2000) -> str | None:
    return _run(["read", str(root), target, str(offset), str(limit)])


def write(root: Path, target: str, content: str) -> str | None:
    return _run(["write", str(root), target], stdin=content)


def edit(
    root: Path, target: str, old: str, new: str, replace_all: bool = False
) -> str | None:
    return _run(["edit", str(root), target, old, new, "1" if replace_all else "0"])


def list_dir(root: Path, target: str = ".") -> str | None:
    return _run(["list", str(root), target])


def file_hash(root: Path, target: str) -> str | None:
    return _run(["hash", str(root), target])


def append(path: Path, line: str) -> str | None:
    return _run(["append", str(path)], stdin=line)


def validate(root: Path, target: str) -> str | None:
    return _run(["validate", str(root), target])


def bench(root: Path, pattern: str, rounds: int = 3) -> str | None:
    return _run(["bench", str(root), pattern, str(rounds)], timeout=300)


def selftest() -> str:
    """Exercise every native command in a temp workspace."""
    import tempfile

    if not enabled():
        return "NATIVE_SELFTEST_SKIPPED (core not built)"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write(root, "sub/a.txt", "alpha beta\n")
        r = read(root, "sub/a.txt", 0, 5) or ""
        edit(root, "sub/a.txt", "alpha", "gamma")
        content = (root / "sub" / "a.txt").read_text(encoding="utf-8")
        listed = list_dir(root, "sub") or ""
        digest = file_hash(root, "sub/a.txt") or ""
        blocked = validate(root, str(root.parent / "escape.txt")) or ""
        ok = (
            "alpha" in r
            and "gamma" in content
            and "a.txt" in listed
            and len(digest.strip()) == 16
            and "BLOCKED" in blocked
        )
    return "NATIVE_SELFTEST_OK" if ok else "NATIVE_SELFTEST_FAIL"


def info() -> dict[str, Any]:
    return {
        "enabled": enabled(),
        "binary": str(BINARY),
        "compiler": build_command(),
        "size": BINARY.stat().st_size if enabled() else 0,
    }
