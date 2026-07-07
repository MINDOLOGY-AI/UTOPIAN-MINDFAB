export function createTrainingPanel(container, onTrain, defaultDims = [1, 16, 16, 1], fixed = false) {
  const fixedDims = fixed ? defaultDims : null;
  const dimsStr = Array.isArray(defaultDims) ? defaultDims.join(",") : String(defaultDims);
  const dimsInput = fixedDims
    ? `<span class="tp-dims-fixed">${dimsStr}</span>`
    : `<input type="text" class="tp-dims" value="${dimsStr}">`;

  container.innerHTML = `
    <div class="training-panel">
      <label>epochs <input type="number" class="tp-epochs" value="200" min="1"></label>
      <label>lr <input type="number" class="tp-lr" value="0.001" step="0.0001"></label>
      <label>batch <input type="number" class="tp-batch" value="32" min="1"></label>
      <label>dims ${dimsInput}</label>
      <button class="tp-train">train</button>
      <div class="tp-status"></div>
      <img class="tp-loss" alt="loss curve" style="display:none;">
    </div>
  `;

  const epochsEl = container.querySelector(".tp-epochs");
  const lrEl = container.querySelector(".tp-lr");
  const batchEl = container.querySelector(".tp-batch");
  const dimsEl = container.querySelector(".tp-dims");
  const statusEl = container.querySelector(".tp-status");
  const lossImg = container.querySelector(".tp-loss");

  function setStatus(msg) {
    statusEl.textContent = msg;
  }

  function setLossImage(url) {
    lossImg.src = url;
    lossImg.style.display = "block";
  }

  function getDims() {
    if (fixedDims) return fixedDims;
    return dimsEl.value.split(",").map((s) => parseInt(s.trim(), 10));
  }

  container.querySelector(".tp-train").addEventListener("click", async () => {
    const epochs = parseInt(epochsEl.value, 10);
    const lr = parseFloat(lrEl.value);
    const batchSize = parseInt(batchEl.value, 10);
    const dims = getDims();

    setStatus("training...");
    lossImg.style.display = "none";

    try {
      const result = await onTrain({ epochs, lr, batchSize, dims });
      setStatus(`final loss: ${result.final_loss.toExponential(3)}`);
      setLossImage(result.loss_image + `?t=${Date.now()}`);
      if (container.onTrainingDone) {
        container.onTrainingDone(result);
      }
    } catch (e) {
      setStatus(`error: ${e.message}`);
      console.error(e);
    }
  });

  return { setStatus, setLossImage };
}
