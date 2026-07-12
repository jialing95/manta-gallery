#!/usr/bin/env python3
"""Update the MANTA Gallery case registry and generated Quarto case pages."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
CASES_DIR = DOCS_DIR / "cases"
REGISTRY_PATH = CASES_DIR / "cases.json"


CASE_ID_RE = re.compile(r"^[a-z0-9_]+$")


def read_registry() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.is_file():
        return []
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{REGISTRY_PATH} must contain a JSON list")
    return data


def write_registry(cases: list[dict[str, Any]]) -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps(cases, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def upsert_case(cases: list[dict[str, Any]], entry: dict[str, Any]) -> list[dict[str, Any]]:
    for index, existing in enumerate(cases):
        if existing.get("id") == entry["id"]:
            cases[index] = {**existing, **entry}
            return cases
    return [*cases, entry]


def qmd_attr(value: str) -> str:
    return html.escape(value, quote=True)


def case_page(entry: dict[str, Any]) -> str:
    case_id = entry["id"]
    title = entry["title"]
    title_yaml = json.dumps(title, ensure_ascii=False)
    overview = entry["overview"]
    default_frame_index = int(entry.get("default_frame_index", 20))
    return f"""---
title: {title_yaml}
page-layout: full
toc: false
---

::: {{.manta-case-intro}}
## Overview

{overview}
:::

::: {{.manta-case-hero}}
```{{=html}}
<div id="{qmd_attr(case_id)}-viewer" class="manta-viewer" data-case-base-url="../assets/data/demo/{qmd_attr(case_id)}/" data-case-title="{qmd_attr(title)}">
  <div class="manta-viewer-status">
    Loading MANTA Gallery viewer...
  </div>
</div>
<script type="module" src="../assets/js/manta_case_viewer.bundle.js?v=gauges-ui-20260712"></script>
```
:::

<details class="manta-foldout">
<summary>Current export settings</summary>

| Item | Value |
|---|---|
| Source | FORT-native |
| Default display frame | `{default_frame_index}` |
| Frame count | all exported time frames |
| Terrain stride | `5` |
| Water stride | `10` |
| Water coastal detail | Native resolution (`stride = 0`) within `100 m` offshore and `500 m` inland from the `z = 0` coastline |
| Landslide stride | Native resolution (`0`) |
| Projected CRS | `EPSG:32637` (`WGS 84 / UTM zone 37N`) |
| Browser asset format | Compact v2: static `X / Y / quad topology` templates plus gzip-compressed per-frame arrays |
| Water dynamic arrays | `z / wave_amplitude / m / h / u / v` as `Float32`; `b = z - h` and speed are derived in the browser |
| Dynamic array precision | `Float32` |
| Terrain reuse | Single static `terrain.vtp` reused across frames; DEM is not regenerated or updated online during playback. |
| Landslide ROI | Global union over all exported frames |
| Landslide ROI pad | `24` native grid cells |
| Water threshold | default `m <= 0.3`; `m` is preserved for browser-side thresholding |
| Landslide threshold | default `m >= 0.0` |

</details>

<details class="manta-foldout">
<summary>Layer styles</summary>

| Layer | Style |
|---|---|
| DEM bathymetry | Sea-split target: `cmocean.deep`; currently kept as a static gray relief surface. |
| DEM topography | Sea-split target: `cmcrameri.grayC + relief / hillshade`; terrain is exported at higher resolution than water frames. |
| Map overlay | Optional online basemap texture-mapped onto the exported terrain mesh using `EPSG:32637 -> Web Mercator` coordinates. Sources are limited to Esri Imagery + Labels, OpenStreetMap Topographic (OpenTopoMap), and Esri Streets, in that order. |
| Water surface | Scalar = `wave_amplitude`; the Layers readout reports the true global ocean-water range (`b = z - h <= 0`) after the active `water m` filter. The color ramp uses a robust symmetric saturation range so wave colors remain readable, while the colorbar header reports the true current-frame ocean-water range. Inland free-surface geometry remains available for inundation detail. Surface opacity = `1.0`. |
| Inundation overlays | Current-frame and cumulative-maximum inland inundation depth where `b >= 0`, filtered by the active `water m` threshold. |
| Velocity overlays | Current-frame `turbo` velocity arrows use cell-aware lengths and spatial sampling across the water region. Cumulative-maximum wave velocity uses `cmocean.speed` with a `99.5`th-percentile saturation limit, matching the publication postprocessing style. Both are filtered by the active `water m` threshold. |
| Landslide | Scalar selector = `hm / m / Δb`; colormap = `magma`; geometry is draped to the DEM and displayed with a `+5 m` visual lift. |

</details>
"""


def gallery_page(cases: list[dict[str, Any]]) -> str:
    blocks = [
        "---",
        'title: "Gallery"',
        "---",
        "",
        "## Demo cases",
        "",
    ]
    for entry in cases:
        blocks.extend(
            [
                "::: {.case-card}",
                f"### {entry['title']}",
                "",
                entry["card_description"],
                "",
                f"[Open case](cases/{entry['id']}.qmd)",
                ":::",
                "",
            ]
        )
    return "\n".join(blocks)


def render_pages(cases: list[dict[str, Any]]) -> None:
    for entry in cases:
        (CASES_DIR / f"{entry['id']}.qmd").write_text(case_page(entry), encoding="utf-8")
    (DOCS_DIR / "gallery.qmd").write_text(gallery_page(cases), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--card-description", default="")
    parser.add_argument("--overview", default="")
    parser.add_argument("--default-frame-index", type=int, default=20)
    args = parser.parse_args()

    case_id = args.case_id.strip()
    if not CASE_ID_RE.fullmatch(case_id):
        raise SystemExit("case id must contain only lowercase letters, numbers, and underscores")

    title = args.title.strip()
    label = args.label.strip() or title
    card_description = args.card_description.strip() or (
        f"Interactive 3D view of landslide tsunami (case: {label}) in the Gulf of Aqaba."
    )
    overview = args.overview.strip() or (
        f"{title} is an interactive 3D D-Claw landslide-tsunami case for the Gulf of Aqaba. "
        "The viewer combines a static high-resolution topo-bathymetric surface with "
        "time-dependent water height and landslide fields for browser-side exploration."
    )

    entry = {
        "id": case_id,
        "title": title,
        "label": label,
        "card_description": card_description,
        "overview": overview,
        "default_frame_index": int(args.default_frame_index),
    }
    cases = upsert_case(read_registry(), entry)
    write_registry(cases)
    render_pages(cases)
    print(f"[OK] Updated case registry and Quarto pages for {case_id}")


if __name__ == "__main__":
    main()
