#!/usr/bin/env python3
"""
Export Aqaba Case 001 for MANTA Gallery.

Place this file at:
    ~/Desktop/manta-gallery/scripts/export_aqaba_case_001.py

Preferred one-command build from the repository root:
    ./scripts/build_site.sh /path/to/dclaw-case

Output:
    data/demo/aqaba_case_001/
    ├── case.json
    ├── terrain.vtp
    ├── water/template.bin.gz
    ├── water/frame_0000.bin.gz
    ├── landslide/template.bin.gz
    └── landslide/frame_0000.bin.gz

Design:
    - DEM is exported once as a static high-resolution VTP and reused by all frames.
    - Water uses a regional stride plus native-resolution offshore/inland
      shoreline bands for inundation detail without oversized browser assets.
    - Landslide is exported with finer stride and cropped to a global ROI.
    - Browser VTP coordinates and scalars are written as Float32.
    - The landslide ROI is the union of landslide footprints over multiple frames,
      not only the target display frame.
"""

from __future__ import annotations

import argparse
import gzip
import json
import struct
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
WATER_STRIDE = 10
WATER_COASTAL_DETAIL_STRIDE = 0
WATER_COASTAL_DETAIL_OFFSHORE_M = 100.0
WATER_COASTAL_DETAIL_INLAND_M = 500.0
LANDSLIDE_STRIDE = 0
VTP_FLOAT_DTYPE = np.float32
VTP_FLOAT_DTYPE_NAME = "float32"
COMPACT_FORMAT_VERSION = 2
COMPACT_MAGIC = b"MANTAV2\0"
COMPACT_HEADER = struct.Struct("<8sII")
COMPACT_COMPRESSION_LEVEL = 9

# Water surface export semantics:
# - Keep m as a scalar for later browser-side thresholding; do NOT hard-filter
#   water VTP cells by WATER_M_DEFAULT here.
# - Suppress non-ocean/landslide-top artifacts using a physical water mask and a
#   robust amplitude outlier guard. This prevents isolated eta spikes from
#   becoming water-surface geometry.
WATER_DRY_TOL = 5.0e-4
WATER_REQUIRE_OCEAN_BASE = False
WATER_OCEAN_B0_EPS = 0.0
WATER_AMP_ROBUST_PERCENTILE = 99.0
WATER_AMP_OUTLIER_FACTOR = 6.0
WATER_AMP_MIN_LIMIT = 10.0
WATER_AMP_ROBUST_GUARD_ENABLED = False
WATER_AMP_ABS_HARD_LIMIT = 100.0

# Global landslide ROI settings.
# "all": scan all frames with ROI_FRAME_STEP.
# "selected": scan ROI_FRAME_INDICES only.
ROI_FRAME_MODE = "all"
ROI_FRAME_STEP = 1
ROI_FRAME_INDICES = [0, 10, 20, 30, 40, 50, 60]

# Pad is counted after LANDSLIDE_STRIDE downsampling. A stride of 0 means native
# resolution, so the current pad is counted in native grid cells.
LANDSLIDE_ROI_PAD = 24

# Detect landslide ROI by hm. Keep this very small to include weak/edge material.
LANDSLIDE_ROI_HM_EPS = 1.0e-6

TITLE = "Aqaba LSB C10"


# =============================================================================
# Utilities
# =============================================================================

def configure_runtime(
    *,
    case_dir: Optional[Path] = None,
    manta_src: Optional[Path] = None,
    outdir: Optional[Path] = None,
    frame_index: Optional[int] = None,
    title: Optional[str] = None,
) -> None:
    """Override case paths without editing this file for each local export."""
    global CASE_DIR, MANTA_SRC, OUTDIR, FRAME_INDEX, TITLE

    if case_dir is not None:
        CASE_DIR = Path(case_dir).expanduser().resolve()
    if manta_src is not None:
        MANTA_SRC = Path(manta_src).expanduser().resolve()
    if outdir is not None:
        OUTDIR = Path(outdir).expanduser().resolve()
    if frame_index is not None:
        FRAME_INDEX = int(frame_index)
    if title is not None:
        TITLE = str(title)


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


