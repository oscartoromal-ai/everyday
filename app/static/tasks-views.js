/* A project's Tasks tab, whichever view it is in (project_tasks.html):
   the gear's menu of views, and what the views share, kept on this device
   across the list's redraws and visits:
   - a part that folds: [data-fold-key] holding a [data-fold] button (or a
     click on its .tv-head); folded, it has the class "folded" and its
     button aria-expanded="false";
   - a task's sub-tasks (or description) shown under it: a [data-subtasks]
     button whose aria-controls names the part it shows, hidden until it is
     pressed (or Space on the row, tasks.js); its data-label says what it
     counts, and its aria-label whether a press shows or hides them;
   - the finished work: [data-done-part] parts, shown while Show completed
     ([data-show-done]) is ticked;
   - List and details' task picked (tasks-pane.js keeps it here).
   It is kept in a cookie of the tab's own (task_views.py reads it), so the
   server draws the view as it was left from its first paint; drawn again
   here as it changes, and over every redraw. Each view's own behaviour is
   its own file (tasks-pane.js, tasks-board.js). */
(() => {
  const root = () => document.getElementById("project-tasks");
  const [project, view] = (root()?.dataset.foldScope ?? ":").split(":");

  /* ---- what is folded, shown, ticked or picked, by view ---- */

  const COOKIE = "tasks-state";
  const all = () => {
    const found = document.cookie.split("; ").find((c) => c.startsWith(`${COOKIE}=`));
    try { return JSON.parse(decodeURIComponent(found?.slice(COOKIE.length + 1) ?? "")) ?? {}; } catch { return {}; }
  };
  const state = () => {
    const mine = all()[view] ?? {};
    return {
      folds: new Set(mine.folds ?? []),
      subtasks: new Set((mine.subtasks ?? []).map(String)),
      done: mine.done === true,
      picked: mine.picked == null ? null : String(mine.picked),
    };
  };
  // Kept for a year, sent only to the tab's page; the sub-tasks of tasks
  // no longer on it are let go.
  const keep = (s) => {
    const here = new Set([...(root()?.querySelectorAll("[data-task-id]") ?? [])].map((el) => el.dataset.taskId));
    const mine = {};
    if (s.folds.size) mine.folds = [...s.folds];
    const subtasks = [...s.subtasks].filter((id) => here.has(id)).map(Number);
    if (subtasks.length) mine.subtasks = subtasks;
    if (s.done) mine.done = true;
    if (s.picked) mine.picked = Number(s.picked);
    const views = all();
    if (Object.keys(mine).length) views[view] = mine; else delete views[view];
    const value = Object.keys(views).length ? encodeURIComponent(JSON.stringify(views)) : "";
    document.cookie = `${COOKIE}=${value}; Path=/projects/${project}/tasks; Max-Age=${value ? 31536000 : 0}; SameSite=Lax`;
  };
  const change = (fn) => {
    const s = state();
    fn(s);
    keep(s);
    draw();
  };

  const draw = () => {
    const list = root();
    if (!list) return;
    const s = state();
    list.querySelectorAll("[data-fold-key]").forEach((part) => {
      const shut = s.folds.has(part.dataset.foldKey);
      part.classList.toggle("folded", shut);
      part.querySelector("[data-fold]")?.setAttribute("aria-expanded", String(!shut));
    });
    list.querySelectorAll("[data-subtasks]").forEach((button) => {
      const shown = s.subtasks.has(button.closest("[data-task-id]")?.dataset.taskId);
      button.setAttribute("aria-expanded", String(shown));
      if (button.dataset.label) button.setAttribute("aria-label", `${button.dataset.label}: ${shown ? "hide" : "show"} them`);
      const part = document.getElementById(button.getAttribute("aria-controls"));
      if (part) part.hidden = !shown;
    });
    document.querySelectorAll("[data-done-part]").forEach((part) => { part.hidden = !s.done; });
    document.querySelectorAll("[data-show-done]").forEach((box) => { box.checked = s.done; });
  };

  // For the views' own scripts and tasks.js.
  window.TasksViews = {
    // A folded part opens (a task dropped on it, tasks.js).
    unfold(part) {
      if (part?.dataset.foldKey && part.classList.contains("folded")) change((s) => s.folds.delete(part.dataset.foldKey));
    },
    picked: () => state().picked,
    pick(id) { change((s) => { s.picked = id; }); },
  };

  document.addEventListener("click", (e) => {
    const head = e.target.closest?.("#project-tasks .tv-head");
    const fold = e.target.closest?.("#project-tasks [data-fold]")
      || (head && !e.target.closest("button, a, input, label") ? head.querySelector("[data-fold]") : null);
    if (fold) {
      const key = fold.closest("[data-fold-key]").dataset.foldKey;
      change((s) => { if (s.folds.has(key)) s.folds.delete(key); else s.folds.add(key); });
      return;
    }
    const sub = e.target.closest?.("#project-tasks [data-subtasks]");
    if (sub) {
      const id = sub.closest("[data-task-id]").dataset.taskId;
      change((s) => { if (s.subtasks.has(id)) s.subtasks.delete(id); else s.subtasks.add(id); });
    }
  });
  document.addEventListener("change", (e) => {
    if (!e.target.matches?.("[data-show-done]")) return;
    change((s) => { s.done = e.target.checked; });
  });
  document.addEventListener("DOMContentLoaded", draw);
  document.addEventListener("htmx:afterSettle", (e) => {
    if (e.detail.elt?.id === "project-tasks" || e.detail.elt?.closest?.("#project-tasks")) draw();
  });

  /* ---- the gear: the views, the one chosen kept for every project ---- */

  const TICK = '<svg class="tick" viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 10.5l3.5 3.5 7.5-8"/></svg>';
  let menu = null;
  const opener = () => document.querySelector(".tasks-view-open");
  const closeMenu = (restore = true) => {
    if (!menu) return;
    menu.remove();
    menu = null;
    opener().setAttribute("aria-expanded", "false");
    if (restore) opener().focus();
  };
  const openMenu = () => {
    const button = opener();
    menu = document.querySelector(".tasks-view-items").content.firstElementChild.cloneNode(true);
    document.body.append(menu);
    const at = button.getBoundingClientRect();
    menu.style.top = `${at.bottom + 4}px`;
    menu.style.left = `${Math.max(8, Math.min(at.right - menu.offsetWidth, window.innerWidth - menu.offsetWidth - 8))}px`;
    button.setAttribute("aria-expanded", "true");
    (menu.querySelector("[aria-checked='true']") ?? menu.querySelector("[role='menuitemradio']")).focus();
  };
  const choose = async (item) => {
    menu.querySelectorAll("[role='menuitemradio']").forEach((i) => {
      i.setAttribute("aria-checked", String(i === item));
      i.querySelector(".tick")?.remove();
    });
    item.insertAdjacentHTML("beforeend", TICK);
    try {
      const res = await fetch("/ui/tasks-view", {
        method: "POST",
        headers: { "X-CSRF": window.csrfToken() },
        body: new URLSearchParams({ view: item.dataset.view }),
      });
      if (!res.ok) throw new Error(String(res.status));
    } catch {
      closeMenu();
      window.toast("Could not change the view.");
      return;
    }
    // Drawn again in it; a ?view= being looked at gives way to the one chosen.
    location.assign(location.pathname);
  };

  document.addEventListener("click", (e) => {
    if (e.target.closest?.(".tasks-view-open")) {
      if (menu) closeMenu(); else openMenu();
      return;
    }
    if (!menu) return;
    const item = e.target.closest?.("[role='menuitemradio']");
    if (item && menu.contains(item)) choose(item);
    else if (!menu.contains(e.target)) closeMenu(false);
  });
  document.addEventListener("keydown", (e) => {
    if (!menu || !menu.contains(e.target)) return;
    const items = [...menu.querySelectorAll("[role='menuitemradio']")];
    const at = items.indexOf(e.target.closest("[role='menuitemradio']"));
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      handled();
      items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    } else if (e.key === "Home" || e.key === "End") {
      handled();
      items[e.key === "Home" ? 0 : items.length - 1].focus();
    } else if (e.key === "Enter" || e.key === " ") {
      handled();
      choose(items[at]);
    } else if (e.key === "Escape" || (e.key === "Tab" && !e.ctrlKey)) {
      handled();
      closeMenu();
    } else {
      e.stopPropagation(); // the page's own keys stay out of the menu
    }
  }, true);
  window.addEventListener("resize", () => closeMenu(false));
})();
