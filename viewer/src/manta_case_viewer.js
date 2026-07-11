import '@kitware/vtk.js/Rendering/Profiles/Geometry';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkTexture from '@kitware/vtk.js/Rendering/Core/Texture';
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

const DEFAULT_CASE_BASE_URL = new URL(
  /* @vite-ignore */ '../data/demo/aqaba_lsa_c10_angm25/',
  import.meta.url
);

const state = {
  caseInfo: null,
  renderer: null,
  renderWindow: null,
  openGLRenderWindow: null,
  interactor: null,
  container: null,
  caseBaseUrl: DEFAULT_CASE_BASE_URL,
  caseJsonUrl: new URL('case.json', DEFAULT_CASE_BASE_URL),
  viewerTitle: 'MANTA Gallery case',
  actors: {
    terrain: null,
    map: null,
    water: null,
    landslide: null,
    waterAnalysis: null,
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
    waterAnalysis: null,
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
  waterGlobalStats: {
    threshold: null,
    range: null,
    rawRange: null,
    token: 0,
    isComputing: false,
  },
  mapOverlay: {
    enabled: false,
    loading: false,
    token: 0,
    providerId: 'esri_world_imagery_labels',
    attribution: '',
  },
  terrainDrape: {
    source: null,
    sampler: null,
  },
  amrCache: new Map(),
  amrVisible: false,
  amrActors: new Map(),
  amrLoadToken: 0,
  analysis: {
    mode: null,
    history: null,
    historyThreshold: null,
    historyThrough: -1,
    historyLoadToken: 0,
  },
};

function injectCss() {
  if (document.getElementById('manta-case-viewer-css')) return;

  const style = document.createElement('style');
  style.id = 'manta-case-viewer-css';
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
      left: 24px;
      top: 24px;
      z-index: 20;
      max-width: min(1640px, calc(100% - 48px));
      padding: 14px 20px;
      border-radius: 12px;
      font-size: 26px;
      line-height: 1.35;
      color: #24292f;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
      pointer-events: none;
    }

    .manta-viewer-error {
      color: #b00020;
      font-weight: 700;
      pointer-events: auto;
    }

    .manta-amr-hud {
      position: absolute;
      left: 24px;
      top: 108px;
      z-index: 21;
      max-width: min(1520px, calc(100% - 48px));
      padding: 12px 18px;
      border-radius: 12px;
      font-size: 24px;
      line-height: 1.3;
      color: #24292f;
      background: rgba(255, 255, 255, 0.88);
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18);
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

    .manta-viewer-controls-row {
      display: flex;
      flex: 1 1 100%;
      flex-wrap: wrap;
      gap: 8px 12px;
      align-items: center;
    }

    .manta-analysis-controls {
      padding-top: 7px;
      border-top: 1px solid rgba(31, 35, 40, 0.14);
    }

    .manta-analysis-controls button[aria-pressed="true"] {
      color: #ffffff;
      background: #0969da;
      border-color: #0969da;
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
      right: 24px;
      top: 24px;
      z-index: 30;
      padding: 16px 20px;
      border-radius: 16px;
      font-size: 24px;
      color: #24292f;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
      width: 620px;
      max-width: calc(100% - 48px);
    }

    .manta-viewer-legend-title {
      font-weight: 700;
      margin-bottom: 10px;
    }

    .manta-viewer-legend-row {
      display: flex;
      align-items: center;
      gap: 14px;
      margin: 8px 0;
      white-space: nowrap;
    }

    .manta-swatch {
      width: 30px;
      height: 30px;
      flex: 0 0 30px;
      border-radius: 6px;
      border: 2px solid rgba(0, 0, 0, 0.25);
      display: inline-block;
    }

    .manta-viewer-legend-value {
      color: #57606a;
      font-size: 22px;
      margin-left: auto;
    }

    .manta-viewer-colorbars {
      margin-top: 18px;
      padding-top: 16px;
      border-top: 2px solid rgba(31, 35, 40, 0.14);
    }

    .manta-colorbar {
      margin-top: 16px;
    }

    .manta-colorbar:first-child {
      margin-top: 0;
    }

    .manta-colorbar-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 8px;
    }

    .manta-colorbar-title {
      font-weight: 700;
      color: #24292f;
    }

    .manta-colorbar-range {
      color: #57606a;
      font-size: 22px;
      white-space: nowrap;
    }

    .manta-colorbar-strip {
      width: 100%;
      height: 24px;
      border-radius: 999px;
      border: 2px solid rgba(31, 35, 40, 0.22);
      box-sizing: border-box;
      overflow: hidden;
    }

    .manta-colorbar-ticks {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-top: 6px;
      color: #57606a;
      font-size: 20px;
      line-height: 1.2;
    }

    .manta-colorbar-ticks-classified {
      position: relative;
      display: block;
      height: 34px;
      font-size: 18px;
    }

    .manta-colorbar-tick-classified {
      position: absolute;
      top: 0;
      transform: translateX(-50%);
      white-space: nowrap;
      text-align: center;
    }

    .manta-colorbar-tick-classified::before {
      content: '';
      position: absolute;
      left: 50%;
      top: -8px;
      width: 2px;
      height: 7px;
      transform: translateX(-50%);
      background: rgba(31, 35, 40, 0.48);
      border-radius: 999px;
    }

    .manta-colorbar-tick-classified:first-child {
      transform: translateX(0);
      text-align: left;
    }

    .manta-colorbar-tick-classified:first-child::before {
      left: 0;
      transform: none;
    }

    .manta-colorbar-tick-classified:last-child {
      transform: translateX(-100%);
      text-align: right;
    }

    .manta-colorbar-tick-classified:last-child::before {
      left: 100%;
      transform: translateX(-100%);
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
        <span id="terrain-scalar-readout" class="manta-viewer-legend-value">projection loading</span>
      </div>
      <div class="manta-viewer-legend-row">
        <span class="manta-swatch manta-swatch-water"></span>
        Water surface
        <span id="water-scalar-readout" class="manta-viewer-legend-value">loading</span>
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
          <div id="water-colorbar-ticks" class="manta-colorbar-ticks">
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
          <div id="landslide-colorbar-ticks" class="manta-colorbar-ticks">
            <span id="landslide-colorbar-min"></span>
            <span id="landslide-colorbar-mid"></span>
            <span id="landslide-colorbar-max"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="manta-viewer-controls">
      <div class="manta-viewer-controls-row">
      <label><input type="checkbox" id="toggle-terrain" checked> Terrain</label>
      <button id="toggle-map" type="button" aria-pressed="false" title="Fetch an online topographic basemap and drape it on the terrain mesh.">Map</button>
      <label title="Choose the online basemap provider used by the Map button.">
        Map source:
        <select id="map-provider">
          <option value="esri_world_imagery_labels" selected>Esri Imagery + Labels</option>
          <option value="opentopomap">OpenStreetMap Topographic</option>
          <option value="esri_world_street">Esri Streets</option>
        </select>
      </label>
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

      <div class="manta-viewer-controls-row manta-analysis-controls" aria-label="Water analysis overlays">
        <label title="Show current-frame inundation depth, filtered by the Water m threshold.">
          <input type="checkbox" id="toggle-inundation"> Inundation
        </label>
        <button id="show-max-inundation" type="button" aria-pressed="false" title="Accumulate maximum inundation depth from the first frame through the paused current frame.">
          Maximum inundation
        </button>
        <label title="Show current-frame water velocity arrows, filtered by the Water m threshold.">
          <input type="checkbox" id="toggle-velocity"> Velocity arrows
        </label>
        <button id="show-max-velocity" type="button" aria-pressed="false" title="Accumulate maximum wave velocity from the first frame through the paused current frame.">
          Maximum wave velocity
        </button>
      </div>
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
  return new URL(path, state.caseBaseUrl);
}

function resolveCaseBaseUrl(container) {
  const configured = container?.dataset?.caseBaseUrl;
  if (configured) return new URL(configured, window.location.href);
  return DEFAULT_CASE_BASE_URL;
}

function configureCaseFromContainer(container) {
  state.container = container;
  state.caseBaseUrl = resolveCaseBaseUrl(container);
  state.caseJsonUrl = new URL(container?.dataset?.caseJson ?? 'case.json', state.caseBaseUrl);
  state.viewerTitle = container?.dataset?.caseTitle || 'MANTA Gallery case';
}

