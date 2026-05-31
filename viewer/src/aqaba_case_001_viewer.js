import '@kitware/vtk.js/Rendering/Profiles/Geometry';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader';
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData';
import vtkPoints from '@kitware/vtk.js/Common/Core/Points';
import vtkCellArray from '@kitware/vtk.js/Common/Core/CellArray';
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray';

import vtkRenderer from '@kitware/vtk.js/Rendering/Core/Renderer';
import vtkRenderWindow from '@kitware/vtk.js/Rendering/Core/RenderWindow';
import vtkOpenGLRenderWindow from '@kitware/vtk.js/Rendering/OpenGL/RenderWindow';
import vtkRenderWindowInteractor from '@kitware/vtk.js/Rendering/Core/RenderWindowInteractor';
import vtkInteractorStyleTrackballCamera from '@kitware/vtk.js/Interaction/Style/InteractorStyleTrackballCamera';

const VIEWER_ID = 'aqaba-viewer';

const CASE_BASE_URL = new URL('../data/demo/aqaba_case_001/', import.meta.url);
const CASE_JSON_URL = new URL('case.json', CASE_BASE_URL);

const state = {
  caseInfo: null,
  renderer: null,
  renderWindow: null,
  openGLRenderWindow: null,
  interactor: null,
  actors: {
    terrain: null,
    water: null,
    landslide: null,
  },
  datasets: {
    terrain: null,
    water: null,
    landslide: null,
  },
  rawDatasets: {
    water: null,
    landslide: null,
  },
  compact: {
    enabled: false,
    templates: {
      water: null,
      landslide: null,
    },
    currentFrames: {
      water: null,
      landslide: null,
    },
  },
  scalarInfo: {
    water: null,
    landslide: null,
  },
  currentFrameIndex: 0,
  frameCount: 1,
  frameCache: new Map(),
  maxCachedFrames: 7,
  isFrameLoading: false,
  queuedFrameIndex: null,
  isScrubbing: false,
  isPlaying: false,
  playTimer: null,
  playIntervalMs: 520,
  activeLandslideScalar: 'hm',
  mThresholds: {
    waterMax: 0.30,
    landslideMin: -0.01,
  },
  amrCache: new Map(),
  amrVisible: false,
  amrActors: new Map(),
  amrLoadToken: 0,
};

function injectCss() {
  if (document.getElementById('manta-aqaba-viewer-css')) return;

  const style = document.createElement('style');
  style.id = 'manta-aqaba-viewer-css';
  style.textContent = `
    .manta-viewer {
      position: relative;
      width: 100%;
      height: clamp(780px, 86vh, 1120px);
      min-height: 720px;
      overflow: hidden;
      border: 1px solid #d0d7de;
      border-radius: 8px;
      background: #0b1020;
    }

    .manta-vtk-host {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }

    .manta-vtk-host canvas {
      width: 100% !important;
      height: 100% !important;
      display: block;
    }

    .manta-viewer-status {
      position: absolute;
      left: 12px;
      top: 12px;
      z-index: 20;
      max-width: min(820px, calc(100% - 24px));
      padding: 7px 10px;
      border-radius: 6px;
      font-size: 13px;
      line-height: 1.35;
      color: #24292f;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 1px 5px rgba(0, 0, 0, 0.2);
      pointer-events: none;
    }

    .manta-viewer-error {
      color: #b00020;
      font-weight: 700;
      pointer-events: auto;
    }

    .manta-amr-hud {
      position: absolute;
      left: 12px;
      top: 54px;
      z-index: 21;
      max-width: min(760px, calc(100% - 24px));
      padding: 6px 9px;
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.3;
      color: #24292f;
      background: rgba(255, 255, 255, 0.88);
      box-shadow: 0 1px 5px rgba(0, 0, 0, 0.18);
      pointer-events: none;
      font-variant-numeric: tabular-nums;
    }

    .manta-amr-hud-hidden {
      display: none;
    }

    .manta-viewer-controls {
      position: absolute;
      left: 12px;
      right: 12px;
      bottom: 12px;
      z-index: 30;
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      align-items: center;
      padding: 8px 10px;
      border-radius: 8px;
      font-size: 13px;
      color: #24292f;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 1px 5px rgba(0, 0, 0, 0.2);
      pointer-events: auto;
    }

    .manta-viewer-controls,
    .manta-viewer-controls * {
      pointer-events: auto;
    }

    .manta-viewer-controls label {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin: 0;
      white-space: nowrap;
      cursor: pointer;
    }

    .manta-viewer-controls select,
    .manta-viewer-controls button {
      font-size: 13px;
      line-height: 1.2;
      padding: 3px 6px;
      border: 1px solid #c9d1d9;
      border-radius: 5px;
      background: #ffffff;
      color: #24292f;
    }



    .manta-threshold-controls {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      flex: 0 0 auto;
      white-space: nowrap;
    }

    .manta-threshold-controls input[type="text"] {
      width: 74px;
      max-width: 74px;
      box-sizing: border-box;
      font-size: 13px;
      line-height: 1.2;
      padding: 3px 6px;
      border: 1px solid #c9d1d9;
      border-radius: 5px;
      background: #ffffff;
      color: #24292f;
      font-variant-numeric: tabular-nums;
    }

    .manta-time-controls {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 1 1 420px;
      min-width: min(420px, 100%);
    }

    .manta-time-controls input[type="range"] {
      flex: 1 1 auto;
      min-width: 180px;
      cursor: pointer;
      touch-action: pan-x;
      position: relative;
      z-index: 40;
    }

    .manta-time-readout {
      min-width: 170px;
      text-align: right;
      color: #57606a;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }

    .manta-viewer-legend {
      position: absolute;
      right: 12px;
      top: 12px;
      z-index: 30;
      padding: 8px 10px;
      border-radius: 8px;
      font-size: 12px;
      color: #24292f;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 1px 5px rgba(0, 0, 0, 0.2);
      width: 310px;
      max-width: calc(100% - 24px);
    }

    .manta-viewer-legend-title {
      font-weight: 700;
      margin-bottom: 5px;
    }

    .manta-viewer-legend-row {
      display: flex;
      align-items: center;
      gap: 7px;
      margin: 4px 0;
      white-space: nowrap;
    }

    .manta-swatch {
      width: 15px;
      height: 15px;
      border-radius: 3px;
      border: 1px solid rgba(0, 0, 0, 0.25);
      display: inline-block;
    }

    .manta-viewer-legend-value {
      color: #57606a;
      font-size: 11px;
      margin-left: auto;
    }

    .manta-viewer-colorbars {
      margin-top: 9px;
      padding-top: 8px;
      border-top: 1px solid rgba(31, 35, 40, 0.14);
    }

    .manta-colorbar {
      margin-top: 8px;
    }

    .manta-colorbar:first-child {
      margin-top: 0;
    }

    .manta-colorbar-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 4px;
    }

    .manta-colorbar-title {
      font-weight: 700;
      color: #24292f;
    }

    .manta-colorbar-range {
      color: #57606a;
      font-size: 11px;
      white-space: nowrap;
    }

    .manta-colorbar-strip {
      width: 100%;
      height: 12px;
      border-radius: 999px;
      border: 1px solid rgba(31, 35, 40, 0.22);
      box-sizing: border-box;
      overflow: hidden;
    }

    .manta-colorbar-ticks {
      display: flex;
      justify-content: space-between;
      gap: 6px;
      margin-top: 3px;
      color: #57606a;
      font-size: 10px;
      line-height: 1.2;
    }

    .manta-colorbar-ticks span:nth-child(2) {
      text-align: center;
    }

    .manta-colorbar-ticks span:last-child {
      text-align: right;
    }

    .manta-colorbar-hidden {
      display: none;
    }

    .manta-swatch-terrain { background: #9b9b9b; }
    .manta-swatch-water { background: #3c75d9; }
    .manta-swatch-landslide { background: #d65f2e; }
  

    .manta-amr-hud .manta-amr-level-token {
      display: inline-block;
      font-weight: 800;
      letter-spacing: 0.01em;
      text-shadow: 0 0 2px rgba(255, 255, 255, 0.85), 0 0 4px rgba(0, 0, 0, 0.18);
    }

    .manta-amr-hud .manta-amr-resolution {
      color: #24292f;
      font-weight: 600;
      opacity: 0.92;
      margin-left: 2px;
    }
`;
  document.head.appendChild(style);
}

function setStatus(container, message, isError = false) {
  const el = container.querySelector('.manta-viewer-status');
  if (!el) return;
  el.className = isError ? 'manta-viewer-status manta-viewer-error' : 'manta-viewer-status';
  el.textContent = message;
}

