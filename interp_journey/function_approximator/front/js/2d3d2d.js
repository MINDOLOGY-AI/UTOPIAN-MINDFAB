import {
  train2d3d2d,
  predict,
  getLiteralNeurons,
  setNeuronWeights,
  setDecoderBias,
  getSpaceShift,
} from "./api.js";
import { createTrainingPanel } from "./training_panel.js";

const inputEditor = document.getElementById("input-editor");
const outputEditor = document.getElementById("output-editor");
const inferInput = document.getElementById("infer-input");
const inferBtn = document.getElementById("infer-btn");
const inferOutput = document.getElementById("infer-output");
const addPairBtn = document.getElementById("add-pair");
const clearPairsBtn = document.getElementById("clear-pairs");
const pairList = document.getElementById("pair-list");
const trainingPanelContainer = document.getElementById("training-panel");
const encoderEditor = document.getElementById("encoder-editor");
const decoderEditor = document.getElementById("decoder-editor");
const encoderBiases = document.getElementById("encoder-biases");
const decoderBiases = document.getElementById("decoder-biases");
const spaceShiftCanvas = document.getElementById("space-shift-canvas");
const spaceShiftCtx = spaceShiftCanvas.getContext("2d");

const COLORS = ["#B8A0FF", "#6BC4FF", "#7FFFD4", "#FFFFFF", "#FF0055", "#FFD700", "#FF69B4"];

const REGION_COLORS = {
  "0,0,0": "#888888",
  "1,0,0": "#FF0055",
  "0,1,0": "#7FFFD4",
  "0,0,1": "#6BC4FF",
  "1,1,0": "#FFD700",
  "1,0,1": "#B8A0FF",
  "0,1,1": "#FFFFFF",
  "1,1,1": "#FF69B4",
};

function maskColor(mask) {
  return REGION_COLORS[mask.join(",")] || "#aaaaaa";
}

const DEFAULT_PAIRS = [
  { input: [1.0, 0.5], output: [1.2, -0.3] },
  { input: [-0.5, 0.8], output: [-0.4, 0.9] },
  { input: [0.3, -0.7], output: [0.5, -0.8] },
];

let pairs = JSON.parse(JSON.stringify(DEFAULT_PAIRS));
let currentSessionId = null;
let currentEncoderBias = [];
let currentDecoderBias = [];

function nextColor(i) {
  return COLORS[i % COLORS.length];
}

function pairToVectors() {
  return pairs.map((p, i) => ({
    x: p.input[0],
    y: p.input[1],
    color: nextColor(i),
    label: `p${i}`,
  }));
}

function pairToOutputVectors() {
  return pairs.map((p, i) => ({
    x: p.output[0],
    y: p.output[1],
    color: nextColor(i),
    label: `p${i}`,
  }));
}

function renderEditors() {
  inputEditor.setVectors(pairToVectors());
  outputEditor.setVectors(pairToOutputVectors());
}

