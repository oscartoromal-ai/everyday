/* The Markdown engine: Markdown written in CodeMirror 6 (window.CM) and
   shown as it reads while it is written, as Obsidian's Live Preview does.

   The text is the record. Every effect here is a decoration over the
   characters, never a change to them, so what is saved, copied and undone
   is the Markdown exactly as written, byte for byte.

   What the text says comes from the Lezer Markdown parser (CommonMark with
   GitHub's tables, strikethrough, task boxes and bare links), parsed as it
   changes and only as far as the window shows. Its markup ("**", "#", "`",
   "[ ](url)", "> ") is hidden until the caret or a selection reaches the
   thing it marks: a heading's or a quote's line, or the words between a
   pair of marks. With the editor unfocused it all reads as finished.

   A list item's lead (its indentation, "- " and box) is drawn as one piece,
   a checkbox or a bullet, and the caret never stands inside it. Lists are
   read line by line, as app/checklist.py reads a task's sub-tasks, so with
   `checklist` every "- " or "* " line is a box, ticked or not, exactly as
   the server counts them. Without it, "- " is a bullet and "- [ ] " a box.

   Raw HTML is never rendered, and a link is only ever opened by Ctrl+click
   (Cmd+click), and only an http(s) one. */

(() => {
  const {
    EditorSelection, EditorState, EditorView, Decoration, ViewPlugin, WidgetType, keymap, Prec,
    Language, LanguageSupport, defineLanguageFacet, syntaxTree, GFM, markdownParser,
  } = window.CM;

  /* ---- the parser ---- */

  // Notes, not a typesetting source: an indented line nests under the one
  // above instead of turning into code, a "---" under a line is a rule (not
  // a heading made of that line), and HTML blocks are just text.
  const parser = markdownParser.configure([GFM, { remove: ["IndentedCode", "SetextHeading", "HTMLBlock"] }]);
  const markdownLanguage = new Language(defineLanguageFacet(), parser, [], "markdown");

  /* ---- lists, line by line ---- */

  const INDENT_UNIT = "  ";
  const MAX_DEPTH = 6;
  // app/checklist.py's _ITEM, up to the item's words. "+" bullets are
  // Markdown's, not the checklist's.
  const CHECKLIST_LEAD = /^([ \t]*)([-*])[ \t]+(?:\[([ xX])\][ \t]+)?/;
  const MARKDOWN_LEAD = /^([ \t]*)([-*+])[ \t]+(?:\[([ xX])\][ \t]+)?/;

  const width = (indent) => indent.replace(/\t/g, "    ").length;
  const depthOf = (indent) => Math.min(MAX_DEPTH, Math.floor(width(indent) / 2));

  // A line's list item, or its indentation: {lead, indent, marker, box,
  // depth}, box being null (none), " " or "x". `lead` is what is drawn as
  // one piece: the item's indentation, marker and box, or a plain line's
  // indentation (when it has words after it).
  const leadOf = (text, checklist) => {
    const m = (checklist ? CHECKLIST_LEAD : MARKDOWN_LEAD).exec(text);
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

  /* ---- what is drawn ---- */

  class Box extends WidgetType {
    constructor(checked, checklist) {
      super();
      this.checked = checked;
      this.checklist = checklist;
    }
    eq(other) {
      return other.checked === this.checked && other.checklist === this.checklist;
    }
    toDOM(view) {
      const box = document.createElement("button");
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
        if (!view.state.readOnly) tick(view, view.state.doc.lineAt(view.posAtDOM(box)), this.checklist);
      });
      return box;
    }
    ignoreEvent() {
      return true;
    }
  }
  const BOXES = new Map([true, false].map((checklist) => [checklist, {
    open: Decoration.replace({ widget: new Box(false, checklist) }),
    done: Decoration.replace({ widget: new Box(true, checklist) }),
  }]));

  class Bullet extends WidgetType {
    eq() {
      return true;
    }
    toDOM() {
      const bullet = document.createElement("span");
      bullet.className = "cm-md-bullet";
      bullet.setAttribute("aria-hidden", "true");
      return bullet;
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
  const lineDeco = (className, depth = 0) => Decoration.line(
    depth ? { class: className, attributes: { style: `--md-depth: ${depth}` } } : { class: className },
  );
  const SPELLED = Decoration.line({ attributes: { spellcheck: "true" } });

  // Only a web address is a link, as in the task's row (app/markdown.py):
  // "www.x.com", "mailto:" or "javascript:" stay words.
  const hrefOf = (url) => (/^https?:\/\/\S+$/i.test(url) ? url : null);
  const linkDeco = (href) => Decoration.mark({
    class: "cm-md-link",
    attributes: { "data-href": href, title: `${href}\nCtrl+click to open` },
  });

  // What the editor shows at this moment: the window's decorations, and the
  // leads the caret steps over as one piece.
  const draw = (view, checklist) => {
    const { state } = view;
    const { doc } = state;
    const focused = view.hasFocus;
    const ranges = state.selection.ranges;
    // Markup shows where the caret or a selection reaches it, and only
    // while the editor has focus.
    const touches = (from, to) => focused && ranges.some((r) => r.from <= to && r.to >= from);
    const lineTouched = (pos) => {
      const line = doc.lineAt(pos);
      return touches(line.from, line.to);
    };

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
    const tree = syntaxTree(state);
    const codeLines = new Set();

    for (const { from, to } of view.visibleRanges) {
      tree.iterate({
        from,
        to,
        enter: (node) => {
          const name = node.name;
          const heading = /^ATXHeading(\d)$/.exec(name);
          if (heading) {
            onLine(node.from, "h", lineDeco(`cm-md-h cm-md-h${heading[1]}`));
            return;
          }
          if (name === "HeaderMark") {
            if (lineTouched(node.from)) return;
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
            hide(line.from + a, line.from + b);
            return;
          }
          if (STYLE[name]) {
            decos.push(STYLE[name].range(node.from, node.to));
            const shown = touches(node.from, node.to);
            for (let mark = node.node.firstChild; mark; mark = mark.nextSibling) {
              if (!MARKS.has(mark.name)) continue;
              if (shown) decos.push(MARK.range(mark.from, mark.to));
              else hide(mark.from, mark.to);
            }
            return name === "InlineCode" ? false : undefined;
          }
          if (name === "Link") {
            // "[words](url)": the words as the link. "[words]" alone, or
            // "[words][ref]", is left as written: notes say "[TBD]".
            const marks = node.node.getChildren("LinkMark");
            const url = node.node.getChild("URL");
            const href = url && hrefOf(doc.sliceString(url.from, url.to));
            if (!href || marks.length < 3) return;
            const close = marks[1];
            if (close.from > marks[0].to) decos.push(linkDeco(href).range(marks[0].to, close.from));
            if (touches(node.from, node.to)) {
              decos.push(MARK.range(node.from, marks[0].to));
              decos.push(MARK.range(close.from, node.to));
            } else {
              hide(node.from, marks[0].to);
              hide(close.from, node.to);
            }
            return;
          }
          if (name === "Autolink") {
            // "<https://...>": the address as a link, its brackets hidden.
            const url = node.node.getChild("URL");
            const href = url && hrefOf(doc.sliceString(url.from, url.to));
            if (!href) return false;
            decos.push(linkDeco(href).range(url.from, url.to));
            if (!touches(node.from, node.to)) {
              hide(node.from, url.from);
              hide(url.to, node.to);
            } else {
              decos.push(MARK.range(node.from, url.from));
              decos.push(MARK.range(url.to, node.to));
            }
            return false;
          }
          if (name === "URL") {
            // A bare address (a link's own is drawn with its link).
            const href = hrefOf(doc.sliceString(node.from, node.to));
            if (href && node.node.parent?.name !== "Link") decos.push(linkDeco(href).range(node.from, node.to));
            return;
          }
          if (name === "Image") {
            decos.push(MARK.range(node.from, node.to));
            return false;
          }
          if (name === "Escape") {
            // "\*": the star, without its backslash.
            if (!touches(node.from, node.to)) hide(node.from, node.from + 1);
            return;
          }
          if (name === "QuoteMark") {
            onLine(node.from, "quote", lineDeco("cm-md-quote"));
            if (lineTouched(node.from)) {
              decos.push(MARK.range(node.from, node.to));
            } else {
              const line = doc.lineAt(node.from);
              hide(node.from, node.to < line.to && doc.sliceString(node.to, node.to + 1) === " " ? node.to + 1 : node.to);
            }
            return;
          }
          if (name === "HorizontalRule") {
            // "---" drawn as the rule it makes, written as itself. "- - -"
            // in a checklist is a sub-task, as the server counts it.
            if (checklist && leadOf(doc.lineAt(node.from).text, true).item) return false;
            if (lineTouched(node.from)) {
              decos.push(MARK.range(node.from, node.to));
            } else {
              onLine(node.from, "hr", lineDeco("cm-md-hr"));
              hide(node.from, node.to);
            }
            return false;
          }
          if (name === "FencedCode") {
            // Its fences ("```js") shrink to the block's edges until the
            // caret is in the block.
            const first = doc.lineAt(node.from).number;
            const last = doc.lineAt(node.to).number;
            const shown = touches(node.from, node.to);
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
                }
              }
              onLine(line.from, "code", lineDeco(kind));
            }
            return false;
          }
        },
      });

      // Lists and indentation, line by line.
      for (let pos = from; pos <= to;) {
        const line = doc.lineAt(pos);
        pos = line.to + 1;
        if (codeLines.has(line.number) && !checklist) continue;
        const l = leadOf(line.text, checklist);
        if (!l.lead) continue;
        const end = line.from + l.lead.length;
        if (l.item) {
          const done = l.box === "x";
          const kind = done ? "cm-md-li cm-md-done" : "cm-md-li";
          onLine(line.from, "li", lineDeco(kind, l.depth));
          const boxes = BOXES.get(checklist);
          const piece = checklist || l.box !== null ? (done ? boxes.done : boxes.open) : BULLET;
          decos.push(piece.range(line.from, end));
          atomic.push(piece.range(line.from, end));
        } else if (!codeLines.has(line.number)) {
          onLine(line.from, "indent", lineDeco("cm-md-indented", l.depth));
          decos.push(HIDDEN.range(line.from, end));
          atomic.push(HIDDEN.range(line.from, end));
        }
      }
    }

    // Spelling is marked only in the line being written.
    const main = state.selection.main;
    if (focused && doc.lineAt(main.from).number === doc.lineAt(main.to).number) {
      decos.push(SPELLED.range(doc.lineAt(main.head).from));
    }
    return { decos: Decoration.set(decos, true), atomic: Decoration.set(atomic, true) };
  };

  const livePreviewPlugin = (checklist) => ViewPlugin.fromClass(class {
    constructor(view) {
      this.drawn = draw(view, checklist);
    }
    update(u) {
      if (u.docChanged || u.viewportChanged || u.selectionSet || u.focusChanged
          || syntaxTree(u.state) !== syntaxTree(u.startState)) {
        this.drawn = draw(u.view, checklist);
      }
    }
  }, {
    decorations: (p) => p.drawn.decos,
    provide: (plugin) => EditorView.atomicRanges.of((view) => view.plugin(plugin)?.drawn.atomic ?? Decoration.none),
  });

  /* ---- the caret: never inside a lead ---- */

  // A caret landing at a list item's (or indented line's) very start goes
  // to its first word, and a selection drawn back to a line's start
  // (Shift+Home) stops there: typing over it keeps the item.
  const offTheLead = (checklist) => EditorState.transactionFilter.of((tr) => {
    if (!tr.selection) return tr;
    const { doc, selection } = tr.state;
    let moved = false;
    const ranges = selection.ranges.map((r) => {
      const line = doc.lineAt(r.head);
      const end = line.from + leadOf(line.text, checklist).lead.length;
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

  // Ticks or unticks a list item's box. As a checklist, the line is written
  // as the server writes it (app/checklist.py _set_checked): "- [x] " done,
  // "- " open. Otherwise only the box's mark changes.
  function tick(view, line, checklist) {
    const l = leadOf(line.text, checklist);
    if (!l.item || (!checklist && l.box === null)) return false;
    const done = l.box === "x";
    if (checklist) {
      const lead = `${l.indent}${l.marker} ${done ? "" : "[x] "}`;
      view.dispatch({ changes: { from: line.from, to: line.from + l.lead.length, insert: lead }, userEvent: "input.tick" });
    } else {
      const at = line.from + l.lead.indexOf("[") + 1;
      view.dispatch({ changes: { from: at, to: at + 1, insert: done ? " " : "x" }, userEvent: "input.tick" });
    }
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
  const ownerOf = (state, line, depth, checklist) => {
    for (let n = line.number - 1; n >= 1; n--) {
      const above = leadOf(state.doc.line(n).text, checklist);
      if (!above.lead && !state.doc.line(n).text.trim()) continue;
      if (above.depth < depth) return above.item && above.depth === depth - 1 ? above : null;
    }
    return null;
  };

  const commands = (checklist) => {
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
      const l = leadOf(line.text, checklist);
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
        const owner = ownerOf(state, line, l.depth, checklist);
        return insertAt(view, r, `\n${owner ? newItem({ ...owner, box: owner.box === null ? null : " " }) : l.indent}`);
      }
      return false;
    };

    // Shift+Enter: a plain line, which under an item is that item's note.
    const softEnter = (view) => {
      const r = one(view.state);
      if (!r) return false;
      const l = leadOf(view.state.doc.lineAt(r.from).text, checklist);
      const indent = l.item ? l.indent + INDENT_UNIT : l.lead ? l.indent : "";
      return insertAt(view, r, `\n${indent}`);
    };

    // Backspace at an item's first word takes its box (or bullet) away, the
    // line staying where it is; on an indented line, a level of indentation.
    const backspace = (view) => {
      const r = one(view.state);
      if (!r || !r.empty) return false;
      const line = view.state.doc.lineAt(r.head);
      const l = leadOf(line.text, checklist);
      if (!l.lead || r.head !== line.from + l.lead.length) return false;
      const lead = l.item ? l.indent : l.indent.replace(/^( {1,2}|\t)/, "");
      view.dispatch({ changes: { from: line.from, to: line.from + l.lead.length, insert: lead }, userEvent: "delete.dedent" });
      return true;
    };

    // Tab nests items and their notes, like an outline: at most one level
    // under the line above. Where nothing can nest (a plain line at the left,
    // or one as deep as it can go) Tab keeps its usual job of moving focus
    // on, so the keyboard never gets stuck in the editor.
    const nest = (delta) => (view) => {
      const { state } = view;
      const { doc } = state;
      const firstLine = doc.lineAt(state.selection.main.from);
      const lastLine = doc.lineAt(state.selection.main.to);
      const here = leadOf(firstLine.text, checklist);
      if (delta > 0) {
        if (firstLine.number === 1 || !firstLine.text.trim()) return false;
        const above = leadOf(doc.line(firstLine.number - 1).text, checklist);
        const nestable = here.depth <= above.depth && here.depth < MAX_DEPTH
          && (here.item || here.depth > 0 || above.item);
        if (!nestable) return false;
      } else if (here.depth === 0) {
        return false;
      }
      const changes = [];
      for (let n = firstLine.number; n <= lastLine.number; n++) {
        const line = doc.line(n);
        if (!line.text.trim()) continue;
        if (delta > 0) {
          changes.push({ from: line.from, insert: INDENT_UNIT });
        } else {
          const drop = /^( {1,2}|\t)/.exec(line.text);
          if (drop) changes.push({ from: line.from, to: line.from + drop[0].length });
        }
      }
      view.dispatch({ changes, userEvent: delta > 0 ? "input.indent" : "delete.dedent" });
      return true;
    };

    // Ctrl+L: a line becomes an item, an item's box is ticked, a ticked one
    // unticked.
    const cycle = (view) => {
      const { state } = view;
      const firstLine = state.doc.lineAt(state.selection.main.from);
      const l = leadOf(firstLine.text, checklist);
      if (l.item && (checklist || l.box !== null)) return tick(view, firstLine, checklist);
      const lead = `${l.indent}- ${checklist ? "" : "[ ] "}`;
      view.dispatch({ changes: { from: firstLine.from, to: firstLine.from + (l.item ? l.lead.length : l.indent.length), insert: lead }, userEvent: "input" });
      return true;
    };

    // Ctrl+B, Ctrl+I: the selection between the marks, or out of them.
    const wrap = (mark) => (view) => {
      const r = one(view.state);
      if (!r) return false;
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

    return { enter, softEnter, backspace, nest, cycle, wrap };
  };

  const listKeymap = (checklist) => {
    const c = commands(checklist);
    return Prec.high(keymap.of([
      { key: "Enter", run: c.enter },
      { key: "Shift-Enter", run: c.softEnter },
      { key: "Backspace", run: c.backspace },
      { key: "Tab", run: c.nest(1), shift: c.nest(-1) },
      { key: "Mod-l", run: c.cycle, preventDefault: true },
      { key: "Mod-b", run: c.wrap("**"), preventDefault: true },
      { key: "Mod-i", run: c.wrap("*"), preventDefault: true },
    ]));
  };

  /* ---- the pointer and the clipboard ---- */

  const handlers = EditorView.domEventHandlers({
    // Ctrl+click (Cmd+click) opens a link beside the app, as a link in a
    // chat does; a plain click writes in it.
    mousedown(e) {
      if (!(e.ctrlKey || e.metaKey) || e.button !== 0) return false;
      const link = e.target.closest?.(".cm-md-link[data-href]");
      if (!link) return false;
      e.preventDefault();
      const a = document.createElement("a");
      a.href = link.dataset.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.click();
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

  /* ---- the engine ---- */

  window.MarkdownEditor = {
    // Everything that makes an editor write Markdown and show it as it
    // reads: the parser, the live preview, the list keys and the links.
    // `checklist`: every list item is a box, as a task's sub-tasks are.
    livePreview({ checklist = false } = {}) {
      return [
        new LanguageSupport(markdownLanguage),
        livePreviewPlugin(checklist),
        offTheLead(checklist),
        listKeymap(checklist),
        handlers,
        EditorView.lineWrapping,
        EditorView.contentAttributes.of({ spellcheck: "false" }),
      ];
    },
  };
})();
