"""Recoverable actions on user-installed Skills.

Nothing here deletes permanently. Every removal or replacement first moves
the current folder into Darwin's recycle bin, from which it can be restored.
Only user-installed Skills inside the known Skill folders can be touched, and
only if their content still matches what the report showed the user.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from typing import Any

from .sources import USER, tree_sha256, user_skill_roots

REPORT_MAX_AGE_DAYS = 7

PLUGIN_UNINSTALL_STEPS = {
    "Claude Code": "在 Claude Code 里输入 /plugin，进入已安装插件（Installed），选中 {plugin} 后卸载。",
    "Codex": "打开 Codex 的插件管理，找到 {plugin} 后卸载。",
    "WorkBuddy": "打开 WorkBuddy 的“专家、技能与连接器”管理，找到 {plugin} 后卸载。",
}


class ActionError(Exception):
    pass


def darwin_home() -> Path:
    value = os.environ.get("DARWIN_HOME")
    return Path(value).expanduser() if value else Path.home() / ".darwin"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# -- reports ---------------------------------------------------------------------
def _latest_pointer(home: Path, agent: str | None) -> Path:
    slug = {"Claude Code": "claude", "豆包": "doubao"}.get(agent or "", (agent or "all").lower())
    return home / "reports" / f"latest-{slug}.json"


def save_report(home: Path, report: dict[str, Any]) -> Path:
    path = home / "reports" / f"{report['report_id']}.json"
    _write_json(path, report)
    _write_json(_latest_pointer(home, report.get("agent")), {"report_id": report["report_id"]})
    return path


def load_report(home: Path, report_id: str | None = None, agent: str | None = None) -> dict[str, Any] | None:
    if not report_id:
        pointer = _read_json(_latest_pointer(home, agent))
        report_id = pointer.get("report_id") if isinstance(pointer, dict) else None
    if not report_id or not re.fullmatch(r"[0-9a-f]{8}", report_id):
        return None
    return _read_json(home / "reports" / f"{report_id}.json")


def fresh_report(home: Path, report_id: str | None = None, agent: str | None = None) -> dict[str, Any]:
    """The exact report the user replied to. Row numbers only mean something within it."""
    if not report_id:
        raise ActionError("请带上报告编号（盘点表开头写着），序号只在那一份报告里有效。")
    report = load_report(home, report_id, agent)
    if not report or "rows" not in report:
        raise ActionError(f"找不到报告 {report_id}，请重新盘点。")
    if agent and report.get("agent") and report["agent"] != agent:
        raise ActionError(f"报告 {report_id} 是 {report['agent']} 的，不是 {agent} 的。")
    age = dt.datetime.now() - dt.datetime.fromisoformat(report["generated_at"])
    if age.days >= REPORT_MAX_AGE_DAYS:
        raise ActionError(f"报告 {report['report_id']} 已经超过 {REPORT_MAX_AGE_DAYS} 天，请重新运行 advise 再选择。")
    return report


def parse_numbers(text: str) -> list[int]:
    numbers: list[int] = []
    for part in re.split(r"[\s,，、;；]+", text.strip()):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)\s*[-~—至到]\s*(\d+)", part)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            numbers.extend(range(min(start, end), max(start, end) + 1))
        elif part.isdigit():
            numbers.append(int(part))
        else:
            raise ActionError(f"看不懂编号“{part}”，请用 1、3、5-8 这样的格式。")
    return list(dict.fromkeys(numbers))


def get_row(report: dict[str, Any], number: int) -> dict[str, Any]:
    for row in report["rows"]:
        if row["no"] == number:
            return row
    raise ActionError(f"报告 {report['report_id']} 里没有序号 {number}。")


def _items_for(report: dict[str, Any], row: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    paths = set(row["paths"])
    return [item for item in report["items"] if item["kind"] == kind and paths & {t["path"] for t in item["targets"]}]


def _row_target(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("agent", "name", "path", "source", "location", "tree_sha256", "stat_sig")}


# -- safety checks ------------------------------------------------------------------
def _check_movable(target: dict[str, Any], home_dir: Path | None = None) -> Path:
    if target.get("source") != USER:
        raise ActionError(f"{target['name']} 不是自己安装的 Skill，Darwin 不会动它。")
    path = Path(target["path"])
    if not path.is_dir():
        raise ActionError(f"{target['name']} 已经不在原位置：{path}")
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ActionError(f"{target['name']} 是一个链接，为避免误伤链接指向的原文件，Darwin 不会动它。")
    resolved = path.resolve()
    roots = user_skill_roots(home_dir)
    root = next((r for r in roots if resolved != r and r in resolved.parents), None)
    if root is None or ".system" in resolved.relative_to(root).parts:
        raise ActionError(f"{target['name']} 不在用户 Skill 目录里，Darwin 不会动它：{resolved}")
    if target.get("stat_sig"):
        from .rows import stat_signature

        changed = stat_signature(resolved) != target["stat_sig"]
    else:
        changed = not target.get("tree_sha256") or tree_sha256(resolved) != target["tree_sha256"]
    if changed:
        raise ActionError(f"{target['name']} 在报告生成后被改过，请重新盘点再选择。")
    return resolved


def _recycle(home: Path, path: Path, meta: dict[str, Any]) -> str:
    bin_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    destination = home / "recycle-bin" / bin_id
    destination.mkdir(parents=True)
    shutil.move(str(path), str(destination / path.name))
    _write_json(destination / "meta.json", {**meta, "bin_id": bin_id, "original_path": str(path), "recycled_at": _now(), "folder": path.name})
    return bin_id


# -- actions ------------------------------------------------------------------------
def delete(home: Path, report: dict[str, Any], numbers: list[int], home_dir: Path | None = None) -> list[dict[str, Any]]:
    """Delete the chosen rows. The user decides; a row need not carry a delete suggestion."""
    rows = [get_row(report, number) for number in numbers]
    # Check everything first so a bad row does not leave a half-done batch.
    checked = [(row, _check_movable(_row_target(row), home_dir)) for row in rows if row["kind"] == "skill"]
    results = []
    for row, path in checked:
        bin_id = _recycle(home, path, {"reason": "delete", "report_id": report["report_id"], "row": row["no"], **_row_target(row)})
        results.append({"no": row["no"], "name": row["name"], "agent": row["agent"], "status": "已移到回收站", "bin_id": bin_id})
    for row in rows:
        if row["kind"] == "plugin":
            steps = PLUGIN_UNINSTALL_STEPS.get(row["agent"], "请在 {plugin} 所在 Agent 的插件管理里卸载。")
            results.append({"no": row["no"], "name": row["plugin"], "agent": row["agent"], "status": "需要你手动卸载", "steps": steps.format(plugin=row["plugin"])})
    return sorted(results, key=lambda value: value["no"])


def set_layer(home: Path, report: dict[str, Any], number: int, layer: str) -> dict[str, Any]:
    from .rows import save_override

    row = get_row(report, number)
    try:
        save_override(home, row["agent"], row, layer)
    except ValueError as exc:
        raise ActionError(str(exc)) from exc
    return {"no": number, "name": row["name"], "layer": layer}


def align(home: Path, report: dict[str, Any], number: int, use: int | None = None, home_dir: Path | None = None) -> list[dict[str, Any]]:
    """Make every same-name copy match one version. ``use`` is the row number to keep."""
    row = get_row(report, number)
    items = _items_for(report, row, "align")
    if not items:
        raise ActionError(f"序号 {number} 没有需要对齐的同名副本。")
    item = items[0]
    if use:
        chosen = get_row(report, use)
        matches = [i for i, t in enumerate(item["targets"], 1) if t["path"] == chosen.get("path")]
        if not matches:
            raise ActionError(f"序号 {use} 不是 {row['name']} 的副本。")
        choice = matches[0]
    else:
        choice = item["recommended"]
    source_target = item["targets"][choice - 1]
    source = Path(source_target["path"])
    if not source.is_dir() or tree_sha256(source.resolve()) != source_target["tree_sha256"]:
        raise ActionError("选中的版本在报告生成后被改过，请重新运行 advise。")
    others = [(target, _check_movable(target, home_dir)) for index, target in enumerate(item["targets"], 1) if index != choice]
    snapshot = home / "staging" / uuid.uuid4().hex
    shutil.copytree(source, snapshot, symlinks=True)
    results = []
    try:
        for target, path in others:
            bin_id = _recycle(home, path, {"reason": "align", "report_id": report["report_id"], "item": number, **target})
            try:
                shutil.copytree(snapshot, path, symlinks=True)
            except OSError:
                shutil.rmtree(path, ignore_errors=True)
                restore(home, bin_id)
                raise
            results.append({"name": target["name"], "agent": target["agent"], "location": target["location"], "status": "已替换为选中版本", "bin_id": bin_id})
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)
    return results


def prepare_draft(home: Path, report: dict[str, Any], number: int, home_dir: Path | None = None) -> dict[str, Any]:
    row = get_row(report, number)
    if row["kind"] != "skill":
        raise ActionError(f"序号 {number} 是插件，Darwin 不修改插件里的 Skill。")
    targets = [_row_target(row)]
    reasons = list(row["notes"])
    for kind in ("optimize", "fix"):
        for item in _items_for(report, row, kind):
            reasons += [reason for reason in item["reasons"] if reason not in reasons]
    for item in _items_for(report, row, "collision"):
        # Rewriting one description is only half the fix; draft the other user Skill too.
        for target in item["targets"]:
            partner = next((r for r in report["rows"] if r.get("path") == target["path"] and r["kind"] == "skill"), None)
            if partner and partner is not row and all(t["path"] != partner["path"] for t in targets):
                targets.append(_row_target(partner))
        reasons += item["reasons"]
    item = {"title": f"序号 {number} {row['name']}", "reasons": reasons}
    for target in targets:
        _check_movable(target, home_dir)
    draft_id = uuid.uuid4().hex[:8]
    root = home / "drafts" / draft_id
    copies = []
    for index, target in enumerate(targets, 1):
        draft = root / f"{index}-{Path(target['path']).name}"
        shutil.copytree(target["path"], draft, symlinks=True)
        copies.append({**target, "draft_path": str(draft)})
    brief = [f"# 优化草稿 {draft_id}", "", f"来自报告 {report['report_id']}：{item['title']}", "", "## 为什么要改", ""]
    brief += [f"- {reason}" for reason in item["reasons"]]
    brief += ["", "## 要改的草稿（只改这里，原版不动）", ""]
    brief += [f"- {copy['name']}（{copy['agent']}）：{copy['draft_path']}" for copy in copies]
    (root / "brief.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "brief.md").write_text("\n".join(brief) + "\n", encoding="utf-8")
    manifest = {"draft_id": draft_id, "report_id": report["report_id"], "item": number, "title": item["title"], "created_at": _now(), "status": "DRAFT", "copies": copies}
    _write_json(root / "manifest.json", manifest)
    return {"draft_id": draft_id, "brief": str(root / "brief.md"), "copies": [{"name": c["name"], "agent": c["agent"], "draft_path": c["draft_path"]} for c in copies]}


def _load_draft(home: Path, draft_id: str) -> tuple[Path, dict[str, Any]]:
    if not re.fullmatch(r"[0-9a-f]{8}", draft_id):
        raise ActionError("草稿编号格式不对。")
    root = home / "drafts" / draft_id
    manifest = _read_json(root / "manifest.json")
    if not manifest:
        raise ActionError(f"找不到草稿 {draft_id}。")
    return root, manifest


def draft_diff(home: Path, draft_id: str) -> str:
    _, manifest = _load_draft(home, draft_id)
    chunks: list[str] = []
    for copy in manifest["copies"]:
        original, draft = Path(copy["path"]), Path(copy["draft_path"])
        files = {p.relative_to(original) for p in original.rglob("*") if p.is_file()} | {p.relative_to(draft) for p in draft.rglob("*") if p.is_file()}
        for relative in sorted(files, key=lambda p: p.as_posix()):
            old = (original / relative).read_bytes() if (original / relative).is_file() else b""
            new = (draft / relative).read_bytes() if (draft / relative).is_file() else b""
            if old == new:
                continue
            try:
                old_lines, new_lines = old.decode("utf-8").splitlines(), new.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                chunks.append(f"二进制文件有变化：{copy['name']}/{relative.as_posix()}\n")
                continue
            label = f"{copy['name']}/{relative.as_posix()}"
            chunks.extend(line + "\n" for line in difflib.unified_diff(old_lines, new_lines, f"原版 {label}", f"草稿 {label}", lineterm=""))
    return "".join(chunks)


def apply_draft(home: Path, draft_id: str, home_dir: Path | None = None) -> list[dict[str, Any]]:
    root, manifest = _load_draft(home, draft_id)
    if manifest["status"] != "DRAFT":
        raise ActionError(f"草稿 {draft_id} 已经处理过（{manifest['status']}）。")
    if not draft_diff(home, draft_id):
        raise ActionError("草稿和原版一模一样，没有需要替换的内容。")
    checked = [(copy, _check_movable(copy, home_dir)) for copy in manifest["copies"]]
    results = []
    for copy, path in checked:
        if not _draft_changed(copy):
            continue
        bin_id = _recycle(home, path, {"reason": "optimize", "draft_id": draft_id, **{k: v for k, v in copy.items() if k != "draft_path"}})
        shutil.copytree(copy["draft_path"], path, symlinks=True)
        results.append({"name": copy["name"], "agent": copy["agent"], "status": "已替换为优化版", "bin_id": bin_id})
    manifest["status"] = "APPLIED"
    manifest["applied_at"] = _now()
    _write_json(root / "manifest.json", manifest)
    return results


def _draft_changed(copy: dict[str, Any]) -> bool:
    original, draft = Path(copy["path"]), Path(copy["draft_path"])
    files = {p.relative_to(original) for p in original.rglob("*") if p.is_file()} | {p.relative_to(draft) for p in draft.rglob("*") if p.is_file()}
    return any(
        not (original / f).is_file() or not (draft / f).is_file() or (original / f).read_bytes() != (draft / f).read_bytes()
        for f in files
    )


def list_bin(home: Path) -> list[dict[str, Any]]:
    entries = []
    for meta_path in sorted((home / "recycle-bin").glob("*/meta.json"), reverse=True):
        meta = _read_json(meta_path)
        if meta and not meta.get("restored_at"):
            entries.append({key: meta.get(key) for key in ("bin_id", "name", "agent", "location", "reason", "recycled_at", "original_path")})
    return entries


def restore(home: Path, bin_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", bin_id):
        raise ActionError("回收站编号格式不对。")
    root = home / "recycle-bin" / bin_id
    meta = _read_json(root / "meta.json")
    if not meta or meta.get("restored_at"):
        raise ActionError(f"回收站里没有 {bin_id}，或已经恢复过。")
    payload = root / meta["folder"]
    original = Path(meta["original_path"])
    if original.exists():
        # An align or optimize put a newer version here; keep it recoverable too.
        current_bin = _recycle(home, original, {"reason": "replaced-by-restore", "name": meta.get("name"), "agent": meta.get("agent"), "location": meta.get("location")})
    else:
        current_bin = None
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(payload), str(original))
    meta["restored_at"] = _now()
    _write_json(root / "meta.json", meta)
    return {"name": meta.get("name"), "agent": meta.get("agent"), "path": str(original), "status": "已恢复", "replaced_version_bin_id": current_bin}
