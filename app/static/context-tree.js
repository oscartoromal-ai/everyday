/* A project's context as a tree, on its page (partials/project_context.html):
   its folders fold by their rows, remembered; a row's tools add a document
   or a folder in a folder, rename or delete; rows are dragged into folders,
   or out to the top. The tree is drawn again by the server after each
   change, so everything here listens on the document.

   New and rename are written in place, in a row of their own: Enter keeps
   it, Esc lets it go. From the keyboard, Up and Down step through the rows
   shown, Right opens a folder (then steps into it), Left folds it (or steps
   out to its folder), F2 renames and Delete deletes, after asking (their
   keys keys.py's). */

(() => {
  const card = () => document.getElementById("project-context");
  if (!card()) return;

  const project = () => card().dataset.project;
  const nodeOf = (el) => el?.closest?.(".ctx-node");
  const folderOf = (node) => node?.parentElement?.closest(".ctx-folder") || null;
  const toggleOf = (folder) => folder.querySelector(":scope > .ctx-row > .ctx-toggle");
  const groupOf = (folder) => folder.querySelector(":scope > .ctx-group");
  const isOpen = (folder) => toggleOf(folder).getAttribute("aria-expanded") === "true";

  // What the next drawing of the tree should bring into view and focus: a
  // node by its kind and name, and the folder it went in (null: the top).
  let landing = null;
  const land = (kind, name, folder) => { landing = { kind, name, folder: folder && folder !== "top" ? folder : "" }; };

  const post = (url, values, swap = "outerHTML") =>
    htmx.ajax("POST", url, { target: "#project-context", swap, values });

  /* ---- folding ---- */

  const fold = (folder, open, save = true) => {
    if (isOpen(folder) === open) return;
    toggleOf(folder).setAttribute("aria-expanded", String(open));
    groupOf(folder).hidden = !open;
    if (save) htmx.ajax("POST", `/ui/folders/${folder.dataset.folder}/fold`, { swap: "none", values: { folded: !open } });
  };

  document.addEventListener("click", (e) => {
    const toggle = e.target.closest(".project-context .ctx-toggle");
    if (!toggle) return;
    const folder = nodeOf(toggle);
    fold(folder, !isOpen(folder));
  });

  /* ---- a new document or folder, named in a row where it will go ---- */

  const dropDraft = () => {
    const draft = card()?.querySelector(".ctx-draft");
    if (!draft) return;
    draft.parentElement.querySelector(":scope > .ctx-empty")?.removeAttribute("hidden");
    // Removing it blurs its field, which asks for it to go again: by then
    // it is no longer found.
    draft.classList.remove("ctx-draft");
    draft.remove();
  };

  const startDraft = (kind, folder) => {
    dropDraft();
    if (folder) fold(folder, true);
    const group = folder ? groupOf(folder) : card().querySelector("[data-ctx-root]");
    const draft = document.getElementById("ctx-draft").content.firstElementChild.cloneNode(true);
    const form = draft.querySelector("form");
    const depth = folder ? Number(folder.style.getPropertyValue("--depth")) + 1 : 0;
    draft.style.setProperty("--depth", depth);
    draft.dataset.kind = kind;
    form.elements.folder.value = folder?.dataset.folder ?? "top";
    const name = form.elements.name;
    const where = folder ? ` in ${folder.dataset.name}` : "";
    name.placeholder = kind === "doc" ? `New document${where}: its name, as Architecture.md` : `New folder${where}: its name`;
    name.setAttribute("aria-label", kind === "doc" ? `New document${where}` : `New folder${where}`);
    if (kind === "doc") {
      form.setAttribute("hx-post", `/ui/projects/${project()}/docs`);
      form.setAttribute("hx-swap", "none");
    } else {
      form.setAttribute("hx-post", `/ui/projects/${project()}/folders`);
      form.setAttribute("hx-target", "#project-context");
      form.addEventListener("submit", () => land("folder", name.value.trim().split(/[/\\]/).filter(Boolean)[0], form.elements.folder.value));
    }
    // At the top of where it goes, in place of "Nothing in it yet".
    group.querySelector(":scope > .ctx-empty")?.setAttribute("hidden", "");
    group.prepend(draft);
    htmx.process(draft);
    name.focus();
    draft.scrollIntoView({ block: "nearest" });
  };

  document.addEventListener("click", (e) => {
    const button = e.target.closest(".project-context [data-ctx-new]");
    if (!button) return;
    startDraft(button.dataset.ctxNew, button.closest(".ctx-folder"));
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !e.target.closest?.(".ctx-draft")) return;
    e.preventDefault();
    const folder = folderOf(nodeOf(e.target));
    dropDraft();
    (folder ? toggleOf(folder) : card().querySelector("#doc-new")).focus();
  });
  // Left empty, it goes; left with a name in it, it waits to be added.
  document.addEventListener("focusout", (e) => {
    const draft = e.target.closest?.(".ctx-draft");
    if (draft && !e.target.value?.trim() && !draft.contains(e.relatedTarget)) dropDraft();
  });

  /* ---- renaming, in a field over the row's name ---- */

  const startRename = (node) => {
    if (!node || node.querySelector(":scope > .ctx-row > .ctx-rename")) return;
    const row = node.querySelector(":scope > .ctx-row");
    const open = row.querySelector(".ctx-open");
    const form = document.createElement("form");
    form.className = "ctx-rename";
    form.append(open.querySelector(".ctx-chevron").cloneNode(true), open.querySelector(".ov-icon").cloneNode(true));
    const input = document.createElement("input");
    input.className = "ctx-name";
    input.value = node.dataset.name;
    input.maxLength = 200;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("aria-label", `Rename ${node.dataset.name}`);
    form.append(input);
    row.prepend(form);
    row.classList.add("is-renaming");
    input.focus();
    // The name without its extension chosen, ready to be written over.
    const dot = node.classList.contains("ctx-doc") ? input.value.lastIndexOf(".") : -1;
    input.setSelectionRange(0, dot > 0 ? dot : input.value.length);

    let done = false;
    const finish = (save) => {
      if (done) return;
      done = true;
      const name = input.value.trim();
      const kind = node.classList.contains("ctx-folder") ? "folder" : "doc";
      if (save && name && name !== node.dataset.name) {
        land(kind, name, folderOf(node)?.dataset.folder);
        const id = node.dataset.folder || node.dataset.doc;
        post(`/ui/${kind === "folder" ? "folders" : "docs"}/${id}/place`, { name }).then(() => {
          // Refused (a name taken): the row as it was, the toast saying why.
          if (node.isConnected) { form.remove(); row.classList.remove("is-renaming"); open.focus(); }
        });
        return;
      }
      form.remove();
      row.classList.remove("is-renaming");
      open.focus();
    };
    form.addEventListener("submit", (e) => { e.preventDefault(); finish(true); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
  };

  document.addEventListener("click", (e) => {
    const button = e.target.closest(".project-context [data-ctx-rename]");
    if (button) startRename(nodeOf(button));
  });

  /* ---- the keyboard, on a row ---- */

  const shown = () => [...card().querySelectorAll(".ctx-open")].filter((el) => el.offsetParent !== null);

  document.addEventListener("keydown", (e) => {
    const open = e.target.closest?.(".project-context .ctx-open");
    if (!open || e.isComposing) return;
    const node = nodeOf(open);
    if (window.Keys.is(e, "doc.rename")) {
      e.preventDefault();
      if (node.querySelector("[data-ctx-rename]")) startRename(node);
      return;
    }
    if (window.Keys.is(e, "doc.delete")) {
      e.preventDefault();
      node.querySelector(":scope > .ctx-row [data-ctx-delete]")?.click();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const folder = node.classList.contains("ctx-folder") ? node : null;
    const rows = shown();
    const at = rows.indexOf(open);
    const go = (el) => { if (el) { e.preventDefault(); el.focus(); } };
    switch (e.key) {
      case "ArrowDown": return go(rows[at + 1]);
      case "ArrowUp": return go(rows[at - 1]);
      case "Home": return go(rows[0]);
      case "End": return go(rows.at(-1));
      case "ArrowRight":
        if (!folder) return;
        e.preventDefault();
        if (!isOpen(folder)) fold(folder, true);
        else groupOf(folder).querySelector(".ctx-open")?.focus();
        return;
      case "ArrowLeft":
        e.preventDefault();
        if (folder && isOpen(folder)) fold(folder, false);
        else if (folderOf(node)) toggleOf(folderOf(node)).focus();
        return;
    }
  });

  /* ---- dragging a row into a folder, or out to the top ---- */

  let dragged = null; // {node, kind, id}
  let over = null; // the folder node, or the tree, it would land in
  let opening = null; // a folded folder held over opens after a moment

  const hover = (target) => {
    if (over === target) return;
    over?.classList.remove("is-drop-target");
    clearTimeout(opening);
    over = target;
    over?.classList.add("is-drop-target");
    if (over?.classList.contains("ctx-folder") && !isOpen(over)) {
      const folder = over;
      opening = setTimeout(() => fold(folder, true), 600);
    }
  };

  // Where a drop on this element lands: the folder it is in, or the top;
  // never into the dragged folder itself, nor one inside it.
  const dropTarget = (el) => {
    if (!dragged || !el?.closest?.("#project-context")) return null;
    const folder = el.closest(".ctx-folder");
    if (folder && dragged.node.contains(folder)) return null;
    return folder || card().querySelector("[data-ctx-root]");
  };

  document.addEventListener("dragstart", (e) => {
    const row = e.target.closest?.(".project-context .ctx-row[draggable='true']");
    if (!row) return;
    const node = nodeOf(row);
    dragged = node.classList.contains("ctx-folder")
      ? { node, kind: "folder", id: node.dataset.folder }
      : { node, kind: "doc", id: node.dataset.doc };
    e.dataTransfer.setData("text/plain", node.dataset.name);
    e.dataTransfer.effectAllowed = "move";
    requestAnimationFrame(() => node.classList.add("is-dragging"));
    card().classList.add("is-dragging-in");
  });

  document.addEventListener("dragover", (e) => {
    if (!dragged) return;
    const target = dropTarget(e.target);
    hover(target);
    if (!target) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  });

  document.addEventListener("drop", (e) => {
    if (!dragged) return;
    const target = dropTarget(e.target);
    const { node, kind, id } = dragged;
    if (!target) return;
    e.preventDefault();
    const to = target.dataset.folder ?? "top";
    if (to === (folderOf(node)?.dataset.folder ?? "top")) return;
    land(kind, node.dataset.name, to);
    post(`/ui/${kind === "folder" ? "folders" : "docs"}/${id}/place`, { folder: to });
  });

  document.addEventListener("dragend", () => {
    dragged?.node.classList.remove("is-dragging");
    card()?.classList.remove("is-dragging-in");
    dragged = null;
    hover(null);
  });

  /* ---- the tree drawn again: what just landed brought into view ---- */

  document.addEventListener("htmx:afterSettle", (e) => {
    if (e.detail.elt.id !== "project-context" || !landing) return;
    const { kind, name, folder } = landing;
    landing = null;
    const scope = folder ? card().querySelector(`.ctx-folder[data-folder="${folder}"] > .ctx-group`) : card().querySelector("[data-ctx-root]");
    const node = [...(scope?.querySelectorAll(`:scope > .ctx-${kind}`) || [])].find((n) => n.dataset.name.toLowerCase() === name?.toLowerCase());
    if (!node) return;
    node.querySelector(".ctx-open").focus();
    node.scrollIntoView({ block: "nearest" });
    const row = node.querySelector(":scope > .ctx-row");
    row.classList.add("is-landed");
    row.addEventListener("animationend", () => row.classList.remove("is-landed"), { once: true });
  });
})();
