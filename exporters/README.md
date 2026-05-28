# MANTA Gallery Exporters

This directory contains scripts for exporting MANTA/PyVista visualization results into gallery-ready web assets.

The first target is a single-frame case export:

```text
terrain.vtp
water/frame_0000.vtp
landslide/frame_0000.vtp
case.json
```

## Data contract

### Water surface

`water/frame_0000.vtp` contains:

- geometry: free surface elevation
- scalar: `wave_amplitude`
- filter field: `m`

The browser viewer should display `wave_amplitude` and filter by:

```text
m <= water_m
```

### Landslide surface

`landslide/frame_0000.vtp` contains:

- `hm`: solid-phase thickness
- `m`: solid volume fraction
