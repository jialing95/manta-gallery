import '@kitware/vtk.js/Rendering/Profiles/Geometry';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader';

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

      <label>
        Landslide color:
        <select id="landslide-scalar" disabled>
          <option value="hm" selected>hm</option>
          <option value="m">m</option>
          <option value="db">Δb</option>
        </select>
      </label>

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

function getWaterDisplayRange() {
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
const WATER_DISPLAY_RANGE_FRACTION = 1.0 / 6.0;
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
    const fullText = `full ${formatRange(statsRange)}`;
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

  const terrainPath = caseInfo.layers.terrain.file;
  const terrainUrl = caseUrl(terrainPath);

  console.log('[MANTA Gallery] case.json:', CASE_JSON_URL.href);
  console.log('[MANTA Gallery] terrain:', terrainUrl.href);

  setStatus(container, 'Loading terrain and default time frame...');

  const [terrain, frameData] = await Promise.all([
    readVtp(terrainUrl),
    readFrameData(state.currentFrameIndex),
  ]);

  state.datasets.terrain = terrain;
  state.datasets.water = frameData.water;
  state.datasets.landslide = frameData.landslide;

  prefetchNearbyFrames(state.currentFrameIndex);

  return {
    caseInfo,
    terrain,
    water: frameData.water,
    landslide: frameData.landslide,
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
    0.72,
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

    state.datasets.water = frameData.water;
    state.datasets.landslide = frameData.landslide;
    state.currentFrameIndex = k;

    updateCurrentFrameActors();
    updateFrameReadout();
    prefetchNearbyFrames(k);

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

  updateFrameReadout();
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
