"""Read-only inspector for model tensors, checkpoints and binary artifacts."""

from __future__ import annotations

import ast
import json
import struct
import zipfile
from pathlib import Path
from typing import Any

SUFFIX_KIND = {
    ".pt": "pytorch",
    ".pth": "pytorch",
    ".ckpt": "pytorch",
    ".safetensors": "safetensors",
    ".gguf": "gguf",
    ".ggml": "gguf",
    ".npy": "numpy",
    ".npz": "numpy",
    ".onnx": "onnx",
    ".bin": "binary",
    ".model": "binary",
}


def inspect(path: Path) -> dict[str, Any]:
    path = Path(path)
    result: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "suffix": path.suffix.lower(),
        "size": path.stat().st_size if path.is_file() else 0,
        "kind": SUFFIX_KIND.get(path.suffix.lower(), "binary"),
        "tensors": [],
        "entries": [],
        "notes": [],
    }
    if not path.is_file():
        result["error"] = "not a file"
        return result
    kind = result["kind"]
    try:
        if kind == "safetensors":
            with path.open("rb") as fh:
                length = struct.unpack("<Q", fh.read(8))[0]
                header = json.loads(fh.read(length).decode("utf-8"))
            for key, value in header.items():
                if key == "__metadata__":
                    continue
                result["tensors"].append(
                    {
                        "name": key,
                        "dtype": value.get("dtype", "?"),
                        "shape": value.get("shape", []),
                        "bytes": (
                            value.get("data_offsets", [0, 0])[1]
                            - value.get("data_offsets", [0, 0])[0]
                        ),
                    }
                )
            result["notes"].append(
                f"{len(result['tensors'])} tensors from safetensors header"
            )
        elif kind == "pytorch" and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                data = [n for n in names if n.startswith("data/")]
                result["entries"] = [
                    {"name": n, "size": zf.getinfo(n).file_size} for n in names[:200]
                ]
                result["tensors"] = [
                    {"name": n.split("/")[-1], "bytes": zf.getinfo(n).file_size}
                    for n in data[:500]
                ]
                result["notes"].append(f"zip checkpoint with {len(data)} tensor blobs")
        elif kind == "gguf":
            with path.open("rb") as fh:
                magic = fh.read(4)
                if magic == b"GGUF":
                    version, tensor_count, kv_count = struct.unpack("<IQQ", fh.read(20))
                    result["notes"].append(
                        f"GGUF v{version}: {tensor_count} tensors, {kv_count} metadata entries"
                    )
                    result["meta"] = {
                        "version": version,
                        "tensors": tensor_count,
                        "kv": kv_count,
                    }
                else:
                    result["notes"].append("not a GGUF header; raw binary preview")
        elif (
            kind == "numpy"
            and path.suffix.lower() == ".npz"
            and zipfile.is_zipfile(path)
        ):
            with zipfile.ZipFile(path) as zf:
                result["entries"] = [
                    {"name": n, "size": zf.getinfo(n).file_size}
                    for n in zf.namelist()[:200]
                ]
                result["notes"].append(
                    f"npz archive with {len(result['entries'])} arrays"
                )
        elif kind == "numpy" and path.suffix.lower() == ".npy":
            with path.open("rb") as fh:
                fh.read(8)
                header = ast.literal_eval(
                    fh.read(4096).decode("latin-1", errors="replace").strip()
                )
            result["meta"] = {
                "dtype": str(header.get("descr")),
                "shape": header.get("shape"),
            }
            result["notes"].append("numpy array header")
        else:
            result["notes"].append("binary artifact; hex preview available")
    except (OSError, ValueError, struct.error, zipfile.BadZipFile, SyntaxError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    with path.open("rb") as fh:
        result["hex"] = fh.read(256).hex(" ")
    return result