def clear_frame_dir(path: Path) -> None:
    """Remove stale exported frames without deleting the directory itself."""
    path.mkdir(parents=True, exist_ok=True)
    for pattern in ("frame_*.vtp", "frame_*.bin.gz", "template.bin.gz"):
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
    """Build one native-resolution water frame for adaptive mesh export."""
    X = F_full["X"]
    Y = F_full["Y"]
    b0 = F_full["b0"]
    h = F_full["h"]
    eta = F_full["eta"]
    m = F_full["m"]
    wave_amplitude = F_full["wave_amplitude"]

    # Wet/dry is physical depth + finite eta, not the default m threshold.
    wet = np.isfinite(h) & (h > float(WATER_DRY_TOL)) & np.isfinite(eta)

    # Ocean-base gate removes subaerial/landslide-top artifacts while preserving
    # ocean cells with m > WATER_M_DEFAULT for future browser-side sliders.
    if WATER_REQUIRE_OCEAN_BASE:
        ocean_base = np.isfinite(b0) & (b0 <= float(SEA_LEVEL) + float(WATER_OCEAN_B0_EPS))
        water_mask = wet & ocean_base
    else:
        water_mask = wet

    # Preserve near-source water elevations.  The robust guard is disabled by
    # default because true impact waves can be large and sparse during the first
    # frames.  We keep only a generous hard sanity cap to remove impossible
    # artifacts such as hundreds-of-meters eta spikes.
    amp_limit = robust_abs_limit(wave_amplitude[water_mask]) if WATER_AMP_ROBUST_GUARD_ENABLED else None
    hard_limit = float(WATER_AMP_ABS_HARD_LIMIT)
    if np.isfinite(hard_limit) and hard_limit > 0.0:
        water_mask = water_mask & np.isfinite(wave_amplitude) & (np.abs(wave_amplitude) <= hard_limit)
    if WATER_AMP_ROBUST_GUARD_ENABLED and amp_limit is not None:
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
    step = stride_step(stride)
    if step == 1:
        return F

    out: Dict[str, np.ndarray] = {}
    for key, val in F.items():
        arr = np.asarray(val)
        if arr.ndim == 2:
            out[key] = arr[::step, ::step]
        else:
            out[key] = arr
    return out


def stride_step(stride: int) -> int:
    """Return the slicing step; stride=0 is the explicit native-resolution mode."""
    return max(1, int(stride))


def stride_indices(size: int, stride: int) -> np.ndarray:
    """Return strided indices while retaining the last boundary point."""
    indices = np.arange(0, int(size), stride_step(stride), dtype=int)
    if indices.size == 0 or indices[-1] != int(size) - 1:
        indices = np.append(indices, int(size) - 1)
    return indices


def estimate_grid_spacing(X: np.ndarray, Y: np.ndarray) -> Tuple[float, float]:
    """Estimate native row/column spacing in the projected grid units."""
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)

    row_steps = np.hypot(np.diff(X, axis=0), np.diff(Y, axis=0))
    col_steps = np.hypot(np.diff(X, axis=1), np.diff(Y, axis=1))

    def median_positive(a: np.ndarray, name: str) -> float:
        vals = a[np.isfinite(a) & (a > 0.0)]
        if vals.size == 0:
            raise ValueError(f"Cannot estimate {name} grid spacing.")
        return float(np.nanmedian(vals))

    return median_positive(row_steps, "row"), median_positive(col_steps, "column")


