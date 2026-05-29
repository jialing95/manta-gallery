#!/usr/bin/env python3
"""
Export Aqaba Case 001 for MANTA Gallery.

Place this file at:
    ~/Desktop/manta-gallery/scripts/export_aqaba_case_001.py

Run from the repository root:
    cd ~/Desktop/manta-gallery
    export PY=/home/daij/Desktop/preprocessor/.venv/bin/python
    $PY scripts/export_aqaba_case_001.py

Output:
    data/demo/aqaba_case_001/
    ├── case.json
    ├── terrain.vtp
    ├── water/frame_0000.vtp
    └── landslide/frame_0000.vtp

Design:
    - DEM is exported once as a static high-resolution VTP and reused by all frames.
    - Water is exported as time-dependent VTP frames with a coarser stride.
    - Landslide is exported with finer stride and cropped to a global ROI.
    - The landslide ROI is the union of landslide footprints over multiple frames,
      not only the target display frame.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np


# =============================================================================
# Case-specific settings
# =============================================================================

REPO_ROOT = Path(__file__).resolve().parents[1]

MANTA_SRC = Path("/home/daij/Desktop/preprocessor")
CASE_DIR = Path("/home/daij/Desktop/compile_all/AQA_016_K1_C10_angm35_mixed")

OUTDIR = REPO_ROOT / "data" / "demo" / "aqaba_case_001"

SOURCE = "fort"
FRAME_INDEX = 20
SEA_LEVEL = 0.0

# Browser time-series export.
EXPORT_FRAME_MODE = "all"
EXPORT_FRAME_STEP = 1
EXPORT_FRAME_INDICES = [0, 10, 20, 30, 40, 50, 60]

# Browser-side default thresholds
WATER_M_DEFAULT = 0.30
LANDSLIDE_M_DEFAULT = 0.0

# Export resolution
# Terrain is a static background VTP: export it finer and reuse it across all
# future time frames instead of writing one DEM per frame.
TERRAIN_STRIDE = 5
WATER_STRIDE = 20
LANDSLIDE_STRIDE = 5

# Water surface export semantics:
# - Keep m as a scalar for later browser-side thresholding; do NOT hard-filter
#   water VTP cells by WATER_M_DEFAULT here.
# - Suppress non-ocean/landslide-top artifacts using a physical water mask and a
#   robust amplitude outlier guard. This prevents isolated eta spikes from
#   becoming water-surface geometry.
WATER_DRY_TOL = 5.0e-4
WATER_REQUIRE_OCEAN_BASE = True
WATER_OCEAN_B0_EPS = 0.0
WATER_AMP_ROBUST_PERCENTILE = 99.0
WATER_AMP_OUTLIER_FACTOR = 6.0
WATER_AMP_MIN_LIMIT = 10.0

# Global landslide ROI settings.
# "all": scan all frames with ROI_FRAME_STEP.
# "selected": scan ROI_FRAME_INDICES only.
ROI_FRAME_MODE = "all"
ROI_FRAME_STEP = 1
ROI_FRAME_INDICES = [0, 10, 20, 30, 40, 50, 60]

# Pad is counted after LANDSLIDE_STRIDE downsampling.
# With LANDSLIDE_STRIDE=5, pad=24 is intentionally conservative.
LANDSLIDE_ROI_PAD = 24

# Detect landslide ROI by hm. Keep this very small to include weak/edge material.
LANDSLIDE_ROI_HM_EPS = 1.0e-6

TITLE = "Aqaba landslide-tsunami simulation"


# =============================================================================
# Utilities
# =============================================================================

# =============================================================================
# Time-series export helpers
# =============================================================================

class RangeAccumulator:
    """Track a global finite min/max range across exported frames."""

    def __init__(self) -> None:
        self.vmin = None
        self.vmax = None

    def update(self, a: np.ndarray) -> None:
        arr = np.asarray(a, dtype=float)
        vals = arr[np.isfinite(arr)]
        if vals.size == 0:
            return
        lo = float(np.nanmin(vals))
        hi = float(np.nanmax(vals))
        self.vmin = lo if self.vmin is None else min(self.vmin, lo)
        self.vmax = hi if self.vmax is None else max(self.vmax, hi)

    def as_list(self):
        return [self.vmin, self.vmax]


def clear_frame_dir(path: Path, pattern: str = "frame_*.vtp") -> None:
    """Remove stale exported frames without deleting the directory itself."""
    path.mkdir(parents=True, exist_ok=True)
    for old in path.glob(pattern):
        old.unlink()


def total_size_mb(path: Path) -> float:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1024.0 / 1024.0


def cube_nt(cube) -> int:
    try:
        return int(getattr(cube, "nt", 0) or 0)
    except Exception:
        return 0


def get_export_frame_indices(cube) -> list[int]:
    """Choose native cube frames to export as browser frames."""
    nt = cube_nt(cube)
    if nt <= 0:
        return [int(FRAME_INDEX)]

    if EXPORT_FRAME_MODE == "selected":
        frames: list[int] = []
        for k in EXPORT_FRAME_INDICES:
            kk = int(k)
            if 0 <= kk < nt:
                frames.append(kk)
        if 0 <= int(FRAME_INDEX) < nt:
            frames.append(int(FRAME_INDEX))
        if not frames:
            frames = [0]
        return sorted(set(frames))

    step = int(max(1, EXPORT_FRAME_STEP))
    frames = list(range(0, nt, step))
    if (nt - 1) not in frames:
        frames.append(nt - 1)
    if 0 <= int(FRAME_INDEX) < nt:
        frames.append(int(FRAME_INDEX))
    return sorted(set(frames))


def get_frame_times(cube, frame_indices: list[int]) -> list[float]:
    try:
        times = cube.get_times()
    except Exception:
        times = None

    out: list[float] = []
    for k in frame_indices:
        value = float(k)
        try:
            if times is not None and len(times) > int(k):
                value = float(times[int(k)])
        except Exception:
            pass
        out.append(value)
    return out


def build_water_surface(F_full: Dict[str, np.ndarray]):
    """Build one strided water frame while preserving m for later thresholding."""
    F_water = apply_stride(F_full, WATER_STRIDE)

    X = F_water["X"]
    Y = F_water["Y"]
    b0 = F_water["b0"]
    h = F_water["h"]
    eta = F_water["eta"]
    m = F_water["m"]
    wave_amplitude = F_water["wave_amplitude"]

    # Wet/dry is physical depth + finite eta, not the default m threshold.
    wet = np.isfinite(h) & (h > float(WATER_DRY_TOL)) & np.isfinite(eta)

    # Ocean-base gate removes subaerial/landslide-top artifacts while preserving
    # ocean cells with m > WATER_M_DEFAULT for future browser-side sliders.
    if WATER_REQUIRE_OCEAN_BASE:
        ocean_base = np.isfinite(b0) & (b0 <= float(SEA_LEVEL) + float(WATER_OCEAN_B0_EPS))
        water_mask = wet & ocean_base
    else:
        water_mask = wet

    # Robust outlier guard, independent of m.
    amp_limit = robust_abs_limit(wave_amplitude[water_mask])
    if amp_limit is not None:
        water_mask = water_mask & np.isfinite(wave_amplitude) & (np.abs(wave_amplitude) <= amp_limit)

    Z_water = np.where(water_mask, eta, np.nan)
    water_amp = np.where(water_mask, wave_amplitude, np.nan)
    water_m = np.where(water_mask, m, np.nan)

    return X, Y, Z_water, water_amp, water_m, amp_limit


def build_landslide_surface(F_full: Dict[str, np.ndarray], global_landslide_roi: Tuple[int, int, int, int]):
    """Build one strided/cropped landslide frame."""
    F_ls = apply_stride(F_full, LANDSLIDE_STRIDE)
    F_ls_roi = crop_dict_to_roi(F_ls, global_landslide_roi)

    X = F_ls_roi["X"]
    Y = F_ls_roi["Y"]
    b = F_ls_roi["b"]
    hm = F_ls_roi["hm"]
    m = F_ls_roi["m"]
    db = F_ls_roi["db"]

    slide_candidate = (
        np.isfinite(hm)
        & np.isfinite(m)
        & np.isfinite(db)
        & (hm > LANDSLIDE_ROI_HM_EPS)
    )

    Z_slide = np.where(slide_candidate, b + hm, np.nan)
    slide_hm = np.where(slide_candidate, hm, np.nan)
    slide_m = np.where(slide_candidate, m, np.nan)
    slide_db = np.where(slide_candidate, db, np.nan)

    return X, Y, Z_slide, slide_hm, slide_m, slide_db


def insert_manta_src(path: Path) -> None:
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"MANTA_SRC does not exist: {path}")
    sys.path.insert(0, str(path))


def as_2d(
    a: Any,
    name: str,
    shape: Optional[Tuple[int, int]] = None,
    required: bool = True,
) -> Optional[np.ndarray]:
    if a is None:
        if required:
            raise KeyError(f"Missing required field: {name}")
        return None

    arr = np.asarray(a)

    if arr.ndim == 3 and arr.shape[-1] == 1:
        arr = arr[..., 0]

    if shape is not None:
        if arr.shape == shape:
            return arr
        if arr.ndim == 2 and arr.T.shape == shape:
            return arr.T
        if arr.size == shape[0] * shape[1]:
            return arr.reshape(shape)

    return arr


def normalize_m(m: np.ndarray) -> np.ndarray:
    """Normalize solid fraction m to [0, 1]."""
    out = np.asarray(m, dtype=float)

    try:
        vmax = float(np.nanmax(out))
        if np.isfinite(vmax) and vmax > 1.5 and vmax <= 200.0:
            out = out / 100.0
    except Exception:
        pass

    with np.errstate(invalid="ignore"):
        out = np.clip(out, 0.0, 1.0)

    return out


def nan_range(a: np.ndarray):
    arr = np.asarray(a, dtype=float)
    mask = np.isfinite(arr)
    if not np.any(mask):
        return [None, None]
    return [float(np.nanmin(arr)), float(np.nanmax(arr))]


def robust_abs_limit(
    a: np.ndarray,
    *,
    percentile: float = WATER_AMP_ROBUST_PERCENTILE,
    factor: float = WATER_AMP_OUTLIER_FACTOR,
    min_limit: float = WATER_AMP_MIN_LIMIT,
) -> Optional[float]:
    """
    Return a robust symmetric amplitude limit used only for export masking.

    This is not a colormap range. It is a safety guard against isolated, non-
    physical eta spikes entering the browser water-surface geometry. The limit
    scales with the data distribution and has a conservative lower bound.
    """
    arr = np.asarray(a, dtype=float)
    vals = np.abs(arr[np.isfinite(arr)])
    if vals.size == 0:
        return None

    q = float(np.nanpercentile(vals, float(percentile)))
    if not np.isfinite(q):
        return None

    limit = max(float(min_limit), float(factor) * q)
    if not np.isfinite(limit) or limit <= 0.0:
        return None
    return float(limit)


def apply_stride(F: Dict[str, np.ndarray], stride: int) -> Dict[str, np.ndarray]:
    stride = int(max(1, stride))
    if stride == 1:
        return F

    out: Dict[str, np.ndarray] = {}
    for key, val in F.items():
        arr = np.asarray(val)
        if arr.ndim == 2:
            out[key] = arr[::stride, ::stride]
        else:
            out[key] = arr
    return out


def crop_dict_to_roi(
    F: Dict[str, np.ndarray],
    roi: Tuple[int, int, int, int],
) -> Dict[str, np.ndarray]:
    """Crop all 2D fields in F to a precomputed ROI."""
    r0, r1, c0, c1 = roi
    out: Dict[str, np.ndarray] = {}
    for key, val in F.items():
        arr = np.asarray(val)
        if arr.ndim == 2:
            out[key] = arr[r0:r1, c0:c1]
        else:
            out[key] = arr
    return out


def landslide_roi_mask(F: Dict[str, np.ndarray]) -> np.ndarray:
    """Return the landslide candidate mask used for ROI construction."""
    hm = np.asarray(F["hm"], float)
    m = np.asarray(F["m"], float)
    db = np.asarray(F["db"], float)

    return (
        np.isfinite(hm)
        & np.isfinite(m)
        & np.isfinite(db)
        & (hm > float(LANDSLIDE_ROI_HM_EPS))
    )


def roi_from_mask(mask: np.ndarray, pad: int = 0) -> Tuple[int, int, int, int]:
    """Return padded bounding box from a boolean mask."""
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError(f"ROI mask must be 2D, got shape={mask.shape}")
    if not np.any(mask):
        raise ValueError("Cannot build ROI: mask has no valid cells.")

    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    pad = int(max(0, pad))

    r0 = max(0, int(rows[0]) - pad)
    r1 = min(mask.shape[0], int(rows[-1]) + pad + 1)
    c0 = max(0, int(cols[0]) - pad)
    c1 = min(mask.shape[1], int(cols[-1]) + pad + 1)

    return (r0, r1, c0, c1)


def union_rois(
    rois: list[Tuple[int, int, int, int]],
    shape: Tuple[int, int],
    pad: int,
) -> Tuple[int, int, int, int]:
    """Union multiple ROI boxes and apply final padding."""
    if not rois:
        raise ValueError("Cannot union empty ROI list.")

    r0 = min(r[0] for r in rois)
    r1 = max(r[1] for r in rois)
    c0 = min(r[2] for r in rois)
    c1 = max(r[3] for r in rois)

    r0 = max(0, int(r0) - int(pad))
    r1 = min(shape[0], int(r1) + int(pad))
    c0 = max(0, int(c0) - int(pad))
    c1 = min(shape[1], int(c1) + int(pad))

    return (r0, r1, c0, c1)


def write_surface_vtp(
    X: np.ndarray,
    Y: np.ndarray,
    Z: np.ndarray,
    point_data: Dict[str, np.ndarray],
    path: Path,
) -> None:
    """
    Write a regular surface to VTP.

    PyVista StructuredGrid saves as .vts by default. For the browser gallery,
    we convert to PolyData first and save as .vtp.
    """
    import pyvista as pv

    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    Z = np.asarray(Z, dtype=float)

    if X.shape != Y.shape or X.shape != Z.shape:
        raise ValueError(f"X/Y/Z shape mismatch: {X.shape}, {Y.shape}, {Z.shape}")

    grid = pv.StructuredGrid(X, Y, Z)

    for key, val in point_data.items():
        arr = np.asarray(val, dtype=float)

        if arr.shape != X.shape:
            if arr.ndim == 2 and arr.T.shape == X.shape:
                arr = arr.T
            else:
                raise ValueError(f"{key}: shape {arr.shape} does not match grid shape {X.shape}")

        grid.point_data[key] = arr.ravel(order="F")

    mesh = grid.extract_surface()

    # Remove PyVista bookkeeping arrays to reduce file size.
    for key in ("vtkOriginalPointIds", "vtkOriginalCellIds"):
        if key in mesh.point_data:
            del mesh.point_data[key]
        if key in mesh.cell_data:
            del mesh.cell_data[key]

    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.save(str(path), binary=True)


def file_size_mb(path: Path) -> float:
    return path.stat().st_size / 1024.0 / 1024.0


# =============================================================================
# D-Claw / FORT loading
# =============================================================================

def load_cube():
    insert_manta_src(MANTA_SRC)

    if SOURCE == "fort":
        from visualization.dclaw_layers import DClawFortCacheCube

        cube = DClawFortCacheCube(str(CASE_DIR))
        try:
            cube.set_mode("mixed")
        except Exception:
            pass
        return cube

    if SOURCE == "fgout":
        from visualization.dclaw_layers import DClawDataCube

        return DClawDataCube(str(CASE_DIR))

    raise ValueError(f"Unknown SOURCE={SOURCE!r}")


def prepare_fields(S: Dict[str, Any]) -> Dict[str, np.ndarray]:
    X = as_2d(S.get("X"), "X")
    assert X is not None

    Y = as_2d(S.get("Y"), "Y", X.shape)
    b = as_2d(S.get("b"), "b", X.shape)
    h = as_2d(S.get("h"), "h", X.shape)

    assert Y is not None
    assert b is not None
    assert h is not None

    b0 = as_2d(S.get("b0"), "b0", X.shape, required=False)
    if b0 is None:
        b0 = b

    eta = as_2d(S.get("eta"), "eta", X.shape, required=False)
    if eta is None:
        eta = b + h

    hm = as_2d(S.get("hm", S.get("hs", None)), "hm", X.shape, required=False)
    m_raw = as_2d(S.get("m"), "m", X.shape, required=False)

    if hm is None and m_raw is not None:
        m_tmp = normalize_m(m_raw)
        hm = np.maximum(h, 0.0) * m_tmp

    if hm is None:
        hm = np.zeros_like(h, dtype=float)

    if m_raw is None:
        with np.errstate(divide="ignore", invalid="ignore"):
            m_raw = np.where(h > 1.0e-12, hm / h, 0.0)

    m = normalize_m(m_raw)

    db = as_2d(S.get("db"), "db", X.shape, required=False)
    if db is None:
        db = b - b0

    wave_amplitude = eta - float(SEA_LEVEL)

    return {
        "X": X,
        "Y": Y,
        "b": b,
        "b0": b0,
        "h": h,
        "eta": eta,
        "hm": hm,
        "m": m,
        "db": db,
        "wave_amplitude": wave_amplitude,
    }


# =============================================================================
# Global landslide ROI
# =============================================================================

def get_roi_frame_indices(cube) -> list[int]:
    """Choose frames used to construct the global landslide ROI."""
    try:
        nt = int(getattr(cube, "nt", 0) or 0)
    except Exception:
        nt = 0

    if nt <= 0:
        return [int(FRAME_INDEX)]

    if ROI_FRAME_MODE == "selected":
        out = []
        for k in ROI_FRAME_INDICES:
            kk = int(k)
            if 0 <= kk < nt:
                out.append(kk)
        if 0 <= int(FRAME_INDEX) < nt:
            out.append(int(FRAME_INDEX))
        return sorted(set(out))

    step = int(max(1, ROI_FRAME_STEP))
    frames = list(range(0, nt, step))
    if (nt - 1) not in frames:
        frames.append(nt - 1)
    if 0 <= int(FRAME_INDEX) < nt:
        frames.append(int(FRAME_INDEX))

    return sorted(set(frames))


def compute_global_landslide_roi(cube) -> Tuple[Tuple[int, int, int, int], Dict[str, object]]:
    """
    Compute a fixed landslide ROI from the union of landslide footprints
    over selected ROI frames.
    """
    frame_indices = get_roi_frame_indices(cube)

    rois: list[Tuple[int, int, int, int]] = []
    valid_counts: Dict[int, int] = {}
    roi_shape: Optional[Tuple[int, int]] = None

    preview = frame_indices[:8]
    suffix = "..." if len(frame_indices) > 8 else ""

    print("[ROI] Building global landslide ROI")
    print(f"[ROI] mode={ROI_FRAME_MODE}, step={ROI_FRAME_STEP}, frames={preview}{suffix}, n={len(frame_indices)}")

    for i, k in enumerate(frame_indices):
        S_k = cube.get_slice(int(k))
        F_k = prepare_fields(S_k)
        F_k_ls = apply_stride(F_k, LANDSLIDE_STRIDE)

        mask_k = landslide_roi_mask(F_k_ls)
        roi_shape = mask_k.shape

        n_valid = int(np.count_nonzero(mask_k))
        valid_counts[int(k)] = n_valid

        if n_valid > 0:
            rois.append(roi_from_mask(mask_k, pad=0))

        if (i % 10 == 0) or (i == len(frame_indices) - 1):
            print(f"[ROI] scanned {i + 1:>3}/{len(frame_indices)} frames; k={k}, valid={n_valid}")

    if not rois:
        raise ValueError(
            "Global landslide ROI failed: no valid landslide cells were found "
            f"in ROI frames {frame_indices}."
        )

    assert roi_shape is not None
    roi = union_rois(rois, shape=roi_shape, pad=LANDSLIDE_ROI_PAD)

    valid_frame_count = sum(1 for v in valid_counts.values() if v > 0)

    meta = {
        "mode": ROI_FRAME_MODE,
        "frame_step": int(ROI_FRAME_STEP),
        "frame_indices": [int(k) for k in frame_indices],
        "valid_counts": {str(k): int(v) for k, v in valid_counts.items()},
        "valid_frame_count": int(valid_frame_count),
        "roi_shape": [int(v) for v in roi_shape],
    }

    print(f"[ROI] global roi rc={roi}, shape={roi_shape}")
    print(f"[ROI] valid frame count={valid_frame_count} / {len(frame_indices)}")

    return roi, meta


# =============================================================================
# Export
# =============================================================================

def export_case() -> None:
    cube = load_cube()

    frame_indices = get_export_frame_indices(cube)
    default_index = frame_indices.index(int(FRAME_INDEX)) if int(FRAME_INDEX) in frame_indices else 0
    frame_times = get_frame_times(cube, frame_indices)

    print("[TIMELINE] Exporting browser time series")
    print(f"[TIMELINE] native frames: {frame_indices[:8]}{'...' if len(frame_indices) > 8 else ''}, n={len(frame_indices)}")
    print(f"[TIMELINE] default browser index={default_index}, native frame={frame_indices[default_index]}")

    # Fixed landslide ROI is computed once and reused by all landslide frames.
    global_landslide_roi, global_landslide_roi_meta = compute_global_landslide_roi(cube)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    water_dir = OUTDIR / "water"
    landslide_dir = OUTDIR / "landslide"
    clear_frame_dir(water_dir)
    clear_frame_dir(landslide_dir)

    # Static terrain: write once only. Use the default display frame to obtain
    # the grid and b0, but do not create per-frame DEM files.
    S_default = cube.get_slice(frame_indices[default_index])
    F_default = prepare_fields(S_default)
    F_terrain = apply_stride(F_default, TERRAIN_STRIDE)
    write_surface_vtp(
        F_terrain["X"],
        F_terrain["Y"],
        F_terrain["b0"],
        {"elevation": F_terrain["b0"]},
        OUTDIR / "terrain.vtp",
    )

    water_amp_range = RangeAccumulator()
    water_m_range = RangeAccumulator()
    slide_hm_range = RangeAccumulator()
    slide_m_range = RangeAccumulator()
    slide_db_range = RangeAccumulator()
    water_amp_limits: Dict[str, Optional[float]] = {}

    for out_i, native_k in enumerate(frame_indices):
        print(f"[FRAME] {out_i + 1:>3}/{len(frame_indices)}  native={native_k}")
        S = cube.get_slice(int(native_k))
        F_full = prepare_fields(S)

        Xw, Yw, Zw, water_amp, water_m, amp_limit = build_water_surface(F_full)
        write_surface_vtp(
            Xw,
            Yw,
            Zw,
            {
                "wave_amplitude": water_amp,
                "m": water_m,
            },
            water_dir / f"frame_{out_i:04d}.vtp",
        )

        Xs, Ys, Zs, slide_hm, slide_m, slide_db = build_landslide_surface(F_full, global_landslide_roi)
        write_surface_vtp(
            Xs,
            Ys,
            Zs,
            {
                "hm": slide_hm,
                "m": slide_m,
                "db": slide_db,
            },
            landslide_dir / f"frame_{out_i:04d}.vtp",
        )

        water_amp_range.update(water_amp)
        water_m_range.update(water_m)
        slide_hm_range.update(slide_hm)
        slide_m_range.update(slide_m)
        slide_db_range.update(slide_db)
        water_amp_limits[str(out_i)] = amp_limit

    case = {
        "id": OUTDIR.name,
        "title": TITLE,
        "description": "Time-series gallery-ready export of wave amplitude and landslide material fields.",
        "source": {
            "kind": SOURCE,
            "case_dir": str(CASE_DIR),
            "raw_output": "not included",
        },
        "time": {
            "mode": "time_series",
            "unit": "s",
            "values": [float(t) for t in frame_times],
            "default_index": int(default_index),
            "frame_count": int(len(frame_indices)),
            "native_indices": [int(k) for k in frame_indices],
        },
        "layers": {
            "terrain": {
                "file": "terrain.vtp",
                "visible": True,
                "time_varying": False,
                "style": {
                    "mode": "sea_split",
                    "below_sea_level": {"label": "Bathymetry", "colormap": "cmocean.deep"},
                    "above_sea_level": {"label": "Topography", "colormap": "cmcrameri.grayC", "relief": True},
                },
            },
            "water": {
                "file_pattern": "water/frame_{frame}.vtp",
                "visible": True,
                "time_varying": True,
                "display_scalar": "wave_amplitude",
                "filter_scalar": "m",
                "filter_rule": "m <= water_m",
                "default_m": float(WATER_M_DEFAULT),
                "m_range": [0.0, 1.0],
                "m_threshold_applied_at_export": False,
                "label": "Wave amplitude",
                "unit": "m",
                "colormap": "dclaw.tsunami",
                "colormap_label": "Tsunami",
                "colorbar": {
                    "side": "right",
                    "range": water_amp_range.as_list(),
                    "range_mode": "robust_symmetric_per_frame_in_viewer",
                },
            },
            "landslide": {
                "file_pattern": "landslide/frame_{frame}.vtp",
                "visible": True,
                "time_varying": True,
                "filter_scalar": "m",
                "filter_rule": "m >= landslide_m",
                "default_m": float(LANDSLIDE_M_DEFAULT),
                "m_range": [0.0, 1.0],
                "default_scalar": "hm",
                "colormap": "magma",
                "colorbar": {"side": "left"},
                "available_scalars": {
                    "hm": {"label": "hm (solid thickness)", "unit": "m", "range": slide_hm_range.as_list()},
                    "m": {"label": "m (solid fraction)", "unit": "1", "range": [0.0, 1.0]},
                    "db": {"label": "Δb (bed change)", "unit": "m", "range": slide_db_range.as_list()},
                },
            },
        },
        "ui": {
            "show_layer_toggles": True,
            "show_time_slider": True,
            "show_play_button": True,
            "show_water_m_slider": True,
            "show_landslide_m_slider": True,
            "show_landslide_scalar_selector": True,
            "show_colormap_controls": False,
            "show_dem_style_controls": False,
            "show_vertical_exaggeration": False,
        },
        "camera": {"preset": "oblique"},
        "processing": {
            "sea_level": float(SEA_LEVEL),
            "export_frame_mode": str(EXPORT_FRAME_MODE),
            "export_frame_step": int(EXPORT_FRAME_STEP),
            "stride": {
                "terrain": int(TERRAIN_STRIDE),
                "water": int(WATER_STRIDE),
                "landslide": int(LANDSLIDE_STRIDE),
            },
            "landslide_roi": {
                "enabled": True,
                "type": "global_union_over_frames",
                "hm_eps": float(LANDSLIDE_ROI_HM_EPS),
                "pad_cells": int(LANDSLIDE_ROI_PAD),
                "roi_rc_exclusive": [int(v) for v in global_landslide_roi],
                "scan": global_landslide_roi_meta,
            },
            "water_surface": {
                "description": "Colored by wave amplitude; m is preserved for browser-side thresholding.",
                "dry_tolerance": float(WATER_DRY_TOL),
                "ocean_base_gate": {
                    "enabled": bool(WATER_REQUIRE_OCEAN_BASE),
                    "b0_max": float(SEA_LEVEL + WATER_OCEAN_B0_EPS),
                },
                "m_threshold_applied_at_export": False,
                "amplitude_outlier_guard": {
                    "enabled": True,
                    "percentile": float(WATER_AMP_ROBUST_PERCENTILE),
                    "factor": float(WATER_AMP_OUTLIER_FACTOR),
                    "min_limit": float(WATER_AMP_MIN_LIMIT),
                    "per_browser_frame_limit": water_amp_limits,
                },
            },
            "landslide_surface": "Cropped to global landslide ROI, colored by hm, m, or Δb, and filtered by browser-side landslide solid-fraction cutoff.",
        },
    }

    with open(OUTDIR / "case.json", "w", encoding="utf-8") as f:
        json.dump(case, f, indent=2, ensure_ascii=False)

    print_export_summary(
        terrain_path=OUTDIR / "terrain.vtp",
        water_dir=water_dir,
        landslide_dir=landslide_dir,
        case_path=OUTDIR / "case.json",
        frame_count=len(frame_indices),
        default_index=default_index,
        native_default=frame_indices[default_index],
        water_amp_range=water_amp_range.as_list(),
        water_m_range=water_m_range.as_list(),
        slide_hm_range=slide_hm_range.as_list(),
        slide_m_range=slide_m_range.as_list(),
        slide_db_range=slide_db_range.as_list(),
        roi=global_landslide_roi,
    )


def print_export_summary(
    *,
    terrain_path: Path,
    water_dir: Path,
    landslide_dir: Path,
    case_path: Path,
    frame_count: int,
    default_index: int,
    native_default: int,
    water_amp_range,
    water_m_range,
    slide_hm_range,
    slide_m_range,
    slide_db_range,
    roi: Tuple[int, int, int, int],
) -> None:
    water_frames = sorted(water_dir.glob("frame_*.vtp"))
    landslide_frames = sorted(landslide_dir.glob("frame_*.vtp"))

    print("[OK] Exported Aqaba Case 001 time series")
    print(f"  outdir:    {OUTDIR}")
    print(f"  terrain:   {terrain_path} ({file_size_mb(terrain_path):.2f} MB)")
    print(f"  water:     {len(water_frames)} frames ({total_size_mb(water_dir):.2f} MB)")
    print(f"  landslide: {len(landslide_frames)} frames ({total_size_mb(landslide_dir):.2f} MB)")
    print(f"  manifest:  {case_path} ({file_size_mb(case_path):.3f} MB)")
    print(f"  package:   {total_size_mb(OUTDIR):.2f} MB")
    print("")
    print("Settings")
    print(f"  frame_count:            {frame_count}")
    print(f"  default browser index:  {default_index}")
    print(f"  default native frame:   {native_default}")
    print(f"  terrain stride:         {TERRAIN_STRIDE}")
    print(f"  water stride:           {WATER_STRIDE}")
    print(f"  landslide stride:       {LANDSLIDE_STRIDE}")
    print(f"  landslide roi pad:      {LANDSLIDE_ROI_PAD}")
    print(f"  landslide roi rc:       {roi}")
    print("")
    print("Global exported scalar ranges")
    print(f"  water wave_amplitude:   {water_amp_range}")
    print(f"  water m:                {water_m_range}")
    print(f"  landslide hm:           {slide_hm_range}")
    print(f"  landslide m:            {slide_m_range}")
    print(f"  landslide db:           {slide_db_range}")


if __name__ == "__main__":
    export_case()
