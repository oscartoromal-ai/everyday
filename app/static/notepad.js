/* A day's notepad (today.html): plain text in rows, like a spreadsheet,
   the rows numbered down the left.

   A task is written in the notes. "- [ ] " at a row's start makes the row a
   task: the marker becomes a tab, and in the gap the page draws the task's
   checkbox and the word Task (not text, so neither can be typed over). Enter
   in a task starts its next row tabbed in the same way, so its description
   lines up under its title ("- " rows its sub-tasks); Enter on an empty
   tabbed row steps back out to a plain row. Backspace at a tabbed row's start
   takes its tab away, and a task row, or a row of one, is plain again. Plain
   rows stay at the left: only a task's rows are tabbed in.

   Every task is bracketed by a rule above its title and below its last row,
   always; the task the caret is in has its row numbers in ink. Ctrl+Enter or
   Esc in a task saves it (adds it for the day, or writes its title and
   description to the task it made), Ctrl+Enter then going on to a fresh
   plain row. Ticking a task's box ticks its task.

   The notes are saved as text, a task row as "- [ ] " or "- [x] " and the
   task it made by row (links), a moment after each change, when the tab is
   hidden, and when the page is left. A save names the version it was made
   from; one refused because another window saved since stops the saving and
   asks which to keep. Coming back to the tab shows a newer version, when
   nothing here is still to be saved. Left and Right, outside the text, go a
   day back or on. */

