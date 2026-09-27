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
   plain row. Ticking a task's box ticks its task. After a task's title's
   last word come its controls, the task sheet's icons (do date, time, due,
   repeat, project) and Delete; a title too long for the box runs on under
   them, at the box's right, unless the caret is writing there. What they
   set goes with the task when it is added, and straight to it once it has
   been. Delete takes the task's rows out of the notes, and an added task,
   once confirmed, out of the plan.

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

  // One entry per row: null, or {done, id, saved, fields} for a task row (id
  // once it is added; saved: its title and description as last written to
  // it; fields: its do date, time, project and the rest, as the sheet posts
  // them).
  let meta = [];
  // The text and selection as they stood before the edit being followed.
  let lastValue = "";
  let lastSel = [0, 0];

  // A task not yet added is for the notes' day, as the page's other tasks.
  const newFields = (day) => ({
    planned_for: day, time: "", due: "", repeat: "none",
    project_id: "", milestone_id: "", status: "todo", owner: "oscar",
  });

  const readRows = (el) => {
    const lines = el.value.split("\n");
    const rows = lines.map(() => null);
    let marks = [];
    try { marks = JSON.parse(el.dataset.taskRows || "[]"); } catch { /* none */ }
    for (const { row, done, id, fields } of marks) {
      if (row >= rows.length) continue;
      const given = Object.entries(fields || {}).map(([name, value]) => [name, value == null ? "" : String(value)]);
      rows[row] = { done, id, saved: null, fields: { ...newFields(el.dataset.day), ...Object.fromEntries(given) } };
    }
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

  // An added task written whole, as its sheet saves it: its words, fields
  // and done or not. Its title stays what it was while its row is empty.
  async function writeTask(block, { leaving = false } = {}) {
    const m = block.m;
    const content = contentOf(block);
    content.title ||= m.saved?.title || "";
    if (!content.title) return false;
    const status = m.done ? "done" : m.fields.status === "done" ? "todo" : m.fields.status;
    const body = new URLSearchParams({ ...m.fields, status, ...content });
    const res = await post(`/ui/tasks/${m.id}`, body, leaving).catch(() => null);
    if (leaving) return true;
    if (!res?.ok) return false;
    m.saved = content;
    htmx.trigger(document.body, "calendar:refresh");
    return true;
  }

  async function saveTask(block, { leaving = false } = {}) {
    const { title, notes } = contentOf(block);
    const m = block.m;
    if (!title || (m.saved && m.saved.title === title && m.saved.notes === notes)) return;
    if (m.id) {
      const ok = await writeTask(block, { leaving });
      if (leaving) return;
      window.toast(ok ? `Task saved: ${title}` : "Could not save that task. Its words are still in the notes.");
      return;
    }
    const { planned_for, time, due, repeat, project_id } = m.fields;
    const body = new URLSearchParams({ title, notes, planned_for, time, due, repeat, project_id });
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
    // What adding leaves out: its milestone, and a box ticked before it was added.
    if (m.id && (m.done || m.fields.milestone_id)) writeTask(block);
  }

  // A task's controls changed a field: kept for its adding, or written to it.
  // A milestone comes with its project (two changes): one write for both.
  const fieldWrites = new WeakMap(); // meta entry -> timer
  document.addEventListener("sheet:field", (e) => {
    const m = e.target._m;
    if (!m) return;
    m.fields[e.detail.name] = e.detail.value;
    if (e.detail.name === "project_id") m.fields.milestone_id = "";
    if (!m.id) return;
    clearTimeout(fieldWrites.get(m));
    fieldWrites.set(m, setTimeout(async () => {
      const block = blocks().find((b) => b.m === m);
      if (block && !(await writeTask(block))) window.toast("Could not save that change to the task.");
    }));
  });

  /* ---- the columns and marks drawn beside the text ---- */

  const rowsOf = () => document.querySelector(".pad-rows-inner");
  const marksOf = () => document.querySelector(".pad-marks");
  const lineHeight = () => parseFloat(getComputedStyle(pad()).lineHeight) || 36;

  // The text as it reads, drawn under the textarea's clear letters: each row
  // in place, a task's first row darker than the rest (its words in a span,
  // measured for where its controls go). Redrawn when the text or the rows'
  // kinds change; moved with the textarea's scroll.
  let mirrored = "";
  const mirror = (el) => {
    const inner = document.querySelector(".pad-mirror-inner");
    if (!inner) return;
    const key = el.value + "\u0000" + meta.map((m) => (m ? 1 : 0)).join("");
    if (key !== mirrored) {
      mirrored = key;
      inner.replaceChildren(...linesOf().map((line, row) => {
        const div = document.createElement("div");
        if (meta[row]) {
          div.className = "title";
          div.append(document.createElement("span"));
          div.firstChild.textContent = line;
        } else {
          div.textContent = line || "​";
        }
        return div;
      }));
    }
    inner.style.transform = `translate(${-el.scrollLeft}px, ${-el.scrollTop}px)`;
  };

  function draw() {
    const el = pad();
    const rows = rowsOf();
    const marks = marksOf();
    if (!el || !rows || !marks) return;
    mirror(el);
    if (keepCaretClear(el)) mirror(el);
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

    // Every task bracketed; in each task's tab, its box and the word Task;
    // after its title's last word, its controls. Each task keeps its own
    // marks, so a menu open on its controls stays open while the notes are
    // written.
    const lines = linesOf();
    const titles = document.querySelector(".pad-mirror-inner")?.children || [];
    const fresh = [];
    const wanted = all.map((b) => {
      let mark = markOf.get(b.m);
      if (!mark) {
        mark = makeMark(b.m);
        markOf.set(b.m, mark);
        fresh.push(mark.querySelector(".pad-props"));
      }
      mark.classList.toggle("current", b === current);
      // In use: the caret is on its title, or a menu of its controls is open.
      const onTitle = focused && here === b.row;
      mark.classList.toggle("in-use", onTitle || !!mark.querySelector(".prop[aria-expanded='true']"));
      mark.style.top = `${b.row * h - el.scrollTop}px`;
      mark.style.height = `${(b.end - b.row + 1) * h}px`;
      const kind = mark.querySelector(".pad-kind");
      kind.classList.toggle("done", !!b.m.done);
      const box = kind.querySelector(".pad-check");
      box.dataset.row = String(b.row);
      box.setAttribute("aria-checked", String(!!b.m.done));
      box.setAttribute("aria-label", `${b.m.done ? "Not done" : "Done"}: ${lines[b.row].slice(1) || "task"}`);
      return mark;
    });
    if (wanted.length !== marks.childElementCount || wanted.some((mark, i) => marks.children[i] !== mark)) {
      marks.replaceChildren(...wanted);
    }
    // Their icons and menus are the task sheet's (task-sheet.js takes them up).
    for (const form of fresh) form.dispatchEvent(new CustomEvent("htmx:load", { bubbles: true, detail: { elt: form } }));

    // Where the text is: the tab's marks move with it, and the controls go
    // after the title's last word, or, the title running on past the box,
    // at its right with the words fading out under them. The caret writing
    // where they would stand sends them on after the words (out of sight).
    const style = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    const right = box.left + el.clientLeft + el.clientWidth - parseFloat(style.paddingRight);
    all.forEach((b, i) => {
      const line = wanted[i].querySelector(".pad-task-line");
      line.style.setProperty("--pad-x", `${-el.scrollLeft}px`);
      const words = titles[b.row]?.firstElementChild;
      if (!words) return;
      const props = line.querySelector(".pad-props");
      const from = line.getBoundingClientRect().left;
      const text = words.getBoundingClientRect();
      const trailing = text.right + PROPS_GAP;
      const edge = Math.max(right - props.offsetWidth, line.querySelector(".pad-kind").getBoundingClientRect().right + PROPS_GAP);
      const writing = focused && here === b.row && caretX(words) > edge - PROPS_GAP;
      const pinned = trailing > edge && !writing;
      props.style.left = `${(pinned ? edge : trailing) - from}px`;
      const fade = edge - PROPS_GAP - text.left;
      words.style.maskImage = pinned ? `linear-gradient(to right, #000 ${fade - 24}px, transparent ${fade}px)` : "";
    });
  }

  // The caret stays in sight, never under the row numbers. The browser
  // reveals it only to the box's edge, where the numbers stand, and not at
  // all when the page sets it (Home, Left to the row above): a row's start
  // scrolled away comes back, all the way when the caret is within the
  // first screenful of its row, and a caret past the right edge is brought
  // in. True when it scrolled.
  const keepCaretClear = (el) => {
    if (document.activeElement !== el || el.selectionStart !== el.selectionEnd) return false;
    const row = document.querySelector(".pad-mirror-inner")?.children[caret().row];
    if (!row) return false;
    const x = caretX(row.classList.contains("title") ? row.firstElementChild : row);
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const start = box.left + el.clientLeft + parseFloat(style.paddingLeft);
    const end = box.left + el.clientLeft + el.clientWidth - parseFloat(style.paddingRight);
    const along = x + el.scrollLeft - start; // from the row's start, unscrolled
    if (x < start && el.scrollLeft) {
      el.scrollLeft = along < el.clientWidth / 2 ? 0 : el.scrollLeft - (start - x) - el.clientWidth / 4;
    } else if (x > end + 1) {
      el.scrollLeft += x - end;
    } else {
      return false;
    }
    return true;
  };

  const PROPS_GAP = 12;
  // The caret's place in a row's words (drawn in the mirror).
  const caretX = (words) => {
    const node = words.firstChild;
    if (!node) return 0;
    const range = document.createRange();
    const at = Math.min(caret().col, node.length);
    range.setStart(node, at);
    range.setEnd(node, at);
    return range.getBoundingClientRect().left;
  };

  const markOf = new WeakMap(); // meta entry -> its marks
  const makeMark = (m) => {
    const mark = document.createElement("div");
    mark.className = "pad-task-mark";
    // The title's row, clipped at the row numbers as the text is.
    mark.innerHTML = '<div class="pad-task-line"><div class="pad-kind"><button type="button" class="pad-check" role="checkbox"></button><span class="pad-kind-name">Task</span></div></div>';
    const form = document.getElementById("pad-props-template").content.firstElementChild.cloneNode(true);
    for (const [name, value] of Object.entries(m.fields)) if (form.elements[name]) form.elements[name].value = value;
    form._m = m;
    mark.firstElementChild.append(form);
    return mark;
  };

  // Ticking a task's box ticks its task (and its row, in the notes).
  document.addEventListener("pointerdown", (e) => {
    if (e.target.closest?.(".pad-check, [data-pad-remove]")) e.preventDefault(); // the caret stays where it was
  });

  // Delete: an added task goes from the plan (asked first), and its rows
  // from the notes, as an edit the browser's undo can take back (the words
  // come back; the task does not).
  const takeOut = (m) => {
    const block = blocks().find((b) => b.m === m);
    if (!block) return;
    const el = pad();
    const lines = linesOf();
    const last = block.end + 1 >= lines.length;
    // Its rows and one of the newlines around them.
    const from = rowStart(lines, block.row) - (last && block.row > 0 ? 1 : 0);
    const to = last ? el.value.length : rowStart(lines, block.end + 1);
    el.focus();
    el.setSelectionRange(from, to);
    type("");
  };
  document.addEventListener("click", async (e) => {
    const button = e.target.closest?.("[data-pad-remove]");
    const m = button?.closest(".pad-props")?._m;
    const block = m && blocks().find((b) => b.m === m);
    if (!block) return;
    if (m.id) {
      const title = contentOf(block).title || m.saved?.title || "";
      const yes = await window.confirmAction({
        title: "Delete task?",
        name: title,
        detail: "will be deleted, with its rows in these notes and any time blocked for it on the calendar. This can't be undone.",
        action: "Delete",
      });
      if (!yes) return;
      const res = await post(`/ui/tasks/${m.id}/delete`).catch(() => null);
      if (!res?.ok) {
        window.toast("Could not delete that task.");
        return;
      }
      window.toast(`Task deleted: ${title}`);
      htmx.trigger(document.body, "calendar:refresh");
    }
    takeOut(m);
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
    m.fields.status = m.done ? "done" : "todo";
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
    meta[row] = { done: false, id: null, saved: null, fields: newFields(el.dataset.day) };
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
