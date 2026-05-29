#!/usr/bin/env python3
"""
Export one MANTA/D-Claw frame into gallery-ready VTP files.

Output:
  <outdir>/
    case.json
    terrain.vtp
    water/frame_0000.vtp
    landslide/frame_0000.vtp
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np


def insert_manta_src(manta_src: Optional[str]) -> None:
    if not manta_src:
        return
    p = Path(manta_src).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"--manta-src does not exist: {p}")
    sys.path.insert(0, str(p))


def load_cube(source: str, case_dir: str, manta_src: Optional[str], prefer_gid: Optional[str]):
    insert_manta_src(manta_src)

    source = source.lower().strip()

    if source == "fgout":
        from visualization.dclaw_layers import DClawDataCube
        return DClawDataCube(case_dir, prefer_gid=prefer_gid)

    if source == "fort":
        from visualization.dclaw_layers import DClawFortCacheCube
        cube = DClawFortCacheCube(case_dir)
        try:
            cube.set_mode("mixed")
        except Exception:
            pass
        return cube

    raise ValueError(f"Unknown source: {source!r}; use 'fgout' or 'fort'.")


def as_2d(a: Any, name: str, shape: Optional[Tuple[int, int]] = None, required: bool = True):
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
    """Downsample all 2D array fields with the same row/column stride."""
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


def write_structured_vtp(
    X: np.ndarray,
    Y: np.ndarray,
    Z: np.ndarray,
    point_data: Dict[str, np.ndarray],
    path: Path,
) -> None:
    try:
        import pyvista as pv
    except Exception as e:
        raise RuntimeError("pyvista is required to export VTP files") from e

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

    # VTP is a PolyData format.  PyVista StructuredGrid must be converted
    # to a surface PolyData before saving as .vtp.
    mesh = grid.extract_surface()

    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.save(str(path))


def prepare_fields(S: Dict[str, Any], sea_level: float) -> Dict[str, np.ndarray]:
    X = as_2d(S.get("X"), "X")
    Y = as_2d(S.get("Y"), "Y", X.shape)

    b = as_2d(S.get("b"), "b", X.shape)
    b0 = as_2d(S.get("b0"), "b0", X.shape, required=False)
    if b0 is None:
        b0 = b

    h = as_2d(S.get("h"), "h", X.shape)

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
            m_raw = np.where(h > 1e-12, hm / h, 0.0)

    m = normalize_m(m_raw)

    db = as_2d(S.get("db"), "db", X.shape, required=False)
    if db is None:
        db = b - b0

    wave_amplitude = eta - float(sea_level)

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


def export_single_frame(
    source: str,
    case_dir: str,
    outdir: str,
    frame_index: int,
    manta_src: Optional[str],
    prefer_gid: Optional[str],
    sea_level: float,
    water_m: float,
    landslide_m: float,
    title: str,
    stride: int,
    water_stride: Optional[int],
    landslide_stride: Optional[int],
) -> None:
    cube = load_cube(source, case_dir, manta_src, prefer_gid)
    S = cube.get_slice(int(frame_index))
    F_full = prepare_fields(S, sea_level)

    water_stride = int(stride if water_stride is None else water_stride)
    landslide_stride = int(stride if landslide_stride is None else landslide_stride)
    water_stride = max(1, water_stride)
    landslide_stride = max(1, landslide_stride)

    # Terrain and water use the broader regional stride.
    # Landslide uses its own finer stride because the slide footprint is local.
    F = apply_stride(F_full, water_stride)
    F_slide = apply_stride(F_full, landslide_stride)

    out = Path(outdir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    X = F["X"]
    Y = F["Y"]
    b0 = F["b0"]
    b = F["b"]
    h = F["h"]
    eta = F["eta"]
    hm = F["hm"]
    m = F["m"]
    db = F["db"]
    wave_amplitude = F["wave_amplitude"]

    write_structured_vtp(
        X,
        Y,
        b0,
        {"elevation": b0},
        out / "terrain.vtp",
    )

    wet = np.isfinite(h) & (h > 5e-4) & np.isfinite(eta)
    Z_water = np.where(wet, eta, np.nan)
    water_amp = np.where(wet, wave_amplitude, np.nan)
    water_m_field = np.where(wet, m, np.nan)

    write_structured_vtp(
        X,
        Y,
        Z_water,
        {
            "wave_amplitude": water_amp,
            "m": water_m_field,
        },
        out / "water" / "frame_0000.vtp",
    )

    Xs = F_slide["X"]
    Ys = F_slide["Y"]
    bs = F_slide["b"]
    hms = F_slide["hm"]
    ms = F_slide["m"]
    dbs = F_slide["db"]

    slide_candidate = np.isfinite(hms) & np.isfinite(ms) & (hms > 1e-6)
    Z_slide = np.where(slide_candidate, bs + hms, np.nan)
    slide_hm = np.where(slide_candidate, hms, np.nan)
    slide_m = np.where(slide_candidate, ms, np.nan)
    slide_db = np.where(slide_candidate, dbs, np.nan)

    write_structured_vtp(
        Xs,
        Ys,
        Z_slide,
        {
            "hm": slide_hm,
            "m": slide_m,
            "db": slide_db,
        },
        out / "landslide" / "frame_0000.vtp",
    )

    t0 = 0.0
    try:
        times = cube.get_times()
        if times is not None and len(times) > int(frame_index):
            t0 = float(times[int(frame_index)])
    except Exception:
        pass

    case = {
        "id": out.name,
        "title": title,
        "description": "Single-frame gallery-ready export of wave amplitude and landslide material fields.",
        "source": {
            "kind": source,
            "case_dir": str(case_dir),
            "frame_index": int(frame_index),
            "raw_output": "not included"
        },
        "time": {
            "mode": "single_frame",
            "unit": "s",
            "values": [float(t0)],
            "default_index": 0
        },
        "layers": {
            "terrain": {
                "file": "terrain.vtp",
                "visible": True,
                "style": {
                    "mode": "sea_split",
                    "below_sea_level": {
                        "label": "Bathymetry",
                        "colormap": "cmocean.deep"
                    },
                    "above_sea_level": {
                        "label": "Topography",
                        "colormap": "cmcrameri.grayC",
                        "relief": True
                    }
                }
            },
            "water": {
                "file_pattern": "water/frame_{frame}.vtp",
                "visible": True,
                "display_scalar": "wave_amplitude",
                "filter_scalar": "m",
                "filter_rule": "m <= water_m",
                "default_m": float(water_m),
                "m_range": [0.0, 1.0],
                "label": "Wave amplitude",
                "unit": "m",
                "colormap": "dclaw.tsunami",
                "colormap_label": "Tsunami",
                "colorbar": {
                    "side": "right",
                    "range": nan_range(water_amp)
                }
            },
            "landslide": {
                "file_pattern": "landslide/frame_{frame}.vtp",
                "visible": True,
                "filter_scalar": "m",
                "filter_rule": "m >= landslide_m",
                "default_m": float(landslide_m),
                "m_range": [0.0, 1.0],
                "default_scalar": "hm",
                "colormap": "magma",
                "colorbar": {
                    "side": "left"
                },
                "available_scalars": {
                    "hm": {
                        "label": "hm (solid thickness)",
                        "unit": "m",
                        "range": nan_range(slide_hm)
                    },
                    "m": {
                        "label": "m (solid fraction)",
                        "unit": "1",
                        "range": [0.0, 1.0]
                    },
                    "db": {
                        "label": "Δb (bed change)",
                        "unit": "m",
                        "range": nan_range(slide_db)
                    }
                }
            }
        },
        "ui": {
            "show_layer_toggles": True,
            "show_time_slider": False,
            "show_water_m_slider": True,
            "show_landslide_m_slider": True,
            "show_landslide_scalar_selector": True,
            "show_colormap_controls": False,
            "show_dem_style_controls": False,
            "show_vertical_exaggeration": False
        },
        "camera": {
            "preset": "oblique"
        },
        "processing": {
            "sea_level": float(sea_level),
            "stride": {
                "terrain": int(water_stride),
                "water": int(water_stride),
                "landslide": int(landslide_stride)
            },
            "water_surface": "Colored by wave amplitude and filtered by water-like solid-fraction cutoff.",
            "landslide_surface": "Colored by hm, m, or Δb and filtered by landslide solid-fraction cutoff."
        }
    }

    with open(out / "case.json", "w", encoding="utf-8") as f:
        json.dump(case, f, indent=2, ensure_ascii=False)

    print(f"[OK] Exported gallery case to: {out}")
    print(f"     terrain:   {out / 'terrain.vtp'}")
    print(f"     water:     {out / 'water' / 'frame_0000.vtp'}")
    print(f"     landslide: {out / 'landslide' / 'frame_0000.vtp'}")
    print(f"     manifest:  {out / 'case.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export one MANTA/D-Claw frame for MANTA Gallery.")
    parser.add_argument("--source", choices=["fgout", "fort"], required=True)
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument("--manta-src", default=None)
    parser.add_argument("--prefer-gid", default=None)
    parser.add_argument("--sea-level", type=float, default=0.0)
    parser.add_argument("--water-m", type=float, default=0.001)
    parser.add_argument("--landslide-m", type=float, default=0.30)
    parser.add_argument("--title", default="Aqaba landslide-tsunami simulation")
    parser.add_argument("--stride", type=int, default=20, help="Fallback row/column downsampling stride.")
    parser.add_argument("--water-stride", type=int, default=None, help="Row/column stride for terrain and water layers.")
    parser.add_argument("--landslide-stride", type=int, default=None, help="Row/column stride for landslide layer.")
    args = parser.parse_args()

    export_single_frame(
        source=args.source,
        case_dir=args.case_dir,
        outdir=args.outdir,
        frame_index=args.frame_index,
        manta_src=args.manta_src,
        prefer_gid=args.prefer_gid,
        sea_level=args.sea_level,
        water_m=args.water_m,
        landslide_m=args.landslide_m,
        title=args.title,
        stride=args.stride,
        water_stride=args.water_stride,
        landslide_stride=args.landslide_stride,
    )


if __name__ == "__main__":
    main()
