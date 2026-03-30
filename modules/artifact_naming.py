"""
统一产物命名（单一事实源）。

目标：
1) 由 project_charter.software_full_name/software_short_name 驱动导出文件名。
2) 对历史项目保持兼容：同时支持 legacy(project_name) 命名查找。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.project_charter import load_project_charter, resolve_software_identity


_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_SPACE_RE = re.compile(r"\s+")


def _sanitize_file_stem(value: Any, fallback: str = "未命名软件", max_len: int = 96) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = text.replace("\r", " ").replace("\n", " ")
    text = _INVALID_FILENAME_RE.sub("_", text)
    text = _SPACE_RE.sub(" ", text).strip(" .")
    if not text:
        text = fallback
    return text[:max_len]


def resolve_project_identity(
    project_name: str,
    project_dir: Optional[Path] = None,
    charter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    source_charter = charter
    if source_charter is None and project_dir is not None:
        source_charter = load_project_charter(Path(project_dir)) or {}
    identity = resolve_software_identity(source_charter or {}, fallback_project_name=project_name)
    software_full_name = str(identity.get("software_full_name") or project_name or "未命名软件").strip() or "未命名软件"
    software_short_name = str(identity.get("software_short_name") or software_full_name).strip() or software_full_name
    return {
        **identity,
        "software_full_name": software_full_name,
        "software_short_name": software_short_name,
        "file_stem": _sanitize_file_stem(software_full_name, fallback=_sanitize_file_stem(project_name or "未命名软件")),
        "legacy_stem": _sanitize_file_stem(project_name or software_full_name),
    }


def build_artifact_filenames(
    project_name: str,
    project_dir: Optional[Path] = None,
    charter: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    identity = resolve_project_identity(project_name=project_name, project_dir=project_dir, charter=charter)
    stem = str(identity.get("file_stem") or _sanitize_file_stem(project_name))
    legacy = str(identity.get("legacy_stem") or _sanitize_file_stem(project_name))
    return {
        "manual_docx": f"{stem}_操作说明书.docx",
        "manual_pdf": f"{stem}_操作说明书.pdf",
        "code_pdf": f"{stem}_源代码.pdf",
        "freeze_zip": f"{stem}_freeze_package.zip",
        "guide_txt": f"{stem}_软著填写手册.txt",
        "legacy_manual_docx": f"{legacy}_操作说明书.docx",
        "legacy_manual_pdf": f"{legacy}_操作说明书.pdf",
        "legacy_code_pdf": f"{legacy}_源代码.pdf",
        "legacy_freeze_zip": f"{legacy}_freeze_package.zip",
        "legacy_guide_txt": f"{legacy}_软著填写手册.txt",
    }


def candidate_artifact_paths(
    project_dir: Path,
    project_name: str,
    artifact_key: str,
    charter: Optional[Dict[str, Any]] = None,
) -> List[Path]:
    names = build_artifact_filenames(project_name=project_name, project_dir=project_dir, charter=charter)
    canonical = project_dir / str(names.get(artifact_key) or "")
    legacy_name = str(names.get(f"legacy_{artifact_key}") or names.get(artifact_key) or "")
    legacy = project_dir / legacy_name
    candidates: List[Path] = []
    for item in [canonical, legacy]:
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def first_existing_artifact_path(
    project_dir: Path,
    project_name: str,
    artifact_key: str,
    charter: Optional[Dict[str, Any]] = None,
) -> Optional[Path]:
    for path in candidate_artifact_paths(
        project_dir=project_dir,
        project_name=project_name,
        artifact_key=artifact_key,
        charter=charter,
    ):
        if path.exists():
            return path
    return None


def preferred_artifact_path(
    project_dir: Path,
    project_name: str,
    artifact_key: str,
    charter: Optional[Dict[str, Any]] = None,
) -> Path:
    names = build_artifact_filenames(project_name=project_name, project_dir=project_dir, charter=charter)
    return project_dir / str(names.get(artifact_key) or "")
