import { train1d1d, predict, getHyperplane } from "./api.js";
import { createTrainingPanel } from "./training_panel.js";

const targetCanvas = document.getElementById("target-canvas");
const predictionCanvas = document.getElementById("prediction-canvas");
const trainingPanelContainer = document.getElementById("training-panel");
const hyperplaneContainer = document.getElementById("hyperplane-plots");

let currentSessionId = null;

const COLORS = ["#B8A0FF", "#6BC4FF", "#7FFFD4", "#FFFFFF", "#FF0055"];

function denseXGrid(n = 200, range = 3) {
  const xs = [];
  for (let i = 0; i < n; i++) {
    const x = -range + (2 * range * i) / (n - 1);
    xs.push([x]);
  }
  return xs;
}

async function renderPrediction(sessionId) {
  const xs = denseXGrid();
  const result = await predict(sessionId, xs);
  const ys = result.y;
  predictionCanvas.clear();
  predictionCanvas.drawCurve(
    xs.map((x, i) => [x[0], ys[i][0]]),
    "#B8A0FF",
    3,
  );
}

async function renderHyperplanes(sessionId, dims) {
  hyperplaneContainer.innerHTML = "";
  for (let layerIdx = 0; layerIdx < dims.length - 1; layerIdx++) {
    const neuronCount = dims[layerIdx + 1];
    for (let n = 0; n < neuronCount; n++) {
      const data = await getHyperplane(sessionId, layerIdx, n, 100);
      const plot = document.createElement("line-plot");
      plot.setAttribute("width", "150");
      plot.setAttribute("height", "150");
      plot.setAttribute("xlabel", "x");
      plot.setAttribute("ylabel", "out");
      plot.setAttribute("xmin", "-3");
      plot.setAttribute("xmax", "3");
      plot.setAttribute("ymin", "-3");
      plot.setAttribute("ymax", "3");
      plot.setData([
        {
          name: `L${layerIdx}N${n} post`,
          color: "#B8A0FF",
          data: data.x.map((xv, i) => ({ x: xv, y: data.y[i] })),
        },
      ]);
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
  const result = await train1d1d(payload.grid, epochs, lr, batchSize, dims);
  currentSessionId = result.session_id;
  await renderPrediction(currentSessionId);
  await renderHyperplanes(currentSessionId, result.dims);
  return result;
}, [1, 16, 16, 1]);

trainingPanelContainer.onTrainingDone = (result) => {
  currentSessionId = result.session_id;
};