def build_water_coastal_detail_plan(F: Dict[str, np.ndarray]) -> Dict[str, Any]:
    """
    Replace coarse water cells near the z=0 coastline with native-resolution cells.

    Fine cells are selected in complete coarse-cell blocks. This makes the fine
    and coarse meshes meet at shared block boundaries without overlapping faces.
    """
    from scipy.ndimage import distance_transform_edt

    X = np.asarray(F["X"], dtype=float)
    Y = np.asarray(F["Y"], dtype=float)
    b0 = np.asarray(F["b0"], dtype=float)
    if X.shape != Y.shape or X.shape != b0.shape:
        raise ValueError(f"Coastal detail X/Y/b0 shape mismatch: {X.shape}, {Y.shape}, {b0.shape}")

    finite = np.isfinite(b0)
    below_sea_level = finite & (b0 <= float(SEA_LEVEL))
    shoreline = np.zeros_like(below_sea_level, dtype=bool)

    cross_rows = (
        finite[:-1, :]
        & finite[1:, :]
        & (below_sea_level[:-1, :] != below_sea_level[1:, :])
    )
    shoreline[:-1, :] |= cross_rows
    shoreline[1:, :] |= cross_rows

    cross_cols = (
        finite[:, :-1]
        & finite[:, 1:]
        & (below_sea_level[:, :-1] != below_sea_level[:, 1:])
    )
    shoreline[:, :-1] |= cross_cols
    shoreline[:, 1:] |= cross_cols

    if not np.any(shoreline):
        raise ValueError("Cannot preserve coastal water detail: no z=0 coastline crossings were found.")

    row_spacing, col_spacing = estimate_grid_spacing(X, Y)
    distance_to_shore = distance_transform_edt(
        ~shoreline,
        sampling=(row_spacing, col_spacing),
    )
    coastal_points = (
        shoreline
        | (below_sea_level & (distance_to_shore <= float(WATER_COASTAL_DETAIL_OFFSHORE_M)))
        | (
            finite
            & ~below_sea_level
            & (distance_to_shore <= float(WATER_COASTAL_DETAIL_INLAND_M))
        )
    )

    row_indices = stride_indices(X.shape[0], WATER_STRIDE)
    col_indices = stride_indices(X.shape[1], WATER_STRIDE)
    coarse_cell_mask = np.ones((row_indices.size - 1, col_indices.size - 1), dtype=bool)
    fine_cell_mask = np.zeros((X.shape[0] - 1, X.shape[1] - 1), dtype=bool)

    for coarse_r, (r0, r1) in enumerate(zip(row_indices[:-1], row_indices[1:])):
        for coarse_c, (c0, c1) in enumerate(zip(col_indices[:-1], col_indices[1:])):
            if np.any(coastal_points[r0:r1 + 1, c0:c1 + 1]):
                coarse_cell_mask[coarse_r, coarse_c] = False
                fine_cell_mask[r0:r1, c0:c1] = True

    return {
        "row_indices": row_indices,
        "col_indices": col_indices,
        "coarse_cell_mask": coarse_cell_mask,
        "fine_cell_mask": fine_cell_mask,
        "row_spacing_m": float(row_spacing),
        "col_spacing_m": float(col_spacing),
        "shoreline_point_count": int(np.count_nonzero(shoreline)),
        "coastal_point_count": int(np.count_nonzero(coastal_points)),
        "fine_cell_count": int(np.count_nonzero(fine_cell_mask)),
        "coarse_cell_count": int(np.count_nonzero(coarse_cell_mask)),
    }


def take_2d_indices(a: np.ndarray, row_indices: np.ndarray, col_indices: np.ndarray) -> np.ndarray:
    """Take the rectangular point subset defined by row and column indices."""
    return np.asarray(a)[np.ix_(row_indices, col_indices)]


