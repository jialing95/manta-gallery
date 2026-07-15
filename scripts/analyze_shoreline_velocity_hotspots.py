#!/usr/bin/env python3
"""Shoreline-following viewer-parity Velocity arrows hotspot analysis."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


COMPACT_MAGIC = b"MANTAV2\0"
COMPACT_FORMAT_VERSION = 2
COMPACT_HEADER = struct.Struct("<8sII")

VELOCITY_ARROW_STRIDE = 1
VELOCITY_ARROW_SCALE = 10.0
VELOCITY_ARROW_MAX_COUNT = 20000
VELOCITY_ARROW_MIN_SPEED = 0.01
WATER_DRY_TOLERANCE_FALLBACK = 5.0e-4

VIEWER_SOURCE_PATH = "viewer/src/manta_case_viewer.js"
VIEWER_FUNCTIONS = (
    "getVelocityArrowOptions",
    "createVelocityArrowDataset",
    "spatiallySampleVelocityCandidates",
    "compactPointMaskFromCellPredicate",
    "getWaterCellPredicate",
    "getWaterOverlayRange",
)

SIDES = ("east", "west")
ZONES = ("seaward", "landward_inundated", "combined_coastal")

FRAME_SUMMARY_FIELDS = (
    "case_id",
    "requested_time_min_s",
    "effective_first_selected_time_s",
    "frame_index",
    "time_s",
    "seaward_distance_m",
    "landward_distance_m",
    "side",
    "zone",
    "candidate_count_before_global_sampling",
    "displayed_arrow_count",
    "displayed_speed_max_mps",
    "displayed_top10_mean_speed_mps",
    "displayed_top10_count",
    "displayed_max_point_id",
    "displayed_max_x_m",
    "displayed_max_y_m",
    "displayed_max_u_mps",
    "displayed_max_v_mps",
    "displayed_max_h_m",
    "displayed_max_m",
    "displayed_max_b0_m",
    "displayed_max_b_current_m",
    "displayed_max_shoreline_distance_m",
    "displayed_max_static_zone",
    "displayed_max_dynamic_wet",
    "displayed_max_source_topo_id",
    "displayed_max_native_dx_m",
    "displayed_max_native_dy_m",
    "displayed_max_effective_resolution_m",
    "displayed_max_source_precedence_rank",
    "colorbar_fraction",
    "colorbar_saturated",
)

HOTSPOT_FIELDS = (
    "case_id",
    "requested_time_min_s",
    "seaward_distance_m",
    "landward_distance_m",
    "side",
    "zone",
    "rank",
    "point_id",
    "max_displayed_speed_mps",
    "max_frame_index",
    "max_time_s",
    "displayed_frame_count",
    "x_m",
    "y_m",
    "shoreline_distance_m",
    "b0_m",
    "b_current_at_max_m",
    "h_at_max_m",
    "dynamic_wet_at_max",
    "u_at_max_mps",
    "v_at_max_mps",
    "source_topo_id",
    "native_dx_m",
    "native_dy_m",
    "effective_resolution_m",
    "source_precedence_rank",
    "colorbar_fraction_at_max",
    "colorbar_saturated_at_max",
)

SUMMARY_FIELDS = (
    "case_id",
    "requested_time_min_s",
    "effective_first_selected_time_s",
    "effective_last_selected_time_s",
    "selected_frame_count",
    "seaward_distance_m",
    "landward_distance_m",
    "zone",
    "frames_with_both_east_and_west",
    "frames_east_only",
    "frames_west_only",
    "frames_neither",
    "east_global_max_mps",
    "west_global_max_mps",
    "east_west_global_max_ratio",
    "east_median_frame_max_mps",
    "west_median_frame_max_mps",
    "east_west_median_frame_max_ratio",
    "east_mean_frame_max_mps",
    "west_mean_frame_max_mps",
    "east_west_mean_frame_max_ratio",
    "east_median_frame_top10_mean_mps",
    "west_median_frame_top10_mean_mps",
    "east_west_median_frame_top10_ratio",
    "east_mean_frame_top10_mean_mps",
    "west_mean_frame_top10_mean_mps",
    "east_west_mean_frame_top10_ratio",
    "frames_east_max_gt_west",
    "frames_west_max_gt_east",
    "fraction_frames_east_max_gt_west",
    "frames_east_top10_gt_west",
    "frames_west_top10_gt_east",
    "fraction_frames_east_top10_gt_west",
    "east_topN_unique_median_max_mps",
    "west_topN_unique_median_max_mps",
    "east_west_topN_unique_median_ratio",
    "east_topN_unique_mean_max_mps",
    "west_topN_unique_mean_max_mps",
    "east_west_topN_unique_mean_ratio",
    "east_topN_recurrent_ge_2_frames",
    "west_topN_recurrent_ge_2_frames",
)

OUTPUT_FILES = {
    "frame_summary.csv",
    "hotspots.csv",
    "summary.csv",
    "shoreline_mask_qc.geojson",
    "shoreline_mask_qc.pdf",
    "validation.txt",
}


@dataclass(frozen=True)
class ArrowOptions:
    stride: int
    scale: float
    max_count: int
    min_speed: float
    cell_scale: float


@dataclass(frozen=True)
class Candidate:
    point_id: int
    speed: float


@dataclass(frozen=True)
class FrameContext:
    case_id: str
    frame_index: int
    time_s: float
    water_m: float
    arrays: dict[str, np.ndarray]
    options: ArrowOptions
    colorbar_range: tuple[float, float]
    dry_tolerance: float


@dataclass(frozen=True)
class Corridor:
    seaward_m: float
    landward_m: float


@dataclass
class ShorelineSet:
    east: list[np.ndarray]
    west: list[np.ndarray]
    crs_epsg: int | None = None
    source: str = ""


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
    source_precedence_rank: int = 1


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_source_topography(provenance_path: Path | None) -> SourceTopography | None:
    if provenance_path is None:
        return None
    provenance_path = Path(provenance_path)
    payload = load_json(provenance_path)
    grid_meta = payload["grid"]
    grid_path = Path(str(grid_meta["elevation_npy"]))
    if not grid_path.is_absolute() and not grid_path.exists():
        grid_path = provenance_path.parent / grid_path
    grid = np.load(grid_path, mmap_mode="r")
    return SourceTopography(
        grid=grid,
        ncols=int(grid_meta["ncols"]),
        nrows=int(grid_meta["nrows"]),
        xllcenter=float(grid_meta["xllcenter"]),
        yllcenter=float(grid_meta["yllcenter"]),
        dx=float(grid_meta["dx"]),
        dy=float(grid_meta["dy"]),
        source_topo_id=str(grid_meta.get("source_topo_id", "topo-bathy.tt3")),
        native_dx_m=float(grid_meta.get("native_dx_m", grid_meta["dx"])),
        native_dy_m=float(grid_meta.get("native_dy_m", grid_meta["dy"])),
        effective_resolution_m=float(grid_meta.get("effective_resolution_m", max(float(grid_meta["dx"]), float(grid_meta["dy"])))),
    )


def sample_source_topography(source: SourceTopography, x: np.ndarray, y: np.ndarray) -> np.ndarray:
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


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def js_round(value: float) -> int:
    return int(math.floor(value + 0.5))


def js_number_or_fallback(value: Any, fallback: float) -> float:
    number = finite_number(value)
    if number is None or number == 0.0:
        return float(fallback)
    return float(number)


def finite_pair_range(range_value: Any) -> tuple[float, float] | None:
    if not isinstance(range_value, list | tuple) or len(range_value) < 2:
        return None
    lo = finite_number(range_value[0])
    hi = finite_number(range_value[1])
    if lo is None or hi is None or hi <= lo:
        return None
    return lo, hi


def compact_dtype(dtype_name: str) -> np.dtype:
    dtype = np.dtype(dtype_name)
    if dtype.itemsize > 1:
        dtype = dtype.newbyteorder("<")
    return dtype


def read_compact_archive(path: Path) -> bytes:
    with gzip.open(path, "rb") as handle:
        blob = handle.read()
    if len(blob) < COMPACT_HEADER.size:
        raise ValueError(f"{path}: compact-v2 archive is shorter than its header")
    magic, version, payload_length = COMPACT_HEADER.unpack_from(blob, 0)
    if magic != COMPACT_MAGIC:
        raise ValueError(f"{path}: invalid compact-v2 magic {magic!r}")
    if int(version) != COMPACT_FORMAT_VERSION:
        raise ValueError(f"{path}: unsupported compact-v2 version {version}")
    actual_payload_length = len(blob) - COMPACT_HEADER.size
    if int(payload_length) != actual_payload_length:
        raise ValueError(
            f"{path}: compact-v2 payload length mismatch "
            f"header={payload_length} actual={actual_payload_length}"
        )
    return blob


def read_compact_array(blob: bytes, meta: dict[str, Any], name: str) -> np.ndarray:
    dtype = compact_dtype(str(meta["dtype"]))
    byte_offset = int(meta["byte_offset"])
    length = int(meta["length"])
    byte_length = length * dtype.itemsize
    if byte_offset < COMPACT_HEADER.size:
        raise ValueError(f"{name}: byte_offset {byte_offset} overlaps compact-v2 header")
    if byte_offset + byte_length > len(blob):
        raise ValueError(f"{name}: compact array extends beyond archive payload")
    arr = np.frombuffer(blob, dtype=dtype, count=length, offset=byte_offset)
    components = int(meta.get("components", 1))
    if components > 1:
        if length % components != 0:
            raise ValueError(f"{name}: length {length} is not divisible by components {components}")
        arr = arr.reshape((-1, components))
    return arr


def require_water_compact(case: dict[str, Any], case_path: Path) -> dict[str, Any]:
    try:
        compact = case["layers"]["water"]["compact"]
    except KeyError as exc:
        raise KeyError(f"{case_path}: missing case.json layers.water.compact") from exc
    if int(compact.get("version", -1)) != COMPACT_FORMAT_VERSION:
        raise ValueError(f"{case_path}: water compact version must be 2")
    if compact.get("compression") != "gzip":
        raise ValueError(f"{case_path}: water compact compression must be gzip")
    if compact.get("endianness") != "little":
        raise ValueError(f"{case_path}: water compact endianness must be little")
    return compact


def resolve_case_file(case_dir: Path, relative_file: str) -> Path:
    path = case_dir / relative_file
    if not path.exists():
        raise FileNotFoundError(f"Missing compact asset: {path}")
    return path


def resolve_frame_file(case_dir: Path, file_pattern: str, frame_index: int) -> Path:
    candidates: list[Path] = []
    for value in (f"{frame_index:04d}", frame_index):
        try:
            rendered = file_pattern.format(frame=value)
        except (ValueError, TypeError):
            continue
        candidates.append(case_dir / rendered)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing frame asset; tried: {', '.join(str(p) for p in candidates)}")


def load_template(case_dir: Path, compact: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    template = compact["template"]
    arrays = template["arrays"]
    blob = read_compact_archive(resolve_case_file(case_dir, str(template["file"])))
    x = read_compact_array(blob, arrays["x"], "template.x").astype(np.float64, copy=False)
    y = read_compact_array(blob, arrays["y"], "template.y").astype(np.float64, copy=False)
    quads = read_compact_array(blob, arrays["quads"], "template.quads").astype(np.int64, copy=False)
    quads = quads.reshape((-1, 4))
    point_count = int(compact["point_count"])
    cell_count = int(compact["cell_count"])
    if x.size != point_count or y.size != point_count:
        raise ValueError(f"{case_dir}: template point arrays do not match point_count")
    if quads.shape != (cell_count, 4):
        raise ValueError(f"{case_dir}: template quads do not match cell_count")
    if np.any(quads < 0) or np.any(quads >= point_count):
        raise ValueError(f"{case_dir}: template quads reference points outside x/y arrays")
    return x, y, quads


def load_frame_arrays(case_dir: Path, compact: dict[str, Any], frame_index: int) -> dict[str, np.ndarray]:
    frame = compact["frame"]
    arrays_meta = frame["arrays"]
    required = ("z", "m", "h", "u", "v", "valid_cells")
    missing = [name for name in required if name not in arrays_meta]
    if missing:
        raise ValueError(f"{case_dir}: water compact frame is missing arrays: {', '.join(missing)}")
    blob = read_compact_archive(resolve_frame_file(case_dir, str(frame["file_pattern"]), frame_index))
    arrays: dict[str, np.ndarray] = {}
    for name in ("z", "m", "h", "u", "v"):
        arrays[name] = read_compact_array(blob, arrays_meta[name], f"frame.{name}").astype(
            np.float64,
            copy=False,
        )
    valid_meta = arrays_meta["valid_cells"]
    packed = read_compact_array(blob, valid_meta, "frame.valid_cells")
    bit_order = str(valid_meta.get("bit_order", "big"))
    if bit_order not in {"big", "little"}:
        raise ValueError(f"{case_dir}: valid_cells bit_order must be big or little")
    valid_cells = np.unpackbits(packed.astype(np.uint8, copy=False), bitorder=bit_order)
    cell_count = int(compact["cell_count"])
    if valid_cells.size < cell_count:
        raise ValueError(f"{case_dir}: packed valid_cells is shorter than cell_count")
    arrays["valid_cells"] = valid_cells[:cell_count].astype(bool, copy=False)
    return arrays


def static_b0_from_frame0(frame0: dict[str, np.ndarray]) -> np.ndarray:
    return frame0["z"] - frame0["h"]


def geojson_epsg(geojson: dict[str, Any]) -> int | None:
    crs = geojson.get("crs")
    if not isinstance(crs, dict):
        return None
    props = crs.get("properties")
    if not isinstance(props, dict):
        return None
    name = str(props.get("name", ""))
    marker = "EPSG"
    upper = name.upper()
    if marker not in upper:
        return None
    digits = "".join(ch if ch.isdigit() else " " for ch in upper.split(marker, 1)[1]).split()
    return int(digits[-1]) if digits else None


def line_parts_from_geometry(geometry: dict[str, Any]) -> list[np.ndarray]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "LineString":
        parts = [coords]
    elif gtype == "MultiLineString":
        parts = coords
    else:
        raise ValueError(f"Shoreline geometry must be LineString or MultiLineString, got {gtype!r}")
    out: list[np.ndarray] = []
    for part in parts:
        arr = np.asarray(part, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[0] < 2 or arr.shape[1] < 2:
            raise ValueError("Shoreline line parts must contain at least two x-y coordinates")
        out.append(arr[:, :2])
    return out


def load_shorelines_geojson(path: Path) -> ShorelineSet:
    geojson = load_json(path)
    if geojson.get("type") != "FeatureCollection":
        raise ValueError(f"{path}: shorelines must be a FeatureCollection")
    parts: dict[str, list[np.ndarray]] = {"east": [], "west": []}
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        side = str(props.get("side", "")).strip().lower()
        if side not in parts:
            continue
        parts[side].extend(line_parts_from_geometry(feature.get("geometry") or {}))
    if len(parts["east"]) == 0 or len(parts["west"]) == 0:
        raise ValueError(f"{path}: must contain east and west shoreline features")
    return ShorelineSet(
        east=parts["east"],
        west=parts["west"],
        crs_epsg=geojson_epsg(geojson),
        source=str((geojson.get("properties") or {}).get("source", "")),
    )


def flatten_line_segments(lines: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    starts: list[np.ndarray] = []
    ends: list[np.ndarray] = []
    for line in lines:
        starts.append(line[:-1])
        ends.append(line[1:])
    if not starts:
        return np.empty((0, 2), dtype=np.float64), np.empty((0, 2), dtype=np.float64)
    return np.vstack(starts).astype(np.float64), np.vstack(ends).astype(np.float64)


def point_to_segments_distance_chunked(
    points_x: np.ndarray,
    points_y: np.ndarray,
    seg_start: np.ndarray,
    seg_end: np.ndarray,
    chunk_size: int = 1024,
    search_pad_m: float = 5000.0,
) -> np.ndarray:
    points = np.column_stack((points_x, points_y)).astype(np.float64, copy=False)
    if seg_start.size == 0:
        return np.full(points.shape[0], np.inf, dtype=np.float64)
    if seg_start.shape[0] > 512:
        return point_to_monotonic_segments_distance(points_x, points_y, seg_start, seg_end)
    seg = seg_end - seg_start
    seg_len2 = np.sum(seg * seg, axis=1)
    seg_len2 = np.where(seg_len2 > 0.0, seg_len2, 1.0)
    out = np.empty(points.shape[0], dtype=np.float64)
    order = np.argsort(points[:, 1], kind="mergesort")
    seg_y_min = np.minimum(seg_start[:, 1], seg_end[:, 1])
    seg_y_max = np.maximum(seg_start[:, 1], seg_end[:, 1])
    for start in range(0, points.shape[0], int(chunk_size)):
        stop = min(points.shape[0], start + int(chunk_size))
        point_index = order[start:stop]
        p = points[point_index]
        y0 = float(np.min(p[:, 1])) - float(search_pad_m)
        y1 = float(np.max(p[:, 1])) + float(search_pad_m)
        seg_keep = (seg_y_max >= y0) & (seg_y_min <= y1)
        if not np.any(seg_keep):
            seg_keep = np.ones(seg_start.shape[0], dtype=bool)
        s0 = seg_start[seg_keep]
        s = seg[seg_keep]
        sl2 = seg_len2[seg_keep]
        rel = p[:, None, :] - s0[None, :, :]
        t = np.sum(rel * s[None, :, :], axis=2) / sl2[None, :]
        t = np.clip(t, 0.0, 1.0)
        closest = s0[None, :, :] + t[:, :, None] * s[None, :, :]
        d2 = np.sum((p[:, None, :] - closest) ** 2, axis=2)
        out[point_index] = np.sqrt(np.min(d2, axis=1))
    return out


def point_to_monotonic_segments_distance(
    points_x: np.ndarray,
    points_y: np.ndarray,
    seg_start: np.ndarray,
    seg_end: np.ndarray,
    window_segments: int = 35,
) -> np.ndarray:
    seg_mid_y = 0.5 * (seg_start[:, 1] + seg_end[:, 1])
    order = np.argsort(seg_mid_y, kind="mergesort")
    seg_start = seg_start[order]
    seg_end = seg_end[order]
    seg_mid_y = seg_mid_y[order]
    base = np.searchsorted(seg_mid_y, points_y)
    out2 = np.full(points_x.shape, np.inf, dtype=np.float64)
    px = points_x.astype(np.float64, copy=False)
    py = points_y.astype(np.float64, copy=False)
    for offset in range(-int(window_segments), int(window_segments) + 1):
        idx = np.clip(base + offset, 0, seg_start.shape[0] - 1)
        ax = seg_start[idx, 0]
        ay = seg_start[idx, 1]
        bx = seg_end[idx, 0]
        by = seg_end[idx, 1]
        abx = bx - ax
        aby = by - ay
        den = abx * abx + aby * aby
        den = np.where(den > 0.0, den, 1.0)
        t = np.clip(((px - ax) * abx + (py - ay) * aby) / den, 0.0, 1.0)
        cx = ax + t * abx
        cy = ay + t * aby
        d2 = (px - cx) * (px - cx) + (py - cy) * (py - cy)
        out2 = np.minimum(out2, d2)
    return np.sqrt(out2)


def shoreline_distances(x: np.ndarray, y: np.ndarray, shorelines: ShorelineSet) -> tuple[np.ndarray, np.ndarray]:
    east_start, east_end = flatten_line_segments(shorelines.east)
    west_start, west_end = flatten_line_segments(shorelines.west)
    east_dist = point_to_segments_distance_chunked(x, y, east_start, east_end)
    west_dist = point_to_segments_distance_chunked(x, y, west_start, west_end)
    return east_dist, west_dist


def classify_coastal_points(
    b0: np.ndarray,
    sea_level: float,
    east_distance: np.ndarray,
    west_distance: np.ndarray,
    corridor: Corridor,
    equality_tolerance_m: float = 1.0e-9,
) -> dict[str, np.ndarray]:
    side = np.full(b0.shape, "outside", dtype=object)
    shoreline_distance = np.minimum(east_distance, west_distance)
    equal = np.isfinite(east_distance) & np.isfinite(west_distance) & (
        np.abs(east_distance - west_distance) <= equality_tolerance_m
    )
    east_nearer = east_distance < west_distance
    west_nearer = west_distance < east_distance
    side[east_nearer] = "east"
    side[west_nearer] = "west"
    side[equal] = "ambiguous"

    static_zone = np.full(b0.shape, "outside", dtype=object)
    finite_b0 = np.isfinite(b0)
    side_valid = (side == "east") | (side == "west")
    static_water = finite_b0 & (b0 < sea_level)
    static_land = finite_b0 & (b0 >= sea_level)
    seaward = side_valid & static_water & (shoreline_distance <= corridor.seaward_m)
    landward = side_valid & static_land & (shoreline_distance <= corridor.landward_m)
    east_corridor = (
        (static_water & (east_distance <= corridor.seaward_m))
        | (static_land & (east_distance <= corridor.landward_m))
    )
    west_corridor = (
        (static_water & (west_distance <= corridor.seaward_m))
        | (static_land & (west_distance <= corridor.landward_m))
    )
    overlap_resolution = (
        np.isfinite(east_distance)
        & np.isfinite(west_distance)
        & east_corridor
        & west_corridor
        & ~equal
    )
    static_zone[seaward] = "seaward"
    static_zone[landward] = "landward"
    static_zone[side == "ambiguous"] = "ambiguous"
    side[(side_valid) & (static_zone == "outside")] = "outside"
    return {
        "side": side,
        "static_zone": static_zone,
        "shoreline_distance": shoreline_distance,
        "east_distance": east_distance,
        "west_distance": west_distance,
        "overlap_resolution": overlap_resolution,
        "overlap_resolution_count": np.asarray([int(np.count_nonzero(overlap_resolution))], dtype=np.int64),
    }


def zone_membership(side: np.ndarray, static_zone: np.ndarray, dynamic_wet: np.ndarray, target_side: str, zone: str) -> np.ndarray:
    base = side == target_side
    if zone == "seaward":
        return base & (static_zone == "seaward")
    if zone == "landward_inundated":
        return base & (static_zone == "landward") & dynamic_wet
    if zone == "combined_coastal":
        return base & ((static_zone == "seaward") | ((static_zone == "landward") & dynamic_wet))
    raise ValueError(f"Unknown zone: {zone}")


def get_default_water_m(case: dict[str, Any]) -> float:
    threshold = finite_number(case.get("layers", {}).get("water", {}).get("default_m"))
    return threshold if threshold is not None else 0.30


def get_water_dry_tolerance(case: dict[str, Any]) -> float:
    value = finite_number(case.get("processing", {}).get("water_surface", {}).get("dry_tolerance"))
    return value if value is not None else WATER_DRY_TOLERANCE_FALLBACK


def get_velocity_arrow_options(case: dict[str, Any]) -> ArrowOptions:
    configured = case.get("layers", {}).get("water", {}).get("analysis_overlays", {}).get("velocity", {})
    stride_value = js_number_or_fallback(configured.get("arrow_stride"), VELOCITY_ARROW_STRIDE)
    scale_value = js_number_or_fallback(configured.get("arrow_scale"), VELOCITY_ARROW_SCALE)
    max_count_value = js_number_or_fallback(configured.get("arrow_max_count"), VELOCITY_ARROW_MAX_COUNT)
    min_speed_value = js_number_or_fallback(configured.get("arrow_min_speed"), VELOCITY_ARROW_MIN_SPEED)
    stride = max(1, js_round(stride_value))
    scale = max(0.0, float(scale_value))
    max_count = max(1, js_round(max_count_value))
    min_speed = max(0.0, float(min_speed_value))

    detail = case.get("processing", {}).get("water_surface", {}).get("coastal_detail", {})
    spacings = [
        finite_number(detail.get("row_spacing_m")),
        finite_number(detail.get("col_spacing_m")),
    ]
    positive_spacings = [value for value in spacings if value is not None and value > 0.0]
    cell_scale = min(positive_spacings) if positive_spacings else 1.0
    return ArrowOptions(stride, scale, max_count, min_speed, float(cell_scale))


def get_velocity_colorbar_range(case: dict[str, Any]) -> tuple[float, float]:
    configured = finite_pair_range(
        case.get("layers", {}).get("water", {}).get("analysis_overlays", {}).get("velocity", {}).get("range")
    )
    if configured is None:
        return float("nan"), float("nan")
    return 0.0, max(abs(configured[0]), abs(configured[1]), 1.0e-12)


def visible_point_mask_from_water_m(quads: np.ndarray, arrays: dict[str, np.ndarray], water_m: float) -> np.ndarray:
    m = arrays["m"]
    quad_m = m[quads]
    keep_cells = (
        arrays["valid_cells"]
        & np.all(np.isfinite(quad_m), axis=1)
        & np.all(quad_m <= float(water_m), axis=1)
    )
    point_mask = np.zeros(m.shape[0], dtype=bool)
    if np.any(keep_cells):
        point_mask[quads[keep_cells].ravel()] = True
    return point_mask


def build_velocity_candidates(
    visible_points: np.ndarray,
    arrays: dict[str, np.ndarray],
    options: ArrowOptions,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    u = arrays["u"]
    v = arrays["v"]
    for point_id in range(0, visible_points.size, options.stride):
        if not visible_points[point_id]:
            continue
        speed = math.hypot(float(u[point_id]), float(v[point_id]))
        if math.isfinite(speed) and speed >= options.min_speed:
            candidates.append(Candidate(point_id, float(speed)))
    return candidates


def build_velocity_candidate_arrays(
    visible_points: np.ndarray,
    arrays: dict[str, np.ndarray],
    options: ArrowOptions,
) -> tuple[np.ndarray, np.ndarray]:
    point_ids = np.arange(0, visible_points.size, options.stride, dtype=np.int64)
    if point_ids.size == 0:
        return point_ids, np.asarray([], dtype=np.float64)
    point_ids = point_ids[visible_points[point_ids]]
    if point_ids.size == 0:
        return point_ids, np.asarray([], dtype=np.float64)
    speeds = np.hypot(arrays["u"][point_ids], arrays["v"][point_ids]).astype(np.float64, copy=False)
    keep = np.isfinite(speeds) & (speeds >= options.min_speed)
    return point_ids[keep], speeds[keep]


def spatially_sample_velocity_candidates(
    candidates: list[Candidate],
    x: np.ndarray,
    y: np.ndarray,
    max_count: int,
) -> list[Candidate]:
    if len(candidates) <= int(max_count):
        return candidates
    point_ids = np.asarray([candidate.point_id for candidate in candidates], dtype=np.int64)
    speeds = np.asarray([candidate.speed for candidate in candidates], dtype=np.float64)
    sampled_ids, sampled_speeds = spatially_sample_velocity_candidate_arrays(point_ids, speeds, x, y, max_count)
    return [
        Candidate(int(point_id), float(speed))
        for point_id, speed in zip(sampled_ids, sampled_speeds)
    ]


def spatially_sample_velocity_candidate_arrays(
    point_ids: np.ndarray,
    speeds: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    max_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    if point_ids.size <= int(max_count):
        return point_ids, speeds
    cx = x[point_ids]
    cy = y[point_ids]
    xmin = float(np.min(cx))
    xmax = float(np.max(cx))
    ymin = float(np.min(cy))
    ymax = float(np.max(cy))
    width = max(xmax - xmin, 1.0)
    height = max(ymax - ymin, 1.0)
    column_count = max(1, math.ceil(math.sqrt(float(max_count) * width / height)))
    row_count = max(1, math.floor(float(max_count) / column_count))
    columns = np.minimum(
        column_count - 1,
        np.floor(column_count * (cx - xmin) / width).astype(np.int64),
    )
    rows = np.minimum(
        row_count - 1,
        np.floor(row_count * (cy - ymin) / height).astype(np.int64),
    )
    keys = rows * column_count + columns
    order = np.lexsort((point_ids, -speeds, keys))
    sorted_keys = keys[order]
    first_in_bucket = np.empty(sorted_keys.shape, dtype=bool)
    first_in_bucket[0] = True
    first_in_bucket[1:] = sorted_keys[1:] != sorted_keys[:-1]
    selected_order = order[first_in_bucket]
    final_order = np.argsort(point_ids[selected_order])
    selected_order = selected_order[final_order]
    return point_ids[selected_order], speeds[selected_order]


def colorbar_fraction(speed: float, colorbar_range: tuple[float, float]) -> float:
    vmin, vmax = colorbar_range
    if not math.isfinite(vmin) or not math.isfinite(vmax) or vmax <= vmin:
        return float("nan")
    return float(np.clip((float(speed) - vmin) / (vmax - vmin), 0.0, 1.0))


def colorbar_saturated(speed: float, colorbar_range: tuple[float, float]) -> bool:
    _, vmax = colorbar_range
    return bool(math.isfinite(vmax) and float(speed) >= vmax)


def safe_ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0.0:
        return float("nan")
    return numerator / denominator


def selected_frame_indices_for_window(times: list[float], requested_time_min_s: float) -> list[int]:
    return [index for index, time_s in enumerate(times) if float(time_s) >= float(requested_time_min_s)]


def effective_window_times(times: list[float], frame_indices: list[int]) -> tuple[float, float]:
    if not frame_indices:
        return float("nan"), float("nan")
    return float(times[frame_indices[0]]), float(times[frame_indices[-1]])


def empty_frame_row(
    case_id: str,
    requested_time_min_s: float,
    effective_first_time_s: float,
    frame_index: int,
    time_s: float,
    corridor: Corridor,
    side: str,
    zone: str,
    candidate_count: int,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "requested_time_min_s": requested_time_min_s,
        "effective_first_selected_time_s": effective_first_time_s,
        "frame_index": frame_index,
        "time_s": time_s,
        "seaward_distance_m": corridor.seaward_m,
        "landward_distance_m": corridor.landward_m,
        "side": side,
        "zone": zone,
        "candidate_count_before_global_sampling": candidate_count,
        "displayed_arrow_count": 0,
        "displayed_speed_max_mps": float("nan"),
        "displayed_top10_mean_speed_mps": float("nan"),
        "displayed_top10_count": 0,
        "displayed_max_point_id": -1,
        "displayed_max_x_m": float("nan"),
        "displayed_max_y_m": float("nan"),
        "displayed_max_u_mps": float("nan"),
        "displayed_max_v_mps": float("nan"),
        "displayed_max_h_m": float("nan"),
        "displayed_max_m": float("nan"),
        "displayed_max_b0_m": float("nan"),
        "displayed_max_b_current_m": float("nan"),
        "displayed_max_shoreline_distance_m": float("nan"),
        "displayed_max_static_zone": "",
        "displayed_max_dynamic_wet": False,
        "displayed_max_source_topo_id": "",
        "displayed_max_native_dx_m": float("nan"),
        "displayed_max_native_dy_m": float("nan"),
        "displayed_max_effective_resolution_m": float("nan"),
        "displayed_max_source_precedence_rank": "",
        "colorbar_fraction": float("nan"),
        "colorbar_saturated": False,
    }


def summarize_arrow_group(
    case_id: str,
    requested_time_min_s: float,
    effective_first_time_s: float,
    frame_index: int,
    time_s: float,
    corridor: Corridor,
    side: str,
    zone: str,
    candidate_count: int,
    arrows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not arrows:
        return empty_frame_row(
            case_id, requested_time_min_s, effective_first_time_s, frame_index, time_s,
            corridor, side, zone, candidate_count
        )
    sorted_arrows = sorted(arrows, key=lambda item: item["speed_mps"], reverse=True)
    top10 = sorted_arrows[:10]
    max_arrow = sorted_arrows[0]
    return {
        "case_id": case_id,
        "requested_time_min_s": requested_time_min_s,
        "effective_first_selected_time_s": effective_first_time_s,
        "frame_index": frame_index,
        "time_s": time_s,
        "seaward_distance_m": corridor.seaward_m,
        "landward_distance_m": corridor.landward_m,
        "side": side,
        "zone": zone,
        "candidate_count_before_global_sampling": candidate_count,
        "displayed_arrow_count": len(arrows),
        "displayed_speed_max_mps": max_arrow["speed_mps"],
        "displayed_top10_mean_speed_mps": float(np.mean([item["speed_mps"] for item in top10])),
        "displayed_top10_count": len(top10),
        "displayed_max_point_id": max_arrow["point_id"],
        "displayed_max_x_m": max_arrow["x_m"],
        "displayed_max_y_m": max_arrow["y_m"],
        "displayed_max_u_mps": max_arrow["u_mps"],
        "displayed_max_v_mps": max_arrow["v_mps"],
        "displayed_max_h_m": max_arrow["h_m"],
        "displayed_max_m": max_arrow["m"],
        "displayed_max_b0_m": max_arrow["b0_m"],
        "displayed_max_b_current_m": max_arrow["b_current_m"],
        "displayed_max_shoreline_distance_m": max_arrow["shoreline_distance_m"],
        "displayed_max_static_zone": max_arrow["static_zone"],
        "displayed_max_dynamic_wet": max_arrow["dynamic_wet"],
        "displayed_max_source_topo_id": max_arrow["source_topo_id"],
        "displayed_max_native_dx_m": max_arrow["native_dx_m"],
        "displayed_max_native_dy_m": max_arrow["native_dy_m"],
        "displayed_max_effective_resolution_m": max_arrow["effective_resolution_m"],
        "displayed_max_source_precedence_rank": max_arrow["source_precedence_rank"],
        "colorbar_fraction": max_arrow["colorbar_fraction"],
        "colorbar_saturated": max_arrow["colorbar_saturated"],
    }


def annotate_sampled_point(
    point_id: int,
    speed: float,
    frame_index: int,
    time_s: float,
    arrays: dict[str, np.ndarray],
    x: np.ndarray,
    y: np.ndarray,
    b0: np.ndarray,
    class_info: dict[str, np.ndarray],
    dry_tolerance: float,
    colorbar_range: tuple[float, float],
    source_topography: SourceTopography | None,
) -> dict[str, Any]:
    z = float(arrays["z"][point_id])
    h = float(arrays["h"][point_id])
    m = float(arrays["m"][point_id])
    b_current = z - h
    dynamic_wet = bool(math.isfinite(h) and h >= dry_tolerance)
    return {
        "frame_index": frame_index,
        "time_s": time_s,
        "point_id": int(point_id),
        "x_m": float(x[point_id]),
        "y_m": float(y[point_id]),
        "speed_mps": float(speed),
        "u_mps": float(arrays["u"][point_id]),
        "v_mps": float(arrays["v"][point_id]),
        "h_m": h,
        "m": m,
        "b0_m": float(b0[point_id]),
        "b_current_m": b_current,
        "side": str(class_info["side"][point_id]),
        "static_zone": str(class_info["static_zone"][point_id]),
        "shoreline_distance_m": float(class_info["shoreline_distance"][point_id]),
        "dynamic_wet": dynamic_wet,
        "source_topo_id": source_topography.source_topo_id if source_topography is not None else "",
        "native_dx_m": source_topography.native_dx_m if source_topography is not None else float("nan"),
        "native_dy_m": source_topography.native_dy_m if source_topography is not None else float("nan"),
        "effective_resolution_m": source_topography.effective_resolution_m if source_topography is not None else float("nan"),
        "source_precedence_rank": source_topography.source_precedence_rank if source_topography is not None else "",
        "colorbar_fraction": colorbar_fraction(speed, colorbar_range),
        "colorbar_saturated": colorbar_saturated(speed, colorbar_range),
    }


def update_window_hotspot(
    store: dict[tuple[float, float, float, str, str, int], dict[str, Any]],
    requested_time_min_s: float,
    corridor: Corridor,
    side: str,
    zone: str,
    arrow: dict[str, Any],
) -> None:
    key = (requested_time_min_s, corridor.seaward_m, corridor.landward_m, side, zone, int(arrow["point_id"]))
    current = store.get(key)
    if current is None:
        record = dict(arrow)
        record["displayed_frame_count"] = 1
        store[key] = record
        return
    current["displayed_frame_count"] += 1
    if arrow["speed_mps"] > current["speed_mps"]:
        count = current["displayed_frame_count"]
        record = dict(arrow)
        record["displayed_frame_count"] = count
        store[key] = record


def build_hotspot_rows(
    case_id: str,
    hotspot_store: dict[tuple[float, float, float, str, str, int], dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = sorted({key[:5] for key in hotspot_store})
    for requested, seaward, landward, side, zone in groups:
        records = [
            record for key, record in hotspot_store.items()
            if key[:5] == (requested, seaward, landward, side, zone)
        ]
        records.sort(key=lambda item: (-float(item["speed_mps"]), int(item["point_id"])))
        for rank, record in enumerate(records[:top_n], start=1):
            rows.append({
                "case_id": case_id,
                "requested_time_min_s": requested,
                "seaward_distance_m": seaward,
                "landward_distance_m": landward,
                "side": side,
                "zone": zone,
                "rank": rank,
                "point_id": record["point_id"],
                "max_displayed_speed_mps": record["speed_mps"],
                "max_frame_index": record["frame_index"],
                "max_time_s": record["time_s"],
                "displayed_frame_count": record["displayed_frame_count"],
                "x_m": record["x_m"],
                "y_m": record["y_m"],
                "shoreline_distance_m": record["shoreline_distance_m"],
                "b0_m": record["b0_m"],
                "b_current_at_max_m": record["b_current_m"],
                "h_at_max_m": record["h_m"],
                "dynamic_wet_at_max": record["dynamic_wet"],
                "u_at_max_mps": record["u_mps"],
                "v_at_max_mps": record["v_mps"],
                "source_topo_id": record["source_topo_id"],
                "native_dx_m": record["native_dx_m"],
                "native_dy_m": record["native_dy_m"],
                "effective_resolution_m": record["effective_resolution_m"],
                "source_precedence_rank": record["source_precedence_rank"],
                "colorbar_fraction_at_max": record["colorbar_fraction"],
                "colorbar_saturated_at_max": record["colorbar_saturated"],
            })
    return rows


def finite_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = float(row[field])
        if math.isfinite(value):
            values.append(value)
    return values


def median_or_nan(values: list[float]) -> float:
    return float(np.median(values)) if values else float("nan")


def mean_or_nan(values: list[float]) -> float:
    return float(np.mean(values)) if values else float("nan")


def build_summary_rows(
    case_id: str,
    frame_rows: list[dict[str, Any]],
    hotspot_rows: list[dict[str, Any]],
    time_windows: dict[float, tuple[list[int], float, float]],
    corridors: list[Corridor],
    top_n: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for requested, (frame_indices, effective_first, effective_last) in time_windows.items():
        for corridor in corridors:
            for zone in ZONES:
                east_rows = [
                    row for row in frame_rows
                    if row["requested_time_min_s"] == requested
                    and row["seaward_distance_m"] == corridor.seaward_m
                    and row["landward_distance_m"] == corridor.landward_m
                    and row["zone"] == zone
                    and row["side"] == "east"
                ]
                west_rows = [
                    row for row in frame_rows
                    if row["requested_time_min_s"] == requested
                    and row["seaward_distance_m"] == corridor.seaward_m
                    and row["landward_distance_m"] == corridor.landward_m
                    and row["zone"] == zone
                    and row["side"] == "west"
                ]
                both = east_only = west_only = neither = 0
                east_max_gt = west_max_gt = east_top10_gt = west_top10_gt = 0
                for east_row, west_row in zip(east_rows, west_rows):
                    east_has = int(east_row["displayed_arrow_count"]) > 0
                    west_has = int(west_row["displayed_arrow_count"]) > 0
                    if east_has and west_has:
                        both += 1
                        em = float(east_row["displayed_speed_max_mps"])
                        wm = float(west_row["displayed_speed_max_mps"])
                        if math.isfinite(em) and math.isfinite(wm):
                            if em > wm:
                                east_max_gt += 1
                            elif wm > em:
                                west_max_gt += 1
                        et = float(east_row["displayed_top10_mean_speed_mps"])
                        wt = float(west_row["displayed_top10_mean_speed_mps"])
                        if math.isfinite(et) and math.isfinite(wt):
                            if et > wt:
                                east_top10_gt += 1
                            elif wt > et:
                                west_top10_gt += 1
                    elif east_has:
                        east_only += 1
                    elif west_has:
                        west_only += 1
                    else:
                        neither += 1
                east_hot = [
                    row for row in hotspot_rows
                    if row["requested_time_min_s"] == requested
                    and row["seaward_distance_m"] == corridor.seaward_m
                    and row["landward_distance_m"] == corridor.landward_m
                    and row["zone"] == zone
                    and row["side"] == "east"
                    and int(row["rank"]) <= top_n
                ]
                west_hot = [
                    row for row in hotspot_rows
                    if row["requested_time_min_s"] == requested
                    and row["seaward_distance_m"] == corridor.seaward_m
                    and row["landward_distance_m"] == corridor.landward_m
                    and row["zone"] == zone
                    and row["side"] == "west"
                    and int(row["rank"]) <= top_n
                ]
                east_hot_speeds = finite_values(east_hot, "max_displayed_speed_mps")
                west_hot_speeds = finite_values(west_hot, "max_displayed_speed_mps")
                east_global = max(east_hot_speeds) if east_hot_speeds else float("nan")
                west_global = max(west_hot_speeds) if west_hot_speeds else float("nan")
                east_frame_max = finite_values(east_rows, "displayed_speed_max_mps")
                west_frame_max = finite_values(west_rows, "displayed_speed_max_mps")
                east_frame_top10 = finite_values(east_rows, "displayed_top10_mean_speed_mps")
                west_frame_top10 = finite_values(west_rows, "displayed_top10_mean_speed_mps")
                east_hot_median = median_or_nan(east_hot_speeds)
                west_hot_median = median_or_nan(west_hot_speeds)
                east_hot_mean = mean_or_nan(east_hot_speeds)
                west_hot_mean = mean_or_nan(west_hot_speeds)
                east_median_frame_max = median_or_nan(east_frame_max)
                west_median_frame_max = median_or_nan(west_frame_max)
                east_mean_frame_max = mean_or_nan(east_frame_max)
                west_mean_frame_max = mean_or_nan(west_frame_max)
                east_median_top10 = median_or_nan(east_frame_top10)
                west_median_top10 = median_or_nan(west_frame_top10)
                east_mean_top10 = mean_or_nan(east_frame_top10)
                west_mean_top10 = mean_or_nan(west_frame_top10)
                rows.append({
                    "case_id": case_id,
                    "requested_time_min_s": requested,
                    "effective_first_selected_time_s": effective_first,
                    "effective_last_selected_time_s": effective_last,
                    "selected_frame_count": len(frame_indices),
                    "seaward_distance_m": corridor.seaward_m,
                    "landward_distance_m": corridor.landward_m,
                    "zone": zone,
                    "frames_with_both_east_and_west": both,
                    "frames_east_only": east_only,
                    "frames_west_only": west_only,
                    "frames_neither": neither,
                    "east_global_max_mps": east_global,
                    "west_global_max_mps": west_global,
                    "east_west_global_max_ratio": safe_ratio(east_global, west_global),
                    "east_median_frame_max_mps": east_median_frame_max,
                    "west_median_frame_max_mps": west_median_frame_max,
                    "east_west_median_frame_max_ratio": safe_ratio(east_median_frame_max, west_median_frame_max),
                    "east_mean_frame_max_mps": east_mean_frame_max,
                    "west_mean_frame_max_mps": west_mean_frame_max,
                    "east_west_mean_frame_max_ratio": safe_ratio(east_mean_frame_max, west_mean_frame_max),
                    "east_median_frame_top10_mean_mps": east_median_top10,
                    "west_median_frame_top10_mean_mps": west_median_top10,
                    "east_west_median_frame_top10_ratio": safe_ratio(east_median_top10, west_median_top10),
                    "east_mean_frame_top10_mean_mps": east_mean_top10,
                    "west_mean_frame_top10_mean_mps": west_mean_top10,
                    "east_west_mean_frame_top10_ratio": safe_ratio(east_mean_top10, west_mean_top10),
                    "frames_east_max_gt_west": east_max_gt,
                    "frames_west_max_gt_east": west_max_gt,
                    "fraction_frames_east_max_gt_west": safe_ratio(float(east_max_gt), float(both)),
                    "frames_east_top10_gt_west": east_top10_gt,
                    "frames_west_top10_gt_east": west_top10_gt,
                    "fraction_frames_east_top10_gt_west": safe_ratio(float(east_top10_gt), float(both)),
                    "east_topN_unique_median_max_mps": east_hot_median,
                    "west_topN_unique_median_max_mps": west_hot_median,
                    "east_west_topN_unique_median_ratio": safe_ratio(east_hot_median, west_hot_median),
                    "east_topN_unique_mean_max_mps": east_hot_mean,
                    "west_topN_unique_mean_max_mps": west_hot_mean,
                    "east_west_topN_unique_mean_ratio": safe_ratio(east_hot_mean, west_hot_mean),
                    "east_topN_recurrent_ge_2_frames": sum(int(row["displayed_frame_count"]) >= 2 for row in east_hot),
                    "west_topN_recurrent_ge_2_frames": sum(int(row["displayed_frame_count"]) >= 2 for row in west_hot),
                })
    return rows


def process_case(
    case_dir: Path,
    shorelines: ShorelineSet,
    source_topography: SourceTopography | None,
    water_m_override: float | None,
    top_n: int,
    time_min_values: list[float],
    corridors: list[Corridor],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    case_dir = Path(case_dir)
    case_path = case_dir / "case.json"
    case = load_json(case_path)
    compact = require_water_compact(case, case_path)
    case_id = str(case.get("id") or case_dir.name)
    times = [float(value) for value in case.get("time", {}).get("values", [])]
    if not times:
        raise ValueError(f"{case_path}: case.json time.values is required")
    frame_count = int(case.get("time", {}).get("frame_count", len(times)))
    if frame_count != len(times):
        raise ValueError(f"{case_path}: time.frame_count does not match len(time.values)")
    time_windows: dict[float, tuple[list[int], float, float]] = {}
    for requested in time_min_values:
        frame_indices = selected_frame_indices_for_window(times, requested)
        if not frame_indices:
            raise ValueError(f"{case_id}: no frames satisfy time_s >= {requested:g}")
        first, last = effective_window_times(times, frame_indices)
        time_windows[float(requested)] = (frame_indices, first, last)

    x, y, quads = load_template(case_dir, compact)
    options = get_velocity_arrow_options(case)
    colorbar_range = get_velocity_colorbar_range(case)
    dry_tolerance = get_water_dry_tolerance(case)
    sea_level = float(case.get("processing", {}).get("sea_level", 0.0))
    water_m = float(water_m_override) if water_m_override is not None else get_default_water_m(case)

    frame0 = load_frame_arrays(case_dir, compact, 0)
    if source_topography is not None:
        b0 = sample_source_topography(source_topography, x, y)
    else:
        b0 = static_b0_from_frame0(frame0)
    east_distance, west_distance = shoreline_distances(x, y, shorelines)
    class_by_corridor = {
        (corridor.seaward_m, corridor.landward_m): classify_coastal_points(
            b0, sea_level, east_distance, west_distance, corridor
        )
        for corridor in corridors
    }

    frame_summary_rows: list[dict[str, Any]] = []
    hotspot_store: dict[tuple[float, float, float, str, str, int], dict[str, Any]] = {}
    required_frames = sorted(set(index for frames, _, _ in time_windows.values() for index in frames))
    for frame_index in required_frames:
        arrays = frame0 if frame_index == 0 else load_frame_arrays(case_dir, compact, frame_index)
        arrays = dict(arrays)
        arrays["_sea_level"] = np.asarray([sea_level], dtype=np.float64)
        visible_points = visible_point_mask_from_water_m(quads, arrays, water_m)
        candidate_ids, candidate_speeds = build_velocity_candidate_arrays(visible_points, arrays, options)
        sampled_ids, sampled_speeds = spatially_sample_velocity_candidate_arrays(
            candidate_ids,
            candidate_speeds,
            x,
            y,
            options.max_count,
        )
        candidate_count = int(candidate_ids.size)
        sampled_by_corridor: dict[tuple[float, float], list[dict[str, Any]]] = {}
        dynamic_wet_all = np.isfinite(arrays["h"]) & (arrays["h"] >= dry_tolerance)
        for corridor in corridors:
            info = class_by_corridor[(corridor.seaward_m, corridor.landward_m)]
            info = dict(info)
            info["dynamic_wet"] = dynamic_wet_all
            arrows: list[dict[str, Any]] = []
            for point_id, speed in zip(sampled_ids, sampled_speeds):
                arrows.append(
                    annotate_sampled_point(
                        int(point_id), float(speed), frame_index, times[frame_index],
                        arrays, x, y, b0, info, dry_tolerance, colorbar_range, source_topography
                    )
                )
            sampled_by_corridor[(corridor.seaward_m, corridor.landward_m)] = arrows

        for requested, (window_frames, effective_first, _) in time_windows.items():
            if frame_index not in window_frames:
                continue
            for corridor in corridors:
                info = class_by_corridor[(corridor.seaward_m, corridor.landward_m)]
                for side in SIDES:
                    for zone in ZONES:
                        group = [
                            arrow for arrow in sampled_by_corridor[(corridor.seaward_m, corridor.landward_m)]
                            if arrow["side"] == side
                            and (
                                (zone == "seaward" and arrow["static_zone"] == "seaward")
                                or (zone == "landward_inundated" and arrow["static_zone"] == "landward" and arrow["dynamic_wet"])
                                or (zone == "combined_coastal" and (
                                    arrow["static_zone"] == "seaward"
                                    or (arrow["static_zone"] == "landward" and arrow["dynamic_wet"])
                                ))
                            )
                        ]
                        frame_summary_rows.append(
                            summarize_arrow_group(
                                case_id, requested, effective_first, frame_index, times[frame_index],
                                corridor, side, zone, candidate_count, group
                            )
                        )
                        for arrow in group:
                            update_window_hotspot(hotspot_store, requested, corridor, side, zone, arrow)

    hotspot_rows = build_hotspot_rows(case_id, hotspot_store, top_n)
    summary_rows = build_summary_rows(case_id, frame_summary_rows, hotspot_rows, time_windows, corridors, top_n)
    corridor_qc: list[dict[str, Any]] = []
    for corridor in corridors:
        info = class_by_corridor[(corridor.seaward_m, corridor.landward_m)]
        ambiguous_mask = (info["side"] == "ambiguous") & (info["shoreline_distance"] <= max(
            corridor.seaward_m,
            corridor.landward_m,
        ))
        overlap_mask = info["overlap_resolution"]
        corridor_qc.append({
            "case_id": case_id,
            "seaward_distance_m": corridor.seaward_m,
            "landward_distance_m": corridor.landward_m,
            "overlap_resolution_count": int(np.count_nonzero(overlap_mask)),
            "ambiguous_count": int(np.count_nonzero(ambiguous_mask)),
            "overlap_point_ids": np.flatnonzero(overlap_mask)[:100].astype(int).tolist(),
            "ambiguous_point_ids": np.flatnonzero(ambiguous_mask)[:100].astype(int).tolist(),
        })

    qc = {
        "case_id": case_id,
        "b0_finite_count": int(np.count_nonzero(np.isfinite(b0))),
        "point_count": int(x.size),
        "overlap_resolution_count": int(sum(item["overlap_resolution_count"] for item in corridor_qc)),
        "corridors": corridor_qc,
        "x": x,
        "y": y,
        "b0": b0,
        "east_distance": east_distance,
        "west_distance": west_distance,
    }
    return frame_summary_rows, hotspot_rows, summary_rows, qc


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


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fields})


def git_commit_hash(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def viewer_function_status(repo_root: Path) -> list[str]:
    source_path = repo_root / VIEWER_SOURCE_PATH
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError:
        return [f"{name}:missing_source" for name in VIEWER_FUNCTIONS]
    status = []
    for name in VIEWER_FUNCTIONS:
        status.append(f"{name}:{'found' if f'function {name}' in source else 'semantic-equivalent-required'}")
    return status


def validation_text(summary_rows: list[dict[str, Any]], repo_root: Path, qcs: list[dict[str, Any]]) -> str:
    lines = [
        "Audit target: viewer-displayed current-frame Velocity arrows",
        "Values: pointwise depth-averaged flow speed",
        "Spatial domain: shoreline-following coastal corridors",
        "Main corridor: 1000 m seaward and 500 m landward",
        "Landward primary statistics include dynamically wet/inundated points only",
        "Sampling reproduced globally before shoreline classification",
        "No area weighting",
        "No time integration",
        "No propagation-speed interpretation",
        f"Git commit hash: {git_commit_hash(repo_root)}",
        f"Viewer source path: {VIEWER_SOURCE_PATH}",
        "Viewer functions: " + ", ".join(viewer_function_status(repo_root)),
        f"QC overlap-resolution count: {sum(int(qc.get('overlap_resolution_count', 0)) for qc in qcs)}",
        "",
    ]
    fields = (
        "case_id",
        "requested_time_min_s",
        "seaward_distance_m",
        "landward_distance_m",
        "zone",
        "east_global_max_mps",
        "west_global_max_mps",
        "east_west_global_max_ratio",
        "east_median_frame_top10_mean_mps",
        "west_median_frame_top10_mean_mps",
        "east_west_median_frame_top10_ratio",
        "frames_east_top10_gt_west",
        "frames_west_top10_gt_east",
    )
    lines.append("\t".join(fields))
    for row in summary_rows[:120]:
        lines.append("\t".join(str(csv_value(row[field])) for field in fields))
    return "\n".join(lines) + "\n"


def offset_line_x(line: np.ndarray, offset: float) -> np.ndarray:
    out = np.asarray(line, dtype=np.float64).copy()
    out[:, 0] += float(offset)
    return out


def line_feature(side: str, role: str, coords: np.ndarray, **props: Any) -> dict[str, Any]:
    properties = {"side": side, "role": role}
    properties.update(props)
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "LineString",
            "coordinates": [[float(x), float(y)] for x, y in coords],
        },
    }


def write_qc_geojson(path: Path, shorelines: ShorelineSet, main_corridor: Corridor, qcs: list[dict[str, Any]]) -> None:
    features: list[dict[str, Any]] = []
    for side, lines in (("east", shorelines.east), ("west", shorelines.west)):
        for idx, line in enumerate(lines):
            features.append(line_feature(side, "shoreline", line, part=idx))
            if side == "east":
                features.append(line_feature(side, "seaward_boundary", offset_line_x(line, -main_corridor.seaward_m), part=idx))
                features.append(line_feature(side, "landward_boundary", offset_line_x(line, main_corridor.landward_m), part=idx))
            else:
                features.append(line_feature(side, "seaward_boundary", offset_line_x(line, main_corridor.seaward_m), part=idx))
                features.append(line_feature(side, "landward_boundary", offset_line_x(line, -main_corridor.landward_m), part=idx))
    for case_id, x, y in (
        ("aqaba_lsa_c10_angm25", 85414.0, 3155833.0),
        ("aqaba_lsd_nc8_angm40", 80312.0, 3143258.0),
    ):
        features.append({
            "type": "Feature",
            "properties": {"role": "acceptance_point", "case_id": case_id},
            "geometry": {"type": "Point", "coordinates": [x, y]},
        })
    for qc in qcs:
        x = qc.get("x")
        y = qc.get("y")
        if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
            continue
        for corridor_qc in qc.get("corridors", []):
            is_main = (
                float(corridor_qc["seaward_distance_m"]) == float(main_corridor.seaward_m)
                and float(corridor_qc["landward_distance_m"]) == float(main_corridor.landward_m)
            )
            if not is_main:
                continue
            for role, ids_key in (
                ("overlap_resolution_point", "overlap_point_ids"),
                ("ambiguous_point", "ambiguous_point_ids"),
            ):
                for point_id in corridor_qc.get(ids_key, []):
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "role": role,
                            "case_id": qc["case_id"],
                            "point_id": int(point_id),
                            "seaward_distance_m": corridor_qc["seaward_distance_m"],
                            "landward_distance_m": corridor_qc["landward_distance_m"],
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [float(x[int(point_id)]), float(y[int(point_id)])],
                        },
                    })
    geojson = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": f"EPSG:{shorelines.crs_epsg or 32637}"}},
        "properties": {
            "qc": [
                {
                    "case_id": qc.get("case_id"),
                    "point_count": qc.get("point_count"),
                    "b0_finite_count": qc.get("b0_finite_count"),
                    "overlap_resolution_count": qc.get("overlap_resolution_count"),
                    "corridors": qc.get("corridors", []),
                }
                for qc in qcs
            ]
        },
        "features": features,
    }
    path.write_text(json.dumps(geojson, indent=2), encoding="utf-8")


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_simple_qc_pdf(path: Path, shorelines: ShorelineSet, main_corridor: Corridor) -> None:
    all_points = np.vstack([line for line in shorelines.east + shorelines.west])
    xmin, ymin = np.min(all_points, axis=0)
    xmax, ymax = np.max(all_points, axis=0)
    width, height = 792.0, 612.0
    margin = 45.0
    scale = min((width - 2 * margin) / max(xmax - xmin, 1.0), (height - 2 * margin) / max(ymax - ymin, 1.0))

    def xy(point: np.ndarray) -> tuple[float, float]:
        return margin + (float(point[0]) - xmin) * scale, margin + (float(point[1]) - ymin) * scale

    ops: list[str] = ["0.8 w", "0 0 0 RG"]
    def draw_line(line: np.ndarray, color: str) -> None:
        ops.append(color)
        x0, y0 = xy(line[0])
        ops.append(f"{x0:.2f} {y0:.2f} m")
        for point in line[1:]:
            px, py = xy(point)
            ops.append(f"{px:.2f} {py:.2f} l")
        ops.append("S")
    for line in shorelines.east:
        draw_line(line, "0.85 0.1 0.1 RG")
        draw_line(offset_line_x(line, -main_corridor.seaward_m), "0.95 0.5 0.5 RG")
        draw_line(offset_line_x(line, main_corridor.landward_m), "0.55 0 0 RG")
    for line in shorelines.west:
        draw_line(line, "0.1 0.1 0.85 RG")
        draw_line(offset_line_x(line, main_corridor.seaward_m), "0.5 0.5 0.95 RG")
        draw_line(offset_line_x(line, -main_corridor.landward_m), "0 0 0.55 RG")
    ops.extend([
        "0 0 0 RG",
        "BT /F1 12 Tf 45 585 Td (Shoreline velocity QC: red=east, blue=west) Tj ET",
        f"BT /F1 10 Tf 45 568 Td ({pdf_escape(f'Main corridor: {main_corridor.seaward_m:g} m seaward, {main_corridor.landward_m:g} m landward')}) Tj ET",
        "BT /F1 10 Tf 700 550 Td (N) Tj ET",
        "700 520 m 700 545 l S",
        "696 539 m 700 545 l 704 539 l S",
        "45 40 m 145 40 l S",
        f"BT /F1 9 Tf 45 25 Td ({pdf_escape(f'{100/scale:.0f} m scale bar')}) Tj ET",
    ])
    content = "\n".join(ops).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode("ascii"))
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    path.write_bytes(bytes(data))


def prepare_output_dir(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    extras = [path.name for path in out_dir.iterdir() if path.name not in OUTPUT_FILES]
    if extras:
        raise ValueError(f"{out_dir}: contains files not produced by this audit: {', '.join(sorted(extras))}")


def write_outputs(
    out_dir: Path,
    frame_rows: list[dict[str, Any]],
    hotspot_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    repo_root: Path,
    shorelines: ShorelineSet,
    main_corridor: Corridor,
    qcs: list[dict[str, Any]],
) -> None:
    prepare_output_dir(out_dir)
    write_csv(out_dir / "frame_summary.csv", FRAME_SUMMARY_FIELDS, frame_rows)
    write_csv(out_dir / "hotspots.csv", HOTSPOT_FIELDS, hotspot_rows)
    write_csv(out_dir / "summary.csv", SUMMARY_FIELDS, summary_rows)
    write_qc_geojson(out_dir / "shoreline_mask_qc.geojson", shorelines, main_corridor, qcs)
    write_simple_qc_pdf(out_dir / "shoreline_mask_qc.pdf", shorelines, main_corridor)
    (out_dir / "validation.txt").write_text(validation_text(summary_rows, repo_root, qcs), encoding="utf-8")


def run_analysis(
    case_dirs: Iterable[Path],
    shorelines_path: Path,
    source_topography_provenance: Path | None,
    water_m: float | None,
    top_n: int,
    time_min_values: list[float],
    corridors: list[Corridor],
    out_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    shorelines = load_shorelines_geojson(Path(shorelines_path))
    source_topography = load_source_topography(source_topography_provenance)
    all_frame_rows: list[dict[str, Any]] = []
    all_hotspot_rows: list[dict[str, Any]] = []
    all_summary_rows: list[dict[str, Any]] = []
    all_qcs: list[dict[str, Any]] = []
    for case_dir in case_dirs:
        frame_rows, hotspot_rows, summary_rows, qc = process_case(
            Path(case_dir),
            shorelines,
            source_topography,
            water_m,
            top_n,
            time_min_values,
            corridors,
        )
        all_frame_rows.extend(frame_rows)
        all_hotspot_rows.extend(hotspot_rows)
        all_summary_rows.extend(summary_rows)
        all_qcs.append(qc)
    repo_root = Path(__file__).resolve().parents[1]
    write_outputs(
        Path(out_dir),
        all_frame_rows,
        all_hotspot_rows,
        all_summary_rows,
        repo_root,
        shorelines,
        corridors[0],
        all_qcs,
    )
    return all_frame_rows, all_hotspot_rows, all_summary_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze shoreline-following viewer-displayed Velocity arrows hotspots.",
    )
    parser.add_argument("--case", dest="case_dirs", action="append", required=True, type=Path)
    parser.add_argument("--shorelines", required=True, type=Path)
    parser.add_argument("--source-topography-provenance", type=Path, default=None)
    parser.add_argument("--water-m", type=float, default=None)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--time-min-s", nargs="+", type=float, required=True)
    parser.add_argument("--corridor", nargs=2, action="append", type=float, metavar=("SEAWARD_M", "LANDWARD_M"), required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.water_m is not None and not math.isfinite(args.water_m):
        parser.error("--water-m must be finite when provided")
    if args.top_n <= 0:
        parser.error("--top-n must be a positive integer")
    if any(not math.isfinite(value) for value in args.time_min_s):
        parser.error("--time-min-s values must be finite")
    args.corridors = []
    for seaward, landward in args.corridor:
        if not math.isfinite(seaward) or not math.isfinite(landward) or seaward <= 0 or landward < 0:
            parser.error("--corridor requires positive SEAWARD_M and non-negative LANDWARD_M")
        args.corridors.append(Corridor(float(seaward), float(landward)))
    return args


def main() -> int:
    args = parse_args()
    run_analysis(
        args.case_dirs,
        args.shorelines,
        args.source_topography_provenance,
        args.water_m,
        args.top_n,
        args.time_min_s,
        args.corridors,
        args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
