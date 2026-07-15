from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_shoreline_velocity_hotspots.py"
SPEC = importlib.util.spec_from_file_location("analyze_shoreline_velocity_hotspots", SCRIPT_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def compact_layout(arrays: dict[str, np.ndarray]) -> dict[str, dict[str, object]]:
    offset = audit.COMPACT_HEADER.size
    layout: dict[str, dict[str, object]] = {}
    for name, array in arrays.items():
        arr = np.ascontiguousarray(array)
        if arr.dtype.itemsize > 1:
            arr = arr.astype(arr.dtype.newbyteorder("<"), copy=False)
        layout[name] = {
            "dtype": arr.dtype.name,
            "byte_offset": offset,
            "length": int(arr.size),
        }
        if arr.ndim > 1:
            layout[name]["components"] = int(arr.shape[-1])
        offset += int(arr.nbytes)
    return layout


def write_compact(path: Path, arrays: dict[str, np.ndarray]) -> dict[str, object]:
    packed: dict[str, np.ndarray] = {}
    for name, array in arrays.items():
        arr = np.ascontiguousarray(array)
        if arr.dtype.itemsize > 1:
            arr = arr.astype(arr.dtype.newbyteorder("<"), copy=False)
        packed[name] = arr
    payload = b"".join(arr.tobytes(order="C") for arr in packed.values())
    archive = audit.COMPACT_HEADER.pack(
        audit.COMPACT_MAGIC,
        audit.COMPACT_FORMAT_VERSION,
        len(payload),
    ) + payload
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=raw, mtime=0) as gz:
            gz.write(archive)
    return {
        "header_bytes": audit.COMPACT_HEADER.size,
        "uncompressed_bytes": len(archive),
        "compressed_bytes": path.stat().st_size,
        "arrays": compact_layout(packed),
    }


def write_shorelines(path: Path, east_x: float = 0.0, west_x: float = 100.0) -> Path:
    shorelines = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:32637"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"side": "east"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[east_x, -100.0], [east_x, 100.0]],
                },
            },
            {
                "type": "Feature",
                "properties": {"side": "west"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[west_x, -100.0], [west_x, 100.0]],
                },
            },
        ],
    }
    path.write_text(json.dumps(shorelines), encoding="utf-8")
    return path


def base_frame(point_count: int, cell_count: int) -> dict[str, list[float] | list[bool]]:
    return {
        "z": [1.0] * point_count,
        "h": [2.0] * point_count,
        "m": [0.0] * point_count,
        "u": [0.0] * point_count,
        "v": [0.0] * point_count,
        "valid_cells": [True] * cell_count,
    }


def make_case(
    root: Path,
    *,
    case_id: str,
    x: list[float],
    y: list[float],
    quads: list[list[int]],
    frames: list[dict[str, list[float] | list[bool]]],
    time_values: list[float] | None = None,
    velocity_overlay: dict[str, object] | None = None,
    dry_tolerance: float = 0.0005,
) -> Path:
    case_dir = root / case_id
    water_dir = case_dir / "water"
    x_arr = np.asarray(x, dtype=np.float32)
    y_arr = np.asarray(y, dtype=np.float32)
    quads_arr = np.asarray(quads, dtype=np.uint32)
    template_meta = write_compact(water_dir / "template.bin.gz", {"x": x_arr, "y": y_arr, "quads": quads_arr})

    frame_layout = None
    for frame_index, frame in enumerate(frames):
        arrays = {
            "z": np.asarray(frame["z"], dtype=np.float32),
            "m": np.asarray(frame["m"], dtype=np.float32),
            "h": np.asarray(frame["h"], dtype=np.float32),
            "u": np.asarray(frame["u"], dtype=np.float32),
            "v": np.asarray(frame["v"], dtype=np.float32),
            "valid_cells": np.packbits(np.asarray(frame["valid_cells"], dtype=bool), bitorder="big"),
        }
        frame_meta = write_compact(water_dir / f"frame_{frame_index:04d}.bin.gz", arrays)
        frame_layout = frame_meta["arrays"]
        frame_layout["valid_cells"]["bit_order"] = "big"

    overlay = {
        "range": [0.0, 20.0],
        "arrow_stride": 1,
        "arrow_scale": 2.0,
        "arrow_max_count": 100,
        "arrow_min_speed": 0.01,
    }
    if velocity_overlay:
        overlay.update(velocity_overlay)
    times = time_values if time_values is not None else [float(i) for i in range(len(frames))]
    case = {
        "id": case_id,
        "time": {
            "mode": "time_series",
            "unit": "s",
            "values": [float(value) for value in times],
            "frame_count": len(frames),
        },
        "processing": {
            "crs": {"epsg": 32637},
            "sea_level": 0.0,
            "water_surface": {
                "dry_tolerance": dry_tolerance,
                "coastal_detail": {"row_spacing_m": 3.0, "col_spacing_m": 4.0},
            },
        },
        "layers": {
            "water": {
                "default_m": 0.30,
                "analysis_overlays": {"velocity": overlay},
                "compact": {
                    "version": 2,
                    "compression": "gzip",
                    "endianness": "little",
                    "point_count": len(x),
                    "cell_count": len(quads),
                    "template": {"file": "water/template.bin.gz", **template_meta},
                    "frame": {
                        "file_pattern": "water/frame_{frame}.bin.gz",
                        "header_bytes": audit.COMPACT_HEADER.size,
                        "arrays": frame_layout,
                    },
                },
            }
        },
    }
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")
    return case_dir


