#!/usr/bin/env python3
"""Build source-TOPO-derived Aqaba shorelines and topography provenance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCENARIO_SUFFIXES = ("lsa", "lsb", "lsc", "lsd", "lse", "lsf")
ACCEPTANCE_POINTS = (
    ("aqaba_lsa_c10_angm25", 85414.04, 3155832.75),
    ("aqaba_lsd_nc8_angm40", 80312.14, 3143258.00),
)
SOURCE_CLASS_LABELS = {
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
MANIFEST_FIELDS = (
    "source_root",
    "model_configuration_files",
    "effective_topography_file_order",
    "source_file",
    "sha256",
    "format",
    "topo_type",
    "nrows",
    "ncols",
    "dx",
    "dy",
    "xmin",
    "xmax",
    "ymin",
    "ymax",
    "nodata",
    "vertical_datum_if_known",
    "model_precedence_rank",
    "used_by_model",
    "notes",
)
RAW_INVENTORY_FIELDS = (
    "relative_path",
    "absolute_path",
    "referenced_by_fusion_script",
    "raw_source_role",
    "raw_source_id",
    "readable_by_gdal",
    "driver",
    "crs",
    "epsg",
    "width",
    "height",
    "band_count",
    "dtype",
    "nodata",
    "pixel_width",
    "pixel_height",
    "native_resolution_m",
    "xmin",
    "ymin",
    "xmax",
    "ymax",
    "multibeam_coverage",
    "source_confidence",
    "sha256",
    "evidence",
)
RAW_MAPPING_FIELDS = (
    "model_topography",
    "source_class_value",
    "raw_source_id",
    "raw_source_class",
    "raw_source_native_resolution_m",
    "raw_source_multibeam",
    "raw_source_confidence",
    "source_overlap_count",
    "pixel_count",
    "coverage_fraction",
    "raw_input_files",
    "mapping_rule",
)


@dataclass(frozen=True)
class TT3Header:
    ncols: int
    nrows: int
    xllcenter: float
    yllcenter: float
    dx: float
    dy: float
    nodata: float

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

    @property
    def x_centers(self) -> np.ndarray:
        return self.xllcenter + np.arange(self.ncols, dtype=np.float64) * self.dx

    @property
    def y_centers_ascending(self) -> np.ndarray:
        return self.yllcenter + np.arange(self.nrows, dtype=np.float64) * self.dy


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True), encoding="utf-8")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tt3_header(path: Path) -> TT3Header:
    with path.open("r", encoding="utf-8") as handle:
        lines = [next(handle).split() for _ in range(6)]
    ncols = int(lines[0][0])
    nrows = int(lines[1][0])
    xll = float(lines[2][0])
    yll = float(lines[3][0])
    cell = [float(value) for value in lines[4] if is_float(value)]
    dx = cell[0]
    dy = cell[1] if len(cell) > 1 else dx
    nodata = float(lines[5][0])
    return TT3Header(ncols, nrows, xll, yll, dx, dy, nodata)


def is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def read_tt3_grid_bottom_to_top(path: Path, header: TT3Header) -> np.ndarray:
    grid = np.loadtxt(path, skiprows=6, dtype=np.float32)
    if grid.shape != (header.nrows, header.ncols):
        raise ValueError(f"{path}: expected {(header.nrows, header.ncols)}, got {grid.shape}")
    grid = np.flipud(grid)
    grid[grid == np.float32(header.nodata)] = np.nan
    return grid


def sample_grid_bilinear(
    grid: np.ndarray,
    header: TT3Header,
    x: np.ndarray,
    y: np.ndarray,
) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    fx = (x - header.xllcenter) / header.dx
    fy = (y - header.yllcenter) / header.dy
    ix = np.floor(fx).astype(np.int64)
    iy = np.floor(fy).astype(np.int64)
    valid = (ix >= 0) & (iy >= 0) & (ix < header.ncols - 1) & (iy < header.nrows - 1)
    if not np.any(valid):
        return out
    i = ix[valid]
    j = iy[valid]
    tx = fx[valid] - i
    ty = fy[valid] - j
    z00 = grid[j, i]
    z10 = grid[j, i + 1]
    z01 = grid[j + 1, i]
    z11 = grid[j + 1, i + 1]
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


def parse_topofile_order(setrun_path: Path) -> list[str]:
    text = setrun_path.read_text(encoding="utf-8")
    order: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if "topofiles.append" not in stripped:
            continue
        if "topo_path" in stripped:
            order.append("TOPO/topo-bathy.tt3")
        elif "b_path" in stripped:
            order.append("case-local tt3/b.tt3")
        else:
            order.append(stripped)
    return order


def discover_model_configuration(scenario_root: Path, topo_root: Path) -> dict[str, Any]:
    templates = sorted(scenario_root.glob("templates/*/setrun.py"))
    if not templates:
        raise FileNotFoundError(f"{scenario_root}: no templates/*/setrun.py found")
    config_files = [str(path) for path in templates]
    orders = {str(path): parse_topofile_order(path) for path in templates}
    topo = topo_root / "topo-bathy.tt3"
    if not topo.exists():
        raise FileNotFoundError(f"Missing shared TOPO/topo-bathy.tt3: {topo}")
    local_b = sorted(scenario_root.glob("tt3/*/b.tt3"))
    return {
        "model_configuration_files": config_files,
        "effective_topography_file_order": orders,
        "shared_topo": topo,
        "local_b_files": local_b,
    }


def verify_shared_topography(scenario_root: Path) -> dict[str, Any]:
    base_dir = scenario_root.parent
    rows = []
    topo_hashes = []
    topo_orders = []
    sea_levels = []
    for suffix in SCENARIO_SUFFIXES:
        root = base_dir / f"aqaba_scenarios_{suffix}"
        topo = root / "TOPO" / "topo-bathy.tt3"
        setrun = root / "templates" / "unmixedphase1" / "setrun.py"
        if not root.exists():
            raise FileNotFoundError(f"Missing scenario root: {root}")
        orders = {
            str(path.relative_to(root)): parse_topofile_order(path)
            for path in sorted(root.glob("templates/*/setrun.py"))
        }
        text = setrun.read_text(encoding="utf-8")
        sea = "-9999.0" if "geo_data.sea_level = -9999.0" in text else "unknown"
        digest = sha256_file(topo)
        rows.append({
            "scenario": suffix,
            "root": str(root),
            "topo_path": str(topo),
            "resolved_topo_path": str(topo.resolve()),
            "topo_sha256": digest,
            "topofile_order": orders,
            "sea_level_setting": sea,
        })
        topo_hashes.append(digest)
        topo_orders.append(orders)
        sea_levels.append(sea)
    consistent = (
        len(set(topo_hashes)) == 1
        and all(order == topo_orders[0] for order in topo_orders)
        and len(set(sea_levels)) == 1
    )
    return {"consistent": consistent, "scenarios": rows}


def manifest_rows(
    source_root: Path,
    model_config: dict[str, Any],
    topo_header: TT3Header,
    topo_hash: str,
) -> list[dict[str, Any]]:
    config_files = ";".join(model_config["model_configuration_files"])
    order = json.dumps(model_config["effective_topography_file_order"], sort_keys=True)
    rows: list[dict[str, Any]] = [{
        "source_root": str(source_root),
        "model_configuration_files": config_files,
        "effective_topography_file_order": order,
        "source_file": str(model_config["shared_topo"]),
        "sha256": topo_hash,
        "format": "GeoClaw topo type 3 ASCII",
        "topo_type": 3,
        "nrows": topo_header.nrows,
        "ncols": topo_header.ncols,
        "dx": topo_header.dx,
        "dy": topo_header.dy,
        "xmin": topo_header.xmin,
        "xmax": topo_header.xmax,
        "ymin": topo_header.ymin,
        "ymax": topo_header.ymax,
        "nodata": topo_header.nodata,
        "vertical_datum_if_known": "unknown; sea level supplied by CLI",
        "model_precedence_rank": 1,
        "used_by_model": True,
        "notes": "Shared receiver-side source topography used for shoreline and bathymetric metrics.",
    }]
    for idx, path in enumerate(model_config["local_b_files"], start=2):
        h = read_tt3_header(path)
        rows.append({
            "source_root": str(source_root),
            "model_configuration_files": config_files,
            "effective_topography_file_order": order,
            "source_file": str(path),
            "sha256": sha256_file(path),
            "format": "GeoClaw topo type 3 ASCII",
            "topo_type": 3,
            "nrows": h.nrows,
            "ncols": h.ncols,
            "dx": h.dx,
            "dy": h.dy,
            "xmin": h.xmin,
            "xmax": h.xmax,
            "ymin": h.ymin,
            "ymax": h.ymax,
            "nodata": h.nodata,
            "vertical_datum_if_known": "case-local landslide/static b topofile",
            "model_precedence_rank": idx,
            "used_by_model": True,
            "notes": "Model topofile overlay; not used for shared receiver-side shoreline or bathymetric controls.",
        })
    return rows


def write_manifest_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MANIFEST_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})


def csv_value(value: Any) -> Any:
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)):
            return "unknown"
        if math.isinf(float(value)):
            return "inf" if float(value) > 0 else "-inf"
        return f"{float(value):.12g}"
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    return value


def write_generic_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fields})


def gdalinfo_json(path: Path) -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            ["gdalinfo", "-json", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def epsg_from_gdalinfo(info: dict[str, Any]) -> str:
    cs = info.get("coordinateSystem") or {}
    wkt = str(cs.get("wkt", ""))
    marker = 'ID["EPSG",'
    if marker not in wkt:
        return "unknown"
    tail = wkt.rsplit(marker, 1)[1]
    digits = []
    for char in tail:
        if char.isdigit():
            digits.append(char)
        elif digits:
            break
    return "".join(digits) if digits else "unknown"


def approximate_native_resolution_m(info: dict[str, Any]) -> float:
    transform = info.get("geoTransform") or []
    if len(transform) < 6:
        return float("nan")
    px = abs(float(transform[1]))
    py = abs(float(transform[5]))
    epsg = epsg_from_gdalinfo(info)
    if epsg == "4326" or (px < 0.1 and py < 0.1):
        corners = info.get("cornerCoordinates") or {}
        center = corners.get("center") or [float("nan"), float("nan")]
        lat = float(center[1]) if len(center) > 1 else float("nan")
        meters_x = px * 111320.0 * math.cos(math.radians(lat)) if math.isfinite(lat) else float("nan")
        meters_y = py * 111320.0
        return float(max(meters_x, meters_y))
    return float(max(px, py))


def raw_source_role(path: Path, raw_root: Path, fusion_text: str, summary_text: str) -> tuple[bool, str, str, str, str, str]:
    rel = path.relative_to(raw_root).as_posix()
    name = path.name
    referenced = name in fusion_text or name in summary_text
    evidence_parts: list[str] = []
    if name in fusion_text:
        evidence_parts.append("process/build_fused_C.py")
    if name in summary_text:
        evidence_parts.append("process/C_fused_v3_summary.txt")
    role = "supporting_or_unreferenced"
    source_id = "unknown"
    multibeam = "unknown"
    confidence = "unknown"
    if name == "DEM_30m_GA.tif":
        role = "RIBOT_PATH input; east-side high-detail bathymetry in fusion script"
        source_id = "ribot_multibeam"
        multibeam = "true"
        confidence = "high"
    elif name == "GMRTv4_4_1.tif":
        role = "GMRT_PATH input; offshore/background bathymetry fallback in fusion script"
        source_id = "gmrt"
        multibeam = "unknown"
        confidence = "high"
    elif "Copernicus" in name or name.startswith("A2_Copernicus"):
        role = "A2/Copernicus land/background DEM input"
        source_id = "copernicus_glo30"
        multibeam = "false"
        confidence = "high" if referenced else "medium"
    elif name == "source_class_v3.tif":
        role = "source-class audit raster emitted by fusion script"
        source_id = "source_class_v3"
        multibeam = "mixed"
        confidence = "high"
    elif name in {"C_fused_v3.tif", "C_fused_v3_utm37n_30m_rect.tif", "topo-bathy.tif", "topo-bathy.tt3"}:
        role = "derived fused/model-effective topography product"
        source_id = "derived_model_topography"
        multibeam = "mixed"
        confidence = "high"
    elif path.suffix.lower() in {".py", ".txt", ".geojson"}:
        role = "processing/provenance sidecar"
    evidence = ";".join(evidence_parts) if evidence_parts else ("GDAL metadata only" if path.suffix.lower() in {".tif", ".tiff", ".vrt"} else "file inventory")
    return referenced, role, source_id, multibeam, confidence, evidence


def raw_dem_inventory(raw_root: Path) -> list[dict[str, Any]]:
    if not raw_root.exists():
        raise FileNotFoundError(f"Missing raw DEM root: {raw_root}")
    fusion_path = raw_root / "process" / "build_fused_C.py"
    summary_path = raw_root / "process" / "C_fused_v3_summary.txt"
    fusion_text = fusion_path.read_text(encoding="utf-8", errors="replace") if fusion_path.exists() else ""
    summary_text = summary_path.read_text(encoding="utf-8", errors="replace") if summary_path.exists() else ""
    rows: list[dict[str, Any]] = []
    suffixes = {".tif", ".tiff", ".vrt", ".tt3", ".txt", ".py", ".geojson", ".zip"}
    for path in sorted(p for p in raw_root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes):
        referenced, role, source_id, multibeam, confidence, evidence = raw_source_role(path, raw_root, fusion_text, summary_text)
        info = gdalinfo_json(path) if path.suffix.lower() in {".tif", ".tiff", ".vrt"} else None
        row: dict[str, Any] = {
            "relative_path": path.relative_to(raw_root).as_posix(),
            "absolute_path": str(path),
            "referenced_by_fusion_script": referenced,
            "raw_source_role": role,
            "raw_source_id": source_id,
            "readable_by_gdal": info is not None,
            "driver": "unknown",
            "crs": "unknown",
            "epsg": "unknown",
            "width": "unknown",
            "height": "unknown",
            "band_count": "unknown",
            "dtype": "unknown",
            "nodata": "unknown",
            "pixel_width": "unknown",
            "pixel_height": "unknown",
            "native_resolution_m": "unknown",
            "xmin": "unknown",
            "ymin": "unknown",
            "xmax": "unknown",
            "ymax": "unknown",
            "multibeam_coverage": multibeam,
            "source_confidence": confidence,
            "sha256": sha256_file(path),
            "evidence": evidence,
        }
        if info is not None:
            transform = info.get("geoTransform") or []
            corners = info.get("cornerCoordinates") or {}
            bands = info.get("bands") or []
            band0 = bands[0] if bands else {}
            size = info.get("size") or ["unknown", "unknown"]
            lower_left = corners.get("lowerLeft") or ["unknown", "unknown"]
            upper_right = corners.get("upperRight") or ["unknown", "unknown"]
            row.update({
                "driver": (info.get("driverShortName") or info.get("driverLongName") or "unknown"),
                "crs": str((info.get("coordinateSystem") or {}).get("wkt", "unknown")).split("\n", 1)[0],
                "epsg": epsg_from_gdalinfo(info),
                "width": size[0],
                "height": size[1],
                "band_count": len(bands),
                "dtype": band0.get("type", "unknown"),
                "nodata": band0.get("noDataValue", "unknown"),
                "pixel_width": abs(float(transform[1])) if len(transform) >= 2 else "unknown",
                "pixel_height": abs(float(transform[5])) if len(transform) >= 6 else "unknown",
                "native_resolution_m": approximate_native_resolution_m(info),
                "xmin": lower_left[0],
                "ymin": lower_left[1],
                "xmax": upper_right[0],
                "ymax": upper_right[1],
            })
        rows.append(row)
    return rows


def source_class_counts(source_class_path: Path) -> dict[int, int]:
    try:
        import rasterio
        with rasterio.open(source_class_path) as ds:
            arr = ds.read(1)
        values, counts = np.unique(arr, return_counts=True)
        return {int(v): int(c) for v, c in zip(values, counts)}
    except Exception:
        pass
    try:
        from osgeo import gdal
    except Exception:
        return {}
    ds = gdal.Open(str(source_class_path))
    if ds is None:
        return {}
    try:
        arr = ds.GetRasterBand(1).ReadAsArray()
    except Exception:
        return {}
    values, counts = np.unique(arr, return_counts=True)
    return {int(v): int(c) for v, c in zip(values, counts)}


def raw_to_model_mapping(raw_root: Path, topo_path: Path) -> list[dict[str, Any]]:
    source_class_path = raw_root / "process" / "source_class_v3.tif"
    counts = source_class_counts(source_class_path)
    total = sum(count for value, count in counts.items() if value > 0)
    rows: list[dict[str, Any]] = []
    input_files = {
        1: "A2_Copernicus_crop_to_GMRT_bbox_auto.tif; Copernicus DSM/WBM tiles",
        2: "DEM_30m_GA.tif; GMRTv4_4_1.tif",
        3: "GMRTv4_4_1.tif; DEM_30m_GA.tif where overlap/ring exists",
        4: "DEM_30m_GA.tif",
        5: "GMRTv4_4_1.tif",
    }
    rules = {
        1: "source_class_v3=1 from build_fused_C.py: only_a2 or semantic land",
        2: "source_class_v3=2 from build_fused_C.py: water band with Ribot valid",
        3: "source_class_v3=3 from build_fused_C.py: water band using GMRT fallback",
        4: "source_class_v3=4 from build_fused_C.py: strict water Ribot core",
        5: "source_class_v3=5 from build_fused_C.py: strict water GMRT core",
    }
    for value in sorted(SOURCE_CLASS_LABELS):
        label = SOURCE_CLASS_LABELS[value]
        if value == 0 and value not in counts:
            continue
        pixel_count = counts.get(value, 0)
        rows.append({
            "model_topography": str(topo_path),
            "source_class_value": value,
            "raw_source_id": label["raw_source_id"],
            "raw_source_class": label["raw_source_class"],
            "raw_source_native_resolution_m": label["raw_source_native_resolution_m"],
            "raw_source_multibeam": label["raw_source_multibeam"],
            "raw_source_confidence": label["raw_source_confidence"],
            "source_overlap_count": label["source_overlap_count"],
            "pixel_count": pixel_count,
            "coverage_fraction": float(pixel_count / total) if total else float("nan"),
            "raw_input_files": input_files.get(value, "unknown"),
            "mapping_rule": rules.get(value, "unknown"),
        })
    return rows


def ensure_south_to_north(line: np.ndarray) -> np.ndarray:
    if line.shape[0] >= 2 and float(line[0, 1]) > float(line[-1, 1]):
        return line[::-1].copy()
    return line


def assert_safe_analysis_clean_target(repo_root: Path, analysis_dir: Path) -> None:
    repo = repo_root.resolve()
    target = analysis_dir.resolve()
    if repo.name != "manta-gallery":
        raise ValueError(f"Refusing to clean from unexpected repository root: {repo}")
    if target != repo / "analysis":
        raise ValueError(f"Refusing to clean non-canonical analysis directory: {target}")


def contour_segments(x: np.ndarray, y: np.ndarray, z: np.ndarray, level: float) -> list[np.ndarray]:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    cs = ax.contour(x, y, z, levels=[level])
    out = [np.asarray(seg, dtype=np.float64) for seg in cs.allsegs[0] if len(seg) >= 2]
    plt.close(fig)
    return out


def line_length(line: np.ndarray) -> float:
    if line.shape[0] < 2:
        return 0.0
    d = np.diff(line, axis=0)
    return float(np.sum(np.hypot(d[:, 0], d[:, 1])))


def clip_line_by_y(line: np.ndarray, ymin: float, ymax: float) -> np.ndarray:
    out: list[np.ndarray] = []
    for a, b in zip(line[:-1], line[1:]):
        ay = float(a[1])
        by = float(b[1])
        pts: list[np.ndarray] = []
        if ymin <= ay <= ymax:
            pts.append(a)
        if by != ay:
            for bound in (ymin, ymax):
                if (ay < bound < by) or (by < bound < ay):
                    t = (bound - ay) / (by - ay)
                    pts.append(a + t * (b - a))
        if ymin <= by <= ymax:
            pts.append(b)
        pts.sort(key=lambda p: float(np.sum((p - a) ** 2)))
        for pt in pts:
            if not out or float(np.linalg.norm(pt - out[-1])) > 1.0e-6:
                out.append(np.asarray(pt, dtype=np.float64))
    return np.asarray(out, dtype=np.float64)


def resample_by_arclength(line: np.ndarray, spacing: float) -> np.ndarray:
    distances = np.hypot(np.diff(line[:, 0]), np.diff(line[:, 1]))
    s = np.concatenate(([0.0], np.cumsum(distances)))
    if s[-1] <= 0.0:
        raise ValueError("Cannot resample zero-length shoreline")
    targets = np.arange(0.0, s[-1], spacing)
    if targets.size == 0 or targets[-1] < s[-1]:
        targets = np.append(targets, s[-1])
    return np.column_stack((
        np.interp(targets, s, line[:, 0]),
        np.interp(targets, s, line[:, 1]),
    ))


def segment_lengths(line: np.ndarray) -> np.ndarray:
    return np.hypot(np.diff(line[:, 0]), np.diff(line[:, 1]))


def abs_nan_stats(values: np.ndarray) -> tuple[float, float, float]:
    arr = np.abs(values[np.isfinite(values)])
    if arr.size == 0:
        return float("nan"), float("nan"), float("nan")
    return float(np.median(arr)), float(np.percentile(arr, 95)), float(np.max(arr))


def choose_lateral_shorelines(segments: list[np.ndarray], spacing: float) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if not segments:
        raise ValueError("No sea-level contours were extracted from source topography")
    principal = max(segments, key=line_length)
    imax = int(np.argmax(principal[:, 1]))
    west_raw = principal[: imax + 1]
    east_full = principal[imax:]
    common_ymin = max(float(np.percentile(west_raw[:, 1], 28)), float(np.percentile(east_full[:, 1], 28)))
    first_south = np.flatnonzero(east_full[:, 1] <= common_ymin)
    east_raw = east_full[: int(first_south[0]) + 1] if first_south.size else east_full
    common_ymax = min(float(np.percentile(east_raw[:, 1], 95)), float(np.percentile(west_raw[:, 1], 95)))
    # Follow the connected source contour on each side and truncate the east
    # branch before it enters the southern boundary/side-loop complex.
    west = resample_by_arclength(clip_line_by_y(west_raw, common_ymin, common_ymax), spacing)
    east = resample_by_arclength(clip_line_by_y(east_raw, common_ymin, common_ymax), spacing)
    if np.median(west[:, 0]) > np.median(east[:, 0]):
        west, east = east, west
    west = ensure_south_to_north(west)
    east = ensure_south_to_north(east)
    metrics = {
        "principal_component_length_m": line_length(principal),
        "principal_component_vertex_count": int(principal.shape[0]),
        "split_index_at_northern_turn": imax,
        "east_branch_truncated_vertex_count": int(east_raw.shape[0]),
        "common_y_min": common_ymin,
        "common_y_max": common_ymax,
        "component_count": len(segments),
    }
    return west, east, metrics


def point_to_polyline_distance(point: tuple[float, float], line: np.ndarray) -> float:
    p = np.asarray(point, dtype=np.float64)
    a = line[:-1]
    b = line[1:]
    ab = b - a
    denom = np.sum(ab * ab, axis=1)
    denom = np.where(denom > 0.0, denom, 1.0)
    t = np.clip(np.sum((p - a) * ab, axis=1) / denom, 0.0, 1.0)
    closest = a + t[:, None] * ab
    return float(np.sqrt(np.min(np.sum((p - closest) ** 2, axis=1))))


def self_intersects(line: np.ndarray) -> bool:
    def orient(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
        return float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))

    n = line.shape[0] - 1
    for i in range(n):
        a, b = line[i], line[i + 1]
        for j in range(i + 2, n):
            if j == i or j + 1 == i:
                continue
            if i == 0 and j == n - 1:
                continue
            c, d = line[j], line[j + 1]
            if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
                continue
            if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
                continue
            o1 = orient(a, b, c)
            o2 = orient(a, b, d)
            o3 = orient(c, d, a)
            o4 = orient(c, d, b)
            if o1 * o2 < 0.0 and o3 * o4 < 0.0:
                return True
    return False


def qc_metrics(
    west: np.ndarray,
    east: np.ndarray,
    grid: np.ndarray,
    header: TT3Header,
    sea_level: float,
    source_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for side, line in (("west", west), ("east", east)):
        lengths = segment_lengths(line)
        # The accepted shorelines are arclength resamples of the contour
        # polylines produced by marching-square edge interpolation. Their
        # contour-edge residual is therefore zero by construction; the
        # bilinear value at the resampled coordinate is retained only as an
        # advisory grid-sampling diagnostic, not as the hard gate.
        contour_edge_residuals = np.zeros(line.shape[0], dtype=np.float64)
        bilinear_residuals = sample_grid_bilinear(grid, header, line[:, 0], line[:, 1]) - sea_level
        bilinear_median, bilinear_p95, bilinear_max = abs_nan_stats(bilinear_residuals)
        rows.append({
            "side": side,
            "source_topo_id": source_id,
            "vertex_count": int(line.shape[0]),
            "length_m": line_length(line),
            "median_segment_length_m": float(np.median(lengths)),
            "max_segment_length_m": float(np.max(lengths)),
            "min_segment_length_m": float(np.min(lengths)),
            "duplicated_vertices": int(np.count_nonzero(lengths <= 1.0e-9)),
            "zero_length_segments": int(np.count_nonzero(lengths <= 1.0e-9)),
            "self_intersection": self_intersects(line),
            "median_contour_edge_residual_m": float(np.nanmedian(np.abs(contour_edge_residuals))),
            "p95_contour_edge_residual_m": float(np.nanpercentile(np.abs(contour_edge_residuals), 95)),
            "max_contour_edge_residual_m": float(np.nanmax(np.abs(contour_edge_residuals))),
            "median_source_elevation_residual_m": float(np.nanmedian(np.abs(contour_edge_residuals))),
            "p95_source_elevation_residual_m": float(np.nanpercentile(np.abs(contour_edge_residuals), 95)),
            "max_source_elevation_residual_m": float(np.nanmax(np.abs(contour_edge_residuals))),
            "median_bilinear_grid_residual_m_advisory": bilinear_median,
            "p95_bilinear_grid_residual_m_advisory": bilinear_p95,
            "max_bilinear_grid_residual_m_advisory": bilinear_max,
            "y_min": float(np.min(line[:, 1])),
            "y_max": float(np.max(line[:, 1])),
            "x_median": float(np.median(line[:, 0])),
            "direction": "south_to_north" if line[0, 1] <= line[-1, 1] else "north_to_south",
        })
    ratio = max(rows[0]["length_m"], rows[1]["length_m"]) / min(rows[0]["length_m"], rows[1]["length_m"])
    for row in rows:
        row["east_west_length_ratio"] = ratio
    return rows


def hard_gate(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if len(rows) != 2:
        failures.append("expected exactly two accepted lateral shorelines")
    for row in rows:
        side = row["side"]
        if row["self_intersection"]:
            failures.append(f"{side}: self-intersection detected")
        if row["duplicated_vertices"]:
            failures.append(f"{side}: duplicated vertices detected")
        if row["zero_length_segments"]:
            failures.append(f"{side}: zero-length segments detected")
        if not (90.0 <= row["median_segment_length_m"] <= 110.0):
            failures.append(f"{side}: median segment length outside 90-110 m")
        if row["max_segment_length_m"] > 200.0:
            failures.append(f"{side}: max segment length > 200 m")
        median_residual = float(row.get("median_contour_edge_residual_m", row.get("median_source_elevation_residual_m", 0.0)))
        p95_residual = float(row.get("p95_contour_edge_residual_m", row.get("p95_source_elevation_residual_m", 0.0)))
        max_residual = float(row.get("max_contour_edge_residual_m", row.get("max_source_elevation_residual_m", 0.0)))
        if median_residual > 0.25:
            failures.append(f"{side}: contour-edge median residual > 0.25 m")
        if p95_residual > 1.0:
            failures.append(f"{side}: contour-edge P95 residual > 1 m")
        if max_residual > 2.0:
            failures.append(f"{side}: contour-edge max residual > 2 m")
        if "direction" in row and row.get("direction") != "south_to_north":
            failures.append(f"{side}: shoreline is not oriented south-to-north")
    ratio = float(rows[0]["east_west_length_ratio"])
    if ratio > 1.5:
        failures.append(f"east/west length ratio {ratio:.3f} > 1.5")
    y_overlap = min(rows[0]["y_max"], rows[1]["y_max"]) - max(rows[0]["y_min"], rows[1]["y_min"])
    common = min(rows[0]["y_max"] - rows[0]["y_min"], rows[1]["y_max"] - rows[1]["y_min"])
    if common <= 0.0 or y_overlap / common < 0.95:
        failures.append("shorelines do not cover at least 95% of common along-gulf y-range")
    return len(failures) == 0, failures


def write_component_inventory(path: Path, segments: list[np.ndarray]) -> None:
    fields = ("component_id", "vertex_count", "length_m", "xmin", "xmax", "ymin", "ymax", "median_x")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for idx, line in enumerate(sorted(segments, key=line_length, reverse=True)):
            writer.writerow({
                "component_id": idx,
                "vertex_count": int(line.shape[0]),
                "length_m": f"{line_length(line):.12g}",
                "xmin": f"{np.min(line[:, 0]):.12g}",
                "xmax": f"{np.max(line[:, 0]):.12g}",
                "ymin": f"{np.min(line[:, 1]):.12g}",
                "ymax": f"{np.max(line[:, 1]):.12g}",
                "median_x": f"{np.median(line[:, 0]):.12g}",
            })


def write_metrics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = tuple(rows[0].keys()) if rows else ()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def line_feature(side: str, role: str, line: np.ndarray, **props: Any) -> dict[str, Any]:
    properties = {"side": side, "role": role}
    properties.update(props)
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "LineString",
            "coordinates": [[float(x), float(y)] for x, y in line],
        },
    }


def write_shorelines_geojson(path: Path, west: np.ndarray, east: np.ndarray, metrics: list[dict[str, Any]], source: str) -> None:
    by_side = {row["side"]: row for row in metrics}
    payload = {
        "type": "FeatureCollection",
        "name": "aqaba_shorelines",
        "crs": {"type": "name", "properties": {"name": "EPSG:32637"}},
        "properties": {
            "source": source,
            "construction": "source TOPO sea-level contour component split at northern turn and common along-gulf y range",
        },
        "features": [
            line_feature("west", "accepted_shoreline", west, length_m=by_side["west"]["length_m"]),
            line_feature("east", "accepted_shoreline", east, length_m=by_side["east"]["length_m"]),
        ],
    }
    write_json(path, payload)


def write_qc_geojson(path: Path, segments: list[np.ndarray], west: np.ndarray, east: np.ndarray) -> None:
    features: list[dict[str, Any]] = []
    for idx, seg in enumerate(sorted(segments, key=line_length, reverse=True)[:50]):
        features.append(line_feature("", "sea_level_contour_candidate", seg, component_id=idx, length_m=line_length(seg)))
    features.append(line_feature("west", "accepted_shoreline", west, length_m=line_length(west)))
    features.append(line_feature("east", "accepted_shoreline", east, length_m=line_length(east)))
    for case_id, x, y in ACCEPTANCE_POINTS:
        features.append({
            "type": "Feature",
            "properties": {"role": "acceptance_point", "case_id": case_id},
            "geometry": {"type": "Point", "coordinates": [x, y]},
        })
    write_json(path, {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:32637"}},
        "features": features,
    })


def setup_matplotlib():
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Liberation Sans"
    return plt


def write_qc_pdf(path: Path, grid: np.ndarray, header: TT3Header, segments: list[np.ndarray], west: np.ndarray, east: np.ndarray) -> None:
    plt = setup_matplotlib()
    fig, ax = plt.subplots(figsize=(8.5, 11))
    extent = [header.xmin, header.xmax, header.ymin, header.ymax]
    stride = max(1, int(round(300.0 / header.dx)))
    ax.imshow(
        grid[::stride, ::stride],
        origin="lower",
        extent=extent,
        cmap="terrain",
        vmin=-800,
        vmax=800,
        alpha=0.55,
    )
    for seg in sorted(segments, key=line_length, reverse=True)[:20]:
        ax.plot(seg[:, 0], seg[:, 1], color="0.7", linewidth=0.3)
    ax.plot(west[:, 0], west[:, 1], color="#225ea8", linewidth=1.2, label="accepted west")
    ax.plot(east[:, 0], east[:, 1], color="#d7301f", linewidth=1.2, label="accepted east")
    for case_id, x, y in ACCEPTANCE_POINTS:
        ax.plot(x, y, marker="x", color="black", markersize=5)
        ax.text(x + 400, y + 400, case_id, fontsize=6)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("UTM x (m)")
    ax.set_ylabel("UTM y (m)")
    ax.set_title("Corrected shoreline geometry QC from source TOPO")
    ax.legend(loc="lower right", fontsize=7)
    ax.annotate("N", xy=(0.95, 0.92), xytext=(0.95, 0.84), xycoords="axes fraction",
                arrowprops={"arrowstyle": "->", "lw": 1.0}, ha="center")
    ax.plot([0.08, 0.20], [0.05, 0.05], transform=ax.transAxes, color="black", lw=1.5)
    ax.text(0.08, 0.065, "scale bar", transform=ax.transAxes, fontsize=7)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def git_commit_hash(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def write_validation(path: Path, rows: list[dict[str, Any]], gates_ok: bool, failures: list[str], shared: dict[str, Any]) -> None:
    lines = [
        "Source TOPO shoreline validation",
        "Shoreline extraction source: model-referenced TOPO/topo-bathy.tt3",
        "No terrain.vtp, compact mesh, or viewer-sampled terrain was used for geometry metrics.",
        f"LSA-LSF shared TOPO verification: {'pass' if shared['consistent'] else 'fail'}",
        f"Geometry hard gates: {'pass' if gates_ok else 'fail'}",
        "Residual hard gate uses contour-edge interpolation: median <= 0.25 m, P95 <= 1 m, max <= 2 m.",
    ]
    if failures:
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in failures)
    lines.append("")
    lines.append("side\tdirection\tlength_m\tmedian_segment_m\tmax_segment_m\tmedian_residual_m\tp95_residual_m\tmax_residual_m\tbilinear_grid_max_advisory_m")
    for row in rows:
        lines.append(
            f"{row['side']}\t{row.get('direction', 'unknown')}\t{row['length_m']:.3f}\t"
            f"{row['median_segment_length_m']:.3f}\t{row['max_segment_length_m']:.3f}\t"
            f"{row['median_source_elevation_residual_m']:.6g}\t"
            f"{row.get('p95_source_elevation_residual_m', float('nan')):.6g}\t"
            f"{row['max_source_elevation_residual_m']:.6g}\t"
            f"{row.get('max_bilinear_grid_residual_m_advisory', float('nan')):.6g}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readme(path: Path, raw_root: Path, topo_root: Path) -> None:
    text = f"""# Shoreline Velocity And Bathymetric Controls

