/* The New project window (#project-dialog, in base.html): Projects' New
   project opens it, and so do Shift+A there and "New project" in the
   command menu on any page. Its form (partials/project_new.html) is
   fetched afresh each time it opens, so the colour it starts on is the
   next one free and nothing written before is left in it; the caret is
   in the name. The name is the one thing it needs: Create project with
   none sends nothing and says so under it, until a letter is written.
   Enter on a line or Ctrl+Enter (Cmd+Enter) anywhere creates, Esc, Cancel
   or a click outside closes it. What the app refuses is said under the
   field it is about, not in a toast, the window open with what was
   written; created, the server sends the browser to the project's page. */

(() => {
  const dialog = document.getElementById("project-dialog");
  if (!dialog) return;
  const form = () => dialog.querySelector("[data-project-new-form]");

  let opening = 0; // the latest opening, so a slow answer to an earlier one is dropped
  const open = async () => {
    if (dialog.open) return true;
    const asked = ++opening;
    let html = "";
    try {
      const res = await fetch("/ui/projects/new");
      if (!res.ok) throw new Error(res.statusText);
      html = await res.text();
    } catch {
      if (asked === opening) window.toast("Could not open a new project. Try again?");
      return true;
    }
    if (asked !== opening || dialog.open || document.querySelector("dialog[open]")) return true;
    dialog.innerHTML = html;
    window.htmx.process(dialog);
    dialog.showModal();
    form()?.elements.name?.focus();
    return true;
  };

  // Closed, it is emptied, so the next opening starts afresh.
  dialog.addEventListener("close", () => dialog.replaceChildren());

  document.addEventListener("click", (e) => {
    if (e.target.closest?.("[data-project-new]")) open();
  });
  window.Keys?.handle("project.new", () => { open(); });

  /* ---- what is said under a field ---- */

  const errorOf = (input) => document.getElementById(input.getAttribute("aria-describedby") || "");
  const say = (input, message) => {
    const error = errorOf(input);
    if (!error) return;
    error.dataset.said ??= error.textContent;
    error.textContent = message || error.dataset.said;
    error.hidden = false;
    input.setAttribute("aria-invalid", "true");
  };
  const unsay = (input) => {
    const error = errorOf(input);
    if (!error || error.hidden) return;
    error.hidden = true;
    input.removeAttribute("aria-invalid");
  };
  const fieldOf = (target) => (target.matches?.("input[name], textarea[name]") ? target : null);
  dialog.addEventListener("input", (e) => {
    const field = fieldOf(e.target);
    if (field) unsay(field);
  });
  // A repository picked from the list fills the line (repo-picker.js).
  dialog.addEventListener("repo:picked", (e) => unsay(e.target));

  /* ---- creating ---- */

  // No name, no request: said under it, the caret back in it.
  dialog.addEventListener("htmx:beforeRequest", (e) => {
    const f = form();
    if (e.detail.elt !== f) return;
    const name = f.elements.name;
    if (name.value.trim()) return;
    e.preventDefault();
    say(name);
    name.focus();
  });

  // Refused: under the field it is about, and in no toast as well (shell.js
  // toasts the rest on the document, after this).
  dialog.addEventListener("htmx:responseError", (e) => {
    const f = form();
    if (e.detail.elt !== f) return;
    let answer = null;
    try { answer = JSON.parse(e.detail.xhr.responseText); } catch { return; }
    if (typeof answer?.detail !== "string") return;
    const field = f.elements[answer.field === "location" ? "location" : "name"];
    if (!field) return;
    e.stopPropagation();
    say(field, answer.detail);
    field.focus();
  });

  dialog.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey) || e.isComposing) return;
    e.preventDefault();
    form()?.requestSubmit();
  });

  /* ---- closing ---- */

  dialog.addEventListener("click", (e) => {
    if (e.target.closest("[data-project-new-cancel]")) dialog.close();
  });
  // A click on the backdrop closes it; a press that began inside (selecting
  // words) and let go outside does not.
  let pressedOutside = false;
  dialog.addEventListener("pointerdown", (e) => { pressedOutside = e.target === dialog; });
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog && pressedOutside) dialog.close();
    pressedOutside = false;
  });

  window.ProjectNew = { open };
})();