function setupDom(container) {
  injectCss();

  container.innerHTML = `
    <div class="manta-vtk-host"></div>

    <div class="manta-viewer-status">
      Loading MANTA Gallery viewer...
    </div>

    <div id="amr-hud" class="manta-amr-hud manta-amr-hud-hidden">
      AMR diagnostics unavailable
    </div>

    <div class="manta-viewer-legend">
      <div class="manta-viewer-legend-title">Layers</div>
      <div class="manta-viewer-legend-row">
        <span class="manta-swatch manta-swatch-terrain"></span>
        Terrain
      </div>
      <div class="manta-viewer-legend-row">
        <span class="manta-swatch manta-swatch-water"></span>
        Water surface
        <span id="water-scalar-readout" class="manta-viewer-legend-value">solid</span>
      </div>
      <div class="manta-viewer-legend-row">
        <span class="manta-swatch manta-swatch-landslide"></span>
        Landslide
        <span id="landslide-scalar-readout" class="manta-viewer-legend-value">solid</span>
      </div>

      <div class="manta-viewer-colorbars">
        <div id="water-colorbar" class="manta-colorbar manta-colorbar-hidden">
          <div class="manta-colorbar-header">
            <span id="water-colorbar-title" class="manta-colorbar-title">Tsunami</span>
            <span id="water-colorbar-range" class="manta-colorbar-range"></span>
          </div>
          <div id="water-colorbar-strip" class="manta-colorbar-strip"></div>
          <div class="manta-colorbar-ticks">
            <span id="water-colorbar-min"></span>
            <span id="water-colorbar-mid"></span>
            <span id="water-colorbar-max"></span>
          </div>
        </div>

        <div id="landslide-colorbar" class="manta-colorbar manta-colorbar-hidden">
          <div class="manta-colorbar-header">
            <span id="landslide-colorbar-title" class="manta-colorbar-title">Landslide</span>
            <span id="landslide-colorbar-range" class="manta-colorbar-range"></span>
          </div>
          <div id="landslide-colorbar-strip" class="manta-colorbar-strip"></div>
          <div class="manta-colorbar-ticks">
            <span id="landslide-colorbar-min"></span>
            <span id="landslide-colorbar-mid"></span>
            <span id="landslide-colorbar-max"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="manta-viewer-controls">
      <label><input type="checkbox" id="toggle-terrain" checked> Terrain</label>
      <label><input type="checkbox" id="toggle-water" checked> Water</label>
      <label><input type="checkbox" id="toggle-landslide" checked> Landslide</label>
      <label><input type="checkbox" id="toggle-amr"> AMR outlines</label>

      <label>
        Landslide color:
        <select id="landslide-scalar" disabled>
          <option value="hm" selected>hm</option>
          <option value="m">m</option>
          <option value="db">Δb</option>
        </select>
      </label>


      <div class="manta-threshold-controls" aria-label="m threshold filters">
        <label title="Press Enter to apply. Water layer keeps cells with m less than or equal to this value.">
          Water m≤
          <input id="water-m-threshold" type="text" inputmode="decimal" value="0.30" autocomplete="off" spellcheck="false">
        </label>
        <label title="Press Enter to apply. If the value is exactly 0, the hidden rule uses m > 0 to avoid including zero-m water cells.">
          Landslide m≥
          <input id="landslide-m-threshold" type="text" inputmode="decimal" value="-0.01" autocomplete="off" spellcheck="false">
        </label>
      </div>

      <div class="manta-time-controls">
        <button id="play-toggle" type="button" disabled>Play</button>
        <input id="time-slider" type="range" min="0" max="0" value="0" step="1" disabled>
        <span id="time-readout" class="manta-time-readout">frame 1/1</span>
      </div>

      <button id="reset-camera" type="button">Reset view</button>
    </div>
  `;

  return container.querySelector('.manta-vtk-host');
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch JSON: ${url.href} (${response.status})`);
  }
  return response.json();
}

async function fetchArrayBuffer(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch file: ${url.href} (${response.status})`);
  }
  return response.arrayBuffer();
}

function framePathFromPattern(pattern, frameIndex = 0) {
  const frame = String(frameIndex).padStart(4, '0');
  return pattern.replace('{frame}', frame);
}

function caseUrl(path) {
  return new URL(path, CASE_BASE_URL);
}


function getAmrFilePattern() {
  return state.caseInfo?.layers?.amr?.file_pattern ?? null;
}

function hasAmrLayer() {
  return Boolean(getAmrFilePattern());
}

function amrFramePath(frameIndex) {
  const pattern = getAmrFilePattern();
  if (!pattern) return null;
  return framePathFromPattern(pattern, frameIndex);
}

async function readAmrFrameData(frameIndex) {
  const k = clampFrameIndex(state.caseInfo, frameIndex);
  if (!hasAmrLayer()) return null;
  if (state.amrCache.has(k)) return state.amrCache.get(k);

  const path = amrFramePath(k);
  if (!path) return null;
  const data = await fetchJson(caseUrl(path));
  state.amrCache.set(k, data);

  // Keep a small cache around the current playback window.
  if (state.amrCache.size > 9) {
    const keys = Array.from(state.amrCache.keys()).sort((a, b) => Math.abs(b - k) - Math.abs(a - k));
    while (state.amrCache.size > 9 && keys.length > 0) {
      const victim = keys.shift();
      if (victim !== k) state.amrCache.delete(victim);
    }
  }

  return data;
}

function formatAmrResolutionLength(value) {
  const v = Number(value);
  if (!Number.isFinite(v)) return '?';
  const av = Math.abs(v);
  if (av >= 1000) {
    const km = v / 1000.0;
    return `${km.toFixed(Math.abs(km) >= 10 ? 1 : 2)} km`;
  }
  if (av >= 10) return `${Math.round(v)} m`;
  if (av >= 1) return `${v.toFixed(1)} m`;
  return `${v.toFixed(3)} m`;
}

function getAmrLevelResolutionText(amrData, level) {
  const patches = Array.isArray(amrData?.patches) ? amrData.patches : [];
  const patch = patches.find((candidate) => {
    return Number(candidate?.level) === Number(level)
      && Number.isFinite(Number(candidate?.dx))
      && Number.isFinite(Number(candidate?.dy));
  });
  if (!patch) return '';
  return ` (${formatAmrResolutionLength(patch.dx)} × ${formatAmrResolutionLength(patch.dy)})`;
}

function amrLevelHtml(amrData) {
  const levels = amrData?.levels;
  if (!levels || typeof levels !== 'object') return '';

  return Object.keys(levels)
    .map((key) => Number(key))
    .filter((key) => Number.isFinite(key) && key > 0)
    .sort((a, b) => a - b)
    .map((level) => {
      const count = levels[String(level)] ?? levels[level] ?? 0;
      const color = getAmrLevelCssColor(level);
      const resolution = getAmrLevelResolutionText(amrData, level);
      return `<span class="manta-amr-level" style="color: ${color}; font-weight: 850;">L${level}=${count}</span>${resolution}`;
    })
    .join(' · ');
}

function updateAmrHud(amrData) {
  const hud = document.getElementById('amr-hud');
  if (!hud) return;

  if (!amrData) {
    hud.classList.add('manta-amr-hud-hidden');
    return;
  }

  const levelText = amrLevelHtml(amrData);
  const grids = Number(amrData.ngrids ?? 0);
  const t = Number(amrData.time);
  const timeText = Number.isFinite(t) ? `t=${t.toFixed(2)} s` : getFrameLabel(state.caseInfo, state.currentFrameIndex);

  hud.innerHTML = `AMR: grids=${grids}${levelText ? ` · ${levelText}` : ''} · ${timeText}`;
  hud.classList.remove('manta-amr-hud-hidden');
}
function clearAmrOutlineActors() {
  if (!state.renderer) return;
  for (const actor of state.amrActors.values()) {
    try {
      state.renderer.removeActor(actor);
    } catch (error) {
      // ignore stale actors
    }
  }
  state.amrActors.clear();
}

const AMR_LEVEL_COLORS = {
  // L1: dark green; L2: bright blue; higher levels remain high-contrast.
  1: [0.00, 0.36, 0.18],
  2: [0.00, 0.62, 1.00],
  3: [0.84, 0.36, 1.00],
  4: [0.24, 0.88, 0.40],
  5: [1.00, 0.44, 0.16],
  6: [0.15, 0.86, 1.00],
  7: [1.00, 0.22, 0.55],
  8: [0.78, 0.84, 0.88],
};
function getAmrLevelColor(level) {
  return AMR_LEVEL_COLORS[Number(level)] ?? [1.0, 1.0, 1.0];
}

function getAmrLevelCssColor(level) {
  const [red, green, blue] = getAmrLevelColor(level);
  const r = Math.round(Math.max(0, Math.min(1, red)) * 255);
  const g = Math.round(Math.max(0, Math.min(1, green)) * 255);
  const b = Math.round(Math.max(0, Math.min(1, blue)) * 255);
  return `rgb(${r}, ${g}, ${b})`;
}
function getAmrOverlayZ() {
  const candidates = [];
  for (const dataset of [state.datasets.water, state.datasets.landslide]) {
    const bounds = dataset?.getBounds?.();
    if (Array.isArray(bounds) && bounds.length >= 6 && Number.isFinite(bounds[5])) {
      candidates.push(Number(bounds[5]));
    }
  }
  if (candidates.length === 0) return 5.0;
  const z = Math.max(...candidates);
  return z + 0.25;
}

function buildAmrPolyDataForLevel(patches, level, zOverlay) {
  const points = [];
  const lines = [];
  let pointIndex = 0;

  for (const patch of patches) {
    const lv = Number(patch.level);
    if (lv !== Number(level)) continue;

    const x0 = Number(patch.xlow);
    const y0 = Number(patch.ylow);
    const x1 = Number.isFinite(Number(patch.xhi)) ? Number(patch.xhi) : x0 + Number(patch.mx) * Number(patch.dx);
    const y1 = Number.isFinite(Number(patch.yhi)) ? Number(patch.yhi) : y0 + Number(patch.my) * Number(patch.dy);

    if (![x0, y0, x1, y1].every(Number.isFinite)) continue;
    if (!(x1 > x0 && y1 > y0)) continue;

    points.push(x0, y0, zOverlay, x1, y0, zOverlay, x1, y1, zOverlay, x0, y1, zOverlay);
    lines.push(5, pointIndex, pointIndex + 1, pointIndex + 2, pointIndex + 3, pointIndex);
    pointIndex += 4;
  }

  if (points.length === 0 || lines.length === 0) return null;

  const vtkPointsObj = vtkPoints.newInstance();
  vtkPointsObj.setData(Float32Array.from(points), 3);

  const vtkLinesObj = vtkCellArray.newInstance({ values: Uint32Array.from(lines) });

  const polyData = vtkPolyData.newInstance();
  polyData.setPoints(vtkPointsObj);
  polyData.setLines(vtkLinesObj);

  return polyData;
}

function renderAmrOutlines(amrData) {
  clearAmrOutlineActors();
  if (!state.amrVisible || !amrData?.patches?.length) {
    state.renderWindow?.render();
    return;
  }

  const levels = Array.from(new Set(amrData.patches.map((patch) => Number(patch.level)).filter(Number.isFinite))).sort((a, b) => a - b);
  const zOverlay = getAmrOverlayZ();

  for (const level of levels) {
    const polyData = buildAmrPolyDataForLevel(amrData.patches, level, zOverlay);
    if (!polyData) continue;

    const mapper = vtkMapper.newInstance();
    mapper.setInputData(polyData);
    mapper.setScalarVisibility(false);

    const actor = vtkActor.newInstance();
    actor.setMapper(mapper);
    actor.setPickable?.(false);

    const property = actor.getProperty();
    property.setColor(...getAmrLevelColor(level));
    property.setOpacity(1.0); property.setLineWidth?.(4.25);

    state.renderer.addActor(actor);
    state.amrActors.set(level, actor);
  }

  state.renderer?.resetCameraClippingRange();
  state.renderWindow?.render();
}

