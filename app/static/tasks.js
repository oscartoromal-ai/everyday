/* Task rows: dating from Tasks, keyboard triage, filing by drag, and the
   rows' collapsible descriptions. Writing a task (adding or editing) is
   task-sheet.js. Listeners sit on document, so they survive htmx swaps. */

(() => {
  /* ---- rows on Tasks: the calendar button opens its hidden date input ---- */

  document.addEventListener("click", (e) => {
    const button = e.target.closest?.("[data-pick-date]");
    if (!button) return;
    const input = button.nextElementSibling;
    try {
      input.showPicker();
    } catch {
      input.focus(); // no showPicker: the input itself takes the date
    }
  });

  /* ---- Tasks: the keyboard cursor ---- */

  // The whole page works from the keyboard. The cursor is the focused row
  // (or a Done fold's header, which Enter or Space opens), drawn as the nav's
  // spark bar. Up/Down or J/K move it, Shift jumps a group, Home/End go to
  // the ends; Enter or E edits, N writes a new task, X done, T today,
  // M tomorrow, D picks a day and P a project (the task sheet's menus),
  // Space opens the description, Delete deletes after asking, V switches
  // By date and By project, Esc leaves. The list re-renders from the server
  // after every change, and the cursor lands where it belongs: on the row
  // that followed one dated, filed, finished or deleted away, and on the
  // same task after an edit.
  const TYPING = "input, textarea, select, [contenteditable]";
  const LIST_KEYS = new Set([
    "ArrowDown", "ArrowUp", "j", "k", "Home", "End", "n", "v", "Escape",
    "t", "m", "d", "p", "x", "e", "Enter", " ", "Delete", "Backspace",
  ]);
  const STOPS = "#task-groups .task-row[tabindex], #task-groups .done-fold > summary";
  const CURSOR_KEY = "pc-task-cursor"; // carries the cursor across V's reload
  const onTasks = () => !!document.querySelector(".tasks-page");
  const shown = (el) => (el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null);
  const stops = () => [...document.querySelectorAll(STOPS)].filter(shown);
  const groupOf = (stop) => stop.closest(".list-section, .project-card");

  let landOn = null; // id to focus once the list has re-rendered
  let last = null; // id of the cursor's last stop, to come back to from writing

  const focusStop = (stop) => {
    if (!stop) return false;
    stop.focus();
    stop.scrollIntoView({ block: "nearest" });
    return true;
  };
  const byId = (id) => {
    const el = id && document.getElementById(id);
    return el && el.matches(STOPS) && shown(el) ? el : null;
  };
  const neighbour = (stop) => {
    const all = stops().filter((s) => s.matches(".task-row"));
    const at = all.indexOf(stop);
    return all[at + 1] || all[at - 1] || null;
  };

  const move = (from, step) => {
    const all = stops();
    const at = all.indexOf(from);
    focusStop(at === -1 ? all[0] : all[Math.max(0, Math.min(all.length - 1, at + step))]);
  };
  const jump = (from, step) => {
    const all = stops();
    const at = all.indexOf(from);
    if (at === -1) return focusStop(all[0]);
    const here = groupOf(from);
    if (step > 0) return focusStop(all.slice(at + 1).find((s) => groupOf(s) !== here));
    // Up: to the start of this group, or from its start to the previous group's.
    const first = all.find((s) => groupOf(s) === here);
    const before = all.slice(0, at).reverse().find((s) => groupOf(s) !== here);
    const target = first !== from ? here : before ? groupOf(before) : here;
    return focusStop(all.find((s) => groupOf(s) === target));
  };

  document.addEventListener("focusin", (e) => {
    if (e.target.matches?.(STOPS)) last = e.target.id;
  });

  // A re-rendered list is only live once its swap settles (about 20ms on):
  // htmx wires up the new rows' controls, and gives focus back to the row
  // that had it, then. A key pressed in between waits for it, and belongs to
  // that row.
  let settling = null; // id of the row that had the cursor, while a list settles
  let listSettling = false;
  let settleTimer = 0;
  const queued = [];
  document.addEventListener("htmx:beforeSwap", (e) => {
    if (!e.detail.target.querySelector?.(STOPS) && !e.detail.target.matches?.(STOPS)) return;
    listSettling = true;
    const active = document.activeElement;
    if (active?.matches?.(STOPS) && e.detail.target.contains(active)) settling = active.id;
    // A swap that removes its own target (a deleted row) settles on a detached
    // element, whose event never reaches the document: a fallback ends it.
    clearTimeout(settleTimer);
    settleTimer = setTimeout(settled, 100);
  });

  // For task-sheet.js: where the keyboard goes when writing is done.
  window.TaskCursor = {
    // After the list settles, land here (a row's id).
    land(id) { landOn = id; },
    // Back from a composer: to the last stop, else the first.
    restore() { return onTasks() && focusStop(byId(last) || stops()[0]); },
    // A task just added: the cursor's next stop.
    remember(id) { last = id; },
  };

  document.addEventListener("keydown", (e) => {
    if (!onTasks() || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return;
    if (e.target.closest?.(TYPING) || document.querySelector("dialog[open]")) return;
    if (listSettling && LIST_KEYS.has(e.key.length === 1 ? e.key.toLowerCase() : e.key)) {
      e.preventDefault();
      queued.push({ key: e.key, shiftKey: e.shiftKey });
      return;
    }
    let stop = e.target.closest?.(STOPS);
    if (!stop && e.target === document.body && settling && byId(settling)) {
      stop = byId(settling);
      stop.focus();
    }
    const row = stop?.matches(".task-row") ? stop : null;
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;

    if (key === "ArrowDown" || key === "j" || key === "ArrowUp" || key === "k") {
      e.preventDefault();
      const step = key === "ArrowDown" || key === "j" ? 1 : -1;
      if (e.shiftKey) jump(stop, step);
      else move(stop, step);
      return;
    }
    if (key === "Home" || key === "End") {
      e.preventDefault();
      const all = stops();
      focusStop(key === "Home" ? all[0] : all[all.length - 1]);
      return;
    }
    if (key === "n") {
      e.preventDefault();
      // By project, into the cursor's project; otherwise the page's composer.
      const card = stop?.closest(".project-card");
      const composer = card?.querySelector(".task-sheet[data-composer]") || document.querySelector(".capture .task-sheet");
      window.TaskSheet.compose(composer);
      return;
    }
    if (key === "v") {
      e.preventDefault();
      const other = document.querySelector(".tasks-page .segmented a:not([aria-current])");
      try {
        if (last) sessionStorage.setItem(CURSOR_KEY, last);
      } catch { /* storage blocked: the cursor starts over */ }
      other?.click();
      return;
    }
    if (key === "Escape" && stop) {
      stop.blur();
      return;
    }
    if (!row) return;

    const click = (selector) => {
      const target = row.querySelector(selector);
      if (!target) return false;
      target.click();
      return true;
    };
    const leaving = () => { landOn = neighbour(row)?.id ?? null; };

    if (key === "t" || key === "m") {
      e.preventDefault();
      leaving();
      if (!click(`[data-plan="${key === "t" ? "today" : "tomorrow"}"]`)) landOn = null;
    } else if (key === "d" || key === "p") {
      e.preventDefault();
      // The sheet opens on the field's menu; a change lands on the next row.
      window.TaskSheet.edit(row, key === "d" ? "planned_for" : "project", neighbour(row)?.id ?? null);
    } else if (key === "x") {
      e.preventDefault();
      leaving();
      click(".task-check");
    } else if (key === "e" || key === "Enter") {
      e.preventDefault();
      click(".task-title-btn");
    } else if (key === " ") {
      e.preventDefault();
      click(".notes-toggle");
    } else if (key === "Delete" || key === "Backspace") {
      e.preventDefault();
      leaving();
      click(".task-delete"); // asks first; Cancel leaves the cursor where it was
    }
  });

  // Reaching for the mouse means the keyboard pass is over (and a cancelled
  // date picker must not leave a landing spot for some later refresh).
  document.addEventListener("pointerdown", () => { landOn = null; }, true);
  // So must a cancelled delete ("close" does not bubble; caught on the way
  // down). A close that arrives with the dialog open again is a late one from
  // an earlier opening (see shell.js), not this delete's answer.
  document.addEventListener("close", (e) => {
    const dialog = e.target;
    if (dialog.id === "confirm-dialog" && !dialog.open && dialog.returnValue !== "go") landOn = null;
  }, true);

  // Once a swap has settled, the cursor lands where a key said it should.
  // htmx already puts focus back on a re-rendered element with the same id,
  // which keeps the cursor on a row through a refresh; a landing overrides
  // that, but only from a row or from the page, never from anything else the
  // user moved to.
  // Once a list has settled: the cursor lands where a key said it should,
  // then keys that waited for the list replay on the row that has focus.
  // htmx already puts focus back on a re-rendered element with the same id,
  // which keeps the cursor on a row through a refresh; a landing overrides
  // that, but only from a row or from the page, never from anything else the
  // user moved to.
  function settled() {
    clearTimeout(settleTimer);
    listSettling = false;
    settling = null;
    const active = document.activeElement;
    const stop = landOn && byId(landOn);
    if (stop && (!active || active === document.body || active.matches(STOPS))) {
      landOn = null;
      focusStop(stop);
    }
    for (const { key, shiftKey } of queued.splice(0)) {
      const at = document.activeElement || document.body;
      at.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }));
    }
  }
  document.addEventListener("htmx:afterSettle", settled);

  // After V's reload, the cursor comes back to the task it was on.
  const carried = (() => {
    try {
      const id = sessionStorage.getItem(CURSOR_KEY);
      sessionStorage.removeItem(CURSOR_KEY);
      return id;
    } catch {
      return null;
    }
  })();
  if (carried) document.addEventListener("DOMContentLoaded", () => focusStop(byId(carried)));

  /* ---- project cards: drag a task onto a milestone, another project, or No project ---- */

  // A card files into its project with no milestone; a milestone group into
  // that milestone; the No project card clears both. The server validates
  // (a milestone must belong to the task's project) and the lists re-render.
  const fileTarget = (el) => el?.closest?.("[data-file-milestone], [data-file-project]");
  const filing = (target) => {
    const card = target.closest("[data-file-project]");
    const project = card?.dataset.fileProject ? Number(card.dataset.fileProject) : null;
    const milestone = target.dataset.fileMilestone ? Number(target.dataset.fileMilestone) : null;
    return { project_id: project, milestone_id: milestone };
  };

  const toast = (message) => {
    let el = document.querySelector(".cal-toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "cal-toast";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2600);
  };

  const armFiling = (root) => {
    root.querySelectorAll?.("[data-file-project] .task-row[data-task-id]").forEach((row) => {
      row.draggable = !row.classList.contains("done");
    });
  };
  document.addEventListener("htmx:load", (e) => armFiling(e.detail.elt));

  let filed = null; // {taskId, from: {project_id, milestone_id}}
  let over = null;
  const hover = (el) => {
    if (over === el) return;
    over?.classList.remove("drop-over");
    over = el;
    over?.classList.add("drop-over");
  };

  document.addEventListener("dragstart", (e) => {
    const row = e.target.closest?.("[data-file-project] .task-row[draggable='true']");
    if (!row) return;
    filed = { taskId: row.dataset.taskId, from: filing(fileTarget(row)) };
    e.dataTransfer.setData("text/plain", row.dataset.taskTitle);
    e.dataTransfer.effectAllowed = "move";
    row.classList.add("dragging");
  });

  document.addEventListener("dragover", (e) => {
    if (!filed) return;
    const target = fileTarget(e.target);
    hover(target);
    if (!target) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  });

  document.addEventListener("drop", async (e) => {
    if (!filed) return;
    const target = fileTarget(e.target);
    const { taskId, from } = filed;
    filed = null;
    hover(null);
    if (!target) return;
    e.preventDefault();
    const to = filing(target);
    if (to.project_id === from.project_id && to.milestone_id === from.milestone_id) return;
    const res = await fetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify(to),
    });
    if (!res.ok) {
      let detail = "Could not move that task.";
      try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
      toast(detail);
    }
    htmx.trigger(document.body, "tasks:changed");
  });

  document.addEventListener("dragend", () => {
    filed = null;
    hover(null);
    document.querySelector(".task-row.dragging")?.classList.remove("dragging");
  });

  /* ---- a tick lands: the fresh row's box plays the system's --check-pulse once ---- */

  let ticked = null; // id of the row whose box was just checked
  document.addEventListener("change", (e) => {
    if (e.target.matches?.(".task-check") && e.target.checked) ticked = e.target.closest(".task-row")?.id;
  });
  document.addEventListener("htmx:afterSettle", () => {
    const row = ticked && document.getElementById(ticked);
    if (!row?.classList.contains("done")) return;
    ticked = null;
    row.classList.add("just-done");
    setTimeout(() => row.classList.remove("just-done"), 700);
  });

  /* ---- what stays open: descriptions and Done folds, per tab ---- */

  const remembered = (key) => {
    try { return new Set(JSON.parse(sessionStorage.getItem(key)) || []); } catch { return new Set(); }
  };
  const remember = (key, id, isOpen) => {
    const ids = remembered(key);
    if (isOpen) ids.add(id); else ids.delete(id);
    try { sessionStorage.setItem(key, JSON.stringify([...ids])); } catch { /* storage blocked */ }
  };
  const NOTES = "pc-open-notes";
  const FOLDS = "pc-open-folds";

  const setOpen = (toggle, isOpen) => {
    toggle.setAttribute("aria-expanded", String(isOpen));
    document.getElementById(toggle.getAttribute("aria-controls")).hidden = !isOpen;
  };

  document.addEventListener("click", (e) => {
    const toggle = e.target.closest?.(".notes-toggle");
    if (!toggle) return;
    const isOpen = toggle.getAttribute("aria-expanded") !== "true";
    setOpen(toggle, isOpen);
    remember(NOTES, toggle.getAttribute("aria-controls"), isOpen);
  });

  // "toggle" does not bubble; capture it on the way down.
  document.addEventListener("toggle", (e) => {
    if (e.target.matches?.("details[data-remember]")) remember(FOLDS, e.target.id, e.target.open);
  }, true);

  // Lists re-render on every plan change; reopen what was open.
  const restore = (root) => {
    const notes = remembered(NOTES);
    root.querySelectorAll?.(".notes-toggle").forEach((toggle) => {
      const id = toggle.getAttribute("aria-controls");
      if (toggle.getAttribute("aria-expanded") === "true") remember(NOTES, id, true);
      else if (notes.has(id)) setOpen(toggle, true);
    });
    const folds = remembered(FOLDS);
    root.querySelectorAll?.("details[data-remember]").forEach((fold) => {
      if (folds.has(fold.id)) fold.open = true;
    });
  };
  document.addEventListener("htmx:load", (e) => restore(e.detail.elt));
})();
