/* A document of a project's context on its own page (project_doc.html):
   its Markdown written on a ruled, numbered sheet, as Today's notes are,
   in CodeMirror 6 (window.CM), its headings in 600 ink; and its name, any
   but AGENTS.md's, written in the heading.

   Both are saved as they are written: a moment after the writing pauses,
   at once on Ctrl+S or Enter in the name, and as the page is left or its
   tab hidden. Saves go one at a time, a save asked for while one is in
   flight following it with what is newest. The header says "Saved" once
   one lands, nothing while there is writing still to save, and "Not saved"
   (with a toast) if one fails. The empty rows under the text, numbered on
   from its last, are the sheet's to its foot; a click there writes at the
   end. */

(() => {
  const {
    EditorState, EditorView, Decoration, ViewPlugin, RangeSetBuilder, drawSelection, keymap,
    lineNumbers, placeholder, defaultKeymap, history, historyKeymap,
  } = window.CM;

  const page = document.querySelector(".doc-page[data-doc]");
  const source = page?.querySelector("[data-doc-body]");
  if (!source) return;

  const PAUSE_MS = 900;
  const nameInput = page.querySelector("[data-doc-name]");
  const filler = page.querySelector("[data-doc-filler]");
  const stateEl = page.querySelector("[data-page-state]");
  const sayState = (text) => { stateEl.textContent = text; };

  let view = null;
  let timer = null;
  let sending = false;
  let again = false;
  let deleted = false;
  let savedName = nameInput ? nameInput.value : null;
  let savedBody = source.value;

  const body = () => view.state.doc.toString();
  const name = () => (nameInput ? nameInput.value.trim().replace(/\s+/g, " ") : null);
  // What is still to save: the body, and a name that is written (an empty
  // one is not saved, and goes back to the last as the heading is left).
  const pending = () => {
    const out = {};
    if (body() !== savedBody) out.body = body();
    if (nameInput && name() && name() !== savedName) out.name = name();
    return out;
  };

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(save, PAUSE_MS);
    if (Object.keys(pending()).length) sayState("");
  }

  function save({ leaving = false } = {}) {
    clearTimeout(timer);
    if (deleted) return;
    const changes = pending();
    if (!Object.keys(changes).length) return;
    if (sending && !leaving) {
      again = true;
      return;
    }
    sending = true;
    const request = fetch(`/ui/docs/${page.dataset.doc}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRF": window.csrfToken() },
      body: new URLSearchParams(changes),
      keepalive: leaving,
    });
    request.then(async (res) => {
      if (!res.ok) {
        const answer = await res.json().catch(() => ({}));
        throw new Error(typeof answer.detail === "string" ? answer.detail : "");
      }
      if ("body" in changes) savedBody = changes.body;
      if ("name" in changes) {
        savedName = changes.name;
        document.title = document.title.replace(/^[^·]*·/, `${savedName} ·`);
      }
      if (!Object.keys(pending()).length) sayState("Saved");
    }).catch((err) => {
      sayState("Not saved");
      window.toast(err.message || "Could not save the document. Try again?");
    }).finally(() => {
      sending = false;
      if (again) {
        again = false;
        save();
      }
    });
  }

  /* ---- the editor ---- */

  // A Markdown heading's line ("# Build", "## Tests") in 600 ink.
  const headLine = Decoration.line({ class: "cm-md-head" });
  const headings = ViewPlugin.fromClass(class {
    constructor(v) { this.decorations = this.build(v); }
    update(u) { if (u.docChanged || u.viewportChanged) this.decorations = this.build(u.view); }
    build(v) {
      const marks = new RangeSetBuilder();
      for (const { from, to } of v.visibleRanges) {
        for (let pos = from; pos <= to;) {
          const line = v.state.doc.lineAt(pos);
          if (/^#{1,6}\s/.test(line.text)) marks.add(line.from, line.from, headLine);
          pos = line.to + 1;
        }
      }
      return marks.finish();
    }
  }, { decorations: (p) => p.decorations });

  // The filler's rows number on from the text's last line.
  const numberFiller = () => {
    filler?.firstElementChild?.style.setProperty("counter-reset", `sheet-row ${view.state.doc.lines}`);
  };

  const theme = EditorView.theme({
    "&": { fontSize: "var(--t-body-sm)", letterSpacing: "-0.01em" },
    "&.cm-focused": { outline: "none" },
    ".cm-scroller": { fontFamily: "inherit", lineHeight: "var(--pad-text)", overflow: "visible" },
    ".cm-content": { padding: "0", caretColor: "var(--ink)" },
    ".cm-line": {
      padding: "var(--pad-above) var(--s-4) var(--pad-below) var(--pad-gap)",
      borderBottom: "1px solid var(--hairline)",
      color: "var(--ink)",
    },
    ".cm-line.cm-md-head": { fontWeight: "600" },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--ink)", borderLeftWidth: "1.5px" },
    "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      background: "color-mix(in srgb, var(--spark) 22%, transparent)",
    },
    // The sheet draws the numbers' fog and its edge; the gutter is as wide.
    ".cm-gutters": { backgroundColor: "transparent", color: "var(--pewter)", border: "none" },
    ".cm-lineNumbers .cm-gutterElement": {
      boxSizing: "border-box",
      minWidth: "var(--pad-rows)",
      padding: "0 var(--s-2) 0 0",
      lineHeight: "calc(var(--pad-line) - 1px)",
      background: "linear-gradient(to top, var(--hairline) 1px, transparent 1px)",
      fontFamily: "var(--font-num)",
      fontSize: "var(--t-caption)",
      fontVariantNumeric: "tabular-nums",
      letterSpacing: "normal",
    },
    ".cm-activeLineGutter": { backgroundColor: "transparent" },
    ".cm-placeholder": { color: "var(--pewter)" },
  });

  view = new EditorView({
    state: EditorState.create({
      doc: source.value,
      extensions: [
        lineNumbers(),
        history(),
        drawSelection(),
        EditorView.lineWrapping,
        placeholder(source.dataset.placeholder || ""),
        EditorView.contentAttributes.of({ "aria-label": source.getAttribute("aria-label") || "Document", spellcheck: "true" }),
        keymap.of([
          { key: "Mod-s", preventDefault: true, run: () => { save(); return true; } },
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        headings,
        EditorView.updateListener.of((u) => {
          if (!u.docChanged) return;
          numberFiller();
          schedule();
        }),
        theme,
      ],
    }),
  });
  source.after(view.dom);
  source.hidden = true;
  numberFiller();

  // A click under the text writes at its end.
  filler?.addEventListener("mousedown", (e) => {
    e.preventDefault();
    view.focus();
    view.dispatch({ selection: { anchor: view.state.doc.length }, scrollIntoView: true });
  });

  // An empty document opens ready to be written.
  if (!source.value) view.focus();

  /* ---- its name ---- */

  if (nameInput) {
    nameInput.addEventListener("input", schedule);
    nameInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.isComposing) {
        e.preventDefault();
        view.focus();
        save();
      } else if (e.key === "Escape") {
        nameInput.value = savedName;
        view.focus();
      }
    });
    nameInput.addEventListener("blur", () => {
      if (!name()) nameInput.value = savedName;
      save();
    });
  }

  // Deleted, it goes without saving what it held.
  document.addEventListener("htmx:beforeRequest", (e) => {
    if (e.detail.elt.closest?.(".doc-title .task-delete")) deleted = true;
  });
  document.addEventListener("htmx:responseError", (e) => {
    if (e.detail.elt.closest?.(".doc-title .task-delete")) deleted = false;
  });

  window.addEventListener("pagehide", () => save({ leaving: true }));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") save({ leaving: true });
  });

  // For the page's tests: the document as written.
  window.DocEditor = { get view() { return view; }, text: body };
})();
