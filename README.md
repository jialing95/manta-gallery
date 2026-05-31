# MANTA Gallery

MANTA Gallery is a collection of 3D PyVista-based interactive visualizations of
landslide tsunamis modeled by D-Claw.

## Build Aqaba LSB C10 From FORT Output

Use one command from the repository root:

```bash
./scripts/build_site.sh /path/to/dclaw-case
```

The input may be either:

- a case root containing `_output/fort.*`
- the output directory that directly contains `fort.q####`, `fort.t####`, and
  `fort.b####`

The command exports compact browser assets, writes AMR sidecars, rebuilds the
viewer bundle, syncs publish assets, and renders the Quarto site to
`docs/_site/`.

Preview the rendered site through a local HTTP server:

```bash
./scripts/preview_site.sh
```

To publish after reviewing the local site, or to build and publish in one step:

```bash
./scripts/build_site.sh /path/to/dclaw-case --push
```

`--push` stages only `data/demo/aqaba_case_001`, commits changed canonical
assets, and pushes `origin/main`. GitHub Actions rebuilds the viewer bundle and
deploys GitHub Pages.

The command defaults to `~/Desktop/preprocessor` for the MANTA source tree and
uses its `.venv/bin/python` when present. Override those paths when needed:

```bash
./scripts/build_site.sh /path/to/dclaw-case \
  --manta-src /path/to/preprocessor \
  --python /path/to/python
```

Raw `fort.*` simulation files remain local. Only curated browser assets under
`data/demo/` are committed.


=========================================

仅修改代码、不修改 FORT 数据时，无需运行耗时的完整导出流程。生成本地网页使用：
```bash
npm run build:viewer
./scripts/sync_demo_assets.sh
quarto render docs
```

预览网页：
```bash
./scripts/preview_site.sh
```

如果仅修改文档`.qmd`，最短命令是：
```bash
quarto render docs
```
