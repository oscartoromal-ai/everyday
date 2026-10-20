/* A day's notepad (today.html): text in rows, like a spreadsheet, the rows
   numbered down the left. A CodeMirror 6 editor (vendor/codemirror.js,
   window.CM) over the page's textarea, which holds the notes as the server
   sends them. A row too long for the box wraps inside its row.

   The notes are Markdown, drawn as they read by the app's one Markdown
   engine (markdown-live.js), as a task's description and a project's
   documents are: headings, emphasis, code, links, lists, quotes, rules,
   fenced code and tables, their marks showing where the caret is. Its
   modes (Live, Source, Reading) are switched at the day's header (Ctrl+E
   in and out of Reading), remembered for the notes. The rows below are the
   notepad's own: on them the engine draws only the words' Markdown (bold,
   code, a link), never the row's lead or shape, nor its keys; and a task's
   title none at all, being plain words wherever the task shows.

   A task is written in the notes. "- [ ] " at a row's start makes the row a
   task: its "- [ ] " is drawn as the task's checkbox and the word Task (one
   piece, never typed into), and after the title's last word, at the row's
   right, come its controls: the task sheet's icons (do date, time, due,
   repeat, project) and Delete, on the title's last line when they fit there
   and on a line of their own under it when not. Enter in a task starts its
   next row with a tab, drawn as the same indent, so its description lines
   up under its title; Enter on an empty tabbed row steps back out to a
   plain row. "- [ ] " on a task's row makes it a sub-task, with its box
   (the task's description keeps it as "- [ ] " or "- [x] "); Enter on one
   starts the next, on an empty one steps back to a plain row. A ticked
   sub-task is crossed out, and a ticked task, title and rows. Backspace at a row's first word takes its
   box or tab away, and the row is plain again. Tab and Shift+Tab never
   leave the notes: Tab goes from a title to the row under it, takes a
   plain row into the task above it, and makes a task's row a sub-task;
   Shift+Tab steps back out. As in the task sheet, "friday", "due friday",
   "every week" or "30m" and a space in a title become its fields.

   Every task is bracketed by a rule above its title and below its last row,
   always (one rule between a task and the one right under it); the task
   the caret is in has its rules and row numbers in ink. A task in a
   project has its rules in the project's colour, softened (full while the
   caret is in it), and its project control is the flag in that colour. A task with rows
   under its title folds to its title and back (the chevron after Task),
   and stays so; an edit that would reach its hidden rows unfolds it first.
   Ctrl+Enter or Esc in a task saves it (adds it for the day, with what its
   controls set, or writes its title and description to the task it made),
   Ctrl+Enter then going on to a fresh plain row. Ticking a task's box ticks
   its task; its controls write to it straight away once it is added.
   Delete takes its rows out of the notes, and an added task, once
   confirmed, out of the plan. An added task's Open control, after its
   icons, opens it on its page (Ctrl+Shift+Enter in it too, adding it first
   when it is not yet), once what is written of it is saved.

   "/reflection" at a row's start makes the row a reflection, free text:
   its "/reflection" drawn as the word Reflection in the indent, its rows
   under it tabbed in as a task's are, the whole bracketed in light blue.
   Ctrl+Enter goes on to a plain row after it. The notes save it as a
   reflection block, between the text around it.

   After "/" at a row's start the commands are offered. Habits are not
   written here: they are ticked in the habits' pane beside the notes
   (habits.js).

   Beside the notes too, the plan: the day's tasks not yet written here,
   those for the day and those carried over from before (on today's page,
   overdue ones and those still open from the last page before it). A title
   writes its rows at the end of the notes, its title row making that same
   task, and moves its do-date to this day; its box writes them ticked; its
   calendar moves it to another day (Reschedule moves every one carried
   over); Bring all writes every one.

   Where Oscar stays is not written here: it has a pane of its own
   (stays.js), as the habits have.

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
    historyKeymap, invertedEffects, isolateHistory, autocompletion, completionStatus,
  } = window.CM;

  const SAVE_AFTER_MS = 600;
  const RETRY_AFTER_MS = 4000;
  const TASK = /^- \[([ xX])\] /; // a task row's box
  const BOX = 6; // its length
  const TAB = "\t"; // a task's or reflection's other rows start with one
  const REFLECTION = /^\/reflection(?: |$)/; // a reflection's first row, and its lead
  const SUB_LEAD = 7; // a sub-task's tab and box, "\t- [ ] "

  const source = () => document.getElementById("notepad");
  let view = null;
  let day = "";

  /* ---- tasks: which rows made which task ---- */

  // Each task row's task: {id, saved, fields, known}. id once it is added;
  // saved: its title and description as last written to it; fields: its do
  // date, project and the rest, as the sheet posts them; known: its fields
  // as the app last had them from here, so a write sends only what changed
  // since (and a field changed elsewhere meanwhile stays). A task not yet
  // added is for the notes' day.
  const newFields = () => ({
    planned_for: day, due: "", repeat: "none", estimate: "", priority: "",
    project_id: "", workstream_id: "", status: "todo", owner: "oscar",
  });
  const newTask = () => ({ id: null, saved: null, fields: newFields(), folded: false });

  const isTask = (line) => TASK.test(line.text);
  const isReflection = (line) => REFLECTION.test(line.text);
  // The rows the notepad draws itself: its tasks and reflections,
  // and every tabbed row (theirs). On these the Markdown engine draws only
  // the words' marks.
  const owns = (line) => line.text.startsWith(TAB) || isTask(line) || isReflection(line);
  // A row that is Markdown's own to go on from (a list item, an indented
  // note under one, a numbered item, a quote): Enter is the engine's there.
  const MARKUP = /^(?: +\S|[-*+][ \t]|\d{1,9}[.)](?:[ \t]|$)|>)/;

  // Each project's colour (1 to 8, --hue-N), by id; and a task's, when it
  // is in one.
  const projectColors = new Map();
  const colorOf = (b) => (b.kind === "task" && projectColors.get(String(b.m.fields.project_id))) || 0;
  // The rows drawn again (a task's project changed from its controls).
  const redraw = StateEffect.define();
  const setTasks = StateEffect.define();
  // A task folded to its title, or unfolded: {m, folded}.
  const setFolded = StateEffect.define();
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

  // A task row taken out and put back elsewhere by the same edit keeps its
  // task: Alt+Up and Alt+Down (CodeMirror's moveLine) move the caret's rows
  // by taking out the row they pass and putting it back on their other side.
  // A lost row finds the row put back with its very words, unless that row
  // is another task's already.
  const moved = (list, next, tr) => {
    const put = [];
    tr.changes.iterChanges((fromA, toA, fromB, toB) => { if (toB > fromB) put.push([fromB, toB]); });
    const doc = tr.state.doc;
    const held = new Set(next.map((t) => t.pos).filter((pos) => pos != null));
    return next.map((t, i) => {
      if (t.pos != null) return t;
      const words = tr.startState.doc.lineAt(list[i].pos).text;
      for (const [from, to] of put) {
        for (let line = doc.lineAt(from); line.from <= to; line = doc.line(line.number + 1)) {
          if (line.text === words && !held.has(line.from)) {
            held.add(line.from);
            return { pos: line.from, m: t.m };
          }
          if (line.number === doc.lines) break;
        }
      }
      return t;
    });
  };

  // [{pos, m}]: each task row's start and its task. A row keeps its task
  // through edits around it (Enter at its first word moves it down with its
  // words), and loses it with its box.
  const tasksField = StateField.define({
    create: () => [],
    update(list, tr) {
      let next = null;
      for (const e of tr.effects) if (e.is(setFolded)) e.value.m.folded = e.value.folded;
      for (const e of tr.effects) if (e.is(setTasks)) next = e.value;
      if (!next && tr.docChanged) {
        next = list.map(({ pos, m }) => ({ pos: tr.changes.mapPos(pos, 1, MapMode.TrackAfter), m }));
        if (next.some((t) => t.pos == null)) next = moved(list, next, tr);
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
      return { first, last, m, kind: "task" };
    });
  };
  const blocks = () => blocksOf(view.state);
  // A reflection: its first row and the tabbed rows under it.
  const writtenOf = (state) => {
    const doc = state.doc;
    const out = [];
    for (let n = 1; n <= doc.lines; n++) {
      const line = doc.line(n);
      if (!isReflection(line)) continue;
      let last = n;
      while (last < doc.lines) {
        const next = doc.line(last + 1);
        if (!next.text.startsWith(TAB) || isTask(next)) break;
        last++;
      }
      out.push({ first: n, last, kind: "reflection" });
    }
    return out;
  };
  // The task or reflection the caret is in.
  const blockAt = (state) => {
    const n = state.doc.lineAt(state.selection.main.head).number;
    return [...blocksOf(state), ...writtenOf(state)].find((b) => n >= b.first && n <= b.last) || null;
  };
  // A task's sub-task: a "- [ ] " (or "- [x] ") row under its title.
  const SUB = /^\t- \[([ xX])\] /;
  const taskOfRow = (state, line) =>
    blocksOf(state).find((b) => line.number > b.first && line.number <= b.last) || null;
  const isSub = (state, line) => SUB.test(line.text) && !!taskOfRow(state, line);

  const contentOf = (block) => {
    const doc = view.state.doc;
    const notes = [];
    for (let n = block.first + 1; n <= block.last; n++) notes.push(doc.line(n).text.slice(1));
    return { title: doc.line(block.first).text.slice(BOX).trim(), notes: notes.join("\n") };
  };
  const isDone = (block) => TASK.exec(view.state.doc.line(block.first).text)[1] !== " ";

  /* ---- how the rows are drawn ---- */

  // In a task's row: its checkbox and the word Task.
  // A task with rows under its title has its chevron after Task, to fold
  // it to its title (fold: null without rows, else whether it is folded).
  class Kind extends WidgetType {
    constructor(done, name = "Task", fold = null) {
      super();
      this.done = done;
      this.name = name;
      this.fold = fold;
    }
    eq(other) {
      return other.done === this.done && other.name === this.name && other.fold === this.fold;
    }
    toDOM() {
      const kind = document.createElement("span");
      kind.className = this.done ? "pad-kind done" : "pad-kind";
      kind.innerHTML = '<button type="button" class="pad-check" role="checkbox"></button><span class="pad-kind-name"></span>';
      kind.lastElementChild.textContent = this.name;
      const box = kind.firstElementChild;
      box.setAttribute("aria-checked", String(this.done));
      box.setAttribute("aria-label", "Done");
      if (this.fold !== null) {
        const fold = document.createElement("button");
        fold.type = "button";
        fold.className = "pad-fold";
        fold.setAttribute("aria-expanded", String(!this.fold));
        fold.setAttribute("aria-label", this.fold ? "Unfold the task" : "Fold the task to its title");
        fold.title = this.fold ? "Unfold" : "Fold to its title";
        fold.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 8l4 4 4-4"/></svg>';
        kind.append(fold);
      }
      return kind;
    }
    ignoreEvent() {
      return true;
    }
  }

  // In a reflection's first row, for its "/reflection": the word Reflection.
  class Label extends WidgetType {
    constructor(name, className) {
      super();
      this.name = name;
      this.className = className;
    }
    eq(other) {
      return other.name === this.name;
    }
    toDOM() {
      const label = document.createElement("span");
      label.className = `pad-kind ${this.className}`;
      label.textContent = this.name;
      return label;
    }
  }
  const REFLECTION_LABEL = new Label("Reflection", "pad-reflection-name");

  // In a sub-task, for its "- [ ] ": its box, ticked once it is done.
  class SubBox extends WidgetType {
    constructor(done) {
      super();
      this.done = done;
    }
    eq(other) {
      return other.done === this.done;
    }
    toDOM() {
      const box = document.createElement("button");
      box.type = "button";
      box.className = "pad-check pad-sub-check";
      box.setAttribute("role", "checkbox");
      box.setAttribute("aria-checked", String(this.done));
      box.setAttribute("aria-label", "Done");
      return box;
    }
    ignoreEvent() {
      return true;
    }
  }

  // A folded task's hidden rows, after its title: how many.
  class Folded extends WidgetType {
    constructor(count) {
      super();
      this.count = count;
    }
    eq(other) {
      return other.count === this.count;
    }
    toDOM() {
      const badge = document.createElement("span");
      badge.className = "pad-folded-rows";
      badge.textContent = `${this.count} ${this.count === 1 ? "row" : "rows"}`;
      return badge;
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
  // Spelling is marked only in the row being written: every other row (all
  // of them, out of the notes) is left unmarked.
  const UNCHECKED = Decoration.line({ attributes: { spellcheck: "false" } });

  // After a title's last word: its controls, the task sheet's icons and
  // their menus (task-sheet.js takes them up), and Delete. One per task,
  // kept while it is a task, so a menu open on it stays open.
  const controls = new WeakMap(); // task -> its form
  // Its Open control: there once the task is added, to its page.
  const showOpen = (m) => {
    const open = controls.get(m)?.querySelector("[data-open-task]");
    if (!open) return;
    open.hidden = !m.id;
    if (m.id) open.href = `/tasks/${m.id}`;
  };
  const setId = (m, id) => {
    m.id = id;
    showOpen(m);
  };
  const controlsOf = (m) => {
    let form = controls.get(m);
    if (form) return form;
    form = document.getElementById("pad-props-template").content.firstElementChild.cloneNode(true);
    for (const [name, value] of Object.entries(m.fields)) if (form.elements[name]) form.elements[name].value = value;
    form._m = m;
    controls.set(m, form);
    showOpen(m);
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

  // A block the Markdown draws over rows (a table): numbered as its first row.
  class BlockNumber extends GutterMarker {
    constructor(number) {
      super();
      this.number = number;
    }
    eq(other) {
      return other.number === this.number;
    }
    toDOM() {
      return document.createTextNode(String(this.number));
    }
  }

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
  // indented; a reflection's rows bracketed in light blue, its first with
  // the word Reflection; the row numbers alike, the
  // caret's in ink.
  const draw = (state) => {
    const doc = state.doc;
    const all = [...blocksOf(state), ...writtenOf(state)];
    const focused = state.field(focusField);
    const here = doc.lineAt(state.selection.main.head).number;
    const current = focused ? all.find((b) => here >= b.first && here <= b.last) : null;
    const of = new Map();
    for (const b of all) for (let n = b.first; n <= b.last; n++) of.set(n, b);
    // A folded task shows its title alone: its last row, as drawn.
    const folded = (b) => b.kind === "task" && b.m.folded && b.last > b.first;
    const shownLast = (b) => (folded(b) ? b.first : b.last);
    const decos = [];
    const atomic = [];
    const numbers = new RangeSetBuilder();
    for (let n = 1; n <= doc.lines; n++) {
      const line = doc.line(n);
      const b = of.get(n);
      const head = b?.first === n;
      if (b && !head && folded(b)) continue; // hidden under its title
      if (!focused || n !== here) decos.push(UNCHECKED.range(line.from));
      const task = head && b.kind === "task";
      const reflection = head && b.kind === "reflection";
      const tabbed = !head && line.text.startsWith(TAB);
      const sub = tabbed && b?.kind === "task" && SUB.exec(line.text);
      // A ticked task is crossed out, title and rows; a ticked sub-task, its row.
      const struck = (b?.kind === "task" && TASK.exec(doc.line(b.first).text)[1] !== " ") || (sub && sub[1] !== " ");
      const kinds = [];
      if (b) {
        // Right under another, it shares that one's rule: its own is not drawn,
        // and that one's is drawn in its colour while the caret is in it.
        const above = head && of.get(n - 1);
        const below = shownLast(b) === n && of.get(b.last + 1);
        if (head) kinds.push(above ? "pad-first pad-joined" : "pad-first");
        if (shownLast(b) === n) kinds.push("pad-last");
        if (below && below === current) {
          kinds.push("pad-then-current", `pad-then-${below.kind}`);
          const then = colorOf(below);
          if (then) kinds.push("pad-then-project", `pad-then-hue-${then}`);
        }
        if (b === current) kinds.push("pad-current");
        if (b.kind !== "task") kinds.push(`pad-${b.kind}`);
        // A task in a project: its rules in the project's colour.
        const color = colorOf(b);
        if (color) kinds.push("pad-project", `pad-hue-${color}`);
      }
      const row = [...kinds];
      if (task) row.push("pad-title");
      else if (reflection || tabbed) row.push("pad-body");
      if (sub) row.push("pad-sub");
      if (struck) row.push("pad-struck");
      if (row.length) decos.push(Decoration.line({ class: row.join(" ") }).range(line.from));
      if (reflection) {
        const lead = REFLECTION.exec(line.text)[0].length;
        const label = Decoration.replace({ widget: REFLECTION_LABEL });
        decos.push(label.range(line.from, line.from + lead));
        atomic.push(label.range(line.from, line.from + lead));
      } else if (task) {
        const fold = b.last > b.first ? folded(b) : null;
        const box = Decoration.replace({ widget: new Kind(TASK.exec(line.text)[1] !== " ", "Task", fold) });
        decos.push(box.range(line.from, line.from + BOX));
        atomic.push(box.range(line.from, line.from + BOX));
        let end = line.to;
        if (fold) {
          // Its rows hidden after its title, their count in their place.
          end = doc.line(b.last).to;
          const hidden = Decoration.replace({ widget: new Folded(b.last - b.first) });
          decos.push(hidden.range(line.to, end));
          atomic.push(hidden.range(line.to, end));
        }
        decos.push(Decoration.widget({ widget: new Controls(b.m), side: 1 }).range(end));
      } else if (tabbed) {
        const tab = Decoration.replace({ widget: INDENT });
        decos.push(tab.range(line.from, line.from + 1));
        atomic.push(tab.range(line.from, line.from + 1));
        if (sub) {
          const box = Decoration.replace({ widget: new SubBox(sub[1] !== " ") });
          decos.push(box.range(line.from + 1, line.from + SUB_LEAD));
          atomic.push(box.range(line.from + 1, line.from + SUB_LEAD));
        }
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

  const leadOf = (line, state = null) => {
    if (isTask(line)) return BOX;
    const lead = REFLECTION.exec(line.text);
    if (lead) return lead[0].length;
    if (state && isSub(state, line)) return SUB_LEAD;
    return line.text.startsWith(TAB) ? 1 : 0;
  };
  // A caret landing at a boxed, labelled or tabbed row's very start goes to
  // its first word (Home too, from anywhere in the row). One landing after a
  // folded task's hidden rows (End on its title: they share its line) goes
  // to its title's end, where what is typed can be seen.
  const offTheLead = EditorState.transactionFilter.of((tr) => {
    if (!tr.selection) return tr;
    const { doc, selection } = tr.state;
    const hidden = new Map(blocksOf(tr.state)
      .filter((b) => b.m.folded && b.last > b.first)
      .map((b) => [doc.line(b.last).to, doc.line(b.first).to]));
    let moved = false;
    const ranges = selection.ranges.map((r) => {
      if (r.empty && hidden.has(r.head)) {
        moved = true;
        return EditorSelection.cursor(hidden.get(r.head));
      }
      const line = doc.lineAt(r.head);
      const lead = leadOf(line, tr.state);
      if (!lead || r.head >= line.from + lead) return r;
      if (!r.empty) {
        // A selection drawn back to a row's start (Shift+Home) stops at its
        // first word, leaving the box: typing over it keeps the task.
        if (r.anchor < line.from + lead) return r;
        moved = true;
        return EditorSelection.range(r.anchor, line.from + lead);
      }
      moved = true;
      return EditorSelection.cursor(line.from + lead);
    });
    if (!moved) return tr;
    return [tr, { selection: EditorSelection.create(ranges, selection.mainIndex), sequential: true }];
  });

  /* ---- folded tasks ---- */

  // An edit that would reach a folded task's hidden rows unfolds it instead
  // (the next edit does what was meant); an undo or redo goes through, and
  // unfolds it too. A row added after it (Ctrl+Enter) leaves it folded.
  const unfoldFirst = EditorState.transactionFilter.of((tr) => {
    if (!tr.docChanged || tr.annotation(loading)) return tr;
    const reached = [];
    for (const b of blocksOf(tr.startState)) {
      if (!b.m.folded || b.last === b.first) continue;
      const from = tr.startState.doc.line(b.first).to;
      const to = tr.startState.doc.line(b.last).to;
      tr.changes.iterChanges((fromA, toA, fromB, toB, inserted) => {
        const text = inserted.toString();
        const reaches = toA > fromA
          // a deletion into its rows, or joining the row after onto its last
          ? (fromA < to && toA > from) || fromA === to
          // a row added under its title, or words at its last row's end
          : (fromA === from && text.includes("\n")) || (fromA === to && !text.startsWith("\n"));
        if (reaches) reached.push(b.m);
      });
    }
    if (!reached.length) return tr;
    const effects = [...new Set(reached)].map((m) => setFolded.of({ m, folded: false }));
    if (tr.isUserEvent("undo") || tr.isUserEvent("redo")) return [tr, { effects, sequential: true }];
    return { effects };
  });

  document.addEventListener("pointerdown", (e) => {
    if (e.target.closest?.(".pad-fold")) e.preventDefault(); // the caret stays where it was
  });
  document.addEventListener("click", (e) => {
    const fold = e.target.closest?.(".pad-fold");
    if (!fold || !view?.dom.contains(fold)) return;
    const m = taskOfBox(fold);
    if (!m) return;
    view.dispatch({ effects: setFolded.of({ m, folded: !m.folded }) });
    schedule(); // kept with the notes
  });

  /* ---- keys ---- */

  const enter = (v) => {
    const { state } = v;
    if (state.selection.ranges.length > 1) return false;
    const range = state.selection.main;
    const line = state.doc.lineAt(range.head);
    if (isTask(line) || isReflection(line)) {
      const lead = leadOf(line);
      if (range.empty && range.head === line.from + lead && line.length > lead) {
        // At a first row's first word: a plain row above it, the task (or
        // reflection) moving down with its words.
        v.dispatch({ changes: { from: line.from, insert: "\n" }, selection: { anchor: range.head + 1 }, scrollIntoView: true, userEvent: "input" });
        return true;
      }
    } else if (!line.text.startsWith(TAB)) {
      // A plain row: a list (or a quote) goes on as Markdown has it; any
      // other row starts a plain row, never one Markdown would take into a
      // task right above it (a line under a list is that list's).
      if (MARKUP.test(line.text)) return false;
      v.dispatch(state.replaceSelection("\n"), { scrollIntoView: true, userEvent: "input" });
      return true;
    } else if (isSub(state, line)) {
      if (range.empty && /^\t- \[[ xX]\] $/.test(line.text)) {
        // An empty sub-task: a plain tabbed row (Enter again steps out).
        v.dispatch({ changes: { from: line.from + 1, to: line.to }, userEvent: "delete" });
        return true;
      }
      v.dispatch(state.replaceSelection(`\n${TAB}- [ ] `), { scrollIntoView: true, userEvent: "input" });
      return true;
    } else if (line.text === TAB && range.empty) {
      // An empty row of a task or reflection: out of it, to a plain row.
      v.dispatch({ changes: { from: line.from, to: line.to }, userEvent: "delete" });
      return true;
    }
    v.dispatch(state.replaceSelection(`\n${TAB}`), { scrollIntoView: true, userEvent: "input" });
    return true;
  };

  // Tab and Shift+Tab stay in the notes, a step into or out of a task (or
  // reflection) at a time. Tab from a first row goes under it (to its first
  // row, a new one when it has none); on a plain row right under one, the
  // row joins it; on a task's row, the row takes a box (a sub-task).
  // Shift+Tab takes a box away, else a row's tab.
  // On any other row, Tab and Shift+Tab are Markdown's (a list item nests,
  // or steps back out), and otherwise do nothing (keepTab).
  const blockOfLine = (state, n) =>
    [...blocksOf(state), ...writtenOf(state)].find((b) => n >= b.first && n <= b.last) || null;
  const tab = (v) => {
    const { state } = v;
    if (state.selection.ranges.length > 1) return true;
    const line = state.doc.lineAt(state.selection.main.head);
    const block = blockOfLine(state, line.number);
    if (block?.first === line.number) {
      const effects = block.kind === "task" && block.m.folded ? [setFolded.of({ m: block.m, folded: false })] : [];
      if (block.last > block.first) {
        v.dispatch({ selection: { anchor: state.doc.line(line.number + 1).to }, effects, scrollIntoView: true, userEvent: "select" });
      } else {
        v.dispatch({ changes: { from: line.to, insert: `\n${TAB}` }, selection: { anchor: line.to + 2 }, effects, scrollIntoView: true, userEvent: "input" });
      }
      return true;
    }
    if (block) {
      if (block.kind === "task" && line.text.startsWith(TAB) && !SUB.test(line.text)) {
        v.dispatch({ changes: { from: line.from + 1, insert: "- [ ] " }, scrollIntoView: true, userEvent: "input" });
      }
      return true;
    }
    if (!line.text.startsWith(TAB) && blockOfLine(state, line.number - 1)) {
      v.dispatch({ changes: { from: line.from, insert: TAB }, scrollIntoView: true, userEvent: "input" });
      return true;
    }
    return false;
  };
  const keepTab = Prec.low(keymap.of([{ key: "Tab", run: () => true, shift: () => true }]));
  // A row deleted from inside a task (or reflection) goes
  // whole: its words, box and tab deleted (by Backspace, Delete or a cut),
  // it would be left an empty plain row between two of the task's rows,
  // ending the task there and leaving the rows under it outside. The caret
  // goes to the end of the row above.
  const DELETES = ["delete.backward", "delete.forward", "delete.cut", "delete.selection"];
  const rowsStayTogether = EditorState.transactionFilter.of((tr) => {
    if (!tr.docChanged || !DELETES.some((e) => tr.isUserEvent(e))) return tr;
    const { state } = tr;
    const doc = state.doc;
    let gap = null;
    tr.changes.iterChangedRanges((fromA, toA, fromB, toB) => {
      for (let n = doc.lineAt(fromB).number; !gap && n <= doc.lineAt(toB).number; n++) {
        const line = doc.line(n);
        if (line.text !== "" || n === 1 || n === doc.lines) continue;
        const next = doc.line(n + 1);
        if (next.text.startsWith(TAB) && blockOfLine(state, n - 1)) gap = line;
      }
    });
    if (!gap) return tr;
    const end = doc.line(gap.number - 1).to;
    return [tr, { changes: { from: end, to: gap.to }, selection: { anchor: end }, sequential: true }];
  });

  // Lines pasted inside a task (or reflection) stay inside it:
  // each after the first is tabbed in as one of its rows ("- [ ] " ones
  // becoming sub-tasks), so a paste never ends it early or starts another.
  const pasteInside = EditorView.domEventHandlers({
    paste(e, v) {
      const text = e.clipboardData?.getData("text/plain");
      if (!text || !/[\r\n]/.test(text)) return false;
      const line = v.state.doc.lineAt(v.state.selection.main.from);
      if (!blockOfLine(v.state, line.number)) return false;
      e.preventDefault();
      const rows = text.replace(/\r\n?/g, "\n").split("\n");
      const insert = rows.map((row, i) => (i === 0 || row.startsWith(TAB) ? row : TAB + row)).join("\n");
      v.dispatch(v.state.replaceSelection(insert), { scrollIntoView: true, userEvent: "input.paste" });
      return true;
    },
  });
  const untab = (v) => {
    const { state } = v;
    if (state.selection.ranges.length > 1) return true;
    const line = state.doc.lineAt(state.selection.main.head);
    if (!line.text.startsWith(TAB) || !blockOfLine(state, line.number)) return false;
    const boxed = SUB.test(line.text);
    const change = boxed ? { from: line.from + 1, to: line.from + SUB_LEAD } : { from: line.from, to: line.from + 1 };
    v.dispatch({ changes: change, scrollIntoView: true, userEvent: "delete" });
    return true;
  };

  // As in the task sheet: in a task's title, "friday", "at 3pm", "due
  // friday" or "every week" and a space set the field (its icon shows it)
  // and leave the title; Backspace straight after puts the words back, and
  // they stay words. A title's last words are taken when it is closed, and
  // the toast that says so can take them back. Each is an undo step of its
  // own, the field with the words: Ctrl+Z puts both back, Ctrl+Y again.
  // {m, name, value, previous, start, toWords}: start, the words' in the
  // title; toWords, the words coming back (they then stay words, as after
  // Backspace) rather than becoming the field.
  const fieldChange = StateEffect.define();
  const fieldHistory = invertedEffects.of((tr) => tr.effects
    .filter((e) => e.is(fieldChange))
    .map((e) => fieldChange.of({ ...e.value, value: e.value.previous, previous: e.value.value, toWords: !e.value.toWords })));
  const setFields = EditorView.updateListener.of((u) => {
    for (const tr of u.transactions) {
      for (const e of tr.effects) {
        if (!e.is(fieldChange)) continue;
        const { m, name, value, start, toWords } = e.value;
        window.TaskSheet.setField(controlsOf(m), name, value);
        if (toWords) (m.kept ||= new Set()).add(start);
        else m.kept?.delete(start);
      }
    }
  });
  let converted = null; // {m, name, previous, at, words, doc}: the last, for Backspace
  const toField = (v, line, caret, { closing = false } = {}) => {
    const text = `${line.text.slice(BOX, caret - line.from)} `;
    const m = v.state.field(tasksField).find(({ pos }) => pos === line.from)?.m;
    if (!m) return null;
    const field = window.TaskSheet?.fieldOfWords(text, (name) => !!controlsOf(m).elements[name]);
    if (!field || m.kept?.has(field.start)) return null;
    const at = line.from + BOX + field.start;
    const words = v.state.sliceDoc(at, caret);
    // Closing, the space before the words goes with them.
    let from = at;
    if (closing) while (from > line.from + BOX && v.state.sliceDoc(from - 1, from) === " ") from--;
    const previous = controlsOf(m).elements[field.name].value;
    v.dispatch({
      changes: { from, to: caret }, selection: { anchor: from }, userEvent: "input",
      effects: fieldChange.of({ m, name: field.name, value: field.value, previous, start: field.start, toWords: false }),
      annotations: isolateHistory.of("full"),
    });
    converted = { m, name: field.name, value: field.value, previous, at: from, words, doc: v.state.doc };
    return converted;
  };
  const wordsToFields = EditorView.inputHandler.of((v, from, to, text) => {
    if (text !== " " || from !== to || v.state.selection.ranges.length > 1) return false;
    const line = v.state.doc.lineAt(from);
    return isTask(line) && from >= line.from + BOX && !!toField(v, line, from);
  });
  // Words back in a title (where they were, or at its end) and the field as
  // it was; the words stay words from then on.
  const unconvert = (v, c, at, insert) => {
    const start = at + insert.length - c.words.length - v.state.doc.lineAt(at).from - BOX;
    v.dispatch({
      changes: { from: at, insert }, selection: { anchor: at + insert.length }, scrollIntoView: true, userEvent: "input",
      effects: fieldChange.of({ m: c.m, name: c.name, value: c.previous, previous: c.value, start, toWords: true }),
      annotations: isolateHistory.of("full"),
    });
  };
  const backToWords = (v) => {
    const c = converted;
    converted = null;
    const range = v.state.selection.main;
    if (!c || v.state.doc !== c.doc || !range.empty || range.head !== c.at) return false;
    unconvert(v, c, c.at, c.words);
    return true;
  };
  // The title's last words, as a task is closed: its block as it then
  // stands, and what they became (null when nothing).
  const closing = (v, block) => {
    const line = v.state.doc.line(block.first);
    const end = line.from + BOX + line.text.slice(BOX).replace(/\s+$/, "").length;
    const c = end > line.from + BOX ? toField(v, line, end, { closing: true }) : null;
    converted = null;
    return { block: blocksOf(v.state).find((b) => b.m === block.m) || block, converted: c };
  };
  // What a closed title's words became, in the toast's words: "do Fri 2 Oct".
  const fieldWords = (c) => {
    const button = controlsOf(c.m).querySelector(`.prop[data-prop="${c.name}"]`);
    const shown = button?.querySelector(".prop-value")?.textContent || "";
    if (c.name === "planned_for") return `do ${shown}`;
    if (c.name === "due") return `due ${shown}`;
    if (c.name === "estimate") return `${shown} estimate`;
    if (c.name === "priority") return `${shown.toLowerCase()} priority`;
    return (button?.title || "").toLowerCase();
  };
  // The toast's Undo: the words back at the title's end, written to the task.
  const undoClosing = (c) => {
    const entry = view?.state.field(tasksField).find(({ m }) => m === c.m);
    if (!entry) return;
    const line = view.state.doc.lineAt(entry.pos);
    const end = line.from + BOX + line.text.slice(BOX).replace(/\s+$/, "").length;
    view.focus();
    unconvert(view, c, end, ` ${c.words}`);
  };

  // Esc: in a task, save it (saved already, out of the text); elsewhere, out of the text. Ahead of what is
  // offered while writing, which takes Esc even while it is only looking
  // (just after a key), and would lose a task's save: it has Esc only while
  // an offer is on screen, to close it.
  const escape = Prec.highest(keymap.of([{
    key: "Escape",
    run: (v) => {
      if (completionStatus(v.state) === "active") return false;
      // A task saved as it stands (Esc again) lets the keyboard out too.
      const block = blockAt(v.state);
      const { title, notes } = block?.kind === "task" ? contentOf(block) : {};
      const saved = block?.m?.saved;
      if (block?.kind === "task" && !(saved && saved.title === title && saved.notes === notes)) {
        const closed = closing(v, block);
        saveTask(closed.block, { converted: closed.converted });
      }
      else v.contentDOM.blur();
      return true;
    },
  }]));

  const keys = Prec.high(keymap.of([
    {
      // In a task: save it, and go on to a fresh plain row after it. In a
      // reflection: on to a plain row after it.
      key: "Mod-Enter",
      run: (v) => {
        let block = blockAt(v.state);
        if (!block) return false;
        if (block.kind === "task") {
          const closed = closing(v, block);
          block = closed.block;
          saveTask(block, { converted: closed.converted });
        }
        const end = v.state.doc.line(block.last).to;
        v.dispatch({ changes: { from: end, insert: "\n" }, selection: { anchor: end + 1 }, scrollIntoView: true, userEvent: "input" });
        return true;
      },
    },
    // In a task, its key (Ctrl+Shift+Enter): open it on its page, added
    // first when it is not yet.
    ...window.Keys.cm("today.openTask").map((key) => ({
      key,
      run: (v) => {
        const block = blockAt(v.state);
        if (block?.kind !== "task") return false;
        openTask(block.m);
        return true;
      },
    })),
    { key: "Enter", run: enter },
    { key: "Tab", run: tab, shift: untab },
    { key: "Backspace", run: backToWords },
    {
      // Left from a boxed, labelled or tabbed row's first word goes on to the
      // row above (past the box, not into it).
      key: "ArrowLeft",
      run: (v) => {
        const range = v.state.selection.main;
        const line = v.state.doc.lineAt(range.head);
        const lead = leadOf(line, v.state);
        if (!range.empty || !lead || range.head !== line.from + lead || line.number === 1) return false;
        v.dispatch({ selection: { anchor: line.from - 1 }, scrollIntoView: true, userEvent: "select" });
        return true;
      },
    },
  ]));

  /* ---- saving the notes ---- */

  let version = 0;
  let saved = "";
  let timer = 0;
  let inflight = false;
  let again = false;
  let stale = false;
  let theirs = 0;
  // This window, and its saves numbered: the server lets a later save of
  // this window stand over an earlier one still on its way (a page being
  // left saves while its last save has not landed), never the other way.
  const writer = Math.random().toString(36).slice(2) + Date.now().toString(36);
  let seq = 0;
  let left = false; // the page is being left: its last save has gone
  const loading = Annotation.define(); // the notes being taken up, not written

  // A task row not added yet, as its add would write it: null when there is
  // nothing to add (no title, or words the notes already had when they were
  // taken up, which stay text until written in).
  const toAdd = (block) => {
    const m = block.m;
    if (m.id) return null;
    const { title, notes } = contentOf(block);
    if (!title || (m.saved && m.saved.title === title && m.saved.notes === notes)) return null;
    const { planned_for, time, due, repeat, project_id, workstream_id, estimate, priority } = m.fields;
    return { title, notes, planned_for, time, due, repeat, project_id, workstream_id, estimate, priority, done: isDone(block) };
  };

  // The notes as the page's blocks: the text between reflections (each
  // with the rows that made tasks, by row), and each reflection's words.
  // `adding`: the page is being left, so the task rows not added yet go
  // with the notes (a text block's `new`, by row), the server adding and
  // linking them in the same save; a separate add's answer, naming the
  // task it made, would never reach a page that is gone.
  const serialize = ({ adding = false } = {}) => {
    const { state } = view;
    const doc = state.doc;
    const tasks = new Map(state.field(tasksField).map(({ pos, m }) => [pos, m]));
    const unadded = new Map();
    if (adding) {
      for (const block of blocks()) {
        const task = toAdd(block);
        if (task) unadded.set(block.m, task);
      }
    }
    const written = new Map(writtenOf(state).map((r) => [r.first, r]));
    const foldable = new Set(blocksOf(state).filter((b) => b.last > b.first).map((b) => b.first));
    const out = [];
    let text = null;
    const endText = () => {
      if (!text) return;
      const block = { kind: "text", text: text.text };
      if (Object.keys(text.links).length) block.links = text.links;
      if (Object.keys(text.new).length) block.new = text.new;
      if (text.folded.length) block.folded = text.folded;
      out.push(block);
      text = null;
    };
    for (let n = 1; n <= doc.lines; n++) {
      const line = doc.line(n);
      const block = written.get(n);
      if (block) {
        endText();
        const words = [line.text.slice(leadOf(line))];
        for (let k = n + 1; k <= block.last; k++) words.push(doc.line(k).text.slice(1));
        out.push({ kind: block.kind, text: words.join("\n") });
        n = block.last;
        continue;
      }
      if (!text) text = { kind: "text", text: null, links: {}, new: {}, folded: [], rows: [] };
      const m = tasks.get(line.from);
      if (m?.id) text.links[text.rows.length] = m.id;
      else if (m && unadded.has(m)) text.new[text.rows.length] = unadded.get(m);
      if (m?.folded && foldable.has(n)) text.folded.push(text.rows.length);
      text.rows.push(line.text);
      text.text = text.rows.join("\n");
    }
    endText();
    return out;
  };
  const snapshot = () => JSON.stringify(serialize());
  const pending = () => !!view && snapshot() !== saved;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(flush, SAVE_AFTER_MS);
  };

  async function flush({ leaving = false } = {}) {
    clearTimeout(timer);
    if (left && !leaving) return;
    if (!view || stale || !(pending() || (leaving && blocks().some(toAdd)))) return;
    if (inflight && !leaving) {
      again = true;
      return;
    }
    const page = serialize({ adding: leaving });
    const state = JSON.stringify(page);
    const request = fetch(`/ui/notebook/${day}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify({ version, blocks: page, writer, seq: ++seq }),
      keepalive: leaving,
    });
    if (leaving) return;
    inflight = true;
    try {
      const res = await request;
      const answer = await res.json().catch(() => ({}));
      if (res.ok) {
        version = answer.version;
        // Stood over by a later save of this window: that one is the saved.
        if (!answer.superseded) saved = state;
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
    const fields = { ...m.fields, status };
    const was = m.known ? { ...m.known, ...m.saved } : {};
    const changed = Object.entries({ ...fields, ...content }).filter(([name, value]) => was[name] !== value);
    if (!changed.length) return true;
    const res = await post(`/ui/tasks/${m.id}`, new URLSearchParams(changed), leaving).catch(() => null);
    if (leaving) return true;
    if (!res?.ok) return false;
    m.known = fields;
    m.saved = content;
    htmx.trigger(document.body, "calendar:refresh");
    return true;
  }

  // `converted`: the title's last words became a field as it closed; the
  // toast says which, and can take it back.
  async function saveTask(block, { leaving = false, converted = null } = {}) {
    const { title, notes } = contentOf(block);
    const m = block.m;
    const told = (news) => (converted
      ? window.toast(`${news}, ${fieldWords(converted)}`, { action: "Undo", run: () => undoClosing(converted) })
      : window.toast(news));
    if (!title) return;
    if (m.saved && m.saved.title === title && m.saved.notes === notes) {
      // Only a field changed (its words taken): the field is already written.
      if (converted && m.id) told(`Task saved: ${title}`);
      return;
    }
    if (m.id) {
      const ok = await writeTask(block, { leaving });
      if (leaving) return;
      if (ok) told(`Task saved: ${title}`);
      else window.toast("Could not save that task. Its words are still in the notes.");
      return;
    }
    const { planned_for, time, due, repeat, project_id, estimate, priority } = m.fields;
    const body = new URLSearchParams({
      title, notes, planned_for, time, due, repeat, project_id, estimate: estimate || "", priority: priority || "",
    });
    const res = await post("/ui/tasks/quick-add", body, leaving).catch(() => null);
    if (leaving) return;
    const html = res?.ok ? await res.text() : "";
    if (!res?.ok) {
      window.toast("Could not add that task. Its words are still in the notes.");
      return;
    }
    setId(m, Number(/id="task-(\d+)"/.exec(html)?.[1]) || null);
    m.saved = { title, notes };
    m.known = { ...m.fields, workstream_id: "", status: "todo" };
    told(`Task added: ${title}`);
    htmx.trigger(document.body, "calendar:refresh");
    schedule();
    // What adding leaves out: its workstream, and a box ticked before it was added.
    const now = blocks().find((b) => b.m === m);
    if (m.id && now && (isDone(now) || m.fields.workstream_id)) writeTask(now);
  }

  // A task's controls changed a field: kept for its adding, or written to it.
  // A workstream comes with its project (two changes): one write for both.
  const fieldWrites = new WeakMap(); // task -> timer
  document.addEventListener("sheet:field", (e) => {
    const m = e.target._m;
    if (!m) return;
    m.fields[e.detail.name] = e.detail.value;
    if (e.detail.name === "project_id") {
      m.fields.workstream_id = "";
      view.dispatch({ effects: redraw.of(null) }); // its rules take the project's colour
    }
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
    const line = view.state.doc.lineAt(view.posAtDOM(box));
    if (isSub(view.state, line)) {
      // A sub-task: done, or not; an added task has its description
      // written at once.
      const at = line.from + 4;
      view.dispatch({ changes: { from: at, to: at + 1, insert: line.text[4] === " " ? "x" : " " }, userEvent: "input" });
      const task = taskOfRow(view.state, view.state.doc.lineAt(at));
      if (task?.m.id && !(await writeTask(task))) window.toast("Could not save that to the task.");
      return;
    }
    const m = taskOfBox(box);
    const block = m && blocks().find((b) => b.m === m);
    if (block) setDone(m, !isDone(block));
  });
  // A task ticked (or unticked): its row's box, then the task itself.
  async function setDone(m, done) {
    mark(m, done);
    if (!m.id) return;
    const res = await post(`/ui/tasks/${m.id}/toggle`).catch(() => null);
    if (!res?.ok) {
      mark(m, !done);
      window.toast("Could not tick that task.");
      return;
    }
    m.fields.status = done ? "done" : "todo";
    if (m.known) m.known.status = m.fields.status;
    htmx.trigger(document.body, "calendar:refresh");
  }

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
      setId(m, null);
      m.saved = null;
      window.toast(`Task deleted: ${title}`);
      htmx.trigger(document.body, "calendar:refresh");
    }
    takeOut(m);
  });

  /* ---- a task's page ---- */

  // A task on its page, once what is written of it here is saved: its
  // title's last words taken as it closes, and a task not yet added, added.
  // The notes follow as the page is left.
  let opening = false;
  async function openTask(m) {
    const block = blocks().find((b) => b.m === m);
    if (!block || opening) return;
    opening = true;
    try {
      const closed = closing(view, block);
      await saveTask(closed.block, { converted: closed.converted });
      if (m.id) window.location.href = `/tasks/${m.id}`;
    } finally {
      opening = false;
    }
  }
  document.addEventListener("click", (e) => {
    const open = e.target.closest?.(".pad-props [data-open-task]");
    const m = open?.closest(".pad-props")._m;
    if (!m || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    openTask(m);
  });

  /* ---- the page around it ---- */

  // Left and Right (their keys), outside the text, change the day, what is
  // written saved first.
  document.addEventListener("keydown", (e) => {
    if (e.isComposing || e.defaultPrevented) return;
    const prev = window.Keys.is(e, "day.prev");
    if (!prev && !window.Keys.is(e, "day.next")) return;
    const single = !e.ctrlKey && !e.metaKey && !e.altKey;
    if ((single && e.target.closest?.("input, textarea, select, [contenteditable]")) || document.querySelector("dialog[open]")) return;
    const link = document.querySelector(`[data-day-step="${prev ? "prev" : "next"}"]`);
    if (!link) return;
    e.preventDefault();
    flush();
    link.click();
  });

  // Leaving the page: what is written goes, every task changed with it, and
  // every task row not added yet is added by that same save.
  window.addEventListener("pagehide", () => {
    if (!view) return;
    for (const block of blocks()) if (block.m.id) saveTask(block, { leaving: true });
    flush({ leaving: true });
    // The page hidden as it goes saves nothing after this one, which adds
    // the task rows: a later save would stand over it without them.
    left = true;
  });
  // Back from the browser's cache: written in again.
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) left = false;
  });

  /* ---- the plan: the day's tasks, not yet written ---- */

  // The tasks planned for this day or due on it (on today's also those
  // overdue, and those still open from the last page before it), {label,
  // tasks: [{id, title, notes, fields, moves, carried, due, since, was}]},
  // each with its fields as they stand once brought here, whether that
  // moves its do-date, whether it is carried over from before (and since
  // when, in words), its due in words ("due today") when it has one, and
  // its do-date as it is now. Those for the day are listed first, those
  // carried over under them.
  let dayTasks = { label: "", tasks: [] };
  let carryShows = null;
  const toBring = (state) => {
    const written = new Set(state.field(tasksField).map(({ m }) => m.id));
    return dayTasks.tasks.filter((t) => !written.has(t.id));
  };
  const CALENDAR = '<svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="14" height="13"/><path d="M7 2.5v3"/><path d="M13 2.5v3"/><path d="M3 8.5h14"/></svg>';
  const projectNames = new Map();
  const planItem = (t) => {
    const item = document.createElement("li");
    item.className = "plan-item";
    item.dataset.task = String(t.id);
    // Its box: written in the notes, done.
    const tick = document.createElement("button");
    tick.type = "button";
    tick.className = "plan-tick";
    tick.setAttribute("role", "checkbox");
    tick.setAttribute("aria-checked", "false");
    tick.setAttribute("aria-label", `Done: ${t.title}`);
    tick.title = "Done: written in the notes, ticked";
    const write = document.createElement("button");
    write.type = "button";
    write.className = "pad-carry-write";
    write.dataset.task = String(t.id);
    write.title = `Bring it here, to do ${dayTasks.label.replace(/^For /, "")}`;
    const title = document.createElement("span");
    title.className = "pad-carry-title";
    title.textContent = t.title;
    write.append(title);
    const project = projectColors.get(String(t.fields.project_id));
    if (project) {
      // Its project's flag, its name on hover.
      const flag = document.createElement("span");
      flag.className = "plan-flag";
      flag.style.setProperty("--project", `var(--hue-${project})`);
      flag.setAttribute("role", "img");
      flag.setAttribute("aria-label", projectNames.get(String(t.fields.project_id)) || "Project");
      flag.title = flag.getAttribute("aria-label");
      title.before(flag);
    }
    if (t.fields.priority) {
      // Its priority's bars, the controls' own icon, its word on hover.
      const bars = document.getElementById("pad-props-template")?.content.querySelector(".priority-icon");
      if (bars) {
        const priority = document.createElement("span");
        priority.className = "pad-carry-priority";
        priority.setAttribute("role", "img");
        const word = t.fields.priority[0].toUpperCase() + t.fields.priority.slice(1);
        priority.title = `Priority: ${word}`;
        priority.setAttribute("aria-label", priority.title);
        const icon = bars.cloneNode(true);
        icon.setAttribute("data-priority", t.fields.priority);
        priority.append(icon);
        title.before(priority);
      }
    }
    item.append(tick, write);
    // When it was meant for: its due, else since when it is carried.
    if (t.due || t.since) {
      const when = document.createElement("span");
      when.className = t.due ? "pad-carry-due" : "plan-since";
      when.textContent = t.due || t.since;
      item.append(when);
    }
    const moveIt = document.createElement("button");
    moveIt.type = "button";
    moveIt.className = "plan-move";
    moveIt.dataset.task = String(t.id);
    moveIt.setAttribute("aria-haspopup", "menu");
    moveIt.setAttribute("aria-expanded", "false");
    moveIt.setAttribute("aria-label", `Move “${t.title}” to another day`);
    moveIt.title = "Move to another day";
    moveIt.innerHTML = CALENDAR;
    item.append(moveIt);
    return item;
  };
  // With nothing in it, the plan says so.
  const drawPlanEmpty = () => {
    const empty = document.querySelector("#today-plan .plan-empty");
    if (empty) empty.hidden = !!document.querySelector("#today-plan .plan-group:not([hidden])");
  };
  function drawPlan() {
    const carry = document.getElementById("pad-carry");
    if (!carry || !view) return;
    const open = toBring(view.state);
    const shows = open.map((t) => t.id).join(" ");
    if (shows === carryShows) return;
    carryShows = shows;
    const groups = [
      [carry, open.filter((t) => !t.carried), dayTasks.label],
      [document.getElementById("pad-late"), open.filter((t) => t.carried), "Carried over"],
    ];
    for (const [fold, list, label] of groups) {
      if (!fold) continue;
      fold.hidden = !list.length;
      fold.querySelector(".today-fold-label").textContent = label;
      fold.querySelector(".today-fold-summary .count").textContent = list.length;
      fold.querySelector(".plan-list").replaceChildren(...list.map(planItem));
    }
    const all = document.querySelector("#today-plan .pad-carry-all");
    if (all) all.hidden = open.length < 2;
    drawPlanEmpty();
  }

  // Tasks brought over: each written at the end of the notes (from its last
  // row, when that is empty), its title row making the same task, its
  // description its rows; and its do-date moved to this day.
  async function bring(list) {
    if (!view || !list.length) return;
    const doc = view.state.doc;
    const last = doc.line(doc.lines);
    const from = last.text.trim() ? last.to : last.from;
    let insert = last.text.trim() ? "\n" : "";
    const tasks = [...view.state.field(tasksField)];
    list.forEach((t, i) => {
      const fields = { ...newFields(), ...t.fields };
      const m = { id: t.id, saved: { title: t.title, notes: t.notes }, fields, known: { ...fields }, folded: false };
      tasks.push({ pos: from + insert.length, m });
      const rows = t.notes ? t.notes.split("\n").map((row) => `\n${TAB}${row}`).join("") : "";
      insert += `- [ ] ${t.title}${rows}${i < list.length - 1 ? "\n" : ""}`;
    });
    view.focus();
    view.dispatch({
      changes: { from, to: last.to, insert }, effects: setTasks.of(tasks),
      selection: { anchor: from + insert.length }, scrollIntoView: true, userEvent: "input",
    });
    const moved = await Promise.all(list.filter((t) => t.moves).map((t) =>
      post(`/ui/tasks/${t.id}/plan`, new URLSearchParams({ planned_for: day })).then((r) => r.ok, () => false)));
    if (moved.includes(false)) window.toast("Could not move every task to this day. Their rows are in the notes.");
    if (moved.length) htmx.trigger(document.body, "calendar:refresh");
  }
  const offered = (id) => toBring(view.state).filter((t) => String(t.id) === id);
  document.addEventListener("click", async (e) => {
    if (!view) return;
    const write = e.target.closest?.(".pad-carry-write");
    const tick = e.target.closest?.(".plan-tick");
    if (write) bring(offered(write.dataset.task));
    else if (e.target.closest?.(".pad-carry-all")) bring(toBring(view.state));
    else if (tick) {
      // Written, ticked there at once: done this day, in the notes; the
      // task itself ticked once it is moved to the day.
      const id = tick.closest(".plan-item").dataset.task;
      const moving = bring(offered(id));
      const block = blocks().find((b) => String(b.m.id) === id);
      if (!block) return;
      mark(block.m, true);
      await moving;
      setDone(block.m, true);
    }
  });

  // Moved to another day: off this day's plan (Undo puts it back as it was).
  async function moveTo(list, plannedFor) {
    if (!list.length) return;
    const before = dayTasks.tasks.slice();
    const sent = await Promise.all(list.map((t) =>
      post(`/ui/tasks/${t.id}/plan`, new URLSearchParams({ planned_for: plannedFor })).then((r) => r.ok, () => false)));
    const moved = list.filter((_, i) => sent[i]);
    const gone = new Set(moved.map((t) => t.id));
    dayTasks.tasks = dayTasks.tasks.filter((t) => !gone.has(t.id));
    carryShows = null;
    drawPlan();
    if (moved.length) htmx.trigger(document.body, "calendar:refresh");
    if (moved.length < list.length) {
      window.toast("Could not move every task. Those left are still here.");
      return;
    }
    const to = plannedFor ? window.TaskSheet.shortDate(plannedFor) : "no date";
    const what = moved.length === 1 ? `“${moved[0].title}”` : `${moved.length} tasks`;
    window.toast(`Moved ${what} to ${to}.`, {
      action: "Undo",
      run: async () => {
        const back = await Promise.all(moved.map((t) =>
          post(`/ui/tasks/${t.id}/plan`, new URLSearchParams({ planned_for: t.was || "" })).then((r) => r.ok, () => false)));
        const restored = new Set(moved.filter((_, i) => back[i]).map((t) => t.id));
        dayTasks.tasks = before.filter((t) => !gone.has(t.id) || restored.has(t.id));
        carryShows = null;
        drawPlan();
        htmx.trigger(document.body, "calendar:refresh");
        if (restored.size < moved.length) window.toast("Could not put every task back.");
      },
    });
  }

  // A row's calendar, or Reschedule on Carried over: a menu of days, as the
  // task sheet's do-date offers them (in the body, on the page's paper).
  let moveMenu = null; // {button, el}
  const closeMoveMenu = (restore = true) => {
    if (!moveMenu) return;
    const { button, el } = moveMenu;
    moveMenu = null;
    el.remove();
    button.setAttribute("aria-expanded", "false");
    if (restore && button.isConnected) button.focus();
  };
  function openMoveMenu(button, list) {
    closeMoveMenu(false);
    const el = document.createElement("div");
    el.className = "sheet-menu plan-move-menu";
    el.setAttribute("role", "menu");
    el.setAttribute("aria-label", list.length === 1 ? "Move it to" : `Move ${list.length} tasks to`);
    const choices = [...window.TaskSheet.soonDays(), ["Pick a date…", "pick"], ["No date", ""]];
    for (const [label, value] of choices) {
      const item = document.createElement("button");
      item.type = "button";
      item.tabIndex = -1;
      item.setAttribute("role", "menuitemradio");
      item.setAttribute("aria-checked", "false");
      item.dataset.value = value;
      item.innerHTML = '<span class="label"></span>';
      item.querySelector(".label").textContent = label;
      if (value && value !== "pick") {
        const aside = document.createElement("span");
        aside.className = "aside";
        aside.textContent = window.TaskSheet.shortDate(value);
        if (aside.textContent !== label.toLowerCase()) item.append(aside);
      }
      if (value === "pick") {
        // The native picker anchors to its input, unseen under the item.
        const input = document.createElement("input");
        input.type = "date";
        input.className = "plan-move-pick";
        input.tabIndex = -1;
        input.setAttribute("aria-hidden", "true");
        input.addEventListener("change", () => {
          if (!input.value) return;
          closeMoveMenu();
          moveTo(list, input.value);
        });
        item.append(input);
      }
      el.append(item);
    }
    document.body.append(el);
    const at = button.getBoundingClientRect();
    const below = window.innerHeight - at.bottom >= el.offsetHeight + 8;
    el.style.top = `${Math.max(8, below ? at.bottom + 4 : at.top - el.offsetHeight - 4)}px`;
    el.style.left = `${Math.max(8, Math.min(at.right - el.offsetWidth, window.innerWidth - el.offsetWidth - 8))}px`;
    button.setAttribute("aria-expanded", "true");
    moveMenu = { button, el, list };
    el.firstElementChild.focus();
  }
  const chooseMove = (item) => {
    const { list } = moveMenu;
    if (item.dataset.value === "pick") {
      const input = item.querySelector("input");
      try { input.showPicker(); } catch { input.click(); }
      return;
    }
    closeMoveMenu();
    moveTo(list, item.dataset.value);
  };
  document.addEventListener("click", (e) => {
    const one = e.target.closest?.(".plan-move");
    const every = e.target.closest?.(".plan-move-all");
    if ((one || every) && view) {
      if (moveMenu?.button === (one || every)) { closeMoveMenu(); return; }
      const list = one ? offered(one.dataset.task) : toBring(view.state).filter((t) => t.carried);
      if (list.length) openMoveMenu(one || every, list);
      return;
    }
    if (!moveMenu) return;
    const item = e.target.closest?.(".plan-move-menu [data-value]");
    if (item && moveMenu.el.contains(item)) {
      if (!e.target.closest?.("input")) chooseMove(item);
    } else if (!moveMenu.el.contains(e.target)) closeMoveMenu(false);
  });
  document.addEventListener("keydown", (e) => {
    if (!moveMenu || !moveMenu.el.contains(e.target)) return;
    const items = [...moveMenu.el.querySelectorAll("[data-value]")];
    const at = items.indexOf(e.target.closest("[data-value]"));
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      handled();
      items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    } else if (e.key === "Home" || e.key === "End") {
      handled();
      items[e.key === "Home" ? 0 : items.length - 1].focus();
    } else if (e.key === "Enter" || e.key === " ") {
      handled();
      chooseMove(items[at]);
    } else if (e.key === "Escape" || (e.key === "Tab" && !e.ctrlKey)) {
      handled();
      closeMoveMenu();
    } else if (e.key !== "Tab") {
      e.stopPropagation(); // the page's own keys stay out of the menu
    }
  }, true);
  window.addEventListener("resize", () => closeMoveMenu(false));
  document.addEventListener("scroll", (e) => {
    if (moveMenu && !moveMenu.el.contains(e.target)) closeMoveMenu(false);
  }, true);

  /* ---- the page's folds: the plan's groups, and the habits ---- */

  // Those folded are kept in a cookie (today-layout.js), the page drawn
  // with them so (partials/today_fold.html), on every day's page.
  // "toggle" does not bubble; capture it on the way down.
  document.addEventListener("toggle", (e) => {
    const fold = e.target;
    if (fold.matches?.("details[data-fold]")) window.TodayFolds.set(fold.dataset.fold, !fold.open);
  }, true);

  // A nudge dismissed: its count says so, and the last takes the center
  // away (the plan saying so when nothing else is in it).
  const nudges = document.getElementById("nudge-center");
  if (nudges) {
    new MutationObserver(() => {
      const left = nudges.querySelectorAll(".nudge").length;
      if (left) nudges.querySelector(".today-fold-summary .count").textContent = left;
      else nudges.remove();
      drawPlanEmpty();
    }).observe(nudges.querySelector(".nudge-list"), { childList: true });
  }

  // Offered while writing: the commands, after "/" at a row's start.
  const COMMANDS = [
    { label: "/reflection", apply: "/reflection ", detail: "free text" },
  ];
  const offer = (context) => {
    const line = context.state.doc.lineAt(context.pos);
    const before = line.text.slice(0, context.pos - line.from);
    if (/^\/[a-z]*$/.test(before)) {
      return {
        from: line.from,
        options: COMMANDS.map((c) => ({
          ...c,
          apply: (v, completion, from, to) => {
            v.dispatch({ changes: { from, to, insert: c.apply }, selection: { anchor: from + c.apply.length }, userEvent: "input.complete" });
          },
        })),
        validFor: /^\/[a-z]*$/,
      };
    }
    return null;
  };

  /* ---- start ---- */

  const theme = EditorView.theme({
    "&": { height: "100%", fontSize: "var(--t-body-sm)", letterSpacing: "-0.01em" },
    "&.cm-focused": { outline: "none" },
    ".cm-scroller": { fontFamily: "inherit", lineHeight: "var(--pad-text)" },
    ".cm-content": { padding: "0", caretColor: "var(--ink)" },
    ".cm-line": {
      padding: "var(--pad-above) var(--s-4) var(--pad-below) var(--pad-gap)",
      borderBottom: "1px solid var(--hairline)",
      color: "var(--pad-words)",
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
    // What is offered while writing: drawn as the icons' menus are.
    ".cm-tooltip.cm-tooltip-autocomplete": {
      padding: "var(--s-1)",
      background: "var(--paper)",
      border: "1px solid var(--hairline)",
      borderRadius: "var(--r-ctl)",
      boxShadow: "var(--shadow-dropdown)",
    },
    ".cm-tooltip.cm-tooltip-autocomplete > ul": { fontFamily: "inherit", fontSize: "var(--t-body-sm)", maxHeight: "min(280px, 50vh)" },
    ".cm-tooltip.cm-tooltip-autocomplete > ul > li": {
      display: "flex", alignItems: "baseline", gap: "var(--s-2)",
      minHeight: "32px", padding: "6px 10px", lineHeight: "20px", color: "var(--ink)",
    },
    ".cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]": { background: "var(--fog)", color: "var(--ink)" },
    ".cm-completionMatchedText": { textDecoration: "none", fontWeight: "600" },
    ".cm-completionDetail": { marginLeft: "auto", fontStyle: "normal", fontSize: "var(--t-caption)", color: "var(--pewter)" },
  });

  // The Markdown's mode: the one in use, else the one the notes were last
  // left in.
  const modeNow = () => (view && window.MarkdownLive.modeOf(view)) || window.MarkdownLive.rememberedMode("notes");

  // The notepad's own first, so its rows' drawing and keys come before the
  // engine's.
  const extensions = () => [
    tasksField, keepTasks, focusField, fillerField, drawField, offTheLead, unfoldFirst, wordsToFields,
    fieldHistory, setFields, pasteInside, rowsStayTogether,
    EditorView.focusChangeEffect.of((state, focusing) => setFocus.of(focusing)),
    lineNumbers(),
    lineNumberWidgetMarker.of((v, widget, block) => (widget instanceof Filler
      ? new FillerNumbers(v.state.doc.lines + 1, widget.count)
      : new BlockNumber(v.state.doc.lineAt(block.from).number))),
    fillToBottom,
    history(),
    drawSelection(),
    EditorView.lineWrapping,
    placeholder("Anything on your mind today."),
    EditorView.contentAttributes.of({ "aria-label": "Notes", spellcheck: "true" }),
    escape,
    keys,
    window.MarkdownLive.extensions({ mode: modeNow(), owns, plain: isTask }),
    keepTab,
    keymap.of([...defaultKeymap, ...historyKeymap]),
    autocompletion({ override: [offer], icons: false }),
    EditorView.updateListener.of((u) => {
      if (u.docChanged && !u.transactions.some((tr) => tr.annotation(loading))) schedule();
      if (u.docChanged) drawPlan();
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
    dayTasks = { label: "", tasks: [] };
    try { dayTasks = JSON.parse(src.dataset.dayTasks || "null") || dayTasks; } catch { /* none */ }
    carryShows = null;
    projectColors.clear();
    projectNames.clear();
    const projects = document.getElementById("pad-props-template")?.content.querySelector("[data-sheet-projects]");
    try {
      for (const { id, name, color } of JSON.parse(projects?.textContent || "[]")) {
        projectColors.set(String(id), color);
        projectNames.set(String(id), name);
      }
    } catch { /* none */ }
    const starts = [0];
    for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
    const tasks = rows.filter(({ row }) => row < starts.length).map(({ row, id, fields, folded }) => {
      const given = Object.entries(fields || {}).map(([name, value]) => [name, value == null ? "" : String(value)]);
      const its = { ...newFields(), ...Object.fromEntries(given) };
      const m = { id, saved: null, fields: its, known: id ? { ...its } : null, folded: !!folded };
      return { pos: starts[row], m };
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
    drawPlan();
  }

  // Compact rows, or the timeline folded: the rows' size or the box's width changed.
  document.addEventListener("density:change", () => view?.requestMeasure());

  const el = source();
  if (el) load(el);
  // The day header's switch between the Markdown's modes, and Ctrl+E.
  const modes = document.querySelector(".today-page [data-md-modes]");
  if (el && modes) window.MarkdownLive.bindSwitch(modes, () => view, "notes");
  // For the page's tests: the notes as written.
  window.Notepad = { get view() { return view; }, text: () => view?.state.doc.toString() ?? "" };
})();
