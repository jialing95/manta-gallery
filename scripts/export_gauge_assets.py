#!/usr/bin/env python3
"""Export D-Claw gauge time-series text files to compact gallery JSON assets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(
    os.environ.get("AQABA_COMPILE_ROOT")
    or Path(__file__).resolve().parents[2] / "compile_all"
).expanduser().resolve()
GAUGES_GEOJSON = ROOT / "aqaba_scenarios_lsb" / "CSV" / "gauges_manta.geojson"

CASES = {
    "aqaba_lsa_c10_angm25": ROOT / "aqaba_scenarios_lsa" / "results" / "AQA_017_K1_C10_angm25_mixed" / "_output",
    "aqaba_lsb_nc10_angm20": ROOT / "aqaba_scenarios_lsb" / "results" / "AQA_006_K1_NC10_angm20_mixed" / "_output",
    "aqaba_lsc_c10_angm30": ROOT / "aqaba_scenarios_lsc" / "results" / "AQA_018_K1_C10_angm30_mixed" / "_output",
    "aqaba_lsd_nc8_angm40": ROOT / "aqaba_scenarios_lsd" / "results" / "AQA_005_K1_NC8_angm40_mixed" / "_output",
    "aqaba_lse_c10_angm40": ROOT / "aqaba_scenarios_lse" / "results" / "AQA_020_K1_C10_angm40_mixed" / "_output",
    "aqaba_lsf_nc10_angm30": ROOT / "aqaba_scenarios_lsf" / "results" / "AQA_008_K1_NC10_angm30_mixed" / "_output",
}


def round_float(value: float, digits: int) -> float:
    rounded = round(value, digits)
    return 0.0 if rounded == -0.0 else rounded


def read_gauge_locations() -> dict[int, dict[str, object]]:
    data = json.loads(GAUGES_GEOJSON.read_text())
    locations: dict[int, dict[str, object]] = {}
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        coordinates = feature.get("geometry", {}).get("coordinates") or []
        gauge_id = int(props.get("id"))
        locations[gauge_id] = {
            "id": gauge_id,
            "name": str(props.get("name") or f"G{gauge_id:02d}"),
            "gauge_no": int(props.get("gauge_no", gauge_id + 1)),
            "x": round_float(float(coordinates[0]), 3),
            "y": round_float(float(coordinates[1]), 3),
        }
    return locations


def parse_gauge_file(path: Path) -> dict[str, object]:
    time: list[float] = []
    eta: list[float] = []
    levels: set[int] = set()
    eta_min = float("inf")
    eta_max = float("-inf")

    with path.open() as file:
        for line in file:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 10:
                continue
            level = int(parts[0])
            t = float(parts[1])
            value = float(parts[9])
            levels.add(level)
            time.append(round_float(t, 3))
            eta_value = round_float(value, 6)
            eta.append(eta_value)
            eta_min = min(eta_min, eta_value)
            eta_max = max(eta_max, eta_value)

    if not time:
        raise ValueError(f"No gauge samples found in {path}")

    return {
        "time": time,
        "eta": eta,
        "source_count": len(time),
        "levels": sorted(levels),
        "time_range": [time[0], time[-1]],
        "eta_range": [round_float(eta_min, 6), round_float(eta_max, 6)],
    }


def export_case(case_id: str, output_dir: Path, locations: dict[int, dict[str, object]]) -> Path:
    source_dir = CASES[case_id]
    if not source_dir.is_dir():
        raise FileNotFoundError(source_dir)

    gauges = []
    for gauge_file in sorted(source_dir.glob("gauge*.txt")):
        gauge_id = int(gauge_file.stem.replace("gauge", ""))
        location = locations.get(gauge_id)
        if not location:
            raise KeyError(f"Missing location for gauge {gauge_id}")
        series = parse_gauge_file(gauge_file)
        gauges.append({**location, **series})

    if not gauges:
        raise ValueError(f"No gauge files found in {source_dir}")

    payload = {
        "version": 1,
        "case_id": case_id,
        "source": f"{source_dir.parent.name}/_output",
        "crs": "EPSG:32637",
        "variable": {
            "key": "eta",
            "label": "Free-surface elevation",
            "symbol": "eta",
            "unit": "m",
        },
        "gauges": gauges,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{case_id}.json"
    output_path.write_text(json.dumps(payload, separators=(",", ":")))
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/gauges")
    parser.add_argument("--cases", nargs="+", choices=sorted(CASES), default=sorted(CASES))
    args = parser.parse_args()

    locations = read_gauge_locations()
    output_dir = Path(args.output_dir)
    for case_id in args.cases:
        path = export_case(case_id, output_dir, locations)
        print(f"[GAUGES] wrote {path}")


if __name__ == "__main__":
    main()
