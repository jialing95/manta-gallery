# MANTA Gallery Exporters

This directory will contain scripts for exporting MANTA/PyVista visualization results into gallery-ready web assets.

The first target is a single-frame case export:

- `terrain.vtp`
- `water/frame_0000.vtp`
  - scalar: `wave_amplitude`
  - filter field: `m`
- `landslide/frame_0000.vtp`
  - scalars: `hm`, `m`, `db`
- `case.json`
- `thumbnail.png`

The web viewer should not parse raw D-Claw or GeoClaw outputs directly. Raw simulation outputs are processed by MANTA/exporter first, then exported as lightweight gallery-ready files.
