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

  /* ---- the keyboard cursor: the task lists (a project's Tasks, Plan) ---- */

  // A list works from the keyboard alone; it marks its area with
  // data-cursor, and each of its lists (a workstream, a project, a stretch
  // of days) with data-task-group. The cursor is the focused row (or Done's
  // header, which Enter or Space opens), drawn as the nav's spark bar. Its
  // keys are keys.py's (the defaults said here): Up/Down or J/K move it,
  // Shift jumps a list, Home/End go to the ends; Enter or E edits, N writes
  // a new task (into the cursor's list), X steps its status on (its box's
  // click), T today, M tomorrow, D picks a day and P a project (the task
  // sheet's menus), Space shows what
  // the row folds away under it (its .notes-toggle, or a view's
  // [data-subtasks]), Ctrl+Enter opens its page, Delete deletes after
  // asking, Esc leaves. A row's keys are the row's only while the row
  // itself has the focus: a control in it keeps its own Enter and Space.
  // The lists re-render from the server after every change, and the cursor
  // lands where it belongs: on the row that followed one acted on, and on
  // the same task after an edit.
  const TYPING = "input, textarea, select, [contenteditable]";
  const STOPS = [
    "[data-cursor] .task-row[tabindex]",
    "[data-cursor] .done-fold > summary",
  ].join(", ");
  const CURSOR_KEY = "pc-task-cursor"; // a task found in the command menu, to land on
  const onCursorPage = () => !!document.querySelector("[data-cursor]");
  const shown = (el) => (el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null);
  const stops = () => [...document.querySelectorAll(STOPS)].filter(shown);
  const groupOf = (stop) => stop.closest("[data-task-group]");
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

  // A new task (its key, N, from shell.js; or the command menu): into the
  // cursor's list where it has a composer; else the page's first. False off
  // a task list.
  const compose = () => {
    if (!onCursorPage()) return false;
    const stop = document.activeElement?.closest?.(STOPS);
    const composer = (stop && groupOf(stop)?.querySelector(".task-sheet[data-composer]"))
      || [...document.querySelectorAll(".task-sheet[data-composer]")].find((form) => !form.closest("dialog"));
    if (!composer) return false;
    window.TaskSheet.compose(composer);
    return true;
  };

  // For task-sheet.js: where the keyboard goes when writing is done.
  window.TaskCursor = {
    // After the list settles, land here (a row's id).
    land(id) { landOn = id; },
    // Back from a composer: to the last stop, else the first.
    restore() { return onCursorPage() && focusStop(byId(last) || stops()[0]); },
    // A task just added: the cursor's next stop.
    remember(id) { last = id; },
    compose,
    // For the views' own keys (tasks-pane.js, tasks-board.js): the
    // cursor's stops as they are now, and whether an element is drawn.
    stops,
    shown,
  };

  // What the keys do to the cursor's row (keys.py's ids).
  const ROW_ACTIONS = [
    "task.done", "task.today", "task.tomorrow", "task.pickDay", "task.project", "task.priority",
    "task.edit", "task.notes", "task.delete", "task.openPage",
  ];

  document.addEventListener("keydown", (e) => {
    if (!onCursorPage() || e.isComposing || e.defaultPrevented) return;
    if (e.target.closest?.(TYPING) || document.querySelector("dialog[open]")) return;
    const keys = window.Keys;
    let stop = e.target.closest?.(STOPS);
    if (!stop && e.target === document.body && settling && byId(settling)) {
      stop = byId(settling);
      stop.focus();
    }
    // The row's own keys, while it (not a control in it) has the focus.
    const row = stop?.matches(".task-row") && (e.target === stop || e.target === document.body) ? stop : null;
    const plain = !e.ctrlKey && !e.metaKey && !e.altKey;

    const down = keys.is(e, "list.down");
    const list = keys.is(e, "list.nextProject") ? 1 : keys.is(e, "list.prevProject") ? -1 : 0;
    if (down || list || keys.is(e, "list.up")) {
      e.preventDefault();
      if (list) jump(stop, list);
      else move(stop, down ? 1 : -1);
      return;
    }
    if (plain && (e.key === "Home" || e.key === "End")) {
      e.preventDefault();
      const all = stops();
      focusStop(e.key === "Home" ? all[0] : all[all.length - 1]);
      return;
    }
    if (plain && e.key === "Escape" && stop) {
      stop.blur();
      return;
    }
    if (!row) return;
    const action = ROW_ACTIONS.find((id) => keys.is(e, id));
    if (!action) return;
    e.preventDefault();
    // A key for a row while its list is being re-rendered waits for the new
    // list, and acts on the row there: the row it was pressed on is about to
    // be replaced (a change often re-renders a list twice, for the task and
    // for the calendar).
    if (listBusy()) {
      waiting = { id: row.id, action };
      return;
    }
    act(row, action);
  });

  // Delete, in the app's dialog (shell.js), then the row goes; the lists
  // re-render. Answered after a redraw, it deletes the row drawn again.
  function remove(row) {
    const { id } = row;
    window.confirmAction({
      title: "Delete task?", name: row.dataset.taskTitle,
      detail: "will be deleted. This can't be undone.", action: "Delete",
    }).then((yes) => {
      const now = yes && document.getElementById(id);
      if (!now) return;
      htmx.ajax("POST", `/ui/tasks/${now.dataset.taskId}/delete`, { source: now, target: `#${id}`, swap: "outerHTML" });
    });
  }

  function act(row, action) {
    const click = (selector) => {
      const target = row.querySelector(selector);
      if (!target) return false;
      target.click();
      return true;
    };
    const leaving = () => { landOn = neighbour(row)?.id ?? null; };

    if (action === "task.today" || action === "task.tomorrow") {
      const today = action === "task.today";
      leaving();
      // A row's do-date button takes it; a done row has none, so the key posts it.
      if (click(`[data-plan="${today ? "today" : "tomorrow"}"]`)) return;
      htmx.ajax("POST", `/ui/tasks/${row.dataset.taskId}/plan`, {
        source: row, swap: "none", values: { planned_for: isoDay(today ? 0 : 1) },
      });
    } else if (action === "task.pickDay" || action === "task.project") {
      // The sheet opens on the field's menu; a change lands on the next row.
      window.TaskSheet.edit(row, action === "task.pickDay" ? "planned_for" : "project", neighbour(row)?.id ?? null);
    } else if (action === "task.priority") {
      // Its priority's menu; the cursor stays on the task.
      window.TaskSheet.edit(row, "priority", null);
    } else if (action === "task.done") {
      // Its status stepped on; once that makes it done, it leaves the list.
      const box = row.querySelector(".task-check");
      if (box && NEXT_STATUS[box.dataset.status] === "done") leaving();
      click(".task-check");
    } else if (action === "task.edit") {
      click(".task-title-btn");
    } else if (action === "task.notes") {
      click(".notes-toggle, [data-subtasks]");
    } else if (action === "task.delete") {
      leaving();
      remove(row); // asks first; Cancel leaves the cursor where it was
    } else if (action === "task.openPage") {
      window.location.href = `/tasks/${row.dataset.taskId}`;
    }
  }

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
  const listBusy = () => !!document.querySelector("[hx-trigger*='tasks:changed'].htmx-request");
  let waiting = null; // {id, action}
  document.addEventListener("htmx:afterSettle", () => {
    if (!waiting || listBusy()) return;
    const { id, action } = waiting;
    waiting = null;
    const row = byId(id);
    if (!row) return;
    focusStop(row);
    act(row, action);
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
  // Back here, the cursor on the row it was on (shell.js).
  window.keepPlace?.("task-cursor", () => (document.activeElement?.matches(STOPS) ? document.activeElement.id : null),
    (id) => document.addEventListener("DOMContentLoaded", () => focusStop(byId(id))));

  /* ---- Projects' timeline: a project folded to its row, kept on the project ---- */

  // A project folded hides its workstreams (data-fold-card, its chevron
  // data-project-fold, its name data-fold-name). A fold shows at once and is
  // saved behind it, a project's saves one after another, so the last one is
  // what stays. The timeline redrawn before a save lands would bring the
  // project back as it was, so a fold still saving is put back on the fresh one.
  const saving = new Map(); // project id -> {shut}, its last fold, while that is saving
  const queues = new Map(); // project id -> its last save
  const foldCard = (id) => document.querySelector(`[data-project-fold="${id}"]`)?.closest("[data-fold-card]");

  const showFold = (card, shut) => {
    card.classList.toggle("folded", shut);
    const chevron = card.querySelector("[data-project-fold]");
    const name = card.querySelector("[data-fold-name]")?.textContent ?? "";
    chevron.setAttribute("aria-expanded", String(!shut));
    chevron.setAttribute("aria-label", `${shut ? "Show" : "Hide"} the workstreams of ${name}`);
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
    const chevron = card.querySelector("[data-project-fold]");
    if (!chevron || card.classList.contains("folded") === shut) return;
    const id = chevron.dataset.projectFold;
    showFold(card, shut);
    const mine = { shut };
    saving.set(id, mine);
    const saved = (queues.get(id) || Promise.resolve()).then(() => save(id, shut));
    queues.set(id, saved);
    saved.then((ok) => {
      if (saving.get(id) !== mine) return; // a later fold of the same project owns it now
      saving.delete(id);
      queues.delete(id);
      if (ok) return;
      window.toast("Could not keep that fold. Try again?");
      const now = foldCard(id);
      if (now) showFold(now, !shut);
    });
  }

  // The chevron; with Alt, every project on the page goes the same way.
  document.addEventListener("click", (e) => {
    const chevron = e.target.closest?.("[data-project-fold]");
    if (!chevron) return;
    const card = chevron.closest("[data-fold-card]");
    const shut = !card.classList.contains("folded");
    const cards = e.altKey
      ? [...document.querySelectorAll("[data-fold-card]:has([data-project-fold])")]
      : [card];
    cards.forEach((c) => fold(c, shut));
  });

  document.addEventListener("htmx:load", (e) => {
    saving.forEach(({ shut }, id) => {
      const card = e.detail.elt.querySelector?.(`[data-project-fold="${id}"]`)?.closest("[data-fold-card]");
      if (card) showFold(card, shut);
    });
  });

  /* ---- task lists: a task dragged onto another list ---- */

  // A list a task can be dropped on says what a drop there does:
  // - filing: data-file-project (empty for No project) and, a workstream's,
  //   data-file-workstream: the task goes into that project and workstream
  //   (the server validates: a workstream must be in the task's project);
  // - dating (By do-date): data-drop-offset, the do-date it takes in days
  //   from today as this device has it at the drop, so a page left open
  //   past midnight still means today ("" for none); a [data-drop-note] in
  //   it says the day while a task is held over it.
  // A task drops on a list of the kind it is in, but its own; anywhere else
  // (its own list, between lists, the page) it stays where it was. A list
  // folded opens to show it, and the lists re-render.
  const TARGETS = "[data-file-project], [data-drop-offset]";
  const ROWS = ":is([data-file-project], [data-drop-offset]) .task-row[data-task-id]";
  const targetOf = (el) => el?.closest?.(TARGETS) ?? null;
  const kindOf = (target) => (target.hasAttribute("data-drop-offset") ? "date" : "file");
  const filing = (target) => ({
    project_id: target.dataset.fileProject ? Number(target.dataset.fileProject) : null,
    workstream_id: target.dataset.fileWorkstream ? Number(target.dataset.fileWorkstream) : null,
  });
  const dayOf = (target) => (target.dataset.dropOffset === "" ? "" : isoDay(Number(target.dataset.dropOffset)));
  // As the app writes a day (app/dates.py): "Thu 29 Oct".
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const said = (iso) => {
    const d = new Date(`${iso}T12:00`);
    return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
  };

  const armDrags = (root) => {
    const rows = [...(root.querySelectorAll?.(ROWS) ?? [])];
    if (root.matches?.(ROWS)) rows.push(root);
    rows.forEach((row) => { row.draggable = !row.classList.contains("done"); });
  };
  document.addEventListener("htmx:load", (e) => armDrags(e.detail.elt));

  let held = null; // {row, home, kind}: the row in hand, the list it is in, and that list's kind
  let over = null; // the list lit under it
  const light = (target) => {
    if (over === target) return;
    over?.classList.remove("drop-over");
    over = target;
    over?.classList.add("drop-over");
  };
  const dropOn = (el) => {
    const target = targetOf(el);
    return target && target !== held.home && kindOf(target) === held.kind ? target : null;
  };
  const letGo = () => {
    held?.row.classList.remove("dragging");
    held = null;
    light(null);
  };

  document.addEventListener("dragstart", (e) => {
    const row = e.target.closest?.(".task-row[draggable='true']");
    const home = targetOf(row);
    if (!row || !home) return;
    held = { row, home, kind: kindOf(home) };
    e.dataTransfer.setData("text/plain", row.dataset.taskTitle);
    e.dataTransfer.effectAllowed = "move";
    row.classList.add("dragging");
    if (held.kind === "date") {
      document.querySelectorAll("[data-drop-offset] [data-drop-note]").forEach((note) => {
        const day = dayOf(note.closest("[data-drop-offset]"));
        note.textContent = day ? `Do it ${said(day)}` : "";
      });
    }
  });

  // Lit as the pointer enters a list, and every moment over it; where
  // nothing takes it, the pointer says so.
  const hover = (e) => {
    if (!held) return;
    const target = dropOn(e.target);
    light(target);
    if (!target) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };
  document.addEventListener("dragenter", hover);
  document.addEventListener("dragover", hover);

  document.addEventListener("drop", async (e) => {
    if (!held) return;
    const target = dropOn(e.target);
    const { row, kind } = held;
    letGo();
    if (!target) return;
    e.preventDefault();
    window.TasksViews?.unfold(target);
    if (kind === "date") {
      // Dated, the lists are drawn again (tasks:changed), the row in its new list.
      htmx.ajax("POST", `/ui/tasks/${row.dataset.taskId}/plan`, {
        source: row, swap: "none", values: { planned_for: dayOf(target) },
      });
      return;
    }
    const res = await fetch(`/api/tasks/${row.dataset.taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify(filing(target)),
    });
    if (!res.ok) {
      let detail = "Could not move that task.";
      try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
      window.toast(detail);
    }
    htmx.trigger(document.body, "tasks:changed");
  });

  document.addEventListener("dragend", letGo);

  /* ---- a row's box steps its task on, as Gantt's does ---- */

  // To do, in progress, review, done, and round to to do again; a blocked
  // task starts (tasks.next_status). Drawn at once, as the row will come
  // back drawn (macros.check). Each step is posted after the one before
  // (the server steps the task from where the last left it), so two quick
  // clicks are two steps; the row is drawn again from the last answer
  // alone, and never shows a step it has already gone past.
  const NEXT_STATUS = { todo: "in_progress", blocked: "in_progress", in_progress: "needs_review", needs_review: "done" };
  const steps = new Map(); // task id -> {left: steps not yet answered, last: the last one's promise}
  document.addEventListener("click", (e) => {
    const box = e.target.closest?.(".task-check[data-step]");
    if (!box) return;
    box.dataset.status = NEXT_STATUS[box.dataset.status] || "todo";
    box.checked = box.dataset.status === "done";
    const id = box.dataset.step;
    const at = steps.get(id) || { left: 0, last: Promise.resolve() };
    at.left += 1;
    // Asked from the row as it is then, so it carries what its list sends
    // (a Tasks view's X-Tasks-View) and comes back as that list's row.
    at.last = at.last.then(() => {
      const row = `#task-${id}`;
      if (!document.querySelector(row)) return null;
      return htmx.ajax("POST", `/ui/tasks/${id}/toggle`, { source: row, target: row, swap: "outerHTML" }).catch(() => null);
    }).then(() => {
      at.left -= 1;
      if (!at.left) steps.delete(id);
    });
    steps.set(id, at);
  });
  document.addEventListener("htmx:beforeSwap", (e) => {
    const id = /^\/ui\/tasks\/(\d+)\/toggle$/.exec(e.detail.pathInfo?.requestPath || "")?.[1];
    if (!id) return;
    if (e.detail.isError) {
      // Not taken: the row drawn again as the task stands.
      window.toast("Could not change that task's status.");
      htmx.ajax("GET", `/ui/tasks/${id}/row`, { source: `#task-${id}`, target: `#task-${id}`, swap: "outerHTML" });
    } else if (steps.get(id)?.left > 1) {
      e.detail.shouldSwap = false; // a later step's answer draws it
    }
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
