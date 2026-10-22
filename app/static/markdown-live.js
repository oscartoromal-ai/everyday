/* The Markdown engine: Markdown written in CodeMirror 6 (window.CM) and
   drawn as it reads while it is written, as Obsidian's Live Preview is.

   The text is the record. Every effect here is a decoration over the
   characters, never a change to them, so what is saved, copied and undone
   is the Markdown exactly as written, byte for byte.

   It has Obsidian's three modes:
   - "live": every element is drawn rendered, its syntax hidden, until the
     caret or a selection reaches it, when its marks show in steel: a
     heading's, a quote's or a rule's by their line, emphasis, code, links
     and images by the element, a fenced block and a table by the block.
     Out of focus, everything is drawn rendered.
   - "source": the Markdown as written, all its marks showing in steel.
   - "reading": drawn rendered throughout and not editable, though its boxes
     still tick and its links still open.

   What the text says comes from the Lezer Markdown parser (CommonMark with
   GitHub's tables, strikethrough, task boxes and bare links), parsed as it
   changes and drawn only as far as the window shows. These are notes, not
   a typesetting source: an indented line nests under the one above instead
   of turning into code, "---" under a line is a rule (not a heading made of
   that line), and HTML blocks are just text. Raw HTML is never rendered.

   A list item's lead (its indentation, "- " and box) is drawn as one piece,
   a checkbox or a bullet, and the caret never stands inside it. Lists are
   read line by line, as app/checklist.py reads a task's sub-tasks: "- " is
   a bullet and "- [ ] " a box, exactly as the server counts them.

   Only an http(s) address is a link, as in a task's row (app/markdown.py).
   A rendered link opens on a click, a revealed one on Ctrl+click (Cmd+click);
   only web and data images are drawn.

   A page adds MarkdownLive.extensions(options) to its editor beside its own
   (history, placeholder, saving) and switches modes with setMode,
   toggleReading and toggleSource. Options:
   - mode: the mode it opens in ("live").
   - openLink(href): opens a link (beside the app, as a chat's link does).
   - imageSrc(url): the src an image is drawn from, or null to leave its
     Markdown showing (web and data images).
   - owns(line): whether the page draws this line itself (Today's notepad
     its tasks, reflections, habits and stays, and the rows tabbed under
     them). The engine then draws only the line's inline Markdown (emphasis,
     code, links, images, escapes): never its lead, its block (a heading, a
     quote, a rule, a fence, a table) or its keys, which are the page's.
   - plain(line): whether a line the page owns is drawn exactly as written,
     no Markdown in it at all (Today's task titles: a title is plain words
     wherever it shows).
   - ownsTab: whether Tab, beyond nesting a list, is the page's (Today's
     notepad steps into its tasks with it). Else it is the editor's: Tab
     indents and never leaves, and Shift+Tab, from a line at the left,
     steps out of the editor.
   Its keys: Enter, Shift+Enter, Backspace, Tab and Shift+Tab for lists
   and indentation, Ctrl+L an item's box, Ctrl+B, Ctrl+I, Ctrl+Shift+X and Ctrl+` the marks.
   Ctrl+E (toggleReading) is the page's to bind: reading is not editable, so
   the editor cannot hear the key back out of it. bindSwitch binds it, with
   a page's Live Preview, Source and Reading buttons (partials/md_modes.html),
   and remembers the mode for the kind of page, opened again in
   rememberedMode(key). */

