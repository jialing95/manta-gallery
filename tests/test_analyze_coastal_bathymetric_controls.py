from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_coastal_bathymetric_controls.py"
SPEC = importlib.util.spec_from_file_location("analyze_coastal_bathymetric_controls", SCRIPT_PATH)
controls = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = controls
SPEC.loader.exec_module(controls)


def source_from_grid(grid: np.ndarray) -> controls.SourceTopography:
    return controls.SourceTopography(
        grid=grid,
        ncols=grid.shape[1],
        nrows=grid.shape[0],
        xllcenter=0.0,
        yllcenter=0.0,
        dx=1.0,
        dy=1.0,
        source_topo_id="synthetic",
        native_dx_m=1.0,
        native_dy_m=1.0,
        effective_resolution_m=1.0,
        sea_level=0.0,
    )


class IdentityTransformer:
    def TransformPoint(self, x: float, y: float) -> tuple[float, float, float]:
        return x, y, 0.0


def raw_map_from_array(array: np.ndarray, pixel_size: float = 1.0) -> controls.RawSourceMap:
    return controls.RawSourceMap(
        path=Path("synthetic_source_class.tif"),
        array=array,
        geotransform=(0.0, pixel_size, 0.0, 0.0, 0.0, pixel_size),
        inv_geotransform=(0.0, 1.0 / pixel_size, 0.0, 0.0, 0.0, 1.0 / pixel_size),
        transformer=IdentityTransformer(),
        pixel_size_m=pixel_size,
    )


