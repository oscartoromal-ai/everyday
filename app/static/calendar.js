/* The calendar island: drag-to-slot, move/resize blocks, complete/remove.
   The grid is server-rendered and re-rendered via htmx (calendar:refresh);
   all listeners live on document so they survive swaps. */

(() => {
  const SNAP_MIN = 15;
  const DEFAULT_BLOCK_MIN = 60;

  const grid = () => document.getElementById("calendar-grid");
  const dayStartHour = () => Number(grid().dataset.dayStart);
  const hourPx = () => Number(grid().dataset.hourPx);

  const refresh = () => document.body.dispatchEvent(new Event("calendar:refresh"));

  /* ---- scroll position of a height-capped grid (Today's timeline) ---- */

  // First paint lands an hour before now; a refresh keeps wherever Oscar was.
  let keptScroll = null;
  const placeScroll = () => {
    const g = grid();
    if (!g || g.scrollHeight <= g.clientHeight) return;
    if (keptScroll !== null) {
      g.scrollTop = keptScroll;
      keptScroll = null;
      return;
    }
    const now = g.querySelector(".now-line");
    const bodyTop = g.querySelector(".grid-body").offsetTop;
    g.scrollTop = now ? bodyTop + now.offsetTop - hourPx() * 1.5 : bodyTop + hourPx() * 2;
  };
  document.addEventListener("htmx:beforeSwap", (e) => {
    if (e.detail.target?.id === "calendar-grid") keptScroll = e.detail.target.scrollTop;
  });
  document.addEventListener("htmx:load", (e) => {
    if (e.detail.elt?.id === "calendar-grid") placeScroll();
  });
  placeScroll();

  const api = async (method, url, body) => {
    const headers = { "X-CSRF": window.csrfToken ? window.csrfToken() : "" };
    if (body) headers["Content-Type"] = "application/json";
    const res = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = "Something went wrong.";
      try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
      window.toast(detail);
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  };

  /* ---- time math ---- */

  const snapMinutes = (col, clientY) => {
    const rect = col.getBoundingClientRect();
    const raw = ((clientY - rect.top) / hourPx()) * 60 + dayStartHour() * 60;
    const snapped = Math.round(raw / SNAP_MIN) * SNAP_MIN;
    return Math.max(dayStartHour() * 60, Math.min(24 * 60, snapped));
  };

  const isoAt = (dateStr, minutes) => {
    const h = String(Math.floor(minutes / 60)).padStart(2, "0");
    const m = String(minutes % 60).padStart(2, "0");
    return `${dateStr}T${h}:${m}:00`;
  };

  const minutesOf = (iso) => {
    const d = new Date(iso);
    return d.getHours() * 60 + d.getMinutes();
  };

  const colFromPoint = (x, y) =>
    document.elementsFromPoint(x, y).find((el) => el.classList?.contains("day-col"));

  /* ---- drop preview ---- */

  let preview = null;
  const showPreview = (col, minutes, durationMin, label) => {
    if (!preview || preview.parentElement !== col) {
      preview?.remove();
      preview = document.createElement("div");
      preview.className = "cal-item preview";
      col.appendChild(preview);
    }
    const top = ((minutes - dayStartHour() * 60) / 60) * hourPx();
    preview.style.top = `${top}px`;
    preview.style.height = `${(durationMin / 60) * hourPx()}px`;
    preview.textContent = label;
  };
  const clearPreview = () => { preview?.remove(); preview = null; };

  /* ---- 1. drag a task (tray, or Today's list) onto the grid ---- */

  // Task rows inside a [data-drag-to-grid] list become drag sources; re-armed
  // whenever htmx swaps a row in (toggle, edit, quick-add).
  const armRows = () =>
    document
      .querySelectorAll("[data-drag-to-grid] .task-row[data-task-id]")
      .forEach((row) => { row.draggable = !row.classList.contains("done"); });
  armRows();
  document.addEventListener("htmx:load", armRows);

  document.addEventListener("dragstart", (e) => {
    const source = e.target.closest?.("[draggable='true'][data-task-id]");
    if (!source) return;
    e.dataTransfer.setData("text/task-id", source.dataset.taskId);
    e.dataTransfer.setData("text/task-title", source.dataset.taskTitle);
    e.dataTransfer.effectAllowed = "copyMove";
  });

  document.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes("text/task-id")) return;
    const col = e.target.closest?.(".day-col");
    if (!col) { clearPreview(); return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    showPreview(col, snapMinutes(col, e.clientY), DEFAULT_BLOCK_MIN, "");
  });

  document.addEventListener("drop", async (e) => {
    const taskId = e.dataTransfer.getData("text/task-id");
    if (!taskId) return;
    const col = e.target.closest?.(".day-col");
    clearPreview();
    if (!col) return;
    e.preventDefault();
    const startMin = snapMinutes(col, e.clientY);
    await api("POST", "/api/blocks", {
      task_id: Number(taskId),
      start: isoAt(col.dataset.date, startMin),
      end: isoAt(col.dataset.date, startMin + DEFAULT_BLOCK_MIN),
    });
    refresh();
  });

  document.addEventListener("dragend", clearPreview);

  /* ---- 2 & 3. move and resize planned blocks ---- */

  let gesture = null; // {kind: "move"|"resize", el, blockId, startMin, endMin, moved}

  document.addEventListener("pointerdown", (e) => {
    const block = e.target.closest?.(".cal-item.block");
    if (!block || block.dataset.state !== "planned" || e.button !== 0) return;
    const kind = e.target.classList.contains("resize-handle") ? "resize" : "move";
    gesture = {
      kind,
      el: block,
      blockId: Number(block.dataset.blockId),
      date: block.closest(".day-col").dataset.date,
      startMin: minutesOf(block.dataset.start),
      endMin: minutesOf(block.dataset.end),
      originY: e.clientY,
      moved: false,
    };
    block.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  document.addEventListener("pointermove", (e) => {
    if (!gesture) return;
    const dy = e.clientY - gesture.originY;
    if (!gesture.moved && Math.abs(dy) < 4) return;
    gesture.moved = true;
    const durationMin = gesture.endMin - gesture.startMin;
    if (gesture.kind === "move") {
      const col = colFromPoint(e.clientX, e.clientY) || gesture.el.closest(".day-col");
      const startMin = Math.min(snapMinutes(col, e.clientY), 24 * 60 - durationMin);
      gesture.target = { col, startMin, endMin: startMin + durationMin };
      gesture.el.style.opacity = "0.45";
      showPreview(col, startMin, durationMin, gesture.el.querySelector(".item-title").textContent);
    } else {
      const col = gesture.el.closest(".day-col");
      const endMin = Math.max(
        snapMinutes(col, e.clientY),
        gesture.startMin + SNAP_MIN
      );
      gesture.target = { col, startMin: gesture.startMin, endMin };
      const top = ((gesture.startMin - dayStartHour() * 60) / 60) * hourPx();
      gesture.el.style.height = `${((endMin - gesture.startMin) / 60) * hourPx()}px`;
      gesture.el.style.top = `${top}px`;
    }
  });

  const endGesture = async (e) => {
    if (!gesture) return;
    const g = gesture;
    gesture = null;
    clearPreview();
    g.el.style.opacity = "";
    if (!g.moved) {
      if (e.type === "pointerup") openBlockMenu(g.el, e);
      return;
    }
    if (!g.target) return;
    await api("PATCH", `/api/blocks/${g.blockId}`, {
      start: isoAt(g.target.col.dataset.date, g.target.startMin),
      end: isoAt(g.target.col.dataset.date, g.target.endMin),
    });
    refresh();
  };

  document.addEventListener("pointerup", endGesture);
  document.addEventListener("pointercancel", endGesture);

  /* ---- 4. block menu: complete / remove ---- */

  let menu = null;
  const closeMenu = () => { menu?.remove(); menu = null; };

  function openBlockMenu(block, e) {
    closeMenu();
    const template = document.getElementById("block-menu-template");
    menu = template.content.firstElementChild.cloneNode(true);
    menu.querySelector(".block-menu-title").textContent =
      block.querySelector(".item-title").textContent;
    // The task's sub-tasks load into the menu, tickable while in the block.
    menu.querySelector(".block-menu-checklist")
      .setAttribute("hx-get", `/ui/tasks/${block.dataset.taskId}/checklist`);
    document.body.appendChild(menu);
    const place = () => {
      const rect = block.getBoundingClientRect();
      const left = Math.min(rect.right + 8, window.innerWidth - menu.offsetWidth - 12);
      menu.style.left = `${Math.max(12, left)}px`;
      const bottom = window.scrollY + window.innerHeight - menu.offsetHeight - 12;
      menu.style.top = `${Math.max(window.scrollY + 12, Math.min(rect.top + window.scrollY, bottom))}px`;
    };
    place();
    menu.addEventListener("htmx:afterSettle", place); // re-fit once the checklist is in
    htmx.process(menu);
    const blockId = block.dataset.blockId;
    menu.addEventListener("click", async (ev) => {
      const action = ev.target.dataset?.action;
      if (!action) return;
      closeMenu();
      if (action === "complete") await api("POST", `/api/blocks/${blockId}/complete`);
      if (action === "delete") await api("DELETE", `/api/blocks/${blockId}`);
      refresh();
    });
  }

  document.addEventListener("pointerdown", (e) => {
    if (menu && !menu.contains(e.target)) closeMenu();
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

  /* completed blocks: click opens the menu too (to undo nothing, just remove) */
  document.addEventListener("click", (e) => {
    const block = e.target.closest?.(".cal-item.block");
    if (block && block.dataset.state === "completed") openBlockMenu(block, e);
  });
})();
