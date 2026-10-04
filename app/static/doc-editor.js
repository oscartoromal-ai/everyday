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
   at its end.

   Its file in the project's folder is the master copy, which an editor or
   an agent may write too. A save names the version its words were written
   over; one refused because the file has moved on since stops the saving
   and asks which to keep, as Today's notes do. Coming back to the tab shows
   the file as it is now, when nothing here is still to save. */

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
  // The file's version this copy was read at; and, once a save was refused,
  // the file's since (stale until Oscar chooses which to keep).
  let version = page.dataset.version;
  let stale = false;
  let theirs = null;
  const staleBar = page.querySelector("[data-doc-stale]");

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
    if (deleted || stale) return;
    const changes = pending();
    if (!Object.keys(changes).length) return;
    if ("body" in changes) changes.base = version;
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
      const answer = await res.json().catch(() => ({}));
      if (res.status === 409) {
        stale = true;
        theirs = answer.version;
        staleBar.hidden = false;
        sayState("Not saved");
        return;
      }
      if (!res.ok) throw new Error(typeof answer.detail === "string" ? answer.detail : "");
      version = answer.version;
      if ("body" in changes) savedBody = changes.body;
      if ("name" in changes) named(answer.name, changes.name);
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

  // Its name as the file has it: the one written, made a file's ("Notes" is
  // Notes.md), in the heading unless more has been written there since.
  function named(fileName, written = savedName) {
    if (nameInput && name() === written) nameInput.value = fileName;
    savedName = fileName;
    document.title = document.title.replace(/^[^·]*·/, `${fileName} ·`);
    const file = page.querySelector("[data-doc-file]");
    if (file) file.textContent = file.textContent.replace(/[^\\/]*$/, fileName);
  }

  // The file as it is now, in place of what is here: its words, its name and
  // its version.
  async function showLatest() {
    const res = await fetch(`/ui/docs/${page.dataset.doc}/latest`).catch(() => null);
    if (res?.status === 404) {
      location.reload();
      return;
    }
    const answer = res?.ok ? await res.json() : null;
    if (!answer) return;
    savedBody = answer.body;
    version = answer.version;
    if (answer.name !== savedName) named(answer.name);
    if (body() !== answer.body) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: answer.body } });
      clearTimeout(timer);
    }
    stale = false;
    staleBar.hidden = true;
    sayState("");
  }

  // Moved to another folder from the line under its name: its file's path
  // says where it went.
  document.addEventListener("htmx:afterRequest", (e) => {
    if (!e.detail.successful || !e.detail.elt.matches?.('.doc-rest select[name="folder"]')) return;
    let answer = {};
    try { answer = JSON.parse(e.detail.xhr.responseText); } catch { return; }
    const file = page.querySelector("[data-doc-file]");
    if (file && answer.file) file.textContent = answer.file;
  });

  staleBar.addEventListener("click", (e) => {
    if (e.target.closest("[data-doc-reload]")) {
      showLatest();
    } else if (e.target.closest("[data-doc-keep]")) {
      stale = false;
      version = theirs;
      staleBar.hidden = true;
      save();
    }
  });

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
          // Save now: Ctrl+S, or the keys chosen for it (keys.py).
          ...window.Keys.cm("save.now").map((key) => ({ key, preventDefault: true, run: () => { save(); return true; } })),
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
    // Back to the tab: the file as an editor or agent left it, unless there
    // is writing here still to save.
    else if (!stale && !sending && !Object.keys(pending()).length) showLatest();
  });

  // For the page's tests: the document as written.
  window.DocEditor = { get view() { return view; }, text: body, showLatest };
})();
