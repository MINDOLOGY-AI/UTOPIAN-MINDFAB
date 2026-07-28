"use strict";

const DEFAULT_SIZE = 300;
const DEFAULT_RANGE = 3;

class Surface3D extends HTMLElement {
  static get observedAttributes() {
    return ["width", "height", "range", "zmax"];
  }

  connectedCallback() {
    this.render();
    if (this.pendingData) {
      this.setData(this.pendingData.x, this.pendingData.y, this.pendingData.z);
      this.pendingData = null;
    }
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

  get zmax() {
    const v = parseFloat(this.getAttribute("zmax"));
    return isFinite(v) ? v : null;
  }

  render() {
    this.innerHTML = `
      <div class="surface-3d">
        <canvas width="${this.width}" height="${this.height}"></canvas>
      </div>
    `;
    this.canvas = this.querySelector("canvas");
    this.ctx = this.canvas.getContext("2d");
  }

  setData(xGrid, yGrid, zGrid) {
    this.xGrid = xGrid;
    this.yGrid = yGrid;
    this.zGrid = zGrid;
    if (!this.isConnected) {
      this.pendingData = { x: xGrid, y: yGrid, z: zGrid };
      return;
    }
    this.draw();
  }

  project(p) {
    // isometric-ish view: rotate 45 around z, 30 around x
    const rz = Math.PI / 4;
    const rx = Math.PI / 6;

    let x = p[0], y = p[1], z = p[2];

    // rotate around z
    let x1 = x * Math.cos(rz) - y * Math.sin(rz);
    let y1 = x * Math.sin(rz) + y * Math.cos(rz);
    let z1 = z;

    // rotate around x
    let y2 = y1 * Math.cos(rx) - z1 * Math.sin(rx);
    let z2 = y1 * Math.sin(rx) + z1 * Math.cos(rx);
    let x2 = x1;

    const scale = Math.min(this.width, this.height) / (2.8 * this.range);
    return {
      x: this.width / 2 + scale * x2,
      y: this.height / 2 - scale * y2,
      z: z2,
    };
  }

  drawLine3D(a, b, color, width = 1) {
    const ctx = this.ctx;
    const pa = this.project(a);
    const pb = this.project(b);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
    ctx.stroke();
  }

  draw() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    ctx.clearRect(0, 0, w, h);

    if (!this.zGrid || this.zGrid.length === 0) return;

    const rows = this.zGrid.length;
    const cols = this.zGrid[0].length;
    const R = this.range;

    let minZ = Infinity, maxZ = -Infinity;
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const z = this.zGrid[i][j];
        if (z < minZ) minZ = z;
        if (z > maxZ) maxZ = z;
      }
    }
    if (!isFinite(minZ)) { minZ = 0; maxZ = 1; }
    if (this.zmax !== null) maxZ = Math.max(maxZ, this.zmax);
    if (minZ === maxZ) { minZ -= 1; maxZ += 1; }

    // base square at z = 0
    const base = [
      [-R, -R, 0], [R, -R, 0], [R, R, 0], [-R, R, 0],
    ];
    ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    const p0 = this.project(base[0]);
    ctx.moveTo(p0.x, p0.y);
    for (let k = 1; k < base.length; k++) {
      const p = this.project(base[k]);
      ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();
    ctx.stroke();

    // axes
    this.drawLine3D([-R, 0, 0], [R, 0, 0], "rgba(255,255,255,0.25)");
    this.drawLine3D([0, -R, 0], [0, R, 0], "rgba(255,255,255,0.25)");
    this.drawLine3D([0, 0, 0], [0, 0, maxZ], "rgba(255,255,255,0.25)");

    // build quads back-to-front by projected depth
    const quads = [];
    for (let i = 0; i < rows - 1; i++) {
      for (let j = 0; j < cols - 1; j++) {
        const corners = [
          [this.xGrid[i][j], this.yGrid[i][j], this.zGrid[i][j]],
          [this.xGrid[i][j + 1], this.yGrid[i][j + 1], this.zGrid[i][j + 1]],
          [this.xGrid[i + 1][j + 1], this.yGrid[i + 1][j + 1], this.zGrid[i + 1][j + 1]],
          [this.xGrid[i + 1][j], this.yGrid[i + 1][j], this.zGrid[i + 1][j]],
        ];
        const proj = corners.map((c) => this.project(c));
        const avgZ = proj.reduce((s, p) => s + p.z, 0) / proj.length;
        quads.push({ proj, avgZ });
      }
    }

    quads.sort((a, b) => a.avgZ - b.avgZ);

    for (const q of quads) {
      ctx.fillStyle = "rgba(184, 160, 255, 0.35)";
      ctx.strokeStyle = "rgba(184, 160, 255, 0.7)";
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(q.proj[0].x, q.proj[0].y);
      for (let k = 1; k < q.proj.length; k++) {
        ctx.lineTo(q.proj[k].x, q.proj[k].y);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
  }
}

customElements.define("surface-3d", Surface3D);
