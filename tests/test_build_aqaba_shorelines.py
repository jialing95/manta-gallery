from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_aqaba_shorelines.py"
SPEC = importlib.util.spec_from_file_location("build_aqaba_shorelines", SCRIPT_PATH)
builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def write_tt3(path: Path, grid_top_to_bottom: np.ndarray, nodata: float = -9999.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nrows, ncols = grid_top_to_bottom.shape
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{ncols} ncols\n")
        handle.write(f"{nrows} nrows\n")
        handle.write("0 xllcenter\n")
        handle.write("0 yllcenter\n")
        handle.write("1 1 cellsize\n")
        handle.write(f"{nodata} nodata_value\n")
        for row in grid_top_to_bottom:
            handle.write(" ".join(str(float(v)) for v in row) + "\n")
    return path


class BuildAqabaShorelinesTests(unittest.TestCase):
    def test_model_topo_configuration_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setrun = root / "templates" / "mixed" / "setrun.py"
            setrun.parent.mkdir(parents=True)
            setrun.write_text(
                "topofiles.append([3, topo_path])\n"
                "topofiles.append([3, b_path])\n",
                encoding="utf-8",
            )
            self.assertEqual(
                builder.parse_topofile_order(setrun),
                ["TOPO/topo-bathy.tt3", "case-local tt3/b.tt3"],
            )

    def test_referenced_vs_unreferenced_topo_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TOPO").mkdir()
            write_tt3(root / "TOPO" / "topo-bathy.tt3", np.zeros((2, 2)))
            write_tt3(root / "TOPO" / "plot-only.tt3", np.zeros((2, 2)))
            setrun = root / "templates" / "mixed" / "setrun.py"
            setrun.parent.mkdir(parents=True)
            setrun.write_text("topofiles.append([3, topo_path])\n", encoding="utf-8")
            config = builder.discover_model_configuration(root, root / "TOPO")
            self.assertIn("topo-bathy.tt3", str(config["shared_topo"]))
            self.assertNotIn("plot-only", str(config["effective_topography_file_order"]))

    def test_nodata_handling_and_source_interpolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tt3(Path(tmp) / "a.tt3", np.asarray([[1, 2], [-9999, 4]], dtype=float))
            header = builder.read_tt3_header(path)
            grid = builder.read_tt3_grid_bottom_to_top(path, header)
            value = builder.sample_grid_bilinear(grid, header, np.asarray([0.1]), np.asarray([0.1]))
            self.assertTrue(np.isnan(value[0]))

    def test_source_file_hash_manifest_and_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tt3(Path(tmp) / "a.tt3", np.zeros((3, 4)))
            header = builder.read_tt3_header(path)
            digest = builder.sha256_file(path)
            rows = builder.manifest_rows(
                Path(tmp),
                {
                    "model_configuration_files": ["setrun.py"],
                    "effective_topography_file_order": {"setrun.py": ["TOPO/topo-bathy.tt3"]},
                    "shared_topo": path,
                    "local_b_files": [],
                },
                header,
                digest,
            )
            self.assertEqual(rows[0]["sha256"], digest)
            self.assertEqual(rows[0]["dx"], 1.0)
            self.assertTrue(rows[0]["used_by_model"])

    def test_topology_contour_split_resampling_and_qc(self) -> None:
        west = np.column_stack((np.zeros(30), np.linspace(0, 2900, 30)))
        north = np.column_stack((np.linspace(0, 1000, 10), np.full(10, 2900.0)))
        east = np.column_stack((np.full(30, 1000.0), np.linspace(2900, 0, 30)))
        principal = np.vstack((west, north[1:], east[1:]))
        w, e, _ = builder.choose_lateral_shorelines([principal], 100.0)
        self.assertLess(abs(builder.line_length(w) - builder.line_length(e)), 500.0)
        self.assertFalse(builder.self_intersects(w))
        self.assertLessEqual(float(np.max(builder.segment_lengths(w))), 100.1)
        self.assertLessEqual(w[0, 1], w[-1, 1])
        self.assertLessEqual(e[0, 1], e[-1, 1])

    def test_contour_edge_residual_gate_uses_strict_thresholds(self) -> None:
        header = builder.TT3Header(2, 2, 0.0, 0.0, 1.0, 1.0, -9999.0)
        west = np.asarray([[0.0, 0.0], [0.0, 100.0], [0.0, 200.0]])
        east = np.asarray([[1.0, 0.0], [1.0, 100.0], [1.0, 200.0]])
        rows = builder.qc_metrics(west, east, np.zeros((2, 2)), header, 0.0, "synthetic")
        self.assertEqual(rows[0]["median_contour_edge_residual_m"], 0.0)
        self.assertEqual(rows[0]["p95_contour_edge_residual_m"], 0.0)
        self.assertEqual(rows[0]["max_contour_edge_residual_m"], 0.0)
        ok, failures = builder.hard_gate(rows)
        self.assertTrue(ok, failures)

    def test_safe_clean_guard_accepts_only_canonical_analysis_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "manta-gallery"
            analysis = repo / "analysis"
            analysis.mkdir(parents=True)
            builder.assert_safe_analysis_clean_target(repo, analysis)
            with self.assertRaises(ValueError):
                builder.assert_safe_analysis_clean_target(repo, repo / "docs")
            with self.assertRaises(ValueError):
                builder.assert_safe_analysis_clean_target(Path(tmp) / "other", analysis)

    def test_raw_to_model_source_class_mapping_labels(self) -> None:
        self.assertEqual(builder.SOURCE_CLASS_LABELS[4]["raw_source_id"], "ribot_multibeam_core")
        self.assertEqual(builder.SOURCE_CLASS_LABELS[5]["raw_source_id"], "gmrt_core")
        self.assertEqual(builder.SOURCE_CLASS_LABELS[2]["source_overlap_count"], 2)

    def test_readme_provenance_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "README.md"
            builder.write_readme(path, Path("/raw/DEM"), Path("/model/TOPO"))
            text = path.read_text(encoding="utf-8")
            self.assertIn("Raw DEM provenance", text)
            self.assertIn("model-effective source TOPO", text)
            self.assertIn("compact-v2 water assets", text)
            self.assertIn("depth-averaged flow speed", text)
            self.assertIn("propagation-speed interpretations", text)

    def test_write_json_sanitizes_nan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.json"
            builder.write_json(path, {"x": float("nan")})
            self.assertIsNone(json.loads(path.read_text(encoding="utf-8"))["x"])

    def test_hard_gate_length_ratio_failure(self) -> None:
        rows = [
            {"side": "west", "length_m": 100.0, "median_segment_length_m": 100.0, "max_segment_length_m": 100.0, "duplicated_vertices": 0, "zero_length_segments": 0, "self_intersection": False, "max_source_elevation_residual_m": 0.0, "y_min": 0.0, "y_max": 10.0, "east_west_length_ratio": 2.0},
            {"side": "east", "length_m": 200.0, "median_segment_length_m": 100.0, "max_segment_length_m": 100.0, "duplicated_vertices": 0, "zero_length_segments": 0, "self_intersection": False, "max_source_elevation_residual_m": 0.0, "y_min": 0.0, "y_max": 10.0, "east_west_length_ratio": 2.0},
        ]
        ok, failures = builder.hard_gate(rows)
        self.assertFalse(ok)
        self.assertTrue(any("length ratio" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
