// Geometry / layout unit tests for FabStore.
// These encode the folder rules: folders never move unless dragged themselves,
// children follow folders automatically, expanding pushes siblings aside.
// Run from repo root: node fab/TH0UGHTGR4PH/tests/geometry.test.js

const {FabStore} = require("../front/store.js");

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

function makeStore() {
  const store = new FabStore("main");
  store.api = async () => ({id: "stub"}); // geometry tests never hit the network
  return store;
}

function addFolder(store, id, x, y, expanded = true, parent = null) {
  store.nodes[id] = {id, kind: "folder", node_type: "folder", title: id, x, y, parent, expanded, width: 0, height: 0};
  return store.nodes[id];
}

function addObj(store, id, x, y, parent = null, expanded = false) {
  store.nodes[id] = {id, kind: "obj", node_type: "doc", title: id, x, y, parent, expanded, width: 0, height: 0};
  return store.nodes[id];
}

// ---------------------------------------------------------------------------

test("root node renders at its stored position", () => {
  const s = makeStore();
  addObj(s, "a", 400, 600);
  s.computeFolderContentOffsets();
  const p = s.renderPos(s.nodes.a);
  eq(p.x, 400, "x");
  eq(p.y, 600, "y");
});

test("top-left child renders grid-aligned at the folder's position", () => {
  const s = makeStore();
  addFolder(s, "f", 200, 200, true);
  addObj(s, "c", 12, 44, "f");
  s.computeFolderContentOffsets();
  const p = s.renderPos(s.nodes.c);
  eq(p.x, 200, "x must not be pushed off-center by padding");
  eq(p.y, 200, "y must not be pushed off-center by padding");
});

test("folder top-left stays pinned when a child moves (post-drop)", () => {
  const s = makeStore();
  addFolder(s, "f", 0, 0, true);
  addObj(s, "c1", 12, 44, "f");
  addObj(s, "c2", 12, 244, "f");
  s.computeFolderContentOffsets();
  const before = s.folderBounds(s.nodes.f);
  // user drags c2 down-right and drops it
  s.nodes.c2.x = 412;
  s.nodes.c2.y = 444;
  s.computeFolderContentOffsets();
  const after = s.folderBounds(s.nodes.f);
  eq(after.x, before.x, "folder x moved");
  eq(after.y, before.y, "folder y moved");
  if (after.w <= before.w) throw new Error("folder should grow to contain moved child");
});

test("folder does not chase a child mid-drag", () => {
  const s = makeStore();
  addFolder(s, "f", 0, 0, true);
  addObj(s, "c", 12, 44, "f");
  s.computeFolderContentOffsets();
  const offBefore = {...s.folderContentOffsets.f};
  // mid-drag: node coords mutated, dragging guard active
  s.dragging = {nodeId: "c", origX: 12, origY: 44};
  s.nodes.c.x = 2000;
  s.nodes.c.y = 2000;
  s.computeFolderContentOffsets();
  const off = s.folderContentOffsets.f;
  eq(off.dx, offBefore.dx, "content offset must not change mid-drag");
  eq(off.dy, offBefore.dy, "content offset must not change mid-drag");
  // the dragged child renders at its dragged spot, but the folder's own
  // stored position (its anchor) is untouched
  const pf = s.renderPos(s.nodes.f);
  eq(pf.x, 0, "folder render x");
  eq(pf.y, 0, "folder render y");
  s.dragging = null;
});

test("dragging a folder moves its children visually, stored rels unchanged", () => {
  const s = makeStore();
  addFolder(s, "f", 100, 100, true);
  addObj(s, "c", 12, 44, "f");
  s.computeFolderContentOffsets();
  const before = s.renderPos(s.nodes.c);
  // drag folder by (+300, +300) — only the folder's coords change
  s.nodes.f.x = 400;
  s.nodes.f.y = 400;
  s.computeFolderContentOffsets();
  const after = s.renderPos(s.nodes.c);
  eq(after.x - before.x, 300, "child must move exactly with the folder (x)");
  eq(after.y - before.y, 300, "child must move exactly with the folder (y)");
  eq(s.nodes.c.x, 12, "child stored rel x must not change");
  eq(s.nodes.c.y, 44, "child stored rel y must not change");
});

test("expanding a node pushes the sibling below it down", () => {
  const s = makeStore();
  addObj(s, "a", 0, 0);
  addObj(s, "b", 0, 200);
  s.nodes.a.expanded = true;
  s.nodes.a.width = FabStore.EXPANDED_W;
  s.nodes.a.height = FabStore.EXPANDED_H;
  s.computeFolderContentOffsets();
  s.resolveCollisions();
  const ra = s.renderPos(s.nodes.a);
  const rb = s.renderPos(s.nodes.b);
  eq(ra.x, 0, "expanded node must not move (x)");
  eq(ra.y, 0, "expanded node must not move (y)");
  if (rb.y <= 200) throw new Error(`sibling b should be pushed down, got y=${rb.y}`);
  // offsets are render-time only: stored coords untouched
  eq(s.nodes.b.y, 200, "sibling stored y must not change");
});

