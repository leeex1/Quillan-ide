"""Extension API: drop-in Python modules that register tools/providers/hooks.

An extension defines `register(registry, config, hooks)` and may add tools with
`registry.register(ToolInstance)`. No entry points or network installs required.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .hooks import HookBus


@dataclass
class Extension:
    name: str
    path: Path
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "path": str(self.path), "source": self.source}


class ExtensionManager:
    def roots(self, cwd: str | Path | None = None) -> list[tuple[str, Path]]:
        base = Path(cwd) if cwd else Path.cwd()
        return [
            ("workspace", base / ".quillancode" / "extensions"),
            ("user", Path.home() / ".quillancode" / "extensions"),
            ("bundled", Path(__file__).parent / "extensions_built"),
        ]

    def discover(self, cwd: str | Path | None = None) -> list[Extension]:
        found: dict[str, Extension] = {}
        for source, root in self.roots(cwd):
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                if path.stem not in found:
                    found[path.stem] = Extension(path.stem, path, source)
        return sorted(found.values(), key=lambda e: e.name)

    def load(
        self,
        registry: Any,
        config: Config,
        hooks: HookBus,
        cwd: str | Path | None = None,
    ) -> list[str]:
        import sys

        disabled = set(config.get("extensions.disabled", []) or [])
        loaded: list[str] = []
        self.errors: dict[str, str] = {}
        for ext in self.discover(cwd):
            if ext.name in disabled:
                continue
            module_name = f"quillancode_user_ext_{ext.name}"
            spec = importlib.util.spec_from_file_location(module_name, ext.path)
            if spec is None or spec.loader is None:
                self.errors[ext.name] = "cannot create module spec"
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                register = getattr(module, "register", None)
                if callable(register):
                    register(registry, config, hooks)
                loaded.append(ext.name)
            except Exception as exc:
                self.errors[ext.name] = f"{type(exc).__name__}: {exc}"
        return loaded
