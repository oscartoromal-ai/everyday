/* A day's notepad (today.html): plain text in rows, like a spreadsheet.

   Down the left run two columns: the rows' numbers, and each row's kind,
   where a task row shows its checkbox and the word Task. Neither is part of
   the text, so neither can be typed over; every row's text starts in the
   same place.

   A task is written in the notes: "- [ ] " at a row's start makes the row a
   task (the marker leaves the text for the checkbox) and opens it, and the
   rows it covers are bracketed until it is closed. Its row is the title;
   rows added under it with Enter are its description ("- " rows its
   sub-tasks). Ctrl+Enter closes it and goes on to the next row, Esc closes
   it where it is; closing adds the task for the day. Ticking a task row's
   box ticks its task. Backspace at the start of a task row makes it a plain
   row again.

   The notes are saved as text, a task row as "- [ ] " or "- [x] " and its
   task by row (links), a moment after each change, when the tab is hidden,
   and when the page is left. A save names the version it was made from;
   one refused because another window saved since stops the saving and asks
   which to keep. Coming back to the tab shows a newer version, when nothing
   here is still to be saved. Left and Right, outside the text, go a day
   back or on. */

(() => {
  const SAVE_AFTER_MS = 600;
  const RETRY_AFTER_MS = 4000;
  const OPENS = "- [ ] ";

  const pad = () => document.getElementById("notepad");
  const staleBar = () => document.getElementById("pad-stale");
  const linesOf = () => pad().value.split("\n");
  const rowAt = (offset) => pad().value.slice(0, offset).split("\n").length - 1;
  const rowStart = (lines, row) => lines.slice(0, row).reduce((n, line) => n + line.length + 1, 0);

  /* ---- rows: which are tasks ---- */

  // One entry per row: null for text, {done, id} for a task (id once it is added).
  let meta = [];
  // The text and selection as they stood before the edit being followed.
  let lastValue = "";
  let lastSel = [0, 0];

  const readRows = (el) => {
    const lines = el.value.split("\n");
    const rows = lines.map(() => null);
    let marks = [];
    try { marks = JSON.parse(el.dataset.taskRows || "[]"); } catch { /* none */ }
    for (const { row, done, id } of marks) if (row < rows.length) rows[row] = { done, id };
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
  // text it replaced (read against the selection it was made from, so a run
  // of repeated characters or blank rows is never misread). Rows wholly
  // before or after that span keep their kind; a row the span starts inside
  // keeps its kind if words of it stand before the span; the row where the
  // old row the span ends in carries on keeps that row's kind if its words
  // after the span remain (Enter at a task row's start moves the task down
  // with its words). Rows the span swallowed are gone, and new rows are text.
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
      // The whole text replaced: what is left is text, not the task it was.
    } else if (added === 0 && r1 === r2) {
      mid[0] = meta[r1] ?? null; // an edit within one row keeps it
    } else {
      if (restOfR2.trim()) mid[added] = meta[r2] ?? null;
      if (c1 > 0) mid[0] = meta[r1] ?? null;
    }
    meta = [...meta.slice(0, r1), ...mid, ...meta.slice(r2 + 1)];
    lastValue = value;
    lastSel = [pad().selectionStart, pad().selectionEnd];
  };

  const serialize = () => {
    const lines = linesOf();
    const links = {};
    const text = lines.map((line, row) => {
      const m = meta[row];
      if (!m) return line;
      if (m.id) links[row] = m.id;
      return `- [${m.done ? "x" : " "}] ${line}`;
    }).join("\n");
    return { text, links };
  };

  /* ---- saving ---- */

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
    if (!el || stale || pending() || task || document.activeElement === el) return;
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

  /* ---- the task being written ---- */

  let task = null; // {row: its row's entry in meta, extra: rows under it}

  const taskRange = () => {
    if (!task) return null;
    const start = meta.indexOf(task.row);
    return start < 0 ? null : { start, end: start + task.extra };
  };

  const openTaskIfTyped = () => {
    const el = pad();
    if (el.selectionStart !== el.selectionEnd) return;
    const lines = linesOf();
    const row = rowAt(el.selectionStart);
    const at = rowStart(lines, row);
    if (meta[row] || !lines[row].startsWith(OPENS) || el.selectionStart !== at + OPENS.length) return;
    // Inside an open task, rows are its description, not tasks of their own.
    const range = taskRange();
    if (range && row >= range.start && row <= range.end + 1) return;
    // The marker leaves the text: the row's kind column draws the checkbox.
    el.setRangeText("", at, at + OPENS.length, "start");
    remember();
    meta[row] = { done: false, id: null };
    if (!task) task = { row: meta[row], extra: 0 };
  };

  // Rows added or taken away inside the open task change what it covers.
  const followTask = (before, after) => {
    if (!task) return;
    const range = taskRange();
    if (!range) {
      task = null;
      return;
    }
    const delta = after - before;
    const row = rowAt(pad().selectionStart);
    if (delta && row >= range.start && row - Math.max(delta, 0) <= range.end) {
      task.extra = Math.max(0, task.extra + delta);
    }
  };

  const addTask = async (row, title, notes) => {
    const day = pad().dataset.day;
    const res = await fetch("/ui/tasks/quick-add", {
      method: "POST",
      headers: { "X-CSRF": window.csrfToken() },
      body: new URLSearchParams({ title, notes, planned_for: day, list_day: day }),
    }).catch(() => null);
    const html = res?.ok ? await res.text() : "";
    const id = Number(/id="task-(\d+)"/.exec(html)?.[1]) || null;
    if (!res?.ok) {
      window.toast("Could not add that task. Its words are still in the notes.");
      return;
    }
    row.id = id;
    window.toast(`Task added: ${title}`);
    htmx.trigger(document.body, "calendar:refresh");
    schedule();
  };

  function closeTask({ nextRow }) {
    const el = pad();
    const range = taskRange();
    const row = task?.row;
    task = null;
    if (!range) return;
    const lines = linesOf();
    const title = lines[range.start].trim();
    const notes = lines.slice(range.start + 1, range.end + 1).join("\n");
    if (nextRow) {
      // On to a fresh row under the task.
      const at = rowStart(lines, range.end) + lines[range.end].length;
      el.setSelectionRange(at, at);
      remember();
      el.setRangeText("\n", at, at, "end");
      followRows();
    }
    draw();
    schedule();
    if (title && !row.id) addTask(row, title, notes);
  }

  /* ---- the columns down the left: numbers, and each row's kind ---- */

  const rowsOf = () => document.querySelector(".pad-rows-inner");
  const lineHeight = () => parseFloat(getComputedStyle(pad()).lineHeight) || 36;
  const TASK_KIND = '<button type="button" class="pad-check" role="checkbox"></button><span class="pad-kind-name">Task</span>';

  function draw() {
    const el = pad();
    const rows = rowsOf();
    if (!el || !rows) return;
    const written = meta.length;
    const shown = Math.ceil(el.clientHeight / lineHeight()) + 1;
    const count = Math.max(written, shown) + Math.ceil(el.scrollTop / lineHeight());
    while (rows.childElementCount < count) {
      const row = document.createElement("div");
      row.innerHTML = `<span class="pad-n">${rows.childElementCount + 1}</span><span class="pad-kind"></span>`;
      rows.append(row);
    }
    while (rows.childElementCount > count) rows.lastElementChild.remove();
    rows.style.transform = `translateY(${-el.scrollTop}px)`;
    const here = rowAt(el.selectionStart);
    const range = taskRange();
    [...rows.children].forEach((row, i) => {
      const m = meta[i];
      const kind = row.lastElementChild;
      if (!!m !== !!kind.firstElementChild) kind.innerHTML = m ? TASK_KIND : "";
      if (m) {
        const box = kind.firstElementChild;
        box.setAttribute("aria-checked", String(m.done));
        box.setAttribute("aria-label", `${m.done ? "Not done" : "Done"}: ${linesOf()[i] || "task"}`);
        box.dataset.row = String(i);
      }
      row.classList.toggle("done", !!m?.done);
      row.classList.toggle("here", i === here && document.activeElement === el);
      row.classList.toggle("task", !!range && i >= range.start && i <= range.end);
    });
    const mark = document.querySelector(".pad-task-mark");
    if (mark) {
      mark.hidden = !range;
      if (range) {
        mark.style.top = `${range.start * lineHeight() - el.scrollTop}px`;
        mark.style.height = `${(range.end - range.start + 1) * lineHeight()}px`;
      }
    }
  }

  // Ticking a task row's box ticks its task (and the row, in the notes).
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
    const res = await fetch(`/ui/tasks/${m.id}/toggle`, {
      method: "POST", headers: { "X-CSRF": window.csrfToken() },
    }).catch(() => null);
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

  document.addEventListener("input", (e) => {
    if (e.target !== pad()) return;
    const before = meta.length;
    followRows();
    openTaskIfTyped();
    followTask(before, meta.length);
    draw();
    schedule();
  });

  ["scroll", "keyup", "click", "focus", "blur"].forEach((type) => {
    document.addEventListener(type, (e) => {
      if (e.target === pad()) draw();
    }, true);
  });
  window.addEventListener("resize", draw);

  document.addEventListener("keydown", (e) => {
    const el = pad();
    if (e.target === el && task && (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey)))) {
      e.preventDefault();
      closeTask({ nextRow: e.key === "Enter" });
      return;
    }
    if (e.target === el && e.key === "Escape") {
      el.blur();
      return;
    }
    // Backspace at a task row's start makes it a plain row again.
    if (e.target === el && e.key === "Backspace" && el.selectionStart === el.selectionEnd) {
      const row = rowAt(el.selectionStart);
      if (meta[row] && el.selectionStart === rowStart(linesOf(), row)) {
        e.preventDefault();
        if (task?.row === meta[row]) task = null;
        meta[row] = null;
        draw();
        schedule();
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

  // Leaving the page: what is written goes, a task still open with it.
  window.addEventListener("pagehide", () => {
    const range = taskRange();
    if (range && !task.row.id) {
      const lines = linesOf();
      const title = lines[range.start].trim();
      const day = pad().dataset.day;
      if (title) {
        fetch("/ui/tasks/quick-add", {
          method: "POST",
          headers: { "X-CSRF": window.csrfToken() },
          body: new URLSearchParams({
            title, notes: lines.slice(range.start + 1, range.end + 1).join("\n"), planned_for: day, list_day: day,
          }),
          keepalive: true,
        });
      }
    }
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
    saved = snapshot();
    draw();
  }

  const el = pad();
  if (el) start(el);
})();
