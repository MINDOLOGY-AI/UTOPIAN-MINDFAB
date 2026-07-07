"use strict";

const DEFAULT_SIZE = 300;

/**
 * <heatmap-plot>
 *
 * Renders a 2D grid of scalar values as a colored heatmap.
 *
 * Attributes:
 *   width, height: canvas size (default 300)
 *
 * API:
 *   setData(grid) — grid is a 2D array of numbers (rows x cols)
 *   setRange(min, max) — optional; auto-computed if omitted
 */
class HeatmapPlot extends HTMLElement {
  static get observedAttributes() {
    return ["width", "height"];
  }

  connectedCallback() {
    this.render();
    if (this.pendingGrid) {
      this.setData(this.pendingGrid);
      this.pendingGrid = null;
    }
  }

  get width() {
    return parseInt(this.getAttribute("width") || String(DEFAULT_SIZE), 10);
  }

  get height() {
    return parseInt(this.getAttribute("height") || String(DEFAULT_SIZE), 10);
  }

  render() {
    this.innerHTML = `
      <div class="heatmap-plot">
        <canvas width="${this.width}" height="${this.height}"></canvas>
      </div>
    `;
    this.canvas = this.querySelector("canvas");
    this.ctx = this.canvas.getContext("2d");
    this.grid = null;
  }

  setData(grid) {
    this.grid = grid;
    if (!this.isConnected) {
      this.pendingGrid = grid;
      return;
    }
    this.draw();
  }

  setRange(min, max) {
    this.fixedMin = min;
    this.fixedMax = max;
    this.draw();
  }

  valueToColor(v, min, max) {
    if (max === min) return "rgb(128, 128, 128)";
    const t = Math.max(0, Math.min(1, (v - min) / (max - min)));
    // lavender (#B8A0FF) to dark background
    const r = Math.round(20 + t * (184 - 20));
    const g = Math.round(20 + t * (160 - 20));
    const b = Math.round(30 + t * (255 - 30));
    return `rgb(${r}, ${g}, ${b})`;
  }

  draw() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    ctx.clearRect(0, 0, w, h);

    if (!this.grid || this.grid.length === 0) return;

    const rows = this.grid.length;
    const cols = this.grid[0].length;
    const cellW = w / cols;
    const cellH = h / rows;

    let min = this.fixedMin;
    let max = this.fixedMax;
    if (min === undefined || max === undefined) {
      min = Infinity;
      max = -Infinity;
      for (const row of this.grid) {
        for (const v of row) {
          if (v < min) min = v;
          if (v > max) max = v;
        }
      }
    }

    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        ctx.fillStyle = this.valueToColor(this.grid[row][col], min, max);
        ctx.fillRect(col * cellW, row * cellH, cellW + 0.5, cellH + 0.5);
      }
    }
  }
}

customElements.define("heatmap-plot", HeatmapPlot);
