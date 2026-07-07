const FDC_COLORS = {
  white: "#FFFFFF",
  lavender: "#B8A0FF",
  sky: "#6BC4FF",
};

const FDC_RANGE = 3;

class FreeDrawCanvas extends HTMLElement {
  static get observedAttributes() {
    return ["width", "height", "cols", "rows", "endpoint", "writable"];
  }

  connectedCallback() {
    this.render();
    this.init();
  }

  attributeChangedCallback() {
    this.render();
    this.init();
  }

  get writable() {
    const attr = this.getAttribute("writable");
    return attr === null ? true : attr !== "false";
  }

  render() {
    const size = this.getAttribute("width") || "600";
    const cols = this.getAttribute("cols") || "60";
    const rows = this.getAttribute("rows") || "60";

    const pencilIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>`;
    const circleIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg>`;
    const squareIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>`;
    const triangleIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4L22 20H2z"/></svg>`;
    const eraseIcon = `<svg viewBox="0 0 299.289 299.289" aria-hidden="true"><path d="M278.755,110.357l-122.111,122.11l-89.833-89.833l122.11-122.111c5.374-5.374,14.071-5.374,19.446,0l70.388,70.388C284.129,96.285,284.129,104.983,278.755,110.357z" fill="currentColor"/><path d="M110.367,278.744c-5.374,5.373-14.071,5.373-19.446,0l-70.388-70.388c-5.373-5.374-5.375-14.071,0-19.446l34.61-34.61l89.834,89.834L110.367,278.744z" fill="none" stroke="currentColor" stroke-width="12"/></svg>`;
    const clearIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>`;

    const toolbar = this.writable ? `
      <div class="fdc-toolbar" style="width: ${size}px;">
        <div class="fdc-tools">
          <button class="fdc-tool-btn active" data-tool="freehand" title="freehand">${pencilIcon}</button>
          <button class="fdc-tool-btn" data-tool="circle" title="circle">${circleIcon}</button>
          <button class="fdc-tool-btn" data-tool="square" title="square">${squareIcon}</button>
          <button class="fdc-tool-btn" data-tool="triangle" title="triangle">${triangleIcon}</button>
          <button class="fdc-tool-btn" data-tool="erase" title="erase">${eraseIcon}</button>
          <button class="fdc-tool-btn" data-action="clear" title="clear">${clearIcon}</button>
        </div>
        <div class="fdc-divider"></div>
        <div class="fdc-colors">
          <div class="fdc-color" style="background: ${FDC_COLORS.white};" data-color="white"></div>
          <div class="fdc-color active" style="background: ${FDC_COLORS.lavender};" data-color="lavender"></div>
          <div class="fdc-color" style="background: ${FDC_COLORS.sky};" data-color="sky"></div>
          <div class="fdc-color fdc-color-custom" data-color="custom">
            <input type="color" value="#FFFFFF">
          </div>
        </div>
        <div class="fdc-divider"></div>
        <label class="fdc-size-slider" title="brush size">
          <input type="range" min="1" max="30" value="5">
          <span class="fdc-size-value">5</span>
        </label>
      </div>
    ` : "";

    this.innerHTML = `
      <div class="free-draw-canvas ${this.writable ? "" : "readonly"}">
        ${toolbar}
        <div class="fdc-canvas-wrap" style="width: ${size}px; height: ${size}px;">
          <canvas class="fdc-canvas" width="${size}" height="${size}" style="cursor: ${this.writable ? "crosshair" : "default"}"></canvas>
          <canvas class="fdc-grid-overlay" width="${size}" height="${size}"></canvas>
        </div>
      </div>
    `;
  }

  init() {
    this.canvas = this.querySelector(".fdc-canvas");
    this.ctx = this.canvas.getContext("2d");
    this.gridCanvas = this.querySelector(".fdc-grid-overlay");
    this.gridCtx = this.gridCanvas.getContext("2d");

    this.currentTool = "freehand";
    this.currentColorKey = "lavender";
    this.customColor = "#B8A0FF";
    this.currentSize = 5;
    this.isDrawing = false;
    this.lastX = 0;
    this.lastY = 0;

    this.drawGrid();
    this.bindEvents();
  }

  get cols() {
    return parseInt(this.getAttribute("cols") || "60", 10);
  }

  get rows() {
    return parseInt(this.getAttribute("rows") || "60", 10);
  }

  get endpoint() {
    return this.getAttribute("endpoint") || "/api/drawing";
  }

  currentColor() {
    return this.currentColorKey === "custom" ? this.customColor : FDC_COLORS[this.currentColorKey];
  }

  coordToPixel(x, y) {
    const size = this.canvas.width;
    const half = size / 2;
    const px = (x / FDC_RANGE) * half + half;
    const py = -(y / FDC_RANGE) * half + half;
    return [px, py];
  }

  pixelToWorld(px, py) {
    const size = this.canvas.width;
    const half = size / 2;
    const x = ((px - half) / half) * FDC_RANGE;
    const y = -((py - half) / half) * FDC_RANGE;
    return [x, y];
  }

  getCentroid() {
    const size = this.canvas.width;
    const imageData = this.ctx.getImageData(0, 0, size, size).data;
    let sumX = 0, sumY = 0, count = 0;
    for (let py = 0; py < size; py++) {
      for (let px = 0; px < size; px++) {
        const idx = (py * size + px) * 4;
        const a = imageData[idx + 3];
        if (a > 10) {
          sumX += px;
          sumY += py;
          count++;
        }
      }
    }
    if (count === 0) return [0, 0];
    return this.pixelToWorld(sumX / count, sumY / count);
  }

  drawGrid() {
    const ctx = this.gridCtx;
    const size = this.canvas.width;

    ctx.clearRect(0, 0, size, size);

    // grid lines at integer coordinates
    ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
    ctx.lineWidth = 1;
    for (let i = -FDC_RANGE; i <= FDC_RANGE; i++) {
      const [x1, y1] = this.coordToPixel(i, -FDC_RANGE);
      const [x2, y2] = this.coordToPixel(i, FDC_RANGE);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
    for (let i = -FDC_RANGE; i <= FDC_RANGE; i++) {
      const [x1, y1] = this.coordToPixel(-FDC_RANGE, i);
      const [x2, y2] = this.coordToPixel(FDC_RANGE, i);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }

    // axes
    ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    const [leftX, leftY] = this.coordToPixel(-FDC_RANGE, 0);
    const [rightX, rightY] = this.coordToPixel(FDC_RANGE, 0);
    ctx.moveTo(leftX, leftY);
    ctx.lineTo(rightX, rightY);
    const [bottomX, bottomY] = this.coordToPixel(0, -FDC_RANGE);
    const [topX, topY] = this.coordToPixel(0, FDC_RANGE);
    ctx.moveTo(bottomX, bottomY);
    ctx.lineTo(topX, topY);
    ctx.stroke();

    // ticks and labels
    ctx.fillStyle = "rgba(255, 255, 255, 0.55)";
    ctx.font = "12px 'Space Grotesk', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";

    for (let i = -FDC_RANGE; i <= FDC_RANGE; i++) {
      if (i === 0) continue;
      const [px, py] = this.coordToPixel(i, 0);
      ctx.beginPath();
      ctx.moveTo(px, py - 4);
      ctx.lineTo(px, py + 4);
      ctx.stroke();
      ctx.fillText(i.toString(), px, py + 8);

      const [px2, py2] = this.coordToPixel(0, i);
      ctx.beginPath();
      ctx.moveTo(px2 - 4, py2);
      ctx.lineTo(px2 + 4, py2);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(i.toString(), px2 - 8, py2 - 5);
      ctx.textAlign = "center";
    }

    // origin label
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    const [originX, originY] = this.coordToPixel(0, 0);
    ctx.fillText("0", originX + 4, originY + 4);
  }

  bindEvents() {
    if (!this.writable) return;

    this.querySelectorAll(".fdc-tool-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.action === "clear") {
          this.clear();
          return;
        }
        this.querySelectorAll(".fdc-tool-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        this.currentTool = btn.dataset.tool;
      });
    });

    this.querySelectorAll(".fdc-color[data-color]").forEach((swatch) => {
      if (swatch.dataset.color === "custom") return;
      swatch.addEventListener("click", () => {
        this.querySelectorAll(".fdc-color").forEach((s) => s.classList.remove("active"));
        swatch.classList.add("active");
        this.currentColorKey = swatch.dataset.color;
      });
    });

    const colorInput = this.querySelector(".fdc-color-custom input");
    colorInput.addEventListener("input", () => {
      this.customColor = colorInput.value;
      this.querySelector(".fdc-color-custom").style.background = this.customColor;
      this.querySelectorAll(".fdc-color").forEach((s) => s.classList.remove("active"));
      this.querySelector(".fdc-color-custom").classList.add("active");
      this.currentColorKey = "custom";
    });

    const sizeInput = this.querySelector(".fdc-size-slider input");
    const sizeValue = this.querySelector(".fdc-size-value");
    sizeInput.addEventListener("input", () => {
      this.currentSize = parseInt(sizeInput.value, 10);
      sizeValue.textContent = this.currentSize;
    });

    this.canvas.addEventListener("mousedown", (e) => this.startStroke(e));
    this.canvas.addEventListener("mousemove", (e) => this.moveStroke(e));
    this.canvas.addEventListener("mouseup", () => this.endStroke());
    this.canvas.addEventListener("mouseleave", () => this.endStroke());

    this.canvas.addEventListener("touchstart", (e) => this.startStroke(e.touches[0]), { passive: true });
    this.canvas.addEventListener("touchmove", (e) => {
      e.preventDefault();
      this.moveStroke(e.touches[0]);
    });
    this.canvas.addEventListener("touchend", () => this.endStroke());
  }

  getPointerPos(event) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  startStroke(event) {
    this.isDrawing = true;
    const pos = this.getPointerPos(event);
    this.lastX = pos.x;
    this.lastY = pos.y;

    if (this.currentTool !== "freehand" && this.currentTool !== "erase") {
      this.placeShape(this.currentTool, pos.x, pos.y);
      this.isDrawing = false;
    } else if (this.currentTool === "freehand" || this.currentTool === "erase") {
      this.drawSegment(pos.x, pos.y, pos.x, pos.y);
    }
  }

  moveStroke(event) {
    if (!this.isDrawing) return;
    const pos = this.getPointerPos(event);

    if (this.currentTool === "freehand" || this.currentTool === "erase") {
      this.drawSegment(this.lastX, this.lastY, pos.x, pos.y);
    }

    this.lastX = pos.x;
    this.lastY = pos.y;
  }

  endStroke() {
    this.isDrawing = false;
  }

  drawSegment(x1, y1, x2, y2) {
    const ctx = this.ctx;

    if (this.currentTool === "erase") {
      ctx.globalCompositeOperation = "destination-out";
      ctx.strokeStyle = "rgba(0, 0, 0, 1)";
    } else {
      ctx.globalCompositeOperation = "source-over";
      ctx.strokeStyle = this.currentColor();
    }

    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.lineWidth = this.currentSize;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();
    ctx.globalCompositeOperation = "source-over";
  }

  placeShape(tool, x, y) {
    const ctx = this.ctx;
    const color = this.currentColor();
    const size = this.currentSize * 6;

    ctx.fillStyle = color;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1, this.currentSize / 3);

    switch (tool) {
      case "circle":
        ctx.beginPath();
        ctx.arc(x, y, size / 2, 0, Math.PI * 2);
        ctx.fill();
        break;
      case "square":
        ctx.fillRect(x - size / 2, y - size / 2, size, size);
        break;
      case "triangle": {
        const h = size * 0.866;
        ctx.beginPath();
        ctx.moveTo(x, y - h / 2);
        ctx.lineTo(x - size / 2, y + h / 2);
        ctx.lineTo(x + size / 2, y + h / 2);
        ctx.closePath();
        ctx.fill();
        break;
      }
    }
  }

  clear() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  getGrid() {
    const size = this.canvas.width;
    const cols = this.cols;
    const rows = this.rows;
    const cellW = size / cols;
    const cellH = size / rows;

    const imageData = this.ctx.getImageData(0, 0, size, size).data;
    const grid = [];

    for (let row = 0; row < rows; row++) {
      const gridRow = [];
      for (let col = 0; col < cols; col++) {
        const startX = Math.floor(col * cellW);
        const startY = Math.floor(row * cellH);
        const endX = Math.floor((col + 1) * cellW);
        const endY = Math.floor((row + 1) * cellH);

        let r = 0, g = 0, b = 0, a = 0, count = 0;
        for (let py = startY; py < endY && py < size; py++) {
          for (let px = startX; px < endX && px < size; px++) {
            const idx = (py * size + px) * 4;
            r += imageData[idx];
            g += imageData[idx + 1];
            b += imageData[idx + 2];
            a += imageData[idx + 3];
            count++;
          }
        }

        if (count > 0) {
          r = Math.round(r / count);
          g = Math.round(g / count);
          b = Math.round(b / count);
          a = Math.round(a / count);
        }

        gridRow.push([r, g, b, a]);
      }
      grid.push(gridRow);
    }

    return {
      grid: grid,
      shape: [rows, cols],
      range: [-FDC_RANGE, FDC_RANGE],
      timestamp: Date.now(),
    };
  }

  /**
   * Render an rgba grid onto the canvas.
   * grid: rows x cols x 4 array with values in [0, 255].
   * The grid is stretched to fill the canvas.
   */
  drawGrid(grid) {
    const ctx = this.ctx;
    const size = this.canvas.width;
    ctx.clearRect(0, 0, size, size);

    if (!grid || grid.length === 0 || grid[0].length === 0) return;

    const rows = grid.length;
    const cols = grid[0].length;
    const cellW = size / cols;
    const cellH = size / rows;

    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const [r, g, b, a = 255] = grid[row][col];
        ctx.fillStyle = `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${a / 255})`;
        ctx.fillRect(Math.round(col * cellW), Math.round(row * cellH), Math.ceil(cellW), Math.ceil(cellH));
      }
    }
  }

  /**
   * Draw a polyline of (x, y) world-space points.
   */
  drawCurve(points, color = "#B8A0FF", lineWidth = 3) {
    const ctx = this.ctx;
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    let first = true;
    for (const [x, y] of points) {
      const [px, py] = this.coordToPixel(x, y);
      if (first) {
        ctx.moveTo(px, py);
        first = false;
      } else {
        ctx.lineTo(px, py);
      }
    }
    ctx.stroke();
  }

  exportGrid() {
    const payload = this.getGrid();

    fetch(this.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => console.log("Sent:", r.status))
      .catch((e) => console.log("Backend not ready:", e));

    return payload;
  }
}

customElements.define("free-draw-canvas", FreeDrawCanvas);
