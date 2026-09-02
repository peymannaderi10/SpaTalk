/* SpaTalk web chat widget (text-channels plan, Task B4).
 *
 * One file, no build step, no third-party assets: the only external script it ever loads is
 * Cloudflare Turnstile, and only when the tenant's config carries a site key. Everything is
 * inline, the styling follows the visitor's colour scheme, and the accent colour comes from
 * the install snippet (data-accent) so a tenant can match its site without a code change.
 *
 * Install (docs/runbooks/widget-install.md):
 *   <script src="https://api.example.com/widget.js" data-tenant="skincentrix" defer></script>
 */
(function () {
  "use strict";

  var script =
    document.currentScript ||
    (function () {
      var all = document.getElementsByTagName("script");
      return all[all.length - 1];
    })();
  if (!script) return;

  var tenant = script.getAttribute("data-tenant") || "";
  if (!tenant) return;
  var api = new URL(script.src, window.location.href).origin;
  var fallbackBase = script.getAttribute("data-fallback") || api;
  var accent = script.getAttribute("data-accent") || "";
  var label = script.getAttribute("data-label") || "Chat with us";

  var MAX_RECONNECTS = 3;
  var session = newSession();
  var config = null;
  var socket = null;
  var attempts = 0;
  var ended = false;
  var showingForm = false;
  var root, panel, list, input, form, button, statusLine;

  function newSession() {
    try {
      if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    } catch (e) {
      /* fall through to the random id below */
    }
    return "s-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function styles() {
    return [
      ".st-root{position:fixed;right:16px;bottom:16px;z-index:2147483000;",
      "font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#111827}",
      ".st-btn{border:0;border-radius:999px;padding:12px 18px;cursor:pointer;color:#fff;",
      "background:var(--st-accent);box-shadow:0 6px 24px rgba(0,0,0,.25);font:inherit}",
      ".st-panel{display:none;flex-direction:column;width:min(360px,calc(100vw - 32px));",
      "height:min(520px,calc(100vh - 96px));background:#fff;border-radius:14px;overflow:hidden;",
      "box-shadow:0 12px 40px rgba(0,0,0,.28);margin-bottom:10px}",
      ".st-open .st-panel{display:flex}",
      ".st-head{background:var(--st-accent);color:#fff;padding:12px 14px;display:flex;",
      "justify-content:space-between;align-items:center;gap:8px}",
      ".st-head b{font-weight:600}",
      ".st-close{background:transparent;border:0;color:#fff;font-size:20px;cursor:pointer;",
      "line-height:1}",
      ".st-list{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}",
      ".st-msg{max-width:85%;padding:8px 11px;border-radius:12px;white-space:pre-wrap;",
      "word-wrap:break-word}",
      ".st-them{background:#f1f5f9;align-self:flex-start}",
      ".st-me{background:var(--st-accent);color:#fff;align-self:flex-end}",
      ".st-staff{background:#fef3c7;align-self:flex-start}",
      ".st-status{padding:0 12px 8px;font-size:13px;opacity:.7;min-height:18px}",
      ".st-form{display:flex;gap:6px;padding:10px;border-top:1px solid #e5e7eb}",
      ".st-form input,.st-form textarea{flex:1;font:inherit;padding:9px 10px;",
      "border:1px solid #d1d5db;border-radius:9px;background:#fff;color:inherit}",
      ".st-form button{border:0;border-radius:9px;padding:9px 14px;cursor:pointer;color:#fff;",
      "background:var(--st-accent);font:inherit}",
      ".st-fallback{display:flex;flex-direction:column;gap:8px;padding:12px;",
      "border-top:1px solid #e5e7eb}",
      ".st-fallback textarea{min-height:70px;resize:vertical}",
      "@media (prefers-color-scheme: dark){",
      ".st-root{color:#e5e7eb}.st-panel{background:#0b1220}",
      ".st-them{background:#1f2937;color:#e5e7eb}.st-staff{background:#3f3213;color:#fde68a}",
      ".st-form,.st-fallback{border-top-color:#1f2937}",
      ".st-form input,.st-form textarea{background:#0b1220;color:#e5e7eb;border-color:#334155}}"
    ].join("");
  }

  function mount() {
    root = el("div", "st-root");
    root.style.setProperty("--st-accent", accent || (config && config.accent) || "#0f766e");

    panel = el("div", "st-panel");
    var head = el("div", "st-head");
    head.appendChild(el("b", null, (config && config.name) || label));
    var close = el("button", "st-close", "×");
    close.setAttribute("aria-label", "Close chat");
    close.addEventListener("click", toggle);
    head.appendChild(close);

    list = el("div", "st-list");
    list.setAttribute("role", "log");
    statusLine = el("div", "st-status", "");

    form = el("form", "st-form");
    input = el("input");
    input.setAttribute("placeholder", "Type your message");
    input.setAttribute("aria-label", "Your message");
    input.setAttribute("autocomplete", "off");
    var send = el("button", null, "Send");
    send.type = "submit";
    form.appendChild(input);
    form.appendChild(send);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = input.value.trim();
      if (!text) return;
      input.value = "";
      say("st-me", text);
      sendMessage(text);
    });

    panel.appendChild(head);
    panel.appendChild(list);
    panel.appendChild(statusLine);
    panel.appendChild(form);

    button = el("button", "st-btn", label);
    button.addEventListener("click", toggle);

    var style = el("style", null, styles());
    root.appendChild(style);
    root.appendChild(panel);
    root.appendChild(button);
    document.body.appendChild(root);
  }

  function say(kind, text) {
    var node = el("div", "st-msg " + kind, text);
    list.appendChild(node);
    list.scrollTop = list.scrollHeight;
    return node;
  }

  function status(text) {
    if (statusLine) statusLine.textContent = text || "";
  }

  function toggle() {
    if (!root) return;
    var open = root.classList.toggle("st-open");
    if (open) {
      if (!socket && !showingForm) connect();
      if (input) input.focus();
    }
  }

  function socketUrl(token) {
    var base = api.replace(/^http/, "ws");
    return (
      base +
      "/chat/ws?tenant=" +
      encodeURIComponent(tenant) +
      "&session=" +
      encodeURIComponent(session) +
      "&turnstile=" +
      encodeURIComponent(token || "")
    );
  }

  function connect() {
    challenge(function (token) {
      var ws;
      try {
        ws = new WebSocket(socketUrl(token));
      } catch (e) {
        return giveUp();
      }
      socket = ws;
      ws.onopen = function () {
        attempts = 0;
        status("");
      };
      ws.onmessage = function (event) {
        var frame;
        try {
          frame = JSON.parse(event.data);
        } catch (e) {
          return;
        }
        if (frame.type === "typing") return status("…");
        status("");
        if (frame.type === "reply") say("st-them", frame.text);
        else if (frame.type === "staff") say("st-staff", frame.text);
        else if (frame.type === "ended") {
          ended = true;
          if (input) input.disabled = true;
        }
      };
      ws.onclose = function (event) {
        socket = null;
        if (ended) return;
        if (event && event.code === 4429) {
          status("Too many messages just now. Please try again in a minute.");
          return giveUp();
        }
        attempts += 1;
        if (attempts > MAX_RECONNECTS) return giveUp();
        status("Reconnecting…");
        window.setTimeout(connect, 800 * attempts);
      };
      ws.onerror = function () {
        try {
          ws.close();
        } catch (e) {
          /* onclose handles the retry */
        }
      };
    });
  }

  function sendMessage(text) {
    if (!socket || socket.readyState !== 1) return giveUp();
    socket.send(JSON.stringify({ type: "message", text: text }));
  }

  function giveUp() {
    if (showingForm) return;
    showingForm = true;
    if (socket) {
      try {
        socket.close();
      } catch (e) {
        /* already closing */
      }
      socket = null;
    }
    if (form) form.style.display = "none";
    status("");
    say("st-them", "I can't reach the assistant right now. Leave your details and the team will come back to you.");

    var box = el("form", "st-fallback");
    var name = el("input");
    name.setAttribute("placeholder", "Your name");
    name.setAttribute("aria-label", "Your name");
    var contact = el("input");
    contact.setAttribute("placeholder", "Phone or email");
    contact.setAttribute("aria-label", "Phone or email");
    contact.required = true;
    var message = el("textarea");
    message.setAttribute("placeholder", "How can we help?");
    message.setAttribute("aria-label", "How can we help?");
    var submit = el("button", null, "Send to the team");
    submit.type = "submit";
    box.appendChild(name);
    box.appendChild(contact);
    box.appendChild(message);
    box.appendChild(submit);
    box.addEventListener("submit", function (e) {
      e.preventDefault();
      submit.disabled = true;
      postFallback(name.value, contact.value, message.value, box);
    });
    panel.appendChild(box);
  }

  function postFallback(name, contact, message, box) {
    var body = {
      tenant_id: tenant,
      name: name || "",
      contact: contact || "",
      message: message || "",
      session: session
    };
    var request = new XMLHttpRequest();
    request.open("POST", fallbackBase + "/chat/fallback", true);
    request.setRequestHeader("Content-Type", "application/json");
    request.onreadystatechange = function () {
      if (request.readyState !== 4) return;
      box.parentNode.removeChild(box);
      if (request.status >= 200 && request.status < 300) {
        say("st-them", "Thanks. The team has your message and will get back to you.");
      } else {
        say("st-them", "That did not go through. Please call the clinic instead.");
      }
    };
    request.send(JSON.stringify(body));
  }

  function challenge(done) {
    var siteKey = config && config.turnstile_site_key;
    if (!siteKey) return done("");
    if (window.turnstile) return render(siteKey, done);
    var holder = document.getElementById("st-turnstile-loader");
    if (!holder) {
      holder = el("script");
      holder.id = "st-turnstile-loader";
      holder.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      holder.async = true;
      holder.defer = true;
      document.head.appendChild(holder);
    }
    var waited = 0;
    var timer = window.setInterval(function () {
      waited += 1;
      if (window.turnstile) {
        window.clearInterval(timer);
        render(siteKey, done);
      } else if (waited > 40) {
        window.clearInterval(timer);
        done("");
      }
    }, 100);
  }

  function render(siteKey, done) {
    var holder = el("div");
    holder.style.display = "none";
    document.body.appendChild(holder);
    try {
      window.turnstile.render(holder, {
        sitekey: siteKey,
        size: "invisible",
        callback: function (token) {
          done(token);
        },
        "error-callback": function () {
          done("");
        }
      });
    } catch (e) {
      done("");
    }
  }

  function start() {
    var request = new XMLHttpRequest();
    request.open("GET", api + "/widget/" + encodeURIComponent(tenant) + "/config", true);
    request.onreadystatechange = function () {
      if (request.readyState !== 4) return;
      if (request.status >= 200 && request.status < 300) {
        try {
          config = JSON.parse(request.responseText);
        } catch (e) {
          config = null;
        }
      }
      mount();
      if (config && config.greeting) say("st-them", config.greeting);
    };
    request.send();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
