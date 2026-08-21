"use strict";

import {
  clamp,
  makeCamera,
  cameraBasisFromAngles,
  projectPoint,
  screenToWorldPlane,
  screenToSupportPlane,
  rotationBetween,
  quatMultiply,
  pointSegmentDistance,
  add,
  scale as vecScale,
} from "./math3d.js";

const DEFAULT_WIDTH = 600;
const DEFAULT_HEIGHT = 600;
const DEFAULT_RANGE = 3;
const DEFAULT_BRUSH_RADIUS = 0.15;
const DEFAULT_PLANE_DEPTH_RATIO = 0.5;
const PLANE_SIZE_RATIO = 0.15;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.0;
const DEFAULT_SUPPORT_DISTANCE_RATIO = 0.75;
const AXIS_PICK_RADIUS = 12;

const COLORS = {
  white: "#FFFFFF",
  lavender: "#B8A0FF",
  sky: "#6BC4FF",
  mint: "#7FFFD4",
  red: "#FF0055",
};

const TOOL_CAMERA = "camera";
const TOOL_FREEHAND = "freehand";
const TOOL_SPHERE = "sphere";
const TOOL_ERASE = "erase";

/**
 * <draw-canvas-3d>
 *
 * A reusable 3D canvas component. Always supports rotate (drag) and zoom (wheel).
 * Optional drawing is enabled with the `drawable` attribute, which adds a toolbar,
 * a camera-facing drawing plane, and brush tools.
 *
 * Programmatic API:
 *   setData(primitives)   - replace the scene
 *   addPrimitive(p)       - append one primitive
 *   getData()             - return current primitives
 *   export()              - return serializable payload
 *   setCamera(theta, phi, zoom)
 *
 * Supported primitive types:
 *   { type: "point",   x, y, z, color, radius }
 *   { type: "sphere",  x, y, z, color, radius }
 *   { type: "capsule", x1, y1, z1, x2, y2, z2, color, radius }
 */
class DrawCanvas3D extends HTMLElement {
  static get observedAttributes() {
    return ["width", "height", "range", "drawable", "endpoint"];
  }

  connectedCallback() {
    this.render();
    this.init();
  }

  attributeChangedCallback() {
    this.render();
    this.init();
  }

  get width() {
    return parseInt(this.getAttribute("width") || String(DEFAULT_WIDTH), 10);
  }

  get height() {
    return parseInt(this.getAttribute("height") || String(DEFAULT_HEIGHT), 10);
  }

  get range() {
    return parseFloat(this.getAttribute("range") || String(DEFAULT_RANGE));
  }

  get drawable() {
    return this.hasAttribute("drawable");
  }

  get endpoint() {
    return this.getAttribute("endpoint") || "/api/drawing3d";
  }

