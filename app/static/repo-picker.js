/* The line to add a repository to a project (project_repos.html): a
   combobox over his GitHub repositories. Focused, it lists them, last
   pushed first; written on, those holding its words (the server draws
   #repo-options each time). Up and Down move through them, Enter or a
   click adds the one picked, as its URL, and Esc folds the list away.
   Written words found nowhere are added as written, a folder or a URL.
   Events are delegated, so the card drawn again after each change needs
   nothing more. */

(() => {
  const isPicker = (el) => el instanceof HTMLInputElement && el.matches("[data-repo-picker]");
  const box = () => document.getElementById("repo-options");
  const options = () => [...(box()?.querySelectorAll('[role="option"]') || [])];
  const active = () => box()?.querySelector('[role="option"][aria-selected="true"]') || null;

  const shown = () => {
    const el = box();
    return !!el && !el.hidden;
  };

  const activate = (input, option) => {
    for (const o of options()) o.setAttribute("aria-selected", String(o === option));
    if (option) {
      input.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };

  const fold = (input) => {
    const el = box();
    if (el) el.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  };

  const pick = (input, option) => {
    input.value = option.dataset.location;
    fold(input);
    input.form.requestSubmit();
  };

  // A list arriving once the line has lost the focus is not drawn.
  document.addEventListener("htmx:beforeSwap", (e) => {
    const input = e.detail.requestConfig?.elt;
    if (isPicker(input) && document.activeElement !== input) e.detail.shouldSwap = false;
  });

  // Just after one is added, the focus coming back to the line does not
  // offer more at once; a click, a key or words do.
  document.addEventListener("htmx:beforeRequest", (e) => {
    const input = e.detail.elt;
    if (!isPicker(input) || !("quiet" in input.dataset)) return;
    delete input.dataset.quiet;
    if (e.detail.requestConfig?.triggeringEvent?.type === "focus") e.preventDefault();
  });

  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target?.id !== "repo-options") return;
    const input = document.querySelector("[data-repo-picker]");
    if (!input) return;
    input.setAttribute("aria-expanded", String(options().length > 0 && shown()));
    // The card may sit at the page's foot: the list is brought into sight.
    if (shown()) box().scrollIntoView({ block: "nearest", behavior: "smooth" });
    // Words written: the first found is the one Enter takes.
    activate(input, input.value.trim() ? options()[0] || null : null);
  });

  document.addEventListener("keydown", (e) => {
    const input = e.target;
    if (!isPicker(input)) return;
    delete input.dataset.quiet;
    const all = options();
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!shown()) {
        // Folded: open it again, as focusing it does.
        window.htmx?.trigger(input, "focus");
        e.preventDefault();
        return;
      }
      if (!all.length) return;
      e.preventDefault();
      const at = all.indexOf(active());
      const next = e.key === "ArrowDown"
        ? (at + 1) % all.length
        : (at <= 0 ? all.length - 1 : at - 1);
      activate(input, all[next]);
    } else if (e.key === "Enter") {
      const option = shown() ? active() : null;
      if (option) {
        e.preventDefault();
        pick(input, option);
      }
    } else if (e.key === "Escape" && shown()) {
      e.preventDefault();
      e.stopPropagation();
      fold(input);
    }
  }, true);

  // A press in the list keeps the focus on the line, so the list stays.
  document.addEventListener("mousedown", (e) => {
    if (e.target instanceof Element && e.target.closest("#repo-options")) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const option = e.target instanceof Element && e.target.closest('#repo-options [role="option"]');
    const input = document.querySelector("[data-repo-picker]");
    if (option && input) pick(input, option);
  });

  document.addEventListener("mousemove", (e) => {
    const option = e.target instanceof Element && e.target.closest('#repo-options [role="option"]');
    const input = document.querySelector("[data-repo-picker]");
    if (option && input && option !== active()) activate(input, option);
  });

  document.addEventListener("focusout", (e) => {
    if (isPicker(e.target)) {
      delete e.target.dataset.quiet;
      fold(e.target);
    }
  });
})();