function renderPairList() {
  pairList.innerHTML = "";
  pairs.forEach((pair, i) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="pair-color" style="background:${nextColor(i)}"></span>
      in (${pair.input[0].toFixed(2)}, ${pair.input[1].toFixed(2)})
      &rarr; out (${pair.output[0].toFixed(2)}, ${pair.output[1].toFixed(2)})
      <button data-idx="${i}">x</button>
    `;
    li.querySelector("button").addEventListener("click", () => {
      pairs.splice(i, 1);
      renderPairList();
      renderEditors();
      outputEditor.setOverlay([]);
    });
    pairList.appendChild(li);
  });
}

addPairBtn.addEventListener("click", () => {
  pairs.push({ input: [0.5, 0.5], output: [0.5, 0.5] });
  renderPairList();
  renderEditors();
});

clearPairsBtn.addEventListener("click", () => {
  pairs = [];
  renderPairList();
  renderEditors();
  outputEditor.setOverlay([]);
});

inputEditor.addEventListener("change", (e) => {
  const { index, vector } = e.detail;
  pairs[index].input = [vector.x, vector.y];
  renderPairList();
  if (currentSessionId) {
    renderPredictions(currentSessionId);
  }
});

outputEditor.addEventListener("change", (e) => {
  const { index, vector } = e.detail;
  pairs[index].output = [vector.x, vector.y];
  renderPairList();
});

inferBtn.addEventListener("click", async () => {
  if (!currentSessionId) return;
  const v = inferInput.getVectors()[0];
  const result = await predict(currentSessionId, [[v.x, v.y]]);
  const out = result.y[0];
  inferOutput.setVectors([{ x: out[0], y: out[1], color: "#B8A0FF", label: "out" }]);
});

async function renderPredictions(sessionId) {
  const inputs = pairs.map((p) => p.input);
  if (inputs.length === 0) {
    outputEditor.setOverlay([]);
    return;
  }
  const result = await predict(sessionId, inputs);
  const overlay = result.y.map((out, i) => ({
    x: out[0],
    y: out[1],
    color: nextColor(i),
    label: `p${i}`,
  }));
  outputEditor.setOverlay(overlay);
}

function buildBiasInputs(container, values, onChange, prefix) {
  container.innerHTML = "";
  values.forEach((b, i) => {
    const label = document.createElement("label");
    label.className = "bias-item";
    label.innerHTML = `${prefix}${i} <input type="number" step="0.01" value="${b.toFixed(3)}">`;
    label.querySelector("input").addEventListener("change", (e) => {
      onChange(i, parseFloat(e.target.value));
    });
    container.appendChild(label);
  });
}

async function renderLiteralNeurons(sessionId) {
  const data = await getLiteralNeurons(sessionId);
  const encoder = data.encoder;
  const decoder = data.decoder;

  currentEncoderBias = encoder.bias;
  currentDecoderBias = decoder.bias;

  encoderEditor.setVectors(encoder.weight.map((w, i) => ({
    x: w[0],
    y: w[1],
    color: nextColor(i),
    label: `n${i}`,
  })));

  decoderEditor.setVectors(decoder.weight[0].map((_, i) => ({
    x: decoder.weight[0][i],
    y: decoder.weight[1][i],
    color: nextColor(i),
    label: `n${i}`,
  })));

  buildBiasInputs(encoderBiases, currentEncoderBias, async (i, b) => {
    if (!currentSessionId) return;
    const v = encoderEditor.getVectors()[i];
    await setNeuronWeights(currentSessionId, "encoder", i, [v.x, v.y], b);
    await Promise.all([renderPredictions(currentSessionId), renderSpaceShift(currentSessionId)]);
  }, "b");

  buildBiasInputs(decoderBiases, currentDecoderBias, async (i, b) => {
    if (!currentSessionId) return;
    await setDecoderBias(currentSessionId, i, b);
    await Promise.all([renderPredictions(currentSessionId), renderSpaceShift(currentSessionId)]);
  }, "out");
}

async function renderSpaceShift(sessionId) {
  const data = await getSpaceShift(sessionId, 30);
  const w = spaceShiftCanvas.width;
  const h = spaceShiftCanvas.height;
  const pad = 10;
  spaceShiftCtx.clearRect(0, 0, w, h);

  const inX = data.input_x;
  const inY = data.input_y;
  const outX = data.output_x;
  const outY = data.output_y;
  const masks = data.masks;
  const res = inX.length;

  const halfW = w / 2;
  const square = Math.min(halfW, h) - 2 * pad;
  const inLeft = (halfW - square) / 2;
  const inTop = (h - square) / 2;
  const outLeft = halfW + (halfW - square) / 2;

  function toInputPx(x, y) {
    return {
      x: inLeft + ((x + 3) / 6) * square,
      y: inTop + square * (1 - (y + 3) / 6),
    };
  }

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (let i = 0; i < res; i++) {
    for (let j = 0; j < res; j++) {
      const x = outX[i][j], y = outY[i][j];
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }
  if (!isFinite(minX) || minX === maxX) { minX = -3; maxX = 3; }
  if (!isFinite(minY) || minY === maxY) { minY = -3; maxY = 3; }
  const maxRange = Math.max(maxX - minX, maxY - minY);
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;

  function toOutputPx(x, y) {
    return {
      x: outLeft + square * (0.5 + (x - cx) / maxRange),
      y: inTop + square * (0.5 - (y - cy) / maxRange),
    };
  }

  function quad(pts) {
    spaceShiftCtx.beginPath();
    spaceShiftCtx.moveTo(pts[0].x, pts[0].y);
    for (let k = 1; k < pts.length; k++) spaceShiftCtx.lineTo(pts[k].x, pts[k].y);
    spaceShiftCtx.closePath();
  }

  // input cells
  for (let i = 0; i < res - 1; i++) {
    for (let j = 0; j < res - 1; j++) {
      const color = maskColor(masks[i][j]);
      spaceShiftCtx.fillStyle = color + "40";
      quad([
        toInputPx(inX[i][j], inY[i][j]),
        toInputPx(inX[i][j + 1], inY[i][j + 1]),
        toInputPx(inX[i + 1][j + 1], inY[i + 1][j + 1]),
        toInputPx(inX[i + 1][j], inY[i + 1][j]),
      ]);
      spaceShiftCtx.fill();
    }
  }

  // output cells
  for (let i = 0; i < res - 1; i++) {
    for (let j = 0; j < res - 1; j++) {
      const color = maskColor(masks[i][j]);
      spaceShiftCtx.fillStyle = color + "55";
      quad([
        toOutputPx(outX[i][j], outY[i][j]),
        toOutputPx(outX[i][j + 1], outY[i][j + 1]),
        toOutputPx(outX[i + 1][j + 1], outY[i + 1][j + 1]),
        toOutputPx(outX[i + 1][j], outY[i + 1][j]),
      ]);
      spaceShiftCtx.fill();
    }
  }

  // input grid lines
  spaceShiftCtx.strokeStyle = "rgba(255, 255, 255, 0.25)";
  spaceShiftCtx.lineWidth = 0.5;
  for (let i = 0; i < res; i++) {
    for (let j = 0; j < res - 1; j++) {
      const a = toInputPx(inX[i][j], inY[i][j]);
      const b = toInputPx(inX[i][j + 1], inY[i][j + 1]);
      spaceShiftCtx.beginPath();
      spaceShiftCtx.moveTo(a.x, a.y);
      spaceShiftCtx.lineTo(b.x, b.y);
      spaceShiftCtx.stroke();
    }
  }
  for (let j = 0; j < res; j++) {
    for (let i = 0; i < res - 1; i++) {
      const a = toInputPx(inX[i][j], inY[i][j]);
      const b = toInputPx(inX[i + 1][j], inY[i + 1][j]);
      spaceShiftCtx.beginPath();
      spaceShiftCtx.moveTo(a.x, a.y);
      spaceShiftCtx.lineTo(b.x, b.y);
      spaceShiftCtx.stroke();
    }
  }

  // output grid lines colored by region
  spaceShiftCtx.lineWidth = 0.8;
  for (let i = 0; i < res; i++) {
    for (let j = 0; j < res - 1; j++) {
      const color = maskColor(masks[i][j]);
      spaceShiftCtx.strokeStyle = color;
      const a = toOutputPx(outX[i][j], outY[i][j]);
      const b = toOutputPx(outX[i][j + 1], outY[i][j + 1]);
      spaceShiftCtx.beginPath();
      spaceShiftCtx.moveTo(a.x, a.y);
      spaceShiftCtx.lineTo(b.x, b.y);
      spaceShiftCtx.stroke();
    }
  }
  for (let j = 0; j < res; j++) {
    for (let i = 0; i < res - 1; i++) {
      const color = maskColor(masks[i][j]);
      spaceShiftCtx.strokeStyle = color;
      const a = toOutputPx(outX[i][j], outY[i][j]);
      const b = toOutputPx(outX[i + 1][j], outY[i + 1][j]);
      spaceShiftCtx.beginPath();
      spaceShiftCtx.moveTo(a.x, a.y);
      spaceShiftCtx.lineTo(b.x, b.y);
      spaceShiftCtx.stroke();
    }
  }

  // divider
  spaceShiftCtx.strokeStyle = "rgba(255, 255, 255, 0.2)";
  spaceShiftCtx.lineWidth = 1;
  spaceShiftCtx.beginPath();
  spaceShiftCtx.moveTo(w / 2, 0);
  spaceShiftCtx.lineTo(w / 2, h);
  spaceShiftCtx.stroke();
}

createTrainingPanel(trainingPanelContainer, async ({ epochs, lr, batchSize, dims }) => {
  const inputs = pairs.map((p) => p.input);
  const outputs = pairs.map((p) => p.output);
  const result = await train2d3d2d(inputs, outputs, epochs, lr, batchSize, dims);
  currentSessionId = result.session_id;
  await Promise.all([
    renderPredictions(currentSessionId),
    renderLiteralNeurons(currentSessionId),
    renderSpaceShift(currentSessionId),
  ]);
  return result;
}, [2, 3, 2], true);

encoderEditor.addEventListener("change", async (e) => {
  if (!currentSessionId) return;
  const { index, vector } = e.detail;
  await setNeuronWeights(currentSessionId, "encoder", index, [vector.x, vector.y], currentEncoderBias[index]);
  await Promise.all([
    renderPredictions(currentSessionId),
    renderSpaceShift(currentSessionId),
  ]);
});

decoderEditor.addEventListener("change", async (e) => {
  if (!currentSessionId) return;
  const { index, vector } = e.detail;
  await setNeuronWeights(currentSessionId, "decoder", index, [vector.x, vector.y]);
  await Promise.all([
    renderPredictions(currentSessionId),
    renderSpaceShift(currentSessionId),
  ]);
});

renderPairList();
renderEditors();
inferInput.setVectors([{ x: 0.5, y: 0.5, color: "#B8A0FF", label: "in" }]);
