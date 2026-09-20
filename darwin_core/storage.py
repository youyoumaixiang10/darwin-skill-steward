"""Small runtime-neutral persistence boundary for Darwin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RuntimeStore:
    def __init__(self, root: Path, runtime_id: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.runtime_id = runtime_id
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("storage path must stay inside runtime root")
        return path

    def append_jsonl(self, relative: str, value: dict[str, Any]) -> None:
        path = self._path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")

    def read_jsonl(self, relative: str) -> list[dict[str, Any]]:
        path = self._path(relative)
        if not path.is_file():
            return []
        values: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                values.append(value)
        return values
