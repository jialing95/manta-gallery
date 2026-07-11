# MANTA Gallery

MANTA Gallery is a collection of 3D PyVista-based interactive visualizations of
landslide tsunamis modeled by D-Claw.

## Build A Case From FORT Output

Use one command from the repository root:

```bash
./scripts/build_case.sh aqaba_lsa_c10 \
  /home/daij/Desktop/compile_all/AQA_020_K1_C10_angm35_mixed \
  --title "Aqaba LSA C10" \
  --label "LSA C10" \
  --frame-index 20 \
  --frame-step 2
```

The input may be either:

- a case root containing `_output/fort.*`
- the output directory that directly contains `fort.q####`, `fort.t####`, and
  `fort.b####`

The command exports compact browser assets to `data/demo/<case-id>/`, writes AMR
sidecars, updates the Gallery and case page, rebuilds the shared viewer bundle,
syncs publish assets, and renders the Quarto site to `docs/_site/`.

Preview the rendered site through a local HTTP server:

```bash
./scripts/preview_site.sh
```

To build and publish in one step:

```bash
./scripts/build_case.sh aqaba_lsa_c10 \
  /home/daij/Desktop/compile_all/AQA_020_K1_C10_angm35_mixed \
  --title "Aqaba LSA C10" \
  --label "LSA C10" \
  --push
```

`--push` stages only that case's canonical assets and generated case/gallery
pages, commits them, and pushes `origin/main`. GitHub Actions rebuilds the shared
viewer bundle and deploys GitHub Pages.

The compatibility wrapper builds the default LSA demo with the compact frame
stride:

```bash
./scripts/build_site.sh /path/to/dclaw-case
```

Override local tool paths when needed:

```bash
./scripts/build_case.sh aqaba_lsa_c10 /path/to/dclaw-case \
  --title "Aqaba LSA C10" \
  --label "LSA C10" \
  --manta-src /path/to/preprocessor \
  --python /path/to/python
```

Raw `fort.*` simulation files remain local. Only curated browser assets under
`data/demo/` are committed.

## Rebuild Without Re-Exporting Data

Only modified viewer code:

```bash
npm run build:viewer
./scripts/sync_demo_assets.sh
quarto render docs
```

Only modified Quarto/Markdown docs:

```bash
quarto render docs
```

Preview:

```bash
./scripts/preview_site.sh
```