async function updateAmrForCurrentFrame(container) {
  if (!hasAmrLayer()) {
    updateAmrHud(null);
    clearAmrOutlineActors();
    const toggle = container?.querySelector?.('#toggle-amr');
    if (toggle) toggle.disabled = true;
    return;
  }

  const token = ++state.amrLoadToken;
  const frameIndex = state.currentFrameIndex;

  try {
    const amrData = await readAmrFrameData(frameIndex);
    if (token !== state.amrLoadToken) return;
    updateAmrHud(amrData);
    renderAmrOutlines(amrData);
  } catch (error) {
    console.warn('[MANTA Gallery] failed to load AMR diagnostics:', error);
    updateAmrHud(null);
    clearAmrOutlineActors();
  }
}

function getFrameCount(caseInfo) {
  const declared = Number(caseInfo?.time?.frame_count);
  if (Number.isFinite(declared) && declared > 0) return Math.floor(declared);

  const values = caseInfo?.time?.values;
  if (Array.isArray(values) && values.length > 0) return values.length;

  return 1;
}

function clampFrameIndex(caseInfo, frameIndex) {
  const n = getFrameCount(caseInfo);
  const k = Number(frameIndex);
  if (!Number.isFinite(k)) return 0;
  return Math.min(Math.max(Math.round(k), 0), n - 1);
}

function getDefaultFrameIndex(caseInfo) {
  return clampFrameIndex(caseInfo, Number(caseInfo?.time?.default_index ?? 0));
}

function getFrameTime(caseInfo, frameIndex) {
  const values = caseInfo?.time?.values;
  if (!Array.isArray(values)) return null;
  const t = Number(values[frameIndex]);
  return Number.isFinite(t) ? t : null;
}

function getFrameLabel(caseInfo, frameIndex) {
  const n = getFrameCount(caseInfo);
  const t = getFrameTime(caseInfo, frameIndex);
  const timeText = Number.isFinite(t) ? `t = ${t.toFixed(2)} s` : 'time unavailable';
  return `frame ${frameIndex + 1}/${n}, ${timeText}`;
}

function finitePairRange(range) {
  if (!Array.isArray(range) || range.length < 2) return null;
  const lo = Number(range[0]);
  const hi = Number(range[1]);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;
  return [lo, hi];
}

function symmetricRangeFromRange(range) {
  const clean = finitePairRange(range);
  if (!clean) return null;
  const limit = Math.max(Math.abs(clean[0]), Math.abs(clean[1]), 1e-12);
  return [-limit, limit];
}

function getWaterStatisticsRange() {
  const manifestRange = state.caseInfo?.layers?.water?.colorbar?.range;
  return finitePairRange(manifestRange);
}

function getWaterStatisticsLabel() {
  return state.caseInfo?.layers?.water?.colorbar?.range_label ?? 'full';
}

function getWaterDisplayRange() {
  const configuredRange = state.caseInfo?.layers?.water?.colorbar?.display_range;
  const cleanConfiguredRange = finitePairRange(configuredRange);
  if (cleanConfiguredRange) return symmetricRangeFromRange(cleanConfiguredRange);

  // Backward-compatible fallback for older manifests.
  const statsRange = getWaterStatisticsRange();
  if (!statsRange) return null;

  const fullLimit = Math.max(Math.abs(statsRange[0]), Math.abs(statsRange[1]), 1e-12);
  const displayLimit = Math.max(fullLimit * WATER_DISPLAY_RANGE_FRACTION, 1e-12);

  return [-displayLimit, displayLimit];
}

async function readVtp(url) {
  const reader = vtkXMLPolyDataReader.newInstance();
  const buffer = await fetchArrayBuffer(url);
  reader.parseAsArrayBuffer(buffer);

  const output = reader.getOutputData(0);
  if (!output) {
    throw new Error(`No PolyData output from ${url.href}`);
  }

  return output;
}

const COMPACT_V2_MAGIC = [77, 65, 78, 84, 65, 86, 50, 0];
const COMPACT_V2_HEADER_BYTES = 16;
const COMPACT_ARRAY_TYPES = {
  float32: Float32Array,
  uint32: Uint32Array,
  uint8: Uint8Array,
};

function hasCompactV2Layer(caseInfo, layerName) {
  return Number(caseInfo?.layers?.[layerName]?.compact?.version) === 2;
}

function caseUsesCompactV2(caseInfo) {
  return hasCompactV2Layer(caseInfo, 'water') && hasCompactV2Layer(caseInfo, 'landslide');
}

