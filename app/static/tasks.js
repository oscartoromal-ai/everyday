/* Writing tasks: the quick-add composer and the rows' collapsible
   descriptions. The description editor itself is notes-editor.js. Listeners
   sit on document, so they survive htmx swaps. */

(() => {
  const SUBMIT = (e) => e.key === "Enter" && (e.ctrlKey || e.metaKey);

  /* ---- the composer: title, then a description revealed on focus ---- */

  const composerOf = (el) => el.closest?.("[data-composer]");
  const editorOf = (form) => form.querySelector("[data-notes-editor]");
  const hasNotes = (form) => form.elements.notes.value.trim() !== "";

  const open = (form) => form.classList.add("composing");
  const close = (form) => form.classList.remove("composing");

  document.addEventListener("focusin", (e) => {
    const form = composerOf(e.target);
    if (form) open(form);
  });

  document.addEventListener("focusout", (e) => {
    const form = composerOf(e.target);
    if (!form || form.contains(e.relatedTarget)) return;
    // Written context stays on screen; an untouched description folds away.
    if (!hasNotes(form)) close(form);
  });

  // Touch Safari never focuses a tapped button, so the blur would fold the
  // composer away under the finger; keep focus where it is instead.
  document.addEventListener("pointerdown", (e) => {
    if (e.target.closest?.(".quick-add-actions button")) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const cancel = e.target.closest?.("[data-composer-cancel]");
    if (!cancel) return;
    const form = composerOf(cancel);
    form.reset();
    close(form);
    document.activeElement?.blur();
  });

  document.addEventListener("keydown", (e) => {
    const target = e.target;
    const form = composerOf(target);

    if (SUBMIT(e) && (form || target.closest?.("[data-notes-editor]"))) {
      e.preventDefault();
      if (form && !form.elements.title.value.trim()) form.elements.title.focus();
      else target.closest("form").requestSubmit();
      return;
    }

    if (form && e.key === "Escape") {
      e.preventDefault();
      // Esc steps away; a draft stays put until Cancel or Add.
      if (!hasNotes(form)) close(form);
      target.blur();
      return;
    }

    if (form && target === form.elements.title && e.key === "Enter" && !e.isComposing) {
      // Enter moves on to the description; Ctrl+Enter (or Add task) saves.
      e.preventDefault();
      if (target.value.trim()) window.NotesEditor.focusEnd(editorOf(form));
    }
  });

  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.detail.elt;
    if (!form.matches?.("[data-composer]") || !e.detail.successful) return;
    form.reset();
    close(form);
    // Ready for the next one.
    form.elements.title.focus();
  });

  /* ---- rows: the description folds under the meta line ---- */

  const KEY = "pc-open-notes";
  const remembered = () => {
    try { return new Set(JSON.parse(sessionStorage.getItem(KEY)) || []); } catch { return new Set(); }
  };
  const remember = (id, isOpen) => {
    const ids = remembered();
    if (isOpen) ids.add(id); else ids.delete(id);
    try { sessionStorage.setItem(KEY, JSON.stringify([...ids])); } catch { /* storage blocked */ }
  };

  const setOpen = (toggle, isOpen) => {
    toggle.setAttribute("aria-expanded", String(isOpen));
    document.getElementById(toggle.getAttribute("aria-controls")).hidden = !isOpen;
  };

  document.addEventListener("click", (e) => {
    const toggle = e.target.closest?.(".notes-toggle");
    if (!toggle) return;
    const isOpen = toggle.getAttribute("aria-expanded") !== "true";
    setOpen(toggle, isOpen);
    remember(toggle.getAttribute("aria-controls"), isOpen);
  });

  // Today re-renders its list on every calendar change; reopen what was open.
  const restore = (root) => {
    const ids = remembered();
    root.querySelectorAll?.(".notes-toggle").forEach((toggle) => {
      const id = toggle.getAttribute("aria-controls");
      if (toggle.getAttribute("aria-expanded") === "true") remember(id, true);
      else if (ids.has(id)) setOpen(toggle, true);
    });
  };
  document.addEventListener("htmx:load", (e) => restore(e.detail.elt));
})();
