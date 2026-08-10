// === TODO view: flat task list across all boards ===
// task title on the left, assignee (if any) on the right. click jumps the board to the node.

class TodoView {
  constructor(board) {
    this.board = board;
  }

  toggle() {
    const panel = document.getElementById("todo-panel");
    const btn = document.getElementById("todo-btn");
    if (!panel || !btn) return;
    if (panel.classList.contains("hidden")) {
      btn.classList.add("active");
      panel.classList.remove("hidden");
      this.loadAndRender();
    } else {
      btn.classList.remove("active");
      panel.classList.add("hidden");
    }
  }

  async loadAndRender() {
    const canvas = document.getElementById("todo-canvas");
    canvas.innerHTML = '<div class="todo-loading">loading...</div>';

    const boardsRes = await fetch("boards");
    const boards = (await boardsRes.json()).boards || [];

    const tasks = [];  // [{boardId, nid, title, state, assignee}]
    for (const boardId of boards) {
      try {
        const r = await fetch(`boards/${encodeURIComponent(boardId)}/graph`);
        if (!r.ok) continue;
        const g = await r.json();
        for (const [nid, node] of Object.entries(g.nodes || {})) {
          if (node.state) tasks.push({ boardId, nid, ...node });
        }
      } catch (e) {}
    }

    if (!tasks.length) {
      canvas.innerHTML = '<div class="todo-empty">no tasks — set a node state (todo/doing/done) to see it here</div>';
      return;
    }

    const order = { doing: 0, todo: 1, done: 2 };
    tasks.sort((a, b) => (order[a.state] ?? 3) - (order[b.state] ?? 3) || a.title.localeCompare(b.title));

    const icons = { done: "✓", doing: "▶", todo: "○" };
    canvas.innerHTML = tasks.map(t => `
      <div class="todo-row todo-${t.state}" data-board="${t.boardId}" data-nid="${t.nid}">
        <span class="todo-title">${icons[t.state] || ""} ${t.title}<span class="todo-board">${t.boardId}</span></span>
        <span class="todo-assignee">${t.state === "doing" && t.assignee ? t.assignee : ""}</span>
      </div>`).join("");

    canvas.querySelectorAll(".todo-row").forEach(el => {
      el.addEventListener("click", () => {
        document.getElementById("todo-panel").classList.add("hidden");
        document.getElementById("todo-btn").classList.remove("active");
        this.board.initStore(el.dataset.board).then(() => {
          const node = this.board.store.nodes[el.dataset.nid];
          if (node) this.board.centerCameraOn(node);
        });
      });
    });
  }
}
