/* The description editor: a task's notes written as Markdown and shown as
   they read (markdown-editor.js, on CodeMirror 6), its sub-tasks boxes.
   The hidden textarea beside it stays the form field, holding the same
   plain text the server stores (app/checklist.py), so nothing outside this
   file knows the editor exists: every change is written into it at once,
   with an input event, as typing in it would.

   Each [data-notes-editor] in a [data-notes-field] gets its editor as htmx
   loads it, and loses it as htmx takes it away. */

(() => {
  const { EditorState, EditorView, keymap, placeholder, drawSelection, defaultKeymap, history, historyKeymap } = window.CM;

  const views = new WeakMap(); // [data-notes-editor] -> EditorView
  const field = (root) => root.closest("[data-notes-field]").querySelector("textarea");

  // Ctrl+Enter belongs to the task sheet (add, or save), not to a blank line.
  const keys = defaultKeymap.filter((b) => b.key !== "Mod-Enter");

  const stateFor = (root, text) => EditorState.create({
    doc: text,
    extensions: [
      window.MarkdownEditor.livePreview({ checklist: true }),
      history(),
      drawSelection(),
      placeholder(root.dataset.placeholder || ""),
      EditorView.contentAttributes.of({ "aria-label": root.getAttribute("aria-label") || "Description" }),
      keymap.of([...keys, ...historyKeymap]),
      EditorView.updateListener.of((u) => {
        if (!u.docChanged) return;
        const textarea = field(root);
        textarea.value = u.state.doc.toString();
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
      }),
    ],
  });

  const init = (root) => {
    if (views.has(root)) return;
    const view = new EditorView({ state: stateFor(root, field(root).value), parent: root });
    views.set(root, view);
  };

  // The editor's text set from the field, with a fresh history: after a
  // form reset, or a draft carried over from another sheet.
  const reload = (root) => {
    const view = views.get(root);
    if (view) view.setState(stateFor(root, field(root).value));
  };

  document.addEventListener("htmx:load", (e) => {
    const elt = e.detail.elt;
    if (elt.matches?.("[data-notes-editor]")) init(elt);
    elt.querySelectorAll?.("[data-notes-editor]").forEach(init);
  });

  // An editor taken off the page lets go of the window's events.
  document.addEventListener("htmx:beforeCleanupElement", (e) => {
    const view = views.get(e.detail.elt);
    if (!view) return;
    view.destroy();
    views.delete(e.detail.elt);
  });

  // A form reset (after Add, or Cancel) empties the field; the editor follows.
  document.addEventListener("reset", (e) => {
    e.target.querySelectorAll?.("[data-notes-editor]").forEach((root) => setTimeout(() => reload(root)));
  }, true);

  // A click in the field's empty room under the text writes at its end.
  document.addEventListener("mousedown", (e) => {
    const root = e.target.closest?.("[data-notes-editor]");
    const view = root && views.get(root);
    if (!view || e.target !== root || e.button !== 0) return;
    e.preventDefault();
    window.NotesEditor.focusEnd(root);
  });

  window.NotesEditor = {
    reload,
    focusEnd(root) {
      const view = views.get(root);
      if (!view) return;
      view.focus();
      view.dispatch({ selection: { anchor: view.state.doc.length }, scrollIntoView: true });
    },
    // For the tests: the editor of a [data-notes-editor].
    viewOf: (root) => views.get(root),
  };
})();
