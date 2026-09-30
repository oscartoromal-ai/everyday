/* Nutrition's chat (nutrition.html): a message goes to Claude, and its answer
   streams in as it is written, with what Claude is doing meanwhile ("Reading
   the plan"). The server sends newline-delimited JSON events; once Claude is
   done, the chat and the day's log are drawn again from the server
   (nutrition:changed), the answer as Markdown and the log as Claude left it.
   Enter sends, Shift+Enter starts a new line; Left and Right, outside the
   message, go a day back or on. */
(() => {
  const form = document.getElementById("chat-composer");
  if (!form) return;
  const field = form.querySelector("textarea");
  const send = form.querySelector(".chat-send");
  const chatLog = document.getElementById("chat-log");
  let busy = false;

  const nearBottom = () => chatLog.scrollHeight - chatLog.scrollTop - chatLog.clientHeight < 48;
  const toBottom = () => { chatLog.scrollTop = chatLog.scrollHeight; };

  const element = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };

  const now = () => new Date().toTimeString().slice(0, 5);

  // Oscar's message, and Claude's answer to come, drawn at once.
  const draft = (text) => {
    chatLog.querySelector(".chat-empty")?.remove();
    let list = chatLog.querySelector(".chat-messages");
    if (!list) list = chatLog.appendChild(element("ol", "chat-messages"));

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

    const answer = element("li", "chat-message from-claude is-pending");
    const head = element("div", "chat-who", "Claude ");
    const status = head.appendChild(element("span", "chat-status", "Thinking…"));
    const said = element("p", "chat-streaming");
    const body = element("div", "chat-text");
    body.hidden = true;
    body.appendChild(said);
    answer.append(head, body);

    list.append(mine, answer);
    toBottom();
    return { mine, answer, status, said, body };
  };

  const settle = () => {
    busy = false;
    form.classList.remove("is-busy");
    send.disabled = false;
    // The chat as saved (the answer as Markdown) and the log as Claude left it.
    htmx.trigger(document.body, "nutrition:changed");
  };

  const submit = async () => {
    const text = field.value.trim();
    if (busy || !text) return;
    busy = true;
    form.classList.add("is-busy");
    send.disabled = true;
    const view = draft(text);
    field.value = "";

    let response;
    try {
      response = await fetch(form.action, {
        method: "POST",
        headers: { "X-CSRF": window.csrfToken() },
        body: new URLSearchParams({ message: text }),
      });
    } catch {
      response = null;
    }
    if (!response || !response.ok) {
      let detail = "";
      try { detail = (await response.json()).detail; } catch { /* not JSON, or no response */ }
      window.toast(typeof detail === "string" && detail ? detail : "Could not reach Claude. Try again?");
      view.mine.remove();
      view.answer.remove();
      if (!field.value) field.value = text;
      busy = false;
      form.classList.remove("is-busy");
      send.disabled = false;
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const handle = (event) => {
      const follow = nearBottom();
      if (event.type === "text") {
        view.body.hidden = false;
        view.said.textContent += event.text;
      } else if (event.type === "status") {
        view.status.textContent = `${event.text}…`;
      }
      if (follow) toBottom();
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
      window.toast("Lost the connection. Claude's answer shows once it is done.");
    }
    settle();
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submit();
  });
  field.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    submit();
  });

  // Left and Right, outside the message, change the day.
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (e.target.closest?.("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]")) return;
    const link = document.querySelector(`[data-day-step="${e.key === "ArrowLeft" ? "prev" : "next"}"]`);
    if (!link) return;
    e.preventDefault();
    link.click();
  });

  // The latest of the chat in view, on arrival and each time it is drawn again.
  toBottom();
  chatLog.addEventListener("htmx:afterSwap", toBottom);
})();
