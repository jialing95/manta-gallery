# Shoreline Velocity And Bathymetric Controls

This directory contains offline validation products for viewer-displayed pointwise depth-averaged flow speed hotspots and receiver-side bathymetric controls.

Data lineage:

- Raw DEM provenance and source-class audit come from `/home/daij/Desktop/general/DEM`.
- Shoreline and bathymetric metrics use the model-effective source TOPO in `/home/daij/Desktop/compile_all/aqaba_scenarios_lsa/TOPO/topo-bathy.tt3`.
- Velocity hotspot statistics read the existing viewer compact-v2 water assets from `data/demo/<case-id>/case.json`.
- `terrain.vtp`, `viewer/**`, `docs/**`, `data/demo/**`, `fort.*`, and D-Claw reruns are not used for shoreline or bathymetric metrics.

Terminology: outputs refer to depth-averaged flow speed or viewer-displayed pointwise depth-averaged flow speed; they do not make propagation-speed interpretations.
