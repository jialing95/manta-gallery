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
};

function injectCss() {
  if (document.getElementById('manta-aqaba-viewer-css')) return;

  const style = document.createElement('style');
  style.id = 'manta-aqaba-viewer-css';
  style.textContent = `
    .manta-viewer {
      position: relative;
      width: 100%;
      height: clamp(780px, 86vh, 1120px); min-height: 720px;
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
      max-width: min(760px, calc(100% - 24px));
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

const LANDSLIDE_COLOR_STOPS = {
  hm: MAGMA_COLOR_STOPS,
  m: MAGMA_COLOR_STOPS,
  db: MAGMA_COLOR_STOPS,
};

const LANDSLIDE_SCALAR_LABELS = {
  hm: 'hm',
  m: 'm',
  db: 'Δb',
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

function resolveDisplayRange({ arrayName, dataArray, rawRange, rangeMode = 'auto', robustPercentile = 99.0 }) {
  if (!rawRange) return null;

  if (rangeMode === 'robust-symmetric') {
    return computeRobustSymmetricRange(dataArray, robustPercentile) ?? zeroCenteredRangeIfNeeded(arrayName, rawRange);
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
  updateColorbar({
    idPrefix: 'water',
    title: 'Tsunami / wave amplitude',
    scalarInfo: state.scalarInfo.water,
    colorStops: WATER_COLOR_STOPS,
    showZeroTick: true,
  });
}

function updateLandslideColorbar(scalarName = 'hm') {
  const colorStops = LANDSLIDE_COLOR_STOPS[scalarName] ?? MAGMA_COLOR_STOPS;
  const label = LANDSLIDE_SCALAR_LABELS[scalarName] ?? scalarName;
  updateColorbar({
    idPrefix: 'landslide',
    title: `Landslide / ${label}`,
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
}) {
  if (!actor || !polyData) return null;

  const mapper = actor.getMapper();
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

async function loadCaseAndData(container) {
  setStatus(container, 'Loading case.json...');

  const caseInfo = await fetchJson(CASE_JSON_URL);
  state.caseInfo = caseInfo;

  const terrainPath = caseInfo.layers.terrain.file;
  const waterPath = framePathFromPattern(caseInfo.layers.water.file_pattern, 0);
  const landslidePath = framePathFromPattern(caseInfo.layers.landslide.file_pattern, 0);

  const terrainUrl = caseUrl(terrainPath);
  const waterUrl = caseUrl(waterPath);
  const landslideUrl = caseUrl(landslidePath);

  console.log('[MANTA Gallery] case.json:', CASE_JSON_URL.href);
  console.log('[MANTA Gallery] terrain:', terrainUrl.href);
  console.log('[MANTA Gallery] water:', waterUrl.href);
  console.log('[MANTA Gallery] landslide:', landslideUrl.href);

  setStatus(container, 'Loading VTP surfaces...');

  const [terrain, water, landslide] = await Promise.all([
    readVtp(terrainUrl),
    readVtp(waterUrl),
    readVtp(landslideUrl),
  ]);

  state.datasets.terrain = terrain;
  state.datasets.water = water;
  state.datasets.landslide = landslide;

  return { caseInfo, terrain, water, landslide };
}

function addActors(terrain, water, landslide) {
  const terrainActor = createSolidActor(terrain, [0.58, 0.58, 0.58], 1.0);
  const { actor: waterActor, scalarInfo: waterScalarInfo } = createScalarActor(
    water,
    ['wave_amplitude'],
    WATER_COLOR_STOPS,
    [0.10, 0.36, 0.85],
    0.72,
    { rangeMode: 'robust-symmetric', robustPercentile: 99.0 }
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

      applyLandslideScalar(landslideScalarSelect.value);
    }

    landslideScalarSelect.addEventListener('change', (event) => {
      applyLandslideScalar(event.target.value);
    });
  }

  container.querySelector('#reset-camera')?.addEventListener('click', () => {
    resetCamera();
  });
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

    const { caseInfo, terrain, water, landslide } = await loadCaseAndData(container);
    addActors(terrain, water, landslide);
    setupControls(container);

    const t = caseInfo.time?.values?.[0];
    const timeText = Number.isFinite(t) ? `t = ${t.toFixed(2)} s` : 'single frame';

    setStatus(container, `Loaded Aqaba Case 001 (${timeText}). Drag to rotate, scroll to zoom.`);
  } catch (error) {
    console.error('[MANTA Gallery] viewer failed:', error);
    setStatus(container, 'Failed to load MANTA Gallery viewer. Check Console and Network tabs.', true);
  }
}

main();