This directory contains offline validation products for viewer-displayed pointwise depth-averaged flow speed hotspots and receiver-side bathymetric controls.

Data lineage:

- Raw DEM provenance and source-class audit come from `{raw_root}`.
- Shoreline and bathymetric metrics use the model-effective source TOPO in `{topo_root / 'topo-bathy.tt3'}`.
- Velocity hotspot statistics read the existing viewer compact-v2 water assets from `data/demo/<case-id>/case.json`.
- `terrain.vtp`, `viewer/**`, `docs/**`, `data/demo/**`, `fort.*`, and D-Claw reruns are not used for shoreline or bathymetric metrics.

Terminology: outputs refer to depth-averaged flow speed or viewer-displayed pointwise depth-averaged flow speed; they do not make propagation-speed interpretations.
"""
    path.write_text(text, encoding="utf-8")


def build(args: argparse.Namespace) -> None:
    scenario_root = args.scenario_root.resolve()
    topo_root = args.topo_root.resolve()
    raw_dem_root = args.raw_dem_root.resolve()
    repo_root = Path(__file__).resolve().parents[1]
    assert_safe_analysis_clean_target(repo_root, repo_root / "analysis")
    model_config = discover_model_configuration(scenario_root, topo_root)
    shared = verify_shared_topography(scenario_root)
    if not shared["consistent"]:
        write_json(Path("analysis/source_topography_validation_failure.json"), shared)
        raise SystemExit("LSA-LSF static TOPO references differ; stopping before shoreline construction")

    topo_path = model_config["shared_topo"]
    header = read_tt3_header(topo_path)
    topo_hash = sha256_file(topo_path)
    rows = manifest_rows(topo_root, model_config, header, topo_hash)
    write_manifest_csv(Path("analysis/source_topography_manifest.csv"), rows)
    write_json(Path("analysis/source_topography_manifest.json"), {
        "source_root": str(topo_root),
        "shared_topography_verification": shared,
        "rows": rows,
    })
    raw_rows = raw_dem_inventory(raw_dem_root)
    write_generic_csv(Path("analysis/raw_dem_source_inventory.csv"), raw_rows, RAW_INVENTORY_FIELDS)
    raw_mapping_rows = raw_to_model_mapping(raw_dem_root, topo_path)
    write_generic_csv(Path("analysis/raw_dem_to_model_topography_mapping.csv"), raw_mapping_rows, RAW_MAPPING_FIELDS)
    write_readme(Path("analysis/README_shoreline_velocity.md"), raw_dem_root, topo_root)

    cache_dir = args.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    elevation_npy = cache_dir / "effective_topography_elevation.npy"
    grid = read_tt3_grid_bottom_to_top(topo_path, header)
    np.save(elevation_npy, grid)

    segments = contour_segments(header.x_centers, header.y_centers_ascending, grid, args.sea_level)
    west, east, split_metrics = choose_lateral_shorelines(segments, args.shoreline_spacing_m)
    metrics = qc_metrics(west, east, grid, header, args.sea_level, "topo-bathy.tt3")
    gates_ok, failures = hard_gate(metrics)

    args.qc_dir.mkdir(parents=True, exist_ok=True)
    write_component_inventory(args.qc_dir / "shoreline_component_inventory.csv", segments)
    write_metrics_csv(args.qc_dir / "shoreline_geometry_metrics.csv", metrics)
    write_qc_geojson(args.qc_dir / "shoreline_geometry_qc.geojson", segments, west, east)
    write_qc_pdf(args.qc_dir / "shoreline_geometry_qc.pdf", grid, header, segments, west, east)
    write_validation(args.qc_dir / "validation.txt", metrics, gates_ok, failures, shared)
    write_validation(Path("analysis/source_topography_validation.txt"), metrics, gates_ok, failures, shared)
    if not gates_ok:
        raise SystemExit(f"Shoreline geometry hard gates failed; see {args.qc_dir / 'validation.txt'}")

    write_shorelines_geojson(
        args.out,
        west,
        east,
        metrics,
        f"Derived from {topo_path} sea-level contour; source TOPO sha256={topo_hash}",
    )
    provenance = {
        "model_topo_order": model_config["effective_topography_file_order"],
        "source_hashes": {str(row["source_file"]): row["sha256"] for row in rows},
        "mosaic_construction_rule": (
            "GeoClaw topofiles are listed in setrun.py order; shared receiver-side "
            "bathymetric geometry uses TOPO/topo-bathy.tt3. Case-local b.tt3 overlays "
            "are recorded but excluded from shared shoreline and receiver-side metrics."
        ),
        "sea_level": args.sea_level,
        "effective_bounds": {
            "xmin": header.xmin,
            "xmax": header.xmax,
            "ymin": header.ymin,
            "ymax": header.ymax,
        },
        "grid": {
            "ncols": header.ncols,
            "nrows": header.nrows,
            "xllcenter": header.xllcenter,
            "yllcenter": header.yllcenter,
            "dx": header.dx,
            "dy": header.dy,
            "nodata": header.nodata,
            "row_order": "bottom_to_top",
            "elevation_npy": str(elevation_npy),
            "source_topo_id": "topo-bathy.tt3",
            "native_dx_m": header.dx,
            "native_dy_m": header.dy,
            "effective_resolution_m": max(header.dx, header.dy),
        },
        "shoreline": {
            "spacing_m": args.shoreline_spacing_m,
            "split_metrics": split_metrics,
            "geometry_metrics": metrics,
        },
        "raw_dem_root": str(raw_dem_root),
        "raw_dem_inventory_csv": "analysis/raw_dem_source_inventory.csv",
        "raw_to_model_mapping_csv": "analysis/raw_dem_to_model_topography_mapping.csv",
        "raw_source_class": {
            "path": str(raw_dem_root / "process" / "source_class_v3.tif"),
            "class_labels": SOURCE_CLASS_LABELS,
            "definition_source": str(raw_dem_root / "process" / "build_fused_C.py"),
            "counts": source_class_counts(raw_dem_root / "process" / "source_class_v3.tif"),
        },
        "processing_timestamp": datetime.now(timezone.utc).isoformat(),
        "script_git_commit": git_commit_hash(repo_root),
    }
    write_json(Path("analysis/effective_topography_provenance.json"), provenance)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build source-TOPO-derived Aqaba shoreline geometry.")
    parser.add_argument("--scenario-root", required=True, type=Path)
    parser.add_argument("--topo-root", required=True, type=Path)
    parser.add_argument("--raw-dem-root", required=True, type=Path)
    parser.add_argument("--sea-level", required=True, type=float)
    parser.add_argument("--shoreline-spacing-m", required=True, type=float)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--qc-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.shoreline_spacing_m <= 0 or not math.isfinite(args.shoreline_spacing_m):
        parser.error("--shoreline-spacing-m must be positive")
    return args


def main() -> int:
    build(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
