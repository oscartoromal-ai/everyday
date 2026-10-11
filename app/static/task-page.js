/* A task's page (task.html) beyond its sheet: the map at its left, whose
   folds are remembered, the task's own workstream always opening; the
   outline pane, its description's headings, each a way to its line; and
   the agent work pane, which follows whose task it is as that changes,
   with its way to hand Oscar's task to an agent (it sets the sheet's owner,
   which the page saves, as the owner's menu does). */

(() => {
  const page = document.querySelector(".task-page");
  if (!page) return;

  /* ---- the map: folds remembered per browser, by what they fold ---- */

  const FOLDS = "pc-map-folds";
  const folds = () => {
    try { return JSON.parse(localStorage.getItem(FOLDS) || "{}"); } catch { return {}; }
  };
  const map = document.querySelector("[data-task-map]");
  const foldKey = (fold) => `${map.dataset.project || ""}:${fold.dataset.fold}`;
  const setFold = (fold, open) => {
    const toggle = fold.querySelector(":scope > .map-toggle");
    toggle.setAttribute("aria-expanded", String(open));
    fold.querySelector(":scope > .map-group").hidden = !open;
  };
  if (map) {
    const saved = folds();
    map.querySelectorAll("[data-fold]").forEach((fold) => {
      // The task's own workstream (and its fold of finished ones) opens as drawn.
      if (fold.hasAttribute("data-here")) return;
      const open = saved[foldKey(fold)];
      if (open !== undefined) setFold(fold, open);
    });
    map.addEventListener("click", (e) => {
      const toggle = e.target.closest(".map-toggle");
      if (!toggle) return;
      const fold = toggle.closest("[data-fold]");
      const open = toggle.getAttribute("aria-expanded") !== "true";
      setFold(fold, open);
      const all = folds();
      all[foldKey(fold)] = open;
      try { localStorage.setItem(FOLDS, JSON.stringify(all)); } catch { /* private mode */ }
    });
    // The task itself in sight, however long the map.
    map.querySelector('[aria-current="page"]')?.scrollIntoView({ block: "nearest" });
  }

  /* ---- the outline: the description's headings, as written ---- */

  const editorRoot = () => page.querySelector("[data-notes-editor]");
  const field = () => page.querySelector("textarea[name=notes]");
  const outline = document.querySelector("[data-outline]");
  const FENCE = /^ {0,3}(`{3,}|~{3,})/;
  const headings = (text) => {
    const found = [];
    let fence = null;
    text.split("\n").forEach((line, n) => {
      const opens = FENCE.exec(line);
      if (fence) {
        if (opens && opens[1][0] === fence[0] && opens[1].length >= fence.length) fence = null;
        return;
      }
      if (opens) {
        fence = opens[1];
        return;
      }
      const m = /^ {0,3}(#{1,6})[ \t]+(.+?)[ \t#]*$/.exec(line);
      if (m) found.push({ level: m[1].length, text: m[2], line: n + 1 });
    });
    return found;
  };
  const drawOutline = () => {
    if (!outline || !field()) return;
    const found = headings(field().value);
    const top = Math.min(...found.map((h) => h.level));
    outline.replaceChildren(...found.map((h) => {
      const li = document.createElement("li");
      if (h.level === top) li.className = "is-top";
      li.style.setProperty("--level", h.level - top);
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.line = h.line;
      button.textContent = h.text.replace(/[*_`]/g, "");
      li.append(button);
      return li;
    }));
  };
  outline?.addEventListener("click", (e) => {
    const button = e.target.closest("button[data-line]");
    const view = window.NotesEditor?.viewOf(editorRoot());
    if (!button || !view) return;
    const line = view.state.doc.line(Math.min(+button.dataset.line, view.state.doc.lines));
    // The heading at the window's top, with room above it; the caret at its start.
    view.dispatch({
      selection: { anchor: line.from },
      effects: window.CM.EditorView.scrollIntoView(line.from, { y: "start", yMargin: 96 }),
    });
    view.focus();
  });
  page.addEventListener("input", (e) => {
    if (e.target.matches?.("textarea[name=notes]")) drawOutline();
  });
  drawOutline();

  /* ---- whose task: the agent work pane follows ---- */

  const work = document.getElementById("side-work");
  // Claude's task opens on its work, Oscar's on its outline, until a pane is chosen.
  window.Side?.select(page.dataset.owner === "claude" ? "work" : "outline");
  page.addEventListener("sheet:field", (e) => {
    if (e.detail.name !== "owner") return;
    page.dataset.owner = e.detail.value;
    if (work) work.dataset.owner = e.detail.value;
  });
  // Hand to an agent: the sheet's owner set, and saved, as its menu sets it.
  document.addEventListener("click", (e) => {
    const button = e.target.closest?.("[data-sheet-set]");
    const form = page.querySelector('.task-sheet[data-sheet="page"]');
    if (!button || !form) return;
    form.dispatchEvent(new CustomEvent("sheet:set", {
      bubbles: true, detail: { name: button.dataset.sheetSet, value: button.dataset.value },
    }));
  });
})();
