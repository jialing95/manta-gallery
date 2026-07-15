#!/usr/bin/env python3
"""Analyze source-TOPO coastal bathymetric controls for velocity hotspots."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


DEPTH_SAMPLE_M = (100, 250, 500, 1000, 2000)
ISOBATHS_M = (5, 10, 20, 50, 100)
SLOPE_BANDS_M = ((0, 250), (250, 500), (500, 1000), (1000, 2000))
MAIN_CORRIDOR = (1000.0, 500.0)
RAW_SOURCE_LABELS = {
    0: {
        "raw_source_id": "nodata",
        "raw_source_class": "nodata",
        "raw_source_multibeam": "unknown",
        "raw_source_native_resolution_m": float("nan"),
        "raw_source_confidence": "unknown",
        "source_overlap_count": 0,
    },
    1: {
        "raw_source_id": "copernicus_a2_land_core",
        "raw_source_class": "land/a2 core",
        "raw_source_multibeam": "false",
        "raw_source_native_resolution_m": 30.0,
        "raw_source_confidence": "high",
        "source_overlap_count": 1,
    },
    2: {
        "raw_source_id": "ribot_gmrt_shore_blend",
        "raw_source_class": "blend to Ribot",
        "raw_source_multibeam": "partial",
        "raw_source_native_resolution_m": 30.0,
        "raw_source_confidence": "mixed_blend",
        "source_overlap_count": 2,
    },
    3: {
        "raw_source_id": "gmrt_shore_blend",
        "raw_source_class": "blend to GMRT",
        "raw_source_multibeam": "unknown",
        "raw_source_native_resolution_m": 54.0,
        "raw_source_confidence": "mixed_blend",
        "source_overlap_count": 2,
    },
    4: {
        "raw_source_id": "ribot_multibeam_core",
        "raw_source_class": "Ribot core",
        "raw_source_multibeam": "true",
        "raw_source_native_resolution_m": 30.0,
        "raw_source_confidence": "high",
        "source_overlap_count": 1,
    },
    5: {
        "raw_source_id": "gmrt_core",
        "raw_source_class": "GMRT core",
        "raw_source_multibeam": "unknown",
        "raw_source_native_resolution_m": 54.0,
        "raw_source_confidence": "high",
        "source_overlap_count": 1,
    },
}


@dataclass
class SourceTopography:
    grid: np.ndarray
    ncols: int
    nrows: int
    xllcenter: float
    yllcenter: float
    dx: float
    dy: float
    source_topo_id: str
    native_dx_m: float
    native_dy_m: float
    effective_resolution_m: float
    sea_level: float


@dataclass
class RawSourceMap:
    path: Path
    array: np.ndarray
    geotransform: tuple[float, float, float, float, float, float]
    inv_geotransform: tuple[float, float, float, float, float, float]
    transformer: Any
    pixel_size_m: float
    available: bool = True


class RasterioPointTransformer:
    def __init__(self, source_crs: Any, target_crs: Any):
        self.source_crs = source_crs
        self.target_crs = target_crs

    def TransformPoint(self, x: float, y: float) -> tuple[float, float, float]:
        from rasterio.warp import transform
        xs, ys = transform(self.source_crs, self.target_crs, [float(x)], [float(y)])
        return float(xs[0]), float(ys[0]), 0.0


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_source_topography(path: Path) -> SourceTopography:
    payload = load_json(path)
    meta = payload["grid"]
    grid_path = Path(str(meta["elevation_npy"]))
    if not grid_path.is_absolute() and not grid_path.exists():
        grid_path = path.parent / grid_path
    return SourceTopography(
        grid=np.load(grid_path, mmap_mode="r"),
        ncols=int(meta["ncols"]),
        nrows=int(meta["nrows"]),
        xllcenter=float(meta["xllcenter"]),
        yllcenter=float(meta["yllcenter"]),
        dx=float(meta["dx"]),
        dy=float(meta["dy"]),
        source_topo_id=str(meta.get("source_topo_id", "topo-bathy.tt3")),
        native_dx_m=float(meta.get("native_dx_m", meta["dx"])),
        native_dy_m=float(meta.get("native_dy_m", meta["dy"])),
        effective_resolution_m=float(meta.get("effective_resolution_m", max(float(meta["dx"]), float(meta["dy"])))),
        sea_level=float(payload.get("sea_level", 0.0)),
    )


def invert_geotransform(gt: tuple[float, float, float, float, float, float]) -> tuple[float, float, float, float, float, float]:
    c, a, b, f, d, e = gt
    det = a * e - b * d
    if det == 0.0:
        raise ValueError("Cannot invert degenerate geotransform")
    return (
        (-e * c + b * f) / det,
        e / det,
        -b / det,
        (d * c - a * f) / det,
        -d / det,
        a / det,
    )


def load_raw_source_map(provenance_path: Path) -> RawSourceMap | None:
    payload = load_json(provenance_path)
    class_path_text = str((payload.get("raw_source_class") or {}).get("path", ""))
    if not class_path_text:
        return None
    class_path = Path(class_path_text)
    if not class_path.exists():
        return None
    try:
        import rasterio
        with rasterio.open(class_path) as ds:
            arr = ds.read(1)
            affine = ds.transform
            gt = (
                float(affine.c),
                float(affine.a),
                float(affine.b),
                float(affine.f),
                float(affine.d),
                float(affine.e),
            )
            inv_gt = invert_geotransform(gt)
            transformer = RasterioPointTransformer("EPSG:32637", ds.crs)
            center_lat = gt[3] + 0.5 * arr.shape[0] * gt[5]
            px_m = abs(gt[1]) * 111320.0 * math.cos(math.radians(center_lat)) if abs(gt[1]) < 0.1 else abs(gt[1])
            py_m = abs(gt[5]) * 111320.0 if abs(gt[5]) < 0.1 else abs(gt[5])
        return RawSourceMap(
            path=class_path,
            array=np.asarray(arr),
            geotransform=gt,
            inv_geotransform=inv_gt,
            transformer=transformer,
            pixel_size_m=float(max(px_m, py_m)),
            available=True,
        )
    except Exception:
        pass
    try:
        from osgeo import gdal, osr
    except Exception:
        return None
    ds = gdal.Open(str(class_path))
    if ds is None:
        return None
    try:
        arr = ds.GetRasterBand(1).ReadAsArray()
    except Exception:
        return None
    gt = tuple(float(v) for v in ds.GetGeoTransform())
    inv = gdal.InvGeoTransform(gt)
    if isinstance(inv, tuple) and len(inv) == 2 and isinstance(inv[1], tuple):
        inv_gt = tuple(float(v) for v in inv[1])
    else:
        inv_gt = tuple(float(v) for v in inv)
    source_srs = osr.SpatialReference()
    source_srs.ImportFromEPSG(32637)
    target_srs = osr.SpatialReference()
    projection = ds.GetProjection()
    if projection:
        target_srs.ImportFromWkt(projection)
    else:
        target_srs.ImportFromEPSG(4326)
    source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transformer = osr.CoordinateTransformation(source_srs, target_srs)
    # source_class_v3 is geographic 1-arcsecond data. Approximate meters per
    # pixel is sufficient for boundary-distance QC.
    center_lat = gt[3] + 0.5 * arr.shape[0] * gt[5]
    px_m = abs(gt[1]) * 111320.0 * math.cos(math.radians(center_lat)) if abs(gt[1]) < 0.1 else abs(gt[1])
    py_m = abs(gt[5]) * 111320.0 if abs(gt[5]) < 0.1 else abs(gt[5])
    return RawSourceMap(
        path=class_path,
        array=np.asarray(arr),
        geotransform=gt,
        inv_geotransform=inv_gt,
        transformer=transformer,
        pixel_size_m=float(max(px_m, py_m)),
        available=True,
    )


def sample_source(source: SourceTopography, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    fx = (x - source.xllcenter) / source.dx
    fy = (y - source.yllcenter) / source.dy
    ix = np.floor(fx).astype(np.int64)
    iy = np.floor(fy).astype(np.int64)
    valid = (ix >= 0) & (iy >= 0) & (ix < source.ncols - 1) & (iy < source.nrows - 1)
    if not np.any(valid):
        return out
    i = ix[valid]
    j = iy[valid]
    tx = fx[valid] - i
    ty = fy[valid] - j
    z00 = np.asarray(source.grid[j, i], dtype=np.float64)
    z10 = np.asarray(source.grid[j, i + 1], dtype=np.float64)
    z01 = np.asarray(source.grid[j + 1, i], dtype=np.float64)
    z11 = np.asarray(source.grid[j + 1, i + 1], dtype=np.float64)
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


def raw_map_pixel(raw_map: RawSourceMap, x: float, y: float) -> tuple[int, int] | None:
    try:
        rx, ry, _ = raw_map.transformer.TransformPoint(float(x), float(y))
    except Exception:
        rx, ry = float(x), float(y)
    gt = raw_map.inv_geotransform
    px = gt[0] + gt[1] * rx + gt[2] * ry
    py = gt[3] + gt[4] * rx + gt[5] * ry
    ix = int(math.floor(px))
    iy = int(math.floor(py))
    if iy < 0 or ix < 0 or iy >= raw_map.array.shape[0] or ix >= raw_map.array.shape[1]:
        return None
    return ix, iy


def raw_source_info(raw_map: RawSourceMap | None, x: float, y: float, search_radius_m: float = 3000.0) -> dict[str, Any]:
    if raw_map is None:
        label = RAW_SOURCE_LABELS[0]
        return {
            "raw_source_class_value": 0,
            **label,
            "distance_to_raw_source_boundary_m": float("nan"),
            "distance_to_raw_source_boundary_censored": "unknown",
        }
    pixel = raw_map_pixel(raw_map, x, y)
    if pixel is None:
        label = RAW_SOURCE_LABELS[0]
        return {
            "raw_source_class_value": 0,
            **label,
            "distance_to_raw_source_boundary_m": float("nan"),
            "distance_to_raw_source_boundary_censored": "outside_source_class_raster",
        }
    ix, iy = pixel
    value = int(raw_map.array[iy, ix])
    label = RAW_SOURCE_LABELS.get(value, RAW_SOURCE_LABELS[0])
    radius_px = max(1, int(math.ceil(search_radius_m / max(raw_map.pixel_size_m, 1.0))))
    y0 = max(0, iy - radius_px)
    y1 = min(raw_map.array.shape[0], iy + radius_px + 1)
    x0 = max(0, ix - radius_px)
    x1 = min(raw_map.array.shape[1], ix + radius_px + 1)
    sub = raw_map.array[y0:y1, x0:x1]
    yy, xx = np.nonzero(sub != value)
    censored = "false"
    if yy.size == 0:
        distance = float(search_radius_m)
        censored = "true"
    else:
        dx = (xx + x0 - ix).astype(np.float64) * raw_map.pixel_size_m
        dy = (yy + y0 - iy).astype(np.float64) * raw_map.pixel_size_m
        distance = float(np.min(np.hypot(dx, dy)))
    return {
        "raw_source_class_value": value,
        **label,
        "distance_to_raw_source_boundary_m": distance,
        "distance_to_raw_source_boundary_censored": censored,
    }


def source_gradient(source: SourceTopography, x: float, y: float) -> np.ndarray:
    step_x = max(float(source.dx), 1.0)
    step_y = max(float(source.dy), 1.0)
    east_west = sample_source(source, np.asarray([x + step_x, x - step_x]), np.asarray([y, y]))
    north_south = sample_source(source, np.asarray([x, x]), np.asarray([y + step_y, y - step_y]))
    dzdx = (east_west[0] - east_west[1]) / (2.0 * step_x) if np.all(np.isfinite(east_west)) else float("nan")
    dzdy = (north_south[0] - north_south[1]) / (2.0 * step_y) if np.all(np.isfinite(north_south)) else float("nan")
    return np.asarray([dzdx, dzdy], dtype=np.float64)


def unit_or_nan(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if not math.isfinite(norm) or norm <= 0.0:
        return np.asarray([float("nan"), float("nan")], dtype=np.float64)
    return vec / norm


def unsigned_angle_deg(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    a = unit_or_nan(vec_a)
    b = unit_or_nan(vec_b)
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        return float("nan")
    return math.degrees(math.acos(float(np.clip(abs(np.dot(a, b)), 0.0, 1.0))))


def read_shorelines(path: Path) -> dict[str, np.ndarray]:
    data = load_json(path)
    lines: dict[str, np.ndarray] = {}
    for feature in data.get("features", []):
        side = str((feature.get("properties") or {}).get("side", "")).lower()
        if side in {"east", "west"}:
            line = np.asarray(feature["geometry"]["coordinates"], dtype=np.float64)
            if line.shape[0] >= 2 and line[0, 1] > line[-1, 1]:
                line = line[::-1].copy()
            lines[side] = line
    if set(lines) != {"east", "west"}:
        raise ValueError(f"{path}: expected east and west shoreline features")
    return lines


def arclength(line: np.ndarray) -> np.ndarray:
    d = np.hypot(np.diff(line[:, 0]), np.diff(line[:, 1]))
    return np.concatenate(([0.0], np.cumsum(d)))


def resample_line(line: np.ndarray, spacing: float) -> tuple[np.ndarray, np.ndarray]:
    s = arclength(line)
    targets = np.arange(0.0, s[-1] + 1e-9, spacing)
    if targets[-1] < s[-1]:
        targets = np.append(targets, s[-1])
    pts = np.column_stack((np.interp(targets, s, line[:, 0]), np.interp(targets, s, line[:, 1])))
    return targets, pts


def station_tangents(points: np.ndarray) -> np.ndarray:
    tangents = np.zeros_like(points)
    for i in range(points.shape[0]):
        if i == 0:
            vec = points[1] - points[0]
        elif i == points.shape[0] - 1:
            vec = points[-1] - points[-2]
        else:
            vec = points[i + 1] - points[i - 1]
        norm = float(np.linalg.norm(vec))
        tangents[i] = vec / norm if norm > 0.0 else np.asarray([1.0, 0.0])
    return tangents


def curvature(points: np.ndarray, spacing: float) -> np.ndarray:
    tangents = station_tangents(points)
    angle = np.unwrap(np.arctan2(tangents[:, 1], tangents[:, 0]))
    if angle.size < 3:
        return np.zeros(angle.shape)
    return np.gradient(angle, spacing)


def choose_seaward_normals(source: SourceTopography, points: np.ndarray, tangents: np.ndarray, test_distance: float) -> np.ndarray:
    normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
    test = points + normals * test_distance
    elev = sample_source(source, test[:, 0], test[:, 1])
    flip = ~np.isfinite(elev) | (elev >= source.sea_level)
    normals[flip] *= -1.0
    test = points + normals * test_distance
    elev = sample_source(source, test[:, 0], test[:, 1])
    still_land = np.isfinite(elev) & (elev >= source.sea_level)
    normals[still_land] *= -1.0
    return normals


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = rows[0].keys() if rows else ()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fields})


def csv_value(value: Any) -> Any:
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)):
            return "nan"
        if math.isinf(float(value)):
            return "inf" if value > 0 else "-inf"
        return f"{float(value):.12g}"
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    return value


def interp_at_distance(distances: np.ndarray, values: np.ndarray, target: float) -> float:
    finite = np.isfinite(values)
    if np.count_nonzero(finite) < 2:
        return float("nan")
    return float(np.interp(target, distances[finite], values[finite]))


def distance_to_isobath(distances: np.ndarray, bed: np.ndarray, sea_level: float, depth: float) -> float:
    water_depth = sea_level - bed
    finite = np.isfinite(water_depth)
    if np.count_nonzero(finite) < 2:
        return float("nan")
    d = distances[finite]
    h = water_depth[finite]
    hit = np.flatnonzero(h >= depth)
    if hit.size == 0:
        return float("nan")
    idx = int(hit[0])
    if idx == 0:
        return float(d[0])
    h0, h1 = h[idx - 1], h[idx]
    if h1 == h0:
        return float(d[idx])
    t = (depth - h0) / (h1 - h0)
    return float(d[idx - 1] + t * (d[idx] - d[idx - 1]))


def slope_band(distances: np.ndarray, bed: np.ndarray, start: float, stop: float) -> float:
    z0 = interp_at_distance(distances, bed, start)
    z1 = interp_at_distance(distances, bed, stop)
    if not math.isfinite(z0) or not math.isfinite(z1) or stop == start:
        return float("nan")
    return abs((z1 - z0) / (stop - start))


def smooth_values(values: np.ndarray, spacing: float, scale: float) -> np.ndarray:
    window = max(1, int(round(scale / spacing)))
    if window <= 1:
        return values.copy()
    out = np.full(values.shape, np.nan, dtype=np.float64)
    half = window // 2
    for i in range(values.size):
        if i == 0:
            out[i] = values[i]
            continue
        lo = max(0, i - half)
        hi = min(values.size, i + half + 1)
        chunk = values[lo:hi]
        out[i] = float(np.nanmean(chunk)) if np.any(np.isfinite(chunk)) else float("nan")
    return out


def metric_row(
    station: dict[str, Any],
    distances: np.ndarray,
    bed: np.ndarray,
    sea_level: float,
    representation: str,
    scale_m: float,
    channel_anomaly: dict[float, float] | None = None,
) -> dict[str, Any]:
    row = {
        "side": station["side"],
        "station_id": station["station_id"],
        "alongshore_distance_m": station["alongshore_distance_m"],
        "normalized_along_gulf_coordinate": station.get("normalized_along_gulf_coordinate", float("nan")),
        "x_m": station["x_m"],
        "y_m": station["y_m"],
        "representation": representation,
        "common_scale_m": scale_m,
        "shoreline_curvature": station["shoreline_curvature"],
        "channel_axis_orientation_deg": math.degrees(math.atan2(float(station.get("shoreline_tangent_y", 0.0)), float(station.get("shoreline_tangent_x", 1.0)))),
        "source_topo_id": station["source_topo_id_at_shoreline"],
        "native_resolution_m": station["native_resolution_m_at_shoreline"],
        "effective_resolution_m": station["effective_resolution_m_at_shoreline"],
        "model_grid_spacing_m": station.get("model_grid_spacing_m", float("nan")),
        "raw_source_class_value": station.get("raw_source_class_value", 0),
        "raw_source_id": station.get("raw_source_id", "unknown"),
        "raw_source_class": station.get("raw_source_class", "unknown"),
        "raw_source_native_resolution_m": station.get("raw_source_native_resolution_m", float("nan")),
        "raw_source_multibeam": station.get("raw_source_multibeam", "unknown"),
        "raw_source_confidence": station.get("raw_source_confidence", "unknown"),
        "source_overlap_count": station.get("source_overlap_count", 0),
        "distance_to_raw_source_boundary_m": station.get("distance_to_raw_source_boundary_m", float("nan")),
        "distance_to_raw_source_boundary_censored": station.get("distance_to_raw_source_boundary_censored", "unknown"),
        "multibeam_coverage": station.get("raw_source_multibeam", "unknown"),
        "distance_to_resolution_boundary_m": station.get("distance_to_raw_source_boundary_m", float("nan")),
    }
    for depth_at in DEPTH_SAMPLE_M:
        z = interp_at_distance(distances, bed, float(depth_at))
        row[f"depth_at_{depth_at}m_offshore"] = sea_level - z if math.isfinite(z) else float("nan")
    iso_distances: dict[int, float] = {}
    for iso in ISOBATHS_M:
        d = distance_to_isobath(distances, bed, sea_level, float(iso))
        iso_distances[iso] = d
        row[f"distance_to_{iso}m_isobath"] = d
    for start, stop in SLOPE_BANDS_M:
        s = slope_band(distances, bed, float(start), float(stop))
        row[f"mean_abs_slope_{start}_{stop}m"] = s
        row[f"slope_angle_{start}_{stop}m_deg"] = math.degrees(math.atan(s)) if math.isfinite(s) else float("nan")
    for a, b in ((5, 10), (10, 20), (20, 50), (50, 100)):
        da = iso_distances[a]
        db = iso_distances[b]
        row[f"isobath_spacing_{a}_{b}m"] = db - da if math.isfinite(da) and math.isfinite(db) else float("nan")
    if channel_anomaly:
        for offset, anomaly in channel_anomaly.items():
            row[f"channel_anomaly_{int(offset)}m"] = anomaly
    return row


def build_stations(
    source: SourceTopography,
    raw_map: RawSourceMap | None,
    shorelines: dict[str, np.ndarray],
    station_spacing: float,
    normal_test: float,
) -> list[dict[str, Any]]:
    stations: list[dict[str, Any]] = []
    for side in ("east", "west"):
        along, pts = resample_line(shorelines[side], station_spacing)
        tangents = station_tangents(pts)
        normals = choose_seaward_normals(source, pts, tangents, normal_test)
        curv = curvature(pts, station_spacing)
        elev = sample_source(source, pts[:, 0], pts[:, 1])
        total_length = float(along[-1]) if along.size else float("nan")
        for i, (s, p, t, n) in enumerate(zip(along, pts, tangents, normals)):
            raw_info = raw_source_info(raw_map, float(p[0]), float(p[1]))
            stations.append({
                "side": side,
                "station_id": f"{side}_{i:04d}",
                "station_index": i,
                "alongshore_distance_m": float(s),
                "normalized_along_gulf_coordinate": float(s / total_length) if total_length > 0 else float("nan"),
                "x_m": float(p[0]),
                "y_m": float(p[1]),
                "shoreline_tangent_x": float(t[0]),
                "shoreline_tangent_y": float(t[1]),
                "seaward_normal_x": float(n[0]),
                "seaward_normal_y": float(n[1]),
                "shoreline_curvature": float(curv[i]),
                "source_topo_id_at_shoreline": source.source_topo_id,
                "native_resolution_m_at_shoreline": max(source.native_dx_m, source.native_dy_m),
                "effective_resolution_m_at_shoreline": source.effective_resolution_m,
                "model_grid_spacing_m": source.effective_resolution_m,
                "source_elevation_at_shoreline_m": float(elev[i]),
                **raw_info,
            })
    return stations


def transect_for_station(source: SourceTopography, station: dict[str, Any], distances: np.ndarray) -> np.ndarray:
    x = float(station["x_m"]) + distances * float(station["seaward_normal_x"])
    y = float(station["y_m"]) + distances * float(station["seaward_normal_y"])
    return sample_source(source, x, y)


def channel_anomalies_for_side(
    side_stations: list[dict[str, Any]],
    station_profiles: dict[str, np.ndarray],
    distances: np.ndarray,
    sea_level: float,
    along_window_m: float = 1000.0,
) -> dict[str, dict[float, float]]:
    out: dict[str, dict[float, float]] = {}
    along = np.asarray([float(station["alongshore_distance_m"]) for station in side_stations], dtype=np.float64)
    depths_by_offset: dict[float, np.ndarray] = {}
    for offset in (100.0, 250.0, 500.0, 1000.0):
        vals = []
        for station in side_stations:
            bed = station_profiles[station["station_id"]]
            vals.append(sea_level - interp_at_distance(distances, bed, offset))
        depths_by_offset[offset] = np.asarray(vals, dtype=np.float64)
    for idx, station in enumerate(side_stations):
        anomalies: dict[float, float] = {}
        nearby = np.abs(along - along[idx]) <= along_window_m
        for offset, depths in depths_by_offset.items():
            local = depths[nearby]
            baseline = float(np.nanmedian(local)) if np.any(np.isfinite(local)) else float("nan")
            depth = float(depths[idx])
            anomalies[offset] = depth - baseline if math.isfinite(depth) and math.isfinite(baseline) else float("nan")
        out[station["station_id"]] = anomalies
    return out


def add_channel_summary(row: dict[str, Any], channel: dict[float, float]) -> None:
    offsets = [100.0, 250.0, 500.0, 1000.0]
    valid_offsets = []
    positives = []
    max_positive = 0.0
    current_run = 0.0
    best_run = 0.0
    last_positive_offset: float | None = None
    for offset in offsets:
        anomaly = float(channel.get(offset, float("nan")))
        if math.isfinite(anomaly):
            row[f"channel_anomaly_{int(offset)}m"] = anomaly
            valid_offsets.append(offset)
            pos = max(0.0, anomaly)
            positives.append(pos)
            max_positive = max(max_positive, pos)
            if pos > 0.0:
                if last_positive_offset is None:
                    current_run = 0.0
                else:
                    current_run += offset - last_positive_offset
                best_run = max(best_run, current_run)
                last_positive_offset = offset
            else:
                current_run = 0.0
                last_positive_offset = None
        else:
            row[f"channel_anomaly_{int(offset)}m"] = float("nan")
    row["integrated_positive_channel_anomaly_0_1000m"] = (
        float(np.trapezoid(positives, valid_offsets)) if len(valid_offsets) >= 2 else float("nan")
    )
    row["max_positive_channel_anomaly_0_1000m"] = max_positive if positives else float("nan")
    row["contiguous_positive_channel_run_length_m"] = best_run if positives else float("nan")


def compute_metrics(
    source: SourceTopography,
    stations: list[dict[str, Any]],
    transect_length: float,
    transect_spacing: float,
    common_scales: list[float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    distances = np.arange(0.0, transect_length + 1e-9, transect_spacing)
    native_rows: list[dict[str, Any]] = []
    common_rows: list[dict[str, Any]] = []
    transect_rows: list[dict[str, Any]] = []
    station_beds: dict[str, np.ndarray] = {}
    smoothed_beds: dict[float, dict[str, np.ndarray]] = {float(scale): {} for scale in common_scales}
    for station in stations:
        bed = transect_for_station(source, station, distances)
        station_beds[station["station_id"]] = bed
        for scale in common_scales:
            smoothed_beds[float(scale)][station["station_id"]] = smooth_values(bed, transect_spacing, float(scale))
        if int(station["station_index"]) % 20 == 0:
            for d, z in zip(distances, bed):
                transect_rows.append({
                    "side": station["side"],
                    "station_id": station["station_id"],
                    "distance_offshore_m": d,
                    "bed_elevation_m": z,
                    "water_depth_m": source.sea_level - z if math.isfinite(float(z)) else float("nan"),
                    "source_topo_id": source.source_topo_id,
                    "native_resolution_m": max(source.native_dx_m, source.native_dy_m),
                    "effective_resolution_m": source.effective_resolution_m,
                    "valid_source_data": math.isfinite(float(z)),
                })
    native_channel: dict[str, dict[float, float]] = {}
    common_channel: dict[float, dict[str, dict[float, float]]] = {}
    for side in ("east", "west"):
        side_stations = [station for station in stations if station["side"] == side]
        native_channel.update(channel_anomalies_for_side(side_stations, station_beds, distances, source.sea_level))
        for scale in common_scales:
            profile = smoothed_beds[float(scale)]
            common_channel.setdefault(float(scale), {}).update(
                channel_anomalies_for_side(side_stations, profile, distances, source.sea_level)
            )
    for station in stations:
        bed = station_beds[station["station_id"]]
        channel = native_channel[station["station_id"]]
        row = metric_row(station, distances, bed, source.sea_level, "native", 0.0, channel)
        add_channel_summary(row, channel)
        native_rows.append(row)
        for scale in common_scales:
            smooth = smoothed_beds[float(scale)][station["station_id"]]
            common_row = metric_row(
                station,
                distances,
                smooth,
                source.sea_level,
                "common",
                float(scale),
                common_channel[float(scale)][station["station_id"]],
            )
            add_channel_summary(common_row, common_channel[float(scale)][station["station_id"]])
            common_rows.append(common_row)
    persistence: dict[str, int] = defaultdict(int)
    for row in native_rows + common_rows:
        value = float(row.get("integrated_positive_channel_anomaly_0_1000m", "nan"))
        if math.isfinite(value) and value > 0.0:
            persistence[str(row["station_id"])] += 1
    for row in native_rows + common_rows:
        row["channel_persistence_scale_count"] = persistence[str(row["station_id"])]
    return native_rows, common_rows, transect_rows


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def nearest_station(point: tuple[float, float], stations: list[dict[str, Any]], side: str) -> dict[str, Any]:
    side_stations = [station for station in stations if station["side"] == side]
    px, py = point
    return min(side_stations, key=lambda s: (float(s["x_m"]) - px) ** 2 + (float(s["y_m"]) - py) ** 2)


def velocity_station_response(
    source: SourceTopography,
    velocity_results: Path,
    stations: list[dict[str, Any]],
    metrics_native: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hotspots = load_csv(velocity_results / "hotspots.csv")
    summary = load_csv(velocity_results / "summary.csv")
    selected_frames = {
        (row["case_id"], row["requested_time_min_s"]): int(row["selected_frame_count"])
        for row in summary
        if row["zone"] == "combined_coastal"
        and float(row["seaward_distance_m"]) == MAIN_CORRIDOR[0]
        and float(row["landward_distance_m"]) == MAIN_CORRIDOR[1]
    }
    metrics_by_station = {row["station_id"]: row for row in metrics_native}
    joined: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in hotspots:
        if row["zone"] != "combined_coastal":
            continue
        if float(row["seaward_distance_m"]) != MAIN_CORRIDOR[0] or float(row["landward_distance_m"]) != MAIN_CORRIDOR[1]:
            continue
        side = row["side"]
        station = nearest_station((float(row["x_m"]), float(row["y_m"])), stations, side)
        tangent = np.asarray([station["shoreline_tangent_x"], station["shoreline_tangent_y"]], dtype=float)
        normal = np.asarray([station["seaward_normal_x"], station["seaward_normal_y"]], dtype=float)
        velocity = np.asarray([float(row["u_at_max_mps"]), float(row["v_at_max_mps"])], dtype=float)
        speed = float(row["max_displayed_speed_mps"])
        gradient = source_gradient(source, float(row["x_m"]), float(row["y_m"]))
        gradient_unit = unit_or_nan(gradient)
        downslope = -gradient_unit
        isobath_tangent = unit_or_nan(np.asarray([-gradient_unit[1], gradient_unit[0]], dtype=np.float64))
        u_parallel = float(np.dot(velocity, tangent))
        u_normal = float(np.dot(velocity, normal))
        u_parallel_isobath = float(np.dot(velocity, isobath_tangent)) if np.all(np.isfinite(isobath_tangent)) else float("nan")
        u_downslope = float(np.dot(velocity, downslope)) if np.all(np.isfinite(downslope)) else float("nan")
        angle_tangent = math.degrees(math.acos(np.clip(abs(u_parallel) / speed, 0.0, 1.0))) if speed > 0 else float("nan")
        metric = metrics_by_station.get(station["station_id"], {})
        item = {
            **row,
            "station_id": station["station_id"],
            "station_alongshore_distance_m": station["alongshore_distance_m"],
            "normalized_along_gulf_coordinate": station["normalized_along_gulf_coordinate"],
            "u_parallel_mps": u_parallel,
            "u_normal_mps": u_normal,
            "angle_to_shoreline_tangent_deg": angle_tangent,
            "angle_to_shoreline_normal_deg": math.degrees(math.acos(np.clip(abs(u_normal) / speed, 0.0, 1.0))) if speed > 0 else float("nan"),
            "angle_to_seaward_normal_deg": math.degrees(math.acos(np.clip(abs(u_normal) / speed, 0.0, 1.0))) if speed > 0 else float("nan"),
            "bathymetric_gradient_x": float(gradient[0]),
            "bathymetric_gradient_y": float(gradient[1]),
            "isobath_tangent_x": float(isobath_tangent[0]),
            "isobath_tangent_y": float(isobath_tangent[1]),
            "downslope_x": float(downslope[0]),
            "downslope_y": float(downslope[1]),
            "u_parallel_isobath_mps": u_parallel_isobath,
            "u_downslope_mps": u_downslope,
            "angle_to_isobath_tangent_deg": unsigned_angle_deg(velocity, isobath_tangent),
            "angle_to_bathymetric_gradient_deg": unsigned_angle_deg(velocity, gradient_unit),
            "velocity_to_channel_axis_alignment_deg": angle_tangent,
            "model_grid_spacing_m": station.get("model_grid_spacing_m", float("nan")),
            "raw_source_class_value": station.get("raw_source_class_value", 0),
            "raw_source_id": station.get("raw_source_id", "unknown"),
            "raw_source_native_resolution_m": station.get("raw_source_native_resolution_m", float("nan")),
            "raw_source_multibeam": station.get("raw_source_multibeam", "unknown"),
            "raw_source_confidence": station.get("raw_source_confidence", "unknown"),
            "source_overlap_count": station.get("source_overlap_count", 0),
            "distance_to_raw_source_boundary_m": station.get("distance_to_raw_source_boundary_m", float("nan")),
        }
        item.update({f"metric_{k}": v for k, v in metric.items()})
        joined.append(item)
        groups[(row["case_id"], row["requested_time_min_s"], side, station["station_id"])].append(item)
    responses: list[dict[str, Any]] = []
    station_by_id = {station["station_id"]: station for station in stations}
    for (case_id, time_min, side, station_id), items in groups.items():
        speeds = sorted([float(item["max_displayed_speed_mps"]) for item in items], reverse=True)
        rec = sum(int(item["displayed_frame_count"]) >= 2 for item in items)
        frame_count = selected_frames.get((case_id, time_min), 1)
        station = station_by_id[station_id]
        responses.append({
            "case_id": case_id,
            "requested_time_min_s": time_min,
            "side": side,
            "station_id": station_id,
            "alongshore_distance_m": station["alongshore_distance_m"],
            "displayed_arrow_count": len(items),
            "frame_presence_fraction": min(1.0, sum(int(item["displayed_frame_count"]) for item in items) / max(frame_count, 1)),
            "median_frame_local_max_speed_mps": float(np.median(speeds)) if speeds else float("nan"),
            "median_frame_local_top3_mean_speed_mps": float(np.mean(speeds[:3])) if speeds else float("nan"),
            "max_speed_mps": max(speeds) if speeds else float("nan"),
            "unique_hotspot_count": len(items),
            "recurrent_hotspot_count": rec,
            "median_u_parallel": float(np.median([float(item["u_parallel_mps"]) for item in items])),
            "median_u_normal": float(np.median([float(item["u_normal_mps"]) for item in items])),
            "median_alignment_to_isobath_deg": float(np.nanmedian([float(item["angle_to_isobath_tangent_deg"]) for item in items])),
            "median_alignment_to_shoreline_tangent_deg": float(np.nanmedian([float(item["angle_to_shoreline_tangent_deg"]) for item in items])),
            "median_u_parallel_isobath": float(np.nanmedian([float(item["u_parallel_isobath_mps"]) for item in items])),
            "median_u_downslope": float(np.nanmedian([float(item["u_downslope_mps"]) for item in items])),
            "raw_source_id": station.get("raw_source_id", "unknown"),
            "raw_source_native_resolution_m": station.get("raw_source_native_resolution_m", float("nan")),
            "raw_source_multibeam": station.get("raw_source_multibeam", "unknown"),
            "distance_to_raw_source_boundary_m": station.get("distance_to_raw_source_boundary_m", float("nan")),
        })
    return responses, joined


def rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.shape, dtype=np.float64)
    ranks[order] = np.arange(1, values.size + 1, dtype=np.float64)
    sorted_values = values[order]
    start = 0
    while start < values.size:
        stop = start + 1
        while stop < values.size and sorted_values[stop] == sorted_values[start]:
            stop += 1
        if stop - start > 1:
            ranks[order[start:stop]] = 0.5 * (start + 1 + stop)
        start = stop
    return ranks


def spearman(x: Iterable[float], y: Iterable[float]) -> float:
    xa = np.asarray(list(x), dtype=np.float64)
    ya = np.asarray(list(y), dtype=np.float64)
    finite = np.isfinite(xa) & np.isfinite(ya)
    xa = xa[finite]
    ya = ya[finite]
    if xa.size < 3 or np.nanstd(xa) == 0.0 or np.nanstd(ya) == 0.0:
        return float("nan")
    rx = rankdata(xa)
    ry = rankdata(ya)
    return float(np.corrcoef(rx, ry)[0, 1])


def bootstrap_ci(x: list[float], y: list[float], blocks: list[int], seed: int = 1234) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    unique = sorted(set(blocks))
    if len(unique) < 2:
        return float("nan"), float("nan")
    vals = []
    for _ in range(50):
        chosen = rng.choice(unique, size=len(unique), replace=True)
        keep = [i for i, block in enumerate(blocks) if block in chosen]
        vals.append(spearman([x[i] for i in keep], [y[i] for i in keep]))
    arr = np.asarray([v for v in vals if math.isfinite(v)], dtype=float)
    if arr.size == 0:
        return float("nan"), float("nan")
    return float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))


def mechanism_associations(
    responses: list[dict[str, Any]],
    metrics_native: list[dict[str, Any]],
    metrics_common: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metrics_by_station = {(row["station_id"], row["representation"], str(row["common_scale_m"])): row for row in metrics_native + metrics_common}
    predictors = {
        "distance_to_20m_isobath": "distance_to_20m_isobath",
        "distance_to_50m_isobath": "distance_to_50m_isobath",
        "mean_slope_0_500m": "mean_abs_slope_0_250m",
        "mean_slope_0_1000m": "mean_abs_slope_500_1000m",
        "integrated_channel_anomaly_0_1000m": "integrated_positive_channel_anomaly_0_1000m",
        "isobath_convergence_20m": "isobath_spacing_10_20m",
        "isobath_convergence_50m": "isobath_spacing_20_50m",
        "shoreline_curvature_500m": "shoreline_curvature",
        "distance_to_source_boundary": "distance_to_raw_source_boundary_m",
        "raw_source_native_resolution": "raw_source_native_resolution_m",
    }
    response_predictors = {
        "velocity_isobath_alignment": "median_alignment_to_isobath_deg",
    }
    rows: list[dict[str, Any]] = []
    for representation, scale in [("native", "0.0")] + [("common", str(float(v))) for v in (250, 500, 1000)]:
        for case_id in sorted({row["case_id"] for row in responses}):
            for time_min in sorted({row["requested_time_min_s"] for row in responses if row["case_id"] == case_id}, key=float):
                for side in ("east", "west"):
                    subset = [row for row in responses if row["case_id"] == case_id and row["requested_time_min_s"] == time_min and row["side"] == side]
                    source_ids = sorted({
                        str(metrics_by_station.get((row["station_id"], representation, scale), {}).get("raw_source_id", "unknown"))
                        for row in subset
                    })
                    source_subsets = ["all"] + [value for value in source_ids if value != "unknown"]
                    for boundary_exclusion in (0.0, 250.0, 500.0, 1000.0):
                        for source_subset in source_subsets:
                            for matched_resolution_subset in ("all", "raw_30m_only"):
                                filtered: list[dict[str, Any]] = []
                                for row in subset:
                                    metric = metrics_by_station.get((row["station_id"], representation, scale))
                                    if not metric:
                                        continue
                                    boundary = float(metric.get("distance_to_raw_source_boundary_m", "nan"))
                                    if math.isfinite(boundary) and boundary < boundary_exclusion:
                                        continue
                                    if source_subset != "all" and str(metric.get("raw_source_id", "unknown")) != source_subset:
                                        continue
                                    if matched_resolution_subset == "raw_30m_only":
                                        resolution = float(metric.get("raw_source_native_resolution_m", "nan"))
                                        if not math.isfinite(resolution) or abs(resolution - 30.0) > 1.0e-6:
                                            continue
                                    filtered.append(row)
                                for response_field in ("median_frame_local_top3_mean_speed_mps", "frame_presence_fraction"):
                                    y = [float(row[response_field]) for row in filtered]
                                    blocks = [int(float(row["alongshore_distance_m"]) // 5000.0) for row in filtered]
                                    for predictor, field in predictors.items():
                                        x = []
                                        for row in filtered:
                                            metric = metrics_by_station.get((row["station_id"], representation, scale))
                                            x.append(float(metric.get(field, "nan")) if metric else float("nan"))
                                        rho = spearman(x, y)
                                        lo, hi = bootstrap_ci(x, y, blocks)
                                        rows.append({
                                            "case_id": case_id,
                                            "requested_time_min_s": time_min,
                                            "side": side,
                                            "representation": representation,
                                            "common_scale_m": scale,
                                            "response": response_field,
                                            "predictor": predictor,
                                            "boundary_exclusion_m": boundary_exclusion,
                                            "raw_source_class_subset": source_subset,
                                            "matched_resolution_subset": matched_resolution_subset,
                                            "spearman_rho": rho,
                                            "block_bootstrap_ci_low": lo,
                                            "block_bootstrap_ci_high": hi,
                                            "sample_count": len(filtered),
                                        })
                                    for predictor, field in response_predictors.items():
                                        x = [float(row.get(field, "nan")) for row in filtered]
                                        rho = spearman(x, y)
                                        lo, hi = bootstrap_ci(x, y, blocks)
                                        rows.append({
                                            "case_id": case_id,
                                            "requested_time_min_s": time_min,
                                            "side": side,
                                            "representation": representation,
                                            "common_scale_m": scale,
                                            "response": response_field,
                                            "predictor": predictor,
                                            "boundary_exclusion_m": boundary_exclusion,
                                            "raw_source_class_subset": source_subset,
                                            "matched_resolution_subset": matched_resolution_subset,
                                            "spearman_rho": rho,
                                            "block_bootstrap_ci_low": lo,
                                            "block_bootstrap_ci_high": hi,
                                            "sample_count": len(filtered),
                                        })
    by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["side"],
            row["representation"],
            row["common_scale_m"],
            row["response"],
            row["predictor"],
            row["boundary_exclusion_m"],
            row["raw_source_class_subset"],
            row["matched_resolution_subset"],
        )
        by_key[key].append(row)
    for group in by_key.values():
        signs = [math.copysign(1.0, float(row["spearman_rho"])) for row in group if math.isfinite(float(row["spearman_rho"]))]
        dominant = math.copysign(1.0, float(np.nanmedian(signs))) if signs else float("nan")
        case_count = len({
            row["case_id"] for row in group
            if math.isfinite(float(row["spearman_rho"])) and math.copysign(1.0, float(row["spearman_rho"])) == dominant
        }) if math.isfinite(dominant) else 0
        for row in group:
            row["same_sign_case_count"] = case_count
    return rows


def matched_bins(stations: list[dict[str, Any]], metrics_native: list[dict[str, Any]], responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    east = [s for s in stations if s["side"] == "east"]
    west = [s for s in stations if s["side"] == "west"]
    metric = {row["station_id"]: row for row in metrics_native}
    response_by_station: dict[str, list[float]] = defaultdict(list)
    for row in responses:
        response_by_station[row["station_id"]].append(float(row["median_frame_local_top3_mean_speed_mps"]))
    rows = []
    for e in east:
        e_xi = float(e.get("normalized_along_gulf_coordinate", float("nan")))
        w = min(west, key=lambda s: abs(float(s.get("normalized_along_gulf_coordinate", float("nan"))) - e_xi))
        w_xi = float(w.get("normalized_along_gulf_coordinate", float("nan")))
        rows.append({
            "east_station_id": e["station_id"],
            "west_station_id": w["station_id"],
            "normalized_along_gulf_coordinate": e_xi,
            "xi_mismatch": abs(e_xi - w_xi) if math.isfinite(e_xi) and math.isfinite(w_xi) else float("nan"),
            "east_alongshore_distance_m": e["alongshore_distance_m"],
            "west_alongshore_distance_m": w["alongshore_distance_m"],
            "east_distance_to_20m_isobath": metric[e["station_id"]].get("distance_to_20m_isobath", "nan"),
            "west_distance_to_20m_isobath": metric[w["station_id"]].get("distance_to_20m_isobath", "nan"),
            "east_raw_source_id": metric[e["station_id"]].get("raw_source_id", "unknown"),
            "west_raw_source_id": metric[w["station_id"]].get("raw_source_id", "unknown"),
            "east_median_top3_response": float(np.nanmedian(response_by_station[e["station_id"]])) if response_by_station[e["station_id"]] else float("nan"),
            "west_median_top3_response": float(np.nanmedian(response_by_station[w["station_id"]])) if response_by_station[w["station_id"]] else float("nan"),
        })
    return rows


def setup_matplotlib():
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Liberation Sans"
    return plt


def finite_float_list(rows: list[dict[str, Any]], field: str) -> list[float]:
    vals = []
    for row in rows:
        try:
            value = float(row.get(field, "nan"))
        except (TypeError, ValueError):
            value = float("nan")
        if math.isfinite(value):
            vals.append(value)
    return vals


def write_simple_figures(
    out: Path,
    shorelines: dict[str, np.ndarray],
    stations: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    common_metrics: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    joined: list[dict[str, Any]],
    associations: list[dict[str, Any]],
    transects: list[dict[str, Any]],
) -> None:
    plt = setup_matplotlib()
    station_by_id = {s["station_id"]: s for s in stations}

    fig, ax = plt.subplots(figsize=(8, 9))
    for side, line in shorelines.items():
        ax.plot(line[:, 0], line[:, 1], linewidth=1.1, label=f"{side} accepted shoreline")
    ax.scatter([s["x_m"] for s in stations[::10]], [s["y_m"] for s in stations[::10]], s=2, color="0.2", alpha=0.35)
    ax.quiver(
        [s["x_m"] for s in stations[::60]],
        [s["y_m"] for s in stations[::60]],
        [s["seaward_normal_x"] for s in stations[::60]],
        [s["seaward_normal_y"] for s in stations[::60]],
        angles="xy",
        scale_units="xy",
        scale=0.002,
        width=0.002,
        color="#238b45",
    )
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("UTM x (m)")
    ax.set_ylabel("UTM y (m)")
    ax.set_title("corrected shoreline geometry QC")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "corrected_shoreline_geometry_qc.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 9))
    colors = {
        "copernicus_a2_land_core": "#969696",
        "ribot_gmrt_shore_blend": "#74c476",
        "gmrt_shore_blend": "#9ecae1",
        "ribot_multibeam_core": "#006d2c",
        "gmrt_core": "#08519c",
        "unknown": "#d9d9d9",
    }
    for side, line in shorelines.items():
        ax.plot(line[:, 0], line[:, 1], color="black", linewidth=0.6)
    for source_id in sorted({str(s.get("raw_source_id", "unknown")) for s in stations}):
        pts = [s for s in stations if str(s.get("raw_source_id", "unknown")) == source_id]
        ax.scatter([p["x_m"] for p in pts], [p["y_m"] for p in pts], s=4, color=colors.get(source_id, "#fd8d3c"), label=source_id)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("UTM x (m)")
    ax.set_ylabel("UTM y (m)")
    ax.set_title("source resolution and raw source class samples")
    ax.legend(fontsize=6, markerscale=2)
    fig.tight_layout()
    fig.savefig(out / "source_resolution_map.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 9))
    for side, line in shorelines.items():
        ax.plot(line[:, 0], line[:, 1], linewidth=0.7, label=side)
    if joined:
        speeds = finite_float_list(joined, "max_displayed_speed_mps")
        sc = ax.scatter(
            [float(row["x_m"]) for row in joined],
            [float(row["y_m"]) for row in joined],
            c=[float(row["max_displayed_speed_mps"]) for row in joined],
            s=8,
            cmap="viridis",
            alpha=0.75,
        )
        fig.colorbar(sc, ax=ax, label="depth-averaged flow speed (m/s)")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("UTM x (m)")
    ax.set_ylabel("UTM y (m)")
    ax.set_title("velocity hotspots over shoreline stations")
    fig.tight_layout()
    fig.savefig(out / "fig_hotspots_bathymetry_map.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    for side, color in (("east", "#d7301f"), ("west", "#225ea8")):
        side_rows = [row for row in metrics if row["side"] == side]
        xs = [float(row["normalized_along_gulf_coordinate"]) for row in side_rows]
        axes[0].plot(xs, [float(row.get("distance_to_20m_isobath", "nan")) for row in side_rows], color=color, label=f"{side} d20")
        axes[1].plot(xs, [float(row.get("mean_abs_slope_0_250m", "nan")) for row in side_rows], color=color, label=f"{side} slope")
        axes[2].plot(xs, [float(row.get("integrated_positive_channel_anomaly_0_1000m", "nan")) for row in side_rows], color=color, label=f"{side} channel")
    axes[0].set_ylabel("20 m isobath distance (m)")
    axes[1].set_ylabel("slope 0-250 m")
    axes[2].set_ylabel("positive channel anomaly")
    axes[2].set_xlabel("normalized along-gulf coordinate")
    for axis in axes:
        axis.legend(fontsize=7)
        axis.grid(True, linewidth=0.3, alpha=0.4)
    fig.tight_layout()
    fig.savefig(out / "fig_alongshore_controls.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6))
    for row in transects:
        if int(str(row["station_id"]).split("_")[-1]) % 80 != 0:
            continue
        color = "#d7301f" if row["side"] == "east" else "#225ea8"
        ax.scatter(float(row["distance_offshore_m"]), float(row["water_depth_m"]), s=2, color=color, alpha=0.45)
    ax.set_xlabel("distance offshore (m)")
    ax.set_ylabel("water depth (m)")
    ax.set_title("representative bathymetric transect samples")
    ax.grid(True, linewidth=0.3, alpha=0.4)
    fig.tight_layout()
    fig.savefig(out / "fig_bathymetric_transects.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    assoc = [
        row for row in associations
        if row["boundary_exclusion_m"] == "0" or str(row["boundary_exclusion_m"]) in {"0.0", "0"}
    ]
    predictors = sorted({row["predictor"] for row in associations})
    pos = {name: idx for idx, name in enumerate(predictors)}
    for row in associations:
        rho = float(row["spearman_rho"])
        if not math.isfinite(rho) or str(row.get("raw_source_class_subset", "all")) != "all":
            continue
        x = pos[row["predictor"]] + (-0.12 if row["side"] == "east" else 0.12)
        ax.scatter(x, rho, s=8, alpha=0.35, color="#d7301f" if row["side"] == "east" else "#225ea8")
    ax.axhline(0, color="0.2", linewidth=0.6)
    ax.set_xticks(range(len(predictors)))
    ax.set_xticklabels(predictors, rotation=35, ha="right", fontsize=7)
    ax.set_ylabel("Spearman rho")
    ax.set_title("control associations by predictor")
    fig.tight_layout()
    fig.savefig(out / "fig_control_associations.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6))
    for predictor, marker in (("distance_to_source_boundary", "o"), ("raw_source_native_resolution", "s"), ("velocity_isobath_alignment", "^")):
        rows = [row for row in associations if row["predictor"] == predictor and str(row.get("raw_source_class_subset", "all")) == "all"]
        xs = [float(row["boundary_exclusion_m"]) for row in rows if math.isfinite(float(row["spearman_rho"]))]
        ys = [float(row["spearman_rho"]) for row in rows if math.isfinite(float(row["spearman_rho"]))]
        ax.scatter(xs, ys, s=12, alpha=0.45, label=predictor, marker=marker)
    ax.axhline(0, color="0.2", linewidth=0.6)
    ax.set_xlabel("raw source boundary exclusion (m)")
    ax.set_ylabel("Spearman rho")
    ax.set_title("resolution and provenance sensitivity")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "fig_resolution_sensitivity.pdf")
    plt.close(fig)


def write_source_resolution_geojson(out: Path, source: SourceTopography, stations: list[dict[str, Any]]) -> None:
    xmin = source.xllcenter - 0.5 * source.dx
    xmax = xmin + source.ncols * source.dx
    ymin = source.yllcenter - 0.5 * source.dy
    ymax = ymin + source.nrows * source.dy
    features: list[dict[str, Any]] = [{
        "type": "Feature",
        "properties": {
            "role": "source_topography_extent",
            "source_topo_id": source.source_topo_id,
            "native_dx_m": source.native_dx_m,
            "native_dy_m": source.native_dy_m,
            "effective_resolution_m": source.effective_resolution_m,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]],
        },
    }]
    for station in stations[:: max(1, len(stations) // 200)]:
        features.append({
            "type": "Feature",
            "properties": {
                "role": "shoreline_station_resolution_sample",
                "side": station["side"],
                "station_id": station["station_id"],
                "source_topo_id": source.source_topo_id,
                "effective_resolution_m": source.effective_resolution_m,
                "model_grid_spacing_m": station.get("model_grid_spacing_m", float("nan")),
                "raw_source_class_value": station.get("raw_source_class_value", 0),
                "raw_source_id": station.get("raw_source_id", "unknown"),
                "raw_source_native_resolution_m": station.get("raw_source_native_resolution_m", float("nan")),
                "raw_source_multibeam": station.get("raw_source_multibeam", "unknown"),
                "distance_to_raw_source_boundary_m": station.get("distance_to_raw_source_boundary_m", float("nan")),
            },
            "geometry": {"type": "Point", "coordinates": [station["x_m"], station["y_m"]]},
        })
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:32637"}},
        "features": features,
    }
    (out / "source_resolution_map.geojson").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def mechanism_summary_text(associations: list[dict[str, Any]]) -> str:
    lines = [
        "Receiver-side bathymetric controls summary",
        "Velocity response: viewer-displayed pointwise depth-averaged flow speed hotspots.",
        "Bathymetric metrics source: model-referenced source TOPO only.",
        "Interpretation language is limited to association/consistency diagnostics.",
        "Evidence categories: strong, moderate, weak, not supported, resolution-confounded, provenance unresolved, not evaluated.",
        "",
        "Energy trapping was not evaluated because no energy-flux residence or lateral-leakage diagnostic was computed.",
        "",
    ]
    for predictor in sorted({row["predictor"] for row in associations}):
        common = [
            float(row["spearman_rho"]) for row in associations
            if row["predictor"] == predictor
            and row["representation"] == "common"
            and str(row.get("raw_source_class_subset", "all")) == "all"
            and str(row.get("matched_resolution_subset", "all")) == "all"
            and math.isfinite(float(row["spearman_rho"]))
        ]
        native = [
            float(row["spearman_rho"]) for row in associations
            if row["predictor"] == predictor
            and row["representation"] == "native"
            and str(row.get("raw_source_class_subset", "all")) == "all"
            and str(row.get("matched_resolution_subset", "all")) == "all"
            and math.isfinite(float(row["spearman_rho"]))
        ]
        if not common or not native:
            label = "not evaluated"
        elif predictor in {"raw_source_native_resolution", "distance_to_source_boundary"}:
            label = "provenance unresolved" if np.nanmedian(np.abs(native + common)) > 0.2 else "weak"
        elif np.sign(np.nanmedian(common)) != np.sign(np.nanmedian(native)):
            label = "resolution-confounded"
        elif predictor == "integrated_channel_anomaly_0_1000m" and abs(float(np.nanmedian(native))) < 0.3:
            label = "not supported"
        elif abs(float(np.nanmedian(native))) > 0.7 and abs(float(np.nanmedian(common))) > 0.7:
            label = "strong"
        elif abs(float(np.nanmedian(native))) > 0.5 and abs(float(np.nanmedian(common))) > 0.5:
            label = "moderate"
        elif abs(float(np.nanmedian(native))) > 0.3 and abs(float(np.nanmedian(common))) > 0.3:
            label = "weak"
        else:
            label = "not supported"
        lines.append(f"{predictor}: {label}; native median rho={np.nanmedian(native) if native else float('nan'):.3f}; common median rho={np.nanmedian(common) if common else float('nan'):.3f}")
    lines.append("")
    lines.append("Specific trough/channel control is not supported unless contiguous positive channel anomalies persist across native and common scales with same-sign velocity association.")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> None:
    source = load_source_topography(args.topography_provenance)
    raw_map = load_raw_source_map(args.topography_provenance)
    shorelines = read_shorelines(args.shorelines)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    stations = build_stations(source, raw_map, shorelines, args.station_spacing_m, args.transect_spacing_m)
    native_rows, common_rows, transects = compute_metrics(
        source,
        stations,
        args.transect_length_m,
        args.transect_spacing_m,
        args.common_scale_m,
    )
    responses, joined = velocity_station_response(source, args.velocity_results, stations, native_rows)
    associations = mechanism_associations(responses, native_rows, common_rows)
    bins = matched_bins(stations, native_rows, responses)
    resolution_summary = [{
        "side": station["side"],
        "station_id": station["station_id"],
        "source_topo_id": station["source_topo_id_at_shoreline"],
        "model_grid_spacing_m": station.get("model_grid_spacing_m", float("nan")),
        "native_dx_m": source.native_dx_m,
        "native_dy_m": source.native_dy_m,
        "effective_resolution_m": source.effective_resolution_m,
        "raw_source_class_value": station.get("raw_source_class_value", 0),
        "raw_source_id": station.get("raw_source_id", "unknown"),
        "raw_source_native_resolution_m": station.get("raw_source_native_resolution_m", float("nan")),
        "raw_source_multibeam": station.get("raw_source_multibeam", "unknown"),
        "raw_source_confidence": station.get("raw_source_confidence", "unknown"),
        "source_overlap_count": station.get("source_overlap_count", 0),
        "source_precedence_rank": 1,
        "multibeam_coverage": station.get("raw_source_multibeam", "unknown"),
        "distance_to_raw_source_boundary_m": station.get("distance_to_raw_source_boundary_m", float("nan")),
        "distance_to_resolution_boundary_m": station.get("distance_to_raw_source_boundary_m", float("nan")),
        "distance_to_raw_source_boundary_censored": station.get("distance_to_raw_source_boundary_censored", "unknown"),
    } for station in stations]
    manifest_path = args.topography_provenance.parent / "source_topography_manifest.csv"
    if not manifest_path.exists():
        manifest_path = Path("analysis/source_topography_manifest.csv")
    write_csv(out / "source_topography_manifest.csv", load_csv(manifest_path))
    write_csv(out / "source_resolution_station_summary.csv", resolution_summary)
    write_csv(out / "shoreline_stations.csv", stations)
    write_csv(out / "bathymetric_metrics_native.csv", native_rows)
    write_csv(out / "bathymetric_metrics_common_scale.csv", common_rows)
    write_csv(out / "station_velocity_response.csv", responses)
    write_csv(out / "hotspot_bathymetry_join.csv", joined)
    write_csv(out / "east_west_matched_bins.csv", bins)
    write_csv(out / "mechanism_associations.csv", associations)
    write_csv(out / "representative_transects.csv", transects)
    (out / "mechanism_summary.txt").write_text(mechanism_summary_text(associations), encoding="utf-8")
    write_simple_figures(out, shorelines, stations, native_rows, common_rows, responses, joined, associations, transects)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze receiver-side coastal bathymetric controls from source TOPO.")
    parser.add_argument("--scenario-root", required=True, type=Path)
    parser.add_argument("--topo-root", required=True, type=Path)
    parser.add_argument("--topography-provenance", required=True, type=Path)
    parser.add_argument("--shorelines", required=True, type=Path)
    parser.add_argument("--velocity-results", required=True, type=Path)
    parser.add_argument("--station-spacing-m", required=True, type=float)
    parser.add_argument("--transect-length-m", required=True, type=float)
    parser.add_argument("--transect-spacing-m", required=True, type=float)
    parser.add_argument("--common-scale-m", nargs="+", type=float, required=True)
    parser.add_argument("--time-min-s", nargs="+", type=float, required=True)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
