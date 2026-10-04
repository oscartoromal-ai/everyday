/* A document of a project's context on its own page (project_doc.html):
   its Markdown written and drawn as it reads (markdown-live.js, on
   CodeMirror 6), bullets as bullets, "- [ ] " as boxes, in the mode last
   chosen for a document from the header's switch (Live, Source, Reading;
   Ctrl+E in and out of reading); and its name, any but AGENTS.md's,
   written in the heading.

   Both are saved as they are written: a moment after the writing pauses,
   at once on Ctrl+S or Enter in the name, and as the page is left or its
   tab hidden. Saves go one at a time, a save asked for while one is in
   flight following it with what is newest. The header says "Saved" once
   one lands, nothing while there is writing still to save, and "Not saved"
   (with a toast) if one fails. A click in the room under the text writes
   at its end. */

(() => {
  const { EditorState, EditorView, drawSelection, keymap, placeholder, defaultKeymap, history, historyKeymap } = window.CM;

  const page = document.querySelector(".doc-page[data-doc]");
  const source = page?.querySelector("[data-doc-body]");
  if (!source) return;

  const PAUSE_MS = 900;
  const nameInput = page.querySelector("[data-doc-name]");
  const room = page.querySelector("[data-doc-editor]");
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

  // An empty document opens to be written, whatever it was last left in.
  const mode = source.value ? window.MarkdownLive.rememberedMode("doc") : "live";

  view = new EditorView({
    state: EditorState.create({
      doc: source.value,
      extensions: [
        window.MarkdownLive.extensions({ mode }),
        history(),
        drawSelection(),
        placeholder(source.dataset.placeholder || ""),
        EditorView.contentAttributes.of({ "aria-label": source.getAttribute("aria-label") || "Document" }),
        keymap.of([
          { key: "Mod-s", preventDefault: true, run: () => { save(); return true; } },
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) schedule();
        }),
      ],
    }),
  });
  source.after(view.dom);
  window.MarkdownLive.bindSwitch(page.querySelector("[data-md-modes]"), () => view, "doc");

  // A click in the room under the text writes at its end.
  room.addEventListener("mousedown", (e) => {
    if (e.target !== room || e.button !== 0 || window.MarkdownLive.modeOf(view) === "reading") return;
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