class CoastalBathymetricControlsTests(unittest.TestCase):
    def test_source_topography_interpolation(self) -> None:
        source = source_from_grid(np.asarray([[0.0, 1.0], [2.0, 3.0]]))
        value = controls.sample_source(source, np.asarray([0.5]), np.asarray([0.5]))
        self.assertAlmostEqual(value[0], 1.5)

    def test_cross_shore_normal_flips_to_water(self) -> None:
        grid = np.tile(np.linspace(5.0, -5.0, 11), (11, 1))
        source = source_from_grid(grid)
        points = np.asarray([[5.0, 5.0]])
        tangents = np.asarray([[0.0, 1.0]])
        normals = controls.choose_seaward_normals(source, points, tangents, 2.0)
        self.assertGreater(normals[0, 0], 0.0)

    def test_distance_to_isobath(self) -> None:
        distances = np.asarray([0.0, 100.0, 200.0])
        bed = np.asarray([0.0, -10.0, -20.0])
        self.assertAlmostEqual(controls.distance_to_isobath(distances, bed, 0.0, 5.0), 50.0)

    def test_slope_bands(self) -> None:
        distances = np.asarray([0.0, 100.0])
        bed = np.asarray([0.0, -10.0])
        self.assertAlmostEqual(controls.slope_band(distances, bed, 0.0, 100.0), 0.1)

    def test_channel_anomaly_metric_row(self) -> None:
        station = {
            "side": "east",
            "station_id": "east_0001",
            "alongshore_distance_m": 0.0,
            "x_m": 0.0,
            "y_m": 0.0,
            "shoreline_curvature": 0.0,
            "source_topo_id_at_shoreline": "synthetic",
            "native_resolution_m_at_shoreline": 1.0,
            "effective_resolution_m_at_shoreline": 1.0,
        }
        row = controls.metric_row(
            station,
            np.asarray([0.0, 100.0, 200.0]),
            np.asarray([0.0, -10.0, -20.0]),
            0.0,
            "native",
            0.0,
            {100.0: 2.0},
        )
        self.assertAlmostEqual(row["depth_at_100m_offshore"], 10.0)
        self.assertAlmostEqual(row["channel_anomaly_100m"], 2.0)

    def test_velocity_decomposition(self) -> None:
        tangent = np.asarray([1.0, 0.0])
        normal = np.asarray([0.0, 1.0])
        velocity = np.asarray([3.0, 4.0])
        self.assertAlmostEqual(float(np.dot(velocity, tangent)), 3.0)
        self.assertAlmostEqual(float(np.dot(velocity, normal)), 4.0)

    def test_spearman_and_bootstrap_are_reproducible(self) -> None:
        x = [1, 2, 3, 4, 5, 6]
        y = [2, 4, 6, 8, 10, 12]
        self.assertAlmostEqual(controls.spearman(x, y), 1.0)
        ci1 = controls.bootstrap_ci(x, y, [0, 0, 1, 1, 2, 2])
        ci2 = controls.bootstrap_ci(x, y, [0, 0, 1, 1, 2, 2])
        self.assertEqual(ci1, ci2)

    def test_common_scale_processing(self) -> None:
        values = np.asarray([0.0, 10.0, 0.0])
        smooth = controls.smooth_values(values, spacing=1.0, scale=3.0)
        self.assertEqual(smooth[0], values[0])
        self.assertLess(smooth[1], values[1])

    def test_read_shorelines_flips_south_to_north(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shorelines.geojson"
            path.write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"side": "east"}, "geometry": {"type": "LineString", "coordinates": [[0, 10], [0, 0]]}},
                    {"type": "Feature", "properties": {"side": "west"}, "geometry": {"type": "LineString", "coordinates": [[1, 0], [1, 10]]}},
                ],
            }), encoding="utf-8")
            lines = controls.read_shorelines(path)
            self.assertLessEqual(lines["east"][0, 1], lines["east"][-1, 1])
            self.assertLessEqual(lines["west"][0, 1], lines["west"][-1, 1])

    def test_raw_source_classification_and_boundary_distance(self) -> None:
        arr = np.full((7, 7), 4, dtype=np.uint8)
        arr[:, 5:] = 5
        raw = raw_map_from_array(arr, pixel_size=30.0)
        info = controls.raw_source_info(raw, 90.0, 90.0, search_radius_m=300.0)
        self.assertEqual(info["raw_source_id"], "ribot_multibeam_core")
        self.assertEqual(info["raw_source_multibeam"], "true")
        self.assertTrue(np.isfinite(info["distance_to_raw_source_boundary_m"]))
        self.assertGreater(info["distance_to_raw_source_boundary_m"], 0.0)

    def test_true_isobath_tangent_differs_from_shoreline_tangent(self) -> None:
        yy, xx = np.mgrid[0:20, 0:20]
        source = source_from_grid(-(xx + yy).astype(float))
        gradient = controls.source_gradient(source, 10.0, 10.0)
        isobath_tangent = controls.unit_or_nan(np.asarray([-gradient[1], gradient[0]]))
        shoreline_tangent = np.asarray([0.0, 1.0])
        self.assertGreater(controls.unsigned_angle_deg(isobath_tangent, shoreline_tangent), 1.0)

    def test_matched_bins_uses_normalized_xi(self) -> None:
        stations = [
            {"side": "east", "station_id": "east_0000", "alongshore_distance_m": 0.0, "normalized_along_gulf_coordinate": 0.0},
            {"side": "east", "station_id": "east_0001", "alongshore_distance_m": 50.0, "normalized_along_gulf_coordinate": 0.5},
            {"side": "west", "station_id": "west_0000", "alongshore_distance_m": 0.0, "normalized_along_gulf_coordinate": 0.0},
            {"side": "west", "station_id": "west_0001", "alongshore_distance_m": 100.0, "normalized_along_gulf_coordinate": 0.5},
        ]
        metrics = [
            {"station_id": "east_0000", "distance_to_20m_isobath": 1, "raw_source_id": "a"},
            {"station_id": "east_0001", "distance_to_20m_isobath": 2, "raw_source_id": "a"},
            {"station_id": "west_0000", "distance_to_20m_isobath": 3, "raw_source_id": "b"},
            {"station_id": "west_0001", "distance_to_20m_isobath": 4, "raw_source_id": "b"},
        ]
        rows = controls.matched_bins(stations, metrics, [])
        second = next(row for row in rows if row["east_station_id"] == "east_0001")
        self.assertEqual(second["west_station_id"], "west_0001")
        self.assertAlmostEqual(second["xi_mismatch"], 0.0)

    def test_common_scale_channel_metrics_are_computed(self) -> None:
        width = 1105
        grid = -0.01 * np.tile(np.arange(width, dtype=float), (30, 1))
        grid[5, :] -= 5.0
        source = source_from_grid(grid)
        stations = []
        for idx, y in enumerate((5.0, 15.0)):
            stations.append({
                "side": "east",
                "station_id": f"east_{idx:04d}",
                "station_index": idx,
                "alongshore_distance_m": idx * 100.0,
                "normalized_along_gulf_coordinate": idx,
                "x_m": 0.0,
                "y_m": y,
                "shoreline_tangent_x": 0.0,
                "shoreline_tangent_y": 1.0,
                "seaward_normal_x": 1.0,
                "seaward_normal_y": 0.0,
                "shoreline_curvature": 0.0,
                "source_topo_id_at_shoreline": "synthetic",
                "native_resolution_m_at_shoreline": 1.0,
                "effective_resolution_m_at_shoreline": 1.0,
                "model_grid_spacing_m": 1.0,
            })
        native, common, _ = controls.compute_metrics(source, stations, 1000.0, 100.0, [300.0])
        self.assertTrue(any(float(row["integrated_positive_channel_anomaly_0_1000m"]) > 0.0 for row in native))
        self.assertTrue(any(float(row["integrated_positive_channel_anomaly_0_1000m"]) > 0.0 for row in common))
        self.assertTrue(all("channel_persistence_scale_count" in row for row in common))

    def test_mechanism_summary_is_conservative(self) -> None:
        text = controls.mechanism_summary_text([
            {
                "predictor": "integrated_channel_anomaly_0_1000m",
                "representation": "native",
                "raw_source_class_subset": "all",
                "matched_resolution_subset": "all",
                "spearman_rho": 0.1,
            },
            {
                "predictor": "integrated_channel_anomaly_0_1000m",
                "representation": "common",
                "raw_source_class_subset": "all",
                "matched_resolution_subset": "all",
                "spearman_rho": -0.1,
            },
        ])
        self.assertIn("Energy trapping was not evaluated", text)
        self.assertIn("resolution-confounded", text)
        self.assertNotIn("channel" + "ization", text.lower())

    def test_figures_are_distinct_nonempty_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            shorelines = {
                "east": np.asarray([[0.0, 0.0], [0.0, 100.0]]),
                "west": np.asarray([[10.0, 0.0], [10.0, 100.0]]),
            }
            stations = []
            metrics = []
            for side, x in (("east", 0.0), ("west", 10.0)):
                for idx, y in enumerate((0.0, 50.0, 100.0)):
                    sid = f"{side}_{idx:04d}"
                    station = {
                        "side": side,
                        "station_id": sid,
                        "x_m": x,
                        "y_m": y,
                        "seaward_normal_x": 1.0 if side == "east" else -1.0,
                        "seaward_normal_y": 0.0,
                        "raw_source_id": "ribot_multibeam_core" if side == "east" else "gmrt_core",
                    }
                    stations.append(station)
                    metrics.append({
                        "side": side,
                        "station_id": sid,
                        "normalized_along_gulf_coordinate": idx / 2.0,
                        "distance_to_20m_isobath": 20.0 + idx,
                        "mean_abs_slope_0_250m": 0.01 * (idx + 1),
                        "integrated_positive_channel_anomaly_0_1000m": float(idx),
                    })
            joined = [{"x_m": 0.0, "y_m": 50.0, "max_displayed_speed_mps": 3.0}]
            associations = [{
                "predictor": "distance_to_source_boundary",
                "side": "east",
                "spearman_rho": 0.2,
                "boundary_exclusion_m": 0.0,
                "raw_source_class_subset": "all",
            }]
            transects = [
                {"station_id": "east_0080", "side": "east", "distance_offshore_m": d, "water_depth_m": d / 10.0}
                for d in (0.0, 100.0, 200.0)
            ]
            controls.write_simple_figures(out, shorelines, stations, metrics, metrics, [], joined, associations, transects)
            pdfs = sorted(out.glob("*.pdf"))
            self.assertEqual(len(pdfs), 7)
            sizes = [path.stat().st_size for path in pdfs]
            self.assertTrue(all(size > 1000 for size in sizes))
            self.assertGreater(len(set(sizes)), 3)


if __name__ == "__main__":
    unittest.main()