async function fetchGzipArrayBuffer(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch compact file: ${url.href} (${response.status})`);
  }
  if (typeof DecompressionStream !== 'function' || !response.body) {
    throw new Error('This browser does not support gzip DecompressionStream required by compact-v2 assets.');
  }

  const stream = response.body.pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).arrayBuffer();
}

function validateCompactV2Header(buffer, url) {
  if (buffer.byteLength < COMPACT_V2_HEADER_BYTES) {
    throw new Error(`Compact-v2 file is too short: ${url.href}`);
  }

  const bytes = new Uint8Array(buffer, 0, COMPACT_V2_MAGIC.length);
  for (let i = 0; i < COMPACT_V2_MAGIC.length; i += 1) {
    if (bytes[i] !== COMPACT_V2_MAGIC[i]) {
      throw new Error(`Compact-v2 magic mismatch: ${url.href}`);
    }
  }

  const view = new DataView(buffer);
  const version = view.getUint32(8, true);
  const payloadBytes = view.getUint32(12, true);
  if (version !== 2 || payloadBytes !== buffer.byteLength - COMPACT_V2_HEADER_BYTES) {
    throw new Error(`Compact-v2 header mismatch: ${url.href}`);
  }
}

function readCompactArrays(buffer, arraySpecs, url) {
  const arrays = {};
  for (const [name, spec] of Object.entries(arraySpecs ?? {})) {
    const ArrayType = COMPACT_ARRAY_TYPES[spec.dtype];
    const offset = Number(spec.byte_offset);
    const length = Number(spec.length);
    if (!ArrayType || !Number.isInteger(offset) || !Number.isInteger(length) || length < 0) {
      throw new Error(`Invalid compact-v2 array descriptor for ${name}: ${url.href}`);
    }
    const end = offset + length * ArrayType.BYTES_PER_ELEMENT;
    if (offset < COMPACT_V2_HEADER_BYTES || end > buffer.byteLength) {
      throw new Error(`Compact-v2 array bounds mismatch for ${name}: ${url.href}`);
    }
    arrays[name] = new ArrayType(buffer, offset, length);
  }
  return arrays;
}

async function readCompactArchive(path, arraySpecs) {
  const url = caseUrl(path);
  const buffer = await fetchGzipArrayBuffer(url);
  validateCompactV2Header(buffer, url);
  return readCompactArrays(buffer, arraySpecs, url);
}

function createCompactPolyData(layerName, compactInfo, templateArrays) {
  const pointCount = Number(compactInfo.point_count);
  const cellCount = Number(compactInfo.cell_count);
  const x = templateArrays.x;
  const y = templateArrays.y;
  const quads = templateArrays.quads;

  if (!Number.isInteger(pointCount) || !Number.isInteger(cellCount)) {
    throw new Error(`Invalid compact-v2 ${layerName} template dimensions.`);
  }
  if (x?.length !== pointCount || y?.length !== pointCount || quads?.length !== cellCount * 4) {
    throw new Error(`Compact-v2 ${layerName} template array lengths do not match the manifest.`);
  }

  const pointValues = new Float32Array(pointCount * 3);
  for (let i = 0; i < pointCount; i += 1) {
    const base = i * 3;
    pointValues[base] = x[i];
    pointValues[base + 1] = y[i];
  }

  const points = vtkPoints.newInstance();
  points.setData(pointValues, 3);
  const polys = vtkCellArray.newInstance();
  polys.setData(new Uint32Array(0));

  const polyData = vtkPolyData.newInstance();
  polyData.setPoints(points);
  polyData.setPolys(polys);

  const dataArrays = {};
  for (const [name, spec] of Object.entries(compactInfo.frame?.arrays ?? {})) {
    if (name === 'z' || name === 'valid_cells') continue;
    if (spec.dtype !== 'float32' || Number(spec.length) !== pointCount) {
      throw new Error(`Compact-v2 ${layerName} point array ${name} has an invalid layout.`);
    }
    const array = vtkDataArray.newInstance({
      name,
      numberOfComponents: 1,
      values: new Float32Array(pointCount),
    });
    polyData.getPointData().addArray(array);
    dataArrays[name] = array;
  }

  return {
    layerName,
    polyData,
    points,
    polys,
    pointValues,
    quads,
    dataArrays,
  };
}

async function loadCompactTemplate(caseInfo, layerName) {
  const compactInfo = caseInfo.layers[layerName].compact;
  const templateArrays = await readCompactArchive(
    compactInfo.template.file,
    compactInfo.template.arrays
  );
  return createCompactPolyData(layerName, compactInfo, templateArrays);
}

async function loadCompactTemplates(caseInfo) {
  if (!caseUsesCompactV2(caseInfo)) return;
  const [water, landslide] = await Promise.all([
    loadCompactTemplate(caseInfo, 'water'),
    loadCompactTemplate(caseInfo, 'landslide'),
  ]);
  state.compact.templates.water = water;
  state.compact.templates.landslide = landslide;
}

async function readCompactLayerFrame(caseInfo, layerName, frameIndex) {
  const compactInfo = caseInfo.layers[layerName].compact;
  const path = framePathFromPattern(compactInfo.frame.file_pattern, frameIndex);
  return readCompactArchive(path, compactInfo.frame.arrays);
}

async function readCompactFrameData(caseInfo, frameIndex) {
  const [water, landslide] = await Promise.all([
    readCompactLayerFrame(caseInfo, 'water', frameIndex),
    readCompactLayerFrame(caseInfo, 'landslide', frameIndex),
  ]);
  return { compact: true, water, landslide };
}

function compactBitIsSet(bits, index) {
  return (bits[index >> 3] & (1 << (7 - (index & 7)))) !== 0;
}

function compactMPointPredicate(layerName) {
  if (layerName === 'water') {
    const threshold = Number(state.mThresholds.waterMax);
    const waterMax = Number.isFinite(threshold) ? threshold : 0.30;
    return (m) => Number.isFinite(m) && m <= waterMax;
  }

  const threshold = Number(state.mThresholds.landslideMin);
  const landslideMin = Number.isFinite(threshold) ? threshold : -0.01;
  const eps = 1e-12;
  return (m) => Number.isFinite(m) && (Math.abs(landslideMin) <= eps ? m > 0.0 : m >= landslideMin);
}

function buildCompactVisiblePolys(template, frameArrays) {
  const quads = template.quads;
  const validCells = frameArrays.valid_cells;
  const m = frameArrays.m;
  const keepPoint = compactMPointPredicate(template.layerName);
  const cellCount = Math.floor(quads.length / 4);
  let visibleCellCount = 0;

  function keepCell(cellIndex) {
    if (!compactBitIsSet(validCells, cellIndex)) return false;
    const base = cellIndex * 4;
    return keepPoint(m[quads[base]])
      && keepPoint(m[quads[base + 1]])
      && keepPoint(m[quads[base + 2]])
      && keepPoint(m[quads[base + 3]]);
  }

  for (let cellIndex = 0; cellIndex < cellCount; cellIndex += 1) {
    if (keepCell(cellIndex)) visibleCellCount += 1;
  }

  const polys = new Uint32Array(visibleCellCount * 5);
  let target = 0;
  for (let cellIndex = 0; cellIndex < cellCount; cellIndex += 1) {
    if (!keepCell(cellIndex)) continue;
    const source = cellIndex * 4;
    polys[target] = 4;
    polys[target + 1] = quads[source];
    polys[target + 2] = quads[source + 1];
    polys[target + 3] = quads[source + 2];
    polys[target + 4] = quads[source + 3];
    target += 5;
  }
  return polys;
}

function updateCompactLayerDataset(layerName, frameArrays) {
  const template = state.compact.templates[layerName];
  if (!template || !frameArrays) return;

  const z = frameArrays.z;
  if (z.length * 3 !== template.pointValues.length) {
    throw new Error(`Compact-v2 ${layerName} frame z length does not match its template.`);
  }

  for (let i = 0; i < z.length; i += 1) {
    template.pointValues[i * 3 + 2] = z[i];
  }
  template.points.dataChange?.();
  template.points.modified?.();

  for (const [name, dataArray] of Object.entries(template.dataArrays)) {
    const source = frameArrays[name];
    const target = dataArray.getData();
    if (!source || source.length !== target.length) {
      throw new Error(`Compact-v2 ${layerName} frame array ${name} does not match its template.`);
    }
    target.set(source);
    dataArray.dataChange?.();
    dataArray.modified?.();
  }

  template.polys.setData(buildCompactVisiblePolys(template, frameArrays));
  template.polys.modified?.();
  template.polyData.modified?.();
  state.datasets[layerName] = template.polyData;
}

function applyLoadedFrameData(frameData) {
  if (frameData?.compact) {
    state.rawDatasets.water = null;
    state.rawDatasets.landslide = null;
    state.compact.currentFrames.water = frameData.water;
    state.compact.currentFrames.landslide = frameData.landslide;
    updateCompactLayerDataset('water', frameData.water);
    updateCompactLayerDataset('landslide', frameData.landslide);
    return;
  }

  state.rawDatasets.water = frameData.water;
  state.rawDatasets.landslide = frameData.landslide;
  applyMThresholdsToRawDatasets();
}

function setupScene(host) {
  const renderer = vtkRenderer.newInstance({
    background: [0.03, 0.05, 0.10],
  });

  const renderWindow = vtkRenderWindow.newInstance();
  renderWindow.addRenderer(renderer);

  const openGLRenderWindow = vtkOpenGLRenderWindow.newInstance();
  openGLRenderWindow.setContainer(host);
  renderWindow.addView(openGLRenderWindow);

  const interactor = vtkRenderWindowInteractor.newInstance();
  interactor.setView(openGLRenderWindow);
  interactor.initialize();
  interactor.bindEvents(host);
  interactor.setInteractorStyle(vtkInteractorStyleTrackballCamera.newInstance());

  state.renderer = renderer;
  state.renderWindow = renderWindow;
  state.openGLRenderWindow = openGLRenderWindow;
  state.interactor = interactor;

  const resize = () => {
    const rect = host.getBoundingClientRect();
    const width = Math.max(100, Math.floor(rect.width));
    const height = Math.max(100, Math.floor(rect.height));
    openGLRenderWindow.setSize(width, height);
    renderWindow.render();
  };

  window.addEventListener('resize', resize);
  setTimeout(resize, 0);
}

const TSUNAMI_COLOR_STOPS = [
  [0.00, 0.03, 0.05, 0.22],
  [0.18, 0.06, 0.22, 0.55],
  [0.36, 0.10, 0.44, 0.82],
  [0.50, 0.90, 0.96, 0.98],
  [0.64, 0.99, 0.80, 0.36],
  [0.82, 0.90, 0.24, 0.12],
  [1.00, 0.45, 0.02, 0.04],
];

const MAGMA_COLOR_STOPS = [
  [0.00, 0.00, 0.00, 0.02],
  [0.18, 0.11, 0.07, 0.33],
  [0.38, 0.45, 0.12, 0.51],
  [0.62, 0.82, 0.28, 0.42],
  [0.82, 0.99, 0.62, 0.34],
  [1.00, 0.99, 0.99, 0.65],
];

const WATER_COLOR_STOPS = TSUNAMI_COLOR_STOPS;
const WATER_DISPLAY_RANGE_FRACTION = 1.0 / 10.0;
const WATER_SURFACE_OPACITY = 1.0;
const LANDSLIDE_COLOR_STOPS = {
  hm: MAGMA_COLOR_STOPS,
  m: MAGMA_COLOR_STOPS,
  db: MAGMA_COLOR_STOPS,
};

const LANDSLIDE_COLORBAR_TITLES = {
  hm: 'Landslide thickness (m)',
  m: 'Landslide solid volume fraction m',
  db: 'Bed elevation change δb (m)',
};

function getArrayByName(attributes, name) {
  if (!attributes || !name) return null;
  if (typeof attributes.getArrayByName === 'function') {
    return attributes.getArrayByName(name);
  }
  return null;
}

function findDataArray(polyData, names) {
  const pointData = polyData.getPointData?.();
  const cellData = polyData.getCellData?.();

  for (const name of names) {
    const array = getArrayByName(pointData, name);
    if (array) {
      return {
        name,
        array,
        attributes: pointData,
        association: 'point',
      };
    }
  }

  for (const name of names) {
    const array = getArrayByName(cellData, name);
    if (array) {
      return {
        name,
        array,
        attributes: cellData,
        association: 'cell',
      };
    }
  }

  return null;
}

function computeFiniteRange(dataArray) {
  const values = dataArray?.getData?.();
  if (!values || values.length === 0) return null;

  const numberOfComponents = Math.max(1, dataArray.getNumberOfComponents?.() ?? 1);
  let minValue = Number.POSITIVE_INFINITY;
  let maxValue = Number.NEGATIVE_INFINITY;

  for (let i = 0; i < values.length; i += numberOfComponents) {
    const value = Number(values[i]);
    if (!Number.isFinite(value)) continue;
    minValue = Math.min(minValue, value);
    maxValue = Math.max(maxValue, value);
  }

  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) return null;

  if (minValue === maxValue) {
    const pad = Math.max(Math.abs(minValue) * 1e-6, 1e-12);
    return [minValue - pad, maxValue + pad];
  }

  return [minValue, maxValue];
}

function computeRobustSymmetricRange(dataArray, percentile = 99.0) {
  const values = dataArray?.getData?.();
  if (!values || values.length === 0) return null;

  const numberOfComponents = Math.max(1, dataArray.getNumberOfComponents?.() ?? 1);
  const magnitudes = [];

  for (let i = 0; i < values.length; i += numberOfComponents) {
    const value = Number(values[i]);
    if (!Number.isFinite(value)) continue;
    magnitudes.push(Math.abs(value));
  }

  if (magnitudes.length === 0) return null;

  magnitudes.sort((a, b) => a - b);
  const clampedPercentile = Math.min(100.0, Math.max(0.0, percentile));
  const index = Math.min(
    magnitudes.length - 1,
    Math.max(0, Math.floor((clampedPercentile / 100.0) * (magnitudes.length - 1)))
  );
  const limit = Math.max(magnitudes[index], 1e-12);
  return [-limit, limit];
}

function zeroCenteredRangeIfNeeded(arrayName, range) {
  const lowerName = arrayName.toLowerCase();
  const shouldCenter = lowerName === 'wave_amplitude' || lowerName === 'db';
  if (!shouldCenter || !range) return range;

  const limit = Math.max(Math.abs(range[0]), Math.abs(range[1]), 1e-12);
  return [-limit, limit];
}

function resolveDisplayRange({
  arrayName,
  dataArray,
  rawRange,
  rangeMode = 'auto',
  robustPercentile = 99.0,
  fixedRange = null,
}) {
  const cleanFixedRange = finitePairRange(fixedRange);
  if (cleanFixedRange) {
    return zeroCenteredRangeIfNeeded(arrayName, cleanFixedRange);
  }

  if (!rawRange) return null;
  if (rangeMode === 'robust-symmetric') {
    return computeRobustSymmetricRange(dataArray, robustPercentile)
      ?? zeroCenteredRangeIfNeeded(arrayName, rawRange);
  }
  return zeroCenteredRangeIfNeeded(arrayName, rawRange);
}

function createTransferFunction(range, stops) {
  const ctf = vtkColorTransferFunction.newInstance();
  const [vmin, vmax] = range;

  for (const [position, red, green, blue] of stops) {
    const value = vmin + position * (vmax - vmin);
    ctf.addRGBPoint(value, red, green, blue);
  }

  ctf.setMappingRange?.(vmin, vmax);
  ctf.updateRange?.();

  return ctf;
}

function formatScalar(value) {
  const absValue = Math.abs(value);
  if ((absValue > 0 && absValue < 1e-2) || absValue >= 1e3) {
    return value.toExponential(2);
  }
  return value.toFixed(3);
}

function formatRange(range) {
  if (!range) return '';
  return `[${formatScalar(range[0])}, ${formatScalar(range[1])}]`;
}

function setLegendReadout(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function stopsToCssGradient(stops) {
  return `linear-gradient(to right, ${stops
    .map(([position, red, green, blue]) => {
      const r = Math.round(red * 255);
      const g = Math.round(green * 255);
      const b = Math.round(blue * 255);
      const pct = Math.round(position * 1000) / 10;
      return `rgb(${r}, ${g}, ${b}) ${pct}%`;
    })
    .join(', ')})`;
}

function updateColorbar({ idPrefix, title, scalarInfo, colorStops, showZeroTick = false }) {
  const container = document.getElementById(`${idPrefix}-colorbar`);
  if (!container) return;

  if (!scalarInfo?.range) {
    container.classList.add('manta-colorbar-hidden');
    return;
  }

  const [vmin, vmax] = scalarInfo.range;
  const midValue = showZeroTick && vmin < 0 && vmax > 0 ? 0.0 : 0.5 * (vmin + vmax);

  container.classList.remove('manta-colorbar-hidden');

  const titleEl = document.getElementById(`${idPrefix}-colorbar-title`);
  const rangeEl = document.getElementById(`${idPrefix}-colorbar-range`);
  const stripEl = document.getElementById(`${idPrefix}-colorbar-strip`);
  const minEl = document.getElementById(`${idPrefix}-colorbar-min`);
  const midEl = document.getElementById(`${idPrefix}-colorbar-mid`);
  const maxEl = document.getElementById(`${idPrefix}-colorbar-max`);

  if (titleEl) titleEl.textContent = title;
  if (rangeEl) rangeEl.textContent = formatRange(scalarInfo.range);
  if (stripEl) stripEl.style.background = stopsToCssGradient(colorStops);
  if (minEl) minEl.textContent = formatScalar(vmin);
  if (midEl) midEl.textContent = formatScalar(midValue);
  if (maxEl) maxEl.textContent = formatScalar(vmax);
}

function updateWaterColorbar() {
  const statsRange = getWaterStatisticsRange();

  updateColorbar({
    idPrefix: 'water',
    title: 'Wave height (m)',
    scalarInfo: state.scalarInfo.water,
    colorStops: WATER_COLOR_STOPS,
    showZeroTick: true,
  });

  if (statsRange) {
    const fullText = `${getWaterStatisticsLabel()} ${formatRange(statsRange)}`;
    const rangeEl = document.getElementById('water-colorbar-range');
    if (rangeEl) rangeEl.textContent = fullText;
    setLegendReadout('water-scalar-readout', `wave_amplitude ${fullText}`);
  }
}

function updateLandslideColorbar(scalarName = 'hm') {
  const colorStops = LANDSLIDE_COLOR_STOPS[scalarName] ?? MAGMA_COLOR_STOPS;
  const title = LANDSLIDE_COLORBAR_TITLES[scalarName] ?? `Landslide / ${scalarName}`;
  updateColorbar({
    idPrefix: 'landslide',
    title,
    scalarInfo: state.scalarInfo.landslide,
    colorStops,
    showZeroTick: scalarName === 'db',
  });
}

function applyScalarToActor({
  actor,
  polyData,
  arrayNames,
  colorStops,
  fallbackColor,
  rangeMode = 'auto',
  robustPercentile = 99.0,
  fixedRange = null,
}) {
  if (!actor || !polyData) return null;

  const mapper = actor.getMapper();
  mapper.setInputData(polyData);

  const found = findDataArray(polyData, arrayNames);

  if (!found) {
    mapper.setScalarVisibility(false);
    actor.getProperty().setColor(...fallbackColor);
    console.warn(`[MANTA Gallery] Missing scalar array: ${arrayNames.join(' / ')}`);
    return null;
  }

  const rawRange = computeFiniteRange(found.array);
  const range = resolveDisplayRange({
    arrayName: found.name,
    dataArray: found.array,
    rawRange,
    rangeMode,
    robustPercentile,
    fixedRange,
  });

  if (!range) {
    mapper.setScalarVisibility(false);
    actor.getProperty().setColor(...fallbackColor);
    console.warn(`[MANTA Gallery] Scalar array has no finite values: ${found.name}`);
    return null;
  }

  const lookupTable = createTransferFunction(range, colorStops);

  found.attributes.setActiveScalars?.(found.name);

  if (found.association === 'point') {
    mapper.setScalarModeToUsePointFieldData?.();
  } else {
    mapper.setScalarModeToUseCellFieldData?.();
  }

  mapper.setColorByArrayName?.(found.name);
  mapper.setLookupTable(lookupTable);
  mapper.setScalarRange(range[0], range[1]);
  mapper.setScalarVisibility(true);
  mapper.setColorModeToMapScalars?.();
  mapper.setInterpolateScalarsBeforeMapping?.(true);
  mapper.modified?.();

  actor.getProperty().setColor(1.0, 1.0, 1.0);

  return {
    name: found.name,
    association: found.association,
    range,
    rawRange,
  };
}

function createSolidActor(polyData, color, opacity) {
  const mapper = vtkMapper.newInstance();
  mapper.setInputData(polyData);
  mapper.setScalarVisibility(false);

  const actor = vtkActor.newInstance();
  actor.setMapper(mapper);

  const property = actor.getProperty();
  property.setColor(...color);
  property.setOpacity(opacity);

  return actor;
}

function createScalarActor(
  polyData,
  arrayNames,
  colorStops,
  fallbackColor,
  opacity,
  options = {}
) {
  const actor = createSolidActor(polyData, fallbackColor, opacity);
  const scalarInfo = applyScalarToActor({
    actor,
    polyData,
    arrayNames,
    colorStops,
    fallbackColor,
    ...options,
  });

  return { actor, scalarInfo };
}


function getPointScalarArray(polyData, name) {
  const pointData = polyData?.getPointData?.();
  return getArrayByName(pointData, name);
}

function parseMThresholdValue(textValue, fallbackValue) {
  const value = Number(String(textValue ?? '').trim());
  return Number.isFinite(value) ? value : fallbackValue;
}

function getPolyDataPointCount(polyData) {
  const points = polyData?.getPoints?.();
  if (!points) return 0;
  if (typeof points.getNumberOfPoints === 'function') {
    return points.getNumberOfPoints();
  }
  const data = points.getData?.();
  return data ? Math.floor(data.length / 3) : 0;
}

function clonePointDataArrays(sourcePolyData, targetPolyData, oldToNew) {
  const sourcePointData = sourcePolyData?.getPointData?.();
  const targetPointData = targetPolyData?.getPointData?.();
  if (!sourcePointData || !targetPointData || !oldToNew || oldToNew.size === 0) return;

  let arrays = [];
  if (typeof sourcePointData.getArrays === 'function') {
    arrays = sourcePointData.getArrays();
  } else if (typeof sourcePointData.getNumberOfArrays === 'function' && typeof sourcePointData.getArrayByIndex === 'function') {
    const n = sourcePointData.getNumberOfArrays();
    for (let i = 0; i < n; i += 1) arrays.push(sourcePointData.getArrayByIndex(i));
  }

  const orderedMap = Array.from(oldToNew.entries());

  for (const array of arrays) {
    const sourceValues = array?.getData?.();
    if (!sourceValues) continue;

    const name = array.getName?.() ?? 'array';
    const nComp = Math.max(1, array.getNumberOfComponents?.() ?? 1);
    const TargetArrayType = sourceValues.constructor ?? Float32Array;
    const targetValues = new TargetArrayType(oldToNew.size * nComp);

    for (const [oldId, newId] of orderedMap) {
      const srcBase = oldId * nComp;
      const dstBase = newId * nComp;
      for (let c = 0; c < nComp; c += 1) {
        targetValues[dstBase + c] = sourceValues[srcBase + c];
      }
    }

    const copiedArray = vtkDataArray.newInstance({
      name,
      numberOfComponents: nComp,
      values: targetValues,
    });
    targetPointData.addArray(copiedArray);
  }
}

function filterPolyDataByM(polyData, predicate) {
  const mArray = getPointScalarArray(polyData, 'm');
  const mValues = mArray?.getData?.();
  const points = polyData?.getPoints?.();
  const pointValues = points?.getData?.();
  const polys = polyData?.getPolys?.();
  const polyValues = polys?.getData?.();

  if (!mArray || !mValues || !points || !pointValues || !polys || !polyValues) {
    return polyData;
  }

  const pointCount = getPolyDataPointCount(polyData);
  const mComp = Math.max(1, mArray.getNumberOfComponents?.() ?? 1);

  function keepPoint(pointId) {
    if (!Number.isInteger(pointId) || pointId < 0 || pointId >= pointCount) return false;
    const value = Number(mValues[pointId * mComp]);
    return Number.isFinite(value) && predicate(value);
  }

  const oldToNew = new Map();
  const newPointValues = [];
  const newPolyValues = [];

  function mapPoint(oldId) {
    if (oldToNew.has(oldId)) return oldToNew.get(oldId);
    const newId = oldToNew.size;
    oldToNew.set(oldId, newId);
    const base = oldId * 3;
    newPointValues.push(
      Number(pointValues[base] ?? 0),
      Number(pointValues[base + 1] ?? 0),
      Number(pointValues[base + 2] ?? 0)
    );
    return newId;
  }

  let offset = 0;
  while (offset < polyValues.length) {
    const n = Number(polyValues[offset]);
    offset += 1;
    if (!Number.isInteger(n) || n <= 0 || offset + n > polyValues.length) break;

    const ids = [];
    let keep = true;
    for (let i = 0; i < n; i += 1) {
      const id = Number(polyValues[offset + i]);
      ids.push(id);
      if (!keepPoint(id)) keep = false;
    }

    if (keep) {
      newPolyValues.push(n);
      for (const id of ids) newPolyValues.push(mapPoint(id));
    }
    offset += n;
  }

  const filtered = vtkPolyData.newInstance();
  const filteredPoints = vtkPoints.newInstance();
  filteredPoints.setData(Float32Array.from(newPointValues), 3);
  filtered.setPoints(filteredPoints);

  const filteredPolys = vtkCellArray.newInstance();
  filteredPolys.setData(Uint32Array.from(newPolyValues));
  filtered.setPolys(filteredPolys);

  clonePointDataArrays(polyData, filtered, oldToNew);
  return filtered;
}

function filterWaterDataset(rawPolyData) {
  const threshold = Number(state.mThresholds.waterMax);
  const waterMax = Number.isFinite(threshold) ? threshold : 0.30;
  return filterPolyDataByM(rawPolyData, (m) => m <= waterMax);
}

function filterLandslideDataset(rawPolyData) {
  const threshold = Number(state.mThresholds.landslideMin);
  const landslideMin = Number.isFinite(threshold) ? threshold : -0.01;
  const eps = 1e-12;
  return filterPolyDataByM(rawPolyData, (m) => {
    if (Math.abs(landslideMin) <= eps) return m > 0.0;
    return m >= landslideMin;
  });
}

function applyMThresholdsToRawDatasets() {
  if (state.compact.enabled) {
    updateCompactLayerDataset('water', state.compact.currentFrames.water);
    updateCompactLayerDataset('landslide', state.compact.currentFrames.landslide);
    return;
  }
  if (state.rawDatasets.water) {
    state.datasets.water = filterWaterDataset(state.rawDatasets.water);
  }
  if (state.rawDatasets.landslide) {
    state.datasets.landslide = filterLandslideDataset(state.rawDatasets.landslide);
  }
}

function applyMThresholdInputs(container) {
  const waterInput = container.querySelector('#water-m-threshold');
  const landslideInput = container.querySelector('#landslide-m-threshold');

  const waterValue = parseMThresholdValue(waterInput?.value, state.mThresholds.waterMax);
  const landslideValue = parseMThresholdValue(landslideInput?.value, state.mThresholds.landslideMin);

  state.mThresholds.waterMax = waterValue;
  state.mThresholds.landslideMin = landslideValue;

  if (waterInput) waterInput.value = String(waterValue);
  if (landslideInput) landslideInput.value = String(landslideValue);

  applyMThresholdsToRawDatasets();
  updateCurrentFrameActors();

  setStatus(
    container,
    `Applied m thresholds: water m≤${waterValue}, landslide m≥${landslideValue}. ` +
      `Frame ${state.currentFrameIndex + 1}/${state.frameCount}.`
  );
}

function setupMThresholdControls(container) {
  const waterInput = container.querySelector('#water-m-threshold');
  const landslideInput = container.querySelector('#landslide-m-threshold');

  if (waterInput) waterInput.value = String(state.mThresholds.waterMax);
  if (landslideInput) landslideInput.value = String(state.mThresholds.landslideMin);

  for (const input of [waterInput, landslideInput]) {
    if (!input) continue;
    for (const eventName of ['pointerdown', 'mousedown', 'touchstart', 'wheel', 'dblclick']) {
      input.addEventListener(eventName, (event) => {
        event.stopPropagation();
      }, { passive: true });
    }
    input.addEventListener('keydown', (event) => {
      event.stopPropagation();
      if (event.key === 'Enter') {
        event.preventDefault();
        stopPlayback();
        applyMThresholdInputs(container);
      }
    });
  }
}

function applyLandslideScalar(scalarName) {
  state.activeLandslideScalar = scalarName;
  const colorStops = LANDSLIDE_COLOR_STOPS[scalarName] ?? LANDSLIDE_COLOR_STOPS.hm;
  const scalarInfo = applyScalarToActor({
    actor: state.actors.landslide,
    polyData: state.datasets.landslide,
    arrayNames: [scalarName],
    colorStops,
    fallbackColor: [0.90, 0.32, 0.12],
  });

  state.scalarInfo.landslide = scalarInfo;
  setLegendReadout(
    'landslide-scalar-readout',
    scalarInfo ? `${scalarInfo.name} ${formatRange(scalarInfo.range)}` : 'solid'
  );
  updateLandslideColorbar(scalarName);

  state.renderWindow?.render();
}

async function readFrameData(frameIndex) {
  const caseInfo = state.caseInfo;
  const k = clampFrameIndex(caseInfo, frameIndex);

  if (state.frameCache.has(k)) {
    return state.frameCache.get(k);
  }

  if (state.compact.enabled) {
    const entry = await readCompactFrameData(caseInfo, k);
    state.frameCache.set(k, entry);
    trimFrameCache(k);
    return entry;
  }

  const waterPath = framePathFromPattern(caseInfo.layers.water.file_pattern, k);
  const landslidePath = framePathFromPattern(caseInfo.layers.landslide.file_pattern, k);

  const [water, landslide] = await Promise.all([
    readVtp(caseUrl(waterPath)),
    readVtp(caseUrl(landslidePath)),
  ]);

  const entry = { water, landslide };
  state.frameCache.set(k, entry);
  trimFrameCache(k);

  return entry;
}

function trimFrameCache(centerIndex) {
  const keys = Array.from(state.frameCache.keys()).sort((a, b) => a - b);
  if (keys.length <= state.maxCachedFrames) return;

  const scored = keys.map((key) => ({ key, distance: Math.abs(key - centerIndex) }));
  scored.sort((a, b) => b.distance - a.distance);

  while (state.frameCache.size > state.maxCachedFrames && scored.length > 0) {
    const victim = scored.shift();
    if (victim && victim.key !== centerIndex) {
      state.frameCache.delete(victim.key);
    }
  }
}

function prefetchNearbyFrames(frameIndex) {
  const n = state.frameCount;
  for (const k of [frameIndex + 1, frameIndex - 1]) {
    if (k >= 0 && k < n && !state.frameCache.has(k)) {
      readFrameData(k).catch(() => {});
    }
  }
}

async function loadCaseAndData(container) {
  setStatus(container, 'Loading case.json...');

  const caseInfo = await fetchJson(CASE_JSON_URL);
  state.caseInfo = caseInfo;
  state.frameCount = getFrameCount(caseInfo);
  state.currentFrameIndex = getDefaultFrameIndex(caseInfo);
  state.compact.enabled = caseUsesCompactV2(caseInfo);

  const terrainPath = caseInfo.layers.terrain.file;
  const terrainUrl = caseUrl(terrainPath);

  console.log('[MANTA Gallery] case.json:', CASE_JSON_URL.href);
  console.log('[MANTA Gallery] terrain:', terrainUrl.href);

  setStatus(container, 'Loading terrain and default time frame...');

  const [terrain, frameData] = await Promise.all([
    readVtp(terrainUrl),
    Promise.all([
      loadCompactTemplates(caseInfo),
      readFrameData(state.currentFrameIndex),
    ]).then(([, loadedFrame]) => loadedFrame),
  ]);

  state.datasets.terrain = terrain;
  applyLoadedFrameData(frameData);

  prefetchNearbyFrames(state.currentFrameIndex);

  return {
    caseInfo,
    terrain,
    water: state.datasets.water,
    landslide: state.datasets.landslide,
    frameIndex: state.currentFrameIndex,
  };
}

function addActors(terrain, water, landslide) {
  const terrainActor = createSolidActor(terrain, [0.58, 0.58, 0.58], 1.0);
  const { actor: waterActor, scalarInfo: waterScalarInfo } = createScalarActor(
    water,
    ['wave_amplitude'],
    WATER_COLOR_STOPS,
    [0.10, 0.36, 0.85],
    WATER_SURFACE_OPACITY,
    {
      fixedRange: getWaterDisplayRange(),
      rangeMode: 'robust-symmetric',
      robustPercentile: 99.0,
    }
  );
  const { actor: landslideActor, scalarInfo: landslideScalarInfo } = createScalarActor(
    landslide,
    ['hm'],
    LANDSLIDE_COLOR_STOPS.hm,
    [0.90, 0.32, 0.12],
    0.92
  );

  state.actors.terrain = terrainActor;
  state.actors.water = waterActor;
  state.actors.landslide = landslideActor;
  state.scalarInfo.water = waterScalarInfo;
  state.scalarInfo.landslide = landslideScalarInfo;

  state.renderer.addActor(terrainActor);
  state.renderer.addActor(waterActor);
  state.renderer.addActor(landslideActor);

  resetCamera();

  setLegendReadout(
    'water-scalar-readout',
    waterScalarInfo ? `${waterScalarInfo.name} ${formatRange(waterScalarInfo.range)}` : 'solid'
  );

  setLegendReadout(
    'landslide-scalar-readout',
    landslideScalarInfo ? `${landslideScalarInfo.name} ${formatRange(landslideScalarInfo.range)}` : 'solid'
  );

  updateWaterColorbar();
  updateLandslideColorbar('hm');
}

function resetCamera() {
  if (!state.renderer || !state.renderWindow) return;

  state.renderer.resetCamera();

  const camera = state.renderer.getActiveCamera();
  camera.elevation(35);
  camera.azimuth(-35);
  camera.zoom(1.15);

  state.renderer.resetCameraClippingRange();
  state.renderWindow.render();
}

function updateFrameReadout(displayFrameIndex = state.currentFrameIndex, syncSlider = true) {
  const slider = document.getElementById('time-slider');
  const readout = document.getElementById('time-readout');
  const playButton = document.getElementById('play-toggle');

  const frameIndex = clampFrameIndex(state.caseInfo, displayFrameIndex);

  if (slider) {
    slider.max = String(Math.max(0, state.frameCount - 1));
    if (syncSlider) {
      slider.value = String(frameIndex);
    }
    slider.disabled = state.frameCount <= 1;
  }

  if (playButton) {
    playButton.disabled = state.frameCount <= 1;
    playButton.textContent = state.isPlaying ? 'Pause' : 'Play';
  }

  if (readout) {
    const loadingText = state.isFrameLoading ? 'loading…' : '';
    readout.textContent = `${getFrameLabel(state.caseInfo, frameIndex)}${loadingText ? ` · ${loadingText}` : ''}`;
  }
}

function updateCurrentFrameActors() {
  const waterScalarInfo = applyScalarToActor({
    actor: state.actors.water,
    polyData: state.datasets.water,
    arrayNames: ['wave_amplitude'],
    colorStops: WATER_COLOR_STOPS,
    fallbackColor: [0.10, 0.36, 0.85],
    fixedRange: getWaterDisplayRange(),
    rangeMode: 'robust-symmetric',
    robustPercentile: 99.0,
  });

  state.scalarInfo.water = waterScalarInfo;
  setLegendReadout(
    'water-scalar-readout',
    waterScalarInfo ? `${waterScalarInfo.name} ${formatRange(waterScalarInfo.range)}` : 'solid'
  );
  updateWaterColorbar();

  applyLandslideScalar(state.activeLandslideScalar);

  state.renderer?.resetCameraClippingRange();
  state.renderWindow?.render();
}

async function requestFrame(frameIndex, container) {
  const k = clampFrameIndex(state.caseInfo, frameIndex);

  if (state.isFrameLoading) {
    state.queuedFrameIndex = k;
    return;
  }

  if (k === state.currentFrameIndex && state.datasets.water && state.datasets.landslide) {
    updateFrameReadout();
    return;
  }

  state.isFrameLoading = true;
  state.queuedFrameIndex = null;
  updateFrameReadout(k, true);

  try {
    setStatus(container, `Loading ${getFrameLabel(state.caseInfo, k)}...`);
    const frameData = await readFrameData(k);

    applyLoadedFrameData(frameData);
    state.currentFrameIndex = k;

    updateCurrentFrameActors();
    updateFrameReadout();
    prefetchNearbyFrames(k);
    updateAmrForCurrentFrame(container).catch(() => {});

    setStatus(
      container,
      `Loaded Aqaba Case LSB C10 (${getFrameLabel(state.caseInfo, k)}). Drag to rotate, scroll to zoom.`
    );
  } catch (error) {
    console.error('[MANTA Gallery] failed to load frame:', error);
    stopPlayback();
    setStatus(container, `Failed to load ${getFrameLabel(state.caseInfo, k)}. Check Console and Network tabs.`, true);
  } finally {
    state.isFrameLoading = false;
    const queued = state.queuedFrameIndex;
    state.queuedFrameIndex = null;
    if (queued !== null && queued !== state.currentFrameIndex) {
      requestFrame(queued, container);
    }
  }
}

function startPlayback(container) {
  if (state.isPlaying || state.frameCount <= 1) return;

  state.isPlaying = true;
  updateFrameReadout();

  state.playTimer = window.setInterval(() => {
    const next = (state.currentFrameIndex + 1) % state.frameCount;
    requestFrame(next, container);
  }, state.playIntervalMs);
}

function stopPlayback() {
  if (state.playTimer !== null) {
    window.clearInterval(state.playTimer);
    state.playTimer = null;
  }
  state.isPlaying = false;
  updateFrameReadout();
}

function togglePlayback(container) {
  if (state.isPlaying) {
    stopPlayback();
  } else {
    startPlayback(container);
  }
}

function setupControls(container) {
  container.querySelector('#toggle-terrain')?.addEventListener('change', (event) => {
    state.actors.terrain?.setVisibility(event.target.checked);
    state.renderWindow.render();
  });

  container.querySelector('#toggle-water')?.addEventListener('change', (event) => {
    state.actors.water?.setVisibility(event.target.checked);
    state.renderWindow.render();
  });

  container.querySelector('#toggle-landslide')?.addEventListener('change', (event) => {
    state.actors.landslide?.setVisibility(event.target.checked);
    state.renderWindow.render();
  });

  const landslideScalarSelect = container.querySelector('#landslide-scalar');
  if (landslideScalarSelect) {
    const options = Array.from(landslideScalarSelect.options);

    for (const option of options) {
      option.disabled = !findDataArray(state.datasets.landslide, [option.value]);
    }

    const availableOptions = options.filter((option) => !option.disabled);
    landslideScalarSelect.disabled = availableOptions.length === 0;

    if (availableOptions.length > 0) {
      if (landslideScalarSelect.selectedOptions[0]?.disabled) {
        landslideScalarSelect.value = availableOptions[0].value;
      }

      state.activeLandslideScalar = landslideScalarSelect.value;
      applyLandslideScalar(landslideScalarSelect.value);
    }

    landslideScalarSelect.addEventListener('change', (event) => {
      applyLandslideScalar(event.target.value);
    });
  }

  const amrToggle = container.querySelector('#toggle-amr');
  if (amrToggle) {
    amrToggle.disabled = !hasAmrLayer();
    amrToggle.checked = false;
    state.amrVisible = false;
    amrToggle.addEventListener('change', (event) => {
      state.amrVisible = Boolean(event.target.checked);
      if (state.amrVisible) {
        updateAmrForCurrentFrame(container).catch(() => {});
      } else {
        clearAmrOutlineActors();
        state.renderWindow?.render();
      }
    });
  }

  container.querySelector('#reset-camera')?.addEventListener('click', () => {
    resetCamera();
  });

  const controls = container.querySelector('.manta-viewer-controls');
  if (controls) {
    for (const eventName of ['pointerdown', 'mousedown', 'touchstart', 'wheel', 'dblclick']) {
      controls.addEventListener(eventName, (event) => {
        event.stopPropagation();
      }, { passive: true });
    }
  }

  container.querySelector('#play-toggle')?.addEventListener('click', (event) => {
    event.stopPropagation();
    togglePlayback(container);
  });

  const slider = container.querySelector('#time-slider');
  if (slider) {
    slider.addEventListener('pointerdown', (event) => {
      event.stopPropagation();
      state.isScrubbing = true;
      stopPlayback();
    });

    slider.addEventListener('input', (event) => {
      event.stopPropagation();
      const k = clampFrameIndex(state.caseInfo, Number(event.target.value));
      updateFrameReadout(k, false);
      setStatus(container, `Selected ${getFrameLabel(state.caseInfo, k)}. Release slider to load frame.`);
    });

    slider.addEventListener('change', (event) => {
      event.stopPropagation();
      state.isScrubbing = false;
      requestFrame(Number(event.target.value), container);
    });

    slider.addEventListener('pointerup', () => {
      state.isScrubbing = false;
    });

    slider.addEventListener('keydown', (event) => {
      event.stopPropagation();
    });

    slider.addEventListener('keyup', (event) => {
      event.stopPropagation();
      requestFrame(Number(event.target.value), container);
    });
  }
  setupMThresholdControls(container);

  updateFrameReadout();
}



// -----------------------------------------------------------------------------
// Map-style viewport overlays: north arrow and dynamic scale bar.
// These are DOM/SVG overlays only; they do not touch the vtk.js data pipeline.
// North is +Y in the exported projected coordinate system, and scale is estimated
// at the camera focal plane from the active camera and render-window size.
// -----------------------------------------------------------------------------
const MAP_OVERLAY_CSS_ID = 'manta-map-overlays-css';
let mapOverlayRaf = null;

function ensureMapOverlayCss() {
  if (document.getElementById(MAP_OVERLAY_CSS_ID)) return;
  const style = document.createElement('style');
  style.id = MAP_OVERLAY_CSS_ID;
  style.textContent = `
    .manta-map-compass {
      position: absolute;
      left: 18px;
      bottom: 86px;
      z-index: 26;
      width: 118px;
      height: 118px;
      pointer-events: none;
      filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.30));
    }

    .manta-map-compass svg {
      width: 100%;
      height: 100%;
      display: block;
    }

    .manta-map-compass-card {
      fill: rgba(255, 255, 255, 0.88);
      stroke: rgba(31, 35, 40, 0.25);
      stroke-width: 1.0;
    }

    .manta-map-compass-ring {
      fill: rgba(246, 248, 250, 0.75);
      stroke: rgba(31, 35, 40, 0.62);
      stroke-width: 1.25;
    }

    .manta-map-compass-tick {
      stroke: rgba(31, 35, 40, 0.55);
      stroke-width: 1.0;
      stroke-linecap: round;
    }

    .manta-map-compass-minor {
      stroke: rgba(31, 35, 40, 0.28);
      stroke-width: 0.8;
      stroke-linecap: round;
    }

    .manta-map-compass-arrow-n {
      fill: #203f33;
      stroke: #10261d;
      stroke-width: 0.9;
    }

    .manta-map-compass-arrow-s {
      fill: #f7f0dc;
      stroke: #203f33;
      stroke-width: 0.9;
    }

    .manta-map-compass-n {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 17px;
      font-weight: 700;
      fill: #203f33;
      letter-spacing: 0.03em;
    }

    .manta-map-compass-label {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 8px;
      font-weight: 600;
      fill: rgba(31, 35, 40, 0.66);
      letter-spacing: 0.06em;
    }

    .manta-map-scale {
      position: absolute;
      right: 18px;
      bottom: 86px;
      z-index: 26;
      min-width: 170px;
      padding: 8px 10px 7px;
      border-radius: 8px;
      color: #24292f;
      background: rgba(255, 255, 255, 0.88);
      border: 1px solid rgba(31, 35, 40, 0.22);
      box-shadow: 0 3px 10px rgba(0, 0, 0, 0.22);
      pointer-events: none;
      font-family: Georgia, 'Times New Roman', serif;
      font-variant-numeric: tabular-nums;
    }

    .manta-map-scale-title {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: rgba(31, 35, 40, 0.70);
      margin-bottom: 4px;
    }

    .manta-map-scale-bar {
      position: relative;
      height: 12px;
      width: 140px;
      min-width: 64px;
      max-width: 260px;
      border: 1px solid rgba(31, 35, 40, 0.78);
      box-sizing: border-box;
      background: linear-gradient(to right, #111 0 25%, #fff 25% 50%, #111 50% 75%, #fff 75% 100%);
    }

    .manta-map-scale-bar::before,
    .manta-map-scale-bar::after {
      content: '';
      position: absolute;
      bottom: -5px;
      width: 1px;
      height: 5px;
      background: rgba(31, 35, 40, 0.78);
    }

    .manta-map-scale-bar::before { left: -1px; }
    .manta-map-scale-bar::after { right: -1px; }

    .manta-map-scale-labels {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 10px;
      margin-top: 5px;
      font-size: 12px;
      font-weight: 700;
      color: #24292f;
    }

    .manta-map-scale-subtitle {
      margin-top: 2px;
      font-size: 9px;
      color: rgba(31, 35, 40, 0.62);
      letter-spacing: 0.03em;
    }
  `;
  document.head.appendChild(style);
}

function vectorSubtract(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

function vectorDot(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function vectorCross(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function vectorLength(v) {
  return Math.hypot(v[0], v[1], v[2]);
}

function vectorNormalize(v) {
  const len = vectorLength(v);
  if (!Number.isFinite(len) || len <= 1e-12) return [0, 0, 0];
  return [v[0] / len, v[1] / len, v[2] / len];
}

function getCameraBasis() {
  const camera = state.renderer?.getActiveCamera?.();
  if (!camera) return null;

  const position = camera.getPosition?.();
  const focalPoint = camera.getFocalPoint?.();
  const viewUpRaw = camera.getViewUp?.();

  if (!position || !focalPoint || !viewUpRaw) return null;

  const viewDir = vectorNormalize(vectorSubtract(focalPoint, position));
  let viewUp = vectorNormalize(viewUpRaw);
  let right = vectorNormalize(vectorCross(viewDir, viewUp));

  // Re-orthogonalize up to avoid drift after repeated camera rotations.
  viewUp = vectorNormalize(vectorCross(right, viewDir));
  right = vectorNormalize(right);

  if (vectorLength(right) <= 1e-12 || vectorLength(viewUp) <= 1e-12) return null;
  return { camera, position, focalPoint, viewDir, right, viewUp };
}

function getNorthArrowAngleDegrees() {
  const basis = getCameraBasis();
  if (!basis) return 0;

  // In the exported UTM-like projected coordinates, map north is +Y.
  const north = [0, 1, 0];
  const sx = vectorDot(north, basis.right);
  const sy = vectorDot(north, basis.viewUp);

  if (!Number.isFinite(sx) || !Number.isFinite(sy) || Math.hypot(sx, sy) <= 1e-12) return 0;

  // SVG arrow points upward at 0°. Positive CSS rotation turns it clockwise.
  return Math.atan2(sx, sy) * 180.0 / Math.PI;
}

function createCompassOverlay(container) {
  let el = container.querySelector('#manta-map-compass');
  if (el) return el;

  el = document.createElement('div');
  el.id = 'manta-map-compass';
  el.className = 'manta-map-compass';
  el.innerHTML = `
    <svg viewBox="0 0 120 120" role="img" aria-label="North arrow">
      <rect x="8" y="8" width="104" height="104" rx="18" class="manta-map-compass-card"></rect>
      <circle cx="60" cy="60" r="42" class="manta-map-compass-ring"></circle>
      <g class="manta-map-compass-static">
        <line x1="60" y1="17" x2="60" y2="25" class="manta-map-compass-tick"></line>
        <line x1="60" y1="95" x2="60" y2="103" class="manta-map-compass-tick"></line>
        <line x1="17" y1="60" x2="25" y2="60" class="manta-map-compass-tick"></line>
        <line x1="95" y1="60" x2="103" y2="60" class="manta-map-compass-tick"></line>
        <line x1="31" y1="31" x2="36" y2="36" class="manta-map-compass-minor"></line>
        <line x1="89" y1="31" x2="84" y2="36" class="manta-map-compass-minor"></line>
        <line x1="31" y1="89" x2="36" y2="84" class="manta-map-compass-minor"></line>
        <line x1="89" y1="89" x2="84" y2="84" class="manta-map-compass-minor"></line>
      </g>
      <g id="manta-map-compass-rotor" transform="rotate(0 60 60)">
        <path d="M60 20 L72 61 L60 54 L48 61 Z" class="manta-map-compass-arrow-n"></path>
        <path d="M60 100 L48 61 L60 68 L72 61 Z" class="manta-map-compass-arrow-s"></path>
        <circle cx="60" cy="60" r="4.2" fill="#203f33"></circle>
      </g>
      <text x="60" y="17" text-anchor="middle" dominant-baseline="middle" class="manta-map-compass-n">N</text>
      <text x="60" y="111" text-anchor="middle" class="manta-map-compass-label">Aqaba DEM</text>
    </svg>
  `;
  container.appendChild(el);
  return el;
}

function createScaleOverlay(container) {
  let el = container.querySelector('#manta-map-scale');
  if (el) return el;

  el = document.createElement('div');
  el.id = 'manta-map-scale';
  el.className = 'manta-map-scale';
  el.innerHTML = `
    <div class="manta-map-scale-title">Scale</div>
    <div id="manta-map-scale-bar" class="manta-map-scale-bar"></div>
    <div class="manta-map-scale-labels">
      <span>0</span>
      <span id="manta-map-scale-label">—</span>
    </div>
    <div class="manta-map-scale-subtitle">at camera focal plane</div>
  `;
  container.appendChild(el);
  return el;
}

function niceScaleDistance(rawDistance) {
  if (!Number.isFinite(rawDistance) || rawDistance <= 0) return null;
  const exponent = Math.floor(Math.log10(rawDistance));
  const base = 10 ** exponent;
  const fraction = rawDistance / base;
  let niceFraction;
  if (fraction < 1.5) niceFraction = 1;
  else if (fraction < 3.5) niceFraction = 2;
  else if (fraction < 7.5) niceFraction = 5;
  else niceFraction = 10;
  return niceFraction * base;
}

function formatScaleDistance(distanceMeters) {
  if (!Number.isFinite(distanceMeters)) return '—';
  const d = Math.abs(distanceMeters);
  if (d >= 1000) {
    const km = distanceMeters / 1000.0;
    const absKm = Math.abs(km);
    if (absKm >= 100) return `${Math.round(km)} km`;
    if (absKm >= 10) return `${km.toFixed(1)} km`;
    return `${km.toFixed(2)} km`;
  }
  if (d >= 100) return `${Math.round(distanceMeters)} m`;
  if (d >= 10) return `${distanceMeters.toFixed(1)} m`;
  if (d >= 1) return `${distanceMeters.toFixed(2)} m`;
  return `${distanceMeters.toFixed(3)} m`;
}

function getMetersPerPixelAtFocalPlane(container) {
  const basis = getCameraBasis();
  if (!basis) return null;

  const rect = container.querySelector('.manta-vtk-host')?.getBoundingClientRect?.() ?? container.getBoundingClientRect();
  const height = Math.max(1, Number(rect?.height ?? 0));

  const camera = basis.camera;
  const parallel = Boolean(camera.getParallelProjection?.());

  if (parallel) {
    const parallelScale = Number(camera.getParallelScale?.());
    if (!Number.isFinite(parallelScale) || parallelScale <= 0) return null;
    return (2.0 * parallelScale) / height;
  }

  const distance = vectorLength(vectorSubtract(basis.position, basis.focalPoint));
  const viewAngleDegrees = Number(camera.getViewAngle?.() ?? 30.0);
  if (!Number.isFinite(distance) || distance <= 0 || !Number.isFinite(viewAngleDegrees) || viewAngleDegrees <= 0) {
    return null;
  }

  const visibleHeight = 2.0 * distance * Math.tan((viewAngleDegrees * Math.PI / 180.0) / 2.0);
  return visibleHeight / height;
}

function updateCompassOverlay(container) {
  const rotor = container.querySelector('#manta-map-compass-rotor');
  if (!rotor) return;
  const angle = getNorthArrowAngleDegrees();
  rotor.setAttribute('transform', `rotate(${angle.toFixed(2)} 60 60)`);
}

function updateScaleOverlay(container) {
  const bar = container.querySelector('#manta-map-scale-bar');
  const label = container.querySelector('#manta-map-scale-label');
  if (!bar || !label) return;

  const rect = container.querySelector('.manta-vtk-host')?.getBoundingClientRect?.() ?? container.getBoundingClientRect();
  const metersPerPixel = getMetersPerPixelAtFocalPlane(container);
  if (!Number.isFinite(metersPerPixel) || metersPerPixel <= 0) {
    label.textContent = '—';
    return;
  }

  const targetPixels = Math.max(95, Math.min(210, Number(rect?.width ?? 900) * 0.16));
  const niceDistance = niceScaleDistance(metersPerPixel * targetPixels);
  if (!niceDistance) {
    label.textContent = '—';
    return;
  }

  const pixelWidth = Math.max(70, Math.min(280, niceDistance / metersPerPixel));
  bar.style.width = `${pixelWidth.toFixed(0)}px`;
  label.textContent = formatScaleDistance(niceDistance);
}

function startMapOverlays(container) {
  ensureMapOverlayCss();
  createCompassOverlay(container);
  createScaleOverlay(container);

  if (mapOverlayRaf !== null) {
    window.cancelAnimationFrame(mapOverlayRaf);
    mapOverlayRaf = null;
  }

  const tick = () => {
    updateCompassOverlay(container);
    updateScaleOverlay(container);
    mapOverlayRaf = window.requestAnimationFrame(tick);
  };
  tick();
}

async function main() {
  const container = document.getElementById(VIEWER_ID);
  if (!container) {
    console.error(`[MANTA Gallery] Missing container: #${VIEWER_ID}`);
    return;
  }

  const host = setupDom(container);

  try {
    setupScene(host);

    const { caseInfo, terrain, water, landslide, frameIndex } = await loadCaseAndData(container);
    addActors(terrain, water, landslide);
    setupControls(container);
    
    startMapOverlays(container);
await updateAmrForCurrentFrame(container);

    setStatus(
      container,
      `Loaded Aqaba Case LSB C10 (${getFrameLabel(caseInfo, frameIndex)}). Drag to rotate, scroll to zoom.`
    );
  } catch (error) {
    console.error('[MANTA Gallery] viewer failed:', error);
    setStatus(container, 'Failed to load MANTA Gallery viewer. Check Console and Network tabs.', true);
  }
}

main();
