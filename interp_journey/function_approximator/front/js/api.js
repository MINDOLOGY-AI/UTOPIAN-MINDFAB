const BASE = "/api/function_approximator";

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export async function train1d1d(grid, epochs, lr, batchSize, dims) {
  return post("/train", { task: "1d1d", grid, epochs, lr, batch_size: batchSize, dims });
}

export async function train2d3d(grid, epochs, lr, batchSize, dims) {
  return post("/train", { task: "2d3d", grid, epochs, lr, batch_size: batchSize, dims });
}

export async function train2d3d2d(inputs, outputs, epochs, lr, batchSize, dims) {
  return post("/train", { task: "2d3d2d", inputs, outputs, epochs, lr, batch_size: batchSize, dims });
}

export async function predict(sessionId, x) {
  return post("/predict", { session_id: sessionId, x });
}

export async function getHyperplane(sessionId, layer, neuron, gridRes = 100) {
  return post("/hyperplane", { session_id: sessionId, layer, neuron, grid_res: gridRes });
}

export async function getLiteralNeurons(sessionId) {
  return post("/literal_neurons", { session_id: sessionId });
}

export async function setNeuronWeights(sessionId, layer, index, weights, bias = null) {
  return post("/neuron_weights", { session_id: sessionId, layer, index, weights, bias });
}

export async function setDecoderBias(sessionId, index, bias) {
  return post("/decoder_bias", { session_id: sessionId, index, bias });
}

export async function getSpaceShift(sessionId, gridRes = 20) {
  return post("/space_shift", { session_id: sessionId, grid_res: gridRes });
}

export function lossImageUrl(sessionId) {
  return `${BASE}/loss/${sessionId}`;
}

export async function deleteSession(sessionId) {
  await fetch(`${BASE}/session/${sessionId}`, { method: "DELETE" });
}
