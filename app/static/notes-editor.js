/* The description editor: a contenteditable where each line is a block, and
   a "- " line turns into a checkbox when Enter is pressed. The hidden
   textarea beside it stays the form field, holding the same plain text the
   server stores (app/checklist.py), so nothing outside this file knows the
   editor exists.

   Structure is always ours: every edit that could create, split, merge or
   restyle a line is cancelled in beforeinput and redone on the line model,
   then re-rendered. The browser only ever edits text inside one line. That
   also means the browser's undo stack cannot be trusted, so the editor
   keeps its own.

   In prose mode (data-notes-editor="prose", the notebook's text and
   reflections) every line is plain text: no sub-tasks, no nesting, and Tab
   moves on. notebook.js drives it through window.NotesEditor. */

(() => {
  const ITEM = /^([ \t]*)([-*])[ \t]+(?:\[([ xX])\][ \t]+)?(\S.*)$/;
  // What Oscar types at the start of a plain line to make it a sub-task.
  const TYPED = /^[-*][ \t]+(?:\[([ xX])\][ \t]+)?(?=\S)/;
  const INDENT = 22; // px per level: a 14px box plus its 8px gap
  const MAX_DEPTH = 6;
  const TYPING_BURST_MS = 800;

  /* ---- text <-> line model ---- */

  const width = (indent) => indent.replace(/\t/g, "    ").length;

  const parse = (notes, prose = false) =>
    notes.replace(/\r\n?/g, "\n").split("\n").map((raw) => {
      if (prose) return { kind: "text", depth: 0, checked: false, text: raw };
      const m = ITEM.exec(raw);
      if (m) {
        return {
          kind: "item",
          depth: Math.min(MAX_DEPTH, Math.floor(width(m[1]) / 2)),
          checked: (m[3] || " ").toLowerCase() === "x",
          text: m[4],
        };
      }
      const indent = /^[ \t]*/.exec(raw)[0];
      const text = raw.slice(indent.length);
      const depth = text ? Math.min(MAX_DEPTH, Math.floor(width(indent) / 2)) : 0;
      return { kind: "text", depth, checked: false, text };
    });

  const serialize = (model) =>
    model
      .map((b) => {
        if (!b.text) return ""; // an empty sub-task is just a blank line
        const pad = "  ".repeat(b.depth);
        return b.kind === "item" ? `${pad}- ${b.checked ? "[x] " : ""}${b.text}` : pad + b.text;
      })
      .join("\n");

  /* ---- the DOM: one div.ln per line ---- */

  const lines = (root) => [...root.children];
  const isProse = (root) => root.dataset.notesEditor === "prose";
  const parseFor = (root, text) => parse(text, isProse(root));
  const field = (root) => root.closest("[data-notes-field]").querySelector("textarea");
  const textOf = (el) => el.textContent.replace(/ /g, " ").replace(/\n/g, " ");

  const lineEl = (b) => {
    const el = document.createElement("div");
    el.className = "ln";
    el.dataset.kind = b.kind;
    el.dataset.depth = String(b.depth);
    el.style.setProperty("--depth", b.depth);
    if (b.kind === "item" && b.checked) el.dataset.checked = "";
    el.textContent = b.text;
    if (!b.text) el.append(document.createElement("br")); // keeps an empty line caret-able
    return el;
  };

  const readLine = (el) => ({
    kind: el.dataset.kind === "item" ? "item" : "text",
    depth: Number(el.dataset.depth) || 0,
    checked: "checked" in el.dataset,
    text: textOf(el),
  });

  const read = (root) => lines(root).map(readLine);

  const sync = (root) => {
    const model = read(root);
    field(root).value = serialize(model);
    root.classList.toggle("is-empty", model.length === 1 && model[0].kind === "text" && !model[0].text);
    // Structural edits never raise "input" (they are cancelled and redone):
    // this is the one signal that the text changed, however it did.
    root.dispatchEvent(new CustomEvent("notes:change", { bubbles: true }));
  };

  const render = (root, model) => {
    root.replaceChildren(...(model.length ? model : parseFor(root, "")).map(lineEl));
    sync(root);
  };

  /* ---- caret as (line index, text offset) ---- */

  const pointOf = (root, node, offset) => {
    const all = lines(root);
    if (node === root) {
      if (offset >= all.length) return { i: all.length - 1, o: textOf(all[all.length - 1]).length };
      return { i: offset, o: 0 };
    }
    let line = node;
    while (line.parentNode !== root) line = line.parentNode;
    const range = document.createRange();
    range.selectNodeContents(line);
    range.setEnd(node, offset);
    return { i: all.indexOf(line), o: range.toString().length };
  };

  const selectionIn = (root) => {
    const sel = getSelection();
    if (!sel.rangeCount) return null;
    const r = sel.getRangeAt(0);
    if (!root.contains(r.startContainer) || !root.contains(r.endContainer)) return null;
    return { start: pointOf(root, r.startContainer, r.startOffset), end: pointOf(root, r.endContainer, r.endOffset) };
  };

  const place = (root, i, o) => {
    const line = lines(root)[i];
    const range = document.createRange();
    const walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
    let left = o;
    let node;
    while ((node = walker.nextNode())) {
      if (left <= node.length) break;
      left -= node.length;
    }
    if (node) range.setStart(node, left);
    else range.setStart(line, 0);
    range.collapse(true);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  };

  /* ---- history: snapshots of the model and caret ---- */

  const histories = new WeakMap();
  const historyOf = (root) => {
    if (!histories.has(root)) histories.set(root, { undo: [], redo: [], last: 0 });
    return histories.get(root);
  };
  const snapshot = (root) => ({ model: read(root), caret: selectionIn(root)?.start ?? null });

  // Structural edits are one step each; typing is grouped into bursts.
  const remember = (root, structural) => {
    const h = historyOf(root);
    const now = Date.now();
    if (!structural && now - h.last < TYPING_BURST_MS) return;
    h.undo.push(snapshot(root));
    if (h.undo.length > 200) h.undo.shift();
    h.redo.length = 0;
    h.last = structural ? 0 : now;
  };

  const restore = (root, snap) => {
    render(root, snap.model);
    if (snap.caret) place(root, Math.min(snap.caret.i, lines(root).length - 1), snap.caret.o);
  };

  const step = (root, from, to) => {
    const h = historyOf(root);
    if (!h[from].length) return;
    h[to].push(snapshot(root));
    restore(root, h[from].pop());
    h.last = 0;
  };

  /* ---- structural edits on the model ---- */

  const commit = (root, model, i, o) => {
    render(root, model);
    place(root, i, o);
  };

  const cut = (model, sel) => {
    const { start, end } = sel;
    if (start.i !== end.i || start.o !== end.o) {
      const a = model[start.i];
      const z = model[end.i];
      model[start.i] = { ...a, text: a.text.slice(0, start.o) + z.text.slice(end.o) };
      model.splice(start.i + 1, end.i - start.i);
    }
    return { model, i: start.i, o: start.o };
  };

  // The sub-task an indented plain line hangs under, if any.
  const ownerOf = (model, i) => {
    for (let j = i - 1; j >= 0; j--) {
      if (model[j].depth < model[i].depth) {
        return model[j].kind === "item" && model[j].depth === model[i].depth - 1 ? model[j] : null;
      }
    }
    return null;
  };

  const enter = (root, sel, soft) => {
    const { model, i, o } = cut(read(root), sel);
    const b = model[i];

    if (isProse(root)) {
      model.splice(i, 1, { ...b, text: b.text.slice(0, o) }, { ...b, text: b.text.slice(o) });
      return commit(root, model, i + 1, 0);
    }

    if (soft) {
      // Shift+Enter: a plain line; under a sub-task it is that sub-task's note.
      const depth = Math.min(MAX_DEPTH, b.kind === "item" ? b.depth + 1 : b.depth);
      model.splice(i, 1, { ...b, text: b.text.slice(0, o) }, { kind: "text", depth, checked: false, text: b.text.slice(o) });
      return commit(root, model, i + 1, 0);
    }

    if (b.kind === "item" && !b.text) {
      // Enter on an empty sub-task steps out of the list, a level at a time.
      model[i] = b.depth > 0 ? { ...b, depth: b.depth - 1 } : { ...b, kind: "text", checked: false };
      return commit(root, model, i, 0);
    }

    const typed = TYPED.exec(b.text);
    if (typed && o >= typed[0].length) {
      // "- fetch the feed" + Enter: the line becomes a checkbox.
      const text = b.text.slice(typed[0].length);
      const at = o - typed[0].length;
      const checked = b.kind === "item" ? b.checked : (typed[1] || " ").toLowerCase() === "x";
      model.splice(
        i,
        1,
        { kind: "item", depth: b.depth, checked, text: text.slice(0, at) },
        { kind: "item", depth: b.depth, checked: false, text: text.slice(at) },
      );
      return commit(root, model, i + 1, 0);
    }

    // A sub-task continues the list, and so does its note: Enter on a note
    // starts the next sub-task (Shift+Enter adds another note line). A plain
    // line continues plain.
    const owner = b.kind === "text" && b.depth > 0 ? ownerOf(model, i) : null;
    const next = owner
      ? { kind: "item", depth: owner.depth, checked: false, text: b.text.slice(o) }
      : { kind: b.kind, depth: b.depth, checked: false, text: b.text.slice(o) };
    model.splice(i, 1, { ...b, text: b.text.slice(0, o) }, next);
    commit(root, model, i + 1, 0);
  };

  const backspaceAtStart = (root, i) => {
    const model = read(root);
    const b = model[i];
    if (b.kind === "item") {
      model[i] = { ...b, kind: "text", checked: false };
      return commit(root, model, i, 0);
    }
    if (b.depth > 0) {
      model[i] = { ...b, depth: b.depth - 1 };
      return commit(root, model, i, 0);
    }
    if (i === 0) return;
    const prev = model[i - 1];
    model.splice(i - 1, 2, { ...prev, text: prev.text + b.text });
    commit(root, model, i - 1, prev.text.length);
  };

  const deleteAtEnd = (root, i) => {
    const model = read(root);
    if (i >= model.length - 1) return;
    const b = model[i];
    model.splice(i, 2, { ...b, text: b.text + model[i + 1].text });
    commit(root, model, i, b.text.length);
  };

  const indent = (root, sel, delta) => {
    const model = read(root);
    for (let i = sel.start.i; i <= sel.end.i; i++) {
      model[i] = { ...model[i], depth: Math.max(0, Math.min(MAX_DEPTH, model[i].depth + delta)) };
    }
    render(root, model);
    place(root, sel.start.i, sel.start.o);
  };

  const paste = (root, sel, text) => {
    const { model, i, o } = cut(read(root), sel);
    const b = model[i];
    const before = b.text.slice(0, o);
    const after = b.text.slice(o);
    const pasted = text.replace(/\r\n?/g, "\n").split("\n");
    if (pasted.length === 1) {
      model[i] = { ...b, text: before + pasted[0] + after };
      return commit(root, model, i, o + pasted[0].length);
    }
    // The first pasted line joins the current one; the rest arrive as lines
    // of their own, "- " ones as sub-tasks.
    const first = parseFor(root, pasted[0])[0];
    model[i] = !before && b.kind === "text" ? { ...first, depth: first.depth + b.depth } : { ...b, text: before + pasted[0] };
    const rest = parseFor(root, pasted.slice(1).join("\n"));
    const last = rest[rest.length - 1];
    const caret = last.text.length;
    last.text += after;
    model.splice(i + 1, 0, ...rest);
    commit(root, model, i + rest.length, caret);
  };

  /* ---- wiring ---- */

  const editorOf = (target) => target?.closest?.("[data-notes-editor]");

  document.addEventListener("beforeinput", (e) => {
    const root = editorOf(e.target);
    if (!root) return;
    const type = e.inputType;

    if (type === "historyUndo" || type === "historyRedo") {
      e.preventDefault();
      step(root, type === "historyUndo" ? "undo" : "redo", type === "historyUndo" ? "redo" : "undo");
      return;
    }
    // Plain text only: no bold, no dropped HTML; pastes go through "paste".
    if (type.startsWith("format") || type === "insertFromDrop" || type === "deleteByDrag") {
      e.preventDefault();
      return;
    }
    if (type === "insertFromPaste" || e.isComposing) return;

    const sel = selectionIn(root);
    if (!sel) return;
    const collapsed = sel.start.i === sel.end.i && sel.start.o === sel.end.o;
    const acrossLines = sel.start.i !== sel.end.i;

    if (type === "insertParagraph" || type === "insertLineBreak") {
      e.preventDefault();
      remember(root, true);
      enter(root, sel, type === "insertLineBreak");
      return;
    }
    if (collapsed && type.startsWith("delete") && type.endsWith("Backward") && sel.start.o === 0) {
      e.preventDefault();
      remember(root, true);
      backspaceAtStart(root, sel.start.i);
      return;
    }
    if (
      collapsed && type.startsWith("delete") && type.endsWith("Forward")
      && sel.start.o === textOf(lines(root)[sel.start.i]).length
    ) {
      e.preventDefault();
      remember(root, true);
      deleteAtEnd(root, sel.start.i);
      return;
    }
    if (acrossLines && (type.startsWith("insert") || type.startsWith("delete"))) {
      e.preventDefault();
      remember(root, true);
      const { model, i, o } = cut(read(root), sel);
      const typed = type === "insertText" || type === "insertReplacementText" ? e.data || "" : "";
      model[i] = { ...model[i], text: model[i].text.slice(0, o) + typed + model[i].text.slice(o) };
      commit(root, model, i, o + typed.length);
      return;
    }
    remember(root, false); // the browser edits text within one line
  });

  // The safety net: whatever the browser did inside a line, the editor ends
  // up as plain-text lines again, and the form field follows.
  document.addEventListener("input", (e) => {
    const root = editorOf(e.target);
    if (!root) return;
    const clean = [...root.childNodes].every(
      (n) => n.nodeType === 1 && n.classList.contains("ln")
        && [...n.childNodes].every((c) => c.nodeType === 3 || c.nodeName === "BR"),
    );
    if (!clean) {
      const sel = selectionIn(root);
      const model = [...root.childNodes].flatMap((n) =>
        n.nodeType === 1 && n.classList.contains("ln")
          ? [readLine(n)]
          : parseFor(root, n.textContent || ""),
      );
      render(root, model);
      if (sel) place(root, Math.min(sel.start.i, lines(root).length - 1), sel.start.o);
      return;
    }
    lines(root).forEach((line) => {
      if (!line.firstChild) line.append(document.createElement("br"));
    });
    sync(root);
  });

  document.addEventListener("paste", (e) => {
    const root = editorOf(e.target);
    if (!root) return;
    e.preventDefault();
    const sel = selectionIn(root);
    if (!sel) return;
    remember(root, true);
    paste(root, sel, e.clipboardData?.getData("text/plain") || "");
  });

  document.addEventListener("keydown", (e) => {
    const root = editorOf(e.target);
    if (!root || e.isComposing) return;
    const mod = e.ctrlKey || e.metaKey;
    const key = e.key.toLowerCase();
    if (mod && !e.altKey && (key === "z" || key === "y")) {
      e.preventDefault();
      const redo = key === "y" || e.shiftKey;
      step(root, redo ? "redo" : "undo", redo ? "undo" : "redo");
      return;
    }
    if (e.key === "Enter" && e.shiftKey && !mod && !e.altKey) {
      // Shift+Enter is read here, not from beforeinput: WebKit reports it as
      // "insertParagraph" like a plain Enter, where Chromium says "insertLineBreak".
      const sel = selectionIn(root);
      if (!sel) return;
      e.preventDefault();
      remember(root, true);
      enter(root, sel, true);
      return;
    }
    if (e.key === "Tab" && !mod && !e.altKey && !isProse(root)) {
      const sel = selectionIn(root);
      if (!sel) return;
      const model = read(root);
      const here = model[sel.start.i];
      // Tab nests sub-tasks and notes, like an outline: at most one level
      // under the line above. Where it cannot nest (a plain top-level line,
      // or a line already as deep as it can go) it keeps its usual job of
      // moving focus on, so the keyboard never gets stuck in the description.
      const above = model[sel.start.i - 1];
      const nestable = e.shiftKey
        ? here.depth > 0
        : !!above && here.depth <= above.depth && (here.kind === "item" || here.depth > 0 || above.kind === "item");
      if (!nestable) return;
      e.preventDefault();
      remember(root, true);
      indent(root, sel, e.shiftKey ? -1 : 1);
    }
  });

  // Ticking a box in the editor: the box is the line's ::before, so the
  // click lands on the line itself, within the box's few pixels.
  document.addEventListener("pointerdown", (e) => {
    const line = e.target.closest?.("[data-notes-editor] > .ln[data-kind='item']");
    if (!line) return;
    const x = e.clientX - line.getBoundingClientRect().left - (Number(line.dataset.depth) || 0) * INDENT;
    if (x < -2 || x > 18) return;
    e.preventDefault();
    const root = line.parentNode;
    remember(root, true);
    if ("checked" in line.dataset) delete line.dataset.checked;
    else line.dataset.checked = "";
    sync(root);
  });

  // A contenteditable is not labelable; its label focuses it all the same.
  document.addEventListener("click", (e) => {
    const label = e.target.closest?.("[data-notes-field] > label");
    if (label) window.NotesEditor.focusEnd(label.parentNode.querySelector("[data-notes-editor]"));
  });

  const init = (root) => {
    if (root.dataset.ready) return;
    root.dataset.ready = "";
    render(root, parseFor(root, field(root).value));
  };
  document.addEventListener("htmx:load", (e) => {
    const elt = e.detail.elt;
    if (elt.matches?.("[data-notes-editor]")) init(elt);
    elt.querySelectorAll?.("[data-notes-editor]").forEach(init);
  });

  // A form reset (after Add, or Cancel) empties the field; the editor follows.
  document.addEventListener("reset", (e) => {
    e.target.querySelectorAll?.("[data-notes-editor]").forEach((root) => {
      setTimeout(() => {
        render(root, parseFor(root, field(root).value));
        histories.delete(root);
      });
    });
  }, true);

  window.NotesEditor = {
    // Re-read the field after something else set it (a carried-over draft).
    reload(root) {
      render(root, parseFor(root, field(root).value));
      histories.delete(root);
    },
    focusEnd(root) {
      root.focus();
      const last = lines(root).length - 1;
      place(root, last, textOf(lines(root)[last]).length);
    },

    /* ---- for notebook.js, on prose editors ---- */

    init,
    // The caret as {i: line, o: offset}, or null when it is not in `root`.
    caret(root) {
      return selectionIn(root)?.start ?? null;
    },
    // The editor's lines, as text.
    texts(root) {
      return read(root).map((b) => b.text);
    },
    // Replace the lines (a split or a join made by the page), caret at (i, o).
    set(root, texts, i = null, o = 0) {
      render(root, texts.map((text) => ({ kind: "text", depth: 0, checked: false, text })));
      histories.delete(root);
      if (i !== null) this.place(root, i, o);
    },
    place(root, i, o) {
      root.focus();
      const all = lines(root);
      const at = Math.max(0, Math.min(i, all.length - 1));
      place(root, at, Math.min(o, textOf(all[at]).length));
    },
  };
})();
