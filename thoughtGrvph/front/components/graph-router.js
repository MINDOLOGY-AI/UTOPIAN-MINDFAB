// === graph-router: Manhattan edge routing through grid cells ===

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
    const sc = {x: sr.x + sr.w / 2, y: sr.y + sr.h / 2};
    const tc = {x: tr.x + tr.w / 2, y: tr.y + tr.h / 2};

    const sSide = this.sideToward(sr, tc);
    const tSide = this.sideToward(tr, sc);

    // build port index for spreading multiple edges on the same side
    const ports = this.buildPortIndex();
    const sp = this.portPoint(sr, sSide, edge.source, edge.target, ports);
    const tp = this.portPoint(tr, tSide, edge.target, edge.source, ports);

    return this.connect(sp, sSide, tp, tSide);
  }

  sideToward(rect, targetCenter) {
    const cx = rect.x + rect.w / 2;
    const cy = rect.y + rect.h / 2;
    const dx = targetCenter.x - cx;
    const dy = targetCenter.y - cy;
    if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? "right" : "left";
    return dy > 0 ? "bottom" : "top";
  }

  buildPortIndex() {
    // {nodeId: {side: [edgeId, ...]}}
    const idx = {};
    for (const edge of Object.values(this.store.edges)) {
      const s = this.store.nodes[edge.source];
      const t = this.store.nodes[edge.target];
      if (!s || !t) continue;
      const sr = this.store.nodeRect(s);
      const tr = this.store.nodeRect(t);
      const sc = {x: sr.x + sr.w / 2, y: sr.y + sr.h / 2};
      const tc = {x: tr.x + tr.w / 2, y: tr.y + tr.h / 2};
      const sSide = this.sideToward(sr, tc);
      const tSide = this.sideToward(tr, sc);
      if (!idx[s.id]) idx[s.id] = {};
      if (!idx[t.id]) idx[t.id] = {};
      if (!idx[s.id][sSide]) idx[s.id][sSide] = [];
      if (!idx[t.id][tSide]) idx[t.id][tSide] = [];
      idx[s.id][sSide].push(edge.id);
      idx[t.id][tSide].push(edge.id);
    }
    return idx;
  }

  portPoint(rect, side, nodeId, otherNodeId, ports) {
    const sideEdges = (ports[nodeId] && ports[nodeId][side]) || [""];
    const others = sideEdges.map(eid => {
      const edge = this.store.edges[eid];
      if (!edge) return null;
      const oid = edge.source === nodeId ? edge.target : edge.source;
      const n = this.store.nodes[oid];
      if (!n) return null;
      const r = this.store.nodeRect(n);
      return {id: eid, oid, center: {x: r.x + r.w / 2, y: r.y + r.h / 2}};
    }).filter(Boolean);

    // sort by position along the side
    others.sort((a, b) => (side === "left" || side === "right") ? a.center.y - b.center.y : a.center.x - b.center.x);
    const idx = Math.max(0, others.findIndex(o => o.oid === otherNodeId));
    const n = others.length || 1;
    const i = others.length ? idx : 0;

    if (side === "top") {
      const step = rect.w / (n + 1);
      return {x: rect.x + step * (i + 1), y: rect.y};
    }
    if (side === "bottom") {
      const step = rect.w / (n + 1);
      return {x: rect.x + step * (i + 1), y: rect.y + rect.h};
    }
    if (side === "left") {
      const step = rect.h / (n + 1);
      return {x: rect.x, y: rect.y + step * (i + 1)};
    }
    const step = rect.h / (n + 1);
    return {x: rect.x + rect.w, y: rect.y + step * (i + 1)};
  }

  connect(sp, sSide, tp, tSide) {
    const points = [sp];

    // opposite sides on same axis -> straight with one bend in the middle of the lane
    if ((sSide === "right" && tSide === "left") || (sSide === "left" && tSide === "right")) {
      const midX = (sp.x + tp.x) / 2;
      points.push({x: midX, y: sp.y}, {x: midX, y: tp.y});
    } else if ((sSide === "top" && tSide === "bottom") || (sSide === "bottom" && tSide === "top")) {
      const midY = (sp.y + tp.y) / 2;
      points.push({x: sp.x, y: midY}, {x: tp.x, y: midY});
    } else {
      // L-shape via target's axis
      if (sSide === "right" || sSide === "left") {
        points.push({x: tp.x, y: sp.y});
      } else {
        points.push({x: sp.x, y: tp.y});
      }
    }

    points.push(tp);
    // remove consecutive duplicates
    return points.filter((p, i) => i === 0 || p.x !== points[i - 1].x || p.y !== points[i - 1].y);
  }
}
