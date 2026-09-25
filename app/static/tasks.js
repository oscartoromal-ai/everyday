/* Writing tasks: the quick-add composer and the rows' collapsible
   descriptions. The description editor itself is notes-editor.js. Listeners
   sit on document, so they survive htmx swaps. */

(() => {
  const SUBMIT = (e) => e.key === "Enter" && (e.ctrlKey || e.metaKey);

  /* ---- the composer: title, then a description revealed on focus ---- */

  const composerOf = (el) => el.closest?.("[data-composer]");
  const editorOf = (form) => form.querySelector("[data-notes-editor]");
  const hasNotes = (form) => form.elements.notes.value.trim() !== "";

  const open = (form) => form.classList.add("composing");
  const close = (form) => form.classList.remove("composing");

  // The description opens once a title is being written, not on mere focus:
  // after an add, focus returns to the empty title, and a composer that
  // folded away on the next click elsewhere would shift the page under the
  // pointer between mousedown and mouseup, losing that click.
  document.addEventListener("input", (e) => {
    const form = composerOf(e.target);
    if (form && e.target === form.elements.title && e.target.value.trim()) open(form);
  });

  document.addEventListener("focusin", (e) => {
    const form = composerOf(e.target);
    if (form && (form.elements.title.value.trim() || hasNotes(form))) open(form);
  });

  document.addEventListener("focusout", (e) => {
    const form = composerOf(e.target);
    if (!form || form.contains(e.relatedTarget)) return;
    // A started task stays open; only an untouched composer folds away.
    if (!form.elements.title.value.trim() && !hasNotes(form)) close(form);
  });

  // Touch Safari never focuses a tapped button, so the blur would fold the
  // composer away under the finger; keep focus where it is instead.
  document.addEventListener("pointerdown", (e) => {
    if (e.target.closest?.(".quick-add-actions button")) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const cancel = e.target.closest?.("[data-composer-cancel]");
    if (!cancel) return;
    const form = composerOf(cancel);
    form.reset();
    close(form);
    document.activeElement?.blur();
  });

  document.addEventListener("keydown", (e) => {
    const target = e.target;
    const form = composerOf(target);

    if (SUBMIT(e) && (form || target.closest?.("[data-notes-editor]"))) {
      e.preventDefault();
      if (form && !form.elements.title.value.trim()) form.elements.title.focus();
      else target.closest("form").requestSubmit();
      return;
    }

    if (form && e.key === "Escape") {
      e.preventDefault();
      // Esc steps away; a draft stays put until Cancel or Add.
      if (!hasNotes(form)) close(form);
      target.blur();
      return;
    }

    if (form && target === form.elements.title && e.key === "Enter" && !e.isComposing) {
      // Enter moves on to the description; Ctrl+Enter (or Add task) saves.
      e.preventDefault();
      if (target.value.trim()) window.NotesEditor.focusEnd(editorOf(form));
    }
  });

  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.detail.elt;
    if (!form.matches?.("[data-composer]") || !e.detail.successful) return;
    form.reset();
    close(form);
    // Ready for the next one.
    form.elements.title.focus();
  });

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

  /* ---- Tasks: keyboard triage ---- */

  // Up/Down (or J/K) move between rows; T today, M tomorrow, D pick a day,
  // X done, E edit, Space opens the description. Dating or finishing a row
  // regroups the page, and the cursor lands on the row that followed it, so
  // a pass down No date never leaves the keyboard.
  const TYPING = "input, textarea, select, [contenteditable]";
  const rows = () => [...document.querySelectorAll("#task-groups .task-row[tabindex]")];
  let landOn = null; // task id to focus once the page has regrouped

  const neighbour = (row) => {
    const all = rows();
    const at = all.indexOf(row);
    return all[at + 1] || all[at - 1] || null;
  };
  const move = (row, step) => {
    const all = rows();
    const at = all.indexOf(row);
    const next = at === -1 ? all[0] : all[Math.max(0, Math.min(all.length - 1, at + step))];
    next?.focus();
    next?.scrollIntoView({ block: "nearest" });
  };

  document.addEventListener("keydown", (e) => {
    if (!document.querySelector(".tasks-page")) return;
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    if (e.target.closest?.(TYPING)) return;
    const row = e.target.closest?.("#task-groups .task-row[tabindex]");
    const key = e.key.toLowerCase();

    if (key === "arrowdown" || key === "j" || key === "arrowup" || key === "k") {
      e.preventDefault();
      move(row, key === "arrowdown" || key === "j" ? 1 : -1);
      return;
    }
    if (!row) return;
    const click = (selector) => {
      const target = row.querySelector(selector);
      if (!target) return false;
      target.click();
      return true;
    };
    const leaving = () => { landOn = neighbour(row)?.dataset.taskId ?? null; };

    if (key === "t" || key === "m") {
      e.preventDefault();
      leaving();
      if (!click(`[data-plan="${key === "t" ? "today" : "tomorrow"}"]`)) landOn = null;
    } else if (key === "d") {
      e.preventDefault();
      leaving();
      click("[data-pick-date]");
    } else if (key === "x") {
      e.preventDefault();
      leaving();
      click(".task-check");
    } else if (key === "e" || key === "enter") {
      e.preventDefault();
      click(".task-title-btn");
    } else if (key === " ") {
      e.preventDefault();
      click(".notes-toggle");
    } else if (key === "escape") {
      row.blur();
    }
  });

  // Reaching for the mouse means the keyboard pass is over (and a cancelled
  // date picker must not leave a landing spot for some later refresh).
  document.addEventListener("pointerdown", () => { landOn = null; }, true);

  // htmx:load fires for the regrouped list; put the cursor where it belongs.
  document.addEventListener("htmx:load", (e) => {
    if (!landOn || !e.detail.elt.matches?.("#task-groups")) return;
    const row = document.getElementById(`task-${landOn}`);
    landOn = null;
    row?.focus();
    row?.scrollIntoView({ block: "nearest" });
  });

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

  /* ---- drafts survive live refreshes ---- */

  // Today's list and the Tasks page re-render from the server whenever the
  // plan changes, composers included. Carry a half-written task, and focus,
  // over to the fresh composer with the same key.
  const carried = new WeakMap(); // request -> drafts
  document.addEventListener("htmx:beforeSwap", (e) => {
    const drafts = [...e.detail.target.querySelectorAll("[data-composer]")]
      .map((form) => ({
        key: form.dataset.composerKey,
        title: form.elements.title.value,
        notes: form.elements.notes.value,
        focus: !form.contains(document.activeElement) ? null
          : document.activeElement === form.elements.title ? "title" : "notes",
      }))
      .filter((d) => d.title || d.notes || d.focus);
    if (drafts.length) carried.set(e.detail.xhr, drafts);
  });
  document.addEventListener("htmx:afterSettle", (e) => {
    const drafts = carried.get(e.detail.xhr);
    if (!drafts) return;
    carried.delete(e.detail.xhr);
    for (const d of drafts) {
      const form = document.querySelector(`[data-composer][data-composer-key="${CSS.escape(d.key)}"]`);
      if (!form) continue;
      form.elements.title.value = d.title;
      form.elements.notes.value = d.notes;
      window.NotesEditor.reload(editorOf(form));
      if (d.title || d.notes) open(form);
      if (d.focus === "title") form.elements.title.focus();
      else if (d.focus === "notes") window.NotesEditor.focusEnd(editorOf(form));
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
