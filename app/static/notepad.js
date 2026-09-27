/* A day's notepad (today.html): plain text in rows, like a spreadsheet, the
   rows numbered down the left. A CodeMirror 6 editor (vendor/codemirror.js,
   window.CM) over the page's textarea, which holds the notes as the server
   sends them. A row too long for the box wraps inside its row.

   A task is written in the notes. "- [ ] " at a row's start makes the row a
   task: its "- [ ] " is drawn as the task's checkbox and the word Task (one
   piece, never typed into), and after the title's last word, at the row's
   right, come its controls: the task sheet's icons (do date, time, due,
   repeat, project) and Delete, on the title's last line when they fit there
   and on a line of their own under it when not. Enter in a task starts its
   next row with a tab, drawn as the same indent, so its description lines
   up under its title ("- " rows its sub-tasks); Enter on an empty tabbed row
   steps back out to a plain row. Backspace at a row's first word takes its
   box or tab away, and the row is plain again.

   Every task is bracketed by a rule above its title and below its last row,
   always; the task the caret is in has its rules and row numbers in ink.
   Ctrl+Enter or Esc in a task saves it (adds it for the day, with what its
   controls set, or writes its title and description to the task it made),
   Ctrl+Enter then going on to a fresh plain row. Ticking a task's box ticks
   its task; its controls write to it straight away once it is added.
   Delete takes its rows out of the notes, and an added task, once
   confirmed, out of the plan.

   The notes are saved as text, the task each row made by row (links), a
   moment after each change, when the tab is hidden, and when the page is
   left. A save names the version it was made from; one refused because
   another window saved since stops the saving and asks which to keep.
   Coming back to the tab shows a newer version, when nothing here is still
   to be saved. Left and Right, outside the text, go a day back or on. */

