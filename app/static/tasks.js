/* Writing tasks: the quick-add composer, the description textareas where a
   "- " line is a sub-task, and the rows' collapsible descriptions. Listeners
   sit on document, so they survive htmx swaps. */

(() => {
  const SUBMIT = (e) => e.key === "Enter" && (e.ctrlKey || e.metaKey);

  /* ---- description textareas: lists continue, height follows content ---- */

  const ITEM = /^([ \t]*)([-*])[ \t]+(?:\[[ xX]\][ \t]+)?(.*)$/;

  const insert = (area, text) => {
    // execCommand keeps the browser's own undo stack; setRangeText is the fallback.
    if (!document.execCommand("insertText", false, text)) {
      area.setRangeText(text, area.selectionStart, area.selectionEnd, "end");
      area.dispatchEvent(new Event("input", { bubbles: true }));
    }
  };

  const continueList = (area, e) => {
    if (e.key !== "Enter" || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    const { value, selectionStart: start, selectionEnd: end } = area;
    if (start !== end) return;
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    const match = ITEM.exec(value.slice(lineStart, start));
    if (!match) return;
    e.preventDefault();
    if (match[3].trim() === "") {
      // Enter on an empty sub-task ends the list, as in any editor.
      area.setSelectionRange(lineStart, start);
      if (!document.execCommand("delete")) {
        area.setRangeText("", lineStart, start, "end");
        area.dispatchEvent(new Event("input", { bubbles: true }));
      }
    } else {
      insert(area, `\n${match[1]}${match[2]} `);
    }
  };

  const autosizeNeeded = !CSS.supports("field-sizing", "content");
  const autosize = (area) => {
    if (!autosizeNeeded) return;
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight + area.offsetHeight - area.clientHeight}px`;
  };

  document.addEventListener("input", (e) => {
    if (e.target.matches?.("[data-checklist-input]")) autosize(e.target);
  });

  /* ---- the composer: title, then a description revealed on focus ---- */

  const composerOf = (el) => el.closest?.("[data-composer]");
  const hasDraft = (form) => form.elements.title.value.trim() || form.elements.notes.value.trim();

  const open = (form) => form.classList.add("composing");
  const close = (form) => {
    form.classList.remove("composing");
    form.elements.notes.style.height = "";
  };

  document.addEventListener("focusin", (e) => {
    const form = composerOf(e.target);
    if (form) open(form);
  });

  document.addEventListener("focusout", (e) => {
    const form = composerOf(e.target);
    if (!form || form.contains(e.relatedTarget)) return;
    // Written context stays on screen; an untouched description folds away.
    if (!form.elements.notes.value.trim()) close(form);
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
    form.elements.title.blur();
  });

  document.addEventListener("keydown", (e) => {
    const target = e.target;
    const form = composerOf(target);

    if (SUBMIT(e) && (form || target.matches?.("[data-checklist-input]"))) {
      e.preventDefault();
      const owner = form || target.form;
      if (form && !form.elements.title.value.trim()) form.elements.title.focus();
      else owner.requestSubmit();
      return;
    }

    if (form && e.key === "Escape") {
      e.preventDefault();
      // Esc steps away; a draft stays put until Cancel or Add.
      if (!form.elements.notes.value.trim()) close(form);
      target.blur();
      return;
    }

    if (form && target === form.elements.title && e.key === "Enter" && !e.isComposing) {
      // Enter moves on to the description; Ctrl+Enter (or Add task) saves.
      e.preventDefault();
      if (target.value.trim()) form.elements.notes.focus();
      return;
    }

    if (target.matches?.("[data-checklist-input]")) continueList(target, e);
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
    root.querySelectorAll?.("[data-checklist-input]").forEach(autosize);
  };
  document.addEventListener("htmx:load", (e) => restore(e.detail.elt));
})();
