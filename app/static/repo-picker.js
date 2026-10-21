/* The line to add a repository to a project (project_repos.html), and the
   New project window's (project_new.html): a combobox over his GitHub
   repositories. Focused, it lists them, last pushed first; written on,
   those holding its words (the server draws the line's list each time, in
   the box its data-repo-box names, #repo-options unless it names another,
   so two lines on one page never cross). Up and Down move through them,
   Enter or a click takes the one picked, as its URL, and Esc folds the
   list away. On a project's Overview the one taken is added at once; a
   line marked data-repo-fill is only filled, for its form to send with the
   rest. Written words found nowhere are taken as written, a folder or a
   URL. Events are delegated, so the card drawn again after each change
   needs nothing more. */

(() => {
  const isPicker = (el) => el instanceof HTMLInputElement && el.matches("[data-repo-picker]");
  const boxId = (input) => input.dataset.repoBox || "repo-options";
  const box = (input) => document.getElementById(boxId(input));
  // The line a list is for.
  const lineOf = (el) => {
    const list = el.closest(".repo-options");
    if (!list) return null;
    return [...document.querySelectorAll("[data-repo-picker]")].find((i) => boxId(i) === list.id) || null;
  };
  const options = (input) => [...(box(input)?.querySelectorAll('[role="option"]') || [])];
  const active = (input) => box(input)?.querySelector('[role="option"][aria-selected="true"]') || null;

  const shown = (input) => {
    const el = box(input);
    return !!el && !el.hidden;
  };

  const activate = (input, option) => {
    for (const o of options(input)) o.setAttribute("aria-selected", String(o === option));
    if (option) {
      input.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };

  const fold = (input) => {
    const el = box(input);
    if (el) el.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  };

  const pick = (input, option) => {
    input.value = option.dataset.location;
    fold(input);
    // Not an input event: that would ask for the list again.
    if ("repoFill" in input.dataset) input.dispatchEvent(new Event("repo:picked", { bubbles: true }));
    else input.form.requestSubmit();
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
    const target = e.detail.target;
    if (!target?.classList?.contains("repo-options")) return;
    const input = lineOf(target);
    if (!input) return;
    input.setAttribute("aria-expanded", String(options(input).length > 0 && shown(input)));
    // The card may sit at the page's foot: the list is brought into sight
    // (a window's floats over it instead).
    if (shown(input) && !input.closest("dialog")) box(input).scrollIntoView({ block: "nearest", behavior: "smooth" });
    // Words written: the first found is the one Enter takes.
    activate(input, input.value.trim() ? options(input)[0] || null : null);
  });

  document.addEventListener("keydown", (e) => {
    const input = e.target;
    if (!isPicker(input)) return;
    delete input.dataset.quiet;
    const all = options(input);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!shown(input)) {
        // Folded: open it again, as focusing it does.
        window.htmx?.trigger(input, "focus");
        e.preventDefault();
        return;
      }
      if (!all.length) return;
      e.preventDefault();
      const at = all.indexOf(active(input));
      const next = e.key === "ArrowDown"
        ? (at + 1) % all.length
        : (at <= 0 ? all.length - 1 : at - 1);
      activate(input, all[next]);
    } else if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
      const option = shown(input) ? active(input) : null;
      if (option) {
        e.preventDefault();
        e.stopPropagation();
        pick(input, option);
      }
    } else if (e.key === "Escape" && shown(input)) {
      e.preventDefault();
      e.stopPropagation();
      fold(input);
    }
  }, true);

  // A press in the list keeps the focus on the line, so the list stays.
  document.addEventListener("mousedown", (e) => {
    if (e.target instanceof Element && e.target.closest(".repo-options")) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const option = e.target instanceof Element && e.target.closest('.repo-options [role="option"]');
    const input = option && lineOf(option);
    if (input) pick(input, option);
  });

  document.addEventListener("mousemove", (e) => {
    const option = e.target instanceof Element && e.target.closest('.repo-options [role="option"]');
    const input = option && lineOf(option);
    if (input && option !== active(input)) activate(input, option);
  });

  document.addEventListener("focusout", (e) => {
    if (isPicker(e.target)) {
      delete e.target.dataset.quiet;
      fold(e.target);
    }
  });
})();