(() => {
  const {
    Decoration, EditorSelection, EditorState, EditorView, GFM, Prec, StateEffect, StateField,
    ViewPlugin, WidgetType, codeLanguages, commonmarkLanguage, keymap, markdown, markdownKeymap,
    syntaxHighlighting, syntaxTree, tagHighlighter, tags,
  } = window.CM;

  const MODES = ["live", "source", "reading"];

  /* ---- the mode and the focus, as state ---- */

  const setModeEffect = StateEffect.define();
  const modeField = StateField.define({
    create: () => "live",
    update(mode, tr) {
      for (const e of tr.effects) if (e.is(setModeEffect)) mode = e.value;
      return mode;
    },
  });

  // Focus is state too, so that the tables' field (state, not view) sees it.
  const focusEffect = StateEffect.define();
  const focusField = StateField.define({
    create: () => false,
    update(focused, tr) {
      for (const e of tr.effects) if (e.is(focusEffect)) focused = e.value;
      return focused;
    },
  });

  const modeChanged = (tr) => tr.effects.some((e) => e.is(setModeEffect) || e.is(focusEffect));

  // Whether from..to has its marks showing: everywhere in source, nowhere
  // in reading, and in live where the caret or a selection reaches it while
  // the editor has focus.
  function shows(state, from, to) {
    const mode = state.field(modeField);
    if (mode !== "live") return mode === "source";
    if (!state.field(focusField)) return false;
    return state.selection.ranges.some((r) => r.from <= to && r.to >= from);
  }
  const lineShows = (state, pos) => {
    const line = state.doc.lineAt(pos);
    return shows(state, line.from, line.to);
  };

  /* ---- the parser ---- */

  const language = markdown({
    base: commonmarkLanguage,
    extensions: [GFM, { remove: ["IndentedCode", "SetextHeading", "HTMLBlock"] }],
    codeLanguages,
    addKeymap: false,
    completeHTMLTags: false,
  });

  /* ---- lists, line by line ---- */

  const INDENT_UNIT = "  ";
  const MAX_DEPTH = 6;
  // A list item up to its words, as app/checklist.py's _LIST reads it.
  const LIST_LEAD = /^([ \t]*)([-*+])[ \t]+(?:\[([ xX])\][ \t]+)?/;

  const width = (indent) => indent.replace(/\t/g, "    ").length;
  const depthOf = (indent) => Math.min(MAX_DEPTH, Math.floor(width(indent) / 2));

  // A line's list item, or its indentation: {lead, indent, marker, box,
  // depth}, box being null (none), " " or "x". `lead` is what is drawn as
  // one piece: the item's indentation, marker and box, or a plain line's
  // indentation (when it has words after it).
  const leadOf = (text) => {
    const m = LIST_LEAD.exec(text);
    if (m) {
      return {
        item: true, lead: m[0], indent: m[1], marker: m[2],
        box: m[3] === undefined ? null : m[3].toLowerCase(), depth: depthOf(m[1]),
      };
    }
    const indent = /^[ \t]*/.exec(text)[0];
    const lead = indent && indent.length < text.length ? indent : "";
    return { item: false, lead, indent, marker: null, box: null, depth: lead ? depthOf(indent) : 0 };
  };

  // Whether a line is a fenced block's code, between its fences.
  const inCode = (state, line) => {
    for (let node = syntaxTree(state).resolveInner(line.from, 1); node; node = node.parent) {
      if (node.name !== "FencedCode") continue;
      const { doc } = state;
      const close = doc.lineAt(node.to);
      return line.number > doc.lineAt(node.from).number
        && (line.number < close.number || !/^\s*(`{3,}|~{3,})/.test(close.text));
    }
    return false;
  };

  /* ---- widgets ---- */

  // A box (or a bullet) is drawn in a lead as wide as the gap before the
  // words, so the caret after it stands where the words do, not on its edge.
  class Box extends WidgetType {
    constructor(checked) {
      super();
      this.checked = checked;
    }
    eq(other) {
      return other.checked === this.checked;
    }
    toDOM(view) {
      const lead = document.createElement("span");
      lead.className = "cm-md-lead";
      const box = lead.appendChild(document.createElement("button"));
      box.type = "button";
      box.tabIndex = -1; // Ctrl+L ticks it from the keyboard
      box.className = "cm-md-box";
      box.setAttribute("role", "checkbox");
      box.setAttribute("aria-checked", String(this.checked));
      box.setAttribute("aria-label", "Done");
      // The caret stays where it was; the box is ticked on the click.
      box.addEventListener("mousedown", (e) => e.preventDefault());
      box.addEventListener("click", (e) => {
        e.preventDefault();
        if (!view.state.readOnly) tick(view, view.state.doc.lineAt(view.posAtDOM(lead)));
      });
      return lead;
    }
    ignoreEvent() {
      return true;
    }
  }
  const BOXES = {
    open: Decoration.replace({ widget: new Box(false) }),
    done: Decoration.replace({ widget: new Box(true) }),
  };

  class Bullet extends WidgetType {
    eq() {
      return true;
    }
    toDOM() {
      const bullet = document.createElement("span");
      bullet.className = "cm-md-lead cm-md-bullet";
      bullet.setAttribute("aria-hidden", "true");
      return bullet;
    }
  }

  class ImageWidget extends WidgetType {
    constructor(src, alt) {
      super();
      this.src = src;
      this.alt = alt;
    }
    eq(other) {
      return other.src === this.src && other.alt === this.alt;
    }
    toDOM(view) {
      const img = document.createElement("img");
      img.className = "cm-md-image";
      img.src = this.src;
      img.alt = this.alt;
      img.title = this.alt;
      img.draggable = false;
      // Its height lands once it loads: the editor measures its lines again.
      img.addEventListener("load", () => view.requestMeasure());
      img.addEventListener("error", () => {
        img.classList.add("is-broken");
        view.requestMeasure();
      });
      return img;
    }
    ignoreEvent() {
      return false;
    }
  }

  // A fenced block's language, at its top right while its fences fold.
  class LanguageLabel extends WidgetType {
    constructor(name) {
      super();
      this.name = name;
    }
    eq(other) {
      return other.name === this.name;
    }
    toDOM() {
      const label = document.createElement("span");
      label.className = "cm-md-code-lang";
      label.textContent = this.name;
      return label;
    }
  }

  const BULLET = Decoration.replace({ widget: new Bullet() });
  const HIDDEN = Decoration.replace({});
  const MARK = Decoration.mark({ class: "cm-md-mark" });
  const STYLE = {
    Emphasis: Decoration.mark({ class: "cm-md-em" }),
    StrongEmphasis: Decoration.mark({ class: "cm-md-strong" }),
    Strikethrough: Decoration.mark({ class: "cm-md-strike" }),
    InlineCode: Decoration.mark({ class: "cm-md-code" }),
  };
  const MARKS = new Set(["EmphasisMark", "StrikethroughMark", "CodeMark"]);
  const TABLE_MARKS = new Set([...MARKS, "TableDelimiter", "LinkMark", "URL"]);
  const NUMBER = Decoration.mark({ class: "cm-md-list-number" });
  const lineDeco = (className, depth = 0) => Decoration.line(
    depth ? { class: className, attributes: { style: `--md-depth: ${depth}` } } : { class: className },
  );
  const SPELLED = Decoration.line({ attributes: { spellcheck: "true" } });

  // Only a web address is a link, as in the task's row (app/markdown.py):
  // "www.x.com", "mailto:" or "javascript:" stay words.
  const hrefOf = (url) => (/^https?:\/\/\S+$/i.test(url) ? url : null);
  const linkDeco = (href, rendered) => Decoration.mark({
    class: rendered ? "cm-md-link cm-md-rendered" : "cm-md-link",
    attributes: { "data-href": href, title: rendered ? href : `${href}\nCtrl+click to open` },
  });

  /* ---- inline Markdown as DOM, for a table's cells ---- */

  const CELL_TAG = { Emphasis: "em", StrongEmphasis: "strong", Strikethrough: "s", InlineCode: "code" };
  const CELL_HIDDEN = new Set(["EmphasisMark", "CodeMark", "LinkMark", "StrikethroughMark", "LinkTitle", "LinkLabel"]);

  // The text of from..to under node, its child elements drawn as theirs.
  function inlineDOM(state, node, from, to, parent, options) {
    let pos = from;
    for (let child = node.firstChild; child; child = child.nextSibling) {
      if (child.to <= from || child.from >= to) continue;
      if (child.from > pos) parent.append(state.sliceDoc(pos, child.from));
      parent.append(inlineElement(state, child, options));
      pos = child.to;
    }
    if (to > pos) parent.append(state.sliceDoc(pos, to));
  }

  function inlineElement(state, node, options) {
    const text = state.sliceDoc(node.from, node.to);
    if (CELL_HIDDEN.has(node.name)) return "";
    if (node.name === "Escape") return text.slice(1);
    if (CELL_TAG[node.name]) {
      const el = document.createElement(CELL_TAG[node.name]);
      inlineDOM(state, node, node.from, node.to, el, options);
      return el;
    }
    if (node.name === "Link") {
      const label = linkLabel(node);
      const href = hrefOf(childText(state, node, "URL") || "");
      if (!label || !href) return text;
      const a = document.createElement("span");
      a.className = "cm-md-link cm-md-rendered";
      a.dataset.href = href;
      inlineDOM(state, node, label.from, label.to, a, options);
      return a;
    }
    if (node.name === "URL" || node.name === "Autolink") {
      const url = node.name === "URL" ? text : childText(state, node, "URL") || "";
      const href = hrefOf(url);
      if (!href) return text;
      const a = document.createElement("span");
      a.className = "cm-md-link cm-md-rendered";
      a.dataset.href = href;
      a.textContent = href;
      return a;
    }
    if (node.name === "Image") {
      const src = options.imageSrc(childText(state, node, "URL") || "");
      if (!src) return text;
      const label = linkLabel(node);
      const img = document.createElement("img");
      img.className = "cm-md-image";
      img.src = src;
      img.alt = label ? state.sliceDoc(label.from, label.to) : "";
      return img;
    }
    return text;
  }

  function childText(state, node, name) {
    const child = node.getChild(name);
    return child ? state.sliceDoc(child.from, child.to) : null;
  }

  // A link's or image's words: between its "[" (or "![") and its "]".
  function linkLabel(node) {
    const open = node.firstChild;
    if (open?.name !== "LinkMark") return null;
    for (let child = open.nextSibling; child; child = child.nextSibling) {
      if (child.name === "LinkMark") return { from: open.to, to: child.from };
    }
    return null;
  }

  /* ---- tables: a block widget, so a state field's ---- */

  // A table as its rows and the columns' alignments, each cell its node (or
  // none, when empty) and the place a click on it puts the caret.
  function tableModel(state, node) {
    const rows = [];
    let aligns = [];
    for (let row = node.firstChild; row; row = row.nextSibling) {
      if (row.name === "TableDelimiter") {
        aligns = state.sliceDoc(row.from, row.to).trim().replace(/^\||\|$/g, "").split("|")
          .map((spec) => {
            const s = spec.trim();
            if (s.startsWith(":") && s.endsWith(":")) return "center";
            if (s.endsWith(":")) return "right";
            if (s.startsWith(":")) return "left";
            return "";
          });
      } else if (row.name === "TableHeader" || row.name === "TableRow") {
        rows.push(tableCells(row));
      }
    }
    return { rows, aligns };
  }

  function tableCells(row) {
    const pipes = [];
    const cells = [];
    for (let child = row.firstChild; child; child = child.nextSibling) {
      if (child.name === "TableDelimiter") pipes.push({ from: child.from, to: child.to });
      else if (child.name === "TableCell") cells.push(child);
    }
    // The cells lie between the pipes, and before the first and after the
    // last when the row does without its outer ones.
    if (!pipes.length || pipes[0].from > row.from) pipes.unshift({ from: row.from, to: row.from });
    if (pipes[pipes.length - 1].to < row.to) pipes.push({ from: row.to, to: row.to });
    const out = [];
    for (let i = 0; i + 1 < pipes.length; i++) {
      const from = pipes[i].to;
      const to = pipes[i + 1].from;
      const node = cells.find((c) => c.from >= from && c.to <= to) || null;
      out.push({ node, caret: node ? node.to : Math.min(from + 1, to) });
    }
    return out;
  }

  class TableWidget extends WidgetType {
    constructor(state, node, options) {
      super();
      this.source = state.sliceDoc(node.from, node.to);
      this.from = node.from;
      this.model = tableModel(state, node);
      this.state = state;
      this.options = options;
    }
    eq(other) {
      return other.source === this.source;
    }
    toDOM(view) {
      const { rows, aligns } = this.model;
      const wrap = document.createElement("div");
      wrap.className = "cm-md-table-wrap";
      const table = document.createElement("table");
      table.className = "cm-md-table";
      const columns = rows[0]?.length || 0;
      rows.forEach((cells, r) => {
        const section = r === 0 ? table.createTHead() : (table.tBodies[0] || table.createTBody());
        const tr = section.insertRow();
        for (let c = 0; c < columns; c++) {
          const cell = cells[c];
          const td = document.createElement(r === 0 ? "th" : "td");
          if (aligns[c]) td.style.textAlign = aligns[c];
          if (cell) {
            td.dataset.caret = String(cell.caret - this.from);
            if (cell.node) inlineDOM(this.state, cell.node, cell.node.from, cell.node.to, td, this.options);
          }
          tr.append(td);
        }
      });
      wrap.append(table);
      // A click in a cell writes in it: the table opens as its Markdown, the
      // caret at the cell's end. A link in a cell opens instead.
      wrap.addEventListener("mousedown", (e) => {
        if (e.button !== 0 || e.target.closest("[data-href]")) return;
        const td = e.target.closest("[data-caret]");
        if (!td || view.state.field(modeField) !== "live") return;
        e.preventDefault();
        const start = view.posAtDOM(wrap);
        view.focus();
        view.dispatch({ selection: { anchor: start + Number(td.dataset.caret) } });
      });
      return wrap;
    }
    ignoreEvent(e) {
      return e.type === "mousedown";
    }
  }

  // The tables, and those drawn as tables (the ones not showing their marks).
  // One starting on a line the page owns is its words.
  function tableField(options) {
    const build = (state) => {
      const tables = [];
      const widgets = [];
      if (state.field(modeField) !== "source") {
        syntaxTree(state).iterate({
          enter(node) {
            if (node.name !== "Table") return undefined;
            const from = state.doc.lineAt(node.from).from;
            const to = state.doc.lineAt(node.to).to;
            if (options.owns(state.doc.lineAt(from))) return false;
            if (!shows(state, from, to)) {
              tables.push({ from, to });
              widgets.push(Decoration.replace({
                widget: new TableWidget(state, node.node, options),
                block: true,
              }).range(from, to));
            }
            return false;
          },
        });
      }
      return { tables, deco: Decoration.set(widgets) };
    };
    return StateField.define({
      create: build,
      update(value, tr) {
        const parsed = syntaxTree(tr.startState) !== syntaxTree(tr.state);
        if (tr.docChanged || tr.selection || parsed || modeChanged(tr)) return build(tr.state);
        return value;
      },
      provide: (f) => EditorView.decorations.from(f, (v) => v.deco),
    });
  }

  /* ---- everything else: a view plugin over the window's lines ---- */

  // What the editor shows at this moment: the window's decorations, and the
  // leads the caret steps over as one piece.
  function draw(view, options, tables) {
    const { state } = view;
    const { doc } = state;
    const mode = state.field(modeField);
    const rendering = mode !== "source";
    const inTable = (pos) => tables.some((t) => pos >= t.from && pos <= t.to);
    // A line the page draws itself: only its inline Markdown is the engine's.
    const owned = (pos) => options.owns(doc.lineAt(pos));

    const decos = [];
    const atomic = [];
    const styled = new Set(); // lines with a line decoration of a kind, as "kind:number"
    const onLine = (pos, kind, deco) => {
      const n = doc.lineAt(pos).number;
      if (styled.has(`${kind}:${n}`)) return;
      styled.add(`${kind}:${n}`);
      decos.push(deco.range(doc.line(n).from));
    };
    const hide = (from, to) => {
      if (to > from) decos.push(HIDDEN.range(from, to));
    };
    // A mark: shown in steel, or hidden.
    const markOrHide = (shown, from, to) => {
      if (to <= from) return;
      if (shown) decos.push(MARK.range(from, to));
      else decos.push(HIDDEN.range(from, to));
    };
    const tree = syntaxTree(state);
    const codeLines = new Set();

    for (const { from, to } of view.visibleRanges) {
      tree.iterate({
        from,
        to,
        enter: (node) => {
          const name = node.name;
          if (name === "Table") {
            if (inTable(node.from) || owned(node.from)) return false;
            // Written, a table is its Markdown, every mark in it showing.
            for (let n = doc.lineAt(node.from).number; n <= doc.lineAt(node.to).number; n++) {
              codeLines.add(n);
              onLine(doc.line(n).from, "table", lineDeco("cm-md-table-src"));
            }
            tree.iterate({
              from: node.from,
              to: node.to,
              enter: (inner) => {
                if (TABLE_MARKS.has(inner.name)) decos.push(MARK.range(inner.from, inner.to));
              },
            });
            return false;
          }
          const heading = /^ATXHeading(\d)$/.exec(name);
          if (heading) {
            if (!owned(node.from)) onLine(node.from, "h", lineDeco(`cm-md-h cm-md-h${heading[1]}`));
            return undefined;
          }
          if (name === "HeaderMark") {
            if (owned(node.from)) return undefined;
            const line = doc.lineAt(node.from);
            const text = line.text;
            let a = node.from - line.from;
            let b = node.to - line.from;
            // "# " goes with its space; closing "#"s with the spaces before them.
            if (node.from === node.node.parent.from) {
              while (b < text.length && text[b] === " ") b++;
            } else {
              while (a > 0 && text[a - 1] === " ") a--;
            }
            markOrHide(lineShows(state, node.from), line.from + a, line.from + b);
            return undefined;
          }
          if (STYLE[name]) {
            decos.push(STYLE[name].range(node.from, node.to));
            const shown = shows(state, node.from, node.to);
            for (let mark = node.node.firstChild; mark; mark = mark.nextSibling) {
              if (MARKS.has(mark.name)) markOrHide(shown, mark.from, mark.to);
            }
            return name === "InlineCode" ? false : undefined;
          }
          if (name === "Link") {
            // "[words](url)": the words as the link. "[words]" alone, or
            // "[words][ref]", is left as written: notes say "[TBD]".
            const marks = node.node.getChildren("LinkMark");
            const href = hrefOf(childText(state, node.node, "URL") || "");
            if (!href || marks.length < 3) return undefined;
            const close = marks[1];
            const shown = shows(state, node.from, node.to);
            if (close.from > marks[0].to) decos.push(linkDeco(href, !shown).range(marks[0].to, close.from));
            markOrHide(shown, node.from, marks[0].to);
            markOrHide(shown, close.from, node.to);
            return undefined;
          }
          if (name === "Autolink") {
            // "<https://...>": the address as a link, its brackets hidden.
            const url = node.node.getChild("URL");
            const href = url && hrefOf(doc.sliceString(url.from, url.to));
            if (!href) return false;
            const shown = shows(state, node.from, node.to);
            decos.push(linkDeco(href, !shown).range(url.from, url.to));
            markOrHide(shown, node.from, url.from);
            markOrHide(shown, url.to, node.to);
            return false;
          }
          if (name === "URL") {
            // A bare address (a link's own is drawn with its link).
            const href = hrefOf(doc.sliceString(node.from, node.to));
            const parent = node.node.parent?.name;
            if (href && parent !== "Link" && parent !== "Image") {
              decos.push(linkDeco(href, rendering).range(node.from, node.to));
            }
            return undefined;
          }
          if (name === "Image") {
            // Drawn as itself, its Markdown showing where the caret is.
            const src = options.imageSrc(childText(state, node.node, "URL") || "");
            if (src && !shows(state, node.from, node.to)) {
              const label = linkLabel(node.node);
              const alt = label ? doc.sliceString(label.from, label.to) : "";
              decos.push(Decoration.replace({ widget: new ImageWidget(src, alt) }).range(node.from, node.to));
            } else {
              decos.push(MARK.range(node.from, node.to));
            }
            return false;
          }
          if (name === "Escape") {
            // "\*": the star, without its backslash.
            if (!shows(state, node.from, node.to)) hide(node.from, node.from + 1);
            return undefined;
          }
          if (name === "QuoteMark") {
            if (owned(node.from)) return undefined;
            onLine(node.from, "quote", lineDeco("cm-md-quote"));
            const line = doc.lineAt(node.from);
            const space = node.to < line.to && doc.sliceString(node.to, node.to + 1) === " " ? 1 : 0;
            if (lineShows(state, node.from)) decos.push(MARK.range(node.from, node.to));
            else hide(node.from, node.to + space);
            return undefined;
          }
          if (name === "HorizontalRule") {
            // "---" drawn as the rule it makes, written as itself.
            if (owned(node.from)) return false;
            if (lineShows(state, node.from)) {
              decos.push(MARK.range(node.from, node.to));
            } else {
              onLine(node.from, "hr", lineDeco("cm-md-hr"));
              hide(node.from, node.to);
            }
            return false;
          }
          if (name === "FencedCode") {
            // Its fences ("```js") fold to the block's edges until the caret
            // is in the block, its language at its top right. One opened on
            // a line the page owns is its words.
            if (owned(node.from)) return false;
            const first = doc.lineAt(node.from).number;
            const last = doc.lineAt(node.to).number;
            const shown = shows(state, node.from, node.to);
            const info = (childText(state, node.node, "CodeInfo") || "").trim().split(/\s/)[0];
            for (let n = first; n <= last; n++) {
              codeLines.add(n);
              const line = doc.line(n);
              const fence = (n === first || n === last) && /^\s*(`{3,}|~{3,})/.test(line.text);
              let kind = "cm-md-codeblock";
              if (fence) {
                kind += ` cm-md-fence ${n === first ? "cm-md-fence-open" : "cm-md-fence-close"}`;
                if (!shown) {
                  kind += " cm-md-fence-folded";
                  hide(line.from, line.to);
                  if (n === first && info) {
                    decos.push(Decoration.widget({ widget: new LanguageLabel(info), side: 1 }).range(line.to));
                  }
                } else {
                  decos.push(MARK.range(line.from, line.to));
                }
              }
              onLine(line.from, "code", lineDeco(kind));
            }
            return false;
          }
          if (name === "ListMark" && node.node.parent?.parent?.name === "OrderedList") {
            decos.push(NUMBER.range(node.from, node.to));
            return false;
          }
          return undefined;
        },
      });

      // Lists and indentation, line by line; in source, as written.
      if (!rendering) continue;
      for (let pos = from; pos <= to;) {
        const line = doc.lineAt(pos);
        pos = line.to + 1;
        if (inTable(line.from) || codeLines.has(line.number) || options.owns(line)) continue;
        const l = leadOf(line.text);
        if (!l.lead) continue;
        const end = line.from + l.lead.length;
        if (l.item) {
          const done = l.box === "x";
          const kind = done ? "cm-md-li cm-md-done" : "cm-md-li";
          onLine(line.from, "li", lineDeco(kind, l.depth));
          const piece = l.box !== null ? (done ? BOXES.done : BOXES.open) : BULLET;
          decos.push(piece.range(line.from, end));
          atomic.push(piece.range(line.from, end));
        } else if (!codeLines.has(line.number)) {
          onLine(line.from, "indent", lineDeco("cm-md-indented", l.depth));
          decos.push(HIDDEN.range(line.from, end));
          atomic.push(HIDDEN.range(line.from, end));
        }
      }
    }

    // A line drawn as written keeps nothing of the Markdown's.
    const drawn = (r) => !options.plain(doc.lineAt(r.from));
    const shown = options.plain === NONE ? decos : decos.filter(drawn);
    const steps = options.plain === NONE ? atomic : atomic.filter(drawn);

    // Spelling is marked only in the line being written.
    const main = state.selection.main;
    if (view.hasFocus && doc.lineAt(main.from).number === doc.lineAt(main.to).number) {
      shown.push(SPELLED.range(doc.lineAt(main.head).from));
    }
    return { decos: Decoration.set(shown, true), atomic: Decoration.set(steps, true) };
  }

  const livePlugin = (options, tables) => ViewPlugin.fromClass(class {
    constructor(view) {
      this.drawn = draw(view, options, view.state.field(tables).tables);
    }
    update(u) {
      if (u.docChanged || u.viewportChanged || u.selectionSet || u.focusChanged
          || syntaxTree(u.state) !== syntaxTree(u.startState) || u.transactions.some(modeChanged)) {
        this.drawn = draw(u.view, options, u.state.field(tables).tables);
      }
    }
  }, {
    decorations: (p) => p.drawn.decos,
    provide: (plugin) => EditorView.atomicRanges.of((view) => view.plugin(plugin)?.drawn.atomic ?? Decoration.none),
  });

  /* ---- the caret: never inside a lead ---- */

  // A caret landing at a list item's (or indented line's) very start goes
  // to its first word, and a selection drawn back to a line's start
  // (Shift+Home) stops there: typing over it keeps the item. In source the
  // lead is text like any other, and on a line the page owns, the page's.
  const offTheLead = (owns) => EditorState.transactionFilter.of((tr) => {
    if (!tr.selection || tr.state.field(modeField) === "source") return tr;
    const { doc, selection } = tr.state;
    let moved = false;
    const ranges = selection.ranges.map((r) => {
      const line = doc.lineAt(r.head);
      if (owns(line)) return r;
      const end = line.from + leadOf(line.text).lead.length;
      if (r.head >= end) return r;
      if (!r.empty) {
        if (r.anchor < end) return r;
        moved = true;
        return EditorSelection.range(r.anchor, end);
      }
      moved = true;
      return EditorSelection.cursor(end);
    });
    if (!moved) return tr;
    return [tr, { selection: EditorSelection.create(ranges, selection.mainIndex), sequential: true }];
  });

  /* ---- ticking ---- */

  // Ticks or unticks a list item's box: only the box's mark changes, as
  // the server writes it (app/checklist.py _set_checked).
  function tick(view, line) {
    const l = leadOf(line.text);
    if (!l.item || l.box === null) return false;
    const at = line.from + l.lead.indexOf("[") + 1;
    view.dispatch({ changes: { from: at, to: at + 1, insert: l.box === "x" ? " " : "x" }, userEvent: "input.tick" });
    return true;
  }

  /* ---- keys ---- */

  const one = (state) => (state.selection.ranges.length === 1 ? state.selection.main : null);
  const newItem = (l) => `${l.indent}${l.marker} ${l.box !== null ? "[ ] " : ""}`;
  const insertAt = (view, r, text, caret = text.length) => {
    view.dispatch({
      changes: { from: r.from, to: r.to, insert: text },
      selection: { anchor: r.from + caret },
      scrollIntoView: true,
      userEvent: "input",
    });
    return true;
  };

  // The list item an indented plain line hangs under: the line above it one
  // level less deep, if that is an item.
  const ownerOf = (state, line, depth) => {
    for (let n = line.number - 1; n >= 1; n--) {
      const above = leadOf(state.doc.line(n).text);
      if (!above.lead && !state.doc.line(n).text.trim()) continue;
      if (above.depth < depth) return above.item && above.depth === depth - 1 ? above : null;
    }
    return null;
  };

  // Ctrl+B, Ctrl+I, Ctrl+Shift+X, Ctrl+`: the selection between the marks,
  // or out of them.
  const wrap = (mark) => (view) => {
    const r = one(view.state);
    if (!r || view.state.readOnly) return false;
    const { doc } = view.state;
    const n = mark.length;
    const before = doc.sliceString(Math.max(0, r.from - n), r.from);
    const after = doc.sliceString(r.to, r.to + n);
    if (before === mark && after === mark) {
      view.dispatch({
        changes: [{ from: r.from - n, to: r.from }, { from: r.to, to: r.to + n }],
        selection: { anchor: r.from - n, head: r.to - n },
        userEvent: "input.format",
      });
      return true;
    }
    view.dispatch({
      changes: [{ from: r.from, insert: mark }, { from: r.to, insert: mark }],
      selection: { anchor: r.from + n, head: r.to + n },
      userEvent: "input.format",
    });
    return true;
  };

  const commands = () => {
    // Enter: a list goes on to its next item, and an empty item steps out of
    // the list a level at a time. Enter at an item's first word puts an
    // empty item above it. An indented note under an item goes on to the
    // item's next sibling; another indented line keeps its indentation.
    const enter = (view) => {
      const r = one(view.state);
      if (!r) return false;
      const { state } = view;
      const line = state.doc.lineAt(r.from);
      if (state.doc.lineAt(r.to).number !== line.number) return false;
      const l = leadOf(line.text);
      const end = line.from + l.lead.length;
      if (l.item) {
        if (!line.text.slice(l.lead.length).trim()) {
          const lead = l.depth > 0 ? l.indent.replace(/^( {1,2}|\t)/, "") + l.lead.slice(l.indent.length) : "";
          view.dispatch({ changes: { from: line.from, to: line.to, insert: lead }, userEvent: "delete.dedent" });
          return true;
        }
        if (r.empty && r.from === end) {
          const above = newItem(l);
          view.dispatch({
            changes: { from: line.from, insert: `${above}\n` },
            selection: { anchor: r.from + above.length + 1 },
            scrollIntoView: true,
            userEvent: "input",
          });
          return true;
        }
        return insertAt(view, r, `\n${newItem(l)}`);
      }
      if (l.lead) {
        const owner = ownerOf(state, line, l.depth);
        return insertAt(view, r, `\n${owner ? newItem({ ...owner, box: owner.box === null ? null : " " }) : l.indent}`);
      }
      return false;
    };

    // Shift+Enter: a plain line, which under an item is that item's note.
    const softEnter = (view) => {
      const r = one(view.state);
      if (!r) return false;
      const l = leadOf(view.state.doc.lineAt(r.from).text);
      const indent = l.item ? l.indent + INDENT_UNIT : l.lead ? l.indent : "";
      return insertAt(view, r, `\n${indent}`);
    };

    // Backspace at an item's first word takes its box (or bullet) away, the
    // line staying where it is; on an indented line, a level of indentation.
    const backspace = (view) => {
      const r = one(view.state);
      if (!r || !r.empty) return false;
      const line = view.state.doc.lineAt(r.head);
      const l = leadOf(line.text);
      if (!l.lead || r.head !== line.from + l.lead.length) return false;
      const lead = l.item ? l.indent : l.indent.replace(/^( {1,2}|\t)/, "");
      view.dispatch({ changes: { from: line.from, to: line.from + l.lead.length, insert: lead }, userEvent: "delete.dedent" });
      return true;
    };

    // firstLine..lastLine a level deeper (delta 1) or shallower (-1): the
    // lines with words, or the one line the caret is on, blank or not.
    const indent = (view, delta, firstLine, lastLine) => {
      const { doc } = view.state;
      const single = firstLine.number === lastLine.number;
      const changes = [];
      for (let n = firstLine.number; n <= lastLine.number; n++) {
        const line = doc.line(n);
        if (!single && !line.text.trim()) continue;
        if (delta > 0) {
          changes.push({ from: line.from, insert: INDENT_UNIT });
        } else {
          const drop = /^( {1,2}|\t)/.exec(line.text);
          if (drop) changes.push({ from: line.from, to: line.from + drop[0].length });
        }
      }
      view.dispatch({ changes, scrollIntoView: true, userEvent: delta > 0 ? "input.indent" : "delete.dedent" });
      return true;
    };
    const lines = (state) => [state.doc.lineAt(state.selection.main.from), state.doc.lineAt(state.selection.main.to)];

    // Tab nests items and their notes, like an outline: at most one level
    // under the line above. Where nothing can nest (a plain line at the left,
    // or one as deep as it can go), Tab is the page's (the notepad's), or
    // the editor's own (tab, untab).
    const nest = (delta) => (view) => {
      const { state } = view;
      const [firstLine, lastLine] = lines(state);
      const here = leadOf(firstLine.text);
      if (delta > 0) {
        if (firstLine.number === 1 || !firstLine.text.trim()) return false;
        const above = leadOf(state.doc.line(firstLine.number - 1).text);
        const nestable = here.depth <= above.depth && here.depth < MAX_DEPTH
          && (here.item || here.depth > 0 || above.item);
        if (!nestable) return false;
      } else if (here.depth === 0) {
        return false;
      }
      return indent(view, delta, firstLine, lastLine);
    };

    // The editor's own Tab never leaves it: any line nests under the line
    // above as an outline's does (a blank one for what will be written on
    // it, a fenced block's code as deep as it needs), and where it cannot,
    // Tab does nothing. Shift+Tab steps a line back out, and from a line at
    // the left steps out of the editor.
    const tab = (view) => {
      const { state } = view;
      const [firstLine, lastLine] = lines(state);
      if (inCode(state, firstLine)) return indent(view, 1, firstLine, lastLine);
      if (firstLine.number === 1) return true;
      const depth = depthOf(/^[ \t]*/.exec(firstLine.text)[0]);
      const above = leadOf(state.doc.line(firstLine.number - 1).text);
      if (depth > above.depth || depth >= MAX_DEPTH) return true;
      return indent(view, 1, firstLine, lastLine);
    };
    const untab = (view) => {
      const { state } = view;
      const [firstLine, lastLine] = lines(state);
      for (let n = firstLine.number; n <= lastLine.number; n++) {
        if (/^[ \t]/.test(state.doc.line(n).text)) return indent(view, -1, firstLine, lastLine);
      }
      return false;
    };

    // Ctrl+L: a line becomes an item, an item's box is ticked, a ticked one
    // unticked.
    const cycle = (view) => {
      const { state } = view;
      const firstLine = state.doc.lineAt(state.selection.main.from);
      const l = leadOf(firstLine.text);
      if (l.item && l.box !== null) return tick(view, firstLine);
      const lead = `${l.indent}- [ ] `;
      view.dispatch({ changes: { from: firstLine.from, to: firstLine.from + (l.item ? l.lead.length : l.indent.length), insert: lead }, userEvent: "input" });
      return true;
    };

    return { enter, softEnter, backspace, nest, tab, untab, cycle };
  };

  // The engine's keys, then lang-markdown's (Enter going on with a quote or
  // a numbered list, Backspace taking their marks away). On a line the page
  // owns, its lead is the page's, and so are the keys that write leads: only
  // the marks' keys stay the engine's there. The marks' keys are the app's
  // (keys.py, keys.js), else the defaults.
  const bound = (action, otherwise, run) =>
    (window.Keys ? window.Keys.cm(action) : [otherwise]).map((key) => ({ key, run, preventDefault: true }));
  const writingKeys = (owns, ownsTab) => {
    const c = commands();
    const free = (run) => run && ((view) => !owns(view.state.doc.lineAt(view.state.selection.main.head)) && run(view));
    const leads = [
      { key: "Enter", run: c.enter },
      { key: "Shift-Enter", run: c.softEnter },
      { key: "Backspace", run: c.backspace },
      { key: "Tab", run: c.nest(1), shift: c.nest(-1) },
      ...(ownsTab ? [] : [{ key: "Tab", run: c.tab, shift: c.untab }]),
      ...bound("editor.checklist", "Mod-l", c.cycle),
      ...markdownKeymap,
    ].map((b) => ({ ...b, run: free(b.run), shift: free(b.shift) }));
    return Prec.high(keymap.of([
      ...bound("editor.bold", "Mod-b", wrap("**")),
      ...bound("editor.italic", "Mod-i", wrap("*")),
      ...bound("editor.strike", "Mod-Shift-x", wrap("~~")),
      ...bound("editor.code", "Mod-`", wrap("`")),
      ...leads,
    ]));
  };

  /* ---- the pointer and the clipboard ---- */

  // A link opens beside the app, as a link in a chat does.
  const openBeside = (href) => {
    const a = document.createElement("a");
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.click();
  };

  const handlers = (options) => EditorView.domEventHandlers({
    // A rendered link opens on a click; one showing its Markdown is written
    // in, and opens on Ctrl+click (Cmd+click).
    mousedown(e, view) {
      const link = e.target.closest?.(".cm-md-link[data-href]");
      if (!link || e.button !== 0) return false;
      const rendered = link.classList.contains("cm-md-rendered") || view.state.field(modeField) === "reading";
      if (!rendered && !(e.ctrlKey || e.metaKey)) return false;
      const href = hrefOf(link.dataset.href);
      if (!href) return false;
      e.preventDefault();
      options.openLink(href);
      return true;
    },
    // An address pasted over words on one line makes them its link.
    paste(e, view) {
      const text = (e.clipboardData?.getData("text/plain") || "").trim();
      const r = one(view.state);
      if (!r || r.empty || !/^https?:\/\/\S+$/i.test(text)) return false;
      const { doc } = view.state;
      if (doc.lineAt(r.from).number !== doc.lineAt(r.to).number) return false;
      e.preventDefault();
      const words = doc.sliceString(r.from, r.to);
      view.dispatch({
        changes: { from: r.from, to: r.to, insert: `[${words}](${text})` },
        selection: { anchor: r.from + words.length + text.length + 4 },
        userEvent: "input.paste",
      });
      return true;
    },
  });

  // A fenced block's code, in the system's sign colours: its tokens get
  // classes (app.css colours them only in a code block), so the Markdown
  // around it, raw HTML included, keeps its own.
  const codeTokens = tagHighlighter([
    { tag: [tags.keyword, tags.controlKeyword, tags.operatorKeyword, tags.definitionKeyword, tags.moduleKeyword, tags.modifier], class: "cm-md-tok-keyword" },
    { tag: [tags.string, tags.special(tags.string), tags.regexp, tags.character], class: "cm-md-tok-string" },
    { tag: [tags.number, tags.bool, tags.null, tags.atom], class: "cm-md-tok-number" },
    { tag: [tags.comment, tags.lineComment, tags.blockComment], class: "cm-md-tok-comment" },
    { tag: [tags.function(tags.variableName), tags.function(tags.propertyName), tags.definition(tags.variableName)], class: "cm-md-tok-function" },
    { tag: [tags.typeName, tags.className, tags.namespace], class: "cm-md-tok-type" },
    { tag: tags.tagName, class: "cm-md-tok-tag" },
    { tag: [tags.attributeName, tags.propertyName], class: "cm-md-tok-property" },
    { tag: tags.meta, class: "cm-md-tok-meta" },
    { tag: tags.inserted, class: "cm-md-tok-inserted" },
    { tag: tags.deleted, class: "cm-md-tok-deleted" },
  ]);

  /* ---- the engine ---- */

  const NONE = () => false;

  function extensions(options = {}) {
    const opts = {
      openLink: options.openLink || openBeside,
      imageSrc: options.imageSrc || ((url) => (/^(https?:|data:image\/)/i.test(url) ? url : null)),
      owns: options.owns || NONE,
      plain: options.plain || NONE,
      ownsTab: Boolean(options.ownsTab),
    };
    const mode = MODES.includes(options.mode) ? options.mode : "live";
    const tables = tableField(opts);
    return [
      modeField.init(() => mode),
      focusField,
      EditorView.focusChangeEffect.of((state, focusing) => focusEffect.of(focusing)),
      EditorView.editable.compute([modeField], (s) => s.field(modeField) !== "reading"),
      EditorView.editorAttributes.compute([modeField], (s) => ({ class: `cm-md-${s.field(modeField)}` })),
      language,
      syntaxHighlighting(codeTokens),
      tables,
      livePlugin(opts, tables),
      offTheLead(opts.owns),
      writingKeys(opts.owns, opts.ownsTab),
      handlers(opts),
      EditorView.lineWrapping,
      EditorView.contentAttributes.of({ spellcheck: "false" }),
    ];
  }

  const modeOf = (view) => view.state.field(modeField, false) || null;

  // The mode each editor was last written in, for Ctrl+E out of reading.
  const lastWriting = new WeakMap();

  function setMode(view, mode) {
    const current = modeOf(view);
    if (!MODES.includes(mode) || current === mode) return;
    if (current !== "reading") lastWriting.set(view, current);
    view.dispatch({ effects: setModeEffect.of(mode) });
    if (mode !== "reading") view.focus();
  }

  // Ctrl+E as Obsidian's: reading, and back to the mode it was written in.
  const toggleReading = (view) =>
    setMode(view, modeOf(view) === "reading" ? lastWriting.get(view) || "live" : "reading");

  const toggleSource = (view) => setMode(view, modeOf(view) === "source" ? "live" : "source");

  /* ---- a page's switch between the modes ---- */

  const storeKey = (key) => `pc-md-mode-${key}`;

  // The mode a kind of page ("doc", "task") was last left in, to open in.
  function rememberedMode(key) {
    try {
      const mode = localStorage.getItem(storeKey(key));
      return MODES.includes(mode) ? mode : "live";
    } catch {
      return "live";
    }
  }

  // A page's [data-md-modes] switch, its [data-md-mode] buttons each a
  // mode, for the editor viewOf() returns as it is pressed (the page may
  // have made it anew), and Ctrl+E (Cmd+E) in and out of reading. The mode
  // chosen is remembered for the kind of page, `key`.
  function bindSwitch(el, viewOf, key) {
    const show = () => {
      const view = viewOf();
      const mode = view ? modeOf(view) : null;
      el.querySelectorAll("[data-md-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mdMode === mode)));
    };
    const switched = (view) => {
      try { localStorage.setItem(storeKey(key), modeOf(view)); } catch { /* private mode: this page only */ }
      show();
    };
    el.addEventListener("click", (e) => {
      const button = e.target.closest("[data-md-mode]");
      const view = viewOf();
      if (!button || !view) return;
      setMode(view, button.dataset.mdMode);
      switched(view);
    });
    document.addEventListener("keydown", (e) => {
      // Its key: the app's (keys.py, keys.js), else Ctrl+E.
      const reading = window.Keys
        ? window.Keys.is(e, "editor.reading")
        : e.key.toLowerCase() === "e" && (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey;
      if (!reading || e.isComposing) return;
      const view = viewOf();
      if (!view || document.querySelector("dialog[open]")) return;
      e.preventDefault();
      toggleReading(view);
      switched(view);
    });
    show();
    return { show };
  }

  window.MarkdownLive = { extensions, setMode, modeOf, toggleReading, toggleSource, rememberedMode, bindSwitch };
})();