def surface_polydata_from_cell_mask(
    X: np.ndarray,
    Y: np.ndarray,
    Z: np.ndarray,
    point_data: Dict[str, np.ndarray],
    cell_mask: np.ndarray,
):
    """Create sparse quad PolyData containing only selected finite cells."""
    import pyvista as pv

    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    Z = np.asarray(Z, dtype=float)
    cell_mask = np.asarray(cell_mask, dtype=bool)

    if X.shape != Y.shape or X.shape != Z.shape:
        raise ValueError(f"X/Y/Z shape mismatch: {X.shape}, {Y.shape}, {Z.shape}")
    if cell_mask.shape != (X.shape[0] - 1, X.shape[1] - 1):
        raise ValueError(f"Cell mask shape mismatch: {cell_mask.shape} for points {X.shape}")

    valid_points = np.isfinite(X) & np.isfinite(Y) & np.isfinite(Z)
    arrays: Dict[str, np.ndarray] = {}
    for key, val in point_data.items():
        arr = np.asarray(val, dtype=float)
        if arr.shape != X.shape:
            raise ValueError(f"{key}: shape {arr.shape} does not match grid shape {X.shape}")
        arrays[key] = arr
        valid_points &= np.isfinite(arr)

    valid_cells = (
        cell_mask
        & valid_points[:-1, :-1]
        & valid_points[:-1, 1:]
        & valid_points[1:, 1:]
        & valid_points[1:, :-1]
    )
    rows, cols = np.nonzero(valid_cells)
    if rows.size == 0:
        return pv.PolyData()

    point_ids = np.arange(X.size, dtype=np.int64).reshape(X.shape)
    quads = np.column_stack(
        (
            point_ids[rows, cols],
            point_ids[rows, cols + 1],
            point_ids[rows + 1, cols + 1],
            point_ids[rows + 1, cols],
        )
    )
    used_ids, inverse = np.unique(quads.ravel(), return_inverse=True)
    points = np.column_stack(
        (X.ravel()[used_ids], Y.ravel()[used_ids], Z.ravel()[used_ids])
    ).astype(VTP_FLOAT_DTYPE, copy=False)
    faces = np.column_stack(
        (np.full(quads.shape[0], 4, dtype=np.int64), inverse.reshape((-1, 4)))
    ).ravel()

    mesh = pv.PolyData(points, faces)
    for key, arr in arrays.items():
        mesh.point_data[key] = arr.ravel()[used_ids].astype(VTP_FLOAT_DTYPE, copy=False)
    return mesh


def write_adaptive_water_vtp(
    X: np.ndarray,
    Y: np.ndarray,
    Z: np.ndarray,
    point_data: Dict[str, np.ndarray],
    plan: Dict[str, Any],
    path: Path,
) -> Dict[str, np.ndarray]:
    """Write coarse regional water plus native-resolution shoreline blocks."""
    row_indices = np.asarray(plan["row_indices"], dtype=int)
    col_indices = np.asarray(plan["col_indices"], dtype=int)

    coarse_point_data = {
        key: take_2d_indices(val, row_indices, col_indices)
        for key, val in point_data.items()
    }
    coarse_mesh = surface_polydata_from_cell_mask(
        take_2d_indices(X, row_indices, col_indices),
        take_2d_indices(Y, row_indices, col_indices),
        take_2d_indices(Z, row_indices, col_indices),
        coarse_point_data,
        np.asarray(plan["coarse_cell_mask"], dtype=bool),
    )
    fine_mesh = surface_polydata_from_cell_mask(
        X,
        Y,
        Z,
        point_data,
        np.asarray(plan["fine_cell_mask"], dtype=bool),
    )

    meshes = [mesh for mesh in (coarse_mesh, fine_mesh) if mesh.n_cells > 0]
    if not meshes:
        raise ValueError("Adaptive water surface contains no finite cells.")
    mesh = meshes[0].append_polydata(*meshes[1:]) if len(meshes) > 1 else meshes[0]

    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.save(str(path), binary=True)

    return {
        key: np.concatenate([np.asarray(part.point_data[key]) for part in meshes])
        for key in point_data
    }


