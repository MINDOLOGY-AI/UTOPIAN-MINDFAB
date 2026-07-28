// === fab-edges: intvrpviz-style orthogonal routing, rotated for left-to-right flow ===
//
// ported from intvrpviz/back/routing.py:
// - edges exit/enter through ports spread evenly along the node border facing the other node
// - same row/column: straight line for border (extreme-port) edges, small jog near target for inner edges
// - otherwise: 6-point path via a lane next to the target
// horizontal flow: exit right / enter left for forward edges, mirrored for backward edges.
// vertical pairs (overlapping x-spans) use the original unrotated logic.

const FAB_MARGIN = 20;

function computeRoutes(store) {
  const rects = {};
  for (const [id, n] of Object.entries(store.nodes)) {
    if (store.isVisible(n)) rects[id] = store.nodeRect(n);
  }
  const edges = Object.values(store.edges).filter(e => rects[e.source] && rects[e.target]);
  const center = (r) => ({x: r.x + r.w / 2, y: r.y + r.h / 2});

  // ---- classify edges + collect port lists per node per side ----
  // exitSide/enterSide: which border each edge leaves/enters through
  const outLists = {}; // nodeId -> {side: [eid, ...]}
  const inLists = {};
  const push = (map, id, side, eid) => {
    (map[id] = map[id] || {})[side] = (map[id][side] || []);
    map[id][side].push(eid);
  };

  for (const e of edges) {
    const sr = rects[e.source], tr = rects[e.target];
    const sc = center(sr), tc = center(tr);
    const xOverlap = Math.min(sr.x + sr.w, tr.x + tr.w) - Math.max(sr.x, tr.x);
    if (xOverlap > 0) {
      // vertical pair: exit bottom/top of the upper node, enter top/bottom of the lower
      if (sc.y <= tc.y) {
        push(outLists, e.source, "bottom", e.id);
        push(inLists, e.target, "top", e.id);
      } else {
        push(outLists, e.source, "top", e.id);
        push(inLists, e.target, "bottom", e.id);
      }
    } else if (sc.x <= tc.x) {
      push(outLists, e.source, "right", e.id);
      push(inLists, e.target, "left", e.id);
    } else {
      push(outLists, e.source, "left", e.id);
      push(inLists, e.target, "right", e.id);
    }
  }

  // ---- sort port lists and assign coordinates (spread evenly along the border) ----
  const srcPort = {}; // eid -> {x, y}
  const dstPort = {};
  const edgeById = {};
  for (const e of edges) edgeById[e.id] = e;

  const sortExit = (eids, nodeId, axis) =>
    eids.sort((a, b) => {
      const ca = center(rects[edgeById[a].target]), cb = center(rects[edgeById[b].target]);
      if (axis === "y") return ca.y - cb.y || cb.x - ca.x; // closer dest = upper port
      return ca.x - cb.x || cb.y - ca.y;
    });
  const sortEnter = (eids, nodeId, axis) =>
    eids.sort((a, b) => {
      const ca = center(rects[edgeById[a].source]), cb = center(rects[edgeById[b].source]);
      if (axis === "y") return ca.y - cb.y || ca.x - cb.x;
      return ca.x - cb.x || ca.y - cb.y;
    });

  for (const [nodeId, sides] of Object.entries(outLists)) {
    const r = rects[nodeId];
    for (const [side, eids] of Object.entries(sides)) {
      sortExit(eids, nodeId, side === "left" || side === "right" ? "y" : "x");
      const step = (side === "left" || side === "right" ? r.h : r.w) / (eids.length + 1);
      eids.forEach((eid, i) => {
        if (side === "right") srcPort[eid] = {x: r.x + r.w, y: r.y + step * (i + 1)};
        if (side === "left") srcPort[eid] = {x: r.x, y: r.y + step * (i + 1)};
        if (side === "bottom") srcPort[eid] = {x: r.x + step * (i + 1), y: r.y + r.h};
        if (side === "top") srcPort[eid] = {x: r.x + step * (i + 1), y: r.y};
      });
    }
  }
  for (const [nodeId, sides] of Object.entries(inLists)) {
    const r = rects[nodeId];
    for (const [side, eids] of Object.entries(sides)) {
      sortEnter(eids, nodeId, side === "left" || side === "right" ? "y" : "x");
      const step = (side === "left" || side === "right" ? r.h : r.w) / (eids.length + 1);
      eids.forEach((eid, i) => {
        if (side === "left") dstPort[eid] = {x: r.x, y: r.y + step * (i + 1)};
        if (side === "right") dstPort[eid] = {x: r.x + r.w, y: r.y + step * (i + 1)};
        if (side === "top") dstPort[eid] = {x: r.x + step * (i + 1), y: r.y};
        if (side === "bottom") dstPort[eid] = {x: r.x + step * (i + 1), y: r.y + r.h};
      });
    }
  }

  // ---- route each edge ----
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const spansOverlap = (a, ah, b, bh) => Math.min(a + ah, b + bh) - Math.max(a, b);
  const routes = {};

  for (const e of edges) {
    const sr = rects[e.source], tr = rects[e.target];
    const sp = srcPort[e.id], dp = dstPort[e.id];
    const outSide = Object.keys(outLists[e.source]).find(s => outLists[e.source][s].includes(e.id));
    const horizontal = outSide === "right" || outSide === "left";
    const outList = outLists[e.source][outSide];
    const inSide = horizontal ? (outSide === "right" ? "left" : "right") : (outSide === "bottom" ? "top" : "bottom");
    const inList = inLists[e.target][inSide];

    if (horizontal) {
      const sameRow = spansOverlap(sr.y, sr.h, tr.y, tr.h) > 0;
      if (sameRow) {
        const isFirst = outList[0] === e.id && inList[0] === e.id;
        const isLast = outList[outList.length - 1] === e.id && inList[inList.length - 1] === e.id;
        if (isFirst || isLast) {
          // border edge: straight horizontal through the shared span
          const lo = Math.max(sr.y, tr.y), hi = Math.min(sr.y + sr.h, tr.y + tr.h);
          const y = clamp(isFirst ? Math.min(sp.y, dp.y) : Math.max(sp.y, dp.y), lo, hi);
          routes[e.id] = [{x: sp.x, y}, {x: dp.x, y}];
        } else {
          // inner edge: small jog just outside the target
          const midX = outSide === "right" ? dp.x - FAB_MARGIN : dp.x + FAB_MARGIN;
          routes[e.id] = [{x: sp.x, y: sp.y}, {x: midX, y: sp.y}, {x: midX, y: dp.y}, {x: dp.x, y: dp.y}];
        }
      } else {
        // 6-point path via a horizontal lane next to the target row
        const turnX1 = outSide === "right" ? sp.x + FAB_MARGIN : sp.x - FAB_MARGIN;
        const turnX2 = outSide === "right" ? dp.x - FAB_MARGIN : dp.x + FAB_MARGIN;
        const laneY = sp.y < dp.y ? tr.y - FAB_MARGIN : tr.y + tr.h + FAB_MARGIN;
        routes[e.id] = [
          {x: sp.x, y: sp.y},
          {x: turnX1, y: sp.y},
          {x: turnX1, y: laneY},
          {x: turnX2, y: laneY},
          {x: turnX2, y: dp.y},
          {x: dp.x, y: dp.y},
        ];
      }
    } else {
      // vertical pair — the original intvrpviz logic, unrotated
      const isFirst = outList[0] === e.id && inList[0] === e.id;
      const isLast = outList[outList.length - 1] === e.id && inList[inList.length - 1] === e.id;
      if (isFirst || isLast) {
        const lo = Math.max(sr.x, tr.x), hi = Math.min(sr.x + sr.w, tr.x + tr.w);
        const x = clamp(isFirst ? Math.min(sp.x, dp.x) : Math.max(sp.x, dp.x), lo, hi);
        routes[e.id] = [{x, y: sp.y}, {x, y: dp.y}];
      } else {
        const midY = outSide === "bottom" ? dp.y - FAB_MARGIN : dp.y + FAB_MARGIN;
        routes[e.id] = [{x: sp.x, y: sp.y}, {x: sp.x, y: midY}, {x: dp.x, y: midY}, {x: dp.x, y: dp.y}];
      }
    }
  }

  return routes;
}