test("expanding a node inside a folder grows the folder without moving it", () => {
  const s = makeStore();
  addFolder(s, "f", 0, 0, true);
  addObj(s, "c1", 12, 44, "f");
  addObj(s, "c2", 12, 244, "f");
  s.nodes.c1.expanded = true;
  s.nodes.c1.width = FabStore.EXPANDED_W;
  s.nodes.c1.height = FabStore.EXPANDED_H;
  s.computeFolderContentOffsets();
  s.resolveCollisions();
  const b = s.folderBounds(s.nodes.f);
  // children render from the folder's stored pos; bounds = bbox + border pad
  eq(b.x, -FabStore.FOLDER_PAD.left, "folder x");
  eq(b.y, -FabStore.FOLDER_PAD.top, "folder y");
  if (b.h < FabStore.EXPANDED_H + 200) throw new Error(`folder should engulf expanded child, h=${b.h}`);
  const p2 = s.renderPos(s.nodes.c2);
  if (p2.y < 200 + FabStore.GRID) throw new Error(`sibling c2 should be pushed down, y=${p2.y}`);
});

test("collapsing a folder hides its descendants", () => {
  const s = makeStore();
  addFolder(s, "f", 0, 0, false);
  addObj(s, "c", 12, 44, "f");
  eq(s.isVisible(s.nodes.c), false, "child visible inside collapsed folder");
  s.nodes.f.expanded = true;
  eq(s.isVisible(s.nodes.c), true, "child invisible inside expanded folder");
});

test("nested collapsed ancestor hides descendants", () => {
  const s = makeStore();
  addFolder(s, "outer", 0, 0, false);
  addFolder(s, "inner", 12, 44, true, "outer");
  addObj(s, "c", 12, 44, "inner");
  eq(s.isVisible(s.nodes.c), false, "descendant visible through collapsed ancestor");
  s.nodes.outer.expanded = true;
  eq(s.isVisible(s.nodes.c), true, "descendant still invisible after expanding");
});

test("resolveOverlap slides a new node past existing siblings", () => {
  const s = makeStore();
  addObj(s, "a", 0, 0);
  const candidate = {kind: "obj", node_type: "doc", parent: null, x: 0, y: 0, expanded: false, width: 0, height: 0};
  s.resolveOverlap([candidate]);
  if (candidate.y < FabStore.GRID) throw new Error(`candidate still overlapping: y=${candidate.y}`);
});

test("freeChildPosition never hands out an occupied cell", () => {
  const s = makeStore();
  addFolder(s, "f", 0, 0, true);
  addObj(s, "c1", 12, 44, "f");
  const p = s.freeChildPosition(s.nodes.f);
  if (p.x === 12 && p.y === 44) throw new Error("occupied cell handed out");
});

test("empty expanded folder renders one grid cell plus border pad", () => {
  const s = makeStore();
  addFolder(s, "f", 600, 400, true);
  s.computeFolderContentOffsets();
  const b = s.folderBounds(s.nodes.f);
  eq(b.x, 600 - FabStore.FOLDER_PAD.left, "x");
  eq(b.y, 400 - FabStore.FOLDER_PAD.top, "y");
  eq(b.w, FabStore.GRID + FabStore.FOLDER_PAD.left + FabStore.FOLDER_PAD.right, "w");
  eq(b.h, FabStore.GRID + FabStore.FOLDER_PAD.top + FabStore.FOLDER_PAD.bottom, "h");
});

test("nested child renders through both folder offsets", () => {
  const s = makeStore();
  addFolder(s, "outer", 100, 100, true);
  addFolder(s, "inner", 12, 44, true, "outer");
  addObj(s, "c", 12, 44, "inner");
  s.computeFolderContentOffsets();
  const pi = s.renderPos(s.nodes.inner);
  eq(pi.x, 100, "inner x");
  eq(pi.y, 100, "inner y");
  const pc = s.renderPos(s.nodes.c);
  eq(pc.x, 100, "c x");
  eq(pc.y, 100, "c y");
});

test("wouldOverlap detects stacking and leaves state untouched", () => {
  const s = makeStore();
  addObj(s, "a", 0, 0);
  addObj(s, "b", 400, 400);
  s.computeFolderContentOffsets();
  eq(s.wouldOverlap("b", 0, 0, null), true, "moving b onto a's cell must overlap");
  eq(s.wouldOverlap("b", 200, 0, null), false, "free cell must not overlap");
  // probe must not mutate anything
  eq(s.nodes.b.x, 400, "b x mutated by probe");
  eq(s.nodes.b.y, 400, "b y mutated by probe");
});

test("wouldOverlap is sibling-scoped, not world-scoped", () => {
  const s = makeStore();
  addFolder(s, "f", 0, 0, true);
  addObj(s, "inside", 12, 44, "f");
  addObj(s, "outside", 0, 0, null);
  s.computeFolderContentOffsets();
  eq(s.wouldOverlap("outside", 400, 400, null), false, "free root cell must not overlap");
  // moving 'inside' to root at a free spot: siblings are now root nodes only
  eq(s.wouldOverlap("inside", 400, 400, null), false, "reparent to free root cell must not overlap");
});

test("expanded folder bounds count for overlap", () => {
  const s = makeStore();
  addFolder(s, "f", 0, 0, true);
  addObj(s, "c", 12, 44, "f");
  addObj(s, "b", 600, 600);
  s.computeFolderContentOffsets();
  eq(s.wouldOverlap("b", 0, 0, null), true, "dropping onto the folder's bounds must overlap");
  eq(s.wouldOverlap("b", 400, 0, null), false, "next to the folder must not overlap");
});

// ---------------------------------------------------------------------------

console.log();
if (failed) {
  console.log(`${failed} FAILED, ${passed} passed`);
  process.exit(1);
}
console.log(`ALL ${passed} TESTS PASSED`);
