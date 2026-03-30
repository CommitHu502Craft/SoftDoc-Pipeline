"""
Vendor asset resolver for runtime HTML rendering.

Purpose:
1) Keep third-party script fallback deterministic and offline-capable.
2) Avoid one-shot hard-coded CDN assumptions.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from config import BASE_DIR
from modules.runtime_skill_engine import resolve_external_script_policy


_ECHARTS_SOURCE_CANDIDATES = [
    BASE_DIR / "assets" / "libs" / "echarts" / "dist" / "echarts.min.js",
    BASE_DIR / "Auto_Soft_Template" / "assets" / "libs" / "echarts" / "dist" / "echarts.min.js",
]


def _find_vendor_source(lib_name: str) -> Path:
    name = str(lib_name or "").strip().lower()
    if name == "echarts":
        for path in _ECHARTS_SOURCE_CANDIDATES:
            if path.exists():
                return path
    return Path("")


def ensure_vendor_asset(html_dir: Path, lib_name: str, relative_target: str) -> Tuple[bool, str]:
    html_dir = Path(html_dir)
    target = html_dir / str(relative_target or "").replace("\\", "/").lstrip("/")
    if target.exists():
        return True, str(target)

    source = _find_vendor_source(lib_name)
    if not source or not source.exists():
        return False, str(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True, str(target)


def ensure_vendor_assets_for_html_dir(html_dir: Path, frontend_constraints: Dict[str, Any]) -> Dict[str, Any]:
    policy = resolve_external_script_policy(frontend_constraints if isinstance(frontend_constraints, dict) else {})
    fallback = policy.get("vendor_fallback") if isinstance(policy.get("vendor_fallback"), dict) else {}
    copied: List[str] = []
    missing: List[str] = []

    for lib_name, relative_target in fallback.items():
        ok, path = ensure_vendor_asset(
            html_dir=Path(html_dir),
            lib_name=str(lib_name or "").strip().lower(),
            relative_target=str(relative_target or "").strip(),
        )
        if ok:
            copied.append(path)
        else:
            missing.append(path)

    return {
        "policy": policy,
        "copied_or_existing": copied,
        "missing": missing,
        "ok": len(missing) == 0,
    }