def compact_template_part(source_ids: np.ndarray, cell_mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return source point ids and local quads for selected cells."""
    source_ids = np.asarray(source_ids)
    cell_mask = np.asarray(cell_mask, dtype=bool)
    if cell_mask.shape != (source_ids.shape[0] - 1, source_ids.shape[1] - 1):
        raise ValueError(f"Compact cell mask shape mismatch: {cell_mask.shape} for points {source_ids.shape}")

    rows, cols = np.nonzero(cell_mask)
    local_ids = np.arange(source_ids.size, dtype=np.uint32).reshape(source_ids.shape)
    quads = np.column_stack(
        (
            local_ids[rows, cols],
            local_ids[rows, cols + 1],
            local_ids[rows + 1, cols + 1],
            local_ids[rows + 1, cols],
        )
    )
    used_ids, inverse = np.unique(quads.ravel(), return_inverse=True)
    return (
        source_ids.ravel()[used_ids].astype(np.int64, copy=False),
        inverse.reshape((-1, 4)).astype(np.uint32, copy=False),
    )


def build_compact_water_template(
    F: Dict[str, np.ndarray],
    plan: Dict[str, Any],
) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
    """Build one static adaptive water template and its native source ids."""
    X = np.asarray(F["X"])
    Y = np.asarray(F["Y"])
    native_ids = np.arange(X.size, dtype=np.int64).reshape(X.shape)
    row_indices = np.asarray(plan["row_indices"], dtype=int)
    col_indices = np.asarray(plan["col_indices"], dtype=int)

    coarse_source_ids, coarse_quads = compact_template_part(
        native_ids[np.ix_(row_indices, col_indices)],
        np.asarray(plan["coarse_cell_mask"], dtype=bool),
    )
    fine_source_ids, fine_quads = compact_template_part(
        native_ids,
        np.asarray(plan["fine_cell_mask"], dtype=bool),
    )
    fine_quads = fine_quads + np.uint32(coarse_source_ids.size)

    source_ids = np.concatenate((coarse_source_ids, fine_source_ids))
    quads = np.concatenate((coarse_quads, fine_quads), axis=0)
    return (
        {
            "x": X.ravel()[source_ids].astype(np.float32, copy=False),
            "y": Y.ravel()[source_ids].astype(np.float32, copy=False),
            "quads": quads.astype(np.uint32, copy=False),
        },
        source_ids,
    )


def build_compact_landslide_template(
    F: Dict[str, np.ndarray],
    global_landslide_roi: Tuple[int, int, int, int],
) -> Dict[str, np.ndarray]:
    """Build one static regular-grid landslide template."""
    r0, r1, c0, c1 = global_landslide_roi
    X = np.asarray(F["X"])[r0:r1, c0:c1]
    Y = np.asarray(F["Y"])[r0:r1, c0:c1]
    point_ids = np.arange(X.size, dtype=np.uint32).reshape(X.shape)
    rows, cols = np.indices((X.shape[0] - 1, X.shape[1] - 1))
    quads = np.column_stack(
        (
            point_ids[rows, cols].ravel(),
            point_ids[rows, cols + 1].ravel(),
            point_ids[rows + 1, cols + 1].ravel(),
            point_ids[rows + 1, cols].ravel(),
        )
    )
    return {
        "x": X.ravel().astype(np.float32, copy=False),
        "y": Y.ravel().astype(np.float32, copy=False),
        "quads": quads.astype(np.uint32, copy=False),
    }


def as_little_endian_contiguous(a: np.ndarray) -> np.ndarray:
    """Return a compact little-endian array suitable for browser typed arrays."""
    arr = np.asarray(a)
    if arr.dtype.itemsize > 1:
        arr = arr.astype(arr.dtype.newbyteorder("<"), copy=False)
    return np.ascontiguousarray(arr)


def compact_archive_layout(arrays: Dict[str, np.ndarray]) -> Dict[str, Dict[str, object]]:
    """Describe packed arrays after the fixed compact-v2 archive header."""
    offset = COMPACT_HEADER.size
    layout: Dict[str, Dict[str, object]] = {}
    for name, value in arrays.items():
        arr = as_little_endian_contiguous(value)
        layout[name] = {
            "dtype": arr.dtype.name,
            "byte_offset": int(offset),
            "length": int(arr.size),
        }
        if arr.ndim > 1:
            layout[name]["components"] = int(arr.shape[-1])
        offset += int(arr.nbytes)
    return layout


def write_compact_archive(path: Path, arrays: Dict[str, np.ndarray]) -> Dict[str, object]:
    """Write deterministic gzip-compressed compact-v2 arrays."""
    packed_arrays = {
        name: as_little_endian_contiguous(value)
        for name, value in arrays.items()
    }
    payload = b"".join(arr.tobytes(order="C") for arr in packed_arrays.values())
    archive = COMPACT_HEADER.pack(COMPACT_MAGIC, COMPACT_FORMAT_VERSION, len(payload)) + payload

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=COMPACT_COMPRESSION_LEVEL,
            fileobj=raw,
            mtime=0,
        ) as gz:
            gz.write(archive)

    return {
        "header_bytes": int(COMPACT_HEADER.size),
        "uncompressed_bytes": int(len(archive)),
        "compressed_bytes": int(path.stat().st_size),
        "arrays": compact_archive_layout(packed_arrays),
    }


def build_compact_frame_arrays(
    Z: np.ndarray,
    point_data: Dict[str, np.ndarray],
    quads: np.ndarray,
) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
    """Pack dynamic point fields and a bitmap of finite renderable quads."""
    z = np.asarray(Z, dtype=np.float32).ravel()
    arrays: Dict[str, np.ndarray] = {"z": z}
    valid_points = np.isfinite(z)

    for name, value in point_data.items():
        arr = np.asarray(value, dtype=np.float32).ravel()
        if arr.size != z.size:
            raise ValueError(f"{name}: compact frame size {arr.size} does not match z size {z.size}")
        arrays[name] = arr
        valid_points &= np.isfinite(arr)

    quads = np.asarray(quads, dtype=np.uint32).reshape((-1, 4))
    valid_cells = np.all(valid_points[quads], axis=1)
    arrays["valid_cells"] = np.packbits(valid_cells, bitorder="big")
    return arrays, valid_cells


def compact_used_points(valid_cells: np.ndarray, quads: np.ndarray, point_count: int) -> np.ndarray:
    """Return points participating in at least one finite compact quad."""
    used = np.zeros(int(point_count), dtype=bool)
    used[np.asarray(quads, dtype=np.uint32).reshape((-1, 4))[np.asarray(valid_cells, dtype=bool)]] = True
    return used


def compact_layer_manifest(
    *,
    template_path: Path,
    template_meta: Dict[str, object],
    frame_layout: Dict[str, Dict[str, object]],
    point_count: int,
    cell_count: int,
) -> Dict[str, object]:
    """Return the compact-v2 layer metadata consumed by the browser."""
    frame_layout = {name: dict(value) for name, value in frame_layout.items()}
    frame_layout["valid_cells"]["bit_order"] = "big"
    return {
        "version": int(COMPACT_FORMAT_VERSION),
        "compression": "gzip",
        "endianness": "little",
        "point_count": int(point_count),
        "cell_count": int(cell_count),
        "template": {
            "file": str(template_path.relative_to(OUTDIR)),
            **template_meta,
        },
        "frame": {
            "file_pattern": str((template_path.parent / "frame_{frame}.bin.gz").relative_to(OUTDIR)),
            "header_bytes": int(COMPACT_HEADER.size),
            "arrays": frame_layout,
        },
    }


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

    X = np.asarray(X, dtype=VTP_FLOAT_DTYPE)
    Y = np.asarray(Y, dtype=VTP_FLOAT_DTYPE)
    Z = np.asarray(Z, dtype=VTP_FLOAT_DTYPE)

    if X.shape != Y.shape or X.shape != Z.shape:
        raise ValueError(f"X/Y/Z shape mismatch: {X.shape}, {Y.shape}, {Z.shape}")

    grid = pv.StructuredGrid(X, Y, Z)

    for key, val in point_data.items():
        arr = np.asarray(val, dtype=VTP_FLOAT_DTYPE)

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

def preserve_existing_amr_metadata(case: Dict[str, Any]) -> None:
    """Keep valid AMR sidecar metadata when the main surface export is refreshed."""
    case_path = OUTDIR / "case.json"
    amr_frames = sorted((OUTDIR / "amr").glob("frame_*.json"))
    expected_frames = int(case.get("time", {}).get("frame_count", 0) or 0)
    if not case_path.is_file() or len(amr_frames) != expected_frames:
        return

    try:
        existing = json.loads(case_path.read_text(encoding="utf-8"))
        existing_amr_layer = existing.get("layers", {}).get("amr")
        existing_amr_processing = existing.get("processing", {}).get("amr")
    except Exception:
        return

    if existing_amr_layer:
        case.setdefault("layers", {})["amr"] = existing_amr_layer
        case.setdefault("ui", {})["show_amr_overlay"] = True
    if existing_amr_processing:
        case.setdefault("processing", {})["amr"] = existing_amr_processing


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
    water_coastal_detail_plan = build_water_coastal_detail_plan(F_default)
    water_template, water_source_ids = build_compact_water_template(
        F_default,
        water_coastal_detail_plan,
    )
    landslide_template = build_compact_landslide_template(
        F_default,
        global_landslide_roi,
    )
    water_template_path = water_dir / "template.bin.gz"
    landslide_template_path = landslide_dir / "template.bin.gz"
    water_template_meta = write_compact_archive(water_template_path, water_template)
    landslide_template_meta = write_compact_archive(landslide_template_path, landslide_template)
    water_quads = np.asarray(water_template["quads"], dtype=np.uint32)
    landslide_quads = np.asarray(landslide_template["quads"], dtype=np.uint32)

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
    water_frame_layout: Optional[Dict[str, Dict[str, object]]] = None
    landslide_frame_layout: Optional[Dict[str, Dict[str, object]]] = None

    for out_i, native_k in enumerate(frame_indices):
        print(f"[FRAME] {out_i + 1:>3}/{len(frame_indices)}  native={native_k}")
        S = cube.get_slice(int(native_k))
        F_full = prepare_fields(S)

        Xw, Yw, Zw, water_amp, water_m, amp_limit = build_water_surface(F_full)
        water_frame_arrays, water_valid_cells = build_compact_frame_arrays(
            np.asarray(Zw).ravel()[water_source_ids],
            {
                "wave_amplitude": np.asarray(water_amp).ravel()[water_source_ids],
                "m": np.asarray(water_m).ravel()[water_source_ids],
            },
            water_quads,
        )
        water_frame_meta = write_compact_archive(
            water_dir / f"frame_{out_i:04d}.bin.gz",
            water_frame_arrays,
        )
        if water_frame_layout is None:
            water_frame_layout = water_frame_meta["arrays"]

        Xs, Ys, Zs, slide_hm, slide_m, slide_db = build_landslide_surface(F_full, global_landslide_roi)
        landslide_frame_arrays, landslide_valid_cells = build_compact_frame_arrays(
            Zs,
            {
                "hm": slide_hm,
                "m": slide_m,
                "db": slide_db,
            },
            landslide_quads,
        )
        landslide_frame_meta = write_compact_archive(
            landslide_dir / f"frame_{out_i:04d}.bin.gz",
            landslide_frame_arrays,
        )
        if landslide_frame_layout is None:
            landslide_frame_layout = landslide_frame_meta["arrays"]

        water_used = compact_used_points(water_valid_cells, water_quads, water_source_ids.size)
        landslide_used = compact_used_points(landslide_valid_cells, landslide_quads, Zs.size)
        water_amp_range.update(water_frame_arrays["wave_amplitude"][water_used])
        water_m_range.update(water_frame_arrays["m"][water_used])
        slide_hm_range.update(landslide_frame_arrays["hm"][landslide_used])
        slide_m_range.update(landslide_frame_arrays["m"][landslide_used])
        slide_db_range.update(landslide_frame_arrays["db"][landslide_used])
        water_amp_limits[str(out_i)] = amp_limit

    if water_frame_layout is None or landslide_frame_layout is None:
        raise ValueError("Compact export failed: no browser frames were written.")

    case = {
        "id": OUTDIR.name,
        "title": TITLE,
        "description": "Aqaba LSB C10 time-series D-Claw export with water height and landslide material fields.",
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
                "compact": compact_layer_manifest(
                    template_path=water_template_path,
                    template_meta=water_template_meta,
                    frame_layout=water_frame_layout,
                    point_count=water_template["x"].size,
                    cell_count=water_quads.shape[0],
                ),
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
                    "range_mode": "fixed_symmetric_global_one_tenth_in_viewer",
                },
            },
            "landslide": {
                "file_pattern": "landslide/frame_{frame}.vtp",
                "compact": compact_layer_manifest(
                    template_path=landslide_template_path,
                    template_meta=landslide_template_meta,
                    frame_layout=landslide_frame_layout,
                    point_count=landslide_template["x"].size,
                    cell_count=landslide_quads.shape[0],
                ),
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
            "vtp_float_dtype": str(VTP_FLOAT_DTYPE_NAME),
            "browser_asset_format": "compact_v2",
            "stride": {
                "terrain": int(TERRAIN_STRIDE),
                "water": int(WATER_STRIDE),
                "water_coastal_detail": int(WATER_COASTAL_DETAIL_STRIDE),
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
                "coastal_detail": {
                    "enabled": True,
                    "coastline_elevation_m": float(SEA_LEVEL),
                    "offshore_width_m": float(WATER_COASTAL_DETAIL_OFFSHORE_M),
                    "inland_width_m": float(WATER_COASTAL_DETAIL_INLAND_M),
                    "stride": int(WATER_COASTAL_DETAIL_STRIDE),
                    "stride_meaning": "native_resolution",
                    "row_spacing_m": float(water_coastal_detail_plan["row_spacing_m"]),
                    "col_spacing_m": float(water_coastal_detail_plan["col_spacing_m"]),
                    "shoreline_point_count": int(water_coastal_detail_plan["shoreline_point_count"]),
                    "coastal_point_count": int(water_coastal_detail_plan["coastal_point_count"]),
                    "fine_cell_count": int(water_coastal_detail_plan["fine_cell_count"]),
                    "coarse_cell_count": int(water_coastal_detail_plan["coarse_cell_count"]),
                },
                "ocean_base_gate": {
                    "enabled": bool(WATER_REQUIRE_OCEAN_BASE),
                    "b0_max": float(SEA_LEVEL + WATER_OCEAN_B0_EPS),
                },
                "m_threshold_applied_at_export": False,
                "amplitude_outlier_guard": {
                    "enabled": bool(WATER_AMP_ROBUST_GUARD_ENABLED), "hard_abs_limit": float(WATER_AMP_ABS_HARD_LIMIT), "percentile": float(WATER_AMP_ROBUST_PERCENTILE),
                    "factor": float(WATER_AMP_OUTLIER_FACTOR),
                    "min_limit": float(WATER_AMP_MIN_LIMIT),
                    "per_browser_frame_limit": water_amp_limits,
                },
            },
            "landslide_surface": "Cropped to global landslide ROI, colored by hm, m, or Δb, and filtered by browser-side landslide solid-fraction cutoff.",
        },
    }

    preserve_existing_amr_metadata(case)

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
    water_frames = sorted(water_dir.glob("frame_*.bin.gz"))
    landslide_frames = sorted(landslide_dir.glob("frame_*.bin.gz"))

    print("[OK] Exported Aqaba Case 001 time series")
    print(f"  outdir:    {OUTDIR}")
    print(f"  terrain:   {terrain_path} ({file_size_mb(terrain_path):.2f} MB)")
    print(f"  water:     compact v2, {len(water_frames)} frames ({total_size_mb(water_dir):.2f} MB)")
    print(f"  landslide: compact v2, {len(landslide_frames)} frames ({total_size_mb(landslide_dir):.2f} MB)")
    print(f"  manifest:  {case_path} ({file_size_mb(case_path):.3f} MB)")
    print(f"  package:   {total_size_mb(OUTDIR):.2f} MB")
    print("")
    print("Settings")
    print(f"  frame_count:            {frame_count}")
    print(f"  default browser index:  {default_index}")
    print(f"  default native frame:   {native_default}")
    print(f"  terrain stride:         {TERRAIN_STRIDE}")
    print(f"  water stride:           {WATER_STRIDE}")
    print(
        "  water coastal detail:  "
        f"stride={WATER_COASTAL_DETAIL_STRIDE}, offshore={WATER_COASTAL_DETAIL_OFFSHORE_M:.0f} m, "
        f"inland={WATER_COASTAL_DETAIL_INLAND_M:.0f} m from z={SEA_LEVEL:g}"
    )
    print(f"  vtp float dtype:        {VTP_FLOAT_DTYPE_NAME}")
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the Aqaba LSB C10 compact gallery assets from D-Claw FORT output."
    )
    parser.add_argument("--case-dir", type=Path, default=CASE_DIR)
    parser.add_argument("--manta-src", type=Path, default=MANTA_SRC)
    parser.add_argument("--outdir", type=Path, default=OUTDIR)
    parser.add_argument("--frame-index", type=int, default=FRAME_INDEX)
    parser.add_argument("--title", default=TITLE)
    args = parser.parse_args()

    configure_runtime(
        case_dir=args.case_dir,
        manta_src=args.manta_src,
        outdir=args.outdir,
        frame_index=args.frame_index,
        title=args.title,
    )
    export_case()


if __name__ == "__main__":
    main()
