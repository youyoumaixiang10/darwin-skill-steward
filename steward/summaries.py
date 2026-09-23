"""One-line Chinese function summaries, written once by the Agent and cached.

Descriptions are often long or English. The Agent writes a short Chinese
summary per Skill plus whether it is a general capability (常驻) or a specific
task (工作流). The cache key includes the description, so a changed
description automatically needs a fresh entry.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

MAX_SUMMARY_CHARS = 40
LAYER_HINTS = ("常驻", "工作流")


def summary_key(name: str, description: str) -> str:
    return hashlib.sha256(f"{name}\0{description}".encode("utf-8")).hexdigest()[:16]


def _path(home: Path) -> Path:
    return home / "summaries.json"


def load(home: Path) -> dict[str, Any]:
    try:
        value = json.loads(_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def lookup(cache: dict[str, Any], key: str) -> tuple[str, str | None]:
    """Return (summary, layer hint). Older entries are plain strings without a hint."""
    value = cache.get(key)
    if isinstance(value, dict):
        layer = value.get("layer")
        return str(value.get("summary") or ""), layer if layer in LAYER_HINTS else None
    return (str(value), None) if value else ("", None)


def save(home: Path, updates: dict[str, Any]) -> int:
    cache = load(home)
    saved = 0
    for key, value in updates.items():
        if not re.fullmatch(r"[0-9a-f]{16}", str(key)):
            continue
        if isinstance(value, dict):
            summary = " ".join(str(value.get("summary") or "").split())[:MAX_SUMMARY_CHARS]
            layer = value.get("layer") if value.get("layer") in LAYER_HINTS else None
        else:
            summary, layer = " ".join(str(value).split())[:MAX_SUMMARY_CHARS], None
        if not summary:
            continue
        cache[key] = {"summary": summary, "layer": layer} if layer else {"summary": summary}
        saved += 1
    home.mkdir(parents=True, exist_ok=True)
    temp = _path(home).with_suffix(".tmp")
    temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, _path(home))
    return saved


def fallback(description: str) -> str:
    """A best-effort summary used until the Agent writes a real one."""
    text = " ".join(description.split())
    if not text:
        return "（没有写简介）"
    if re.search(r"[一-鿿]", text[:20]):
        text = re.split(r"[。；;]|当用户|触发场景", text, maxsplit=1)[0]
        return text[:30] + ("…" if len(text) > 30 else "")
    text = re.split(r"(?<=\.)\s|\s[—-]\s", text, maxsplit=1)[0]
    return text[:50] + ("…" if len(text) > 50 else "")


def todo(entries: Iterable[dict[str, Any]], cache: dict[str, Any]) -> list[dict[str, str]]:
    """Entries still missing a summary, or a layer hint where one is needed.

    Each entry: {"key", "name", "description", "needs_layer": bool}.
    """
    seen: set[str] = set()
    missing = []
    for entry in entries:
        key = entry["key"]
        if key in seen or not entry.get("description"):
            continue
        seen.add(key)
        summary, layer = lookup(cache, key)
        if summary and (layer or not entry.get("needs_layer")):
            continue
        missing.append(
            {
                "key": key,
                "name": entry["name"],
                "description": entry["description"][:600],
                "need": "summary+layer" if entry.get("needs_layer") else "summary",
            }
        )
    return missing


def entries_for(inventory: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """What needs a summary: user Skills and plugins (with a layer), plugin members (summary only)."""
    from .rows import plugin_summary_key

    rows = list(inventory)
    entries = []
    plugins: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["source"] == "自己安装":
            entries.append({"key": summary_key(row["name"], row.get("description", "")), "name": row["name"], "description": row.get("description", ""), "needs_layer": True})
        elif row["source"] == "插件" and row.get("plugin"):
            plugins.setdefault(row["plugin"], []).append(row)
            entries.append({"key": summary_key(row["name"], row.get("description", "")), "name": row["name"], "description": row.get("description", ""), "needs_layer": False})
    for name, members in plugins.items():
        description = "插件，包含：" + "；".join(f"{m['name']}：{m.get('description', '')[:80]}" for m in members)
        entries.append({"key": plugin_summary_key(name, [m["name"] for m in members]), "name": f"插件 {name}", "description": description, "needs_layer": True})
    return entries
