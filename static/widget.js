/*
 * Support chat widget. Add ONE line to any website (Shopify, WooCommerce, ...):
 *
 *   <script src="https://YOUR-SERVER/widget.js" data-title="Help" data-color="#2f6f5e" defer></script>
 *
 * Optional attributes: data-api (defaults to the server the script came from),
 * data-title, data-color, data-greeting.
 */
(function () {
  if (window.__supportWidgetLoaded) return;
  window.__supportWidgetLoaded = true;

  var script = document.currentScript;
  var API = (script.getAttribute("data-api") || new URL(script.src).origin).replace(/\/$/, "");
  var TITLE = script.getAttribute("data-title") || "Customer support";
  var COLOR = script.getAttribute("data-color") || "#2f6f5e";
  var GREETING = script.getAttribute("data-greeting") ||
    "Hi! I can help with delivery, returns, products or your order status. What can I do for you?";
  var KEY = "support_widget_session";

  function store(get, val) {
    try { return get ? localStorage.getItem(KEY) : localStorage.setItem(KEY, val); } catch (e) { return null; }
  }

  var css = "" +
    ".sw-btn{position:fixed;right:20px;bottom:20px;width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;" +
    "background:" + COLOR + ";color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.2);z-index:2147483000;display:flex;align-items:center;justify-content:center}" +
    ".sw-btn svg{width:28px;height:28px}" +
    ".sw-panel{position:fixed;right:20px;bottom:90px;width:360px;max-width:calc(100vw - 32px);height:520px;max-height:calc(100vh - 120px);" +
    "background:#fff;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.22);display:none;flex-direction:column;overflow:hidden;" +
    "z-index:2147483000;font:14px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1d1d1f}" +
    ".sw-panel.open{display:flex}" +
    ".sw-head{background:" + COLOR + ";color:#fff;padding:14px 16px;font-weight:600;display:flex;justify-content:space-between;align-items:center}" +
    ".sw-head button{background:none;border:0;color:#fff;font-size:22px;cursor:pointer;line-height:1}" +
    ".sw-log{flex:1;overflow-y:auto;padding:14px;background:#f6f7f8;display:flex;flex-direction:column;gap:8px}" +
    ".sw-msg{max-width:85%;padding:9px 12px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word}" +
    ".sw-bot{background:#fff;border:1px solid #e3e5e8;align-self:flex-start;border-bottom-left-radius:4px}" +
    ".sw-user{background:" + COLOR + ";color:#fff;align-self:flex-end;border-bottom-right-radius:4px}" +
    ".sw-bot a{color:" + COLOR + "}" +
    ".sw-note{align-self:center;font-size:12px;color:#5f6368;background:#e9f3ef;padding:4px 10px;border-radius:10px}" +
    ".sw-typing{color:#80868b;font-style:italic}" +
    ".sw-form{display:flex;border-top:1px solid #e3e5e8;background:#fff}" +
    ".sw-form input{flex:1;border:0;padding:14px;font:inherit;outline:none;min-width:0}" +
    ".sw-form button{border:0;background:none;color:" + COLOR + ";font-weight:600;padding:0 16px;cursor:pointer}" +
    ".sw-form button:disabled{opacity:.4;cursor:default}" +
    "@media (max-width:480px){.sw-panel{right:16px;left:16px;width:auto;bottom:86px}}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  var btn = document.createElement("button");
  btn.className = "sw-btn";
  btn.setAttribute("aria-label", "Open support chat");
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

  var panel = document.createElement("div");
  panel.className = "sw-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", TITLE);
  panel.innerHTML =
    '<div class="sw-head"><span></span><button aria-label="Close">&times;</button></div>' +
    '<div class="sw-log" aria-live="polite"></div>' +
    '<form class="sw-form"><input type="text" maxlength="2000" placeholder="Type your message..." aria-label="Message">' +
    '<button type="submit">Send</button></form>';
  panel.querySelector(".sw-head span").textContent = TITLE;

  document.body.appendChild(panel);
  document.body.appendChild(btn);

  var log = panel.querySelector(".sw-log");
  var form = panel.querySelector("form");
  var input = form.querySelector("input");
  var send = form.querySelector("button");
  var greeted = false;

  // Safe rendering: text only, with URLs turned into links (no innerHTML).
  function addMessage(text, who) {
    var el = document.createElement("div");
    el.className = "sw-msg " + (who === "user" ? "sw-user" : "sw-bot");
    var parts = String(text).split(/(https?:\/\/[^\s)]+)/g);
    parts.forEach(function (part) {
      if (/^https?:\/\//.test(part)) {
        var a = document.createElement("a");
        a.href = part; a.textContent = part; a.target = "_blank"; a.rel = "noopener noreferrer";
        el.appendChild(a);
      } else if (part) {
        el.appendChild(document.createTextNode(part));
      }
    });
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function addNote(text) {
    var el = document.createElement("div");
    el.className = "sw-note";
    el.textContent = text;
    log.appendChild(el);
  }

  function toggle(open) {
    panel.classList.toggle("open", open);
    if (open && !greeted) { addMessage(GREETING, "bot"); greeted = true; }
    if (open) input.focus();
  }
  btn.addEventListener("click", function () { toggle(!panel.classList.contains("open")); });
  panel.querySelector(".sw-head button").addEventListener("click", function () { toggle(false); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    addMessage(text, "user");
    input.value = "";
    send.disabled = true;
    var typing = addMessage("Typing...", "bot");
    typing.classList.add("sw-typing");

    fetch(API + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: store(true) }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data.detail || "Something went wrong");
          return data;
        });
      })
      .then(function (data) {
        typing.remove();
        store(false, data.session_id);
        addMessage(data.reply, "bot");
        if (data.escalated) addNote("Passed to our team - ticket " + data.ticket_id);
      })
      .catch(function (err) {
        typing.remove();
        addMessage((err && err.message) || "Sorry, I couldn't connect. Please try again.", "bot");
      })
      .finally(function () { send.disabled = false; input.focus(); });
  });
})();
