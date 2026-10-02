/* The calendar island, on Calendar's grid and Today's timeline: drag a task
   onto the grid to give it time; move and resize planned blocks and Oscar's
   own events; draw on the grid (or click it) to write an event there, or to
   give the time to a task; click an event for its card, a block for its
   menu. On Calendar, D, X and W switch the days shown and E writes an event.
   The grid is server-rendered and re-rendered via htmx (calendar:refresh);
   all listeners live on document so they survive swaps. */

(() => {
  const SNAP_MIN = 15;
  const CLICK_SNAP_MIN = 30;
  const DEFAULT_BLOCK_MIN = 60;
  const DAY_MIN = 24 * 60;

  const grid = () => document.getElementById("calendar-grid");
  const hourPx = () => Number(grid().dataset.hourPx);
  const usualStartHour = () => Number(grid().dataset.dayStart);

  const refresh = () => document.body.dispatchEvent(new Event("calendar:refresh"));

  /* ---- where the grid opens: the usual day, with now in view ---- */

  // A refresh keeps wherever Oscar was.
  let keptScroll = null;
  const placeScroll = () => {
    const g = grid();
    if (!g || g.scrollHeight <= g.clientHeight) return;
    if (keptScroll !== null) {
      g.scrollTop = keptScroll;
      keptScroll = null;
      return;
    }
    const body = g.querySelector(".grid-body");
    const head = body.offsetTop; // the sticky head's height sits over the body
    const at = (hours) => body.offsetTop + hours * hourPx() - head;
    const view = g.clientHeight - head;
    // The usual day's start a little under the head, its label whole; past
    // its end, no further than the usual day's end at the foot.
    const usual = at(usualStartHour()) - 8;
    const latest = Math.max(usual, at(22) - view);
    const now = g.querySelector(".now-line");
    let top = usual;
    if (now) {
      const nowAt = at(now.offsetTop / hourPx());
      top = Math.min(Math.max(nowAt - 1.5 * hourPx(), usual), latest);
      // Now stays in view, an hour clear of either edge.
      top = Math.min(Math.max(top, nowAt - view + hourPx()), nowAt - hourPx());
    }
    g.scrollTop = top;
  };
  document.addEventListener("htmx:beforeSwap", (e) => {
    if (e.detail.target?.id === "calendar-grid") keptScroll = e.detail.target.scrollTop;
  });
  document.addEventListener("htmx:load", (e) => {
    if (e.detail.elt?.id === "calendar-grid") {
      placeScroll();
      composer?.sync(); // its preview, drawn on the grid just swapped in
    }
  });
  placeScroll();

  const api = async (method, url, body) => {
    const headers = { "X-CSRF": window.csrfToken ? window.csrfToken() : "" };
    let payload;
    if (body instanceof FormData) {
      payload = body;
    } else if (body) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await fetch(url, { method, headers, body: payload });
    if (!res.ok) {
      let detail = "Something went wrong.";
      try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
      window.toast(typeof detail === "string" ? detail : "Could not save that. Try again?");
      throw new Error(detail);
    }
    return res.status === 204 || !res.headers.get("content-type")?.includes("json") ? null : res.json();
  };

  /* ---- time math ---- */

  const pad = (n) => String(n).padStart(2, "0");
  const hhmm = (minutes) => `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`;

  const minutesAt = (col, clientY) => {
    const rect = col.getBoundingClientRect();
    return ((clientY - rect.top) / hourPx()) * 60;
  };
  const snapMinutes = (col, clientY, step = SNAP_MIN, round = Math.round) =>
    Math.max(0, Math.min(DAY_MIN, round(minutesAt(col, clientY) / step) * step));

  // 24:00 is the next day's midnight, as an event ending at midnight is stored.
  const isoAt = (dateStr, minutes) => {
    if (minutes < DAY_MIN) return `${dateStr}T${hhmm(minutes)}:00`;
    const [y, m, d] = dateStr.split("-").map(Number);
    const next = new Date(y, m - 1, d + 1);
    return `${next.getFullYear()}-${pad(next.getMonth() + 1)}-${pad(next.getDate())}T00:00:00`;
  };

  // Minutes from the start of the day `iso` falls on, or 24:00 for an end at the next midnight.
  const minutesOf = (iso, dateStr) => {
    const [day, clock] = iso.split("T");
    const [h, m] = clock.split(":").map(Number);
    return day !== dateStr && h === 0 && m === 0 ? DAY_MIN : h * 60 + m;
  };
  const minutesOfField = (value) => {
    if (!value) return null;
    const [h, m] = value.split(":").map(Number);
    return h * 60 + m;
  };

  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const dayLabel = (dateStr) => {
    const [y, m, d] = dateStr.split("-").map(Number);
    const day = new Date(y, m - 1, d);
    return `${DAYS[day.getDay()]} ${day.getDate()} ${MONTHS[day.getMonth()]}`;
  };
  const lengthLabel = (minutes) => {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return [h && `${h}h`, m && `${m}m`].filter(Boolean).join(" ");
  };

  const colFromPoint = (x, y) =>
    document.elementsFromPoint(x, y).find((el) => el.classList?.contains("day-col"));
  const colOf = (dateStr) => grid()?.querySelector(`.day-col[data-date="${dateStr}"]`);

  /* ---- a preview on the grid: a drop, a move, or the time being written ---- */

  const makePreview = () => {
    const el = document.createElement("div");
    el.className = "cal-item preview";
    return el;
  };
  const drawPreview = (el, col, startMin, endMin, label) => {
    if (el.parentElement !== col) col.appendChild(el);
    el.style.top = `${(startMin / 60) * hourPx()}px`;
    el.style.height = `${Math.max(((endMin - startMin) / 60) * hourPx() - 2, 12)}px`;
    el.textContent = label;
  };

  let preview = null;
  const showPreview = (col, startMin, durationMin, label) => {
    preview ||= makePreview();
    drawPreview(preview, col, startMin, startMin + durationMin, label);
  };
  const clearPreview = () => { preview?.remove(); preview = null; };

  /* ---- floating cards: one at a time (the block menu, an event's card, the composer) ---- */

  let floating = null; // {el, close}
  const closeFloating = () => {
    const f = floating;
    floating = null;
    f?.close();
  };
  const float = (el, close) => {
    closeFloating();
    document.body.appendChild(el);
    floating = { el, close: () => { el.remove(); close?.(); } };
  };

  // Beside the anchor, on whichever side has room, within the viewport.
  const placeBeside = (el, rect) => {
    const gap = 8;
    const margin = 12;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    let left = rect.right + gap;
    if (left + w > window.innerWidth - margin) left = rect.left - gap - w;
    if (left < margin) left = Math.min(Math.max(margin, rect.left), window.innerWidth - margin - w);
    const top = Math.max(margin, Math.min(rect.top, window.innerHeight - margin - h));
    el.style.left = `${Math.max(margin, left) + window.scrollX}px`;
    el.style.top = `${top + window.scrollY}px`;
  };
  // Under a button, as its menu: from its left edge, within the viewport.
  const placeBelow = (el, rect) => {
    const margin = 12;
    const left = Math.max(margin, Math.min(rect.left, window.innerWidth - margin - el.offsetWidth));
    el.style.left = `${left + window.scrollX}px`;
    el.style.top = `${rect.bottom + 6 + window.scrollY}px`;
  };

  // A press outside closes the card, and does nothing else on the grid.
  let closedByPress = false;
  document.addEventListener("pointerdown", (e) => {
    closedByPress = false;
    if (floating && !floating.el.contains(e.target) && !e.target.closest?.("#confirm-dialog")) {
      closeFloating();
      closedByPress = true;
    }
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !floating || document.querySelector("dialog[open]")) return;
    e.preventDefault();
    closeFloating();
  });

  /* ---- 1. drag a task (tray, or Today's list) onto the grid ---- */

  // Task rows inside a [data-drag-to-grid] list become drag sources; re-armed
  // whenever htmx swaps a row in (toggle, edit, quick-add).
  const armRows = () =>
    document
      .querySelectorAll("[data-drag-to-grid] .task-row[data-task-id]")
      .forEach((row) => { row.draggable = !row.classList.contains("done"); });
  armRows();
  document.addEventListener("htmx:load", armRows);

  // A task dropped takes its estimate's length, else an hour. A drag's data
  // cannot be read until the drop, so the length is kept as it starts.
  let dragLength = DEFAULT_BLOCK_MIN;
  const lengthOf = (el) => Math.min(Number(el.dataset.estimate) || DEFAULT_BLOCK_MIN, DAY_MIN);

  document.addEventListener("dragstart", (e) => {
    const source = e.target.closest?.("[draggable='true'][data-task-id]");
    if (!source) return;
    e.dataTransfer.setData("text/task-id", source.dataset.taskId);
    e.dataTransfer.setData("text/task-title", source.dataset.taskTitle);
    e.dataTransfer.effectAllowed = "copyMove";
    dragLength = lengthOf(source);
  });

  document.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes("text/task-id")) return;
    const col = e.target.closest?.(".day-col");
    if (!col) { clearPreview(); return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    const start = Math.min(snapMinutes(col, e.clientY), DAY_MIN - dragLength);
    showPreview(col, start, dragLength, lengthLabel(dragLength));
  });

  document.addEventListener("drop", async (e) => {
    const taskId = e.dataTransfer.getData("text/task-id");
    if (!taskId) return;
    const col = e.target.closest?.(".day-col");
    clearPreview();
    if (!col) return;
    e.preventDefault();
    const startMin = Math.min(snapMinutes(col, e.clientY), DAY_MIN - dragLength);
    await api("POST", "/api/blocks", {
      task_id: Number(taskId),
      start: isoAt(col.dataset.date, startMin),
      end: isoAt(col.dataset.date, startMin + dragLength),
    });
    refresh();
  });

  document.addEventListener("dragend", clearPreview);

  /* ---- 2. on the grid with the pointer: move and resize what is movable,
     open what is clicked, draw a new event's time on the empty grid ---- */

  let gesture = null;
  // move/resize: {kind, el, url, date, startMin, endMin, grabMin, originY, moved, target}
  // draw: {kind: "draw", col, anchorMin, originY, touch, moved, startMin, endMin}

  document.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !grid()?.contains(e.target)) return;
    const item = e.target.closest(".cal-item");
    if (item?.classList.contains("movable")) {
      const col = item.closest(".day-col");
      const date = col.dataset.date;
      const startMin = minutesOf(item.dataset.start, date);
      gesture = {
        kind: e.target.classList.contains("resize-handle") ? "resize" : "move",
        el: item,
        url: item.dataset.blockId ? `/api/blocks/${item.dataset.blockId}` : `/api/events/${item.dataset.eventId}`,
        date,
        startMin,
        endMin: minutesOf(item.dataset.end, date),
        grabMin: minutesAt(col, e.clientY) - startMin,
        originY: e.clientY,
        moved: false,
      };
      item.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    if (item) return; // a click, below
    const col = e.target.closest(".day-col");
    if (!col || closedByPress) return;
    // Touch scrolls the grid: a tap writes an event, a drag never draws.
    const touch = e.pointerType === "touch";
    gesture = {
      kind: "draw",
      col,
      anchorMin: snapMinutes(col, e.clientY),
      clickMin: snapMinutes(col, e.clientY, CLICK_SNAP_MIN, Math.floor),
      originY: e.clientY,
      touch,
      moved: false,
    };
    if (!touch) {
      col.setPointerCapture(e.pointerId);
      e.preventDefault();
    }
  });

  document.addEventListener("pointermove", (e) => {
    if (!gesture) return;
    const dy = e.clientY - gesture.originY;
    if (!gesture.moved && Math.abs(dy) < 4) return;
    gesture.moved = true;
    if (gesture.kind === "draw") {
      if (gesture.touch) return;
      const at = snapMinutes(gesture.col, e.clientY);
      gesture.startMin = Math.min(gesture.anchorMin, at);
      gesture.endMin = Math.max(gesture.anchorMin, at, gesture.startMin + SNAP_MIN);
      showPreview(gesture.col, gesture.startMin, gesture.endMin - gesture.startMin,
        `${hhmm(gesture.startMin)}–${hhmm(gesture.endMin)}`);
      return;
    }
    const durationMin = gesture.endMin - gesture.startMin;
    if (gesture.kind === "move") {
      const col = colFromPoint(e.clientX, e.clientY) || gesture.el.closest(".day-col");
      // The item keeps where it was held: its start moves as far as the pointer.
      const at = minutesAt(col, e.clientY) - gesture.grabMin;
      const startMin = Math.max(0, Math.min(Math.round(at / SNAP_MIN) * SNAP_MIN, DAY_MIN - durationMin));
      gesture.target = { col, startMin, endMin: startMin + durationMin };
      gesture.el.style.opacity = "0.45";
      showPreview(col, startMin, durationMin, gesture.el.querySelector(".item-title").textContent);
    } else {
      const col = gesture.el.closest(".day-col");
      const endMin = Math.max(snapMinutes(col, e.clientY), gesture.startMin + SNAP_MIN);
      gesture.target = { col, startMin: gesture.startMin, endMin };
      gesture.el.style.height = `${((endMin - gesture.startMin) / 60) * hourPx()}px`;
    }
  });

  const endGesture = async (e) => {
    if (!gesture) return;
    const g = gesture;
    gesture = null;
    if (g.kind === "draw") {
      if (e.type !== "pointerup" || (g.touch && g.moved)) { clearPreview(); return; }
      // A click takes the half hour it landed in, for an hour.
      const startMin = g.moved ? g.startMin : Math.min(g.clickMin, DAY_MIN - DEFAULT_BLOCK_MIN);
      const endMin = g.moved ? g.endMin : startMin + DEFAULT_BLOCK_MIN;
      clearPreview();
      openComposer({ day: g.col.dataset.date, startMin, endMin, onGrid: true });
      return;
    }
    clearPreview();
    g.el.style.opacity = "";
    if (!g.moved) {
      if (e.type === "pointerup") openItem(g.el);
      return;
    }
    if (!g.target) return;
    await api("PATCH", g.url, {
      start: isoAt(g.target.col.dataset.date, g.target.startMin),
      end: isoAt(g.target.col.dataset.date, g.target.endMin),
    }).catch(() => {});
    refresh();
  };

  document.addEventListener("pointerup", endGesture);
  document.addEventListener("pointercancel", endGesture);

  // What isn't movable opens on a click: a work meeting, an all-day event, a completed block.
  document.addEventListener("click", (e) => {
    if (!grid()?.contains(e.target)) return;
    const item = e.target.closest(".cal-item:not(.movable), .allday-pill");
    if (item) openItem(item);
  });

  const openItem = (item) => {
    if (item.dataset.eventId) openEventCard(item);
    else if (item.dataset.blockId) openBlockMenu(item);
  };

  /* ---- 3. a block's menu: its sub-tasks, complete, remove ---- */

  function openBlockMenu(block) {
    const template = document.getElementById("block-menu-template");
    const menu = template.content.firstElementChild.cloneNode(true);
    menu.querySelector(".block-menu-title").textContent =
      block.querySelector(".item-title").textContent;
    // The task's sub-tasks load into the menu, tickable while in the block.
    menu.querySelector(".block-menu-checklist")
      .setAttribute("hx-get", `/ui/tasks/${block.dataset.taskId}/checklist`);
    float(menu);
    const place = () => placeBeside(menu, block.getBoundingClientRect());
    place();
    menu.addEventListener("htmx:afterSettle", place); // re-fit once the checklist is in
    htmx.process(menu);
    const blockId = block.dataset.blockId;
    menu.addEventListener("click", async (ev) => {
      const action = ev.target.dataset?.action;
      if (!action) return;
      closeFloating();
      if (action === "complete") await api("POST", `/api/blocks/${blockId}/complete`);
      if (action === "delete") await api("DELETE", `/api/blocks/${blockId}`);
      refresh();
    });
  }

  /* ---- 4. an event's card: what, when, where (Join), and for Oscar's own, change or delete ---- */

  async function openEventCard(item) {
    const card = document.createElement("div");
    card.className = "event-card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", "Event");
    card.tabIndex = -1;
    const res = await fetch(`/ui/events/${item.dataset.eventId}/card`);
    if (!res.ok) { window.toast("Could not open that event."); return; }
    card.innerHTML = await res.text();
    float(card);
    placeBeside(card, item.getBoundingClientRect());
    htmx.process(card);
    card.focus({ preventScroll: true });
    // Saved or deleted: the grid refreshes (HX-Trigger) and the card goes.
    card.addEventListener("htmx:afterRequest", (ev) => {
      if (ev.detail.successful && floating?.el === card) closeFloating();
    });
  }

  /* ---- 5. the composer: an event written over the time drawn, or a task given it ---- */

  let composer = null; // {form, sync, ...}

  // A time in the title's words: "13:00-14:00", as the task sheet writes it.
  const applyWords = (form, field) => {
    const f = form.elements;
    if (field.name === "planned_for") {
      const previous = f.day.value;
      f.day.value = field.value;
      return () => { f.day.value = previous; };
    }
    if (field.name === "time") {
      const previous = [f.start_time.value, f.end_time.value];
      const [start, end] = field.value.split("-");
      f.start_time.value = start;
      f.end_time.value = end;
      return () => { [f.start_time.value, f.end_time.value] = previous; };
    }
    if (field.name === "repeat") {
      const previous = f.repeat.value;
      f.repeat.value = field.value;
      return () => { f.repeat.value = previous; };
    }
    return null; // "due friday" means nothing for an event: the words stay words
  };

  function openComposer({ day, startMin = null, endMin = null, onGrid = false, anchor = null }) {
    const template = document.getElementById("event-composer-template");
    const form = template.content.firstElementChild.cloneNode(true);
    const f = form.elements;
    const title = form.querySelector(".composer-title");
    const note = form.querySelector(".composer-note");
    const picks = form.querySelector(".composer-tasks");
    const pickList = form.querySelector(".composer-task-list");
    f.day.value = day;
    if (startMin !== null) {
      f.start_time.value = hhmm(startMin);
      f.end_time.value = hhmm(Math.min(endMin, DAY_MIN - 1)); // the fields' last minute is 23:59
    }
    const ownPreview = makePreview();
    ownPreview.classList.add("composing");

    const times = () => {
      const start = minutesOfField(f.start_time.value);
      const end = minutesOfField(f.end_time.value);
      if (start === null || end === null) return null;
      return end > start ? { start, end } : null;
    };

    // The note says what the fields make; the preview shows it on the grid,
    // and the tasks are offered while there is a time to give.
    const sync = () => {
      const t = times();
      const empty = !f.start_time.value && !f.end_time.value;
      note.textContent = empty ? "No time: all day" : t ? lengthLabel(t.end - t.start) : "Ends before it starts";
      note.classList.toggle("error", !empty && !t);
      const col = t && f.day.value && colOf(f.day.value);
      if (col) drawPreview(ownPreview, col, t.start, t.end, title.value.trim() || "New event");
      else ownPreview.remove();
      picks.hidden = !onGrid || !t || !filterPicks();
    };

    // The tasks offered: those to schedule in the days shown, narrowed by the title's words.
    let active = -1;
    const visiblePicks = () => [...pickList.querySelectorAll(".composer-task")].filter((b) => !b.closest("li").hidden);
    const filterPicks = () => {
      const words = title.value.trim().toLowerCase();
      let shown = 0;
      pickList.querySelectorAll("li").forEach((li) => {
        const match = shown < 6 && li.textContent.toLowerCase().includes(words);
        li.hidden = !match;
        if (match) shown += 1;
      });
      setActive(Math.min(active, shown - 1));
      return shown;
    };
    const setActive = (i) => {
      active = i;
      visiblePicks().forEach((b, n) => b.classList.toggle("active", n === i));
    };

    const giveTask = async (button) => {
      const t = times();
      if (!t) return;
      await api("POST", "/api/blocks", {
        task_id: Number(button.dataset.taskId),
        start: isoAt(f.day.value, t.start),
        end: isoAt(f.day.value, t.end),
      });
      closeFloating();
      window.toast(`“${button.dataset.taskTitle}” booked ${dayLabel(f.day.value)}, ${hhmm(t.start)}–${hhmm(t.end)}`);
      refresh();
    };

    // Typed words become fields, as in the task sheet; Backspace right after puts them back.
    let converted = null; // {value, caret, undo}
    title.addEventListener("input", (e) => {
      converted = null;
      if (e.inputType === "insertText" && e.data === " ") {
        const caret = title.selectionStart;
        const field = window.TaskSheet?.fieldOfWords(title.value.slice(0, caret));
        const undo = field && applyWords(form, field);
        if (undo) {
          const before = title.value;
          title.value = before.slice(0, field.start) + before.slice(caret);
          title.setSelectionRange(field.start, field.start);
          converted = { before, caret, at: field.start, undo };
        }
      }
      sync();
    });
    title.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && converted && title.selectionStart === converted.at && title.selectionEnd === converted.at) {
        e.preventDefault();
        converted.undo();
        const { before, caret } = converted;
        converted = null;
        title.value = before.slice(0, caret - 1) + before.slice(caret); // the space goes with the Backspace
        title.setSelectionRange(caret - 1, caret - 1);
        sync();
        return;
      }
      const shown = visiblePicks();
      if (!picks.hidden && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        const step = e.key === "ArrowDown" ? 1 : -1;
        setActive(Math.max(-1, Math.min(shown.length - 1, active + step)));
        return;
      }
      if (e.key === "Enter" && !picks.hidden && active >= 0) {
        e.preventDefault();
        giveTask(shown[active]);
      }
    });

    // A start moved keeps the length; an end is never left before the start.
    let length = times() ? times().end - times().start : DEFAULT_BLOCK_MIN;
    f.start_time.addEventListener("change", () => {
      const start = minutesOfField(f.start_time.value);
      if (start !== null) f.end_time.value = hhmm(Math.min(start + length, DAY_MIN - 1));
      sync();
    });
    f.end_time.addEventListener("change", () => {
      const t = times();
      if (t) length = t.end - t.start;
      sync();
    });
    f.day.addEventListener("change", sync);
    form.addEventListener("input", (e) => { if (e.target !== title) sync(); });

    pickList.addEventListener("click", (e) => {
      const button = e.target.closest(".composer-task");
      if (button) giveTask(button);
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      // The title's last words, closed without a space, are read too.
      const text = title.value.replace(/\s+$/, "");
      const field = text && window.TaskSheet?.fieldOfWords(`${text} `);
      if (field && applyWords(form, field)) title.value = text.slice(0, field.start).trim();
      const name = title.value.trim();
      if (!name) { title.focus(); return; }
      const empty = !f.start_time.value && !f.end_time.value;
      const t = times();
      if (!empty && !t) { window.toast("The event ends before it starts."); return; }
      const data = new FormData();
      data.set("title", name);
      data.set("day", f.day.value);
      data.set("repeat", f.repeat.value);
      if (t) {
        data.set("start_time", hhmm(t.start));
        data.set("end_time", hhmm(t.end));
      } else {
        data.set("all_day", "true");
      }
      await api("POST", "/ui/events", data);
      closeFloating();
      const when = t ? `${dayLabel(f.day.value)}, ${hhmm(t.start)}` : `${dayLabel(f.day.value)}, all day`;
      window.toast(`Event added: ${name}, ${when}`);
      refresh();
    });

    float(form, () => {
      ownPreview.remove();
      if (composer?.form === form) composer = null;
    });
    composer = { form, sync };
    sync();
    const anchorRect = anchor?.getBoundingClientRect() || ownPreview.getBoundingClientRect();
    if (anchor) placeBelow(form, anchorRect);
    else placeBeside(form, anchorRect);
    title.focus({ preventScroll: true });

    if (onGrid) {
      const g = grid();
      fetch(`/calendar/tray?start=${g.dataset.start}&days=${g.dataset.days}&pick=true`)
        .then((res) => (res.ok ? res.text() : ""))
        .then((html) => {
          if (composer?.form !== form) return;
          pickList.innerHTML = html;
          sync();
          placeBeside(form, ownPreview.isConnected ? ownPreview.getBoundingClientRect() : anchorRect);
        });
    }
  }

  // New event (E): today if it is shown, else the first day shown; no time yet (all day).
  const newEvent = (button) => {
    const g = grid();
    const today = g.querySelector(".day-col.today");
    openComposer({ day: (today || g.querySelector(".day-col")).dataset.date, anchor: button });
  };
  document.addEventListener("click", (e) => {
    const button = e.target.closest?.("[data-new-event]");
    if (button) newEvent(button);
  });

  /* ---- 6. Calendar's keys: D, X and W the days shown, E a new event ---- */

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return;
    if (e.target.closest?.("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]")) return;
    if (!document.querySelector(".calendar-page")) return;
    const key = e.key.toUpperCase();
    const view = document.querySelector(`[data-calendar-view][aria-keyshortcuts="${key}"]`);
    if (view) {
      e.preventDefault();
      if (!view.hasAttribute("aria-current")) view.click();
      return;
    }
    if (key === "E") {
      e.preventDefault();
      newEvent(document.querySelector("[data-new-event]"));
    }
  });
})();
