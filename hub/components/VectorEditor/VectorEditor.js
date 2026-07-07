"use strict";

const DEFAULT_SIZE = 300;
const DEFAULT_RANGE = 3;
const POINT_RADIUS = 6;
const AXIS_COLOR = "rgba(255, 255, 255, 0.2)";

/**
 * <vector-editor>
 *
 * Displays draggable 2D vectors rooted at the origin.
 *
 * Attributes:
 *   width, height: canvas size (default 300)
 *   range: world-space range (default 3, so axes run -3..3)
 *
 * API:
 *   setVectors([{x, y, color, label}, ...])
 *   getVectors() -> [{x, y}, ...]
 *
 * Events:
 *   change — fired when a drag ends. detail: { index, vector: {x, y} }
 */
class VectorEditor extends HTMLElement {
  static get observedAttributes() {
    return ["width", "height", "range", "writable"];
  }

  connectedCallback() {
    this.render();
    this.init();
  }

  get width() {
    return parseInt(this.getAttribute("width") || String(DEFAULT_SIZE), 10);
  }

  get height() {
    return parseInt(this.getAttribute("height") || String(DEFAULT_SIZE), 10);
  }

  get range() {
    return parseFloat(this.getAttribute("range") || String(DEFAULT_RANGE));
  }

  get writable() {
    const attr = this.getAttribute("writable");
    return attr === null ? true : attr !== "false";
  }

  render() {
    this.innerHTML = `
      <div class="vector-editor">
        <canvas width="${this.width}" height="${this.height}"></canvas>
      </div>
    `;
  }

  init() {
    this.canvas = this.querySelector("canvas");
    this.ctx = this.canvas.getContext("2d");
    this.vectors = [];
    this.overlay = [];
    this.dragIndex = null;

    if (this.writable) {
      this.canvas.addEventListener("mousedown", (e) => this.onDown(e));
      this.canvas.addEventListener("mousemove", (e) => this.onMove(e));
      window.addEventListener("mouseup", () => this.onUp());

      this.canvas.addEventListener("touchstart", (e) => this.onDown(e.touches[0]), { passive: false });
      this.canvas.addEventListener("touchmove", (e) => {
        e.preventDefault();
        this.onMove(e.touches[0]);
      }, { passive: false });
      window.addEventListener("touchend", () => this.onUp());
    }

    this.draw();
  }

  setVectors(vectors) {
    this.vectors = vectors.map((v) => ({ ...v }));
    this.draw();
  }

  getVectors() {
    return this.vectors.map((v) => ({ x: v.x, y: v.y }));
  }

  setOverlay(vectors) {
    this.overlay = vectors.map((v) => ({ ...v }));
    this.draw();
  }

  worldToPixel(wx, wy) {
    const halfW = this.width / 2;
    const halfH = this.height / 2;
    const sx = (wx / this.range) * halfW + halfW;
    const sy = -(wy / this.range) * halfH + halfH;
    return { x: sx, y: sy };
  }

  pixelToWorld(sx, sy) {
    const halfW = this.width / 2;
    const halfH = this.height / 2;
    const wx = ((sx - halfW) / halfW) * this.range;
    const wy = -((sy - halfH) / halfH) * this.range;
    return { x: wx, y: wy };
  }

  getPointerPos(event) {
    const rect = this.canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  onDown(event) {
    if (!this.writable) return;
    const pos = this.getPointerPos(event);
    const threshold = POINT_RADIUS + 4;
    for (let i = 0; i < this.vectors.length; i++) {
      const p = this.worldToPixel(this.vectors[i].x, this.vectors[i].y);
      const dx = p.x - pos.x;
      const dy = p.y - pos.y;
      if (dx * dx + dy * dy < threshold * threshold) {
        this.dragIndex = i;
        return;
      }
    }
  }

  onMove(event) {
    if (this.dragIndex === null) return;
    const pos = this.getPointerPos(event);
    const world = this.pixelToWorld(pos.x, pos.y);
    this.vectors[this.dragIndex].x = world.x;
    this.vectors[this.dragIndex].y = world.y;
    this.draw();
  }

  onUp() {
    if (this.dragIndex === null) return;
    const v = this.vectors[this.dragIndex];
    this.dispatchEvent(new CustomEvent("change", {
      detail: { index: this.dragIndex, vector: { x: v.x, y: v.y } },
      bubbles: true,
    }));
    this.dragIndex = null;
  }

  draw() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    ctx.clearRect(0, 0, w, h);

    // axes
    ctx.strokeStyle = AXIS_COLOR;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
    ctx.moveTo(w / 2, 0);
    ctx.lineTo(w / 2, h);
    ctx.stroke();

    // vectors
    for (let i = 0; i < this.vectors.length; i++) {
      const v = this.vectors[i];
      const end = this.worldToPixel(v.x, v.y);
      const color = v.color || "#B8A0FF";

      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(w / 2, h / 2);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();

      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(end.x, end.y, POINT_RADIUS, 0, Math.PI * 2);
      ctx.fill();

      if (v.label) {
        ctx.fillStyle = "rgba(255, 255, 255, 0.7)";
        ctx.font = "11px 'Space Grotesk', sans-serif";
        ctx.fillText(v.label, end.x + 8, end.y - 8);
      }
    }

    // overlay vectors (e.g. predictions) drawn dashed with white outline
    for (const v of this.overlay) {
      const end = this.worldToPixel(v.x, v.y);
      const color = v.color || "#B8A0FF";

      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(w / 2, h / 2);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(end.x, end.y, POINT_RADIUS, 0, Math.PI * 2);
      ctx.fill();

      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(end.x, end.y, POINT_RADIUS, 0, Math.PI * 2);
      ctx.stroke();

      if (v.label) {
        ctx.fillStyle = "rgba(255, 255, 255, 0.7)";
        ctx.font = "11px 'Space Grotesk', sans-serif";
        ctx.fillText(v.label, end.x + 8, end.y - 8);
      }
    }
  }
}

customElements.define("vector-editor", VectorEditor);
