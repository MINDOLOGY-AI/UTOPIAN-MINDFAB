// === graph-router: Manhattan edge routing (intvrpviz-style lanes) ===
//
// Wires leave a node through the middle of the side facing the target, travel
// in the gutters between grid cells, and enter the target through the middle
// of the facing side.  Vertical lanes run alongside target columns; horizontal
// lanes run alongside target rows.  Same-row/same-column pairs get a straight
// segment when nothing sits between them.

class GraphRouter {
  constructor(store) {
    this.store = store;
  }

  route(edge) {
    const s = this.store.nodes[edge.source];
    const t = this.store.nodes[edge.target];
    if (!s || !t) return null;

    const sr = this.store.nodeRect(s);
    const tr = this.store.nodeRect(t);
    return this.connect(edge.source, sr, edge.target, tr);
  }

  connect(sourceId, sr, targetId, tr) {
    const G = GraphStore.GRID_SIZE;
    const M = GraphStore.NODE_MARGIN;

    const sc = {x: sr.x + sr.w / 2, y: sr.y + sr.h / 2};
    const tc = {x: tr.x + tr.w / 2, y: tr.y + tr.h / 2};
    const dx = tc.x - sc.x;
    const dy = tc.y - sc.y;
    const adx = Math.abs(dx);
    const ady = Math.abs(dy);

    // ---- same row: straight horizontal if clear, else lane above ----
    if (ady < G / 2) {
      const y = sc.y;
      if (!this.nodeBetween(sourceId, targetId, "x")) {
        if (dx > 0) {
          return [{x: sr.x + sr.w, y}, {x: tr.x, y}];
        }
        return [{x: sr.x, y}, {x: tr.x + tr.w, y}];
      }
      const laneY = Math.min(sr.y, tr.y) - M;
      return this.simplify([
        {x: sc.x, y},
        {x: sc.x, y: laneY},
        {x: tc.x, y: laneY},
        {x: tc.x, y}
      ]);
    }

    // ---- same column: straight vertical if clear, else lane to the left ----
    if (adx < G / 2) {
      const x = sc.x;
      if (!this.nodeBetween(sourceId, targetId, "y")) {
        if (dy > 0) {
          return [{x, y: sr.y + sr.h}, {x, y: tr.y}];
        }
        return [{x, y: sr.y}, {x, y: tr.y + tr.h}];
      }
      const laneX = Math.min(sr.x, tr.x) - M;
      return this.simplify([
        {x, y: sc.y},
        {x: laneX, y: sc.y},
        {x: laneX, y: tc.y},
        {x, y: tc.y}
      ]);
    }

    // ---- diagonal: choose dominant axis ----
    if (ady >= adx) {
      // vertically dominant: exit top/bottom, use a vertical lane next to target column
      const sx = sc.x;
      const ex = tc.x;
      let sy, ey, laneY, turnYSrc, turnYDst;

      if (dy > 0) {
        // target below source: leave bottom, enter top
        sy = sr.y + sr.h;
        ey = tr.y;
        turnYSrc = sy + M;
        turnYDst = ey - M;
      } else {
        // target above source: leave top, enter bottom
        sy = sr.y;
        ey = tr.y + tr.h;
        turnYSrc = sy - M;
        turnYDst = ey + M;
      }

      // vertical lane to the left of a rightward target, right of a leftward one
      const laneX = dx > 0 ? tr.x - M : tr.x + tr.w + M;

      return this.simplify([
        {x: sx, y: sy},
        {x: sx, y: turnYSrc},
        {x: laneX, y: turnYSrc},
        {x: laneX, y: turnYDst},
        {x: ex, y: turnYDst},
        {x: ex, y: ey}
      ]);
    }

    // horizontally dominant: exit left/right, use a horizontal lane next to target row
    const sy = sc.y;
    const ey = tc.y;
    let sx, ex, laneX, turnXSrc, turnXDst;

    if (dx > 0) {
      // target to the right: leave right, enter left
      sx = sr.x + sr.w;
      ex = tr.x;
      turnXSrc = sx + M;
      turnXDst = ex - M;
    } else {
      // target to the left: leave left, enter right
      sx = sr.x;
      ex = tr.x + tr.w;
      turnXSrc = sx - M;
      turnXDst = ex + M;
    }

    // horizontal lane above a downward target, below an upward one
    const laneY = dy > 0 ? tr.y - M : tr.y + tr.h + M;

    return this.simplify([
      {x: sx, y: sy},
      {x: turnXSrc, y: sy},
      {x: turnXSrc, y: laneY},
      {x: turnXDst, y: laneY},
      {x: turnXDst, y: ey},
      {x: ex, y: ey}
    ]);
  }

  nodeBetween(sourceId, targetId, axis) {
    const sr = this.store.nodeRect(this.store.nodes[sourceId]);
    const tr = this.store.nodeRect(this.store.nodes[targetId]);

    for (const node of Object.values(this.store.nodes)) {
      if (node.id === sourceId || node.id === targetId) continue;
      if (!this.store.isVisible(node)) continue;
      if (node.type === "folder" && node.expanded) continue;

      const r = this.store.nodeRect(node);
      if (axis === "x") {
        // any visible node whose vertical span overlaps the row and whose x range
        // lies between the source and target
        if (r.y >= sr.y + sr.h || r.y + r.h <= sr.y) continue;
        const left = Math.min(sr.x, tr.x);
        const right = Math.max(sr.x + sr.w, tr.x + tr.w);
        if (r.x < right && r.x + r.w > left) return true;
      } else {
        if (r.x >= sr.x + sr.w || r.x + r.w <= sr.x) continue;
        const top = Math.min(sr.y, tr.y);
        const bottom = Math.max(sr.y + sr.h, tr.y + tr.h);
        if (r.y < bottom && r.y + r.h > top) return true;
      }
    }
    return false;
  }

  simplify(points) {
    // drop collinear intermediate points and duplicates
    const out = [points[0]];
    for (let i = 1; i < points.length - 1; i++) {
      const a = out[out.length - 1], b = points[i], c = points[i + 1];
      const sameX = (a.x === b.x && b.x === c.x);
      const sameY = (a.y === b.y && b.y === c.y);
      if (!sameX && !sameY) out.push(b);
    }
    out.push(points[points.length - 1]);
    return out.filter((p, i) => i === 0 || p.x !== out[i - 1].x || p.y !== out[i - 1].y);
  }
}
