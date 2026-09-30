/* A project's Gantt sheet (gantt.html), run as a spreadsheet: a cell
   cursor moved by the keys or the pointer, a range held with Shift or a
   drag, cells written by typing, bars drawn over weeks, moved and stretched
   by dragging or with Alt, rows moved with Alt+Up/Down, and undo.

   Every edit is one POST of ops (app.services.gantt.apply), answered with
   the sheet drawn again; the cursor, the range, the scroll and any cell
   being written come through the swap by row key and column. Requests go
   one at a time, in order. */

(() => {
  const sheet = document.getElementById("gantt");
  if (!sheet) return;
  const project = sheet.dataset.project;
  const FROZEN = 5; // the box, Task, Start, Wks, Due; the weeks follow
  const TITLE = 1;
  const DUE = 4;

  const store = (key, value) => { try { localStorage.setItem(key, value); } catch { /* private mode */ } };
  const saved = (key) => { try { return localStorage.getItem(key); } catch { return null; } };

  /* ---- the grid ---- */

  const table = () => sheet.querySelector(".gantt-table");
  const rows = () => [...sheet.querySelectorAll(".gantt-group > .gantt-row, .gantt-table > .gantt-row.kind-add-milestone")];
  const rowOf = (key) => sheet.querySelector(`.gantt-row[data-key="${CSS.escape(key)}"]`);
  const colCount = () => FROZEN + Number(table().dataset.weekCount);
  const cellAt = (row, col) => row?.querySelector(`.gantt-cell[data-col="${col}"]`);
  const px = (name) => parseFloat(getComputedStyle(sheet).getPropertyValue(name)) || 0;
  const weekWidth = () => px("--gantt-wk");
  const firstWeek = () => table().dataset.firstWeek;
  const addDays = (iso, days) => {
    const d = new Date(`${iso}T12:00:00`);
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  };
  const weekOf = (col) => addDays(firstWeek(), (col - FROZEN) * 7);
  const isWeek = (col) => col >= FROZEN;

  /* ---- the cursor and the range ---- */

  let cursor = null; // {key, col}
  let anchor = null; // the range's other corner, or null

  const place = () => {
    sheet.querySelectorAll(".is-cursor, .in-range, .has-cursor, .col-cursor").forEach((el) => {
      el.classList.remove("is-cursor", "in-range", "has-cursor", "col-cursor");
    });
    sheet.querySelectorAll('.gantt-cell[tabindex="0"]').forEach((el) => el.setAttribute("tabindex", "-1"));
    const all = rows();
    if (!cursor || !rowOf(cursor.key)) {
      const first = all.find((r) => r.dataset.kind === "task") || all[0];
      if (!first) return null;
      cursor = { key: first.dataset.key, col: TITLE };
      anchor = null;
    }
    cursor.col = Math.max(0, Math.min(cursor.col, colCount() - 1));
    const row = rowOf(cursor.key);
    const cell = cellAt(row, cursor.col);
    row.classList.add("has-cursor");
    row.closest(".gantt-group")?.classList.add("has-cursor");
    sheet.querySelector(`.gantt-wk-head[data-col="${cursor.col}"]`)?.classList.add("col-cursor");
    cell.classList.add("is-cursor");
    cell.setAttribute("tabindex", "0");
    const range = rangeRows();
    if (range.cells.length > 1) range.cells.forEach((c) => c.classList.add("in-range"));
    return cell;
  };

  // The range as rows and columns (the cursor's cell alone without one).
  function rangeRows() {
    const all = rows();
    const from = anchor || cursor;
    if (!cursor) return { rows: [], cols: [], cells: [] };
    const a = all.findIndex((r) => r.dataset.key === from.key);
    const b = all.findIndex((r) => r.dataset.key === cursor.key);
    const [top, bottom] = a < 0 ? [b, b] : [Math.min(a, b), Math.max(a, b)];
    const [left, right] = [Math.min(from.col, cursor.col), Math.max(from.col, cursor.col)];
    const picked = all.slice(top, bottom + 1);
    const cols = [];
    for (let c = left; c <= right; c++) cols.push(c);
    const cells = picked.flatMap((r) => cols.map((c) => cellAt(r, c)).filter(Boolean));
    return { rows: picked, cols, cells };
  }

  // Keeps a cell in sight, clear of the frozen pane and the header.
  const reveal = (cell) => {
    const box = sheet.getBoundingClientRect();
    const at = cell.getBoundingClientRect();
    const pane = sheet.querySelector(".gantt-head .gantt-pane").getBoundingClientRect().width;
    const head = sheet.querySelector(".gantt-head").getBoundingClientRect().height;
    const right = box.left + sheet.clientWidth;
    const bottom = box.top + sheet.clientHeight;
    if (isWeek(Number(cell.dataset.col))) {
      if (at.left < box.left + pane) sheet.scrollLeft -= box.left + pane - at.left;
      else if (at.right > right) sheet.scrollLeft += at.right - right;
    }
    if (at.top < box.top + head) sheet.scrollTop -= box.top + head - at.top;
    else if (at.bottom > bottom) sheet.scrollTop += at.bottom - bottom;
  };

  const moveTo = (key, col, { extend = false, focus = true } = {}) => {
    if (extend) anchor = anchor || { ...cursor };
    else anchor = null;
    cursor = { key, col };
    const cell = place();
    if (cell && focus) {
      cell.focus({ preventScroll: true });
      reveal(cell);
    }
  };

  const step = (dRow, dCol, options) => {
    const all = rows();
    const at = all.findIndex((r) => r.dataset.key === cursor.key);
    const row = all[Math.max(0, Math.min(all.length - 1, at + dRow))];
    moveTo(row.dataset.key, Math.max(0, Math.min(colCount() - 1, cursor.col + dCol)), options);
  };

  /* ---- sending edits, one at a time ---- */

  let chain = Promise.resolve();
  const undos = [];
  const redos = [];

  // What a row is now, as an op that would put it back (undo, redo).
  const snapshot = (row) => {
    if (!row) return null;
    const d = row.dataset;
    if (d.kind === "task") {
      return { op: "task", id: Number(d.id), set: { title: d.title, status: d.status, starts_on: d.startsOn, due: d.due } };
    }
    if (d.kind === "milestone") {
      return { op: "milestone", id: Number(d.id), set: { name: d.title, target: d.target, status: d.status } };
    }
    return null;
  };
  const keyOf = (op) => (op.op === "milestone" ? `m${op.id}` : `t${op.id}`);

  // Draws the sheet the server sent, keeping the view where it was.
  const draw = (html) => {
    const before = firstWeek();
    const left = sheet.scrollLeft;
    const top = sheet.scrollTop;
    const hadFocus = sheet.contains(document.activeElement);
    const writing = editing ? { key: editing.key, col: editing.col, value: editing.input.value,
      start: editing.input.selectionStart, end: editing.input.selectionEnd, typed: editing.typed } : null;
    if (editing) editing = null;
    sheet.innerHTML = html;
    // A plan now starting earlier adds weeks before; the same weeks stay in view.
    const shift = (new Date(before) - new Date(firstWeek())) / 864e5 / 7;
    sheet.scrollLeft = left + shift * weekWidth();
    sheet.scrollTop = top;
    const rest = sheet.querySelector("[data-gantt-rest]");
    if (rest) document.getElementById("gantt-rest").textContent = rest.textContent.trim();
    if (cursor && isWeek(cursor.col)) cursor.col += shift;
    if (anchor && isWeek(anchor.col)) anchor.col += shift;
    if (cursor && !rowOf(cursor.key)) cursor = null;
    if (anchor && !rowOf(anchor.key)) anchor = null;
    const cell = place();
    if (cell && hadFocus) cell.focus({ preventScroll: true });
    if (writing && rowOf(writing.key)) {
      const again = cellAt(rowOf(writing.key), writing.col);
      if (again?.dataset.edit) {
        edit(again, { value: writing.value, typed: writing.typed });
        editing.input.setSelectionRange(writing.start, writing.end);
      }
    }
  };

  const post = async (ops) => {
    const response = await fetch(`/ui/projects/${project}/gantt`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify({ ops }),
    });
    if (!response.ok) {
      let detail = "";
      try { detail = (await response.json()).detail; } catch { /* not JSON */ }
      throw new Error(typeof detail === "string" && detail ? detail : "Could not save that. Try again?");
    }
    const made = (response.headers.get("X-Gantt-Made") || "").split(",").filter(Boolean).map(Number);
    return { html: await response.text(), made };
  };

  /* Sends ops. `record` makes it an undo step: its undo ops are the rows'
     state before (snapshots), or given; redo is their state after. `then`
     runs on the drawn sheet, with what was made (to move the cursor);
     `failed` when the server refuses the edit, after its toast. */
  const send = (ops, { record = true, undo = null, redo = undefined, then = null, failed = null } = {}) => {
    chain = chain.then(async () => {
      // Taken when its turn comes, so an edit queued behind another undoes
      // to where that one left the rows, not to before both.
      const before = undo || ops.filter((op) => op.id && (op.op === "task" || op.op === "milestone"))
        .map((op) => snapshot(rowOf(keyOf(op)))).filter(Boolean);
      try {
        const { html, made } = await post(ops);
        draw(html);
        if (record && before.length) {
          const after = redo !== undefined ? redo
            : before.map((op) => snapshot(rowOf(keyOf(op)))).filter(Boolean);
          undos.push({ undo: before, redo: after });
          redos.length = 0;
        }
        then?.(made);
      } catch (error) {
        window.toast(error.message);
        place();
        failed?.();
      }
    });
    return chain;
  };

  const undo = (from, to, which) => {
    const entry = from.pop();
    if (!entry) {
      window.toast(which === "undo" ? "Nothing to undo" : "Nothing to redo");
      return;
    }
    const ops = which === "undo" ? entry.undo : entry.redo;
    if (!ops) {
      window.toast("That cannot be redone");
      return;
    }
    send(ops, { record: false });
    to.push(entry);
    window.toast(which === "undo" ? "Undone" : "Redone");
  };

  /* ---- writing in a cell ---- */

  let editing = null; // {cell, input, key, col, original, typed}

  const cellText = (cell) => {
    const row = cell.closest(".gantt-row");
    if (cell.dataset.edit === "title" || cell.dataset.edit === "name") return row.dataset.title;
    if (cell.dataset.edit === "add" || cell.dataset.edit === "add-milestone") return "";
    return cell.textContent.trim();
  };

  // typed: the words replace what was there, and the arrows leave the cell
  // (Excel's Enter mode); otherwise they move in the words (Edit mode).
  function edit(cell, { value = null, typed = false } = {}) {
    if (!cell?.dataset.edit) return;
    const row = cell.closest(".gantt-row");
    const original = cellText(cell);
    const input = document.createElement("input");
    input.className = "gantt-input";
    input.type = "text";
    input.spellcheck = cell.dataset.edit !== "start" && cell.dataset.edit !== "weeks" && cell.dataset.edit !== "due" && cell.dataset.edit !== "target";
    input.autocomplete = "off";
    input.value = value ?? original;
    input.placeholder = cell.dataset.placeholder || "";
    input.setAttribute("aria-label", cell.dataset.placeholder || `${cell.dataset.edit} of ${row.dataset.title || ""}`);
    cell.classList.add("is-editing");
    cell.append(input);
    editing = { cell, input, key: row.dataset.key, col: Number(cell.dataset.col), original, typed };
    input.focus({ preventScroll: true });
    const end = input.value.length;
    input.setSelectionRange(end, end);
    input.addEventListener("blur", () => {
      if (editing?.input === input) commit();
    });
  }

  const stopEditing = () => {
    if (!editing) return null;
    const was = editing;
    editing = null;
    was.cell.classList.remove("is-editing");
    was.input.remove();
    return was;
  };

  // Ends the writing; sends it when it changed. `then` moves the cursor
  // (its rows are the drawn sheet's, after the edit lands).
  function commit(then = null) {
    const was = stopEditing();
    if (!was) return;
    const value = was.input.value.trim();
    const row = was.cell.closest(".gantt-row");
    const what = was.cell.dataset.edit;
    const refocus = () => { place()?.focus({ preventScroll: true }); };
    // Refused (not a week, say): the cell opens again on what was written.
    const retry = () => {
      const again = cellAt(rowOf(was.key), was.col);
      if (!again) return;
      cursor = { key: was.key, col: was.col };
      anchor = null;
      place();
      edit(again, { value: was.input.value });
    };
    if (value === was.original.trim()) {
      refocus();
      then?.();
      return;
    }
    if (what === "title" || what === "name") {
      if (!value) {
        window.toast(what === "title" ? "A task needs a title" : "A milestone needs a name");
        refocus();
        return;
      }
      const op = what === "title" ? { op: "task", id: Number(row.dataset.id), title: value }
        : { op: "milestone", id: Number(row.dataset.id), name: value };
      refocus();
      send([op], { then: () => then?.(), failed: retry });
      return;
    }
    if (what === "add" || what === "add-milestone") {
      if (!value) { refocus(); then?.(); return; }
      const op = what === "add" ? { op: "create", milestone_id: row.dataset.milestone, title: value }
        : { op: "milestone_create", name: value };
      refocus();
      // Undone, a new task is deleted and a new milestone dropped; neither redoes.
      send([op], {
        record: false,
        failed: retry,
        then: ([id]) => {
          if (!id) return;
          undos.push({
            undo: what === "add" ? [{ op: "delete", id }]
              : [{ op: "milestone", id, set: { name: value, target: "", status: "dropped" } }],
            redo: null,
          });
          redos.length = 0;
          then?.(what === "add" ? `t${id}` : `m${id}`);
        },
      });
      return;
    }
    const op = row.dataset.kind === "milestone"
      ? { op: "milestone", id: Number(row.dataset.id), [what]: value }
      : { op: "task", id: Number(row.dataset.id), [what]: value };
    refocus();
    send([op], { then: () => then?.(), failed: retry });
  }

  const cancel = () => {
    stopEditing();
    place()?.focus({ preventScroll: true });
  };

  /* ---- what the keys and the pointer do to cells ---- */

  const taskRows = (range) => range.rows.filter((r) => r.dataset.kind === "task");

  // Space or Enter on the weeks: each task's bar becomes the weeks chosen.
  const fill = () => {
    const range = rangeRows();
    const weeks = range.cols.filter(isWeek);
    if (!weeks.length) return;
    const span = [weekOf(weeks[0]), weekOf(weeks[weeks.length - 1])];
    const ops = taskRows(range).map((r) => ({ op: "task", id: Number(r.dataset.id), span }));
    if (!ops.length) return;
    // The bars now show the weeks; the range would only tint behind them.
    anchor = null;
    place();
    send(ops);
  };

  const toggle = (row) => {
    const d = row.dataset;
    if (d.kind === "task") send([{ op: "task", id: Number(d.id), done: d.status !== "done" }]);
    if (d.kind === "milestone") send([{ op: "milestone", id: Number(d.id), reached: d.status !== "reached" }]);
  };

  // Delete: clears what the range covers: a bar (its weeks, Start or Wks),
  // a due (and the bar ending on it), a milestone's target.
  const clear = () => {
    const range = rangeRows();
    const ops = [];
    for (const row of range.rows) {
      const id = Number(row.dataset.id);
      if (row.dataset.kind === "task") {
        if (range.cols.includes(DUE) && row.dataset.due) ops.push({ op: "task", id, clear: "due" });
        else if (range.cols.some((c) => c === 2 || c === 3 || isWeek(c)) && row.dataset.startsOn) ops.push({ op: "task", id, clear: "span" });
      } else if (row.dataset.kind === "milestone" && range.cols.includes(DUE) && row.dataset.target) {
        ops.push({ op: "milestone", id, target: "" });
      }
    }
    if (ops.length) send(ops);
  };

  // Alt+Left/Right: bars (or dues, or targets) a week earlier or later;
  // with Shift, the bars' ends.
  const nudge = (by, grow) => {
    const ops = [];
    for (const row of rangeRows().rows) {
      const id = Number(row.dataset.id);
      if (row.dataset.kind === "task" && (grow ? row.dataset.startsOn : row.dataset.due)) {
        ops.push(grow ? { op: "task", id, grow: by } : { op: "task", id, shift: by });
      } else if (row.dataset.kind === "milestone" && !grow && row.dataset.target) {
        ops.push({ op: "milestone", id, shift: by });
      }
    }
    if (!ops.length) return;
    if (isWeek(cursor.col)) {
      cursor.col += by;
      if (anchor && !grow) anchor.col += by;
    }
    send(ops);
  };

  const moveRow = (by) => {
    const row = rowOf(cursor.key);
    if (row?.dataset.kind !== "task") return;
    const id = Number(row.dataset.id);
    anchor = null;
    send([{ op: "move", id, step: by }], {
      undo: [{ op: "move", id, step: -by }], redo: [{ op: "move", id, step: by }],
      then: () => rowOf(`t${id}`) && moveTo(`t${id}`, cursor.col),
    });
  };

  const remove = async () => {
    const doomed = taskRows(rangeRows());
    if (!doomed.length) return;
    const one = doomed.length === 1;
    const yes = await window.confirmAction({
      title: one ? "Delete task?" : `Delete ${doomed.length} tasks?`,
      name: one ? doomed[0].dataset.title : "",
      detail: one ? "" : doomed.map((r) => r.dataset.title).join(", "),
      action: "Delete",
    });
    if (!yes) {
      place()?.focus({ preventScroll: true });
      return;
    }
    // The row that followed takes the cursor.
    const all = rows();
    const last = all.indexOf(doomed[doomed.length - 1]);
    const next = all.slice(last + 1).find((r) => !doomed.includes(r));
    if (next) cursor = { key: next.dataset.key, col: cursor.col };
    anchor = null;
    send(doomed.map((r) => ({ op: "delete", id: Number(r.dataset.id) })), { record: false });
    // A deleted task cannot come back, so no undo step reaches past it.
    undos.length = 0;
    redos.length = 0;
  };

  const copy = () => {
    const range = rangeRows();
    const text = range.rows.map((row) => range.cols.map((c) => {
      const cell = cellAt(row, c);
      if (!cell || isWeek(c)) return "";
      if (c === 0) return row.dataset.status === "done" || row.dataset.status === "reached" ? "x" : "";
      return cellText(cell);
    }).join("\t")).join("\n");
    navigator.clipboard?.writeText(text).then(
      () => window.toast(range.cells.length > 1 ? "Copied the cells" : "Copied"),
      () => window.toast("Could not copy"),
    );
  };

  // Pasted lines onto the Task column write new tasks in the cursor's group,
  // their columns Task, Start, Wks, Due; onto Start, Wks or Due they write
  // those cells, a line a task, down from the cursor.
  const paste = (text) => {
    const lines = text.replace(/\r/g, "").split("\n").filter((l) => l.trim());
    if (!lines.length) return;
    const row = rowOf(cursor.key);
    const grid = lines.map((l) => l.split("\t"));
    if (grid.length === 1 && grid[0].length === 1) {
      const cell = cellAt(row, cursor.col);
      if (cell?.dataset.edit) {
        edit(cell, { value: grid[0][0].trim(), typed: true });
        commit();
      }
      return;
    }
    if (cursor.col === TITLE) {
      const group = row.closest(".gantt-group");
      const add = group?.querySelector(".gantt-row.kind-add");
      if (!add) return;
      const ops = grid.map(([title = "", start = "", weeks = "", due = ""]) => ({
        op: "create", milestone_id: add.dataset.milestone, title: title.trim(), start, weeks, due,
      }));
      send(ops, {
        then: (made) => {
          undos.push({ undo: made.map((id) => ({ op: "delete", id })), redo: null });
          redos.length = 0;
          window.toast(made.length === 1 ? "1 task added" : `${made.length} tasks added`);
        },
        record: false,
      });
      return;
    }
    const names = { 2: "start", 3: "weeks", 4: "due" };
    const all = rows();
    const targets = all.slice(all.indexOf(row)).filter((r) => r.dataset.kind === "task");
    const ops = [];
    grid.forEach((cells, i) => {
      const target = targets[i];
      if (!target) return;
      const op = { op: "task", id: Number(target.dataset.id) };
      cells.forEach((value, j) => { if (names[cursor.col + j]) op[names[cursor.col + j]] = value.trim(); });
      if (Object.keys(op).length > 2) ops.push(op);
    });
    if (ops.length) send(ops);
  };

  /* ---- keys ---- */

  sheet.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (editing) {
      writingKey(e);
      return;
    }
    if (!cursor || document.querySelector("dialog[open]")) return;
    const row = rowOf(cursor.key);
    const cell = cellAt(row, cursor.col);
    const ctrl = e.ctrlKey || e.metaKey;
    const key = e.key;
    const handled = () => { e.preventDefault(); e.stopPropagation(); };

    if (ctrl && !e.altKey) {
      const k = key.toLowerCase();
      if (k === "z" && !e.shiftKey) { handled(); undo(undos, redos, "undo"); return; }
      if (k === "y" || (k === "z" && e.shiftKey)) { handled(); undo(redos, undos, "redo"); return; }
      if (k === "c") { handled(); copy(); return; }
      if (key === "-" || key === "Delete") { handled(); remove(); return; }
      if (key === "Home") { handled(); moveTo(rows()[0].dataset.key, TITLE, { extend: e.shiftKey }); return; }
      if (key === "End") { const all = rows(); handled(); moveTo(all[all.length - 1].dataset.key, colCount() - 1, { extend: e.shiftKey }); return; }
      const jump = { ArrowUp: [-1e4, 0], ArrowDown: [1e4, 0], ArrowLeft: [0, -1e4], ArrowRight: [0, 1e4] }[key];
      if (jump) { handled(); step(...jump, { extend: e.shiftKey }); }
      return; // Ctrl+V comes as a paste event; other Ctrl keys stay the browser's
    }
    if (e.altKey) {
      if (key === "ArrowLeft" || key === "ArrowRight") { handled(); nudge(key === "ArrowLeft" ? -1 : 1, e.shiftKey); }
      if (key === "ArrowUp" || key === "ArrowDown") { handled(); moveRow(key === "ArrowUp" ? -1 : 1); }
      return;
    }
    const arrows = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (arrows[key]) { handled(); step(...arrows[key], { extend: e.shiftKey }); return; }
    if (key === "PageUp" || key === "PageDown") { handled(); step(key === "PageUp" ? -10 : 10, 0, { extend: e.shiftKey }); return; }
    if (key === "Home") { handled(); moveTo(cursor.key, 0, { extend: e.shiftKey }); return; }
    if (key === "End") { handled(); moveTo(cursor.key, colCount() - 1, { extend: e.shiftKey }); return; }
    if (key === "Tab") {
      // Along the row; past either end, out of the sheet.
      const col = cursor.col + (e.shiftKey ? -1 : 1);
      if (col < 0 || col >= colCount()) return;
      handled();
      moveTo(cursor.key, col);
      return;
    }
    if (key === "Escape") {
      if (anchor) { handled(); anchor = null; place(); return; }
      handled();
      cell.blur();
      return;
    }
    if (key === "Enter" || key === "F2") {
      handled();
      if (cell.dataset.edit) edit(cell);
      else if (isWeek(cursor.col)) fill();
      else if (cell.hasAttribute("data-toggle")) toggle(row);
      else if (key === "Enter") step(1, 0);
      return;
    }
    if (key === " ") {
      handled();
      if (cell.hasAttribute("data-toggle")) toggle(row);
      else if (isWeek(cursor.col)) fill();
      else if (cell.dataset.edit) edit(cell, { value: " ", typed: true });
      return;
    }
    if (key === "Delete" || key === "Backspace") { handled(); clear(); return; }
    if (key === "?") return; // the keys dialog (shell.js)
    if (key.length === 1) {
      // Typing writes over the cell, as in a spreadsheet; a cell that is not
      // written in keeps the letters from reaching the page's own keys.
      handled();
      if (cell.dataset.edit) edit(cell, { value: key, typed: true });
    }
  });

  function writingKey(e) {
    const { typed } = editing;
    const key = e.key;
    const done = (dRow, dCol) => {
      e.preventDefault();
      e.stopPropagation();
      const from = { key: editing.key, col: editing.col };
      commit((made) => {
        // A task just written in its group's last row: Enter writes the next
        // (the row is still its group's last), Tab goes on to its Start.
        if (typeof made === "string" && dCol) { moveTo(made, from.col + dCol); return; }
        if (typeof made === "string") { moveTo(from.key, from.col); return; }
        cursor = from;
        step(dRow, dCol);
      });
    };
    if (key === "Enter") { done(e.shiftKey ? -1 : 1, 0); return; }
    if (key === "Tab") { done(0, e.shiftKey ? -1 : 1); return; }
    if (key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); return; }
    if (typed && (key === "ArrowUp" || key === "ArrowDown")) { done(key === "ArrowUp" ? -1 : 1, 0); return; }
    if (typed && (key === "ArrowLeft" || key === "ArrowRight")) { done(0, key === "ArrowLeft" ? -1 : 1); return; }
    // Everything else is the words' own, and no page key hears it.
    e.stopPropagation();
  }

  sheet.addEventListener("paste", (e) => {
    if (editing || !cursor) return;
    e.preventDefault();
    paste(e.clipboardData.getData("text/plain"));
  });

  /* ---- the pointer ---- */

  let drag = null;
  let lastDown = null; // the last press: its cell and when, for a double click
  const DOUBLE_CLICK_MS = 450;

  sheet.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const resize = e.target.closest("[data-gantt-resize]");
    if (resize) { startResize(e); return; }
    // A bar, tick or diamond lies over the week cells: the cell is the one under it.
    const cell = e.target.closest(".gantt-cell[data-col]")
      || document.elementsFromPoint(e.clientX, e.clientY).find((el) => el.matches(".gantt-cell[data-col]"));
    const row = e.target.closest(".gantt-row[data-key]");
    if (!cell || !row) return;
    if (editing && editing.cell === cell) return; // a click inside the words
    if (editing) commit();
    e.preventDefault(); // no text selection; focus is ours to move
    const col = Number(cell.dataset.col);
    const bar = e.target.closest(".gantt-bar, .gantt-diamond, .gantt-tick");
    moveTo(row.dataset.key, col, { extend: e.shiftKey });
    if (e.shiftKey) return;
    // Clicks are read here, not from click events: the capture below sends
    // those to the sheet (and a pointerdown carries no click count). A
    // second click on the same cell soon after writes in it.
    const again = lastDown && lastDown.cell === cell && e.timeStamp - lastDown.at < DOUBLE_CLICK_MS;
    lastDown = { cell, at: e.timeStamp };
    if (again && cell.dataset.edit) {
      lastDown = null;
      edit(cell);
      return;
    }
    drag = {
      x: e.clientX, row, col, moved: false, bar, id: e.pointerId,
      grip: e.target.closest("[data-grip]")?.dataset.grip, toggles: cell.hasAttribute("data-toggle"),
    };
    sheet.setPointerCapture(e.pointerId);
  });

  sheet.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.moved && Math.abs(e.clientX - drag.x) < 4) return;
    drag.moved = true;
    const weeks = Math.round((e.clientX - drag.x) / weekWidth());
    if (drag.bar) {
      drag.weeks = weeks;
      previewBar(weeks);
      return;
    }
    // Over the cells: a range, in this row on the weeks (a bar to draw).
    const under = document.elementFromPoint(e.clientX, e.clientY)?.closest(".gantt-cell[data-col]");
    let col = under ? Number(under.dataset.col) : drag.col + weeks;
    if (isWeek(drag.col)) col = Math.max(FROZEN, col);
    const key = isWeek(drag.col) ? drag.row.dataset.key : under?.closest(".gantt-row[data-key]")?.dataset.key || cursor.key;
    anchor = { key: drag.row.dataset.key, col: drag.col };
    cursor = { key, col: Math.min(colCount() - 1, col) };
    sheet.classList.toggle("is-drawing", isWeek(drag.col) && drag.row.dataset.kind === "task");
    const cell = place();
    if (cell) reveal(cell);
  });

  const endDrag = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const was = drag;
    drag = null;
    sheet.classList.remove("is-drawing");
    if (!was.moved) {
      // A click on the box: done, or a milestone reached.
      if (was.toggles) toggle(was.row);
      return;
    }
    if (was.bar) {
      if (!was.weeks) { resetBar(was); return; }
      const d = was.row.dataset;
      const id = Number(d.id);
      if (was.bar.classList.contains("gantt-diamond")) send([{ op: "milestone", id, shift: was.weeks }]);
      else if (was.grip === "end") send([{ op: "task", id, grow: was.weeks }]);
      else if (was.grip === "start") {
        const last = addDays(d.due, -((new Date(`${d.due}T12:00:00`).getDay() + 6) % 7));
        const first = addDays(d.startsOn, 7 * was.weeks);
        send([{ op: "task", id, span: [first > last ? last : first, last] }]);
      } else send([{ op: "task", id, shift: was.weeks }]);
      if (isWeek(cursor.col) && !was.grip) cursor.col += was.weeks;
      return;
    }
    // A drag over a task's weeks draws its bar there.
    if (isWeek(was.col) && was.row.dataset.kind === "task") fill();
  };
  sheet.addEventListener("pointerup", endDrag);
  sheet.addEventListener("pointercancel", (e) => { if (drag?.bar) resetBar(drag); drag = null; });

  // While a bar is dragged, it moves (or its end or start does) by whole weeks.
  function previewBar(weeks) {
    const { bar, grip } = drag;
    const s = Number(bar.dataset.s ??= getComputedStyle(bar).getPropertyValue("--s") || 0);
    const n = Number(bar.dataset.n ??= getComputedStyle(bar).getPropertyValue("--n") || 1);
    const x = Number(bar.dataset.x ??= getComputedStyle(bar).getPropertyValue("--x") || 0);
    bar.classList.add("is-dragged");
    if (bar.classList.contains("gantt-bar")) {
      if (grip === "end") bar.style.setProperty("--n", Math.max(1, n + weeks));
      else if (grip === "start") {
        const by = Math.min(weeks, n - 1);
        bar.style.setProperty("--s", s + by);
        bar.style.setProperty("--n", n - by);
      } else bar.style.setProperty("--s", s + weeks);
    } else bar.style.setProperty("--x", x + weeks);
  }
  function resetBar(was) {
    const { bar } = was;
    bar.classList.remove("is-dragged");
    for (const name of ["s", "n", "x"]) if (bar.dataset[name] !== undefined) bar.style.setProperty(`--${name}`, bar.dataset[name]);
  }


  // Focus reaching the sheet by Tab lands on the cursor's cell.
  sheet.addEventListener("focusin", (e) => {
    if (e.target.matches(".gantt-cell") && cursor) return;
    if (!editing && e.target === sheet) place()?.focus({ preventScroll: true });
  });

  /* ---- the Task column's width: dragged on its header's edge, remembered ---- */

  const applyWidth = (width) => sheet.style.setProperty("--gantt-title", `${Math.round(width)}px`);
  const savedWidth = Number(saved("pc-gantt-title"));
  if (savedWidth) applyWidth(savedWidth);

  function startResize(e) {
    e.preventDefault();
    const title = sheet.querySelector(".gantt-head .gantt-title");
    const from = title.getBoundingClientRect().width;
    const x = e.clientX;
    const move = (ev) => applyWidth(Math.max(160, Math.min(640, from + ev.clientX - x)));
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      store("pc-gantt-title", String(Math.round(px("--gantt-title"))));
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  }

  /* ---- this week in view: on opening, and on its button ---- */

  const toThisWeek = () => {
    const at = parseFloat(getComputedStyle(table()).getPropertyValue("--this-week")) || 0;
    sheet.scrollLeft = Math.max(0, (at - 1) * weekWidth());
  };
  document.querySelector("[data-gantt-this-week]")?.addEventListener("click", () => {
    toThisWeek();
    const key = cursor?.key;
    if (key) moveTo(key, FROZEN + (parseFloat(getComputedStyle(table()).getPropertyValue("--this-week")) || 0));
  });

  toThisWeek();
  place();
})();
