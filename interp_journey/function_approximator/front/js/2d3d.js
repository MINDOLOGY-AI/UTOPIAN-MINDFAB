import { train2d3d, predict, getHyperplane } from "./api.js";
import { createTrainingPanel } from "./training_panel.js";

const targetCanvas = document.getElementById("target-canvas");
const predictionCanvas = document.getElementById("prediction-canvas");
const trainingPanelContainer = document.getElementById("training-panel");
const hyperplaneContainer = document.getElementById("hyperplane-plots");

let currentSessionId = null;

function dense2dGrid(res = 30, range = 3) {
  const xs = [];
  for (let row = 0; row < res; row++) {
    for (let col = 0; col < res; col++) {
      const x = -range + (2 * range * col) / (res - 1);
      const y = -range + (2 * range * row) / (res - 1);
      xs.push([x, y]);
    }
  }
  return xs;
}

function toRgbGrid(ys, res = 30) {
  const grid = [];
  for (let row = 0; row < res; row++) {
    const gridRow = [];
    for (let col = 0; col < res; col++) {
      const [r, g, b] = ys[row * res + col];
      gridRow.push([
        Math.max(0, Math.min(255, Math.round(r * 255))),
        Math.max(0, Math.min(255, Math.round(g * 255))),
        Math.max(0, Math.min(255, Math.round(b * 255))),
        255,
      ]);
    }
    grid.push(gridRow);
  }
  return grid;
}

async function renderPrediction(sessionId) {
  const res = 30;
  const xs = dense2dGrid(res);
  const result = await predict(sessionId, xs);
  const grid = toRgbGrid(result.y, res);
  predictionCanvas.clear();
  predictionCanvas.drawGrid(grid);
}

async function renderHyperplanes(sessionId, dims) {
  hyperplaneContainer.innerHTML = "";
  for (let layerIdx = 0; layerIdx < dims.length - 1; layerIdx++) {
    const neuronCount = dims[layerIdx + 1];
    for (let n = 0; n < neuronCount; n++) {
      const data = await getHyperplane(sessionId, layerIdx, n, 6);
      const plot = document.createElement("surface-3d");
      plot.setAttribute("width", "160");
      plot.setAttribute("height", "160");
      plot.setAttribute("range", "3");
      plot.setData(data.x, data.y, data.z);
      const wrap = document.createElement("div");
      wrap.className = "hyperplane-mini";
      wrap.innerHTML = `<span>L${layerIdx} N${n}</span>`;
      wrap.appendChild(plot);
      hyperplaneContainer.appendChild(wrap);
    }
  }
}

createTrainingPanel(trainingPanelContainer, async ({ epochs, lr, batchSize, dims }) => {
  const payload = targetCanvas.getGrid();
  const result = await train2d3d(payload.grid, epochs, lr, batchSize, dims);
  currentSessionId = result.session_id;
  await renderPrediction(currentSessionId);
  await renderHyperplanes(currentSessionId, result.dims);
  return result;
}, [2, 16, 16, 3]);

trainingPanelContainer.onTrainingDone = (result) => {
  currentSessionId = result.session_id;
};
