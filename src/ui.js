export const UI_HTML = String.raw`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0b0e14">
<title>MEGA Direct</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='15' fill='%236ea8fe'/%3E%3Cpath d='M18 45V19h8l6 9 6-9h8v26h-7V31l-7 10-7-10v14z' fill='%230b0e14'/%3E%3C/svg%3E">
<style>
:root{color-scheme:dark;--bg:#0b0e14;--panel:#121722;--panel2:#171f2d;--line:#243149;--text:#e8eef8;--muted:#8e9bb2;--accent:#6ea8fe;--accent2:#8b5cf6;--danger:#ff7a7a}
*{box-sizing:border-box}
html,body{min-height:100%}
body{margin:0;background:radial-gradient(900px 500px at 20% -10%,#1a2742 0,rgba(11,14,20,0) 60%),var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;line-height:1.5}
a{color:var(--accent)}
.wrap{width:min(900px,100%);margin:0 auto;padding:48px 20px 56px}
.brand{display:flex;align-items:center;gap:14px;margin-bottom:8px}
.mark{width:44px;height:44px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#0b0e14;font-weight:800;font-size:22px;letter-spacing:-.5px;box-shadow:0 10px 30px rgba(110,168,254,.25)}
h1{font-size:clamp(24px,4vw,32px);line-height:1.1;margin:0;letter-spacing:-.03em}
.sub{color:var(--muted);margin:6px 0 26px;font-size:15px}
.panel,.card{background:linear-gradient(180deg,rgba(23,31,45,.96),rgba(18,23,34,.96));border:1px solid var(--line);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.28)}
.panel{padding:18px}
.lookup{display:flex;gap:10px;align-items:stretch}
.lookup .btn{height:48px}
.field{flex:1;min-width:0}
label.sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
input[type=text]{width:100%;height:48px;border-radius:12px;border:1px solid var(--line);background:#0d121b;color:var(--text);padding:0 14px;font-size:15px;outline:none;transition:border-color .15s,box-shadow .15s}
input[type=text]:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(110,168,254,.16)}
input[type=text]::placeholder{color:#5e6b82}
.btn{appearance:none;border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:11px;padding:0 16px;height:44px;font:inherit;font-size:14px;font-weight:650;display:inline-flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;cursor:pointer;transition:transform .12s,background .15s,border-color .15s,filter .15s;white-space:nowrap}
.btn:hover{background:#1d2738;border-color:#334565}
.btn:active{transform:translateY(1px)}
.btn:disabled{opacity:.65;cursor:wait}
.btn.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;color:#08101d}
.btn.primary:hover{filter:brightness(1.06)}
.btn.ghost{background:transparent}
.btn.small{height:34px;padding:0 11px;font-size:13px;border-radius:9px}
.row{display:flex;gap:9px;align-items:center;margin-top:10px;flex-wrap:wrap}
.hint{color:var(--muted);font-size:13px;margin:10px 0 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:#0d121b;border:1px solid var(--line);padding:1px 5px;border-radius:5px;font-size:.92em}
.status{min-height:20px;color:var(--muted);font-size:13px;margin:10px 0 0}
.card{margin-top:18px;padding:20px}
.card.error{border-color:rgba(255,122,122,.42);background:linear-gradient(180deg,rgba(255,122,122,.08),rgba(18,23,34,.96))}
.title{font-size:19px;line-height:1.35;margin:0;word-break:break-word;letter-spacing:-.01em}
.meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.chip{font-size:12px;color:#c1cde2;background:#1c2638;border:1px solid #2a3852;border-radius:999px;padding:3px 9px;white-space:nowrap}
.actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:16px}
.files{margin-top:18px;border-top:1px solid var(--line)}
.file-row{display:flex;gap:14px;align-items:center;padding:13px 0;border-bottom:1px solid var(--line)}
.file-row:last-child{border-bottom:0}
.file-main{flex:1;min-width:0}
.file-path{font-size:14px;word-break:break-word;overflow-wrap:anywhere}
.file-sub{display:flex;gap:7px;align-items:center;color:var(--muted);font-size:12px;margin-top:3px}
.dot{opacity:.55}
.file-actions{display:flex;gap:7px;flex-shrink:0}
.muted{color:var(--muted)}
.small{font-size:13px}
.empty{color:var(--muted);padding:16px 0}
.error-text{color:#ffc0c0;margin:10px 0 0;font-size:14px}
.footer{color:var(--muted);font-size:12px;text-align:center;margin-top:30px;line-height:1.6}
@media (max-width:620px){.wrap{padding:32px 14px 44px}.lookup{flex-direction:column}.lookup .btn{width:100%}.file-row{align-items:flex-start;flex-direction:column}.file-actions{width:100%}.file-actions .btn{flex:1}}
[hidden]{display:none!important}
</style>
</head>
<body>
<main class="wrap">
  <div class="brand">
    <div class="mark">M</div>
    <h1>MEGA Direct</h1>
  </div>
  <p class="sub">Public file and folder links to direct downloads.</p>
  <section class="panel">
    <form id="lookup-form" class="lookup" novalidate>
      <div class="field">
        <label class="sr" for="link">MEGA link</label>
        <input id="link" type="text" placeholder="https://mega.nz/file/...#key" autocomplete="off" spellcheck="false" autocapitalize="off">
      </div>
      <button id="lookup-submit" class="btn primary" type="submit">Get links</button>
    </form>
    <div class="row">
      <button id="paste" class="btn small ghost" type="button">Paste</button>
      <button id="reset" class="btn small ghost" type="button">Reset</button>
    </div>
    <p class="hint">Paste the complete link, including the part after <code>#</code>. Subfolders and files inside folders work too.</p>
    <p id="status" class="status" aria-live="polite"></p>
  </section>
  <div id="result" aria-live="polite" hidden></div>
  <p class="footer">Links are generated on demand and expire after about 20 minutes.</p>
</main>
<script>
(function () {
  "use strict";

  const form = document.getElementById("lookup-form");
  const input = document.getElementById("link");
  const submitButton = document.getElementById("lookup-submit");
  const pasteButton = document.getElementById("paste");
  const resetButton = document.getElementById("reset");
  const status = document.getElementById("status");
  const result = document.getElementById("result");

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function formatBytes(value) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = Number(value) || 0;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }
    const digits = unit === 0 ? 0 : size >= 100 ? 0 : size >= 10 ? 1 : 2;
    return size.toFixed(digits) + " " + units[unit];
  }

  function timeLeft(seconds) {
    const minutes = Math.round((Number(seconds) || 0) / 60);
    return minutes > 0 ? "expires in " + minutes + " min" : "";
  }

  function fallbackCopy(text, done) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); } catch (error) {}
    document.body.removeChild(area);
    done();
  }

  function copyText(text, button) {
    const original = button.textContent;
    const done = function () {
      button.textContent = "Copied";
      setTimeout(function () { button.textContent = original; }, 1200);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        fallbackCopy(text, done);
      });
    } else {
      fallbackCopy(text, done);
    }
  }

  function showResult(card) {
    result.replaceChildren(card);
    result.hidden = false;
  }

  function showError(error) {
    const card = make("section", "card error");
    card.appendChild(make("h2", "title", (error && error.code) || "Error"));
    card.appendChild(make("p", "error-text", (error && error.message) || "Something went wrong."));
    if (error && error.code === "missing_key") {
      card.appendChild(make("p", "hint", "Copy the complete MEGA link, including the part after #."));
    }
    showResult(card);
  }

  function addChip(parent, text) {
    if (!text) return;
    parent.appendChild(make("span", "chip", text));
  }

  function fileCard(data) {
    const card = make("section", "card");
    card.appendChild(make("h2", "title", data.name || "File"));
    const meta = make("div", "meta");
    addChip(meta, formatBytes(data.size));
    addChip(meta, data.ext ? data.ext.toUpperCase() : "");
    addChip(meta, timeLeft(data.expires_in));
    card.appendChild(meta);

    const actions = make("div", "actions");
    if (data.url) {
      const open = make("a", "btn primary", "Download");
      open.href = data.url;
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      actions.appendChild(open);
      const copy = make("button", "btn", "Copy URL");
      copy.type = "button";
      copy.addEventListener("click", function () { copyText(data.url, copy); });
      actions.appendChild(copy);
    } else {
      actions.appendChild(make("span", "muted small", "Direct URL unavailable."));
    }
    const json = make("button", "btn ghost", "Copy JSON");
    json.type = "button";
    json.addEventListener("click", function () { copyText(JSON.stringify(data, null, 2), json); });
    actions.appendChild(json);
    card.appendChild(actions);
    showResult(card);
  }

  function fileRow(file) {
    const row = make("div", "file-row");
    const main = make("div", "file-main");
    main.appendChild(make("div", "file-path", file.path || file.name || "File"));
    const sub = make("div", "file-sub");
    sub.appendChild(make("span", "", formatBytes(file.size)));
    if (file.ext) {
      sub.appendChild(make("span", "dot", "·"));
      sub.appendChild(make("span", "", file.ext.toUpperCase()));
    }
    main.appendChild(sub);
    row.appendChild(main);

    const actions = make("div", "file-actions");
    if (file.url) {
      const open = make("a", "btn small primary", "Open");
      open.href = file.url;
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      actions.appendChild(open);
      const copy = make("button", "btn small", "Copy");
      copy.type = "button";
      copy.addEventListener("click", function () { copyText(file.url, copy); });
      actions.appendChild(copy);
    } else {
      actions.appendChild(make("span", "muted small", "No URL"));
    }
    row.appendChild(actions);
    return row;
  }

  function folderCard(data) {
    const files = Array.isArray(data.files) ? data.files : [];
    const card = make("section", "card");
    card.appendChild(make("h2", "title", data.name || "Folder"));
    const meta = make("div", "meta");
    addChip(meta, files.length + (files.length === 1 ? " file" : " files"));
    addChip(meta, formatBytes(data.size));
    addChip(meta, timeLeft(data.expires_in));
    card.appendChild(meta);

    const urls = files.map(function (file) { return file.url; }).filter(Boolean);
    const actions = make("div", "actions");
    if (urls.length > 0) {
      const copyAll = make("button", "btn primary", "Copy all URLs");
      copyAll.type = "button";
      copyAll.addEventListener("click", function () { copyText(urls.join("\n"), copyAll); });
      actions.appendChild(copyAll);
    }
    const json = make("button", "btn ghost", "Copy JSON");
    json.type = "button";
    json.addEventListener("click", function () { copyText(JSON.stringify(data, null, 2), json); });
    actions.appendChild(json);
    card.appendChild(actions);

    const list = make("div", "files");
    if (files.length === 0) list.appendChild(make("div", "empty", "This folder is empty."));
    for (const file of files) list.appendChild(fileRow(file));
    card.appendChild(list);
    showResult(card);
  }

  function setBusy(busy) {
    submitButton.disabled = busy;
    submitButton.textContent = busy ? "Working..." : "Get links";
    status.textContent = busy ? "Contacting MEGA..." : "";
    if (busy) {
      result.hidden = true;
      result.replaceChildren();
    }
  }

  async function resolve(link) {
    const value = String(link || "").trim();
    if (!value) {
      showError({ code: "missing_url", message: "Paste a MEGA link first." });
      input.focus();
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("/", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: value }),
      });
      let data;
      try { data = await response.json(); } catch (error) { throw new Error("The worker returned an unreadable response."); }
      if (!data || typeof data !== "object") throw new Error("The worker returned an unexpected response.");
      if (!response.ok || data.error) {
        showError(data.error || { code: "http_" + response.status, message: "The request failed." });
        return;
      }
      if (data.kind === "folder") folderCard(data);
      else if (data.kind === "file") fileCard(data);
      else showError({ code: "bad_response", message: "The worker returned an unexpected response." });
    } catch (error) {
      showError({ code: "network", message: error && error.message ? error.message : "Could not reach the worker." });
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    resolve(input.value);
  });

  pasteButton.addEventListener("click", async function () {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        input.value = text.trim();
        input.focus();
      }
    } catch (error) {
      input.focus();
    }
  });

  resetButton.addEventListener("click", function () {
    input.value = "";
    result.hidden = true;
    result.replaceChildren();
    status.textContent = "";
    input.focus();
  });

  let initial = location.hash.length > 1 ? location.hash.slice(1) : "";
  if (initial && !/^https?:\/\//i.test(initial)) {
    try { initial = decodeURIComponent(initial); } catch (error) {}
  }
  if (initial) {
    input.value = initial;
    resolve(initial);
  } else {
    input.focus();
  }
})();
</script>
</body>
</html>`;

export function htmlResponse() {
  return new Response(UI_HTML, {
    status: 200,
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'X-Frame-Options': 'DENY',
      'Content-Security-Policy':
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
      Vary: 'Accept',
    },
  });
}
