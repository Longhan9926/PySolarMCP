from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "case"


def stable_hash_bytes(data: bytes, length: int = 10) -> str:
    return hashlib.sha256(data).hexdigest()[:length]


def stable_hash_json(data: Any, length: int = 10) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return stable_hash_bytes(encoded, length)


def hash_file(path: Path, length: int = 16) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


def create_run_id(name: str, input_data: Any) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}_{slugify(name)}_{stable_hash_json(input_data, 8)}"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

