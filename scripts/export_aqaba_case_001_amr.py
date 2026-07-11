#!/usr/bin/env python3
"""
Export FORT AMR diagnostics as lightweight JSON sidecars.

This script is intentionally independent from export_aqaba_case_001.py's
surface pipeline. It reads only FORT headers via dclaw_io.fort_cache and does
not rewrite terrain or compact water/landslide files.

Preferred one-command build from the repository root:
    ./scripts/build_case.sh <case-id> /path/to/dclaw-case --title "Case title"

Output:
    data/demo/<case-id>/amr/frame_0000.json ...
    data/demo/<case-id>/case.json  (updated with layers.amr)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import export_aqaba_case_001 as surface_export
# Reuse case-specific constants from the main exporter without running it.
from export_aqaba_case_001 import (  # type: ignore
    REPO_ROOT,
    MANTA_SRC,
    CASE_DIR,
    OUTDIR,
    FRAME_INDEX,
    EXPORT_FRAME_STEP,
    insert_manta_src,
)

AMR_OUTDIR = OUTDIR / "amr"
AMR_FILE_PATTERN = "amr/frame_{frame}.json"


def configure_runtime(
    *,
    case_dir: Optional[Path] = None,
    manta_src: Optional[Path] = None,
    outdir: Optional[Path] = None,
    frame_index: Optional[int] = None,
    frame_step: Optional[int] = None,
) -> None:
    """Use the same local paths as the compact surface export."""
    global CASE_DIR, MANTA_SRC, OUTDIR, AMR_OUTDIR, FRAME_INDEX, EXPORT_FRAME_STEP

    if case_dir is not None:
        CASE_DIR = Path(case_dir).expanduser().resolve()
    if manta_src is not None:
        MANTA_SRC = Path(manta_src).expanduser().resolve()
    if outdir is not None:
        OUTDIR = Path(outdir).expanduser().resolve()
    if frame_index is not None:
        FRAME_INDEX = int(frame_index)
    if frame_step is not None:
        EXPORT_FRAME_STEP = max(1, int(frame_step))
    AMR_OUTDIR = OUTDIR / "amr"
    surface_export.CASE_DIR = CASE_DIR
    surface_export.MANTA_SRC = MANTA_SRC
    surface_export.OUTDIR = OUTDIR
    surface_export.FRAME_INDEX = FRAME_INDEX
    surface_export.EXPORT_FRAME_STEP = EXPORT_FRAME_STEP


def _as_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(x)
        if v == v and abs(v) != float("inf"):
            return v
    except Exception:
        pass
    return default


def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return int(default)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def load_fort_cube():
    """Load the Fort-native cube directly from dclaw_io.fort_cache.

    The visualization.dclaw_layers wrapper can be stale in some environments.
    The AMR API lives in dclaw_io.fort_cache, so import it directly and also
    keep robust fallbacks for wrapper/private attributes.
    """
    insert_manta_src(MANTA_SRC)
    cache_root = Path(
        os.environ.get(
            "MANTA_FORT_CACHE_DIR",
            f"/tmp/manta-gallery-fort-cache-{os.getuid()}",
        )
    )
    cache_dir = cache_root / CASE_DIR.name

    try:
        from dclaw_io.fort_cache import DClawFortCacheCube  # type: ignore
        return DClawFortCacheCube(str(CASE_DIR), cache_dir=cache_dir)
    except Exception as e_cube:
        try:
            from dclaw_io.fort_cache import DClawFortCacheRun  # type: ignore
            return DClawFortCacheRun(str(CASE_DIR), cache_dir=cache_dir)
        except Exception as e_run:
            raise RuntimeError(
                "Could not import/load dclaw_io.fort_cache DClawFortCacheCube "
                f"or DClawFortCacheRun. cube_error={e_cube!r}, run_error={e_run!r}"
            )


def _inner_fort(obj: Any) -> Any:
    return getattr(obj, "_fort", obj)


def get_times(cube: Any) -> List[float]:
    for target in (cube, _inner_fort(cube)):
        meth = getattr(target, "get_times", None)
        if callable(meth):
            try:
                vals = meth()
                if vals is not None:
                    return [float(v) for v in vals]
            except Exception:
                pass
    nt = int(getattr(cube, "nt", getattr(_inner_fort(cube), "nt", 0)) or 0)
    return [float(i) for i in range(nt)]


def get_nt(cube: Any, times: List[float]) -> int:
    nt = int(getattr(cube, "nt", getattr(_inner_fort(cube), "nt", 0)) or 0)
    return nt if nt > 0 else len(times)


def get_native_frame_no(cube: Any, browser_index: int) -> int:
    for target in (cube, _inner_fort(cube)):
        meth = getattr(target, "frame_no", None)
        if callable(meth):
            try:
                return int(meth(int(browser_index)))
            except Exception:
                pass
    return int(browser_index)


def get_amr_headers(cube: Any, browser_index: int) -> List[Dict[str, Any]]:
    for target in (cube, _inner_fort(cube)):
        meth = getattr(target, "get_amr_headers", None)
        if callable(meth):
            try:
                return list(meth(int(browser_index)))
            except Exception:
                pass
    raise AttributeError("No get_amr_headers(k) method found on cube or cube._fort")


def summarize_headers(headers: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    levels: Dict[str, int] = {}
    xmin = ymin = None
    xmax = ymax = None
    count = 0

    for g in headers:
        count += 1
        lv = _as_int(_get(g, "level", _get(g, "AMR_level", 0)), 0)
        if lv > 0:
            levels[str(lv)] = int(levels.get(str(lv), 0)) + 1

        mx = _as_int(_get(g, "mx"), 0)
        my = _as_int(_get(g, "my"), 0)
        dx = _as_float(_get(g, "dx"), None)
        dy = _as_float(_get(g, "dy"), None)
        xlow = _as_float(_get(g, "xlow"), None)
        ylow = _as_float(_get(g, "ylow"), None)
        if None in (dx, dy, xlow, ylow) or mx <= 0 or my <= 0:
            continue

        xhi = float(xlow) + int(mx) * float(dx)
        yhi = float(ylow) + int(my) * float(dy)
        xmin = float(xlow) if xmin is None else min(float(xmin), float(xlow))
        xmax = float(xhi) if xmax is None else max(float(xmax), float(xhi))
        ymin = float(ylow) if ymin is None else min(float(ymin), float(ylow))
        ymax = float(yhi) if ymax is None else max(float(ymax), float(yhi))

    bbox = None if xmin is None else [float(xmin), float(xmax), float(ymin), float(ymax)]
    return {"ngrids": int(count), "levels": levels, "bbox": bbox}


def normalize_patch(g: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lv = _as_int(_get(g, "level", _get(g, "AMR_level", 0)), 0)
    grid_number = _as_int(_get(g, "grid_number", _get(g, "grid", 0)), 0)
    mx = _as_int(_get(g, "mx"), 0)
    my = _as_int(_get(g, "my"), 0)
    dx = _as_float(_get(g, "dx"), None)
    dy = _as_float(_get(g, "dy"), None)
    xlow = _as_float(_get(g, "xlow"), None)
    ylow = _as_float(_get(g, "ylow"), None)

    if lv <= 0 or mx <= 0 or my <= 0 or None in (dx, dy, xlow, ylow):
        return None

    xhi = float(xlow) + int(mx) * float(dx)
    yhi = float(ylow) + int(my) * float(dy)
    return {
        "level": int(lv),
        "grid_number": int(grid_number),
        "mx": int(mx),
        "my": int(my),
        "xlow": float(xlow),
        "ylow": float(ylow),
        "xhi": float(xhi),
        "yhi": float(yhi),
        "dx": float(dx),
        "dy": float(dy),
    }


def export_one(
    cube: Any,
    browser_index: int,
    source_index: int,
    native_index: int,
    time_value: float,
) -> Dict[str, Any]:
    headers = get_amr_headers(cube, source_index)
    patches = []
    for h in headers:
        p = normalize_patch(h)
        if p is not None:
            patches.append(p)

    summary = summarize_headers(patches)
    return {
        "browser_index": int(browser_index),
        "source_index": int(source_index),
        "native_index": int(native_index),
        "time": float(time_value),
        "ngrids": int(summary["ngrids"]),
        "levels": summary["levels"],
        "bbox": summary["bbox"],
        "patches": patches,
    }


def update_case_json(nt: int, times: List[float], global_level_counts: Dict[str, int]) -> None:
    case_path = OUTDIR / "case.json"
    if not case_path.is_file():
        raise FileNotFoundError(f"case.json not found. Run the main exporter first: {case_path}")

    case = json.loads(case_path.read_text(encoding="utf-8"))
    layers = case.setdefault("layers", {})
    layers["amr"] = {
        "file_pattern": AMR_FILE_PATTERN,
        "visible": False,
        "time_varying": True,
        "label": "FORT AMR diagnostics",
        "mode": "patch_outlines",
        "description": "Header-only FORT AMR patch outlines exported from fort.q####.",
        "level_counts_global": global_level_counts,
    }

    ui = case.setdefault("ui", {})
    ui["show_amr_overlay"] = True

    processing = case.setdefault("processing", {})
    processing["amr"] = {
        "enabled": True,
        "source": "FORT fort.q#### headers",
        "file_pattern": AMR_FILE_PATTERN,
        "frame_count": int(nt),
        "export_mode": "header_only_sidecar_json",
        "level_counts_global": global_level_counts,
    }

    # Keep time-series metadata consistent when the existing case.json already has it.
    time_meta = case.setdefault("time", {})
    if "frame_count" not in time_meta:
        time_meta["frame_count"] = int(nt)
    if "values" not in time_meta or not isinstance(time_meta.get("values"), list):
        time_meta["values"] = [float(v) for v in times[:nt]]
    if "default_index" not in time_meta:
        time_meta["default_index"] = min(int(FRAME_INDEX), max(0, int(nt) - 1))

    case_path.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export lightweight AMR sidecars from D-Claw FORT headers."
    )
    parser.add_argument("--case-dir", type=Path, default=CASE_DIR)
    parser.add_argument("--manta-src", type=Path, default=MANTA_SRC)
    parser.add_argument("--outdir", type=Path, default=OUTDIR)
    parser.add_argument("--frame-index", type=int, default=FRAME_INDEX)
    parser.add_argument("--frame-step", type=int, default=EXPORT_FRAME_STEP)
    args = parser.parse_args()

    configure_runtime(
        case_dir=args.case_dir,
        manta_src=args.manta_src,
        outdir=args.outdir,
        frame_index=args.frame_index,
        frame_step=args.frame_step,
    )

    cube = load_fort_cube()
    times = get_times(cube)
    nt = get_nt(cube, times)
    if nt <= 0:
        raise RuntimeError("No FORT frames found for AMR export")
    if len(times) < nt:
        times = times + [float(i) for i in range(len(times), nt)]
    frame_indices = surface_export.get_export_frame_indices(cube)
    selected_times = [
        float(times[int(k)]) if int(k) < len(times) else float(k)
        for k in frame_indices
    ]

    AMR_OUTDIR.mkdir(parents=True, exist_ok=True)

    global_level_counts: Dict[str, int] = {}

    print("[AMR] Exporting FORT header-only AMR diagnostics")
    print(
        f"[AMR] frames={len(frame_indices)}, native_total={nt}, "
        f"frame_step={EXPORT_FRAME_STEP}"
    )

    for i, source_index in enumerate(frame_indices):
        native = get_native_frame_no(cube, int(source_index))
        payload = export_one(
            cube,
            browser_index=i,
            source_index=int(source_index),
            native_index=native,
            time_value=float(times[int(source_index)]),
        )

        for lv, n in payload.get("levels", {}).items():
            global_level_counts[str(lv)] = int(global_level_counts.get(str(lv), 0)) + int(n)

        out = AMR_OUTDIR / f"frame_{i:04d}.json"
        out.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

        if (i % 10 == 0) or (i == len(frame_indices) - 1):
            print(
                f"[AMR] wrote {i + 1:>3}/{len(frame_indices)} "
                f"frame={i:04d} source={int(source_index):04d} "
                f"native={native:04d} grids={payload['ngrids']}"
            )

    update_case_json(len(frame_indices), selected_times, global_level_counts)
    print(f"[OK] AMR JSON written to: {AMR_OUTDIR}")
    print(f"[OK] Updated manifest: {OUTDIR / 'case.json'}")


if __name__ == "__main__":
    main()
