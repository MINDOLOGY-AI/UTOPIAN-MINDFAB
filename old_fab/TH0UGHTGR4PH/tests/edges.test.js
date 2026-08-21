// Edge routing unit tests for computeRoutes.
// Run from repo root: node fab/TH0UGHTGR4PH/tests/edges.test.js

const {computeRoutes} = require("../front/edges.js");

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  ok  ${name}`);
  } catch (e) {
    failed++;
    console.log(` FAIL ${name}`);
    console.log(`       ${e.message}`);
  }
}

function eq(a, b, msg) {
  if (a !== b) throw new Error(`${msg} (${a} !== ${b})`);
}

// stub store: computeRoutes only needs nodes, edges, isVisible, nodeRect
function makeStore(rects, edges) {
  const nodes = {};
  for (const [id, r] of Object.entries(rects)) nodes[id] = {id};
  return {
    nodes,
    edges,
    isVisible: () => true,
    nodeRect: (n) => rects[n.id],
  };
}

// ---------------------------------------------------------------------------

test("same-row single edge is a straight line", () => {
  const s = makeStore(
    {a: {x: 0, y: 0, w: 160, h: 160}, b: {x: 400, y: 40, w: 80, h: 80}},
    {e1: {id: "e1", source: "a", target: "b"}},
  );
  const pts = computeRoutes(s).e1;
  eq(pts.length, 2, "straight route should have exactly 2 points");
  eq(pts[0].y, pts[1].y, "straight route must be horizontal");
});

test("diagonal single edge is a plain Z (no lane hook)", () => {
  // func-sized target above-right of the source: y-spans don't overlap
  const s = makeStore(
    {a: {x: 0, y: 200, w: 160, h: 160}, f: {x: 400, y: 0, w: 80, h: 80}},
    {e1: {id: "e1", source: "a", target: "f"}},
  );
  const pts = computeRoutes(s).e1;
  eq(pts.length, 4, "single diagonal edge should be a 4-point Z");
  eq(pts[0].y, pts[1].y, "first segment horizontal");
  eq(pts[1].x, pts[2].x, "middle segment vertical");
  eq(pts[2].y, pts[3].y, "final segment horizontal (clean arrow into port)");
  if (pts[1].x <= pts[0].x || pts[1].x >= pts[3].x) {
    throw new Error(`turn must be between source and target: ${JSON.stringify(pts)}`);
  }
});

test("multiple edges into one target get staggered Z lanes", () => {
  const s = makeStore(
    {
      a: {x: 0, y: 200, w: 160, h: 160},
      b: {x: 0, y: 600, w: 160, h: 160},
      f: {x: 400, y: 0, w: 80, h: 80},
    },
    {
      e1: {id: "e1", source: "a", target: "f"},
      e2: {id: "e2", source: "b", target: "f"},
    },
  );
  const routes = computeRoutes(s);
  eq(routes.e1.length, 4, "multi-edge routes must still be plain Zs");
  eq(routes.e2.length, 4, "multi-edge routes must still be plain Zs");
  if (routes.e1[1].x === routes.e2[1].x) throw new Error("turn lanes must stagger");
  if (routes.e1[3].y === routes.e2[3].y) throw new Error("ports must spread");
});

test("backward single edge (target left of source) is a Z too", () => {
  const s = makeStore(
    {a: {x: 400, y: 200, w: 160, h: 160}, b: {x: 0, y: 0, w: 80, h: 80}},
    {e1: {id: "e1", source: "a", target: "b"}},
  );
  const pts = computeRoutes(s).e1;
  eq(pts.length, 4, "backward single edge should be a 4-point Z");
  eq(pts[2].y, pts[3].y, "final segment horizontal");
});

// ---------------------------------------------------------------------------

console.log();
if (failed) {
  console.log(`${failed} FAILED, ${passed} passed`);
  process.exit(1);
}
console.log(`ALL ${passed} TESTS PASSED`);
