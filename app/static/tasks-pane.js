/* List and details (partials/project_tasks/pane.html): the task picked on
   the list, shown in full in the pane beside it. A click on a line picks its
   task, and so does the keyboard's cursor (tasks.js) as it moves, so the
   pane follows it; a line's title, or Enter, edits the task in place as on
   every list, and so does the pane's title. Each line carries its details
   unseen (a template, pane_row.html): the pane is drawn from the picked
   line's, again whenever the line is drawn again (a tick, a save, the list
   redrawn). What is picked is kept on this device, a project at a time,
   across the list's redraws and visits; once its task has gone from the
   list, the task that followed it is picked. Narrow, there is no pane, and
   a click on a line opens its task's page. */
(() => {
  const LINE = ".lp-line[data-task-id]";
  // What takes the focus in the pane; the date pickers' inputs, unseen, do not.
  const FOCUSABLE = "a[href], button, input:not([type='date']), [tabindex]";
  const TYPING = "input:not([type='checkbox']), textarea, select, [contenteditable]";
  const root = () => document.getElementById("project-tasks");
  const inView = () => !!root()?.classList.contains("tasks-in-pane");
  const pane = () => root()?.querySelector(".lp-details");
  // Narrow, the pane is not drawn (app.css).
  const narrow = () => { const p = pane(); return !p || !shown(p); };
  const { shown } = window.TaskCursor;
  const lineOf = (id) => {
    const el = id && document.getElementById(`task-${id}`);
    return el && root()?.contains(el) ? el : null;
  };

  /* ---- what is picked, kept with the view's state (tasks-views.js) ---- */

  const store = (id) => window.TasksViews.pick(id);

  let picked = null; // the picked task's id
  let source = null; // its details as last drawn (its line's template), for while its line is being edited
  let order = []; // the lines' task ids in the list's order, at the last draw
  let held = null; // the pane's focus and scroll, carried over a redraw of the list

  // A control of the pane by what it is, the same in the pane drawn again:
  // a quick day, a sub-task, its box, its title, its tools.
  const CONTROLS = ["[data-pick-date]", "[data-lp-edit]", ".lp-done .task-check", ".lp-delete", ".lp-tool[href]"];
  const nameOf = (el) => {
    if (el.dataset.plan) return `[data-plan="${el.dataset.plan}"]`;
    if (el.matches(".subtask-check")) return `.subtask-check[hx-post="${el.getAttribute("hx-post")}"]`;
    return CONTROLS.find((name) => el.matches(name)) ?? null;
  };
  // The field's row a control is in, by its place, for when the control is
  // gone (Tomorrow, once the task is tomorrow's).
  const rowOf = (el) => {
    const row = el.closest(".lp-fields > div");
    return row ? [...row.parentElement.children].indexOf(row) : -1;
  };

  // Where the pane's focus and scroll are, to put them back once it is drawn again.
  const place = (p) => {
    const active = document.activeElement;
    const inside = p.contains(active) && active !== p;
    return {
      id: p.querySelector(".lp-card")?.dataset.lpFor ?? null,
      focus: inside ? { name: nameOf(active), row: rowOf(active) } : null,
      scroll: p.scrollTop,
    };
  };
  const refocus = (p, { name, row }) => {
    const card = p.querySelector(".lp-card");
    const fields = card?.querySelectorAll(".lp-fields > div")[row];
    return (name && card?.querySelector(name))
      || [...(fields?.querySelectorAll(FOCUSABLE) ?? [])].find(shown)
      || card?.querySelector("[data-lp-edit]");
  };

  function render(html) {
    const p = pane();
    if (!p || p._shown === html) return;
    const was = held ?? place(p);
    held = null;
    p.querySelector(".lp-card")?.remove();
    if (html) {
      p.insertAdjacentHTML("beforeend", html);
      htmx.process(p.querySelector(".lp-card"));
    }
    p._shown = html;
    const same = was.id && was.id === picked;
    p.scrollTop = same ? was.scroll : 0;
    if (!was.focus) return;
    // The focus was in the pane: back on the same control (or its field's
    // row, or the title), or for another task, on its line.
    const target = same ? refocus(p, was.focus) : lineOf(picked);
    (target ?? lineOf(picked))?.focus({ preventScroll: true });
  }

  function draw() {
    if (!inView()) return;
    const lines = [...root().querySelectorAll(LINE)];
    if (picked && !lineOf(picked)) {
      // Gone from the list (done, deleted, filed elsewhere): the task that
      // followed it, else the one before it.
      const open = new Set(lines.filter((l) => !l.classList.contains("done") && shown(l)).map((l) => l.dataset.taskId));
      const at = order.indexOf(picked);
      picked = at === -1 ? null
        : order.slice(at + 1).find((id) => open.has(id)) ?? order.slice(0, at).reverse().find((id) => open.has(id)) ?? null;
      source = null;
      store(picked);
    }
    order = lines.map((l) => l.dataset.taskId);
    for (const line of lines) {
      const on = line.dataset.taskId === picked;
      line.classList.toggle("picked", on);
      if (on) line.setAttribute("aria-current", "true"); else line.removeAttribute("aria-current");
    }
    // A line being edited is the sheet, without its details: the pane keeps them.
    const template = lineOf(picked)?.querySelector(":scope > template.lp-source");
    if (template) source = template.innerHTML;
    render(picked ? source : null);
    held = null;
  }

  function pick(id) {
    if (id === picked) return;
    picked = id;
    source = null;
    store(id);
    draw();
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!inView()) return;
    picked = window.TasksViews.picked();
    // A finished task picked on an earlier visit, its line out of sight: none.
    const line = lineOf(picked);
    if (line?.classList.contains("done") && !shown(line)) picked = null;
    // The server drew the pane as it was left (pane.html): it stays as drawn.
    const p = pane();
    if (p && p.querySelector(".lp-card")?.dataset.lpFor === picked) {
      p._shown = line.querySelector(":scope > template.lp-source").innerHTML;
    }
    draw();
  });
  document.addEventListener("htmx:beforeSwap", (e) => {
    const p = pane();
    if (p && e.detail.target?.contains?.(p)) held = place(p);
  });
  document.addEventListener("htmx:afterSettle", (e) => {
    if (e.detail.elt?.id === "project-tasks" || e.detail.elt?.closest?.("#project-tasks")) draw();
  });

  /* ---- picking: a click on a line, the cursor on one, a title edited ---- */

  document.addEventListener("focusin", (e) => {
    if (inView() && e.target.matches?.(LINE)) pick(e.target.dataset.taskId);
  });

  document.addEventListener("click", (e) => {
    if (!inView()) return;
    // The pane's title edits the task on its line; out of sight, on its page.
    if (e.target.closest?.(".lp-details [data-lp-edit]")) {
      const line = lineOf(picked);
      const title = line && shown(line) && line.querySelector(".task-title-btn");
      if (title) title.click();
      else if (picked) window.location.href = `/tasks/${picked}`;
      return;
    }
    const line = e.target.closest?.(LINE);
    if (!line) return;
    if (e.target.closest(".task-title-btn")) {
      pick(line.dataset.taskId);
      return;
    }
    if (e.target.closest("a, button, input, label")) return;
    if (narrow()) {
      const href = `/tasks/${line.dataset.taskId}`;
      if (e.ctrlKey || e.metaKey || e.shiftKey) window.open(href, "_blank");
      else window.location.href = href;
      return;
    }
    pick(line.dataset.taskId);
  });

  // The picked line ticked with the mouse goes as X takes it: the next open
  // task is picked, and the cursor lands on it once the list is drawn again.
  document.addEventListener("change", (e) => {
    const line = e.target.matches?.(".task-check:checked") && e.target.closest(LINE);
    if (!inView() || !line || line.dataset.taskId !== picked) return;
    const lines = [...root().querySelectorAll(LINE)].filter((l) => !l.classList.contains("done") && shown(l));
    const at = lines.indexOf(line);
    const next = lines[at + 1] ?? lines[at - 1];
    if (!next) return;
    pick(next.dataset.taskId);
    window.TaskCursor?.land(next.id);
  });

  /* ---- keys: into the pane and back ---- */

  // Space on a line (the description's key on every list) goes into its
  // details, at its title; Esc in the pane comes back to the line, and the cursor's keys
  // there move on from it.
  window.addEventListener("keydown", (e) => {
    if (!inView() || narrow() || e.defaultPrevented || e.isComposing || !window.Keys) return;
    if (document.querySelector("dialog[open]")) return;
    const p = pane();
    const line = lineOf(picked);
    if (e.target.matches?.(LINE) && window.Keys.is(e, "task.notes")) {
      const title = p.querySelector(".lp-card [data-lp-edit]");
      if (!title) return;
      e.preventDefault();
      e.stopPropagation();
      title.focus();
      return;
    }
    if (!p.contains(e.target) || e.target.closest(TYPING) || !line) return;
    const down = window.Keys.is(e, "list.down");
    if (e.key !== "Escape" && !down && !window.Keys.is(e, "list.up")) return;
    e.preventDefault();
    e.stopPropagation();
    const stops = window.TaskCursor.stops();
    const at = stops.indexOf(line);
    // Out of sight (folded away, finished), Esc only leaves the pane, and the keys start from the top.
    const to = e.key === "Escape" ? (at === -1 ? null : line)
      : stops[at === -1 ? 0 : Math.max(0, Math.min(stops.length - 1, at + (down ? 1 : -1)))];
    if (!to) {
      document.activeElement.blur();
      return;
    }
    to.focus();
    to.scrollIntoView({ block: "nearest" });
  }, true);
})();