(() => {
  const SAVE_AFTER_MS = 600;
  const RETRY_AFTER_MS = 4000;
  const OPENS = "- [ ] ";
  const TAB = "\t";

  const pad = () => document.getElementById("notepad");
  const staleBar = () => document.getElementById("pad-stale");
  const linesOf = () => pad().value.split("\n");
  const rowAt = (offset) => pad().value.slice(0, offset).split("\n").length - 1;
  const rowStart = (lines, row) => lines.slice(0, row).reduce((n, line) => n + line.length + 1, 0);
  const caret = () => {
    const el = pad();
    const lines = linesOf();
    const row = rowAt(el.selectionStart);
    return { row, col: el.selectionStart - rowStart(lines, row), lines };
  };
  // Typed as if by hand, so the browser's own undo keeps it.
  const type = (text) => document.execCommand("insertText", false, text);

  /* ---- rows: which are tasks ---- */

  // One entry per row: null, or {done, id, saved} for a task row (id once it
  // is added; saved: its title and description as last written to it).
  let meta = [];
  // The text and selection as they stood before the edit being followed.
  let lastValue = "";
  let lastSel = [0, 0];

  const readRows = (el) => {
    const lines = el.value.split("\n");
    const rows = lines.map(() => null);
    let marks = [];
    try { marks = JSON.parse(el.dataset.taskRows || "[]"); } catch { /* none */ }
    for (const { row, done, id } of marks) if (row < rows.length) rows[row] = { done, id, saved: null };
    return rows;
  };

  const remember = () => {
    const el = pad();
    lastValue = el.value;
    lastSel = [el.selectionStart, el.selectionEnd];
  };
  document.addEventListener("beforeinput", (e) => {
    if (e.target === pad()) remember();
  }, true);

  // After an edit, rows keep their kind. The edit is the span of the old
  // text it replaced (read against the selection it was made from, so runs
  // of repeated characters or blank rows are never misread). Rows wholly
  // before or after it keep their kind; an edit within one row keeps it;
  // otherwise a row the span starts inside keeps its kind if words of it
  // stand before the span, and the row the old row where the span ends
  // carries on as keeps that row's kind if its words after the span remain.
  // Clearing the whole text leaves no tasks. A task row that has lost its
  // tab is plain.
  const followRows = () => {
    const value = pad().value;
    const old = lastValue;
    let head = 0;
    const headMax = Math.min(old.length, value.length, lastSel[0]);
    while (head < headMax && old[head] === value[head]) head++;
    let tail = 0;
    const tailMax = Math.min(old.length - Math.max(head, lastSel[1]), value.length - head);
    while (tail < tailMax && old[old.length - 1 - tail] === value[value.length - 1 - tail]) tail++;
    const cutEnd = old.length - tail;
    const inserted = value.slice(head, value.length - tail);
    const r1 = old.slice(0, head).split("\n").length - 1;
    const c1 = head - (old.lastIndexOf("\n", head - 1) + 1);
    const r2 = old.slice(0, cutEnd).split("\n").length - 1;
    const rowEnd = old.indexOf("\n", cutEnd);
    const restOfR2 = old.slice(cutEnd, rowEnd < 0 ? old.length : rowEnd);
    const added = inserted.split("\n").length - 1;
    const mid = Array.from({ length: added + 1 }, () => null);
    if (head === 0 && cutEnd === old.length && old.length) {
      // The whole text replaced: nothing of it is a task any more.
    } else if (added === 0 && r1 === r2) {
      mid[0] = meta[r1] ?? null;
    } else {
      if (restOfR2.trim()) mid[added] = meta[r2] ?? null;
      if (c1 > 0) mid[0] = meta[r1] ?? null;
    }
    meta = [...meta.slice(0, r1), ...mid, ...meta.slice(r2 + 1)];
    const lines = value.split("\n");
    meta = meta.map((m, row) => (m && lines[row]?.startsWith(TAB) ? m : null));
    lastValue = value;
    lastSel = [pad().selectionStart, pad().selectionEnd];
  };

  // A task: its row and the tabbed rows under it that are not tasks themselves.
  const blocks = () => {
    const lines = linesOf();
    const out = [];
    meta.forEach((m, row) => {
      if (!m) return;
      let end = row;
      while (end + 1 < lines.length && !meta[end + 1] && lines[end + 1].startsWith(TAB)) end++;
      out.push({ row, end, m });
    });
    return out;
  };
  const blockAt = (row) => blocks().find((b) => row >= b.row && row <= b.end) || null;
  const contentOf = (block) => {
    const lines = linesOf();
    return {
      title: lines[block.row].slice(1).trim(),
      notes: lines.slice(block.row + 1, block.end + 1).map((line) => line.slice(1)).join("\n"),
    };
  };

  const serialize = () => {
    const lines = linesOf();
    const links = {};
    const text = lines.map((line, row) => {
      const m = meta[row];
      if (!m) return line;
      if (m.id) links[row] = m.id;
      return `- [${m.done ? "x" : " "}] ${line.slice(1)}`;
    }).join("\n");
    return { text, links };
  };

  /* ---- saving the notes ---- */

  let version = 0;
  let saved = "";
  let timer = 0;
  let inflight = false;
  let again = false;
  let stale = false;
  let theirs = 0;

  const snapshot = () => JSON.stringify(serialize());
  const pending = () => !!pad() && snapshot() !== saved;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(flush, SAVE_AFTER_MS);
  };

  async function flush({ leaving = false } = {}) {
    clearTimeout(timer);
    const el = pad();
    if (!el || stale || !pending()) return;
    if (inflight && !leaving) {
      again = true;
      return;
    }
    const page = serialize();
    const state = JSON.stringify(page);
    const request = fetch(`/ui/notebook/${el.dataset.day}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify({
        version,
        blocks: page.text.trim() ? [{ kind: "text", text: page.text, links: page.links }] : [],
      }),
      keepalive: leaving,
    });
    if (leaving) return;
    inflight = true;
    try {
      const res = await request;
      const answer = await res.json().catch(() => ({}));
      if (res.ok) {
        version = answer.version;
        saved = state;
      } else if (res.status === 409) {
        stale = true;
        theirs = answer.version;
        staleBar().hidden = false;
      } else {
        window.toast(answer.detail || "Could not save the notes.");
      }
    } catch {
      // Offline for a moment: what is written stays here and goes later.
      setTimeout(schedule, RETRY_AFTER_MS);
    } finally {
      inflight = false;
    }
    if (again) {
      again = false;
      flush();
    }
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest?.("[data-pad-reload]")) {
      stale = true; // what is here is being let go
      location.reload();
    } else if (e.target.closest?.("[data-pad-keep]")) {
      stale = false;
      version = theirs;
      staleBar().hidden = true;
      flush();
    }
  });

  // Back to notes written elsewhere since (the phone, another window).
  const refresh = async () => {
    const el = pad();
    if (!el || stale || pending() || document.activeElement === el) return;
    const res = await fetch(`/ui/notebook/${el.dataset.day}/version`).catch(() => null);
    const answer = res?.ok ? await res.json() : null;
    if (!answer || answer.version <= version) return;
    const page = await fetch(location.pathname).then((r) => r.text()).catch(() => null);
    const fresh = page && new DOMParser().parseFromString(page, "text/html").getElementById("notepad");
    if (!fresh || pending() || document.activeElement === el) return;
    start(fresh, el);
  };

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
    else refresh();
  });

  /* ---- saving a task ---- */

  const post = (url, body, keepalive = false) =>
    fetch(url, { method: "POST", headers: { "X-CSRF": window.csrfToken() }, body, keepalive });

  async function saveTask(block, { leaving = false } = {}) {
    const { title, notes } = contentOf(block);
    const m = block.m;
    if (!title || (m.saved && m.saved.title === title && m.saved.notes === notes)) return;
    const day = pad().dataset.day;
    if (m.id) {
      const res = await fetch(`/api/tasks/${m.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
        body: JSON.stringify({ title, notes }),
        keepalive: leaving,
      }).catch(() => null);
      if (leaving) return;
      if (!res?.ok) {
        window.toast("Could not save that task. Its words are still in the notes.");
        return;
      }
      m.saved = { title, notes };
      window.toast(`Task saved: ${title}`);
      return;
    }
    const body = new URLSearchParams({ title, notes, planned_for: day, list_day: day });
    const res = await post("/ui/tasks/quick-add", body, leaving).catch(() => null);
    if (leaving) return;
    const html = res?.ok ? await res.text() : "";
    if (!res?.ok) {
      window.toast("Could not add that task. Its words are still in the notes.");
      return;
    }
    m.id = Number(/id="task-(\d+)"/.exec(html)?.[1]) || null;
    m.saved = { title, notes };
    window.toast(`Task added: ${title}`);
    htmx.trigger(document.body, "calendar:refresh");
    schedule();
  }

  /* ---- the columns and marks drawn beside the text ---- */

  const rowsOf = () => document.querySelector(".pad-rows-inner");
  const marksOf = () => document.querySelector(".pad-marks");
  const lineHeight = () => parseFloat(getComputedStyle(pad()).lineHeight) || 36;

  function draw() {
    const el = pad();
    const rows = rowsOf();
    const marks = marksOf();
    if (!el || !rows || !marks) return;
    const h = lineHeight();
    const written = meta.length;
    const count = Math.max(written, Math.ceil(el.clientHeight / h) + 1) + Math.ceil(el.scrollTop / h);
    while (rows.childElementCount < count) {
      const row = document.createElement("div");
      row.textContent = String(rows.childElementCount + 1);
      rows.append(row);
    }
    while (rows.childElementCount > count) rows.lastElementChild.remove();
    rows.style.transform = `translateY(${-el.scrollTop}px)`;

    const { row: here } = caret();
    const focused = document.activeElement === el;
    const all = blocks();
    const current = focused ? all.find((b) => here >= b.row && here <= b.end) : null;
    [...rows.children].forEach((row, i) => {
      row.classList.toggle("here", focused && i === here);
      row.classList.toggle("task", !!current && i >= current.row && i <= current.end);
    });

    // Every task bracketed; in each task's tab, its box and the word Task.
    const lines = linesOf();
    marks.replaceChildren(...all.map((b) => {
      const mark = document.createElement("div");
      mark.className = "pad-task-mark";
      mark.classList.toggle("current", b === current);
      mark.style.top = `${b.row * h - el.scrollTop}px`;
      mark.style.height = `${(b.end - b.row + 1) * h}px`;
      const kind = document.createElement("div");
      kind.className = "pad-kind";
      kind.classList.toggle("done", !!b.m.done);
      kind.style.transform = `translateX(${-el.scrollLeft}px)`;
      kind.innerHTML = '<button type="button" class="pad-check" role="checkbox"></button><span class="pad-kind-name">Task</span>';
      const box = kind.firstElementChild;
      box.dataset.row = String(b.row);
      box.setAttribute("aria-checked", String(!!b.m.done));
      box.setAttribute("aria-label", `${b.m.done ? "Not done" : "Done"}: ${lines[b.row].slice(1) || "task"}`);
      mark.append(kind);
      return mark;
    }));
  }

  // Ticking a task's box ticks its task (and its row, in the notes).
  document.addEventListener("pointerdown", (e) => {
    if (e.target.closest?.(".pad-check")) e.preventDefault(); // the caret stays where it was
  });
  document.addEventListener("click", async (e) => {
    const box = e.target.closest?.(".pad-check");
    if (!box) return;
    const m = meta[Number(box.dataset.row)];
    if (!m) return;
    m.done = !m.done;
    draw();
    schedule();
    if (!m.id) return;
    const res = await post(`/ui/tasks/${m.id}/toggle`).catch(() => null);
    if (!res?.ok) {
      m.done = !m.done;
      draw();
      schedule();
      window.toast("Could not tick that task.");
      return;
    }
    htmx.trigger(document.body, "calendar:refresh");
  });

  /* ---- typing ---- */

  // "- [ ] " at a row's start: the row becomes a task, its marker a tab.
  const makeTaskIfTyped = () => {
    const el = pad();
    if (el.selectionStart !== el.selectionEnd) return;
    const { row, col, lines } = caret();
    if (meta[row] || col !== OPENS.length || !lines[row].startsWith(OPENS)) return;
    const at = rowStart(lines, row);
    el.setSelectionRange(at, at + OPENS.length);
    type(TAB);
    meta[row] = { done: false, id: null, saved: null };
  };

  document.addEventListener("input", (e) => {
    if (e.target !== pad()) return;
    followRows();
    makeTaskIfTyped();
    draw();
    schedule();
  });

  // The caret never stands before a tabbed row's tab: its words start after it.
  document.addEventListener("selectionchange", () => {
    const el = pad();
    if (!el || document.activeElement !== el || el.selectionStart !== el.selectionEnd) return;
    const { col, row, lines } = caret();
    if (col === 0 && lines[row].startsWith(TAB)) el.setSelectionRange(el.selectionStart + 1, el.selectionStart + 1);
  });

  ["scroll", "keyup", "click", "focus", "blur"].forEach((kind) => {
    document.addEventListener(kind, (e) => {
      if (e.target === pad()) draw();
    }, true);
  });
  window.addEventListener("resize", draw);

  document.addEventListener("keydown", (e) => {
    const el = pad();
    if (e.target === el && !e.isComposing) {
      const { row, col, lines } = caret();
      const block = blockAt(row);
      const plainKeys = !e.ctrlKey && !e.metaKey && !e.altKey;

      // Ctrl+Enter or Esc in a task saves it; Ctrl+Enter goes on to a fresh plain row.
      if (block && (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey)))) {
        e.preventDefault();
        saveTask(block);
        if (e.key === "Enter") {
          const at = rowStart(lines, block.end) + lines[block.end].length;
          el.setSelectionRange(at, at);
          type("\n");
        }
        return;
      }
      if (e.key === "Escape") {
        el.blur();
        return;
      }
      if (e.key === "Enter" && plainKeys && !e.shiftKey && lines[row].startsWith(TAB)) {
        e.preventDefault();
        if (lines[row] === TAB && !meta[row]) {
          // An empty row of a task: out of it, to a plain row.
          el.setSelectionRange(el.selectionStart - 1, el.selectionStart);
          type("");
        } else {
          type(`\n${TAB}`); // the task's next row, lined up under its title
        }
        return;
      }
      // A tabbed row's words start after its tab: Home goes there, and
      // Backspace there takes the tab away (the row is plain again).
      if (lines[row].startsWith(TAB) && plainKeys && el.selectionStart === el.selectionEnd) {
        const at = rowStart(lines, row);
        if (e.key === "Home" && !e.shiftKey) {
          e.preventDefault();
          el.setSelectionRange(at + 1, at + 1);
          return;
        }
        if (e.key === "Backspace" && col <= 1) {
          e.preventDefault();
          el.setSelectionRange(at, at + 1);
          type("");
          return;
        }
      }
      // Left at a tabbed row's first word goes on to the row above, past the tab.
      if (e.key === "ArrowLeft" && plainKeys && !e.shiftKey && col === 1 && lines[row].startsWith(TAB) && row > 0) {
        e.preventDefault();
        const at = rowStart(lines, row) - 1;
        el.setSelectionRange(at, at);
        return;
      }
    }
    // Left and Right, outside the text, change the day.
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (e.target.closest?.("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]")) return;
    const link = document.querySelector(`[data-day-step="${e.key === "ArrowLeft" ? "prev" : "next"}"]`);
    if (!link) return;
    e.preventDefault();
    flush();
    link.click();
  });

  // Leaving the page: what is written goes, and every task written or changed with it.
  window.addEventListener("pagehide", () => {
    for (const block of blocks()) saveTask(block, { leaving: true });
    if (pending()) flush({ leaving: true });
  });

  /* ---- start ---- */

  // Take up the notes (or a fresher copy of them, into the page's textarea).
  function start(source, target = source) {
    if (source !== target) {
      target.value = source.value;
      target.dataset.version = source.dataset.version;
    }
    meta = readRows(source);
    lastValue = target.value;
    lastSel = [target.selectionStart, target.selectionEnd];
    version = Number(source.dataset.version) || 0;
    // What the notes say of each task now is what was last written to it.
    for (const block of blocks()) block.m.saved = contentOf(block);
    saved = snapshot();
    draw();
  }

  const el = pad();
  if (el) start(el);
})();
