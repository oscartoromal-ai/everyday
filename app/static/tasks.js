/* Task rows: dating, keyboard triage, filing by drag, and the rows'
   collapsible descriptions. Writing a task (adding or editing) is
   task-sheet.js. Listeners sit on document, so they survive htmx swaps. */

(() => {
  /* ---- a row's calendar button opens its hidden date input ---- */

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

  /* ---- the keyboard cursor: Projects' list ---- */

  // The list works from the keyboard alone; it marks its area with
  // data-cursor. The cursor is the focused row (or a fold's header: Done, or
  // a shelf, which Enter or Space opens; or a folded project's, which Right,
  // Enter or Space unfolds, and Left on one of its rows folds), drawn as the
  // nav's spark bar. Up/Down or J/K move it, Shift jumps a project, Home/End
  // go to the ends; Enter or E edits, N writes a new task (into the cursor's
  // project where there is one), X done, T today, M tomorrow, D picks a day
  // and P a project (the task sheet's menus), Space opens the description,
  // Delete deletes after asking, Esc leaves. The list re-renders from the
  // server after every change, and the cursor lands where it belongs: on the
  // row that followed one acted on, and on the same task after an edit.
  const TYPING = "input, textarea, select, [contenteditable]";
  const STOPS = [
    "[data-cursor] .task-row[tabindex]",
    "[data-cursor] .done-fold > summary",
    "[data-cursor] .project-shelf > summary",
    // A folded project's header; and one just unfolded with no rows to go
    // to, while the cursor is still on it.
    "[data-cursor] .project-card.folded [data-project-fold]",
    "[data-cursor] [data-project-fold]:focus",
  ].join(", ");
  const CURSOR_KEY = "pc-task-cursor"; // a task found in the command menu, to land on
  const onCursorPage = () => !!document.querySelector("[data-cursor]");
  const shown = (el) => (el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null);
  const stops = () => [...document.querySelectorAll(STOPS)].filter(shown);
  const groupOf = (stop) => stop.closest(".list-section, .project-card, .project-shelf");
  const isoDay = (offset) => {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };

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

  // htmx gives focus back to a re-rendered row as its swap settles; a key
  // pressed before that lands on the page, and still belongs to that row.
  let settling = null; // id of the row that had the cursor, while a list settles
  let settleTimer = 0;
  document.addEventListener("htmx:beforeSwap", (e) => {
    const active = document.activeElement;
    if (!active?.matches?.(STOPS) || !e.detail.target.contains(active)) return;
    settling = active.id;
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
    restore() { return onCursorPage() && focusStop(byId(last) || stops()[0]); },
    // A task just added: the cursor's next stop.
    remember(id) { last = id; },
  };

  document.addEventListener("keydown", (e) => {
    if (!onCursorPage() || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return;
    if (e.target.closest?.(TYPING) || document.querySelector("dialog[open]")) return;
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
      // Into the cursor's project where it has one; else the page's own
      // composer (the sheet's first row), else the first project's.
      const card = stop?.closest(".project-card");
      if (card?.classList.contains("folded")) fold(card, false);
      const composers = [...document.querySelectorAll(".task-sheet[data-composer]")];
      const composer = card?.querySelector(".task-sheet[data-composer]")
        || composers.find((form) => !form.closest(".project-card, dialog"))
        || composers.find((form) => !form.closest("dialog"));
      window.TaskSheet.compose(composer);
      return;
    }
    if (key === "Escape" && stop) {
      stop.blur();
      return;
    }
    // As in a tree: Left on a project's row folds the project, the cursor on
    // its header; Right (or Enter, Space) there unfolds it, onto its first row.
    const header = stop?.matches("[data-project-fold]") ? stop : null;
    if (key === "ArrowLeft" && row && !e.shiftKey) {
      const card = row.closest(".project-card");
      const chevron = card?.querySelector(":scope > header [data-project-fold]");
      if (!chevron) return;
      e.preventDefault();
      fold(card, true);
      focusStop(chevron);
      return;
    }
    if (header && (key === "ArrowRight" || key === "Enter" || key === " ")) {
      e.preventDefault();
      const card = header.closest(".project-card");
      if (!card.classList.contains("folded")) return;
      fold(card, false);
      focusStop(stops().find((s) => s !== header && card.contains(s)) || header);
      return;
    }
    if (!row) return;
    // A key for a row while its list is being re-rendered waits for the new
    // list, and acts on the row there: the row it was pressed on is about to
    // be replaced (a change often re-renders a list twice, for the task and
    // for the calendar).
    if (ROW_KEYS.has(key) && listBusy()) {
      e.preventDefault();
      waiting = { id: row.id, key, shiftKey: e.shiftKey };
      return;
    }

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
      // A row's do-date button takes it; a done row has none, so the key posts it.
      if (click(`[data-plan="${key === "t" ? "today" : "tomorrow"}"]`)) return;
      htmx.ajax("POST", `/ui/tasks/${row.dataset.taskId}/plan`, {
        source: row, swap: "none", values: { planned_for: isoDay(key === "t" ? 0 : 1) },
      });
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

  // Once a list has settled, the cursor lands where a key said it should.
  // htmx already puts focus back on a re-rendered element with the same id,
  // which keeps the cursor on a row through a refresh; a landing overrides
  // that, but only from a row or from the page, never from anything else the
  // user moved to.
  function settled() {
    clearTimeout(settleTimer);
    settling = null;
    const active = document.activeElement;
    const stop = landOn && byId(landOn);
    if (stop && (!active || active === document.body || active.matches(STOPS))) {
      landOn = null;
      focusStop(stop);
    }
  }
  document.addEventListener("htmx:afterSettle", settled);

  // A row's key pressed while its list was re-rendering, done once it has
  // settled, on the row as it is now.
  const ROW_KEYS = new Set(["t", "m", "d", "p", "x", "e", "Enter", " ", "Delete", "Backspace"]);
  const listBusy = () => !!document.querySelector("[hx-trigger*='tasks:changed'].htmx-request");
  let waiting = null; // {id, key, shiftKey}
  document.addEventListener("htmx:afterSettle", () => {
    if (!waiting || listBusy()) return;
    const { id, key, shiftKey } = waiting;
    waiting = null;
    const row = byId(id);
    if (!row) return;
    focusStop(row);
    row.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }));
  });

  // Arriving from the command menu, the cursor lands on the task found.
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

  /* ---- project cards: folded to their header, kept on the project ---- */

  // A fold shows at once and is saved behind it, a project's saves one after
  // another, so the last one is what stays. A list re-rendered before a save
  // lands would bring the card back as it was, so a fold still saving is put
  // back on the fresh card.
  const saving = new Map(); // project id -> {shut}, its last fold, while that is saving
  const queues = new Map(); // project id -> its last save

  const showFold = (card, shut) => {
    card.classList.toggle("folded", shut);
    const chevron = card.querySelector(":scope > header [data-project-fold]");
    const name = card.querySelector(":scope > header .project-name")?.textContent ?? "";
    chevron.setAttribute("aria-expanded", String(!shut));
    chevron.setAttribute("aria-label", `${shut ? "Unfold" : "Fold"} ${name}`);
  };

  const save = async (id, shut) => {
    try {
      const res = await fetch(`/ui/projects/${id}/fold`, {
        method: "POST",
        headers: { "X-CSRF": window.csrfToken() },
        body: new URLSearchParams({ folded: String(shut) }),
      });
      return res.ok;
    } catch {
      return false; // offline
    }
  };

  function fold(card, shut) {
    const chevron = card.querySelector(":scope > header [data-project-fold]");
    if (!chevron || card.classList.contains("folded") === shut) return;
    const id = chevron.dataset.projectFold;
    showFold(card, shut);
    const mine = { shut };
    saving.set(id, mine);
    const saved = (queues.get(id) || Promise.resolve()).then(() => save(id, shut));
    queues.set(id, saved);
    saved.then((ok) => {
      if (saving.get(id) !== mine) return; // a later fold of the same card owns it now
      saving.delete(id);
      queues.delete(id);
      if (ok) return;
      window.toast("Could not keep that fold. Try again?");
      const now = document.querySelector(`[data-project-fold="${id}"]`)?.closest(".project-card");
      if (now) showFold(now, !shut);
    });
  }

  // The chevron; with Alt, every project on the page goes the same way.
  document.addEventListener("click", (e) => {
    const chevron = e.target.closest?.("[data-project-fold]");
    if (!chevron) return;
    const card = chevron.closest(".project-card");
    const shut = !card.classList.contains("folded");
    const cards = e.altKey
      ? [...document.querySelectorAll(".project-card:has(> header [data-project-fold])")]
      : [card];
    cards.forEach((c) => fold(c, shut));
  });

  document.addEventListener("htmx:load", (e) => {
    saving.forEach(({ shut }, id) => {
      const card = e.detail.elt.querySelector?.(`[data-project-fold="${id}"]`)?.closest(".project-card");
      if (card) showFold(card, shut);
    });
  });

  /* ---- project cards: drag a task onto a workstream, another project, or No project ---- */

  // A card files into its project with no workstream; a workstream group into
  // that workstream; the No project card clears both. The server validates
  // (a workstream must belong to the task's project) and the lists re-render.
  const fileTarget = (el) => el?.closest?.("[data-file-workstream], [data-file-project]");
  const filing = (target) => {
    const card = target.closest("[data-file-project]");
    const project = card?.dataset.fileProject ? Number(card.dataset.fileProject) : null;
    const workstream = target.dataset.fileWorkstream ? Number(target.dataset.fileWorkstream) : null;
    return { project_id: project, workstream_id: workstream };
  };

  const armFiling = (root) => {
    root.querySelectorAll?.("[data-file-project] .task-row[data-task-id]").forEach((row) => {
      row.draggable = !row.classList.contains("done");
    });
  };
  document.addEventListener("htmx:load", (e) => armFiling(e.detail.elt));

  let filed = null; // {taskId, from: {project_id, workstream_id}}
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
    if (to.project_id === from.project_id && to.workstream_id === from.workstream_id) return;
    const res = await fetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify(to),
    });
    if (!res.ok) {
      let detail = "Could not move that task.";
      try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
      window.toast(detail);
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