def run_small_analysis(
    root: Path,
    case_dir: Path,
    shorelines: Path,
    *,
    time_min_values: list[float] | None = None,
    corridors: list[object] | None = None,
    top_n: int = 10,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], Path]:
    out = root / f"out_{case_dir.name}_{len(list(root.glob('out_*')))}"
    frame_rows, hotspot_rows, summary_rows = audit.run_analysis(
        [case_dir],
        shorelines,
        None,
        0.30,
        top_n,
        time_min_values or [0.0],
        corridors or [audit.Corridor(5.0, 5.0)],
        out,
    )
    return frame_rows, hotspot_rows, summary_rows, out


def row_for(
    rows: list[dict[str, object]],
    *,
    side: str = "east",
    zone: str = "combined_coastal",
    frame_index: int | None = None,
    requested: float | None = None,
    seaward: float | None = None,
    landward: float | None = None,
) -> dict[str, object]:
    for row in rows:
        if row.get("side") != side or row.get("zone") != zone:
            continue
        if frame_index is not None and int(row["frame_index"]) != frame_index:
            continue
        if requested is not None and float(row["requested_time_min_s"]) != requested:
            continue
        if seaward is not None and float(row["seaward_distance_m"]) != seaward:
            continue
        if landward is not None and float(row["landward_distance_m"]) != landward:
            continue
        return row
    raise AssertionError(f"missing row for side={side} zone={zone}")