  render() {
    const pencilIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>`;
    const circleIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg>`;
    const handIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 24c-3.26 0-6.19-1.99-7.8-5.02l-3.5-6.93C.8 10.96 1.37 9.5 2.81 8.94c1.42-.55 3.03.09 3.69 1.45l.87 1.74V3c0-1.66 1.34-3 3-3s3 1.34 3 3v6.18l.55-.11c1.45-.29 2.85.65 3.14 2.1l.86 4.31c.22 1.11-.5 2.19-1.61 2.41l-.19.04c-.3.06-.6.01-.86-.13A5.98 5.98 0 0 1 13 24z"/></svg>`;
    const eraseIcon = `<svg viewBox="0 0 299.289 299.289" aria-hidden="true"><path d="M278.755,110.357l-122.111,122.11l-89.833-89.833l122.11-122.111c5.374-5.374,14.071-5.374,19.446,0l70.388,70.388C284.129,96.285,284.129,104.983,278.755,110.357z" fill="currentColor"/><path d="M110.367,278.744c-5.374,5.373-14.071,5.373-19.446,0l-70.388-70.388c-5.373-5.374-5.375-14.071,0-19.446l34.61-34.61l89.834,89.834L110.367,278.744z" fill="none" stroke="currentColor" stroke-width="12"/></svg>`;
    const clearIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>`;

    const toolbar = this.drawable ? `
      <div class="dc3d-toolbar">
        <div class="dc3d-tools">
          <button class="dc3d-tool-btn active" data-tool="${TOOL_CAMERA}" title="camera">${handIcon}</button>
          <button class="dc3d-tool-btn" data-tool="${TOOL_FREEHAND}" title="freehand">${pencilIcon}</button>
          <button class="dc3d-tool-btn" data-tool="${TOOL_SPHERE}" title="sphere">${circleIcon}</button>
          <button class="dc3d-tool-btn" data-tool="${TOOL_ERASE}" title="erase">${eraseIcon}</button>
          <button class="dc3d-tool-btn" data-action="clear" title="clear">${clearIcon}</button>
        </div>
        <div class="dc3d-divider"></div>
        <div class="dc3d-colors">
          <div class="dc3d-color active" style="background: ${COLORS.lavender};" data-color="lavender"></div>
          <div class="dc3d-color" style="background: ${COLORS.sky};" data-color="sky"></div>
          <div class="dc3d-color" style="background: ${COLORS.mint};" data-color="mint"></div>
          <div class="dc3d-color" style="background: ${COLORS.white};" data-color="white"></div>
          <div class="dc3d-color" style="background: ${COLORS.red};" data-color="red"></div>
          <div class="dc3d-color dc3d-color-custom" data-color="custom">
            <input type="color" value="#B8A0FF">
          </div>
        </div>
        <div class="dc3d-divider"></div>
        <label class="dc3d-slider" title="brush radius">
          <span>r</span>
          <input type="range" class="dc3d-radius" min="1" max="50" value="15">
          <span class="dc3d-radius-value">0.15</span>
        </label>
        <div class="dc3d-divider"></div>
        <label class="dc3d-slider" title="plane depth">
          <span>d</span>
          <input type="range" class="dc3d-depth" min="5" max="100" value="25">
          <span class="dc3d-depth-value">1.50</span>
        </label>
      </div>
    ` : "";

    this.innerHTML = `
      <div class="draw-canvas-3d">
        ${toolbar}
        <div class="dc3d-canvas-wrap" style="width: ${this.width}px; height: ${this.height}px;">
          <canvas class="dc3d-canvas" width="${this.width}" height="${this.height}"></canvas>
          <canvas class="dc3d-grid-overlay" width="${this.width}" height="${this.height}"></canvas>
        </div>
      </div>
    `;
  }

  init() {
    this.canvas = this.querySelector(".dc3d-canvas");
    this.ctx = this.canvas.getContext("2d");
    this.gridCanvas = this.querySelector(".dc3d-grid-overlay");
    this.gridCtx = this.gridCanvas.getContext("2d");

    this.q = cameraBasisFromAngles(Math.PI / 4, Math.PI / 3, this.range);
    this.zoom = 1;
    this.planeDepth = this.range * DEFAULT_PLANE_DEPTH_RATIO;
    this.supportDistance = this.range * DEFAULT_SUPPORT_DISTANCE_RATIO;
    this.brushRadius = DEFAULT_BRUSH_RADIUS;

    this.currentTool = TOOL_CAMERA;
    this.currentColorKey = "lavender";
    this.customColor = COLORS.lavender;

    this.primitives = [];
    this.isDragging = false;
    this.lastMouse = { x: 0, y: 0 };
    this.dragStartPos = null;
    this.lastDrawPoint = null;
    this.hoveredAxis = null;

    this.drawGrid();
    this.bindEvents();
    this.draw();
  }

  getCamera() {
    return makeCamera(this.q, this.range);
  }

  currentColor() {
    return this.currentColorKey === "custom" ? this.customColor : COLORS[this.currentColorKey];
  }

  getPointerPos(event) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  bindEvents() {
    if (this.drawable) {
      this.querySelectorAll(".dc3d-tool-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (btn.dataset.action === "clear") {
            this.clear();
            return;
          }
          this.querySelectorAll(".dc3d-tool-btn").forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          this.currentTool = btn.dataset.tool;
          this.canvas.classList.toggle("tool-camera", this.currentTool === TOOL_CAMERA);
          this.hoveredAxis = null;
          this.draw();
        });
      });

      this.querySelectorAll(".dc3d-color[data-color]").forEach((swatch) => {
        if (swatch.dataset.color === "custom") return;
        swatch.addEventListener("click", () => {
          this.querySelectorAll(".dc3d-color").forEach((s) => s.classList.remove("active"));
          swatch.classList.add("active");
          this.currentColorKey = swatch.dataset.color;
        });
      });

      const colorInput = this.querySelector(".dc3d-color-custom input");
      colorInput.addEventListener("input", () => {
        this.customColor = colorInput.value;
        this.querySelector(".dc3d-color-custom").style.background = this.customColor;
        this.querySelectorAll(".dc3d-color").forEach((s) => s.classList.remove("active"));
        this.querySelector(".dc3d-color-custom").classList.add("active");
        this.currentColorKey = "custom";
      });

      const radiusInput = this.querySelector(".dc3d-radius");
      const radiusValue = this.querySelector(".dc3d-radius-value");
      radiusInput.addEventListener("input", () => {
        const v = parseInt(radiusInput.value, 10);
        this.brushRadius = this.range * (v / 100);
        radiusValue.textContent = this.brushRadius.toFixed(2);
        this.draw();
      });

      const depthInput = this.querySelector(".dc3d-depth");
      const depthValue = this.querySelector(".dc3d-depth-value");
      depthInput.addEventListener("input", () => {
        const v = parseInt(depthInput.value, 10);
        this.planeDepth = this.range * 2 * (v / 100);
        depthValue.textContent = this.planeDepth.toFixed(2);
        this.draw();
      });
    }

    this.canvas.addEventListener("mousedown", (e) => this.onPointerDown(e));
    this.canvas.addEventListener("mousemove", (e) => this.onHover(e));
    window.addEventListener("mousemove", (e) => this.onPointerMove(e));
    window.addEventListener("mouseup", () => this.onPointerUp());
    this.canvas.addEventListener("wheel", (e) => this.onWheel(e), { passive: false });

    this.canvas.addEventListener("touchstart", (e) => {
      e.preventDefault();
      this.onPointerDown(e.touches[0]);
    }, { passive: false });
    this.canvas.addEventListener("touchmove", (e) => {
      e.preventDefault();
      this.onPointerMove(e.touches[0]);
    }, { passive: false });
    this.canvas.addEventListener("touchend", () => this.onPointerUp());
  }

  onPointerDown(event) {
    event.preventDefault();
    const pos = this.getPointerPos(event);
    this.isDragging = true;
    this.lastMouse = pos;

    if (!this.drawable || this.currentTool === TOOL_CAMERA) {
      this.dragStartPos = pos;
      this.hoveredAxis = null;
      return;
    }

    const p = screenToWorldPlane(pos.x, pos.y, this.getCamera(), this.width, this.height, this.zoom, this.planeDepth);

    if (this.currentTool === TOOL_SPHERE) {
      this.addPrimitive({ type: "sphere", x: p[0], y: p[1], z: p[2], color: this.currentColor(), radius: this.brushRadius });
    } else if (this.currentTool === TOOL_FREEHAND || this.currentTool === TOOL_ERASE) {
      this.lastDrawPoint = p;
      if (this.currentTool === TOOL_ERASE) {
        this.eraseAt(p);
      }
    }
  }

  onPointerMove(event) {
    if (!this.isDragging) return;
    const pos = this.getPointerPos(event);

    if (!this.drawable || this.currentTool === TOOL_CAMERA) {
      if (!this.dragStartPos) return;
      const camera = this.getCamera();
      const va = screenToSupportPlane(
        this.dragStartPos.x, this.dragStartPos.y, camera, this.width, this.height, this.zoom, this.supportDistance
      );
      const vb = screenToSupportPlane(
        pos.x, pos.y, camera, this.width, this.height, this.zoom, this.supportDistance
      );
      // Rotate the camera by the inverse of the world-space rotation from va to vb.
      const rot = rotationBetween(vb, va);
      this.q = quatMultiply(rot, this.q);
      this.dragStartPos = pos;
      this.lastMouse = pos;
      this.draw();
      return;
    }

    const p = screenToWorldPlane(pos.x, pos.y, this.getCamera(), this.width, this.height, this.zoom, this.planeDepth);

    if (this.currentTool === TOOL_FREEHAND) {
      if (this.lastDrawPoint) {
        this.addPrimitive({
          type: "capsule",
          x1: this.lastDrawPoint[0], y1: this.lastDrawPoint[1], z1: this.lastDrawPoint[2],
          x2: p[0], y2: p[1], z2: p[2],
          color: this.currentColor(),
          radius: this.brushRadius,
        });
      }
      this.lastDrawPoint = p;
    } else if (this.currentTool === TOOL_ERASE) {
      this.eraseAt(p);
      this.lastDrawPoint = p;
    }
  }

  onPointerUp() {
    this.isDragging = false;
    this.dragStartPos = null;
    this.lastDrawPoint = null;
  }

  onHover(event) {
    if (!this.drawable) return;
    this.lastMouse = this.getPointerPos(event);
    if (this.currentTool === TOOL_CAMERA && !this.isDragging) {
      this.hoveredAxis = this.pickAxis(this.lastMouse);
    }
    this.draw();
  }

  onWheel(event) {
    event.preventDefault();
    const delta = event.deltaY > 0 ? 0.9 : 1.1;
    this.zoom = clamp(this.zoom * delta, MIN_ZOOM, MAX_ZOOM);
    this.draw();
  }

  eraseAt(p) {
    const threshold = this.brushRadius * 1.2;
    this.primitives = this.primitives.filter((prim) => {
      if (prim.type === "point" || prim.type === "sphere") {
        const dx = prim.x - p[0];
        const dy = prim.y - p[1];
        const dz = prim.z - p[2];
        return Math.sqrt(dx * dx + dy * dy + dz * dz) > threshold;
      }
      if (prim.type === "capsule") {
        const a = [prim.x1, prim.y1, prim.z1];
        const b = [prim.x2, prim.y2, prim.z2];
        return pointSegmentDistance(p, a, b) > threshold;
      }
      return true;
    });
    this.draw();
  }

  // ---- Public API ----

  setData(primitives) {
    this.primitives = Array.from(primitives);
    this.draw();
  }

  addPrimitive(primitive) {
    this.primitives.push(primitive);
    this.draw();
  }

  getData() {
    return this.primitives.slice();
  }

  clear() {
    this.primitives = [];
    this.draw();
  }

  setCamera(theta, phi, zoom) {
    this.q = cameraBasisFromAngles(theta, phi, this.range);
    this.zoom = zoom;
    this.draw();
  }

  export() {
    return {
      type: "draw-canvas-3d",
      range: [-this.range, this.range],
      primitives: this.primitives,
      timestamp: Date.now(),
    };
  }

  // ---- Rendering ----

  drawGrid() {
    const ctx = this.gridCtx;
    const w = this.width;
    const h = this.height;
    const camera = this.getCamera();
    const scale = this.zoom * Math.min(w, h) / (2 * this.range);

    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.14)";
    ctx.lineWidth = 1;

    // World-space grid planes at z = -range, 0, range.
    for (const z of [-this.range, 0, this.range]) {
      for (let i = -this.range; i <= this.range; i += 1) {
        this.drawGridLine(ctx, [-this.range, i, z], [this.range, i, z], camera, scale);
        this.drawGridLine(ctx, [i, -this.range, z], [i, this.range, z], camera, scale);
      }
    }

    // Axes: x=red, y=green, z=blue.
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = "rgba(255, 80, 80, 0.85)";
    this.drawGridLine(ctx, [-this.range, 0, 0], [this.range, 0, 0], camera, scale);
    ctx.strokeStyle = "rgba(80, 255, 128, 0.85)";
    this.drawGridLine(ctx, [0, -this.range, 0], [0, this.range, 0], camera, scale);
    ctx.strokeStyle = "rgba(80, 160, 255, 0.85)";
    this.drawGridLine(ctx, [0, 0, -this.range], [0, 0, this.range], camera, scale);
  }

  drawGridLine(ctx, a, b, camera, scale) {
    const pa = projectPoint(a, camera, this.width, this.height, this.zoom);
    const pb = projectPoint(b, camera, this.width, this.height, this.zoom);
    if (!pa || !pb) return;
    ctx.beginPath();
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
    ctx.stroke();
  }

  draw() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    const camera = this.getCamera();
    const scale = this.zoom * Math.min(w, h) / (2 * this.range);

    this.drawGrid();
    ctx.clearRect(0, 0, w, h);

    const commands = [];

    // Drawing plane.
    if (this.drawable) {
      this.collectPlaneCommands(commands, camera, scale);
    }

    // Primitives.
    for (const prim of this.primitives) {
      this.collectPrimitiveCommands(commands, prim, camera, scale);
    }

    // Sort back-to-front by camera-space depth (larger depth = farther).
    commands.sort((a, b) => b.z - a.z);
    for (const cmd of commands) {
      cmd.draw(ctx);
    }

    // Axis endpoint handles (drawn on top so they're always reachable).
    if (this.drawable && this.currentTool === TOOL_CAMERA) {
      this.drawAxisHandles(ctx, camera);
    }

    // Brush cursor on plane.
    if (this.drawable && this.currentTool !== TOOL_CAMERA && this.lastMouse) {
      this.drawBrushCursor(ctx, camera, scale);
    }

    // Cursor state.
    if (this.drawable) {
      this.canvas.classList.toggle("tool-camera", this.currentTool === TOOL_CAMERA);
      this.canvas.classList.toggle("axis-hovered", this.hoveredAxis !== null);
    }
  }

  collectPlaneCommands(commands, camera, scale) {
    const d = this.planeDepth;
    const half = (this.range * PLANE_SIZE_RATIO) / 2;

    // Fixed-size plane centered on the view ray at depth d, always facing the camera.
    const center = add(camera.pos, vecScale(camera.viewDir, d));
    const right = vecScale(camera.right, half);
    const up = vecScale(camera.up, half);

    const corners = [
      add(add(center, vecScale(right, -1)), vecScale(up, -1)),
      add(add(center, right), vecScale(up, -1)),
      add(add(center, right), up),
      add(add(center, vecScale(right, -1)), up),
    ];

    const projected = corners.map((p) => projectPoint(p, camera, this.width, this.height, this.zoom));
    if (projected.some((p) => p === null)) return;

    const avgZ = projected.reduce((sum, p) => sum + p.z, 0) / projected.length;

    commands.push({
      z: avgZ,
      draw: (ctx) => {
        ctx.fillStyle = "rgba(127, 255, 212, 0.22)";
        ctx.strokeStyle = "rgba(127, 255, 212, 0.90)";
        ctx.lineWidth = 2.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(projected[0].x, projected[0].y);
        for (let i = 1; i < projected.length; i++) {
          ctx.lineTo(projected[i].x, projected[i].y);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.setLineDash([]);
      },
    });
  }

  collectPrimitiveCommands(commands, prim, camera, scale) {
    if (prim.type === "point" || prim.type === "sphere") {
      const p = projectPoint([prim.x, prim.y, prim.z], camera, this.width, this.height, this.zoom);
      if (!p) return;
      const r = prim.radius * scale;
      commands.push({
        z: p.z,
        draw: (ctx) => {
          ctx.fillStyle = prim.color;
          ctx.beginPath();
          ctx.arc(p.x, p.y, Math.max(1, r), 0, Math.PI * 2);
          ctx.fill();
          if (prim.type === "sphere") {
            ctx.strokeStyle = "rgba(255,255,255,0.25)";
            ctx.lineWidth = 1;
            ctx.stroke();
          }
        },
      });
    } else if (prim.type === "capsule") {
      const a = projectPoint([prim.x1, prim.y1, prim.z1], camera, this.width, this.height, this.zoom);
      const b = projectPoint([prim.x2, prim.y2, prim.z2], camera, this.width, this.height, this.zoom);
      if (!a || !b) return;
      const avgZ = (a.z + b.z) / 2;
      const r = prim.radius * scale;

      commands.push({
        z: avgZ,
        draw: (ctx) => {
          ctx.strokeStyle = prim.color;
          ctx.lineWidth = Math.max(2, r * 2);
          ctx.lineCap = "round";
          ctx.lineJoin = "round";
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        },
      });
    }
  }

  pickAxis(mousePos) {
    const camera = this.getCamera();
    const endpoints = [
      { axis: "x", pos: [this.range, 0, 0] },
      { axis: "y", pos: [0, this.range, 0] },
      { axis: "z", pos: [0, 0, this.range] },
    ];
    let best = null;
    let bestDist = AXIS_PICK_RADIUS;
    for (const ep of endpoints) {
      const p = projectPoint(ep.pos, camera, this.width, this.height, this.zoom);
      if (!p) continue;
      const dx = p.x - mousePos.x;
      const dy = p.y - mousePos.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < bestDist) {
        bestDist = dist;
        best = ep.axis;
      }
    }
    return best;
  }

  drawAxisHandles(ctx, camera) {
    const endpoints = [
      { axis: "x", pos: [this.range, 0, 0], color: "rgba(255, 80, 80, 0.85)" },
      { axis: "y", pos: [0, this.range, 0], color: "rgba(80, 255, 128, 0.85)" },
      { axis: "z", pos: [0, 0, this.range], color: "rgba(80, 160, 255, 0.85)" },
    ];
    for (const ep of endpoints) {
      const p = projectPoint(ep.pos, camera, this.width, this.height, this.zoom);
      if (!p) continue;
      const isHovered = this.hoveredAxis === ep.axis;
      const r = isHovered ? 8 : 5;
      ctx.fillStyle = ep.color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();
      if (isHovered) {
        ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }
  }

  drawBrushCursor(ctx, camera, scale) {
    const r = this.brushRadius * scale;

    ctx.strokeStyle = this.currentColor();
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(this.lastMouse.x, this.lastMouse.y, Math.max(2, r), 0, Math.PI * 2);
    ctx.stroke();
  }
}

customElements.define("draw-canvas-3d", DrawCanvas3D);
