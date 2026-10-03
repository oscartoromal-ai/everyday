/* Calendar's sheet (partials/day_sheet.html), run as a spreadsheet, as
   Oscar planned his days in Excel: a cell cursor moved by the keys or the
   pointer, a range held with Shift or a drag, cells written by typing.

   Where he stays is written in its cells (an item a column), accommodation
   a checkbox, sorted or not; a Plan cell writes a task for its day; a
   habit's cell, or accommodation's, is ticked by a click or Space, and a
   drag down its column paints the days it crosses. Ctrl+D fills the range
   from its first row (one cell, from the row above), Delete clears it (a
   plan's tasks deleted after asking, as a task's bin does). A
   day whose plan runs over a line folds to its first (its chevron, or
   Alt+Left and Right), and stays folded in this browser. A task's title
   opens its page; so does Ctrl+Enter, on a Plan cell its first task's, and
   writing one, the task just written, to write it out at length.

   Every edit is one POST of ops (/ui/day-sheet), written into the days'
   notes and tasks as they would be there, answered with the sheet drawn
   again; the cursor and the scroll come through the swap. Requests go one
   at a time, in order. */

(() => {
  const sheet = document.getElementById("day-sheet");
  if (!sheet) return;

  const rows = () => [...sheet.querySelectorAll("tbody tr[data-day]")];
  const rowOf = (day) => sheet.querySelector(`tbody tr[data-day="${day}"]`);
  const colCount = () => Number(sheet.dataset.cols);
  const cellAt = (row, col) => row?.querySelector(`.ds-cell[data-col="${col}"]`);
  const writable = (cell) => cell && (cell.dataset.kind === "stay" || cell.dataset.kind === "plan");
  const dayOf = (cell) => cell.closest("tr").dataset.day;
  // Ticked by a click, Space or a drag: a habit's cell, or a stay's checkbox.
  const tickable = (cell) => cell && (cell.dataset.kind === "habit" || cell.dataset.kind === "check");
  const isTicked = (cell) => (cell.dataset.kind === "habit" ? cell.dataset.state === "done" : cell.dataset.done === "true");
  const tickOp = (cell, done) => (cell.dataset.kind === "habit"
    ? { op: "habit", day: dayOf(cell), slug: cell.dataset.slug, done }
    : { op: "stay", day: dayOf(cell), name: cell.dataset.name, done });

  /* ---- the cursor and the range ---- */

  let cursor = null; // {day, col}
  let anchor = null; // the range's other corner, or null
  let editing = null; // {cell, input, day, col}

  const place = () => {
    sheet.querySelectorAll(".is-cursor, .in-range, .has-cursor").forEach((el) => {
      el.classList.remove("is-cursor", "in-range", "has-cursor");
    });
    sheet.querySelectorAll('.ds-cell[tabindex="0"]').forEach((el) => el.setAttribute("tabindex", "-1"));
    if (!cursor || !rowOf(cursor.day)) {
      const today = sheet.querySelector("tr.is-today") || rows()[0];
      cursor = { day: today.dataset.day, col: 1 };
      anchor = null;
    }
    cursor.col = Math.max(0, Math.min(cursor.col, colCount() - 1));
    const row = rowOf(cursor.day);
    const cell = cellAt(row, cursor.col);
    row.classList.add("has-cursor");
    cell.classList.add("is-cursor");
    cell.setAttribute("tabindex", "0");
    const range = rangeCells();
    if (range.cells.length > 1) range.cells.forEach((c) => c.classList.add("in-range"));
    return cell;
  };

  // The range as rows and columns (the cursor's cell alone without one).
  function rangeCells() {
    if (!cursor) return { rows: [], cols: [], cells: [] };
    const all = rows();
    const from = anchor || cursor;
    const a = all.findIndex((r) => r.dataset.day === from.day);
    const b = all.findIndex((r) => r.dataset.day === cursor.day);
    const [top, bottom] = a < 0 ? [b, b] : [Math.min(a, b), Math.max(a, b)];
    const cols = [];
    for (let c = Math.min(from.col, cursor.col); c <= Math.max(from.col, cursor.col); c++) cols.push(c);
    const picked = all.slice(top, bottom + 1);
    return { rows: picked, cols, cells: picked.flatMap((r) => cols.map((c) => cellAt(r, c)).filter(Boolean)) };
  }

  // Keeps a cell in sight, clear of the frozen Day column and the header.
  const reveal = (cell) => {
    const box = sheet.getBoundingClientRect();
    const at = cell.getBoundingClientRect();
    const head = sheet.querySelector("thead").getBoundingClientRect().height;
    const pane = sheet.querySelector("thead .ds-day").getBoundingClientRect().width;
    if (Number(cell.dataset.col) > 0) {
      if (at.left < box.left + pane) sheet.scrollLeft -= box.left + pane - at.left;
      else if (at.right > box.left + sheet.clientWidth) sheet.scrollLeft += at.right - box.left - sheet.clientWidth;
    }
    if (at.top < box.top + head) sheet.scrollTop -= box.top + head - at.top;
    else if (at.bottom > box.top + sheet.clientHeight) sheet.scrollTop += at.bottom - box.top - sheet.clientHeight;
  };

  const moveTo = (day, col, { extend = false, focus = true } = {}) => {
    if (extend) anchor = anchor || { ...cursor };
    else anchor = null;
    cursor = { day, col };
    const cell = place();
    if (cell && focus) {
      cell.focus({ preventScroll: true });
      reveal(cell);
    }
  };

  const step = (dRow, dCol, options) => {
    const all = rows();
    const at = all.findIndex((r) => r.dataset.day === cursor.day);
    const row = all[Math.max(0, Math.min(all.length - 1, at + dRow))];
    moveTo(row.dataset.day, Math.max(0, Math.min(colCount() - 1, cursor.col + dCol)), options);
  };

  /* ---- writing: ops posted in order, the sheet drawn again ---- */

  let queue = Promise.resolve();
  let pending = 0;

  const swap = (html) => {
    const fresh = new DOMParser().parseFromString(html, "text/html").getElementById("day-sheet");
    if (!fresh) return;
    const focused = sheet.contains(document.activeElement);
    sheet.dataset.cols = fresh.dataset.cols;
    sheet.replaceChildren(...fresh.childNodes);
    showFolds();
    if (!cursor) return;
    const cell = place();
    if (focused && cell && !editing) cell.focus({ preventScroll: true });
  };

  // `open`: the task the ops write opens on its page once written.
  const send = (ops, { open = false } = {}) => {
    if (!ops.length) return;
    pending++;
    queue = queue.then(async () => {
      try {
        const res = await fetch(`/ui/day-sheet?start=${sheet.dataset.start}`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
          body: JSON.stringify({ ops }),
        });
        if (!res.ok) {
          const answer = await res.json().catch(() => ({}));
          window.toast(typeof answer.detail === "string" ? answer.detail : "Could not save that. Try again?");
          return refresh(true);
        }
        const created = res.headers.get("X-Task-Created");
        if (open && created) {
          window.location.href = `/tasks/${created}`;
          return;
        }
        swap(await res.text());
      } catch {
        window.toast("Could not save that. Try again?");
      } finally {
        pending--;
      }
    });
  };

  // Drawn again from the days as they stand (notes written elsewhere since).
  async function refresh(force = false) {
    if (!force && (editing || pending || paint)) return;
    const res = await fetch(`/calendar/sheet?start=${sheet.dataset.start}`).catch(() => null);
    if (res?.ok && (force || !(editing || pending || paint))) swap(await res.text());
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });

  // What a cell holds, as an op writing the same into another day's cell.
  const fillOp = (from, to) => {
    if (from.dataset.kind === "stay") return { op: "stay", day: dayOf(to), name: to.dataset.name, value: from.dataset.value };
    if (tickable(from)) return tickOp(to, isTicked(from));
    return null;
  };

  // Ctrl+D: the range's first row down the rest of it; one cell, from the row above.
  const fillDown = () => {
    const range = rangeCells();
    let sources = range.rows[0];
    let targets = range.rows.slice(1);
    if (range.rows.length === 1) {
      const all = rows();
      sources = all[all.indexOf(range.rows[0]) - 1];
      targets = range.rows;
    }
    if (!sources) return;
    send(targets.flatMap((row) => range.cols.map((c) => fillOp(cellAt(sources, c), cellAt(row, c))).filter(Boolean)));
  };

  // Tasks deleted, after asking (their bins, as Projects' rows'); the
  // cursor back on its cell after.
  const deleteTasks = async (bins) => {
    const tasks = new Map(bins.map((b) => [b.dataset.deleteTask, b.dataset.title]));
    if (!tasks.size) return;
    const one = tasks.size === 1;
    const yes = await window.confirmAction({
      title: one ? "Delete task?" : `Delete ${tasks.size} tasks?`,
      name: [...tasks.values()].join(", "),
      detail: "will be deleted. This can't be undone.",
      action: "Delete",
    });
    if (yes) send([...tasks.keys()].map((id) => ({ op: "delete", task: Number(id) })));
    place()?.focus({ preventScroll: true });
  };

  // Delete: the range's stay cleared, its habits and checkboxes unticked,
  // and its plans' tasks deleted, after asking.
  const clear = () => {
    const cells = rangeCells().cells;
    send(cells.flatMap((cell) => {
      if (cell.dataset.kind === "stay" && cell.dataset.value) return [{ op: "stay", day: dayOf(cell), name: cell.dataset.name, value: "" }];
      if (cell.dataset.kind === "habit" && cell.dataset.state) return [tickOp(cell, false)];
      if (cell.dataset.kind === "check" && isTicked(cell)) return [tickOp(cell, false)];
      return [];
    }));
    deleteTasks(cells.flatMap((cell) => [...cell.querySelectorAll("[data-delete-task]")]));
  };

  // Space: the range's habits and checkboxes ticked (unticked when the
  // cursor's is).
  const tick = () => {
    const cell = cellAt(rowOf(cursor.day), cursor.col);
    if (!tickable(cell)) return;
    const done = !isTicked(cell);
    send(rangeCells().cells.filter(tickable).map((c) => tickOp(c, done)));
  };

  /* ---- folding a day to its plan's first line, remembered in this browser ---- */

  const FOLDED = "pc-sheet-folded";
  const folded = new Set((() => {
    try { return JSON.parse(localStorage.getItem(FOLDED)) || []; } catch { return []; }
  })());
  const foldable = () => [...sheet.querySelectorAll("tbody tr[data-foldable]")];

  function showFolds() {
    for (const row of rows()) row.classList.toggle("is-folded", row.hasAttribute("data-foldable") && folded.has(row.dataset.day));
    const all = foldable();
    sheet.classList.toggle("all-folded", all.length > 0 && all.every((r) => folded.has(r.dataset.day)));
  }

  const fold = (days, folding) => {
    for (const row of days) {
      if (folding) folded.add(row.dataset.day);
      else folded.delete(row.dataset.day);
    }
    // The latest days kept, so the list never grows without end.
    try { localStorage.setItem(FOLDED, JSON.stringify([...folded].sort().slice(-400))); } catch { /* private mode */ }
    showFolds();
    if (cursor) reveal(cellAt(rowOf(cursor.day), cursor.col));
  };

  /* ---- writing in a cell: a stay's value, or a task for the day ---- */

  const edit = (cell, { value = null } = {}) => {
    if (!writable(cell)) return;
    const plan = cell.dataset.kind === "plan";
    const input = document.createElement("input");
    input.className = "ds-input";
    input.type = "text";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.value = value ?? (plan ? "" : cell.dataset.value);
    input.placeholder = plan ? "Add a task…" : cell.dataset.name;
    input.setAttribute("aria-label", plan ? `A task for ${dayOf(cell)}` : `${cell.dataset.name} on ${dayOf(cell)}`);
    cell.classList.add("is-editing");
    if (plan) cell.append(input);
    else cell.replaceChildren(input);
    editing = { cell, input, day: dayOf(cell), col: Number(cell.dataset.col), typed: value !== null };
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  };

  // The words written go; the sheet comes back drawn with them. `open`: a
  // task written opens on its page.
  const commit = ({ open = false } = {}) => {
    if (!editing) return;
    const { cell, input, day } = editing;
    editing = null;
    const words = input.value.trim();
    if (cell.dataset.kind === "plan") {
      if (words) send([{ op: "task", day, title: words }], { open });
      else { input.remove(); cell.classList.remove("is-editing"); }
    } else if (words !== cell.dataset.value) {
      send([{ op: "stay", day, name: cell.dataset.name, value: words }]);
    } else {
      refresh(true);
    }
  };

  const cancel = () => {
    if (!editing) return;
    editing = null;
    refresh(true).then(() => moveTo(cursor.day, cursor.col));
  };

  sheet.addEventListener("focusout", (e) => {
    if (editing && e.target === editing.input) commit();
  });

  function writingKey(e) {
    const key = e.key;
    const done = (dRow, dCol) => {
      e.preventDefault();
      e.stopPropagation();
      const from = { day: editing.day, col: editing.col };
      commit();
      cursor = from;
      step(dRow, dCol);
    };
    if (key === "Enter" && (e.ctrlKey || e.metaKey)) {
      // The task written, opened on its page to be written out.
      e.preventDefault();
      e.stopPropagation();
      if (editing.cell.dataset.kind === "plan" && editing.input.value.trim()) commit({ open: true });
      else done(0, 0);
      return;
    }
    if (key === "Enter") { done(e.shiftKey ? -1 : 1, 0); return; }
    if (key === "Tab") { done(0, e.shiftKey ? -1 : 1); return; }
    if (key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); return; }
    if (editing.typed && (key === "ArrowUp" || key === "ArrowDown")) { done(key === "ArrowUp" ? -1 : 1, 0); return; }
    // Everything else is the words' own, and no page key hears it.
    e.stopPropagation();
  }

  /* ---- keys ---- */

  sheet.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (editing) { writingKey(e); return; }
    if (!cursor || document.querySelector("dialog[open]")) return;
    const cell = cellAt(rowOf(cursor.day), cursor.col);
    const key = e.key;
    const handled = () => { e.preventDefault(); e.stopPropagation(); };

    if ((e.ctrlKey || e.metaKey) && !e.altKey) {
      if (key.toLowerCase() === "d") { handled(); fillDown(); return; }
      if (key === "Enter") {
        // A Plan cell's first task, on its page.
        const link = cell.dataset.kind === "plan" && cell.querySelector(".ds-task a.ds-title");
        if (link) { handled(); window.location.href = link.href; }
        return;
      }
      if (key === "Home") { handled(); moveTo(rows()[0].dataset.day, 0, { extend: e.shiftKey }); return; }
      if (key === "End") { const all = rows(); handled(); moveTo(all[all.length - 1].dataset.day, colCount() - 1, { extend: e.shiftKey }); return; }
      return; // other Ctrl keys stay the browser's
    }
    if (e.altKey) {
      if (key === "ArrowLeft" || key === "ArrowRight") {
        // The range's days (or the cursor's) folded, or opened.
        handled();
        fold(rangeCells().rows.filter((r) => r.hasAttribute("data-foldable")), key === "ArrowLeft");
      }
      return;
    }
    const arrows = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (arrows[key]) { handled(); step(...arrows[key], { extend: e.shiftKey }); return; }
    if (key === "PageUp" || key === "PageDown") { handled(); step(key === "PageUp" ? -7 : 7, 0, { extend: e.shiftKey }); return; }
    if (key === "Home") { handled(); moveTo(cursor.day, 0, { extend: e.shiftKey }); return; }
    if (key === "End") { handled(); moveTo(cursor.day, colCount() - 1, { extend: e.shiftKey }); return; }
    if (key === "Tab") {
      // Along the row; past either end, out of the sheet.
      const col = cursor.col + (e.shiftKey ? -1 : 1);
      if (col < 0 || col >= colCount()) return;
      handled();
      step(0, e.shiftKey ? -1 : 1);
      return;
    }
    if (key === "Escape") {
      handled();
      if (anchor) { anchor = null; place(); } else cell.blur();
      return;
    }
    if (key === "Enter" || key === "F2") {
      handled();
      if (cell.dataset.kind === "day") window.location.href = `/day/${cursor.day}`;
      else if (writable(cell)) edit(cell);
      else if (tickable(cell)) tick();
      return;
    }
    if (key === " ") { handled(); tick(); return; }
    if (key === "Delete" || key === "Backspace") { handled(); clear(); return; }
    if (key === "?") return; // the keys dialog (shell.js)
    if (key.length === 1 && writable(cell)) {
      // Typing writes over the cell, as in a spreadsheet.
      handled();
      edit(cell, { value: key });
    }
  });

  /* ---- the pointer: a cell, a range, a column's days painted, a day folded ---- */

  let paint = null; // {col, done, cells}
  let selecting = false;

  const paintCell = (cell) => {
    if (!tickable(cell) || cell.dataset.col !== paint.col || paint.cells.has(cell)) return;
    paint.cells.add(cell);
    cell.classList.toggle("is-painted", paint.done);
    cell.classList.toggle("is-unpainted", !paint.done);
  };

  sheet.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || editing?.input === e.target) return;
    const cell = e.target.closest(".ds-cell");
    if (!cell) return;
    const bin = e.target.closest("[data-delete-task]");
    if (bin) {
      e.preventDefault();
      moveTo(dayOf(cell), Number(cell.dataset.col));
      deleteTasks([bin]);
      return;
    }
    const task = e.target.closest("[data-task]");
    if (task) {
      e.preventDefault();
      moveTo(dayOf(cell), Number(cell.dataset.col));
      send([{ op: "toggle", task: Number(task.dataset.task) }]);
      return;
    }
    const chevron = e.target.closest("[data-fold]");
    if (chevron) {
      // Alt folds or opens every day at once.
      e.preventDefault();
      const row = chevron.closest("tr");
      fold(e.altKey ? foldable() : [row], !row.classList.contains("is-folded"));
      moveTo(row.dataset.day, 0);
      return;
    }
    if (e.target.closest("a")) return; // the day's notes
    e.preventDefault();
    if (editing) commit();
    moveTo(dayOf(cell), Number(cell.dataset.col), { extend: e.shiftKey });
    if (tickable(cell) && !e.shiftKey) {
      paint = { col: cell.dataset.col, done: !isTicked(cell), cells: new Set() };
      paintCell(cell);
    } else {
      selecting = true;
    }
    sheet.setPointerCapture?.(e.pointerId);
  });

  sheet.addEventListener("pointermove", (e) => {
    if (!paint && !selecting) return;
    const cell = document.elementFromPoint(e.clientX, e.clientY)?.closest(".ds-cell");
    if (!cell || !sheet.contains(cell)) return;
    if (paint) {
      // Every day between: a quick drag skips none.
      const all = rows();
      const from = all.indexOf(rowOf(cursor.day));
      const to = all.indexOf(cell.closest("tr"));
      const col = cursor.col;
      for (let i = Math.min(from, to); i <= Math.max(from, to); i++) paintCell(cellAt(all[i], col));
      return;
    }
    if (dayOf(cell) !== cursor.day || Number(cell.dataset.col) !== cursor.col) {
      moveTo(dayOf(cell), Number(cell.dataset.col), { extend: true });
    }
  });

  const endPointer = () => {
    selecting = false;
    if (!paint) return;
    const { done, cells } = paint;
    paint = null;
    const ops = [...cells].filter((c) => isTicked(c) !== done).map((c) => tickOp(c, done));
    if (ops.length) send(ops);
    else cells.forEach((c) => c.classList.remove("is-painted", "is-unpainted"));
  };
  sheet.addEventListener("pointerup", endPointer);
  sheet.addEventListener("pointercancel", endPointer);

  sheet.addEventListener("dblclick", (e) => {
    const cell = e.target.closest(".ds-cell");
    if (writable(cell) && !e.target.closest("[data-task], [data-delete-task], input")) edit(cell);
  });

  // The Day header's chevron folds every day, or opens them all again.
  sheet.addEventListener("click", (e) => {
    if (e.target.closest("[data-fold-all]")) fold(foldable(), !sheet.classList.contains("all-folded"));
  });

  // Today's row in view as the sheet opens, the cursor on it, unfocused, so
  // the page's own keys (the views, Left and Right) still work until a click.
  showFolds();
  place();
  const today = sheet.querySelector("tr.is-today");
  if (today) reveal(cellAt(today, 0));
})();