(() => {
  const {
    Annotation, EditorSelection, EditorState, MapMode, Prec, RangeSetBuilder, StateEffect, StateField,
    Transaction, Decoration, EditorView, GutterMarker, ViewPlugin, WidgetType, drawSelection,
    gutterLineClass, keymap, lineNumberWidgetMarker, lineNumbers, placeholder, defaultKeymap, history,
    historyKeymap, invertedEffects, isolateHistory,
  } = window.CM;

  const SAVE_AFTER_MS = 600;
  const RETRY_AFTER_MS = 4000;
  const TASK = /^- \[([ xX])\] /; // a task row's box
  const BOX = 6; // its length
  const TAB = "\t"; // a task's other rows start with one

  const source = () => document.getElementById("notepad");
  let view = null;
  let day = "";

  /* ---- tasks: which rows made which task ---- */

  // Each task row's task: {id, saved, fields}. id once it is added; saved:
  // its title and description as last written to it; fields: its do date,
  // time, project and the rest, as the sheet posts them. A task not yet
  // added is for the notes' day.
  const newFields = () => ({
    planned_for: day, time: "", due: "", repeat: "none",
    project_id: "", milestone_id: "", status: "todo", owner: "oscar",
  });
  const newTask = () => ({ id: null, saved: null, fields: newFields() });

  const isTask = (line) => TASK.test(line.text);
  const setTasks = StateEffect.define();
  // Tasks an edit took away, back with the undo that brings their rows back.
  const restoreTasks = StateEffect.define({
    map: (list, mapping) => list.map(({ pos, m }) => ({ pos: mapping.mapPos(pos, 1), m })),
  });

  // Every task row has its task: the one it had, else a new one.
  const tidy = (list, doc) => {
    const at = new Map();
    for (const { pos, m } of list) {
      if (pos == null || pos > doc.length || at.has(pos)) continue;
      const line = doc.lineAt(pos);
      if (line.from === pos && isTask(line)) at.set(pos, m);
    }
    const out = [];
    for (let n = 1; n <= doc.lines; n++) {
      const line = doc.line(n);
      if (isTask(line)) out.push({ pos: line.from, m: at.get(line.from) || newTask() });
    }
    return out;
  };

  // [{pos, m}]: each task row's start and its task. A row keeps its task
  // through edits around it (Enter at its first word moves it down with its
  // words), and loses it with its box.
  const tasksField = StateField.define({
    create: () => [],
    update(list, tr) {
      let next = null;
      for (const e of tr.effects) if (e.is(setTasks)) next = e.value;
      if (!next && tr.docChanged) {
        next = list.map(({ pos, m }) => ({ pos: tr.changes.mapPos(pos, 1, MapMode.TrackAfter), m }));
      }
      for (const e of tr.effects) if (e.is(restoreTasks)) next = [...e.value, ...(next || list)];
      return next ? tidy(next, tr.state.doc) : list;
    },
  });
  const keepTasks = invertedEffects.of((tr) => {
    if (!tr.docChanged) return [];
    const kept = new Set(tr.state.field(tasksField).map(({ m }) => m));
    const lost = tr.startState.field(tasksField).filter(({ m }) => !kept.has(m));
    return lost.length ? [restoreTasks.of(lost)] : [];
  });

  // A task: its title row and the tabbed rows under it that are not tasks
  // themselves (line numbers).
  const blocksOf = (state) => {
    const doc = state.doc;
    return state.field(tasksField).map(({ m, pos }) => {
      const first = doc.lineAt(pos).number;
      let last = first;
      while (last < doc.lines) {
        const next = doc.line(last + 1);
        if (!next.text.startsWith(TAB) || isTask(next)) break;
        last++;
      }
      return { first, last, m };
    });
  };
  const blocks = () => blocksOf(view.state);
  const blockAt = (state) => {
    const n = state.doc.lineAt(state.selection.main.head).number;
    return blocksOf(state).find((b) => n >= b.first && n <= b.last) || null;
  };
  const contentOf = (block) => {
    const doc = view.state.doc;
    const notes = [];
    for (let n = block.first + 1; n <= block.last; n++) notes.push(doc.line(n).text.slice(1));
    return { title: doc.line(block.first).text.slice(BOX).trim(), notes: notes.join("\n") };
  };
  const isDone = (block) => TASK.exec(view.state.doc.line(block.first).text)[1] !== " ";

  /* ---- how the rows are drawn ---- */

  // In a task row's box: its checkbox and the word Task.
  class Kind extends WidgetType {
    constructor(done) {
      super();
      this.done = done;
    }
    eq(other) {
      return other.done === this.done;
    }
    toDOM() {
      const kind = document.createElement("span");
      kind.className = this.done ? "pad-kind done" : "pad-kind";
      kind.innerHTML = '<button type="button" class="pad-check" role="checkbox"></button><span class="pad-kind-name">Task</span>';
      const box = kind.firstElementChild;
      box.setAttribute("aria-checked", String(this.done));
      box.setAttribute("aria-label", "Done");
      return kind;
    }
    ignoreEvent() {
      return true;
    }
  }

  // A task's other rows' tab: the same indent.
  class Indent extends WidgetType {
    eq() {
      return true;
    }
    toDOM() {
      const indent = document.createElement("span");
      indent.className = "pad-indent";
      return indent;
    }
  }
  const INDENT = new Indent();

  // After a title's last word: its controls, the task sheet's icons and
  // their menus (task-sheet.js takes them up), and Delete. One per task,
  // kept while it is a task, so a menu open on it stays open.
  const controls = new WeakMap(); // task -> its form
  const controlsOf = (m) => {
    let form = controls.get(m);
    if (form) return form;
    form = document.getElementById("pad-props-template").content.firstElementChild.cloneNode(true);
    for (const [name, value] of Object.entries(m.fields)) if (form.elements[name]) form.elements[name].value = value;
    form._m = m;
    controls.set(m, form);
    document.dispatchEvent(new CustomEvent("htmx:load", { detail: { elt: form } }));
    return form;
  };
  class Controls extends WidgetType {
    constructor(m) {
      super();
      this.m = m;
    }
    eq(other) {
      return other.m === this.m;
    }
    toDOM() {
      return controlsOf(this.m);
    }
    ignoreEvent() {
      return true;
    }
  }

  // Under the last row, empty rows to the bottom of the box, numbered on:
  // exactly the room left (the last of them cut at the box's edge), so a
  // short page never scrolls; at least one row under the text.
  const setFiller = StateEffect.define();
  const fillerField = StateField.define({
    create: () => ({ count: 1, height: 36 }),
    update(filler, tr) {
      for (const e of tr.effects) if (e.is(setFiller)) filler = e.value;
      return filler;
    },
  });
  class Filler extends WidgetType {
    constructor({ count, height }) {
      super();
      this.count = count;
      this.height = height;
    }
    eq(other) {
      return other.count === this.count && other.height === this.height;
    }
    toDOM() {
      const filler = document.createElement("div");
      filler.className = "pad-filler";
      filler.style.height = `${this.height}px`;
      for (let i = 0; i < this.count; i++) filler.append(document.createElement("div"));
      return filler;
    }
    get estimatedHeight() {
      return this.height;
    }
    ignoreEvent() {
      return false; // a click in them writes at the end
    }
  }
  class FillerNumbers extends GutterMarker {
    constructor(from, count) {
      super();
      this.from = from;
      this.count = count;
      this.elementClass = "pad-filler-numbers";
    }
    eq(other) {
      return other.from === this.from && other.count === this.count;
    }
    toDOM() {
      const numbers = document.createElement("div");
      for (let i = 0; i < this.count; i++) {
        const row = document.createElement("div");
        row.textContent = String(this.from + i);
        numbers.append(row);
      }
      return numbers;
    }
  }
  const fillToBottom = ViewPlugin.fromClass(class {
    constructor(v) {
      // Measured again whenever the box changes size (the first time, once
      // it is laid out).
      this.resized = new ResizeObserver(() => this.measure(v));
      this.resized.observe(v.scrollDOM);
    }
    update(u) {
      if (u.docChanged || u.geometryChanged || u.heightChanged) this.measure(u.view);
    }
    destroy() {
      this.resized.disconnect();
    }
    measure(v) {
      v.requestMeasure({
        key: "pad-filler",
        read: () => {
          // The text's height: down to where the empty rows start (the
          // content itself is always the box's full height).
          const filler = v.contentDOM.querySelector(".pad-filler");
          if (!filler) return null;
          const text = filler.getBoundingClientRect().top - v.contentDOM.getBoundingClientRect().top;
          const row = parseFloat(getComputedStyle(v.contentDOM).getPropertyValue("--pad-line")) || 36;
          const height = Math.max(row, Math.floor(v.scrollDOM.clientHeight - text));
          return { count: Math.ceil(height / row), height };
        },
        write: (next) => {
          const same = (f) => !next || (f.count === next.count && f.height === next.height);
          if (same(v.state.field(fillerField))) return;
          setTimeout(() => {
            if (!same(v.state.field(fillerField))) v.dispatch({ effects: setFiller.of(next) });
          });
        },
      });
    }
  });

  class RowClass extends GutterMarker {
    constructor(name) {
      super();
      this.elementClass = name;
    }
    eq(other) {
      return other.elementClass === this.elementClass;
    }
  }

  const setFocus = StateEffect.define();
  const focusField = StateField.define({
    create: () => false,
    update(focused, tr) {
      for (const e of tr.effects) if (e.is(setFocus)) focused = e.value;
      return focused;
    },
  });

  // Each row as it reads: a task's rows bracketed (the one the caret is in,
  // in ink), its title in ink with its box and controls, its other rows
  // indented; the row numbers alike, the caret's in ink.
  const draw = (state) => {
    const doc = state.doc;
    const all = blocksOf(state);
    const focused = state.field(focusField);
    const here = doc.lineAt(state.selection.main.head).number;
    const current = focused ? all.find((b) => here >= b.first && here <= b.last) : null;
    const of = new Map();
    for (const b of all) for (let n = b.first; n <= b.last; n++) of.set(n, b);
    const decos = [];
    const atomic = [];
    const numbers = new RangeSetBuilder();
    for (let n = 1; n <= doc.lines; n++) {
      const line = doc.line(n);
      const b = of.get(n);
      const task = b?.first === n;
      const tabbed = !task && line.text.startsWith(TAB);
      const kinds = [];
      if (b) {
        if (task) kinds.push("pad-first");
        if (b.last === n) kinds.push("pad-last");
        if (b === current) kinds.push("pad-current");
      }
      const row = [...kinds];
      if (task) row.push("pad-title");
      else if (tabbed) row.push("pad-body");
      if (row.length) decos.push(Decoration.line({ class: row.join(" ") }).range(line.from));
      if (task) {
        const box = Decoration.replace({ widget: new Kind(TASK.exec(line.text)[1] !== " ") });
        decos.push(box.range(line.from, line.from + BOX));
        atomic.push(box.range(line.from, line.from + BOX));
        decos.push(Decoration.widget({ widget: new Controls(b.m), side: 1 }).range(line.to));
      } else if (tabbed) {
        const tab = Decoration.replace({ widget: INDENT });
        decos.push(tab.range(line.from, line.from + 1));
        atomic.push(tab.range(line.from, line.from + 1));
      }
      if (focused && n === here) kinds.push("here");
      if (kinds.length) numbers.add(line.from, line.from, new RowClass(kinds.join(" ")));
    }
    const filler = new Filler(state.field(fillerField));
    decos.push(Decoration.widget({ widget: filler, block: true, side: 1 }).range(doc.length));
    return { decos: Decoration.set(decos, true), atomic: Decoration.set(atomic, true), numbers: numbers.finish() };
  };
  const drawField = StateField.define({
    create: draw,
    update: (drawn, tr) => (tr.docChanged || tr.selection || tr.effects.length ? draw(tr.state) : drawn),
    provide: (f) => [
      EditorView.decorations.from(f, (d) => d.decos),
      EditorView.atomicRanges.of((v) => v.state.field(f).atomic),
      gutterLineClass.from(f, (d) => d.numbers),
    ],
  });

  /* ---- the caret: never inside a box or a tab ---- */

  const leadOf = (line) => (isTask(line) ? BOX : line.text.startsWith(TAB) ? 1 : 0);
  // A caret landing at a boxed or tabbed row's very start goes to its first
  // word; Left from that word goes on to the row above.
  const offTheLead = EditorState.transactionFilter.of((tr) => {
    if (!tr.selection) return tr;
    const { doc, selection } = tr.state;
    let moved = false;
    const ranges = selection.ranges.map((r) => {
      const line = doc.lineAt(r.head);
      const lead = leadOf(line);
      if (!lead || r.head >= line.from + lead) return r;
      if (!r.empty) {
        // A selection drawn back to a row's start (Shift+Home) stops at its
        // first word, leaving the box: typing over it keeps the task.
        if (r.anchor < line.from + lead) return r;
        moved = true;
        return EditorSelection.range(r.anchor, line.from + lead);
      }
      moved = true;
      const left = !tr.docChanged && line.number > 1 && tr.startState.selection.main.head === line.from + lead;
      return EditorSelection.cursor(left ? line.from - 1 : line.from + lead);
    });
    if (!moved) return tr;
    return [tr, { selection: EditorSelection.create(ranges, selection.mainIndex), sequential: true }];
  });

  /* ---- keys ---- */

  const enter = (v) => {
    const { state } = v;
    if (state.selection.ranges.length > 1) return false;
    const range = state.selection.main;
    const line = state.doc.lineAt(range.head);
    if (isTask(line)) {
      if (range.empty && range.head === line.from + BOX && line.length > BOX) {
        // At a title's first word: a plain row above it, the task moving down with its words.
        v.dispatch({ changes: { from: line.from, insert: "\n" }, selection: { anchor: range.head + 1 }, scrollIntoView: true, userEvent: "input" });
        return true;
      }
    } else if (!line.text.startsWith(TAB)) {
      return false;
    } else if (line.text === TAB && range.empty) {
      // An empty row of a task: out of it, to a plain row.
      v.dispatch({ changes: { from: line.from, to: line.to }, userEvent: "delete" });
      return true;
    }
    v.dispatch(state.replaceSelection(`\n${TAB}`), { scrollIntoView: true, userEvent: "input" });
    return true;
  };

  const keys = Prec.high(keymap.of([
    {
      // In a task: save it, and go on to a fresh plain row after it.
      key: "Mod-Enter",
      run: (v) => {
        const block = blockAt(v.state);
        if (!block) return false;
        saveTask(block);
        const end = v.state.doc.line(block.last).to;
        v.dispatch({ changes: { from: end, insert: "\n" }, selection: { anchor: end + 1 }, scrollIntoView: true, userEvent: "input" });
        return true;
      },
    },
    {
      // In a task: save it. Outside one: out of the text.
      key: "Escape",
      run: (v) => {
        const block = blockAt(v.state);
        if (block) saveTask(block);
        else v.contentDOM.blur();
        return true;
      },
    },
    { key: "Enter", run: enter },
  ]));

  /* ---- saving the notes ---- */

  let version = 0;
  let saved = "";
  let timer = 0;
  let inflight = false;
  let again = false;
  let stale = false;
  let theirs = 0;
  const loading = Annotation.define(); // the notes being taken up, not written

  const serialize = () => {
    const doc = view.state.doc;
    const links = {};
    for (const { pos, m } of view.state.field(tasksField)) if (m.id) links[doc.lineAt(pos).number - 1] = m.id;
    return { text: doc.toString(), links };
  };
  const snapshot = () => JSON.stringify(serialize());
  const pending = () => !!view && snapshot() !== saved;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(flush, SAVE_AFTER_MS);
  };

  async function flush({ leaving = false } = {}) {
    clearTimeout(timer);
    if (!view || stale || !pending()) return;
    if (inflight && !leaving) {
      again = true;
      return;
    }
    const page = serialize();
    const state = JSON.stringify(page);
    const request = fetch(`/ui/notebook/${day}`, {
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
        document.getElementById("pad-stale").hidden = false;
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
      document.getElementById("pad-stale").hidden = true;
      flush();
    }
  });

  // Back to notes written elsewhere since (the phone, another window).
  const refresh = async () => {
    if (!view || stale || pending() || view.hasFocus) return;
    const res = await fetch(`/ui/notebook/${day}/version`).catch(() => null);
    const answer = res?.ok ? await res.json() : null;
    if (!answer || answer.version <= version) return;
    const page = await fetch(location.pathname).then((r) => r.text()).catch(() => null);
    const fresh = page && new DOMParser().parseFromString(page, "text/html").getElementById("notepad");
    if (!fresh || pending() || view.hasFocus) return;
    load(fresh);
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
    const status = isDone(block) ? "done" : m.fields.status === "done" ? "todo" : m.fields.status;
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
    const now = blocks().find((b) => b.m === m);
    if (m.id && now && (isDone(now) || m.fields.milestone_id)) writeTask(now);
  }

  // A task's controls changed a field: kept for its adding, or written to it.
  // A milestone comes with its project (two changes): one write for both.
  const fieldWrites = new WeakMap(); // task -> timer
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

  /* ---- a task's box and its Delete ---- */

  document.addEventListener("pointerdown", (e) => {
    if (e.target.closest?.(".pad-check, [data-pad-remove]")) e.preventDefault(); // the caret stays where it was
  });

  const taskOfBox = (box) => {
    const line = view.state.doc.lineAt(view.posAtDOM(box));
    return view.state.field(tasksField).find(({ pos }) => pos === line.from)?.m || null;
  };
  // A row's box written as ticked or not: the notes' record of it, not an
  // edit to undo (the task's own tick is not undone with it).
  const mark = (m, done) => {
    const block = blocks().find((b) => b.m === m);
    if (!block) return;
    const at = view.state.doc.line(block.first).from + 3;
    view.dispatch({ changes: { from: at, to: at + 1, insert: done ? "x" : " " }, annotations: Transaction.addToHistory.of(false) });
  };

  // Ticking a task's box ticks its task (and its row, in the notes).
  document.addEventListener("click", async (e) => {
    const box = e.target.closest?.(".pad-check");
    if (!box || !view?.dom.contains(box)) return;
    const m = taskOfBox(box);
    const block = m && blocks().find((b) => b.m === m);
    if (!block) return;
    const done = !isDone(block);
    mark(m, done);
    if (!m.id) return;
    const res = await post(`/ui/tasks/${m.id}/toggle`).catch(() => null);
    if (!res?.ok) {
      mark(m, !done);
      window.toast("Could not tick that task.");
      return;
    }
    m.fields.status = done ? "done" : "todo";
    htmx.trigger(document.body, "calendar:refresh");
  });

  // Delete: an added task goes from the plan (asked first), and its rows
  // from the notes, as an edit undo can take back (the words come back, as
  // a task not yet added).
  const takeOut = (m) => {
    const block = blocks().find((b) => b.m === m);
    if (!block) return;
    const doc = view.state.doc;
    let from = doc.line(block.first).from;
    let to = doc.line(block.last).to;
    if (block.last < doc.lines) to += 1; // with the newline after it
    else if (block.first > 1) from -= 1; // or, last of all, the one before
    view.focus();
    // An undo step of its own, not joined to the writing just before it.
    view.dispatch({
      changes: { from, to }, selection: { anchor: from }, scrollIntoView: true, userEvent: "delete",
      annotations: isolateHistory.of("full"),
    });
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
      m.id = null;
      m.saved = null;
      window.toast(`Task deleted: ${title}`);
      htmx.trigger(document.body, "calendar:refresh");
    }
    takeOut(m);
  });

  /* ---- the page around it ---- */

  // Left and Right, outside the text, change the day.
  document.addEventListener("keydown", (e) => {
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
    if (!view) return;
    for (const block of blocks()) saveTask(block, { leaving: true });
    if (pending()) flush({ leaving: true });
  });

  /* ---- start ---- */

  const theme = EditorView.theme({
    "&": { height: "100%", fontSize: "var(--t-body-sm)", letterSpacing: "-0.01em" },
    "&.cm-focused": { outline: "none" },
    ".cm-scroller": { fontFamily: "inherit", lineHeight: "var(--pad-text)" },
    ".cm-content": { padding: "0", caretColor: "var(--ink)" },
    ".cm-line": {
      padding: "var(--pad-above) var(--s-4) var(--pad-below) var(--pad-gap)",
      borderBottom: "1px solid var(--hairline)",
      color: "color-mix(in srgb, var(--ink) 55%, var(--graphite))",
    },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--ink)", borderLeftWidth: "1.5px" },
    "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      background: "color-mix(in srgb, var(--spark) 22%, transparent)",
    },
    ".cm-gutters": {
      backgroundColor: "color-mix(in srgb, var(--fog) 70%, transparent)",
      color: "var(--pewter)",
      borderRight: "1px solid var(--hairline)",
    },
    // A number in the middle of its row's first line; the row's rule drawn,
    // not a border, so the gutter's unseen sizing element stays 0px tall.
    ".cm-lineNumbers .cm-gutterElement": {
      minWidth: "var(--pad-rows)",
      padding: "0 var(--s-2) 0 0",
      lineHeight: "calc(var(--pad-line) - 1px)",
      background: "linear-gradient(to top, var(--hairline) 1px, transparent 1px)",
      fontSize: "var(--t-caption)",
      fontVariantNumeric: "tabular-nums",
    },
    ".cm-placeholder": { color: "var(--pewter)" },
  });

  const extensions = () => [
    tasksField, keepTasks, focusField, fillerField, drawField, offTheLead,
    EditorView.focusChangeEffect.of((state, focusing) => setFocus.of(focusing)),
    lineNumbers(),
    lineNumberWidgetMarker.of((v, widget) => (widget instanceof Filler ? new FillerNumbers(v.state.doc.lines + 1, widget.count) : null)),
    fillToBottom,
    history(),
    drawSelection(),
    EditorView.lineWrapping,
    placeholder("Anything on your mind today."),
    EditorView.contentAttributes.of({ "aria-label": "Notes", spellcheck: "true" }),
    keys,
    keymap.of([...defaultKeymap, ...historyKeymap]),
    EditorView.updateListener.of((u) => {
      if (u.docChanged && !u.transactions.some((tr) => tr.annotation(loading))) schedule();
    }),
    theme,
  ];

  // Take up the notes (the page's textarea, or a fresher copy of it).
  function load(src) {
    day = src.dataset.day;
    version = Number(src.dataset.version) || 0;
    const text = src.value;
    let rows = [];
    try { rows = JSON.parse(src.dataset.taskRows || "[]"); } catch { /* none */ }
    const starts = [0];
    for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
    const tasks = rows.filter(({ row }) => row < starts.length).map(({ row, id, fields }) => {
      const given = Object.entries(fields || {}).map(([name, value]) => [name, value == null ? "" : String(value)]);
      return { pos: starts[row], m: { id, saved: null, fields: { ...newFields(), ...Object.fromEntries(given) } } };
    });
    const state = EditorState.create({ doc: text, extensions: extensions() });
    if (view) {
      view.setState(state);
    } else {
      const parent = document.createElement("div");
      parent.className = "pad-editor";
      src.after(parent);
      src.hidden = true;
      view = new EditorView({ state, parent });
    }
    view.dispatch({ effects: setTasks.of(tasks), annotations: [loading.of(true), Transaction.addToHistory.of(false)] });
    // What the notes say of each task now is what was last written to it.
    for (const block of blocks()) block.m.saved = contentOf(block);
    saved = snapshot();
  }

  const el = source();
  if (el) load(el);
  // For the page's tests: the notes as written.
  window.Notepad = { get view() { return view; }, text: () => view?.state.doc.toString() ?? "" };
})();
