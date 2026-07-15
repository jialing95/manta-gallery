#!/usr/bin/env python3
"""Make the receiver-side bathymetry asymmetry manuscript figure."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np


CASE_ORDER = (
    "aqaba_lsa_c10_angm25",
    "aqaba_lsb_nc10_angm20",
    "aqaba_lsc_c10_angm30",
    "aqaba_lsd_nc8_angm40",
    "aqaba_lse_c10_angm40",
    "aqaba_lsf_nc10_angm30",
)
CASE_LABELS = {
    "aqaba_lsa_c10_angm25": "LSA",
    "aqaba_lsb_nc10_angm20": "LSB",
    "aqaba_lsc_c10_angm30": "LSC",
    "aqaba_lsd_nc8_angm40": "LSD",
    "aqaba_lse_c10_angm40": "LSE",
    "aqaba_lsf_nc10_angm30": "LSF",
}

EAST_COLOR = "#b2182b"
WEST_COLOR = "#2166ac"
SHORE_COLOR = "#343434"
CORRIDOR_COLOR = "#6f8797"
CONTOUR_COLOR = "#24475a"
MULTIBEAM_COLOR = "#0b8f7a"
FOOTPRINT_COLOR = "#d6a313"
CONTROL_LINE_COLOR = "#ff2aa1"
PANEL_A_NORTH_LONLAT = (34.6634, 29.10)
PANEL_A_PAD_X_M = 4500.0
PANEL_A_PAD_SOUTH_M = 4500.0


@dataclass(frozen=True)
class TT3Grid:
    grid: np.ndarray
    ncols: int
    nrows: int
    xllcenter: float
    yllcenter: float
    dx: float
    dy: float
    nodata: float

    @property
    def x_centers(self) -> np.ndarray:
        return self.xllcenter + np.arange(self.ncols, dtype=np.float64) * self.dx

    @property
    def y_centers(self) -> np.ndarray:
        return self.yllcenter + np.arange(self.nrows, dtype=np.float64) * self.dy

    @property
    def xmin(self) -> float:
        return self.xllcenter - 0.5 * self.dx

    @property
    def xmax(self) -> float:
        return self.xmin + self.ncols * self.dx

    @property
    def ymin(self) -> float:
        return self.yllcenter - 0.5 * self.dy

    @property
    def ymax(self) -> float:
        return self.ymin + self.nrows * self.dy


@dataclass(frozen=True)
class MultibeamPanel:
    ribot_depth: np.ndarray
    diff: np.ndarray
    footprint: np.ndarray
    x: np.ndarray
    y: np.ndarray
    extent: tuple[float, float, float, float]
    strict_limit: float
    valid_count: int
    overlap_count: int
    footprint_segments_lonlat: list[np.ndarray]


@dataclass(frozen=True)
class UtmRasterPanel:
    depth: np.ndarray
    z: np.ndarray
    x: np.ndarray
    y: np.ndarray
    extent: tuple[float, float, float, float]


@dataclass(frozen=True)
class HotspotTransect:
    index: int
    side: str
    recurrence: int
    speed: float
    case_count: int
    shore_point: np.ndarray
    end_point: np.ndarray
    hotspot_point: np.ndarray
    hotspot_distance_m: float
    distance_m: np.ndarray
    gmrt_depth: np.ndarray
    ribot_depth: np.ndarray


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def read_tt3(path: Path) -> TT3Grid:
    with path.open("r", encoding="utf-8") as handle:
        header = [next(handle).split() for _ in range(6)]
    ncols = int(header[0][0])
    nrows = int(header[1][0])
    xllcenter = float(header[2][0])
    yllcenter = float(header[3][0])
    cells = [float(value) for value in header[4] if is_float(value)]
    dx = cells[0]
    dy = cells[1] if len(cells) > 1 else dx
    nodata = float(header[5][0])
    grid = np.loadtxt(path, skiprows=6, dtype=np.float32)
    if grid.shape != (nrows, ncols):
        raise ValueError(f"{path}: expected {(nrows, ncols)}, got {grid.shape}")
    grid = np.flipud(grid)
    grid[grid == np.float32(nodata)] = np.nan
    return TT3Grid(grid, ncols, nrows, xllcenter, yllcenter, dx, dy, nodata)


def load_shorelines(path: Path) -> dict[str, np.ndarray]:
    geojson = read_json(path)
    shorelines: dict[str, np.ndarray] = {}
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        side = str(props.get("side", "")).lower()
        if side not in {"east", "west"}:
            continue
        line = np.asarray(feature["geometry"]["coordinates"], dtype=np.float64)
        if line[0, 1] > line[-1, 1]:
            line = line[::-1].copy()
        shorelines[side] = line[:, :2]
    if set(shorelines) != {"east", "west"}:
        raise ValueError(f"{path}: expected east and west shorelines")
    return shorelines


def sample_grid(grid: TT3Grid, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    fx = (x - grid.xllcenter) / grid.dx
    fy = (y - grid.yllcenter) / grid.dy
    ix = np.floor(fx).astype(np.int64)
    iy = np.floor(fy).astype(np.int64)
    valid = (ix >= 0) & (iy >= 0) & (ix < grid.ncols - 1) & (iy < grid.nrows - 1)
    if not np.any(valid):
        return out
    i = ix[valid]
    j = iy[valid]
    tx = fx[valid] - i
    ty = fy[valid] - j
    z00 = grid.grid[j, i].astype(np.float64)
    z10 = grid.grid[j, i + 1].astype(np.float64)
    z01 = grid.grid[j + 1, i].astype(np.float64)
    z11 = grid.grid[j + 1, i + 1].astype(np.float64)
    finite = np.isfinite(z00) & np.isfinite(z10) & np.isfinite(z01) & np.isfinite(z11)
    vals = (
        (1 - tx) * (1 - ty) * z00
        + tx * (1 - ty) * z10
        + (1 - tx) * ty * z01
        + tx * ty * z11
    )
    tmp = out[valid]
    tmp[finite] = vals[finite]
    out[valid] = tmp
    return out


def arclength(line: np.ndarray) -> np.ndarray:
    d = np.hypot(np.diff(line[:, 0]), np.diff(line[:, 1]))
    return np.concatenate(([0.0], np.cumsum(d)))


def resample_line(line: np.ndarray, spacing_m: float) -> tuple[np.ndarray, np.ndarray]:
    s = arclength(line)
    targets = np.arange(0.0, s[-1] + 1e-9, spacing_m)
    if targets[-1] < s[-1]:
        targets = np.append(targets, s[-1])
    points = np.column_stack((
        np.interp(targets, s, line[:, 0]),
        np.interp(targets, s, line[:, 1]),
    ))
    return targets, points


def station_tangents(points: np.ndarray) -> np.ndarray:
    tangents = np.zeros_like(points)
    for idx in range(points.shape[0]):
        if idx == 0:
            vec = points[1] - points[0]
        elif idx == points.shape[0] - 1:
            vec = points[-1] - points[-2]
        else:
            vec = points[idx + 1] - points[idx - 1]
        norm = float(np.linalg.norm(vec))
        tangents[idx] = vec / norm if norm > 0 else np.asarray([0.0, 1.0])
    return tangents


def seaward_normals(grid: TT3Grid, points: np.ndarray, tangents: np.ndarray, test_m: float = 500.0) -> np.ndarray:
    normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
    test = points + normals * test_m
    z = sample_grid(grid, test[:, 0], test[:, 1])
    flip = ~np.isfinite(z) | (z >= 0.0)
    normals[flip] *= -1.0
    test = points + normals * test_m
    z = sample_grid(grid, test[:, 0], test[:, 1])
    still_land = np.isfinite(z) & (z >= 0.0)
    normals[still_land] *= -1.0
    return normals


def corridor_boundaries(grid: TT3Grid, shorelines: dict[str, np.ndarray], offset_m: float) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for side, line in shorelines.items():
        _, points = resample_line(line, 250.0)
        tangents = station_tangents(points)
        normals = seaward_normals(grid, points, tangents)
        out[side] = points + normals * offset_m
    return out


def cross_shore_profiles(
    grid: TT3Grid,
    shorelines: dict[str, np.ndarray],
    station_spacing_m: float,
    max_distance_m: float,
    distance_step_m: float,
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, dict[str, np.ndarray]]]:
    distances = np.arange(0.0, max_distance_m + 1e-9, distance_step_m)
    profiles: dict[str, np.ndarray] = {}
    summaries: dict[str, dict[str, np.ndarray]] = {}
    for side, line in shorelines.items():
        _, points = resample_line(line, station_spacing_m)
        tangents = station_tangents(points)
        normals = seaward_normals(grid, points, tangents)
        arr = []
        for point, normal in zip(points, normals):
            xy = point + distances[:, None] * normal
            z = sample_grid(grid, xy[:, 0], xy[:, 1])
            depth = np.where(np.isfinite(z), np.maximum(0.0, -z), np.nan)
            depth[0] = 0.0
            arr.append(depth)
        profile = np.asarray(arr, dtype=np.float64)
        profiles[side] = profile
        summaries[side] = {
            "median": np.nanmedian(profile, axis=0),
            "q25": np.nanpercentile(profile, 25, axis=0),
            "q75": np.nanpercentile(profile, 75, axis=0),
        }
    return distances, profiles, summaries


def aggregate_hotspots(rows: list[dict[str, str]], cell_m: float) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, int], list[dict[str, str]]] = {}
    for row in rows:
        if row.get("zone") != "seaward":
            continue
        if abs(float(row.get("requested_time_min_s", "nan")) - 900.0) > 1e-6:
            continue
        if abs(float(row.get("seaward_distance_m", "nan")) - 1000.0) > 1e-6:
            continue
        if abs(float(row.get("landward_distance_m", "nan")) - 500.0) > 1e-6:
            continue
        x = float(row["x_m"])
        y = float(row["y_m"])
        key = (row["side"], int(round(x / cell_m)), int(round(y / cell_m)))
        groups.setdefault(key, []).append(row)
    out = []
    for (side, _, _), items in groups.items():
        case_count = len({item["case_id"] for item in items})
        recurrence = int(sum(int(item["displayed_frame_count"]) for item in items))
        if case_count < 2 and recurrence < 2:
            continue
        weights = np.asarray([max(1, int(item["displayed_frame_count"])) for item in items], dtype=np.float64)
        xs = np.asarray([float(item["x_m"]) for item in items], dtype=np.float64)
        ys = np.asarray([float(item["y_m"]) for item in items], dtype=np.float64)
        speeds = np.asarray([float(item["max_displayed_speed_mps"]) for item in items], dtype=np.float64)
        out.append({
            "side": side,
            "x": float(np.average(xs, weights=weights)),
            "y": float(np.average(ys, weights=weights)),
            "speed": float(np.median(speeds)),
            "max_speed": float(np.max(speeds)),
            "recurrence": recurrence,
            "case_count": case_count,
            "point_count": len(items),
        })
    return sorted(out, key=lambda item: item["speed"])


def scenario_ratios(summary_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_case: dict[str, dict[str, str]] = {}
    for row in summary_rows:
        if row.get("zone") != "seaward":
            continue
        if abs(float(row["requested_time_min_s"]) - 900.0) > 1e-6:
            continue
        if abs(float(row["seaward_distance_m"]) - 1000.0) > 1e-6:
            continue
        if abs(float(row["landward_distance_m"]) - 500.0) > 1e-6:
            continue
        by_case[row["case_id"]] = row
    rows = []
    for case_id in CASE_ORDER:
        row = by_case.get(case_id)
        if not row:
            continue
        rows.append({
            "case_id": case_id,
            "label": CASE_LABELS.get(case_id, case_id),
            "ratio": float(row["east_west_median_frame_top10_ratio"]),
            "east": float(row["east_median_frame_top10_mean_mps"]),
            "west": float(row["west_median_frame_top10_mean_mps"]),
            "source_group": "western-source" if case_id in CASE_ORDER[:3] else "eastern-source",
        })
    return rows


def native_isobath_summary(metrics_rows: list[dict[str, str]]) -> dict[str, dict[str, tuple[float, float, float]]]:
    fields = ("distance_to_20m_isobath", "distance_to_50m_isobath")
    out: dict[str, dict[str, tuple[float, float, float]]] = {"east": {}, "west": {}}
    for side in ("east", "west"):
        side_rows = [row for row in metrics_rows if row.get("side") == side and row.get("representation", "native") == "native"]
        for field in fields:
            values = []
            for row in side_rows:
                try:
                    value = float(row[field])
                except (KeyError, ValueError):
                    continue
                if math.isfinite(value):
                    values.append(value)
            arr = np.asarray(values, dtype=np.float64)
            out[side][field] = (
                float(np.nanmedian(arr)),
                float(np.nanpercentile(arr, 25)),
                float(np.nanpercentile(arr, 75)),
            )
    return out


def lonlat_to_utm37(points: Iterable[tuple[float, float]]) -> np.ndarray:
    try:
        from rasterio.warp import transform
    except Exception as exc:
        raise RuntimeError("rasterio is required for lon/lat annotation transforms") from exc
    pts = list(points)
    lons = [point[0] for point in pts]
    lats = [point[1] for point in pts]
    xs, ys = transform("EPSG:4326", "EPSG:32637", lons, lats)
    return np.column_stack((xs, ys)).astype(np.float64)


def utm37_to_lonlat(points: Iterable[tuple[float, float]]) -> np.ndarray:
    try:
        from rasterio.warp import transform
    except Exception as exc:
        raise RuntimeError("rasterio is required for map annotation transforms") from exc
    pts = list(points)
    xs = [point[0] for point in pts]
    ys = [point[1] for point in pts]
    lons, lats = transform("EPSG:32637", "EPSG:4326", xs, ys)
    return np.column_stack((lons, lats)).astype(np.float64)


def segments_lonlat_to_utm37(segments: list[np.ndarray]) -> list[np.ndarray]:
    out = []
    for segment in segments:
        if segment.shape[0] < 2:
            continue
        out.append(lonlat_to_utm37([(float(x), float(y)) for x, y in segment]))
    return out


def contour_segments_from_mask(x: np.ndarray, y: np.ndarray, mask: np.ndarray) -> list[np.ndarray]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    z = mask.astype(np.float32)
    yy = y
    zz = z
    if yy[0] > yy[-1]:
        yy = yy[::-1]
        zz = zz[::-1, :]
    fig, ax = plt.subplots(figsize=(2, 2))
    cs = ax.contour(x, yy, zz, levels=[0.5])
    segments = [np.asarray(seg, dtype=np.float64) for seg in cs.allsegs[0] if len(seg) >= 2]
    plt.close(fig)
    return segments


def multibeam_footprint(path: Path) -> np.ndarray:
    try:
        import rasterio
        from rasterio.warp import transform
    except Exception as exc:
        raise RuntimeError("rasterio is required for multibeam footprint transforms") from exc
    with rasterio.open(path) as ds:
        b = ds.bounds
        corners = [(b.left, b.bottom), (b.left, b.top), (b.right, b.top), (b.right, b.bottom)]
        xs, ys = transform(ds.crs, "EPSG:32637", [p[0] for p in corners], [p[1] for p in corners])
    return np.column_stack((xs, ys)).astype(np.float64)


def read_raster_depth_on_utm_grid(
    path: Path,
    extent: tuple[float, float, float, float],
    cell_size_m: float = 120.0,
) -> UtmRasterPanel:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.warp import reproject

    x0, x1, y0, y1 = extent
    width = max(1, int(math.ceil((x1 - x0) / cell_size_m)))
    height = max(1, int(math.ceil((y1 - y0) / cell_size_m)))
    actual_right = x0 + width * cell_size_m
    actual_bottom = y1 - height * cell_size_m
    dst_transform = from_origin(x0, y1, cell_size_m, cell_size_m)
    dst = np.full((height, width), np.nan, dtype=np.float32)

    with rasterio.open(path) as ds:
        source = ds.read(1, masked=True).filled(np.nan).astype(np.float32)
        reproject(
            source=source,
            destination=dst,
            src_transform=ds.transform,
            src_crs=ds.crs,
            src_nodata=np.nan,
            dst_transform=dst_transform,
            dst_crs="EPSG:32637",
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    z = np.flipud(dst).astype(np.float64)
    depth = np.where(np.isfinite(z) & (z < 0.0), -z, np.nan)
    x = x0 + (np.arange(width, dtype=np.float64) + 0.5) * cell_size_m
    y = actual_bottom + (np.arange(height, dtype=np.float64) + 0.5) * cell_size_m
    return UtmRasterPanel(
        depth=depth,
        z=z,
        x=x,
        y=y,
        extent=(float(x0), float(actual_right), float(actual_bottom), float(y1)),
    )


def nearest_shoreline_control_line(
    point: np.ndarray,
    shoreline: np.ndarray,
    gmrt_path: Path,
    length_m: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    starts = shoreline[:-1]
    ends = shoreline[1:]
    vec = ends - starts
    seg_len2 = np.sum(vec * vec, axis=1)
    valid = seg_len2 > 0.0
    if not np.any(valid):
        raise ValueError("shoreline has no non-zero-length segments")
    starts_v = starts[valid]
    vec_v = vec[valid]
    seg_len2_v = seg_len2[valid]
    t = np.clip(np.sum((point - starts_v) * vec_v, axis=1) / seg_len2_v, 0.0, 1.0)
    projected = starts_v + t[:, None] * vec_v
    d2 = np.sum((projected - point) ** 2, axis=1)
    best = int(np.argmin(d2))
    shore_point = projected[best]
    tangent = vec_v[best] / math.sqrt(float(seg_len2_v[best]))
    normal = np.asarray([-tangent[1], tangent[0]], dtype=np.float64)

    # Orient the line by the background bathymetry, not by tiny hotspot-to-shore
    # offsets. This keeps near-shore points from accidentally sending a transect
    # landward when the velocity cell is almost on top of the shoreline.
    probe_d = np.linspace(25.0, length_m, 41, dtype=np.float64)
    candidates = (normal, -normal)
    scores = []
    for candidate in candidates:
        probe_xy = shore_point + probe_d[:, None] * candidate
        probe_depth = sample_raster_depth_at_utm(gmrt_path, probe_xy)
        finite = np.isfinite(probe_depth)
        finite_count = int(np.count_nonzero(finite))
        median_depth = float(np.nanmedian(probe_depth[finite])) if finite_count else -1.0
        far_depth = float(probe_depth[finite][-1]) if finite_count else -1.0
        scores.append((finite_count, median_depth, far_depth))
    if scores[1] > scores[0]:
        normal *= -1.0

    hotspot_distance = float(np.dot(point - shore_point, normal))
    return shore_point, normal, hotspot_distance


def sample_raster_depth_at_utm(path: Path, xy_utm: np.ndarray) -> np.ndarray:
    import rasterio
    from rasterio.warp import transform

    with rasterio.open(path) as ds:
        xs, ys = transform("EPSG:32637", ds.crs, xy_utm[:, 0].tolist(), xy_utm[:, 1].tolist())
        values = []
        for sample in ds.sample(zip(xs, ys), indexes=1, masked=True):
            value = sample[0]
            if np.ma.is_masked(value):
                values.append(np.nan)
            else:
                scalar = float(value)
                if not math.isfinite(scalar):
                    values.append(np.nan)
                elif ds.nodata is not None and math.isfinite(float(ds.nodata)) and scalar == float(ds.nodata):
                    values.append(np.nan)
                else:
                    values.append(scalar)
    z = np.asarray(values, dtype=np.float64)
    return np.where(np.isfinite(z) & (z < 0.0), -z, np.nan)


def build_hotspot_transects(
    hotspots: list[dict[str, Any]],
    shorelines: dict[str, np.ndarray],
    gmrt_path: Path,
    ribot_path: Path,
    length_m: float,
    step_m: float,
) -> list[HotspotTransect]:
    ordered = sorted(hotspots, key=lambda item: (item["side"], item["y"], item["x"]))
    distances = np.arange(0.0, length_m + 1e-9, step_m, dtype=np.float64)
    transects: list[HotspotTransect] = []
    for idx, hotspot in enumerate(ordered, start=1):
        side = str(hotspot["side"])
        point = np.asarray([float(hotspot["x"]), float(hotspot["y"])], dtype=np.float64)
        shore_point, normal, hotspot_distance = nearest_shoreline_control_line(point, shorelines[side], gmrt_path, length_m)
        xy = shore_point + distances[:, None] * normal
        transects.append(HotspotTransect(
            index=idx,
            side=side,
            recurrence=int(hotspot["recurrence"]),
            speed=float(hotspot["speed"]),
            case_count=int(hotspot["case_count"]),
            shore_point=shore_point,
            end_point=shore_point + length_m * normal,
            hotspot_point=point,
            hotspot_distance_m=hotspot_distance,
            distance_m=distances,
            gmrt_depth=sample_raster_depth_at_utm(gmrt_path, xy),
            ribot_depth=sample_raster_depth_at_utm(ribot_path, xy),
        ))
    return transects


def select_panel_a_transects(transects: list[HotspotTransect], count: int = 3) -> list[HotspotTransect]:
    def ribot_count(transect: HotspotTransect) -> int:
        return int(np.count_nonzero(np.isfinite(transect.ribot_depth)))

    candidates = [t for t in transects if t.side == "east" and ribot_count(t) >= 30]
    if len(candidates) < count:
        candidates = [t for t in transects if ribot_count(t) >= 30]
    if len(candidates) <= count:
        return sorted(candidates, key=lambda item: item.shore_point[1])[:count]

    ordered = sorted(candidates, key=lambda item: item.shore_point[1])
    targets = np.linspace(0, len(ordered) - 1, count + 2)[1:-1]
    selected: list[HotspotTransect] = []
    used: set[int] = set()
    for target in targets:
        order = sorted(
            range(len(ordered)),
            key=lambda idx: (abs(idx - target), -ordered[idx].recurrence, -ordered[idx].speed),
        )
        for idx in order:
            if idx not in used:
                selected.append(ordered[idx])
                used.add(idx)
                break
    return sorted(selected, key=lambda item: item.shore_point[1])


def read_multibeam_panel(ribot_path: Path, gmrt_path: Path, stride: int = 4) -> MultibeamPanel:
    import rasterio

    with rasterio.open(ribot_path) as ribot_ds, rasterio.open(gmrt_path) as gmrt_ds:
        ribot = ribot_ds.read(1, masked=True).filled(np.nan).astype(np.float32)
        gmrt = gmrt_ds.read(1, masked=True).filled(np.nan).astype(np.float32)
        if ribot.shape != gmrt.shape:
            raise ValueError("Ribot and GMRT rasters must be on the same A2 grid")
        valid = np.isfinite(ribot)
        strict = valid & np.isfinite(gmrt) & (ribot < -50.0)
        diff = np.where(strict, ribot - gmrt, np.nan)
        rows, cols = np.nonzero(valid)
        if rows.size == 0:
            raise ValueError(f"{ribot_path}: no valid Ribot cells")
        pad = 60
        r0 = max(0, int(rows.min()) - pad)
        r1 = min(valid.shape[0], int(rows.max()) + pad + 1)
        c0 = max(0, int(cols.min()) - pad)
        c1 = min(valid.shape[1], int(cols.max()) + pad + 1)
        diff_crop = diff[r0:r1:stride, c0:c1:stride]
        ribot_depth_crop = np.where(valid, np.maximum(0.0, -ribot), np.nan)[r0:r1:stride, c0:c1:stride]
        footprint_crop = valid[r0:r1:stride, c0:c1:stride].astype(np.float32)
        transform = ribot_ds.transform
        left = transform.c + c0 * transform.a
        right = transform.c + c1 * transform.a
        top = transform.f + r0 * transform.e
        bottom = transform.f + r1 * transform.e
        x = left + (np.arange(diff_crop.shape[1]) * stride + 0.5 * stride) * transform.a
        y = top + (np.arange(diff_crop.shape[0]) * stride + 0.5 * stride) * transform.e
    segments = contour_segments_from_mask(x.astype(np.float64), y.astype(np.float64), footprint_crop > 0.5)
    vals = np.abs(diff[np.isfinite(diff)])
    limit = float(max(np.percentile(vals, 98), 20.0)) if vals.size else 20.0
    return MultibeamPanel(
        ribot_depth=ribot_depth_crop,
        diff=diff_crop,
        footprint=footprint_crop,
        x=x.astype(np.float64),
        y=y.astype(np.float64),
        extent=(float(left), float(right), float(bottom), float(top)),
        strict_limit=limit,
        valid_count=int(np.count_nonzero(valid)),
        overlap_count=int(np.count_nonzero(strict)),
        footprint_segments_lonlat=segments,
    )


def setup_matplotlib() -> Any:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Liberation Sans", "Liberate Sans", "Arial", "DejaVu Sans"],
        "font.cursive": ["Liberation Sans"],
        "mathtext.fontset": "custom",
        "mathtext.rm": "Liberation Sans",
        "mathtext.it": "Liberation Sans:italic",
        "mathtext.bf": "Liberation Sans:bold",
        "mathtext.cal": "Liberation Sans",
        "mathtext.sf": "Liberation Sans",
        "mathtext.tt": "Liberation Sans",
        "font.size": 7.0,
        "axes.titlesize": 8.0,
        "axes.labelsize": 7.5,
        "xtick.labelsize": 6.8,
        "ytick.labelsize": 6.8,
        "legend.fontsize": 6.8,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.55,
        "ytick.major.width": 0.55,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
    })
    depth_cmap = LinearSegmentedColormap.from_list(
        "aqaba_depth",
        [
            "#f4f0e5",
            "#d7e8be",
            "#8bd18c",
            "#2fbf9f",
            "#2c9fd6",
            "#2b5fb8",
            "#3c2f7f",
            "#21152f",
        ],
    )
    speed_cmap = LinearSegmentedColormap.from_list(
        "aqaba_speed",
        ["#fee8c8", "#fdbb84", "#e34a33", "#7f0000"],
    )
    return plt, depth_cmap, speed_cmap


def add_panel_label(ax: Any, label: str) -> None:
    ax.text(
        -0.055,
        1.025,
        label,
        transform=ax.transAxes,
        fontsize=10,
        fontweight="bold",
        va="bottom",
        ha="left",
    )


def add_scale_bar(ax: Any, length_m: float = 20000.0) -> None:
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    x = x0 + 0.08 * (x1 - x0)
    y = y0 + 0.055 * (y1 - y0)
    ax.plot([x, x + length_m], [y, y], color="black", lw=1.0, solid_capstyle="butt")
    ax.plot([x, x], [y - 900, y + 900], color="black", lw=0.8)
    ax.plot([x + length_m, x + length_m], [y - 900, y + 900], color="black", lw=0.8)
    ax.text(x + length_m / 2, y + 1800, f"{int(length_m / 1000)} km", ha="center", va="bottom", fontsize=6.5)


def add_north_arrow(ax: Any) -> None:
    ax.annotate(
        "N",
        xy=(0.93, 0.92),
        xytext=(0.93, 0.82),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="center",
        fontsize=7,
        arrowprops={"arrowstyle": "-|>", "lw": 0.8, "color": "black"},
    )


def configure_map_extent(ax: Any, shorelines: dict[str, np.ndarray], pad_x: float = 4500.0, pad_y: float = 4500.0) -> None:
    all_points = np.vstack(list(shorelines.values()))
    ax.set_xlim(float(np.min(all_points[:, 0]) - pad_x), float(np.max(all_points[:, 0]) + pad_x))
    ax.set_ylim(float(np.min(all_points[:, 1]) - pad_y), float(np.max(all_points[:, 1]) + pad_y))


def panel_a_utm_extent(shorelines: dict[str, np.ndarray]) -> tuple[float, float, float, float]:
    north_y = float(lonlat_to_utm37([PANEL_A_NORTH_LONLAT])[0, 1])
    clipped = []
    for line in shorelines.values():
        keep = line[line[:, 1] <= north_y]
        if keep.size:
            clipped.append(keep)
    if not clipped:
        clipped = list(shorelines.values())
    points = np.vstack(clipped)
    return (
        float(np.min(points[:, 0]) - PANEL_A_PAD_X_M),
        float(np.max(points[:, 0]) + PANEL_A_PAD_X_M),
        float(np.min(points[:, 1]) - PANEL_A_PAD_SOUTH_M),
        north_y,
    )


def utm_extent_to_lonlat_bounds(extent: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, x1, y0, y1 = extent
    xs = np.concatenate((
        np.linspace(x0, x1, 17),
        np.linspace(x0, x1, 17),
        np.full(17, x0),
        np.full(17, x1),
    ))
    ys = np.concatenate((
        np.full(17, y0),
        np.full(17, y1),
        np.linspace(y0, y1, 17),
        np.linspace(y0, y1, 17),
    ))
    lonlat = utm37_to_lonlat(zip(xs, ys))
    return (
        float(np.min(lonlat[:, 0])),
        float(np.max(lonlat[:, 0])),
        float(np.min(lonlat[:, 1])),
        float(np.max(lonlat[:, 1])),
    )


def degree_ticks(start: float, stop: float, step: float = 0.2) -> np.ndarray:
    first = math.ceil(start / step) * step
    last = math.floor(stop / step) * step
    if first > last + 1e-9:
        return np.asarray([], dtype=np.float64)
    count = int(round((last - first) / step)) + 1
    return first + np.arange(count, dtype=np.float64) * step


def format_lon(value: float) -> str:
    return f"{value:.1f}°E"


def format_lat(value: float) -> str:
    return f"{value:.1f}°N"


def set_lonlat_frame(ax: Any, extent: tuple[float, float, float, float]) -> None:
    x0, x1, y0, y1 = extent
    lon0, lon1, lat0, lat1 = utm_extent_to_lonlat_bounds(extent)
    lon_ticks = degree_ticks(lon0, lon1)
    lat_ticks = degree_ticks(lat0, lat1)
    mid_lon = 0.5 * (lon0 + lon1)
    mid_lat = 0.5 * (lat0 + lat1)

    if lon_ticks.size:
        xt = lonlat_to_utm37([(float(lon), mid_lat) for lon in lon_ticks])[:, 0]
        keep = (xt >= x0) & (xt <= x1)
        ax.set_xticks(xt[keep])
        ax.set_xticklabels([format_lon(float(lon)) for lon in lon_ticks[keep]])
    else:
        ax.set_xticks([])

    if lat_ticks.size:
        yt = lonlat_to_utm37([(mid_lon, float(lat)) for lat in lat_ticks])[:, 1]
        keep = (yt >= y0) & (yt <= y1)
        ax.set_yticks(yt[keep])
        ax.set_yticklabels([format_lat(float(lat)) for lat in lat_ticks[keep]])
    else:
        ax.set_yticks([])

    ax.tick_params(axis="both", which="major", labelsize=6.2, length=2.4, width=0.55, pad=1.5)
    ax.tick_params(axis="x", top=True, labeltop=False)
    ax.tick_params(axis="y", right=True, labelright=False)


def draw_panel_a(
    fig: Any,
    ax: Any,
    gmrt_panel: UtmRasterPanel,
    shorelines: dict[str, np.ndarray],
    corridor: dict[str, np.ndarray],
    hotspots: list[dict[str, Any]],
    ribot_segments_utm: list[np.ndarray],
    selected_transects: list[HotspotTransect],
    extent: tuple[float, float, float, float],
    depth_cmap: Any,
    speed_cmap: Any,
) -> None:
    from matplotlib.colors import Normalize, PowerNorm
    from matplotlib.lines import Line2D
    import matplotlib.patheffects as pe

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    im = ax.imshow(
        np.ma.masked_invalid(gmrt_panel.depth),
        origin="lower",
        extent=gmrt_panel.extent,
        cmap=depth_cmap,
        norm=PowerNorm(gamma=0.82, vmin=0.0, vmax=1500.0),
        interpolation="nearest",
        alpha=0.96,
        zorder=0,
    )
    ax.set_facecolor("#f4f4f1")
    contours = ax.contour(
        gmrt_panel.x,
        gmrt_panel.y,
        gmrt_panel.z,
        levels=[-100, -50, -20, -10],
        colors=CONTOUR_COLOR,
        linewidths=0.45,
        alpha=0.72,
        linestyles="solid",
        zorder=2,
    )
    ax.clabel(contours, fmt=lambda value: f"{int(value)} m", fontsize=5.8, inline=True, inline_spacing=3)

    for side, line in shorelines.items():
        ax.plot(line[:, 0], line[:, 1], color=SHORE_COLOR, lw=0.75, zorder=3)
        ax.plot(corridor[side][:, 0], corridor[side][:, 1], color=CORRIDOR_COLOR, lw=0.7, ls=(0, (3.0, 2.0)), zorder=3)
    for segment in ribot_segments_utm:
        ax.plot(segment[:, 0], segment[:, 1], color=FOOTPRINT_COLOR, lw=0.85, alpha=0.94, zorder=4)

    line_effect = [pe.withStroke(linewidth=3.2, foreground="white")]
    text_effect = [pe.withStroke(linewidth=2.0, foreground="white")]
    for label_idx, transect in enumerate(selected_transects, start=1):
        xs = [transect.shore_point[0], transect.end_point[0]]
        ys = [transect.shore_point[1], transect.end_point[1]]
        ax.plot(
            xs,
            ys,
            color=CONTROL_LINE_COLOR,
            lw=2.0,
            marker="o",
            markersize=3.2,
            markerfacecolor=CONTROL_LINE_COLOR,
            markeredgecolor="white",
            markeredgewidth=0.45,
            solid_capstyle="round",
            zorder=9,
            path_effects=line_effect,
        )
        label_xy = transect.shore_point + 0.62 * (transect.end_point - transect.shore_point)
        ax.text(
            label_xy[0],
            label_xy[1],
            f"C{label_idx}",
            fontsize=7.0,
            fontweight="bold",
            color=CONTROL_LINE_COLOR,
            ha="center",
            va="center",
            zorder=10,
            path_effects=text_effect,
        )

    if hotspots:
        speeds = np.asarray([h["speed"] for h in hotspots], dtype=float)
        rec = np.asarray([h["recurrence"] for h in hotspots], dtype=float)
        vmax = float(max(8.0, np.nanpercentile(speeds, 95)))
        norm = Normalize(vmin=0.0, vmax=vmax)
        sizes = 14.0 + 7.0 * np.sqrt(rec)
        sc = ax.scatter(
            [h["x"] for h in hotspots],
            [h["y"] for h in hotspots],
            c=speeds,
            s=sizes,
            cmap=speed_cmap,
            norm=norm,
            edgecolor="white",
            linewidth=0.35,
            alpha=0.92,
            zorder=5,
        )
        cax = ax.inset_axes([0.055, 0.875, 0.28, 0.022])
        cbar = fig.colorbar(sc, cax=cax, orientation="horizontal")
        cbar.set_label("Flow speed (m s$^{-1}$)", fontsize=6.2, labelpad=1.0)
        cbar.ax.tick_params(labelsize=5.8, length=2)
        size_handles = []
        for value in (2, 5, 10):
            size_handles.append(ax.scatter([], [], s=14.0 + 7.0 * math.sqrt(value), facecolor="#e34a33", edgecolor="white", linewidth=0.35, label=f"{value} frames"))
        leg1 = ax.legend(handles=size_handles, title="Recurrence", loc="lower right", frameon=False, borderpad=0.2, handletextpad=0.8, title_fontsize=6.8)
        ax.add_artist(leg1)

    depth_cax = ax.inset_axes([0.055, 0.55, 0.022, 0.20])
    depth_cbar = fig.colorbar(im, cax=depth_cax, orientation="vertical")
    depth_cbar.set_ticks([0, 500, 1000, 1500])
    depth_cbar.set_label("Depth (m)", fontsize=6.2, labelpad=1.5)
    depth_cbar.ax.tick_params(labelsize=5.8, length=2)

    source_handles = [
        Line2D([0], [0], color=SHORE_COLOR, lw=0.8, label="Shoreline"),
        Line2D([0], [0], color=CORRIDOR_COLOR, lw=0.8, ls=(0, (3, 2)), label="1-km seaward corridor"),
        Line2D([0], [0], color=FOOTPRINT_COLOR, lw=1.0, label="True Ribot footprint"),
        Line2D([0], [0], color=CONTROL_LINE_COLOR, lw=2.0, marker="o", markersize=3.0, label="Selected control lines"),
    ]
    ax.legend(handles=source_handles, loc="upper right", frameon=False, handlelength=2.0, borderpad=0.2)

    labels = {
        "Aqaba": (35.0078, 29.5320),
        "Eilat": (34.9482, 29.5577),
        "Haql": (34.9490, 29.2850),
        "Nuweiba": (34.6634, 29.0350),
    }
    pts = lonlat_to_utm37(labels.values())
    label_offsets = {
        "Nuweiba": (900.0, -6200.0),
    }
    for (name, _), (x, y) in zip(labels.items(), pts):
        if x0 <= x <= x1 and y0 <= y <= y1:
            dx, dy = label_offsets.get(name, (850.0, 850.0))
            ax.text(x + dx, y + dy, name, fontsize=6.5, color="#262626", zorder=6)
            ax.plot(x, y, marker=".", color="#262626", ms=2.2, zorder=6)

    add_scale_bar(ax, 20000.0)
    add_north_arrow(ax)
    ax.set_aspect("equal", adjustable="box")
    set_lonlat_frame(ax, extent)
    ax.set_title("GMRT bathymetry and recurrent hotspots", loc="left", pad=5)
    add_panel_label(ax, "A")


def draw_panel_b(ax: Any, ratios: list[dict[str, Any]]) -> None:
    y = np.arange(len(ratios), dtype=float)
    values = np.asarray([row["ratio"] for row in ratios], dtype=float)
    ax.axvspan(0.0, 1.0, color="#f4f4f4", zorder=0)
    ax.axhspan(-0.5, 2.5, color="#f7f7f7", zorder=0)
    ax.axhspan(2.5, 5.5, color="#ffffff", zorder=0)
    ax.axvline(1.0, color="0.35", lw=0.8, ls=(0, (2, 2)), zorder=1)
    for yi, value, row in zip(y, values, ratios):
        color = "#7f7f7f" if row["source_group"] == "western-source" else "#252525"
        ax.plot([1.0, value], [yi, yi], color="#bdbdbd", lw=1.0, zorder=2)
        ax.scatter(value, yi, s=32, color=color, edgecolor="white", linewidth=0.5, zorder=3)
        ax.text(value + 0.10, yi, f"{value:.1f}", va="center", ha="left", fontsize=6.7)
    ax.set_yticks(y)
    ax.set_yticklabels([row["label"] for row in ratios])
    ax.invert_yaxis()
    ax.set_xlim(0.6, max(5.4, float(np.nanmax(values) + 0.55)))
    ax.set_xlabel("East/West median framewise top-10 speed ratio")
    ax.set_title("East/West asymmetry across six scenarios", loc="left", pad=5)
    ax.text(0.98, 0.20, "Western-source", transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=6.3, color="0.35")
    ax.text(0.98, 3.75, "Eastern-source", transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=6.3, color="0.35")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color="0.88", lw=0.45)
    add_panel_label(ax, "B")


def draw_panel_a_multibeam(
    fig: Any,
    ax: Any,
    ribot_panel: UtmRasterPanel,
    ribot_segments_utm: list[np.ndarray],
    extent: tuple[float, float, float, float],
    depth_cmap: Any,
) -> None:
    from matplotlib.colors import PowerNorm

    ax.set_facecolor("white")
    im = ax.imshow(
        np.ma.masked_invalid(ribot_panel.depth),
        origin="lower",
        extent=ribot_panel.extent,
        cmap=depth_cmap,
        norm=PowerNorm(gamma=0.82, vmin=0.0, vmax=1500.0),
        interpolation="nearest",
        zorder=1,
    )
    for segment in ribot_segments_utm:
        ax.plot(segment[:, 0], segment[:, 1], color=FOOTPRINT_COLOR, lw=0.85, alpha=0.95, zorder=2)
    cax = ax.inset_axes([0.09, 0.06, 0.82, 0.026])
    cbar = fig.colorbar(im, cax=cax, orientation="horizontal")
    cbar.set_ticks([0, 500, 1000, 1500])
    cbar.set_label("Depth (m)", fontsize=5.8, labelpad=1.0)
    cbar.ax.tick_params(labelsize=5.5, length=2)
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Ribot multibeam bathymetry", loc="left", pad=5)
    ax.text(
        0.05,
        0.94,
        "True Ribot footprint",
        transform=ax.transAxes,
        fontsize=5.9,
        color=FOOTPRINT_COLOR,
        ha="left",
        va="top",
    )
    for spine in ax.spines.values():
        spine.set_linewidth(0.55)
        spine.set_color("0.35")


def draw_panel_a_recurrence_transects(
    plt: Any,
    transects: list[HotspotTransect],
    output_path: Path,
    length_m: float,
) -> None:
    from matplotlib.lines import Line2D

    if not transects:
        return

    cols = min(3, len(transects))
    rows = int(math.ceil(len(transects) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.75, rows * 2.75), squeeze=False)

    all_depths = np.concatenate([
        np.concatenate((transect.gmrt_depth[np.isfinite(transect.gmrt_depth)], transect.ribot_depth[np.isfinite(transect.ribot_depth)]))
        for transect in transects
    ])
    max_depth = float(np.nanmax(all_depths)) if all_depths.size else 100.0
    y_max = max(100.0, math.ceil(max_depth / 100.0) * 100.0)
    x_max_km = length_m / 1000.0

    gmrt_style = {"color": "#4d4d4d", "lw": 1.05, "ls": (0, (3.2, 2.0)), "label": "GMRT"}
    ribot_style = {"color": "#0a4f9c", "lw": 1.25, "ls": "-", "label": "Ribot multibeam"}
    legend_handles = [
        Line2D([0], [0], **gmrt_style),
        Line2D([0], [0], **ribot_style),
        Line2D([0], [0], color="#d95f02", lw=0.8, ls=(0, (1.2, 1.8)), label="hotspot projection"),
    ]

    for plot_idx, (ax, transect) in enumerate(zip(axes.flat, transects), start=1):
        x_km = transect.distance_m / 1000.0
        ax.plot(x_km, transect.gmrt_depth, **gmrt_style)
        has_ribot = bool(np.any(np.isfinite(transect.ribot_depth)))
        if has_ribot:
            ax.plot(x_km, transect.ribot_depth, **ribot_style)
        else:
            ax.text(
                0.04,
                0.92,
                "Ribot: no coverage",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=4.9,
                color="#0a4f9c",
            )
        if 0.0 <= transect.hotspot_distance_m <= length_m:
            ax.axvline(
                transect.hotspot_distance_m / 1000.0,
                color="#d95f02",
                lw=0.8,
                ls=(0, (1.2, 1.8)),
                label="hotspot projection",
            )
        side_label = "East" if transect.side == "east" else "West"
        ax.set_title(
            f"C{plot_idx} {side_label}; R={transect.recurrence}; U={transect.speed:.1f}",
            loc="left",
            fontsize=7.0,
            pad=2.0,
        )
        ax.set_xlim(0.0, x_max_km)
        ax.set_ylim(y_max, 0.0)
        ax.set_box_aspect(1)
        ax.set_xlabel("Distance offshore (km)", fontsize=5.7, labelpad=1.0)
        ax.set_ylabel("Depth (m)", fontsize=5.7, labelpad=1.0)
        ax.tick_params(axis="both", labelsize=5.2, length=2.0, width=0.45, pad=1.0)
        ax.grid(True, color="0.88", lw=0.45)
        ax.legend(handles=legend_handles, loc="lower right", fontsize=4.5, frameon=False, handlelength=1.8, borderpad=0.1)
        for spine in ax.spines.values():
            spine.set_linewidth(0.55)

    for ax in axes.flat[len(transects):]:
        ax.axis("off")

    fig.suptitle(
        "Selected Panel A offshore control-line bathymetry",
        x=0.01,
        y=0.997,
        ha="left",
        va="top",
        fontsize=10.0,
        fontweight="bold",
    )
    fig.subplots_adjust(left=0.06, right=0.985, bottom=0.14, top=0.88, wspace=0.30, hspace=0.35)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)


def draw_panel_c(
    ax: Any,
    distances: np.ndarray,
    summaries: dict[str, dict[str, np.ndarray]],
    isobaths: dict[str, dict[str, tuple[float, float, float]]],
) -> None:
    for side, color, label in (("east", EAST_COLOR, "Eastern Saudi margin"), ("west", WEST_COLOR, "Western Sinai margin")):
        x = distances / 1000.0
        med = summaries[side]["median"]
        q25 = summaries[side]["q25"]
        q75 = summaries[side]["q75"]
        ax.fill_between(x, q25, q75, color=color, alpha=0.16, linewidth=0)
        ax.plot(x, med, color=color, lw=1.55)
        idx = int(np.searchsorted(x, 1.08))
        if idx < med.size and math.isfinite(float(med[idx])):
            offset = -14.0 if side == "east" else 16.0
            ax.text(1.10, float(med[idx]) + offset, label, color=color, fontsize=6.8, ha="left", va="center")
    ax.set_xlim(0.0, 2.0)
    ymax = max(float(np.nanpercentile(summaries["east"]["q75"], 92)), float(np.nanpercentile(summaries["west"]["q75"], 92)), 120.0)
    ax.set_ylim(0.0, min(850.0, ymax * 1.08))
    ax.invert_yaxis()
    ax.set_xlabel("Distance offshore from shoreline (km)")
    ax.set_ylabel("Water depth (m)")
    ax.set_title("Contrasting cross-shore bathymetric profiles", loc="left", pad=5)
    ax.grid(color="0.9", lw=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.text(0.055, 0.16, "Deep water lies closer\nto the eastern shoreline", transform=ax.transAxes, fontsize=6.7, color=EAST_COLOR)

    inset = ax.inset_axes([0.58, 0.12, 0.34, 0.31])
    inset.set_facecolor("white")
    metrics = [("distance_to_20m_isobath", "20 m"), ("distance_to_50m_isobath", "50 m")]
    ypos = np.arange(len(metrics), dtype=float)
    height = 0.28
    for offset, side, color in ((-height / 2, "east", EAST_COLOR), (height / 2, "west", WEST_COLOR)):
        vals = [isobaths[side][field][0] / 1000.0 for field, _ in metrics]
        inset.barh(ypos + offset, vals, height=height, color=color, alpha=0.86)
    inset.set_yticks(ypos)
    inset.set_yticklabels([label for _, label in metrics], fontsize=5.8)
    inset.invert_yaxis()
    inset.set_xlabel("Isobath distance (km)", fontsize=5.8, labelpad=1)
    inset.tick_params(labelsize=5.6, length=2)
    inset.spines["top"].set_visible(False)
    inset.spines["right"].set_visible(False)
    inset.text(0.96, 0.30, "East", color=EAST_COLOR, transform=inset.transAxes, fontsize=5.7, ha="right")
    inset.text(0.96, 0.08, "West", color=WEST_COLOR, transform=inset.transAxes, fontsize=5.7, ha="right")
    add_panel_label(ax, "C")


def git_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True)
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def write_manifest(path: Path, args: argparse.Namespace, hotspot_count: int, station_count: dict[str, int], git_hash: str) -> None:
    lines = [
        "Receiver-side bathymetry asymmetry manuscript figure manifest",
        f"run_time_utc = {datetime.now(timezone.utc).isoformat()}",
        f"git_commit = {git_hash}",
        "",
        "Input files:",
        f"- shoreline velocity summary: {args.velocity_summary}",
        f"- shoreline velocity hotspots: {args.hotspots}",
        f"- shoreline geometry: {args.shorelines}",
        f"- model-effective bathymetry: {args.topography}",
        f"- native bathymetric metrics: {args.native_metrics}",
        f"- raw DEM inventory: {args.raw_dem_inventory}",
        f"- raw-to-model mapping: {args.raw_to_model_mapping}",
        f"- Ribot on A2 grid: {args.ribot_on_a2}",
        f"- GMRT on A2 grid: {args.gmrt_on_a2}",
        "",
        "Time window and corridor:",
        "- requested_time_min_s = 900; selected frames are the existing viewer compact-v2 frames at t >= 900 s.",
        "- corridor = shoreline-following 1000 m seaward / 500 m landward; Panel A displays only the 1-km seaward boundary.",
        "- Panel A is split into a GMRT-only hotspot map and a Ribot multibeam panel on the same UTM extent.",
        "",
        "Hotspot filtering and recurrence encoding:",
        "- source table: analysis/results_shoreline_velocity/hotspots.csv",
        "- retained rows: zone=seaward, requested_time_min_s=900, seaward_distance_m=1000, landward_distance_m=500.",
        "- spatial aggregation: side-specific 100 m grid cells.",
        "- recurrent cluster retained when case_count >= 2 or summed displayed_frame_count >= 2.",
        "- marker color = median max_displayed_speed_mps within the cluster.",
        "- marker size = summed displayed_frame_count within the cluster.",
        f"- recurrent hotspot clusters drawn = {hotspot_count}.",
        "- Panel A left bathymetry = GMRT_on_A2_grid_v3 only; the true Ribot footprint is drawn only as an outline.",
        "- Panel A right bathymetry = Ribot_on_A2_grid_v3 within the same UTM extent, using the same bathymetry color scale as Panel A left.",
        "",
        "Cross-shore profile aggregation:",
        "- profiles sampled directly from topo-bathy.tt3 using corrected south-to-north shorelines.",
        "- shoreline stations every 500 m; seaward normals selected from model-effective bathymetry.",
        "- profiles sampled from 0 to 2 km offshore every 50 m.",
        "- Panel C line = side-specific median depth; ribbon = interquartile range.",
        f"- station counts = {station_count}.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_figure(args: argparse.Namespace) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    plt, depth_cmap, speed_cmap = setup_matplotlib()

    grid = read_tt3(args.topography)
    shorelines = load_shorelines(args.shorelines)
    corridor = corridor_boundaries(grid, shorelines, 1000.0)
    hotspot_clusters = aggregate_hotspots(read_csv(args.hotspots), 100.0)
    ratios = scenario_ratios(read_csv(args.velocity_summary))
    distances, profiles, summaries = cross_shore_profiles(grid, shorelines, 500.0, 2000.0, 50.0)
    isobaths = native_isobath_summary(read_csv(args.native_metrics))
    multibeam_panel = read_multibeam_panel(args.ribot_on_a2, args.gmrt_on_a2)
    ribot_segments_utm = segments_lonlat_to_utm37(multibeam_panel.footprint_segments_lonlat)
    panel_a_extent = panel_a_utm_extent(shorelines)
    gmrt_panel = read_raster_depth_on_utm_grid(args.gmrt_on_a2, panel_a_extent)
    ribot_panel = read_raster_depth_on_utm_grid(args.ribot_on_a2, panel_a_extent)
    hotspot_transects = build_hotspot_transects(
        hotspot_clusters,
        shorelines,
        args.gmrt_on_a2,
        args.ribot_on_a2,
        args.transect_length_m,
        args.transect_step_m,
    )
    selected_transects = select_panel_a_transects(hotspot_transects, 3)

    fig = plt.figure(figsize=(7.75, 5.1), constrained_layout=False)
    gs = fig.add_gridspec(
        2,
        2,
        width_ratios=[1.95, 1.0],
        height_ratios=[1.0, 1.0],
        left=0.055,
        right=0.985,
        bottom=0.09,
        top=0.955,
        wspace=0.20,
        hspace=0.34,
    )
    gs_a = gs[:, 0].subgridspec(1, 2, width_ratios=[1.0, 1.0], wspace=0.055)
    ax_a = fig.add_subplot(gs_a[0, 0])
    ax_a_mb = fig.add_subplot(gs_a[0, 1])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 1])

    draw_panel_a(fig, ax_a, gmrt_panel, shorelines, corridor, hotspot_clusters, ribot_segments_utm, selected_transects, panel_a_extent, depth_cmap, speed_cmap)
    draw_panel_a_multibeam(fig, ax_a_mb, ribot_panel, ribot_segments_utm, panel_a_extent, depth_cmap)
    draw_panel_b(ax_b, ratios)
    draw_panel_c(ax_c, distances, summaries, isobaths)

    args.pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.pdf)
    plt.close(fig)

    draw_panel_a_recurrence_transects(
        plt,
        selected_transects,
        args.panel_a_transects_pdf,
        args.transect_length_m,
    )


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Make the receiver-side bathymetry asymmetry manuscript figure.")
    parser.add_argument("--velocity-summary", type=Path, default=repo_root / "analysis/results_shoreline_velocity/summary.csv")
    parser.add_argument("--hotspots", type=Path, default=repo_root / "analysis/results_shoreline_velocity/hotspots.csv")
    parser.add_argument("--shorelines", type=Path, default=repo_root / "analysis/aqaba_shorelines.geojson")
    parser.add_argument("--topography", type=Path, default=Path("/home/daij/Desktop/compile_all/aqaba_scenarios_lsa/TOPO/topo-bathy.tt3"))
    parser.add_argument("--native-metrics", type=Path, default=repo_root / "analysis/results_bathymetric_controls/bathymetric_metrics_native.csv")
    parser.add_argument("--raw-dem-inventory", type=Path, default=repo_root / "analysis/raw_dem_source_inventory.csv")
    parser.add_argument("--raw-to-model-mapping", type=Path, default=repo_root / "analysis/raw_dem_to_model_topography_mapping.csv")
    parser.add_argument("--ribot-on-a2", type=Path, default=Path("/home/daij/Desktop/general/DEM/process/RIBOT_on_A2_grid_v3.tif"))
    parser.add_argument("--gmrt-on-a2", type=Path, default=Path("/home/daij/Desktop/general/DEM/process/GMRT_on_A2_grid_v3.tif"))
    parser.add_argument("--pdf", type=Path, default=repo_root / "analysis/fig_receiver_side_bathymetry_asymmetry.pdf")
    parser.add_argument("--panel-a-transects-pdf", type=Path, default=repo_root / "analysis/fig_receiver_side_bathymetry_panelA_recurrence_transects.pdf")
    parser.add_argument("--transect-length-m", type=float, default=1000.0)
    parser.add_argument("--transect-step-m", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    make_figure(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
