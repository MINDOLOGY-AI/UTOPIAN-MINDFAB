"use strict";

const DEFAULT_WIDTH = 600;
const DEFAULT_HEIGHT = 300;
const PADDING = 32;

class LinePlot extends HTMLElement {
  static get observedAttributes() {
    return ["width", "height", "xlabel", "ylabel", "xmin", "xmax", "ymin", "ymax"];
  }

  connectedCallback() {
    this.render();
    if (this.pendingSeries) {
      this.setData(this.pendingSeries);
      this.pendingSeries = null;
    }
  }

  get width() {
    return parseInt(this.getAttribute("width") || String(DEFAULT_WIDTH), 10);
  }

  get height() {
    return parseInt(this.getAttribute("height") || String(DEFAULT_HEIGHT), 10);
  }

  getRange(attrMin, attrMax, dataMin, dataMax) {
    let min = parseFloat(this.getAttribute(attrMin));
    let max = parseFloat(this.getAttribute(attrMax));
    if (!isFinite(min)) min = dataMin;
    if (!isFinite(max)) max = dataMax;
    if (min === max) { min -= 1; max += 1; }
    return { min, max };
  }

  render() {
    this.innerHTML = `
      <div class="line-plot">
        <canvas width="${this.width}" height="${this.height}"></canvas>
      </div>
    `;
    this.canvas = this.querySelector("canvas");
    this.ctx = this.canvas.getContext("2d");
  }

  setData(series) {
    // series: [{name, color, data: [{x, y}]}]
    this.series = series || [];
    if (!this.isConnected) {
      this.pendingSeries = this.series;
      return;
    }
    this.draw();
  }

  clear() {
    this.ctx.clearRect(0, 0, this.width, this.height);
  }

  draw() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    ctx.clearRect(0, 0, w, h);

    if (this.series.length === 0) return;

    let dataMinX = Infinity, dataMaxX = -Infinity, dataMinY = Infinity, dataMaxY = -Infinity;
    for (const s of this.series) {
      for (const p of s.data) {
        if (p.x < dataMinX) dataMinX = p.x;
        if (p.x > dataMaxX) dataMaxX = p.x;
        if (p.y < dataMinY) dataMinY = p.y;
        if (p.y > dataMaxY) dataMaxY = p.y;
      }
    }
    const xr = this.getRange("xmin", "xmax", dataMinX, dataMaxX);
    const yr = this.getRange("ymin", "ymax", dataMinY, dataMaxY);
    const minX = xr.min, maxX = xr.max;
    const minY = yr.min, maxY = yr.max;

    const plotW = w - 2 * PADDING;
    const plotH = h - 2 * PADDING;

    const toPx = (x, y) => ({
      x: PADDING + ((x - minX) / (maxX - minX)) * plotW,
      y: PADDING + plotH - ((y - minY) / (maxY - minY)) * plotH,
    });

    // axes
    ctx.strokeStyle = "rgba(255, 255, 255, 0.3)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PADDING, PADDING);
    ctx.lineTo(PADDING, h - PADDING);
    ctx.lineTo(w - PADDING, h - PADDING);
    ctx.stroke();

    // labels
    ctx.fillStyle = "rgba(255, 255, 255, 0.6)";
    ctx.font = "12px 'Space Grotesk', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(this.getAttribute("xlabel") || "x", w / 2, h - 8);
    ctx.save();
    ctx.translate(12, h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(this.getAttribute("ylabel") || "y", 0, 0);
    ctx.restore();

    // series
    for (const s of this.series) {
      ctx.strokeStyle = s.color || "#B8A0FF";
      ctx.lineWidth = 2;
      ctx.beginPath();
      let first = true;
      for (const p of s.data) {
        const pp = toPx(p.x, p.y);
        if (first) {
          ctx.moveTo(pp.x, pp.y);
          first = false;
        } else {
          ctx.lineTo(pp.x, pp.y);
        }
      }
      ctx.stroke();
    }
  }
}

customElements.define("line-plot", LinePlot);
