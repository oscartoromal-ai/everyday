/* A chat with an agent (Nutrition's and Spending's with Claude, the agent
   window's with its agent): each composer is a form[data-chat], its log the
   element data-log names, and its agent data-name ("Claude" if none). A
   message goes to the agent, and its answer streams in as it is written,
   with what the agent is doing meanwhile ("Reading the plan"). The server
   sends newline-delimited JSON events; once the agent is done, the form's
   event (data-changed: nutrition:changed, money:changed, agent:changed)
   draws the chat and what the agent changed again from the server, the
   answer as Markdown. Enter sends, Shift+Enter starts a new line; Left and
   Right, outside the message, go a day (or a month) back or on, through
   shell.js. Listeners are on the document, so a composer drawn again (the
   agent window's, on a new chat) works as it lands. */
(() => {
  const element = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };

  const now = () => new Date().toTimeString().slice(0, 5);
  const nearBottom = (log) => log.scrollHeight - log.scrollTop - log.clientHeight < 48;
  const toBottom = (log) => { log.scrollTop = log.scrollHeight; };
  const logOf = (form) => document.getElementById(form.dataset.log);

  // Oscar's message, and the agent's answer to come, drawn at once.
  const draft = (form, log, text) => {
    log.querySelector(".chat-empty")?.remove();
    let list = log.querySelector(".chat-messages");
    if (!list) list = log.appendChild(element("ol", "chat-messages"));

    const mine = element("li", "chat-message from-oscar");
    const who = element("div", "chat-who", "You ");
    who.appendChild(element("span", "chat-time", now()));
    const words = element("div", "chat-text");
    const p = element("p");
    text.split("\n").forEach((line, i) => {
      if (i) p.appendChild(document.createElement("br"));
      p.appendChild(document.createTextNode(line));
    });
    words.appendChild(p);
    mine.append(who, words);

    const answer = element("li", "chat-message from-agent is-pending");
    const head = element("div", "chat-who", `${form.dataset.name || "Claude"} `);
    const status = head.appendChild(element("span", "chat-status", "Thinking…"));
    const said = element("p", "chat-streaming");
    const body = element("div", "chat-text");
    body.hidden = true;
    body.appendChild(said);
    answer.append(head, body);

    list.append(mine, answer);
    toBottom(log);
    return { mine, answer, status, said, body };
  };

  const setBusy = (form, busy) => {
    form._busy = busy;
    form.classList.toggle("is-busy", busy);
    const send = form.querySelector(".chat-send");
    if (send) send.disabled = busy;
  };

  const submit = async (form) => {
    const field = form.querySelector("textarea");
    const log = logOf(form);
    const text = field.value.trim();
    if (form._busy || !text || field.disabled || !log) return;
    setBusy(form, true);
    const view = draft(form, log, text);
    const body = new URLSearchParams(new FormData(form));
    body.set("message", text);
    field.value = "";

    let response;
    try {
      response = await fetch(form.action, {
        method: "POST",
        headers: { "X-CSRF": window.csrfToken() },
        body,
      });
    } catch {
      response = null;
    }
    if (!response || !response.ok) {
      let detail = "";
      try { detail = (await response.json()).detail; } catch { /* not JSON, or no response */ }
      const name = form.dataset.name || "Claude";
      window.toast(typeof detail === "string" && detail ? detail : `Could not reach ${name}. Try again?`);
      view.mine.remove();
      view.answer.remove();
      if (!field.value) field.value = text;
      setBusy(form, false);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const handle = (event) => {
      const follow = nearBottom(log);
      if (event.type === "text") {
        view.body.hidden = false;
        view.said.textContent += event.text;
      } else if (event.type === "status") {
        view.status.textContent = `${event.text}…`;
      }
      if (follow) toBottom(log);
    };
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) if (line.trim()) handle(JSON.parse(line));
      }
    } catch {
      // The answer goes on at the server; the chat asks after it until it lands.
      window.toast("Lost the connection. The answer shows once it is done.");
    }
    setBusy(form, false);
    // The chat as saved (the answer as Markdown) and what the agent changed.
    htmx.trigger(document.body, form.dataset.changed);
  };

  document.addEventListener("submit", (e) => {
    const form = e.target.closest?.("form[data-chat]");
    if (!form) return;
    e.preventDefault();
    submit(form);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    const form = e.target.closest?.("form[data-chat]");
    if (!form || e.target.tagName !== "TEXTAREA") return;
    e.preventDefault();
    submit(form);
  });

  // The latest of each chat in view, on arrival and each time it is drawn again.
  const settleLogs = (scope) => {
    scope.querySelectorAll?.("form[data-chat]").forEach((form) => {
      const log = logOf(form);
      if (log) toBottom(log);
    });
  };
  settleLogs(document);
  document.addEventListener("htmx:afterSwap", (e) => {
    const target = e.detail.target;
    if (target.id && document.querySelector(`form[data-chat][data-log="${target.id}"]`)) toBottom(target);
    settleLogs(target);
  });
})();