class ShorelineVelocityHotspotTests(unittest.TestCase):
    def test_pointwise_not_cell_centered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shorelines = write_shorelines(root / "shorelines.geojson")
            frame = base_frame(4, 1)
            frame["u"] = [10.0, 0.0, 0.0, 0.0]
            case_dir = make_case(
                root,
                case_id="pointwise",
                x=[1.0, 2.0, 2.0, 1.0],
                y=[0.0, 0.0, 1.0, 1.0],
                quads=[[0, 1, 2, 3]],
                frames=[frame],
            )
            _, hotspots, summary, _ = run_small_analysis(root, case_dir, shorelines)
            combined = next(row for row in summary if row["zone"] == "combined_coastal")
            self.assertAlmostEqual(float(combined["east_global_max_mps"]), 10.0)
            self.assertNotAlmostEqual(float(combined["east_global_max_mps"]), 2.5)
            self.assertEqual(hotspots[0]["point_id"], 0)

    def test_visible_point_mask_matches_viewer_cell_predicate(self) -> None:
        quads = np.asarray([[0, 1, 2, 3], [3, 2, 4, 5]], dtype=np.int64)
        arrays = {
            "m": np.asarray([0.0, 0.0, 0.0, 0.0, 0.9, 0.0], dtype=float),
            "valid_cells": np.asarray([True, True], dtype=bool),
        }
        mask = audit.visible_point_mask_from_water_m(quads, arrays, 0.30)
        self.assertTrue(mask[3])
        self.assertTrue(mask[2])
        self.assertFalse(mask[4])
        self.assertFalse(mask[5])

    def test_global_sampling_before_shoreline_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shorelines = write_shorelines(root / "shorelines.geojson", east_x=0.0, west_x=10.0)
            frame = base_frame(4, 1)
            frame["u"] = [9.0, 8.0, 10.0, 0.0]
            case_dir = make_case(
                root,
                case_id="global_sampling",
                x=[1.0, 9.0, 5.0, 6.0],
                y=[0.0, 10.0, 5.0, 6.0],
                quads=[[0, 1, 2, 3]],
                frames=[frame],
                velocity_overlay={"arrow_max_count": 1},
            )
            frame_rows, _, _, _ = run_small_analysis(root, case_dir, shorelines)
            east = row_for(frame_rows, side="east", zone="combined_coastal")
            west = row_for(frame_rows, side="west", zone="combined_coastal")
            self.assertEqual(east["candidate_count_before_global_sampling"], 3)
            self.assertEqual(west["candidate_count_before_global_sampling"], 3)
            self.assertEqual(east["displayed_arrow_count"], 0)
            self.assertEqual(west["displayed_arrow_count"], 0)

    def test_bucket_maximum_and_tie(self) -> None:
        x = np.asarray([0.0, 0.5, 0.9], dtype=float)
        y = np.asarray([0.0, 0.0, 0.0], dtype=float)
        tied = [audit.Candidate(0, 5.0), audit.Candidate(1, 5.0), audit.Candidate(2, 4.0)]
        self.assertEqual(audit.spatially_sample_velocity_candidates(tied, x, y, 1)[0].point_id, 0)
        higher_later = [audit.Candidate(0, 5.0), audit.Candidate(1, 6.0), audit.Candidate(2, 4.0)]
        self.assertEqual(audit.spatially_sample_velocity_candidates(higher_later, x, y, 1)[0].point_id, 1)

    def test_candidate_count_below_limit_keeps_all(self) -> None:
        candidates = [audit.Candidate(i, float(i)) for i in range(5)]
        x = np.arange(5, dtype=float)
        y = np.zeros(5, dtype=float)
        self.assertEqual(audit.spatially_sample_velocity_candidates(candidates, x, y, 5), candidates)
        self.assertEqual(audit.spatially_sample_velocity_candidates(candidates, x, y, 10), candidates)

    def test_stride_and_minimum_speed_are_viewer_parity(self) -> None:
        arrays = {"u": np.asarray([1.9, 99.0, 2.0, 3.0]), "v": np.zeros(4)}
        options = audit.ArrowOptions(stride=2, scale=1.0, max_count=10, min_speed=2.0, cell_scale=1.0)
        candidates = audit.build_velocity_candidates(np.ones(4, dtype=bool), arrays, options)
        self.assertEqual([candidate.point_id for candidate in candidates], [2])
        self.assertAlmostEqual(candidates[0].speed, 2.0)

    def test_manifest_options_glyph_formula_and_colorbar(self) -> None:
        case = {"processing": {"water_surface": {"coastal_detail": {"row_spacing_m": 7.0, "col_spacing_m": 3.0}}}}
        options = audit.get_velocity_arrow_options(case)
        self.assertEqual(options.stride, 1)
        self.assertEqual(options.max_count, 20000)
        self.assertAlmostEqual(options.scale, 10.0)
        self.assertAlmostEqual(options.min_speed, 0.01)
        self.assertAlmostEqual(options.cell_scale, 3.0)
        self.assertAlmostEqual(5.0 * options.scale * options.cell_scale, 150.0)

        configured = {
            "layers": {
                "water": {
                    "analysis_overlays": {
                        "velocity": {
                            "arrow_stride": 2.4,
                            "arrow_scale": 5.0,
                            "arrow_max_count": 12.6,
                            "arrow_min_speed": 0.5,
                            "range": [-3.0, 12.0],
                        }
                    }
                }
            },
            "processing": {"water_surface": {"coastal_detail": {"row_spacing_m": 8.0, "col_spacing_m": 4.0}}},
        }
        options = audit.get_velocity_arrow_options(configured)
        self.assertEqual(options.stride, 2)
        self.assertEqual(options.max_count, 13)
        self.assertAlmostEqual(options.scale, 5.0)
        self.assertAlmostEqual(options.min_speed, 0.5)
        self.assertAlmostEqual(options.cell_scale, 4.0)
        self.assertEqual(audit.get_velocity_colorbar_range(configured), (0.0, 12.0))
        self.assertAlmostEqual(audit.colorbar_fraction(6.0, (0.0, 12.0)), 0.5)
        self.assertTrue(audit.colorbar_saturated(12.0, (0.0, 12.0)))

    def test_point_to_polyline_distance_segment_and_endpoint(self) -> None:
        line = [np.asarray([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]], dtype=float)]
        starts, ends = audit.flatten_line_segments(line)
        dist = audit.point_to_segments_distance_chunked(
            np.asarray([5.0, 13.0, 10.0]),
            np.asarray([3.0, 10.0, 5.0]),
            starts,
            ends,
            chunk_size=2,
        )
        np.testing.assert_allclose(dist, [3.0, 3.0, 0.0])

    def test_nearest_assignment_ambiguity_zones_and_overlap(self) -> None:
        b0 = np.asarray([-1.0, 1.0, -1.0, -1.0, -1.0])
        east_dist = np.asarray([1.0, 8.0, 5.0, 40.0, 4.0])
        west_dist = np.asarray([9.0, 2.0, 5.0, 30.0, 6.0])
        info = audit.classify_coastal_points(
            b0,
            0.0,
            east_dist,
            west_dist,
            audit.Corridor(8.0, 3.0),
        )
        self.assertEqual(info["side"][0], "east")
        self.assertEqual(info["static_zone"][0], "seaward")
        self.assertEqual(info["side"][1], "west")
        self.assertEqual(info["static_zone"][1], "landward")
        self.assertEqual(info["side"][2], "ambiguous")
        self.assertEqual(info["static_zone"][2], "ambiguous")
        self.assertEqual(info["side"][3], "outside")
        self.assertEqual(info["static_zone"][3], "outside")
        self.assertEqual(info["side"][4], "east")
        self.assertEqual(int(info["overlap_resolution_count"][0]), 1)

    def test_dynamic_inundation_excludes_dry_landward_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shorelines = write_shorelines(root / "shorelines.geojson")
            frame0 = base_frame(4, 1)
            frame0["z"] = [0.501, 1.0, 1.0, 1.0]
            frame0["h"] = [0.001, 2.0, 2.0, 2.0]
            frame0["u"] = [5.0, 0.0, 0.0, 0.0]
            frame1 = base_frame(4, 1)
            frame1["z"] = [0.6, 1.0, 1.0, 1.0]
            frame1["h"] = [0.1, 2.0, 2.0, 2.0]
            frame1["u"] = [7.0, 0.0, 0.0, 0.0]
            case_dir = make_case(
                root,
                case_id="dynamic_landward",
                x=[1.0, 2.0, 3.0, 4.0],
                y=[0.0, 0.0, 1.0, 1.0],
                quads=[[0, 1, 2, 3]],
                frames=[frame0, frame1],
                dry_tolerance=0.01,
            )
            frame_rows, _, _, _ = run_small_analysis(root, case_dir, shorelines)
            self.assertEqual(
                row_for(frame_rows, zone="landward_inundated", frame_index=0)["displayed_arrow_count"],
                0,
            )
            wet_row = row_for(frame_rows, zone="landward_inundated", frame_index=1)
            self.assertEqual(wet_row["displayed_arrow_count"], 1)
            self.assertTrue(wet_row["displayed_max_dynamic_wet"])

    def test_static_zone_uses_frame0_even_when_later_bed_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shorelines = write_shorelines(root / "shorelines.geojson")
            frame0 = base_frame(4, 1)
            frame0["z"] = [1.0, 1.0, 1.0, 1.0]
            frame0["h"] = [2.0, 2.0, 2.0, 2.0]
            frame1 = base_frame(4, 1)
            frame1["z"] = [2.0, 1.0, 1.0, 1.0]
            frame1["h"] = [1.0, 2.0, 2.0, 2.0]
            frame1["u"] = [6.0, 0.0, 0.0, 0.0]
            case_dir = make_case(
                root,
                case_id="static_zone",
                x=[1.0, 2.0, 3.0, 4.0],
                y=[0.0, 0.0, 1.0, 1.0],
                quads=[[0, 1, 2, 3]],
                frames=[frame0, frame1],
            )
            frame_rows, _, _, _ = run_small_analysis(root, case_dir, shorelines, time_min_values=[1.0])
            seaward = row_for(frame_rows, zone="seaward", frame_index=1)
            landward = row_for(frame_rows, zone="landward_inundated", frame_index=1)
            self.assertEqual(seaward["displayed_arrow_count"], 1)
            self.assertEqual(landward["displayed_arrow_count"], 0)
            self.assertEqual(seaward["displayed_max_static_zone"], "seaward")

    def test_time_window_inclusive_and_missing_exact_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shorelines = write_shorelines(root / "shorelines.geojson")
            frames = []
            for speed in [1.0, 2.0, 3.0, 4.0]:
                frame = base_frame(4, 1)
                frame["u"] = [speed, 0.0, 0.0, 0.0]
                frames.append(frame)
            exact_case = make_case(
                root,
                case_id="exact_time",
                x=[1.0, 2.0, 3.0, 4.0],
                y=[0.0, 0.0, 1.0, 1.0],
                quads=[[0, 1, 2, 3]],
                frames=frames,
                time_values=[0.0, 900.0, 1200.0, 1500.0],
            )
            _, _, exact_summary, _ = run_small_analysis(root, exact_case, shorelines, time_min_values=[900.0])
            exact = next(row for row in exact_summary if row["zone"] == "combined_coastal")
            self.assertEqual(float(exact["effective_first_selected_time_s"]), 900.0)
            self.assertEqual(int(exact["selected_frame_count"]), 3)

            missing_case = make_case(
                root,
                case_id="missing_time",
                x=[1.0, 2.0, 3.0, 4.0],
                y=[0.0, 0.0, 1.0, 1.0],
                quads=[[0, 1, 2, 3]],
                frames=frames[:3],
                time_values=[0.0, 840.0, 960.0],
            )
            _, _, missing_summary, _ = run_small_analysis(root, missing_case, shorelines, time_min_values=[900.0])
            missing = next(row for row in missing_summary if row["zone"] == "combined_coastal")
            self.assertEqual(float(missing["effective_first_selected_time_s"]), 960.0)
            self.assertEqual(int(missing["selected_frame_count"]), 1)

    def test_window_specific_hotspot_reranking_and_independent_recurrence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shorelines = write_shorelines(root / "shorelines.geojson")
            speeds = [
                [0.0, 0.0, 0.0, 0.0],
                [100.0, 0.0, 0.0, 0.0],
                [0.0, 50.0, 0.0, 0.0],
                [0.0, 50.0, 0.0, 0.0],
            ]
            frames = []
            for values in speeds:
                frame = base_frame(4, 1)
                frame["u"] = values
                frames.append(frame)
            case_dir = make_case(
                root,
                case_id="windows",
                x=[1.0, 2.0, 3.0, 4.0],
                y=[0.0, 0.0, 1.0, 1.0],
                quads=[[0, 1, 2, 3]],
                frames=frames,
                time_values=[0.0, 900.0, 1200.0, 1500.0],
            )
            _, hotspots, summary, _ = run_small_analysis(
                root,
                case_dir,
                shorelines,
                time_min_values=[900.0, 1200.0, 1500.0],
                top_n=1,
            )
            top900 = next(row for row in hotspots if float(row["requested_time_min_s"]) == 900.0 and row["zone"] == "combined_coastal")
            top1200 = next(row for row in hotspots if float(row["requested_time_min_s"]) == 1200.0 and row["zone"] == "combined_coastal")
            top1500 = next(row for row in hotspots if float(row["requested_time_min_s"]) == 1500.0 and row["zone"] == "combined_coastal")
            self.assertEqual(top900["point_id"], 0)
            self.assertEqual(top1200["point_id"], 1)
            self.assertEqual(top1500["point_id"], 1)
            self.assertEqual(top900["displayed_frame_count"], 1)
            self.assertEqual(top1200["displayed_frame_count"], 2)
            self.assertEqual(top1500["displayed_frame_count"], 1)
            combined1200 = next(
                row for row in summary
                if float(row["requested_time_min_s"]) == 1200.0 and row["zone"] == "combined_coastal"
            )
            self.assertEqual(int(combined1200["east_topN_recurrent_ge_2_frames"]), 1)

    def test_zone_separated_statistics_and_combined_union(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shorelines = write_shorelines(root / "shorelines.geojson")
            frame = base_frame(4, 1)
            frame["z"] = [1.0, 2.0, 1.0, 1.0]
            frame["h"] = [2.0, 1.0, 2.0, 2.0]
            frame["u"] = [4.0, 8.0, 0.0, 0.0]
            case_dir = make_case(
                root,
                case_id="zones",
                x=[1.0, 2.0, 3.0, 4.0],
                y=[0.0, 0.0, 1.0, 1.0],
                quads=[[0, 1, 2, 3]],
                frames=[frame],
                dry_tolerance=0.01,
            )
            frame_rows, _, _, _ = run_small_analysis(root, case_dir, shorelines)
            seaward = row_for(frame_rows, zone="seaward")
            landward = row_for(frame_rows, zone="landward_inundated")
            combined = row_for(frame_rows, zone="combined_coastal")
            self.assertEqual(seaward["displayed_arrow_count"], 1)
            self.assertAlmostEqual(float(seaward["displayed_speed_max_mps"]), 4.0)
            self.assertEqual(landward["displayed_arrow_count"], 1)
            self.assertAlmostEqual(float(landward["displayed_speed_max_mps"]), 8.0)
            self.assertEqual(combined["displayed_arrow_count"], 2)
            self.assertAlmostEqual(float(combined["displayed_top10_mean_speed_mps"]), 6.0)

    def test_output_semantics_and_no_data_demo_files(self) -> None:
        data_demo = REPO_ROOT / "data" / "demo"
        before = set(data_demo.rglob("*")) if data_demo.exists() else set()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shorelines = write_shorelines(root / "shorelines.geojson")
            frame = base_frame(4, 1)
            frame["u"] = [2.0, 3.0, 4.0, 5.0]
            case_dir = make_case(
                root,
                case_id="semantics",
                x=[1.0, 2.0, 3.0, 4.0],
                y=[0.0, 0.0, 1.0, 1.0],
                quads=[[0, 1, 2, 3]],
                frames=[frame],
            )
            _, _, _, out = run_small_analysis(root, case_dir, shorelines)
            self.assertEqual(
                sorted(path.name for path in out.iterdir()),
                [
                    "frame_summary.csv",
                    "hotspots.csv",
                    "shoreline_mask_qc.geojson",
                    "shoreline_mask_qc.pdf",
                    "summary.csv",
                    "validation.txt",
                ],
            )
            combined_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in out.iterdir()
                if path.suffix != ".pdf"
            )
            for forbidden in (
                "east_" + "J_U",
                "west_" + "J_U",
                "east_" + "J_q",
                "west_" + "J_q",
                "trape" + "zoidal",
                "time_" + "integral",
                "area_" + "weighted",
                "q_area_" + "weighted_" + "p95",
                "wave " + "celerity",
                "energy " + "trapping",
                "channel" + "ization",
            ):
                self.assertNotIn(forbidden, combined_text)
            self.assertIn("Values: pointwise depth-averaged flow speed", combined_text)
            with (out / "summary.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["case_id"], "semantics")
        after = set(data_demo.rglob("*")) if data_demo.exists() else set()
        self.assertEqual(before, after)

    def test_repository_cleanliness(self) -> None:
        old_audit = "audit_" + "velocity_arrow_hotspots.py"
        old_validator = "validate_" + "velocity_asymmetry.py"
        old_validator_test = "test_" + old_validator
        old_mask = "aqaba_" + "east_west.geojson"
        self.assertTrue((REPO_ROOT / "scripts" / "analyze_shoreline_velocity_hotspots.py").exists())
        self.assertFalse((REPO_ROOT / "scripts" / old_audit).exists())
        self.assertFalse((REPO_ROOT / "scripts" / old_validator).exists())
        self.assertFalse((REPO_ROOT / "tests" / old_validator_test).exists())
        self.assertFalse((REPO_ROOT / "analysis" / old_mask).exists())
        scripts = list((REPO_ROOT / "scripts").glob("*velocity*hotspot*.py"))
        self.assertEqual([path.name for path in scripts], ["analyze_shoreline_velocity_hotspots.py"])
        script_text = (REPO_ROOT / "scripts" / "analyze_shoreline_velocity_hotspots.py").read_text(encoding="utf-8")
        self.assertNotIn("terrain.vtp", script_text)


if __name__ == "__main__":
    unittest.main()
