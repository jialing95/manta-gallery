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
    - DEM / water are exported over the full domain with coarse stride.
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

# Browser-side default thresholds
WATER_M_DEFAULT = 0.30
LANDSLIDE_M_DEFAULT = 0.0

# Export resolution
TERRAIN_WATER_STRIDE = 20
LANDSLIDE_STRIDE = 5

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

    # Compute fixed global landslide ROI before exporting the target frame.
    global_landslide_roi, global_landslide_roi_meta = compute_global_landslide_roi(cube)

    S = cube.get_slice(FRAME_INDEX)
    F_full = prepare_fields(S)

    OUTDIR.mkdir(parents=True, exist_ok=True)

    # Terrain and water: full domain, coarser stride
    F_tw = apply_stride(F_full, TERRAIN_WATER_STRIDE)

    X = F_tw["X"]
    Y = F_tw["Y"]
    b0 = F_tw["b0"]
    h = F_tw["h"]
    eta = F_tw["eta"]
    m = F_tw["m"]
    wave_amplitude = F_tw["wave_amplitude"]

    write_surface_vtp(
        X,
        Y,
        b0,
        {"elevation": b0},
        OUTDIR / "terrain.vtp",
    )

    wet = np.isfinite(h) & (h > 5.0e-4) & np.isfinite(eta)

    Z_water = np.where(wet, eta, np.nan)
    water_amp = np.where(wet, wave_amplitude, np.nan)
    water_m = np.where(wet, m, np.nan)

    write_surface_vtp(
        X,
        Y,
        Z_water,
        {
            "wave_amplitude": water_amp,
            "m": water_m,
        },
        OUTDIR / "water" / "frame_0000.vtp",
    )

    # Landslide: finer stride + global ROI crop
    F_ls = apply_stride(F_full, LANDSLIDE_STRIDE)
    F_ls_roi = crop_dict_to_roi(F_ls, global_landslide_roi)

    Xs = F_ls_roi["X"]
    Ys = F_ls_roi["Y"]
    bs = F_ls_roi["b"]
    hms = F_ls_roi["hm"]
    ms = F_ls_roi["m"]
    dbs = F_ls_roi["db"]

    slide_candidate = (
        np.isfinite(hms)
        & np.isfinite(ms)
        & np.isfinite(dbs)
        & (hms > LANDSLIDE_ROI_HM_EPS)
    )

    Z_slide = np.where(slide_candidate, bs + hms, np.nan)
    slide_hm = np.where(slide_candidate, hms, np.nan)
    slide_m = np.where(slide_candidate, ms, np.nan)
    slide_db = np.where(slide_candidate, dbs, np.nan)

    write_surface_vtp(
        Xs,
        Ys,
        Z_slide,
        {
            "hm": slide_hm,
            "m": slide_m,
            "db": slide_db,
        },
        OUTDIR / "landslide" / "frame_0000.vtp",
    )

    t0 = 0.0
    try:
        times = cube.get_times()
        if times is not None and len(times) > FRAME_INDEX:
            t0 = float(times[FRAME_INDEX])
    except Exception:
        pass

    case = {
        "id": OUTDIR.name,
        "title": TITLE,
        "description": "Single-frame gallery-ready export of wave amplitude and landslide material fields.",
        "source": {
            "kind": SOURCE,
            "case_dir": str(CASE_DIR),
            "frame_index": int(FRAME_INDEX),
            "raw_output": "not included",
        },
        "time": {
            "mode": "single_frame",
            "unit": "s",
            "values": [float(t0)],
            "default_index": 0,
        },
        "layers": {
            "terrain": {
                "file": "terrain.vtp",
                "visible": True,
                "style": {
                    "mode": "sea_split",
                    "below_sea_level": {
                        "label": "Bathymetry",
                        "colormap": "cmocean.deep",
                    },
                    "above_sea_level": {
                        "label": "Topography",
                        "colormap": "cmcrameri.grayC",
                        "relief": True,
                    },
                },
            },
            "water": {
                "file_pattern": "water/frame_{frame}.vtp",
                "visible": True,
                "display_scalar": "wave_amplitude",
                "filter_scalar": "m",
                "filter_rule": "m <= water_m",
                "default_m": float(WATER_M_DEFAULT),
                "m_range": [0.0, 1.0],
                "label": "Wave amplitude",
                "unit": "m",
                "colormap": "dclaw.tsunami",
                "colormap_label": "Tsunami",
                "colorbar": {
                    "side": "right",
                    "range": nan_range(water_amp),
                },
            },
            "landslide": {
                "file_pattern": "landslide/frame_{frame}.vtp",
                "visible": True,
                "filter_scalar": "m",
                "filter_rule": "m >= landslide_m",
                "default_m": float(LANDSLIDE_M_DEFAULT),
                "m_range": [0.0, 1.0],
                "default_scalar": "hm",
                "colormap": "magma",
                "colorbar": {
                    "side": "left",
                },
                "available_scalars": {
                    "hm": {
                        "label": "hm (solid thickness)",
                        "unit": "m",
                        "range": nan_range(slide_hm),
                    },
                    "m": {
                        "label": "m (solid fraction)",
                        "unit": "1",
                        "range": [0.0, 1.0],
                    },
                    "db": {
                        "label": "Δb (bed change)",
                        "unit": "m",
                        "range": nan_range(slide_db),
                    },
                },
            },
        },
        "ui": {
            "show_layer_toggles": True,
            "show_time_slider": False,
            "show_water_m_slider": True,
            "show_landslide_m_slider": True,
            "show_landslide_scalar_selector": True,
            "show_colormap_controls": False,
            "show_dem_style_controls": False,
            "show_vertical_exaggeration": False,
        },
        "camera": {
            "preset": "oblique",
        },
        "processing": {
            "sea_level": float(SEA_LEVEL),
            "stride": {
                "terrain": int(TERRAIN_WATER_STRIDE),
                "water": int(TERRAIN_WATER_STRIDE),
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
            "water_surface": "Colored by wave amplitude and filtered by water-like solid-fraction cutoff.",
            "landslide_surface": "Cropped to global landslide ROI, colored by hm, m, or Δb, and filtered by landslide solid-fraction cutoff.",
        },
    }

    with open(OUTDIR / "case.json", "w", encoding="utf-8") as f:
        json.dump(case, f, indent=2, ensure_ascii=False)

    print_export_summary(
        terrain_path=OUTDIR / "terrain.vtp",
        water_path=OUTDIR / "water" / "frame_0000.vtp",
        landslide_path=OUTDIR / "landslide" / "frame_0000.vtp",
        case_path=OUTDIR / "case.json",
        water_amp=water_amp,
        water_m=water_m,
        slide_hm=slide_hm,
        slide_m=slide_m,
        slide_db=slide_db,
        roi=global_landslide_roi,
    )


def print_export_summary(
    *,
    terrain_path: Path,
    water_path: Path,
    landslide_path: Path,
    case_path: Path,
    water_amp: np.ndarray,
    water_m: np.ndarray,
    slide_hm: np.ndarray,
    slide_m: np.ndarray,
    slide_db: np.ndarray,
    roi: Tuple[int, int, int, int],
) -> None:
    water_keep = (
        np.isfinite(water_amp)
        & np.isfinite(water_m)
        & (water_m <= WATER_M_DEFAULT)
    )

    slide_keep = (
        np.isfinite(slide_hm)
        & np.isfinite(slide_m)
        & np.isfinite(slide_db)
        & (slide_m >= LANDSLIDE_M_DEFAULT)
    )

    print("[OK] Exported Aqaba Case 001")
    print(f"  outdir:    {OUTDIR}")
    print(f"  terrain:   {terrain_path} ({file_size_mb(terrain_path):.2f} MB)")
    print(f"  water:     {water_path} ({file_size_mb(water_path):.2f} MB)")
    print(f"  landslide: {landslide_path} ({file_size_mb(landslide_path):.2f} MB)")
    print(f"  manifest:  {case_path} ({file_size_mb(case_path):.3f} MB)")
    print("")
    print("Settings")
    print(f"  frame_index:            {FRAME_INDEX}")
    print(f"  terrain/water stride:   {TERRAIN_WATER_STRIDE}")
    print(f"  landslide stride:       {LANDSLIDE_STRIDE}")
    print(f"  landslide roi pad:      {LANDSLIDE_ROI_PAD}")
    print(f"  landslide roi rc:       {roi}")
    print("")
    print("Default display diagnostics")
    print(f"  water m <= {WATER_M_DEFAULT}: {int(water_keep.sum())} / {water_amp.size}")
    if np.any(water_keep):
        print(
            "    wave amplitude range: "
            f"{float(np.nanmin(water_amp[water_keep])):.6g} to "
            f"{float(np.nanmax(water_amp[water_keep])):.6g}"
        )
    print(f"  landslide m >= {LANDSLIDE_M_DEFAULT}: {int(slide_keep.sum())} / {slide_hm.size}")
    if np.any(slide_keep):
        print(
            f"    hm range: {float(np.nanmin(slide_hm[slide_keep])):.6g} to "
            f"{float(np.nanmax(slide_hm[slide_keep])):.6g}"
        )
        print(
            f"    m range:  {float(np.nanmin(slide_m[slide_keep])):.6g} to "
            f"{float(np.nanmax(slide_m[slide_keep])):.6g}"
        )
        print(
            f"    db range: {float(np.nanmin(slide_db[slide_keep])):.6g} to "
            f"{float(np.nanmax(slide_db[slide_keep])):.6g}"
        )


if __name__ == "__main__":
    export_case()