class FabEdge {
  constructor(board, edge) {
    this.board = board;
    this.store = board.store;
    this.edge = edge;
    this.el = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    this.el.classList.add("edge");
    this.el.dataset.id = edge.id;
    this.arrow = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    this.arrow.classList.add("edge-arrow");
    this.el.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      board.selectEdge(edge.id);
    });
    board.svg.appendChild(this.el);
    board.svg.appendChild(this.arrow);
  }

  update() {
    const pts = (this.board.routes || {})[this.edge.id];
    if (!pts || pts.length < 2) {
      this.el.setAttribute("points", "");
      this.arrow.setAttribute("points", "");
      return;
    }
    this.el.setAttribute("points", pts.map(p => `${p.x},${p.y}`).join(" "));
    const [a, b] = [pts[pts.length - 2], pts[pts.length - 1]];
    const size = 5;
    if (Math.abs(b.x - a.x) < 0.001) {
      const off = b.y > a.y ? -size * 1.6 : size * 1.6;
      this.arrow.setAttribute("points", `${b.x},${b.y} ${b.x - size},${b.y + off} ${b.x + size},${b.y + off}`);
    } else {
      const off = b.x > a.x ? -size * 1.6 : size * 1.6;
      this.arrow.setAttribute("points", `${b.x},${b.y} ${b.x + off},${b.y - size} ${b.x + off},${b.y + size}`);
    }
    const selected = this.store.selectedEdgeId === this.edge.id;
    this.el.classList.toggle("selected", selected);
    this.arrow.classList.toggle("selected", selected);
  }

  remove() {
    this.el.remove();
    this.arrow.remove();
  }
}