function getCaseDisplayTitle(caseInfo = state.caseInfo) {
  return caseInfo?.title || state.viewerTitle || 'MANTA Gallery case';
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

function getWaterStatisticsPercentile() {
  const percentile = Number(state.caseInfo?.layers?.water?.colorbar?.statistics?.abs_percentile);
  return Number.isFinite(percentile) ? percentile : WATER_GLOBAL_STATS_PERCENTILE_FALLBACK;
}

function getCurrentWaterMThreshold() {
  const threshold = Number(state.mThresholds.waterMax);
  return Number.isFinite(threshold) ? threshold : 0.30;
}

function getDefaultWaterMThreshold() {
  const threshold = Number(state.caseInfo?.layers?.water?.default_m);
  return Number.isFinite(threshold) ? threshold : 0.30;
}

function thresholdsMatch(a, b) {
  const left = Number(a);
  const right = Number(b);
  return Number.isFinite(left) && Number.isFinite(right) && Math.abs(left - right) <= 1e-9;
}

function getManifestWaterGlobalRangeForThreshold(threshold) {
  if (!thresholdsMatch(threshold, getDefaultWaterMThreshold())) return null;
  return finitePairRange(state.caseInfo?.layers?.water?.colorbar?.statistics?.ocean_default_m_raw_range)
    ?? finitePairRange(state.caseInfo?.layers?.water?.colorbar?.statistics?.ocean_default_m_range)
    ?? finitePairRange(state.caseInfo?.layers?.water?.colorbar?.statistics?.raw_exported_range);
}

function getManifestWaterDisplayRangeForThreshold(threshold) {
  if (!thresholdsMatch(threshold, getDefaultWaterMThreshold())) return null;
  return finitePairRange(state.caseInfo?.layers?.water?.colorbar?.statistics?.ocean_default_m_display_range)
    ?? getWaterStatisticsRange();
}

function getWaterGlobalRange() {
  const threshold = getCurrentWaterMThreshold();
  if (
    thresholdsMatch(state.waterGlobalStats.threshold, threshold)
    && finitePairRange(state.waterGlobalStats.rawRange)
  ) {
    return state.waterGlobalStats.rawRange;
  }
  return getManifestWaterGlobalRangeForThreshold(threshold);
}

function getLandslideGlobalRange(scalarName) {
  return finitePairRange(
    state.caseInfo?.layers?.landslide?.available_scalars?.[scalarName]?.range
  );
}

function getWaterDisplayRange() {
  const threshold = getCurrentWaterMThreshold();
  if (
    thresholdsMatch(state.waterGlobalStats.threshold, threshold)
    && finitePairRange(state.waterGlobalStats.range)
  ) {
    return symmetricRangeFromRange(state.waterGlobalStats.range);
  }

  const manifestDisplayRange = getManifestWaterDisplayRangeForThreshold(threshold);
  if (manifestDisplayRange) return symmetricRangeFromRange(manifestDisplayRange);

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

function getSeaLevel() {
  const seaLevel = Number(state.caseInfo?.processing?.sea_level);
  return Number.isFinite(seaLevel) ? seaLevel : 0.0;
}

function getWaterOverlayRange(overlayName) {
  const configured = finitePairRange(
    state.caseInfo?.layers?.water?.analysis_overlays?.[overlayName]?.range
  );
  if (!configured) return null;
  return [0.0, Math.max(Math.abs(configured[0]), Math.abs(configured[1]), 1e-12)];
}

function getInundationColorSpec(range = getWaterOverlayRange('inundation')) {
  const vmax = Math.max(Number(range?.[1] ?? 15.0), 1e-12);
  const boundaries = [0.0, 0.5, 1.0, 2.5, 5.0, 7.5, 10.0, 15.0, vmax]
    .filter((value, index, values) => value <= vmax && (index === 0 || value > values[index - 1]));
  if (boundaries[boundaries.length - 1] < vmax) boundaries.push(vmax);
  if (boundaries.length < 2) boundaries.push(vmax);

  const stops = [];
  const legendStops = [];
  for (let i = 0; i < boundaries.length - 1; i += 1) {
    const color = INUNDATION_CLASS_COLORS[Math.min(i, INUNDATION_CLASS_COLORS.length - 1)];
    const lo = boundaries[i] / vmax;
    const hi = boundaries[i + 1] / vmax;
    stops.push([lo, ...color], [hi, ...color]);
    const legendLo = i / (boundaries.length - 1);
    const legendHi = (i + 1) / (boundaries.length - 1);
    legendStops.push([legendLo, ...color], [legendHi, ...color]);
  }
  return {
    stops,
    legendStops,
    boundaries,
    legendTicks: boundaries.map((value, index) => ({
      value,
      position: index / (boundaries.length - 1),
    })),
  };
}

function getInundationColorStops(range = getWaterOverlayRange('inundation')) {
  return getInundationColorSpec(range).stops;
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

const TERRAIN_DRAPE_LOOKUP_SCALE = 1000;
const TERRAIN_DRAPE_COORD_TOLERANCE = 1 / TERRAIN_DRAPE_LOOKUP_SCALE;

function terrainDrapeKey(value) {
  return Math.round(Number(value) * TERRAIN_DRAPE_LOOKUP_SCALE);
}

function lowerBound(values, target) {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (values[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function bracketSortedValue(values, target) {
  if (!values?.length || !Number.isFinite(target)) return null;
  const min = values[0];
  const max = values[values.length - 1];
  if (target < min - TERRAIN_DRAPE_COORD_TOLERANCE || target > max + TERRAIN_DRAPE_COORD_TOLERANCE) {
    return null;
  }
  if (target <= min) return { lo: 0, hi: 0, t: 0 };
  if (target >= max) {
    const last = values.length - 1;
    return { lo: last, hi: last, t: 0 };
  }
  const upper = lowerBound(values, target);
  if (upper <= 0) return { lo: 0, hi: 0, t: 0 };
  if (upper >= values.length) {
    const last = values.length - 1;
    return { lo: last, hi: last, t: 0 };
  }
  if (values[upper] === target) return { lo: upper, hi: upper, t: 0 };
  const lo = upper - 1;
  const x0 = values[lo];
  const x1 = values[upper];
  const span = x1 - x0;
  return {
    lo,
    hi: upper,
    t: span > 0 ? (target - x0) / span : 0,
  };
}

function terrainGridValue(sampler, xIndex, yIndex) {
  const value = sampler.zValues[yIndex * sampler.xValues.length + xIndex];
  return Number.isFinite(value) ? value : Number.NaN;
}

function interpolateTerrainGrid(sampler, x, y) {
  const xb = bracketSortedValue(sampler.xValues, x);
  const yb = bracketSortedValue(sampler.yValues, y);
  if (!xb || !yb) return Number.NaN;

  const z00 = terrainGridValue(sampler, xb.lo, yb.lo);
  if (xb.lo === xb.hi && yb.lo === yb.hi) return z00;

  const z10 = terrainGridValue(sampler, xb.hi, yb.lo);
  const z01 = terrainGridValue(sampler, xb.lo, yb.hi);
  const z11 = terrainGridValue(sampler, xb.hi, yb.hi);
  const corners = [
    { z: z00, w: (1 - xb.t) * (1 - yb.t) },
    { z: z10, w: xb.t * (1 - yb.t) },
    { z: z01, w: (1 - xb.t) * yb.t },
    { z: z11, w: xb.t * yb.t },
  ];

  let weighted = 0;
  let weightSum = 0;
  for (const corner of corners) {
    if (!Number.isFinite(corner.z) || corner.w <= 0) continue;
    weighted += corner.z * corner.w;
    weightSum += corner.w;
  }
  return weightSum > 0 ? weighted / weightSum : Number.NaN;
}

function createTerrainDrapeSampler(points) {
  const xByKey = new Map();
  const yByKey = new Map();
  for (let i = 0; i < points.length; i += 3) {
    const x = points[i];
    const y = points[i + 1];
    const z = points[i + 2];
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
    xByKey.set(terrainDrapeKey(x), x);
    yByKey.set(terrainDrapeKey(y), y);
  }

  const xKeys = Array.from(xByKey.keys()).sort((a, b) => a - b);
  const yKeys = Array.from(yByKey.keys()).sort((a, b) => a - b);
  const xIndexByKey = new Map(xKeys.map((key, index) => [key, index]));
  const yIndexByKey = new Map(yKeys.map((key, index) => [key, index]));
  const xValues = Float64Array.from(xKeys, (key) => xByKey.get(key));
  const yValues = Float64Array.from(yKeys, (key) => yByKey.get(key));
  const zValues = new Float32Array(xValues.length * yValues.length);
  zValues.fill(Number.NaN);

  for (let i = 0; i < points.length; i += 3) {
    const x = points[i];
    const y = points[i + 1];
    const z = points[i + 2];
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
    const xi = xIndexByKey.get(terrainDrapeKey(x));
    const yi = yIndexByKey.get(terrainDrapeKey(y));
    if (xi === undefined || yi === undefined) continue;
    zValues[yi * xValues.length + xi] = z;
  }

  return {
    xValues,
    yValues,
    zValues,
  };
}

function getTerrainDrapeSampler() {
  const terrain = state.datasets.terrain;
  const points = terrain?.getPoints?.()?.getData?.();
  if (!terrain || !points) return null;
  if (state.terrainDrape.source === terrain && state.terrainDrape.sampler) {
    return state.terrainDrape.sampler;
  }
  const sampler = createTerrainDrapeSampler(points);
  state.terrainDrape.source = terrain;
  state.terrainDrape.sampler = sampler;
  return sampler;
}

function compactPointHasFiniteZ(template, pointId) {
  return Number.isFinite(template.pointValues[pointId * 3 + 2]);
}

function getCompactTemplateTerrainZ(template, terrainSampler) {
  if (!terrainSampler) return null;
  const pointCount = template.pointValues.length / 3;
  if (
    template.terrainDrapeSampler === terrainSampler
      && template.terrainDrapeZ?.length === pointCount
  ) {
    return template.terrainDrapeZ;
  }

  const terrainZ = new Float32Array(pointCount);
  for (let pointId = 0; pointId < pointCount; pointId += 1) {
    const base = pointId * 3;
    terrainZ[pointId] = interpolateTerrainGrid(
      terrainSampler,
      template.pointValues[base],
      template.pointValues[base + 1]
    );
  }
  template.terrainDrapeSampler = terrainSampler;
  template.terrainDrapeZ = terrainZ;
  return terrainZ;
}

function getCompactPointRenderZ(layerName, frameArrays, pointId, terrainZ) {
  if (layerName !== 'landslide') return frameArrays.z[pointId];
  if (!terrainZ) return frameArrays.z[pointId];
  return Number.isFinite(terrainZ[pointId]) ? terrainZ[pointId] : Number.NaN;
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
  const cellCount = Math.floor(quads.length / 4);
  const keepPoint = compactMPointPredicate(template.layerName);
  let visibleCellCount = 0;

  function keepCell(cellIndex) {
    return compactCellPassesM(template, frameArrays, cellIndex, keepPoint);
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

function compactCellPassesM(
  template,
  frameArrays,
  cellIndex,
  keepPoint = compactMPointPredicate(template.layerName)
) {
  if (!compactBitIsSet(frameArrays.valid_cells, cellIndex)) return false;
  const base = cellIndex * 4;
  const quads = template.quads;
  const m = frameArrays.m;
  return compactPointHasFiniteZ(template, quads[base])
    && compactPointHasFiniteZ(template, quads[base + 1])
    && compactPointHasFiniteZ(template, quads[base + 2])
    && compactPointHasFiniteZ(template, quads[base + 3])
    && keepPoint(m[quads[base]])
    && keepPoint(m[quads[base + 1]])
    && keepPoint(m[quads[base + 2]])
    && keepPoint(m[quads[base + 3]]);
}

function compactCellPassesMThreshold(template, frameArrays, cellIndex, threshold) {
  if (!compactBitIsSet(frameArrays.valid_cells, cellIndex)) return false;
  const base = cellIndex * 4;
  const quads = template.quads;
  const m = frameArrays.m;
  const waterMax = Number.isFinite(threshold) ? threshold : getDefaultWaterMThreshold();
  return Number.isFinite(m[quads[base]])
    && Number.isFinite(m[quads[base + 1]])
    && Number.isFinite(m[quads[base + 2]])
    && Number.isFinite(m[quads[base + 3]])
    && m[quads[base]] <= waterMax
    && m[quads[base + 1]] <= waterMax
    && m[quads[base + 2]] <= waterMax
    && m[quads[base + 3]] <= waterMax;
}

function compactPolysFromCellPredicate(template, keepCell) {
  const quads = template.quads;
  const cellCount = Math.floor(quads.length / 4);
  let selectedCount = 0;
  for (let cellIndex = 0; cellIndex < cellCount; cellIndex += 1) {
    if (keepCell(cellIndex)) selectedCount += 1;
  }

  const polys = new Uint32Array(selectedCount * 5);
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

function compactPointMaskFromCellPredicate(template, keepCell) {
  const quads = template.quads;
  const cellCount = Math.floor(quads.length / 4);
  const pointMask = new Uint8Array(template.pointValues.length / 3);
  for (let cellIndex = 0; cellIndex < cellCount; cellIndex += 1) {
    if (!keepCell(cellIndex)) continue;
    const base = cellIndex * 4;
    pointMask[quads[base]] = 1;
    pointMask[quads[base + 1]] = 1;
    pointMask[quads[base + 2]] = 1;
    pointMask[quads[base + 3]] = 1;
  }
  return pointMask;
}

function updateCompactLayerDataset(layerName, frameArrays) {
  const template = state.compact.templates[layerName];
  if (!template || !frameArrays) return;

  const z = frameArrays.z;
  if (z.length * 3 !== template.pointValues.length) {
    throw new Error(`Compact-v2 ${layerName} frame z length does not match its template.`);
  }

  const terrainSampler = layerName === 'landslide' ? getTerrainDrapeSampler() : null;
  const terrainZ = layerName === 'landslide'
    ? getCompactTemplateTerrainZ(template, terrainSampler)
    : null;
  for (let i = 0; i < z.length; i += 1) {
    template.pointValues[i * 3 + 2] = getCompactPointRenderZ(
      layerName,
      frameArrays,
      i,
      terrainZ
    );
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

function waterAnalysisIsAvailable() {
  const frame = state.compact.currentFrames.water;
  return Boolean(
    state.compact.enabled
      && frame?.z
      && frame?.m
      && frame?.h
      && frame?.u
      && frame?.v
  );
}

function getWaterDryTolerance() {
  const configured = Number(state.caseInfo?.processing?.water_surface?.dry_tolerance);
  return Number.isFinite(configured) ? configured : 5.0e-4;
}

function getWaterCellPredicate(frameArrays, pointPredicate = null) {
  return getWaterCellPredicateForThreshold(frameArrays, getCurrentWaterMThreshold(), pointPredicate);
}

function getWaterCellPredicateForThreshold(frameArrays, threshold, pointPredicate = null) {
  const template = state.compact.templates.water;
  return (cellIndex) => {
    if (!compactCellPassesMThreshold(template, frameArrays, cellIndex, threshold)) return false;
    if (!pointPredicate) return true;
    const base = cellIndex * 4;
    const quads = template.quads;
    return pointPredicate(quads[base])
      && pointPredicate(quads[base + 1])
      && pointPredicate(quads[base + 2])
      && pointPredicate(quads[base + 3]);
  };
}

function finiteMaskedRange(values, mask = null) {
  if (!values) return null;
  let vmin = Number.POSITIVE_INFINITY;
  let vmax = Number.NEGATIVE_INFINITY;
  for (let i = 0; i < values.length; i += 1) {
    if (mask && !mask[i]) continue;
    const value = Number(values[i]);
    if (!Number.isFinite(value)) continue;
    vmin = Math.min(vmin, value);
    vmax = Math.max(vmax, value);
  }
  return Number.isFinite(vmin) && Number.isFinite(vmax) ? [vmin, vmax] : null;
}

function positivePercentileRange(values, percentile) {
  if (!values) return null;
  const positiveValues = [];
  for (const value of values) {
    const numericValue = Number(value);
    if (Number.isFinite(numericValue) && numericValue > 0.0) {
      positiveValues.push(numericValue);
    }
  }
  if (positiveValues.length === 0) return null;
  positiveValues.sort((a, b) => a - b);
  const q = Math.min(100.0, Math.max(0.0, Number(percentile)));
  const index = Math.min(
    positiveValues.length - 1,
    Math.max(0, Math.floor((q / 100.0) * (positiveValues.length - 1)))
  );
  return [0.0, Math.max(positiveValues[index], 1e-12)];
}

function getCurrentVisibleWaveRange() {
  if (!waterAnalysisIsAvailable()) return state.scalarInfo.water?.rawRange ?? null;
  const template = state.compact.templates.water;
  const frame = state.compact.currentFrames.water;
  const seaLevel = getSeaLevel();
  const pointMask = compactPointMaskFromCellPredicate(
    template,
    getWaterCellPredicate(frame, (pointId) => {
      const z = Number(frame.z[pointId]);
      const h = Number(frame.h[pointId]);
      return Number.isFinite(z) && Number.isFinite(h) && z - h <= seaLevel;
    })
  );
  return finiteMaskedRange(frame.wave_amplitude, pointMask);
}

function resetWaterGlobalStats() {
  state.waterGlobalStats.threshold = null;
  state.waterGlobalStats.range = null;
  state.waterGlobalStats.rawRange = null;
  state.waterGlobalStats.isComputing = false;
  state.waterGlobalStats.token += 1;
}

function percentileRangeFromAbsHistogram(histogram, totalCount, maxAbs, percentile) {
  if (!Number.isFinite(totalCount) || totalCount <= 0 || !Number.isFinite(maxAbs) || maxAbs <= 0.0) {
    return null;
  }
  const target = Math.max(1, Math.ceil((Math.min(100.0, Math.max(0.0, percentile)) / 100.0) * totalCount));
  let cumulative = 0;
  for (let bin = 0; bin < histogram.length; bin += 1) {
    cumulative += histogram[bin];
    if (cumulative >= target) {
      const limit = Math.max(maxAbs * ((bin + 1) / histogram.length), 1e-12);
      return [-limit, limit];
    }
  }
  return [-maxAbs, maxAbs];
}

async function computeWaterGlobalRangeForThreshold(threshold, container = null) {
  if (!state.compact.enabled || !state.compact.templates.water || !state.caseInfo) return null;

  const token = ++state.waterGlobalStats.token;
  state.waterGlobalStats.isComputing = true;
  state.waterGlobalStats.threshold = threshold;
  state.waterGlobalStats.range = null;
  state.waterGlobalStats.rawRange = null;

  const rawRange = finitePairRange(state.caseInfo?.layers?.water?.colorbar?.statistics?.raw_exported_range)
    ?? finitePairRange(state.caseInfo?.layers?.water?.colorbar?.statistics?.ocean_default_m_raw_range)
    ?? getWaterStatisticsRange()
    ?? [-1.0, 1.0];
  const histogramMaxAbs = Math.max(Math.abs(rawRange[0]), Math.abs(rawRange[1]), 1.0e-12);
  const histogram = new Uint32Array(WATER_GLOBAL_STATS_BINS);
  const template = state.compact.templates.water;
  const pointCount = template.pointValues.length / 3;
  const frameCount = getFrameCount(state.caseInfo);
  const percentile = getWaterStatisticsPercentile();
  const seaLevel = getSeaLevel();

  let count = 0;
  let minValue = Number.POSITIVE_INFINITY;
  let maxValue = Number.NEGATIVE_INFINITY;

  for (let frameIndex = 0; frameIndex < frameCount; frameIndex += 1) {
    if (token !== state.waterGlobalStats.token) return null;
    if (container && (frameIndex === 0 || frameIndex === frameCount - 1 || frameIndex % 12 === 0)) {
      setStatus(container, `Computing ocean wave-height statistics for Water m≤${threshold} (${frameIndex + 1}/${frameCount})...`);
    }
    const frame = await readWaterFrameForAnalysis(frameIndex);
    const pointMask = compactPointMaskFromCellPredicate(
      template,
      getWaterCellPredicateForThreshold(frame, threshold)
    );
    for (let pointId = 0; pointId < pointCount; pointId += 1) {
      if (!pointMask[pointId]) continue;
      const value = Number(frame.wave_amplitude[pointId]);
      const z = Number(frame.z[pointId]);
      const h = Number(frame.h[pointId]);
      if (!Number.isFinite(value) || !Number.isFinite(z) || !Number.isFinite(h)) continue;
      const b = z - h;
      if (!(b <= seaLevel)) continue;
      minValue = Math.min(minValue, value);
      maxValue = Math.max(maxValue, value);
      const absValue = Math.abs(value);
      const bin = Math.min(
        histogram.length - 1,
        Math.max(0, Math.floor((absValue / histogramMaxAbs) * histogram.length))
      );
      histogram[bin] += 1;
      count += 1;
    }
  }

  if (token !== state.waterGlobalStats.token) return null;

  const range = percentileRangeFromAbsHistogram(histogram, count, histogramMaxAbs, percentile);
  state.waterGlobalStats.isComputing = false;
  state.waterGlobalStats.threshold = threshold;
  state.waterGlobalStats.range = range;
  state.waterGlobalStats.rawRange = Number.isFinite(minValue) && Number.isFinite(maxValue)
    ? [minValue, maxValue]
    : null;
  updateWaterLegendReadout(container);

  if (range && thresholdsMatch(threshold, getCurrentWaterMThreshold()) && state.actors.water) {
    updateCurrentFrameActors();
  }
  return range;
}

function maskedScalarValues(values, pointMask) {
  const masked = new Float32Array(values.length);
  masked.fill(Number.NaN);
  for (let i = 0; i < values.length; i += 1) {
    if (pointMask[i]) masked[i] = values[i];
  }
  return masked;
}

function createSurfaceOverlayDataset(zValues, scalarName, scalarValues, keepCell) {
  const template = state.compact.templates.water;
  const pointValues = new Float32Array(template.pointValues);
  for (let i = 0; i < zValues.length; i += 1) {
    const z = Number(zValues[i]);
    pointValues[i * 3 + 2] = Number.isFinite(z) ? z + ANALYSIS_SURFACE_LIFT : Number.NaN;
  }

  const points = vtkPoints.newInstance();
  points.setData(pointValues, 3);
  const polys = vtkCellArray.newInstance();
  polys.setData(compactPolysFromCellPredicate(template, keepCell));

  const polyData = vtkPolyData.newInstance();
  polyData.setPoints(points);
  polyData.setPolys(polys);
  polyData.getPointData().addArray(vtkDataArray.newInstance({
    name: scalarName,
    numberOfComponents: 1,
    values: scalarValues,
  }));
  return polyData;
}

function createCurrentInundationDataset() {
  const template = state.compact.templates.water;
  const frame = state.compact.currentFrames.water;
  const seaLevel = getSeaLevel();
  const dryTolerance = getWaterDryTolerance();
  const isInundated = (pointId) => {
    const h = Number(frame.h[pointId]);
    const z = Number(frame.z[pointId]);
    return Number.isFinite(h)
      && Number.isFinite(z)
      && h > dryTolerance
      && z - h >= seaLevel;
  };
  const keepCell = getWaterCellPredicate(frame, isInundated);
  const pointMask = compactPointMaskFromCellPredicate(template, keepCell);
  return createSurfaceOverlayDataset(frame.z, 'inundation_depth', maskedScalarValues(frame.h, pointMask), keepCell);
}

function createMaximumInundationDataset() {
  const template = state.compact.templates.water;
  const history = state.analysis.history;
  const keepCell = (cellIndex) => {
    const base = cellIndex * 4;
    const quads = template.quads;
    return Number.isFinite(history.inundationDepth[quads[base]])
      && Number.isFinite(history.inundationDepth[quads[base + 1]])
      && Number.isFinite(history.inundationDepth[quads[base + 2]])
      && Number.isFinite(history.inundationDepth[quads[base + 3]]);
  };
  return createSurfaceOverlayDataset(
    history.inundationZ,
    'maximum_inundation_depth',
    history.inundationDepth,
    keepCell
  );
}

function createMaximumVelocityDataset() {
  const template = state.compact.templates.water;
  const history = state.analysis.history;
  const keepCell = (cellIndex) => {
    const base = cellIndex * 4;
    const quads = template.quads;
    return Number.isFinite(history.velocitySpeed[quads[base]])
      && Number.isFinite(history.velocitySpeed[quads[base + 1]])
      && Number.isFinite(history.velocitySpeed[quads[base + 2]])
      && Number.isFinite(history.velocitySpeed[quads[base + 3]]);
  };
  return createSurfaceOverlayDataset(
    history.velocityZ,
    'maximum_wave_velocity',
    history.velocitySpeed,
    keepCell
  );
}

function getVelocityArrowOptions() {
  const configured = state.caseInfo?.layers?.water?.analysis_overlays?.velocity ?? {};
  const stride = Math.max(1, Math.round(Number(configured.arrow_stride) || VELOCITY_ARROW_STRIDE));
  const scale = Math.max(0.0, Number(configured.arrow_scale) || VELOCITY_ARROW_SCALE);
  const maxCount = Math.max(1, Math.round(Number(configured.arrow_max_count) || VELOCITY_ARROW_MAX_COUNT));
  const minSpeed = Math.max(0.0, Number(configured.arrow_min_speed) || VELOCITY_ARROW_MIN_SPEED);
  const detail = state.caseInfo?.processing?.water_surface?.coastal_detail ?? {};
  const spacings = [Number(detail.row_spacing_m), Number(detail.col_spacing_m)]
    .filter((value) => Number.isFinite(value) && value > 0.0);
  const cellScale = spacings.length > 0 ? Math.min(...spacings) : 1.0;
  return { stride, scale, maxCount, minSpeed, cellScale };
}

function spatiallySampleVelocityCandidates(candidates, template, maxCount) {
  if (candidates.length <= maxCount) return candidates;
  let xmin = Number.POSITIVE_INFINITY;
  let xmax = Number.NEGATIVE_INFINITY;
  let ymin = Number.POSITIVE_INFINITY;
  let ymax = Number.NEGATIVE_INFINITY;
  for (const candidate of candidates) {
    const pointBase = candidate.pointId * 3;
    const x = Number(template.pointValues[pointBase]);
    const y = Number(template.pointValues[pointBase + 1]);
    xmin = Math.min(xmin, x);
    xmax = Math.max(xmax, x);
    ymin = Math.min(ymin, y);
    ymax = Math.max(ymax, y);
  }

  const width = Math.max(xmax - xmin, 1.0);
  const height = Math.max(ymax - ymin, 1.0);
  const columnCount = Math.max(1, Math.ceil(Math.sqrt(maxCount * width / height)));
  const rowCount = Math.max(1, Math.floor(maxCount / columnCount));
  const buckets = new Map();
  for (const candidate of candidates) {
    const pointBase = candidate.pointId * 3;
    const x = Number(template.pointValues[pointBase]);
    const y = Number(template.pointValues[pointBase + 1]);
    const column = Math.min(columnCount - 1, Math.floor(columnCount * (x - xmin) / width));
    const row = Math.min(rowCount - 1, Math.floor(rowCount * (y - ymin) / height));
    const key = row * columnCount + column;
    const previous = buckets.get(key);
    if (!previous || candidate.speed > previous.speed) buckets.set(key, candidate);
  }
  return Array.from(buckets.values()).sort((a, b) => a.pointId - b.pointId);
}

function createVelocityArrowDataset() {
  const template = state.compact.templates.water;
  const frame = state.compact.currentFrames.water;
  const visiblePoints = compactPointMaskFromCellPredicate(template, getWaterCellPredicate(frame));
  const options = getVelocityArrowOptions();
  const candidates = [];

  for (let pointId = 0; pointId < visiblePoints.length; pointId += options.stride) {
    if (!visiblePoints[pointId]) continue;
    const u = Number(frame.u[pointId]);
    const v = Number(frame.v[pointId]);
    const speed = Math.hypot(u, v);
    if (Number.isFinite(speed) && speed >= options.minSpeed) {
      candidates.push({ pointId, speed });
    }
  }

  const sampledCandidates = spatiallySampleVelocityCandidates(candidates, template, options.maxCount);
  const arrowCount = sampledCandidates.length;
  const pointValues = new Float32Array(arrowCount * 18);
  const lineValues = new Uint32Array(arrowCount * 9);
  const speedValues = new Float32Array(arrowCount * 6);
  let arrowIndex = 0;

  for (const candidate of sampledCandidates) {
    const pointId = candidate.pointId;
    const pointBase = pointId * 3;
    const x = Number(template.pointValues[pointBase]);
    const y = Number(template.pointValues[pointBase + 1]);
    const z = Number(frame.z[pointId]) + ANALYSIS_SURFACE_LIFT;
    const u = Number(frame.u[pointId]);
    const v = Number(frame.v[pointId]);
    const speed = candidate.speed;
    const lengthScale = options.scale * options.cellScale;
    const dx = u * lengthScale;
    const dy = v * lengthScale;
    const endX = x + dx;
    const endY = y + dy;
    const wingX = -dx * 0.24;
    const wingY = -dy * 0.24;
    const perpX = -dy * 0.14;
    const perpY = dx * 0.14;
    const xyz = [
      x, y, z, endX, endY, z,
      endX, endY, z, endX + wingX + perpX, endY + wingY + perpY, z,
      endX, endY, z, endX + wingX - perpX, endY + wingY - perpY, z,
    ];
    pointValues.set(xyz, arrowIndex * 18);
    speedValues.fill(speed, arrowIndex * 6, arrowIndex * 6 + 6);
    const firstPoint = arrowIndex * 6;
    lineValues.set([
      2, firstPoint, firstPoint + 1,
      2, firstPoint + 2, firstPoint + 3,
      2, firstPoint + 4, firstPoint + 5,
    ], arrowIndex * 9);
    arrowIndex += 1;
  }

  const points = vtkPoints.newInstance();
  points.setData(pointValues, 3);
  const lines = vtkCellArray.newInstance();
  lines.setData(lineValues);
  const polyData = vtkPolyData.newInstance();
  polyData.setPoints(points);
  polyData.setLines(lines);
  polyData.getPointData().addArray(vtkDataArray.newInstance({
    name: 'wave_velocity',
    numberOfComponents: 1,
    values: speedValues,
  }));
  return polyData;
}

function emptyMaximumArray(pointCount) {
  const values = new Float32Array(pointCount);
  values.fill(Number.NaN);
  return values;
}

function resetWaterAnalysisHistory() {
  const maximumModeWasActive = state.analysis.mode === 'maximumInundation' || state.analysis.mode === 'maximumVelocity';
  state.analysis.history = null;
  state.analysis.historyThreshold = null;
  state.analysis.historyThrough = -1;
  state.analysis.historyLoadToken += 1;
  if (maximumModeWasActive) {
    state.analysis.mode = null;
    removeWaterAnalysisActor();
    syncWaterAnalysisControls();
    syncWaterActorVisibility();
  }
}

async function readWaterFrameForAnalysis(frameIndex) {
  const cached = state.frameCache.get(frameIndex);
  if (cached?.compact && cached.water) return cached.water;
  return readCompactLayerFrame(state.caseInfo, 'water', frameIndex);
}

async function ensureWaterAnalysisHistory(targetFrameIndex, container) {
  const template = state.compact.templates.water;
  const threshold = Number(state.mThresholds.waterMax);
  if (!state.analysis.history || state.analysis.historyThreshold !== threshold || targetFrameIndex < state.analysis.historyThrough) {
    const pointCount = template.pointValues.length / 3;
    state.analysis.history = {
      inundationDepth: emptyMaximumArray(pointCount),
      inundationZ: emptyMaximumArray(pointCount),
      velocitySpeed: emptyMaximumArray(pointCount),
      velocityZ: emptyMaximumArray(pointCount),
    };
    state.analysis.historyThreshold = threshold;
    state.analysis.historyThrough = -1;
  }

  const token = ++state.analysis.historyLoadToken;
  const history = state.analysis.history;
  const seaLevel = getSeaLevel();
  const dryTolerance = getWaterDryTolerance();

  for (let frameIndex = state.analysis.historyThrough + 1; frameIndex <= targetFrameIndex; frameIndex += 1) {
    if (token !== state.analysis.historyLoadToken) return false;
    if (frameIndex === 0 || frameIndex === targetFrameIndex || frameIndex % 8 === 0) {
      setStatus(container, `Accumulating water analysis through frame ${frameIndex + 1}/${targetFrameIndex + 1}...`);
    }
    const frame = await readWaterFrameForAnalysis(frameIndex);
    const waterPoints = compactPointMaskFromCellPredicate(template, getWaterCellPredicate(frame));
    const inundatedPoints = compactPointMaskFromCellPredicate(
      template,
      getWaterCellPredicate(frame, (pointId) => {
        const h = Number(frame.h[pointId]);
        const z = Number(frame.z[pointId]);
        return Number.isFinite(h) && Number.isFinite(z) && h > dryTolerance && z - h >= seaLevel;
      })
    );

    for (let pointId = 0; pointId < waterPoints.length; pointId += 1) {
      if (waterPoints[pointId]) {
        const speed = Math.hypot(Number(frame.u[pointId]), Number(frame.v[pointId]));
        if (Number.isFinite(speed) && (!Number.isFinite(history.velocitySpeed[pointId]) || speed > history.velocitySpeed[pointId])) {
          history.velocitySpeed[pointId] = speed;
          history.velocityZ[pointId] = frame.z[pointId];
        }
      }
      if (inundatedPoints[pointId]) {
        const depth = Number(frame.h[pointId]);
        if (!Number.isFinite(history.inundationDepth[pointId]) || depth > history.inundationDepth[pointId]) {
          history.inundationDepth[pointId] = depth;
          history.inundationZ[pointId] = frame.z[pointId];
        }
      }
    }
    state.analysis.historyThrough = frameIndex;
  }
  return token === state.analysis.historyLoadToken;
}

function removeWaterAnalysisActor() {
  if (state.actors.waterAnalysis) {
    state.renderer?.removeActor(state.actors.waterAnalysis);
  }
  state.actors.waterAnalysis = null;
  state.scalarInfo.waterAnalysis = null;
}

function syncWaterAnalysisControls() {
  const mode = state.analysis.mode;
  const inundationToggle = document.getElementById('toggle-inundation');
  const velocityToggle = document.getElementById('toggle-velocity');
  const maxInundation = document.getElementById('show-max-inundation');
  const maxVelocity = document.getElementById('show-max-velocity');
  if (inundationToggle) inundationToggle.checked = mode === 'inundation';
  if (velocityToggle) velocityToggle.checked = mode === 'velocity';
  maxInundation?.setAttribute('aria-pressed', String(mode === 'maximumInundation'));
  maxVelocity?.setAttribute('aria-pressed', String(mode === 'maximumVelocity'));
}

function syncWaterActorVisibility() {
  const checked = Boolean(document.getElementById('toggle-water')?.checked ?? true);
  state.actors.water?.setVisibility(checked && !state.analysis.mode);
  state.actors.waterAnalysis?.setVisibility(checked && Boolean(state.analysis.mode));
}

function renderWaterAnalysisOverlay() {
  removeWaterAnalysisActor();
  const mode = state.analysis.mode;
  if (!mode) {
    syncWaterActorVisibility();
    updateWaterColorbar();
    state.renderWindow?.render();
    return;
  }

  let polyData;
  let scalarName;
  let colorStops;
  let fixedRange;
  let lineWidth = null;
  let opacity = ANALYSIS_SURFACE_OPACITY;
  if (mode === 'inundation') {
    polyData = createCurrentInundationDataset();
    scalarName = 'inundation_depth';
    fixedRange = getWaterOverlayRange('inundation');
    colorStops = getInundationColorStops(fixedRange);
  } else if (mode === 'maximumInundation') {
    polyData = createMaximumInundationDataset();
    scalarName = 'maximum_inundation_depth';
    fixedRange = getWaterOverlayRange('inundation');
    colorStops = getInundationColorStops(fixedRange);
  } else if (mode === 'velocity') {
    polyData = createVelocityArrowDataset();
    scalarName = 'wave_velocity';
    fixedRange = getWaterOverlayRange('velocity');
    colorStops = TURBO_COLOR_STOPS;
    lineWidth = 2.0;
  } else {
    polyData = createMaximumVelocityDataset();
    scalarName = 'maximum_wave_velocity';
    fixedRange = positivePercentileRange(
      state.analysis.history?.velocitySpeed,
      MAXIMUM_VELOCITY_DISPLAY_PERCENTILE
    ) ?? getWaterOverlayRange('velocity');
    colorStops = CMOCEAN_SPEED_COLOR_STOPS;
    opacity = 1.0;
  }

  const { actor, scalarInfo } = createScalarActor(
    polyData,
    [scalarName],
    colorStops,
    [0.18, 0.62, 0.86],
    opacity,
    { fixedRange }
  );
  setActorRenderLift(actor, WATER_ANALYSIS_RENDER_LIFT);
  if (lineWidth !== null) actor.getProperty().setLineWidth?.(lineWidth);
  state.actors.waterAnalysis = actor;
  state.scalarInfo.waterAnalysis = scalarInfo;
  state.renderer?.addActor(actor);
  syncWaterActorVisibility();
  updateWaterColorbar();
  state.renderer?.resetCameraClippingRange();
  state.renderWindow?.render();
}

async function activateWaterAnalysisMode(mode, container) {
  if (mode && !waterAnalysisIsAvailable()) {
    setStatus(container, 'Water analysis fields are unavailable. Re-export compact assets with h / u / v arrays.', true);
    return;
  }
  stopPlayback();
  if (mode === 'maximumInundation' || mode === 'maximumVelocity') {
    const ready = await ensureWaterAnalysisHistory(state.currentFrameIndex, container);
    if (!ready) return;
  }
  state.analysis.mode = mode;
  syncWaterAnalysisControls();
  renderWaterAnalysisOverlay();
  const label = {
    inundation: 'current-frame inundation depth',
    maximumInundation: `maximum inundation depth through frame ${state.currentFrameIndex + 1}`,
    velocity: 'current-frame velocity arrows',
    maximumVelocity: `maximum wave velocity through frame ${state.currentFrameIndex + 1}`,
  }[mode];
  setStatus(container, label ? `Showing ${label}.` : `Showing water surface for ${getFrameLabel(state.caseInfo, state.currentFrameIndex)}.`);
}

function refreshCurrentWaterAnalysisOverlay() {
  if (state.analysis.mode === 'inundation' || state.analysis.mode === 'velocity') {
    renderWaterAnalysisOverlay();
  }
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

const TURBO_COLOR_STOPS = [
  [0.000, 0.190, 0.072, 0.232],
  [0.125, 0.276, 0.421, 0.891],
  [0.250, 0.158, 0.736, 0.923],
  [0.375, 0.197, 0.949, 0.595],
  [0.500, 0.644, 0.990, 0.234],
  [0.625, 0.933, 0.812, 0.227],
  [0.750, 0.984, 0.493, 0.128],
  [0.875, 0.816, 0.185, 0.018],
  [1.000, 0.480, 0.016, 0.011],
];

const CMOCEAN_SPEED_COLOR_STOPS = [
  [0.000, 1.000, 0.991, 0.804],
  [0.100, 0.933, 0.876, 0.595],
  [0.200, 0.849, 0.772, 0.374],
  [0.300, 0.723, 0.697, 0.183],
  [0.400, 0.556, 0.634, 0.043],
  [0.500, 0.373, 0.571, 0.048],
  [0.600, 0.198, 0.503, 0.121],
  [0.700, 0.058, 0.418, 0.168],
  [0.800, 0.063, 0.328, 0.173],
  [0.900, 0.097, 0.230, 0.139],
  [1.000, 0.091, 0.137, 0.073],
];

const INUNDATION_CLASS_COLORS = [
  [0.749, 0.937, 0.949],
  [0.843, 0.498, 0.827],
  [0.357, 0.384, 0.839],
  [0.271, 0.780, 0.831],
  [0.306, 0.812, 0.353],
  [0.941, 0.863, 0.310],
  [0.953, 0.604, 0.267],
  [0.659, 0.286, 0.286],
];

const WATER_COLOR_STOPS = TSUNAMI_COLOR_STOPS;
const WATER_DISPLAY_RANGE_FRACTION = 1.0 / 10.0;
const WATER_SYMLOG_LINTHRESH_FRACTION = 1.0 / 100.0;
const WATER_SURFACE_OPACITY = 1.0;
const ANALYSIS_SURFACE_OPACITY = 0.94;
const ANALYSIS_SURFACE_LIFT = 0.04;
const VELOCITY_ARROW_STRIDE = 1;
const VELOCITY_ARROW_SCALE = 10.0;
const VELOCITY_ARROW_MAX_COUNT = 20000;
const VELOCITY_ARROW_MIN_SPEED = 0.01;
const MAXIMUM_VELOCITY_DISPLAY_PERCENTILE = 99.5;
const WATER_GLOBAL_STATS_PERCENTILE_FALLBACK = 99.9;
const WATER_GLOBAL_STATS_BINS = 4096;
const MAP_TILE_SIZE = 256;
const MAP_MAX_TILE_COUNT = 384;
const MAP_MIN_ZOOM = 7;
const MAP_MAX_ZOOM = 19;
const MAP_TILE_CONCURRENCY = 8;
const MAP_OVERLAY_LIFT = 0.60;
const MAP_TEXTURE_INTERPOLATE = false;
const WATER_RENDER_LIFT = 0.90;
const WATER_ANALYSIS_RENDER_LIFT = 1.00;
const LANDSLIDE_RENDER_LIFT = 5.00;
const LANDSLIDE_COLOR_STOPS = {
  hm: MAGMA_COLOR_STOPS,
  m: MAGMA_COLOR_STOPS,
  db: MAGMA_COLOR_STOPS,
};

const MAP_TILE_PROVIDERS = {
  esri_world_imagery_labels: {
    label: 'Esri World Imagery + Labels',
    layers: [
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    ],
    minZoom: 0,
    maxZoom: 19,
    attribution: 'Imagery and labels © Esri',
  },
  opentopomap: {
    label: 'OpenStreetMap Topographic (OpenTopoMap)',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    subdomains: ['a', 'b', 'c'],
    minZoom: 0,
    maxZoom: 17,
    attribution: 'Map data © OpenStreetMap contributors; style © OpenTopoMap (CC-BY-SA)',
  },
  esri_world_street: {
    label: 'Esri World Street Map',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
    minZoom: 0,
    maxZoom: 19,
    attribution: 'Tiles © Esri',
  },
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

function symlogLinThreshold(range) {
  const clean = finitePairRange(range);
  if (!clean) return 1e-12;
  const limit = Math.max(Math.abs(clean[0]), Math.abs(clean[1]), 1e-12);
  return Math.max(limit * WATER_SYMLOG_LINTHRESH_FRACTION, 1e-12);
}

function symlogTransform(value, linthresh) {
  const magnitude = Math.log1p(Math.abs(value) / linthresh);
  return Math.sign(value) * magnitude;
}

function symlogInverse(transformed, linthresh) {
  const magnitude = linthresh * Math.expm1(Math.abs(transformed));
  return Math.sign(transformed) * magnitude;
}

function createValueNormalizer(range, normalization = 'linear') {
  const [vmin, vmax] = range;
  if (normalization !== 'symlog') {
    return {
      normalize: (value) => (value - vmin) / (vmax - vmin),
      denormalize: (position) => vmin + position * (vmax - vmin),
    };
  }

  const linthresh = symlogLinThreshold(range);
  const tmin = symlogTransform(vmin, linthresh);
  const tmax = symlogTransform(vmax, linthresh);
  const span = Math.max(tmax - tmin, 1e-12);

  return {
    normalize: (value) => clamp01((symlogTransform(value, linthresh) - tmin) / span),
    denormalize: (position) => symlogInverse(tmin + clamp01(position) * span, linthresh),
  };
}

function createTransferFunction(range, stops, normalization = 'linear') {
  const ctf = vtkColorTransferFunction.newInstance();
  const [vmin, vmax] = range;
  const normalizer = createValueNormalizer(range, normalization);

  for (const [position, red, green, blue] of stops) {
    const value = normalizer.denormalize(position);
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

function getTerrainProjectionLabel() {
  const crs = state.caseInfo?.processing?.crs;
  const epsg = Number(crs?.epsg);
  if (Number.isFinite(epsg)) return `EPSG:${epsg}`;
  if (crs?.name) return String(crs.name);
  return null;
}

function updateTerrainLegendReadout() {
  const projection = getTerrainProjectionLabel();
  setLegendReadout(
    'terrain-scalar-readout',
    projection ? `projection ${projection}` : 'projection unavailable'
  );
}

function updateWaterLegendReadout(container = null) {
  const threshold = getCurrentWaterMThreshold();
  const manifestRange = getManifestWaterGlobalRangeForThreshold(threshold);
  if (
    manifestRange
    && !state.waterGlobalStats.isComputing
    && !thresholdsMatch(state.waterGlobalStats.threshold, threshold)
  ) {
    state.waterGlobalStats.threshold = threshold;
    state.waterGlobalStats.rawRange = manifestRange;
    state.waterGlobalStats.range = getManifestWaterDisplayRangeForThreshold(threshold);
  }

  const globalRange = getWaterGlobalRange();
  const shouldCompute =
    state.compact.enabled
    && container
    && !manifestRange
    && !state.waterGlobalStats.isComputing
    && !(
      thresholdsMatch(state.waterGlobalStats.threshold, threshold)
      && finitePairRange(state.waterGlobalStats.rawRange)
    );

  setLegendReadout(
    'water-scalar-readout',
    shouldCompute
      ? `global computing for m≤${threshold}`
      : state.waterGlobalStats.isComputing && thresholdsMatch(state.waterGlobalStats.threshold, threshold)
      ? `global computing for m≤${threshold}`
      : globalRange
        ? `global ${formatRange(globalRange)}`
        : 'global unavailable'
  );

  if (shouldCompute) {
    computeWaterGlobalRangeForThreshold(threshold, container).catch((error) => {
      console.warn('[MANTA Gallery] failed to compute water global statistics:', error);
      if (thresholdsMatch(state.waterGlobalStats.threshold, threshold)) {
        state.waterGlobalStats.isComputing = false;
        setLegendReadout('water-scalar-readout', globalRange ? `global ${formatRange(globalRange)}` : 'global unavailable');
      }
    });
  }
}

function updateLandslideLegendReadout(scalarName) {
  const globalRange = getLandslideGlobalRange(scalarName);
  setLegendReadout(
    'landslide-scalar-readout',
    globalRange ? `${scalarName} global ${formatRange(globalRange)}` : `${scalarName} global unavailable`
  );
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

function formatColorbarTick(value) {
  const absValue = Math.abs(value);
  if (absValue > 0 && absValue < 1e-2) return value.toExponential(1);
  if (Number.isInteger(value)) return String(value);
  return String(Number(value.toFixed(absValue < 10.0 ? 1 : 2)));
}

function renderColorbarTicks(container, ticks, range, classified = false) {
  if (!container) return;
  container.replaceChildren();
  container.classList.toggle('manta-colorbar-ticks-classified', classified);
  const [vmin, vmax] = range;
  for (const item of ticks) {
    const value = typeof item === 'number' ? item : Number(item.value);
    const tick = document.createElement('span');
    tick.textContent = classified ? formatColorbarTick(value) : formatScalar(value);
    if (classified) {
      tick.className = 'manta-colorbar-tick-classified';
      const position = typeof item === 'number'
        ? (value - vmin) / (vmax - vmin)
        : Number(item.position);
      tick.style.left = `${100.0 * position}%`;
    }
    container.appendChild(tick);
  }
}

function createSymlogTicks(range) {
  const clean = finitePairRange(range);
  if (!clean) return null;

  const [vmin, vmax] = clean;
  const normalizer = createValueNormalizer(clean, 'symlog');
  const linthresh = symlogLinThreshold(clean);
  const limit = Math.max(Math.abs(vmin), Math.abs(vmax));
  const tickValues = [vmin, -10.0 * linthresh, -linthresh, 0.0, linthresh, 10.0 * linthresh, vmax]
    .filter((value) => value >= vmin && value <= vmax);
  const uniqueTickValues = [];

  for (const value of tickValues) {
    if (!uniqueTickValues.some((existing) => Math.abs(existing - value) <= 1e-9 * Math.max(1.0, limit))) {
      uniqueTickValues.push(value);
    }
  }

  return uniqueTickValues.map((value) => ({
    value,
    position: normalizer.normalize(value),
  }));
}

function updateColorbar({
  idPrefix,
  title,
  scalarInfo,
  colorStops,
  showZeroTick = false,
  classifiedTicks = null,
  normalization = 'linear',
}) {
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
  const ticksEl = document.getElementById(`${idPrefix}-colorbar-ticks`);

  if (titleEl) titleEl.textContent = title;
  if (rangeEl) rangeEl.textContent = formatRange(scalarInfo.range);
  if (stripEl) stripEl.style.background = stopsToCssGradient(colorStops);
  const ticks = classifiedTicks
    ?? (normalization === 'symlog' ? createSymlogTicks(scalarInfo.range) : null)
    ?? [vmin, midValue, vmax];
  renderColorbarTicks(
    ticksEl,
    ticks,
    scalarInfo.range,
    Boolean(classifiedTicks) || normalization === 'symlog'
  );
}

function updateWaterColorbar() {
  const mode = state.analysis.mode;
  if (mode) {
    const title = {
      inundation: 'Inundation depth relative to sea level (m)',
      maximumInundation: 'Maximum inundation depth (m)',
      velocity: 'Wave velocity arrows (m/s)',
      maximumVelocity: 'Maximum wave velocity (m/s)',
    }[mode];
    const inundationSpec = getInundationColorSpec();
    const colorStops = mode === 'velocity'
      ? TURBO_COLOR_STOPS
      : mode === 'maximumVelocity'
        ? CMOCEAN_SPEED_COLOR_STOPS
        : inundationSpec.legendStops;
    updateColorbar({
      idPrefix: 'water',
      title,
      scalarInfo: state.scalarInfo.waterAnalysis,
      colorStops,
      classifiedTicks: mode === 'inundation' || mode === 'maximumInundation'
        ? inundationSpec.legendTicks
        : null,
    });
    const analysisRange = state.scalarInfo.waterAnalysis?.rawRange;
    const rangeEl = document.getElementById('water-colorbar-range');
    if (rangeEl) rangeEl.textContent = analysisRange ? `current ${formatRange(analysisRange)}` : '';
    return;
  }

  updateColorbar({
    idPrefix: 'water',
    title: 'Wave height (m)',
    scalarInfo: state.scalarInfo.water,
    colorStops: WATER_COLOR_STOPS,
    showZeroTick: true,
    normalization: 'symlog',
  });

  const actualRange = getCurrentVisibleWaveRange();
  const rangeEl = document.getElementById('water-colorbar-range');
  if (rangeEl) rangeEl.textContent = actualRange ? `current ${formatRange(actualRange)}` : '';
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
  normalization = 'linear',
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

  const lookupTable = createTransferFunction(range, colorStops, normalization);

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
    normalization,
  };
}

function applyGlobalLighting(property, options = {}) {
  const ambient = Number.isFinite(options.ambient) ? options.ambient : 0.58;
  const diffuse = Number.isFinite(options.diffuse) ? options.diffuse : 0.52;
  const specular = Number.isFinite(options.specular) ? options.specular : 0.04;
  property.setAmbient?.(ambient);
  property.setDiffuse?.(diffuse);
  property.setSpecular?.(specular);
  property.setSpecularPower?.(8.0);
}

function setActorRenderLift(actor, lift) {
  actor?.setPosition?.(0.0, 0.0, lift);
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
  applyGlobalLighting(property);

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

function getMapCrsConfig() {
  const crs = state.caseInfo?.processing?.crs ?? {};
  const code = Number(crs.epsg ?? crs.code ?? 32637);
  const zoneFromCode = code >= 32601 && code <= 32660
    ? code - 32600
    : code >= 32701 && code <= 32760
      ? code - 32700
      : null;
  const zone = Number(crs.utm_zone ?? crs.zone ?? zoneFromCode ?? 37);
  const northern = code >= 32701 && code <= 32760
    ? false
    : String(crs.hemisphere ?? 'N').toUpperCase() !== 'S';
  if (!Number.isFinite(zone) || zone < 1 || zone > 60) {
    throw new Error('Map overlay requires a UTM CRS zone in the case manifest.');
  }
  return { code, zone, northern };
}

function utmToLonLat(easting, northing, crsConfig = getMapCrsConfig()) {
  const a = 6378137.0;
  const eccSquared = 0.0066943799901413165;
  const k0 = 0.9996;
  const eccPrimeSquared = eccSquared / (1.0 - eccSquared);
  const e1 = (1.0 - Math.sqrt(1.0 - eccSquared)) / (1.0 + Math.sqrt(1.0 - eccSquared));

  const x = Number(easting) - 500000.0;
  let y = Number(northing);
  if (!crsConfig.northern) y -= 10000000.0;

  const longOrigin = (crsConfig.zone - 1.0) * 6.0 - 180.0 + 3.0;
  const m = y / k0;
  const mu = m / (a * (1.0 - eccSquared / 4.0 - 3.0 * eccSquared ** 2 / 64.0 - 5.0 * eccSquared ** 3 / 256.0));

  const phi1Rad = mu
    + (3.0 * e1 / 2.0 - 27.0 * e1 ** 3 / 32.0) * Math.sin(2.0 * mu)
    + (21.0 * e1 ** 2 / 16.0 - 55.0 * e1 ** 4 / 32.0) * Math.sin(4.0 * mu)
    + (151.0 * e1 ** 3 / 96.0) * Math.sin(6.0 * mu)
    + (1097.0 * e1 ** 4 / 512.0) * Math.sin(8.0 * mu);

  const sinPhi1 = Math.sin(phi1Rad);
  const cosPhi1 = Math.cos(phi1Rad);
  const tanPhi1 = Math.tan(phi1Rad);
  const n1 = a / Math.sqrt(1.0 - eccSquared * sinPhi1 ** 2);
  const t1 = tanPhi1 ** 2;
  const c1 = eccPrimeSquared * cosPhi1 ** 2;
  const r1 = a * (1.0 - eccSquared) / (1.0 - eccSquared * sinPhi1 ** 2) ** 1.5;
  const d = x / (n1 * k0);

  const latRad = phi1Rad - (n1 * tanPhi1 / r1) * (
    d ** 2 / 2.0
    - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1 ** 2 - 9.0 * eccPrimeSquared) * d ** 4 / 24.0
    + (61.0 + 90.0 * t1 + 298.0 * c1 + 45.0 * t1 ** 2 - 252.0 * eccPrimeSquared - 3.0 * c1 ** 2) * d ** 6 / 720.0
  );
  const lonRad = (
    d
    - (1.0 + 2.0 * t1 + c1) * d ** 3 / 6.0
    + (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1 ** 2 + 8.0 * eccPrimeSquared + 24.0 * t1 ** 2) * d ** 5 / 120.0
  ) / cosPhi1;

  return {
    lon: longOrigin + lonRad * 180.0 / Math.PI,
    lat: latRad * 180.0 / Math.PI,
  };
}

function lonLatToTilePixel(lon, lat, zoom) {
  const clampedLat = Math.min(85.05112878, Math.max(-85.05112878, Number(lat)));
  const scale = MAP_TILE_SIZE * 2 ** zoom;
  const sinLat = Math.sin(clampedLat * Math.PI / 180.0);
  return {
    x: ((Number(lon) + 180.0) / 360.0) * scale,
    y: (0.5 - Math.log((1.0 + sinLat) / (1.0 - sinLat)) / (4.0 * Math.PI)) * scale,
  };
}

function getPolyDataBounds2d(polyData) {
  const values = polyData?.getPoints?.()?.getData?.();
  if (!values) return null;
  let xmin = Number.POSITIVE_INFINITY;
  let xmax = Number.NEGATIVE_INFINITY;
  let ymin = Number.POSITIVE_INFINITY;
  let ymax = Number.NEGATIVE_INFINITY;
  for (let i = 0; i < values.length; i += 3) {
    const x = Number(values[i]);
    const y = Number(values[i + 1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    xmin = Math.min(xmin, x);
    xmax = Math.max(xmax, x);
    ymin = Math.min(ymin, y);
    ymax = Math.max(ymax, y);
  }
  return Number.isFinite(xmin) ? { xmin, xmax, ymin, ymax } : null;
}

function terrainLonLatBbox(polyData) {
  const bounds = getPolyDataBounds2d(polyData);
  if (!bounds) return null;
  const crs = getMapCrsConfig();
  const corners = [
    utmToLonLat(bounds.xmin, bounds.ymin, crs),
    utmToLonLat(bounds.xmax, bounds.ymin, crs),
    utmToLonLat(bounds.xmax, bounds.ymax, crs),
    utmToLonLat(bounds.xmin, bounds.ymax, crs),
  ];
  return {
    west: Math.min(...corners.map((p) => p.lon)),
    east: Math.max(...corners.map((p) => p.lon)),
    south: Math.min(...corners.map((p) => p.lat)),
    north: Math.max(...corners.map((p) => p.lat)),
  };
}

function tileBoundsForBbox(bbox, zoom) {
  const nw = lonLatToTilePixel(bbox.west, bbox.north, zoom);
  const se = lonLatToTilePixel(bbox.east, bbox.south, zoom);
  const n = 2 ** zoom;
  return {
    minX: Math.min(n - 1, Math.max(0, Math.floor(Math.min(nw.x, se.x) / MAP_TILE_SIZE))),
    maxX: Math.min(n - 1, Math.max(0, Math.floor(Math.max(nw.x, se.x) / MAP_TILE_SIZE))),
    minY: Math.min(n - 1, Math.max(0, Math.floor(Math.min(nw.y, se.y) / MAP_TILE_SIZE))),
    maxY: Math.min(n - 1, Math.max(0, Math.floor(Math.max(nw.y, se.y) / MAP_TILE_SIZE))),
  };
}

function tileCountForBounds(bounds) {
  return Math.max(0, bounds.maxX - bounds.minX + 1) * Math.max(0, bounds.maxY - bounds.minY + 1);
}

function finiteInteger(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number) : fallback;
}

function getProviderMinZoom(provider) {
  return Math.max(0, finiteInteger(provider?.minZoom, MAP_MIN_ZOOM));
}

function getProviderMaxZoom(provider) {
  const providerMax = finiteInteger(provider?.maxZoom, MAP_MAX_ZOOM);
  return Math.max(getProviderMinZoom(provider), Math.min(MAP_MAX_ZOOM, providerMax));
}

function getProviderMaxTileCount(provider) {
  return Math.max(1, finiteInteger(provider?.maxTileCount, MAP_MAX_TILE_COUNT));
}

function chooseMapZoom(bbox, provider = null) {
  const minZoom = getProviderMinZoom(provider);
  const maxZoom = getProviderMaxZoom(provider);
  const maxTileCount = getProviderMaxTileCount(provider);
  let bestZoom = minZoom;
  for (let zoom = minZoom; zoom <= maxZoom; zoom += 1) {
    if (tileCountForBounds(tileBoundsForBbox(bbox, zoom)) <= maxTileCount) {
      bestZoom = zoom;
    }
  }
  return bestZoom;
}

function formatMapTileUrl(provider, z, x, y, template = provider.url) {
  if (!template) {
    throw new Error(`Map provider ${provider.label ?? 'unknown'} does not use URL templates.`);
  }
  const subdomains = provider.subdomains ?? [''];
  const s = subdomains[Math.abs(x + y) % subdomains.length];
  return template
    .replace('{s}', s)
    .replace('{z}', String(z))
    .replace('{x}', String(x))
    .replace('{y}', String(y));
}

function loadTileImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.decoding = 'async';
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Failed to load map tile: ${url}`));
    image.src = url;
  });
}

async function runWithConcurrency(items, limit, worker) {
  let nextIndex = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      await worker(items[index], index);
    }
  });
  await Promise.all(workers);
}

async function buildMapMosaicForProvider(providerId, bbox, zoom) {
  const provider = MAP_TILE_PROVIDERS[providerId];
  if (!provider) throw new Error(`Unknown map provider: ${providerId}`);
  const layerTemplates = provider.layers ?? (provider.url ? [provider.url] : []);
  if (layerTemplates.length === 0) throw new Error(`Map provider ${provider.label ?? providerId} has no tile URL templates.`);
  const bounds = tileBoundsForBbox(bbox, zoom);
  const tileColumns = bounds.maxX - bounds.minX + 1;
  const tileRows = bounds.maxY - bounds.minY + 1;
  const tileWidth = MAP_TILE_SIZE;
  const tileHeight = MAP_TILE_SIZE;
  const canvas = document.createElement('canvas');
  canvas.width = tileColumns * tileWidth;
  canvas.height = tileRows * tileHeight;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Canvas 2D context is unavailable for map overlay.');

  const jobs = [];
  for (let ty = bounds.minY; ty <= bounds.maxY; ty += 1) {
    for (let tx = bounds.minX; tx <= bounds.maxX; tx += 1) {
      jobs.push({
        tx,
        ty,
        urls: layerTemplates.map((template) => formatMapTileUrl(provider, zoom, tx, ty, template)),
      });
    }
  }

  await runWithConcurrency(jobs, MAP_TILE_CONCURRENCY, async (job) => {
    for (const url of job.urls) {
      const image = await loadTileImage(url);
      ctx.drawImage(
        image,
        (job.tx - bounds.minX) * tileWidth,
        (job.ty - bounds.minY) * tileHeight,
        tileWidth,
        tileHeight
      );
    }
  });

  ctx.getImageData(0, 0, 1, 1);
  return {
    provider,
    bounds,
    zoom,
    tileWidth,
    tileHeight,
    width: canvas.width,
    height: canvas.height,
    canvas,
  };
}

async function buildMapMosaic(bbox, zoom) {
  const preferred = state.mapOverlay.providerId;
  const providerIds = [preferred, 'esri_world_imagery_labels', 'opentopomap', 'esri_world_street']
    .filter((value, index, values) => value && values.indexOf(value) === index);
  let lastError = null;
  for (const providerId of providerIds) {
    try {
      return await buildMapMosaicForProvider(providerId, bbox, zoom);
    } catch (error) {
      lastError = error;
      console.warn(`[MANTA Gallery] map provider failed (${providerId}):`, error);
    }
  }
  throw lastError ?? new Error('No map provider could be loaded.');
}

function clamp01(value) {
  return Math.min(1.0, Math.max(0.0, value));
}

function mapTextureCoordinate(mosaic, lon, lat) {
  const pixel = lonLatToTilePixel(lon, lat, mosaic.zoom);
  const tileWidth = Number(mosaic.tileWidth) || MAP_TILE_SIZE;
  const tileHeight = Number(mosaic.tileHeight) || MAP_TILE_SIZE;
  const px = (pixel.x - mosaic.bounds.minX * MAP_TILE_SIZE) * (tileWidth / MAP_TILE_SIZE);
  const py = (pixel.y - mosaic.bounds.minY * MAP_TILE_SIZE) * (tileHeight / MAP_TILE_SIZE);
  const u = clamp01(px / Math.max(1, mosaic.width - 1));
  const v = clamp01(1.0 - py / Math.max(1, mosaic.height - 1));
  return [u, v];
}

function createMapActorFromTerrain(terrain, mosaic) {
  const sourcePoints = terrain?.getPoints?.()?.getData?.();
  const sourcePolys = terrain?.getPolys?.()?.getData?.();
  if (!sourcePoints || !sourcePolys) {
    throw new Error('Terrain geometry is unavailable for map overlay.');
  }

  const pointValues = new Float32Array(sourcePoints);
  for (let i = 2; i < pointValues.length; i += 3) pointValues[i] += MAP_OVERLAY_LIFT;
  const crs = getMapCrsConfig();
  const pointCount = Math.floor(sourcePoints.length / 3);
  const tcoordValues = new Float32Array(pointCount * 2);
  for (let pointId = 0; pointId < pointCount; pointId += 1) {
    const sourceBase = pointId * 3;
    const targetBase = pointId * 2;
    const { lon, lat } = utmToLonLat(sourcePoints[sourceBase], sourcePoints[sourceBase + 1], crs);
    const [u, v] = mapTextureCoordinate(mosaic, lon, lat);
    tcoordValues[targetBase] = u;
    tcoordValues[targetBase + 1] = v;
  }

  const points = vtkPoints.newInstance();
  points.setData(pointValues, 3);
  const polys = vtkCellArray.newInstance();
  polys.setData(sourcePolys);

  const polyData = vtkPolyData.newInstance();
  polyData.setPoints(points);
  polyData.setPolys(polys);
  const tcoordArray = vtkDataArray.newInstance({
    name: 'basemap_tcoords',
    numberOfComponents: 2,
    values: tcoordValues,
  });
  polyData.getPointData().setTCoords?.(tcoordArray);

  const mapper = vtkMapper.newInstance();
  mapper.setInputData(polyData);
  mapper.setScalarVisibility(false);

  const texture = vtkTexture.newInstance({
    interpolate: MAP_TEXTURE_INTERPOLATE,
    edgeClamp: true,
  });
  texture.setCanvas(mosaic.canvas);

  const actor = vtkActor.newInstance();
  actor.setMapper(mapper);
  actor.addTexture(texture);
  const property = actor.getProperty();
  property.setColor(1.0, 1.0, 1.0);
  property.setOpacity(1.0);
  property.setLighting?.(false);
  applyGlobalLighting(property, { ambient: 0.96, diffuse: 0.08, specular: 0.0 });
  return actor;
}

async function buildMapOverlayActor(container) {
  const terrain = state.datasets.terrain;
  const pointValues = terrain?.getPoints?.()?.getData?.();
  if (!terrain || !pointValues) throw new Error('Terrain must be loaded before the map overlay.');
  const bbox = terrainLonLatBbox(terrain);
  if (!bbox) throw new Error('Could not determine terrain bounds for map overlay.');
  const provider = MAP_TILE_PROVIDERS[state.mapOverlay.providerId];
  const zoom = chooseMapZoom(bbox, provider);
  setStatus(container, `Loading ${provider?.label ?? 'online basemap'} tiles (zoom ${zoom})...`);
  const mosaic = await buildMapMosaic(bbox, zoom);
  state.mapOverlay.attribution = mosaic.provider.attribution;
  return createMapActorFromTerrain(terrain, mosaic);
}

function syncMapOverlayButton(container) {
  const button = container?.querySelector?.('#toggle-map');
  if (button) {
    button.disabled = state.mapOverlay.loading;
    button.setAttribute('aria-pressed', String(state.mapOverlay.enabled));
    button.textContent = state.mapOverlay.loading
      ? 'Map loading'
      : state.mapOverlay.enabled
        ? 'Map on'
        : 'Map';
  }
  const providerSelect = container?.querySelector?.('#map-provider');
  if (providerSelect) {
    providerSelect.disabled = state.mapOverlay.loading;
    providerSelect.value = state.mapOverlay.providerId;
  }
}

function removeMapOverlayActor() {
  if (state.actors.map) {
    state.renderer?.removeActor(state.actors.map);
  }
  state.actors.map = null;
  state.mapOverlay.attribution = '';
}

async function reloadMapOverlay(container) {
  removeMapOverlayActor();
  state.mapOverlay.enabled = true;
  syncMapOverlayButton(container);
  await toggleMapOverlay(container);
}

async function toggleMapOverlay(container) {
  const token = ++state.mapOverlay.token;
  if (state.mapOverlay.loading) return;

  if (state.actors.map) {
    state.mapOverlay.enabled = !state.mapOverlay.enabled;
    state.actors.map.setVisibility(state.mapOverlay.enabled);
    syncMapOverlayButton(container);
    state.renderWindow?.render();
    setStatus(
      container,
      state.mapOverlay.enabled
        ? `Showing terrain basemap (${state.mapOverlay.attribution || 'online tiles'}).`
        : `Hid terrain basemap.`
    );
    return;
  }

  state.mapOverlay.loading = true;
  state.mapOverlay.enabled = true;
  syncMapOverlayButton(container);
  try {
    const actor = await buildMapOverlayActor(container);
    if (token !== state.mapOverlay.token) return;
    state.actors.map = actor;
    state.actors.map.setVisibility(true);
    state.renderer?.addActor(actor);
    state.renderer?.resetCameraClippingRange();
    state.renderWindow?.render();
    setStatus(container, `Showing terrain basemap (${state.mapOverlay.attribution}).`);
  } catch (error) {
    console.error('[MANTA Gallery] failed to load map overlay:', error);
    state.mapOverlay.enabled = false;
    setStatus(container, 'Failed to load online basemap tiles. Check network access and browser CORS policy.', true);
  } finally {
    state.mapOverlay.loading = false;
    syncMapOverlayButton(container);
  }
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
  const previousWaterValue = state.mThresholds.waterMax;

  state.mThresholds.waterMax = waterValue;
  state.mThresholds.landslideMin = landslideValue;
  resetWaterAnalysisHistory();
  if (!thresholdsMatch(previousWaterValue, waterValue)) resetWaterGlobalStats();

  if (waterInput) waterInput.value = String(waterValue);
  if (landslideInput) landslideInput.value = String(landslideValue);

  applyMThresholdsToRawDatasets();
  updateWaterLegendReadout(container);
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
  updateLandslideLegendReadout(scalarName);
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

  const caseInfo = await fetchJson(state.caseJsonUrl);
  state.caseInfo = caseInfo;
  state.frameCount = getFrameCount(caseInfo);
  state.currentFrameIndex = getDefaultFrameIndex(caseInfo);
  state.compact.enabled = caseUsesCompactV2(caseInfo);

  const terrainPath = caseInfo.layers.terrain.file;
  const terrainUrl = caseUrl(terrainPath);

  console.log('[MANTA Gallery] case.json:', state.caseJsonUrl.href);
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
      normalization: 'symlog',
    }
  );
  const { actor: landslideActor, scalarInfo: landslideScalarInfo } = createScalarActor(
    landslide,
    ['hm'],
    LANDSLIDE_COLOR_STOPS.hm,
    [0.90, 0.32, 0.12],
    0.92
  );
  setActorRenderLift(waterActor, WATER_RENDER_LIFT);
  setActorRenderLift(landslideActor, LANDSLIDE_RENDER_LIFT);

  state.actors.terrain = terrainActor;
  state.actors.water = waterActor;
  state.actors.landslide = landslideActor;
  state.scalarInfo.water = waterScalarInfo;
  state.scalarInfo.landslide = landslideScalarInfo;

  state.renderer.addActor(terrainActor);
  state.renderer.addActor(waterActor);
  state.renderer.addActor(landslideActor);

  resetCamera();

  updateTerrainLegendReadout();
  updateWaterLegendReadout();
  updateLandslideLegendReadout('hm');

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
    normalization: 'symlog',
  });

  state.scalarInfo.water = waterScalarInfo;
  updateWaterColorbar();

  applyLandslideScalar(state.activeLandslideScalar);
  refreshCurrentWaterAnalysisOverlay();
  syncWaterActorVisibility();

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

  if (state.analysis.mode === 'maximumInundation' || state.analysis.mode === 'maximumVelocity') {
    state.analysis.mode = null;
    removeWaterAnalysisActor();
    syncWaterAnalysisControls();
    syncWaterActorVisibility();
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
      `Loaded ${getCaseDisplayTitle()} (${getFrameLabel(state.caseInfo, k)}). Drag to rotate, scroll to zoom.`
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

  const mapButton = container.querySelector('#toggle-map');
  if (mapButton) {
    syncMapOverlayButton(container);
    mapButton.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleMapOverlay(container).catch(console.error);
    });
  }
  const mapProviderSelect = container.querySelector('#map-provider');
  if (mapProviderSelect) {
    mapProviderSelect.value = state.mapOverlay.providerId;
    for (const eventName of ['pointerdown', 'mousedown', 'touchstart', 'wheel', 'dblclick']) {
      mapProviderSelect.addEventListener(eventName, (event) => {
        event.stopPropagation();
      }, { passive: true });
    }
    mapProviderSelect.addEventListener('change', (event) => {
      event.stopPropagation();
      const providerId = event.target.value;
      if (!MAP_TILE_PROVIDERS[providerId] || providerId === state.mapOverlay.providerId) return;
      state.mapOverlay.providerId = providerId;
      if (state.mapOverlay.enabled || state.actors.map) {
        reloadMapOverlay(container).catch(console.error);
      } else {
        syncMapOverlayButton(container);
      }
    });
  }
  syncMapOverlayButton(container);

  container.querySelector('#toggle-water')?.addEventListener('change', (event) => {
    syncWaterActorVisibility();
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

  const analysisAvailable = waterAnalysisIsAvailable();
  const inundationToggle = container.querySelector('#toggle-inundation');
  const velocityToggle = container.querySelector('#toggle-velocity');
  const maxInundationButton = container.querySelector('#show-max-inundation');
  const maxVelocityButton = container.querySelector('#show-max-velocity');
  for (const control of [inundationToggle, velocityToggle, maxInundationButton, maxVelocityButton]) {
    if (control) control.disabled = !analysisAvailable;
  }
  inundationToggle?.addEventListener('change', (event) => {
    activateWaterAnalysisMode(event.target.checked ? 'inundation' : null, container).catch(console.error);
  });
  velocityToggle?.addEventListener('change', (event) => {
    activateWaterAnalysisMode(event.target.checked ? 'velocity' : null, container).catch(console.error);
  });
  maxInundationButton?.addEventListener('click', () => {
    const nextMode = state.analysis.mode === 'maximumInundation' ? null : 'maximumInundation';
    activateWaterAnalysisMode(nextMode, container).catch(console.error);
  });
  maxVelocityButton?.addEventListener('click', () => {
    const nextMode = state.analysis.mode === 'maximumVelocity' ? null : 'maximumVelocity';
    activateWaterAnalysisMode(nextMode, container).catch(console.error);
  });
  syncWaterAnalysisControls();

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
      bottom: 132px;
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
      bottom: 132px;
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
  const container = document.querySelector('.manta-viewer[data-case-base-url]')
    ?? document.getElementById('aqaba-viewer')
    ?? document.querySelector('.manta-viewer');
  if (!container) {
    console.error('[MANTA Gallery] Missing viewer container: .manta-viewer');
    return;
  }

  configureCaseFromContainer(container);
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
      `Loaded ${getCaseDisplayTitle(caseInfo)} (${getFrameLabel(caseInfo, frameIndex)}). Drag to rotate, scroll to zoom.`
    );
  } catch (error) {
    console.error('[MANTA Gallery] viewer failed:', error);
    setStatus(container, 'Failed to load MANTA Gallery viewer. Check Console and Network tabs.', true);
  }
}

main();
