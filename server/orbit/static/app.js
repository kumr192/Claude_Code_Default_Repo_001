// Orbit web UI. Plain JavaScript, no build step.
// Used by the desktop app (Electron) and by any browser on your Tailscale network.

const $ = (id) => document.getElementById(id);
const state = { token: null, chatId: null, lastMsgId: 0, models: [], seenApprovals: new Set(), wasRunning: {} };

function getToken() { try { return localStorage.getItem("orbit_token"); } catch { return null; } }
function setToken(t) { try { t ? localStorage.setItem("orbit_token", t) : localStorage.removeItem("orbit_token"); } catch {} }

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}`, ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) { showLogin("Token was not accepted."); throw new Error("unauthorized"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function toast(text) {
  const t = $("toast"); t.textContent = text; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 3500);
}

function notify(title, body) {
  if ("Notification" in window && Notification.permission === "granted") new Notification(title, { body });
}

// ---------- login ----------
function showLogin(err = "") {
  $("app").classList.add("hidden"); $("login").classList.remove("hidden"); $("loginErr").textContent = err;
}
$("tokenSave").onclick = async () => {
  state.token = $("tokenInput").value.trim(); setToken(state.token);
  try { await boot(); } catch (e) { if (e.message !== "unauthorized") showLogin(e.message); }
};
$("logout").onclick = () => { setToken(null); location.reload(); };

// ---------- views ----------
document.querySelectorAll(".nav").forEach((b) => (b.onclick = () => showView(b.dataset.view)));
function showView(name) {
  document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${name}`));
  if (name === "routines") loadRoutines();
  if (name === "approvals") loadApprovals();
  if (name === "settings") $("modelsText").value = state.models.join("\n");
}

function fillModelSelect(sel, value) {
  sel.innerHTML = "";
  for (const m of state.models) {
    const o = document.createElement("option");
    o.value = m; o.textContent = m === "auto" ? "Auto (Claude → Codex)" : m;
    sel.appendChild(o);
  }
  if (value) sel.value = value;
}

// ---------- chats ----------
async function loadChats() {
  const chats = await api("/api/chats");
  const list = $("chatList"); list.innerHTML = "";
  for (const c of chats) {
    const d = document.createElement("div");
    d.className = "chatitem" + (c.id === state.chatId ? " active" : "");
    if (c.running) { const dot = document.createElement("span"); dot.className = "dot"; d.appendChild(dot); }
    d.appendChild(document.createTextNode(c.title));
    d.onclick = () => openChat(c.id);
    list.appendChild(d);
    // Desktop notification when a background task finishes.
    if (state.wasRunning[c.id] && !c.running && c.id !== state.chatId) notify("Orbit: task finished", c.title);
    state.wasRunning[c.id] = !!c.running;
  }
}

async function openChat(id) {
  showView("chat");
  state.chatId = id; state.lastMsgId = 0;
  $("messages").innerHTML = "";
  await pollMessages();
  loadChats();
}

$("newChat").onclick = async () => {
  const c = await api("/api/chats", { method: "POST", body: { model: $("modelPick").value || "auto" } });
  await openChat(c.id);
  $("input").focus();
};

function renderText(el, text) {
  // Safe rendering: text only, with ``` code blocks as <pre>.
  const parts = text.split(/```[\w-]*\n?/);
  parts.forEach((p, i) => {
    if (i % 2) { const pre = document.createElement("pre"); pre.textContent = p; el.appendChild(pre); }
    else if (p) el.appendChild(document.createTextNode(p));
  });
}

function addMsg(m) {
  const box = $("messages");
  box.querySelector(".empty")?.remove();
  const d = document.createElement("div");
  d.className = `msg ${m.role}`;
  if (m.role === "tool") d.textContent = "› " + m.content;
  else renderText(d, m.content);
  if (m.role === "assistant" && m.model) {
    const meta = document.createElement("span"); meta.className = "meta"; meta.textContent = m.model; d.appendChild(meta);
  }
  box.appendChild(d);
}

async function pollMessages() {
  if (!state.chatId) return;
  const box = $("messages");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  const { chat, messages } = await api(`/api/chats/${state.chatId}/messages?after=${state.lastMsgId}`);
  $("chatTitle").textContent = chat.title;
  if (state.lastMsgId === 0) fillModelSelect($("modelPick"), chat.model);
  $("status").textContent = chat.running ? "● working…" : "";
  for (const m of messages) { addMsg(m); state.lastMsgId = m.id; }
  if (messages.length && (atBottom || state.lastMsgId === messages.at(-1).id)) box.scrollTop = box.scrollHeight;
}

$("composer").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("input").value.trim();
  if (!text) return;
  if (!state.chatId) {
    const c = await api("/api/chats", { method: "POST", body: { model: $("modelPick").value || "auto" } });
    state.chatId = c.id; state.lastMsgId = 0; $("messages").innerHTML = "";
  }
  try {
    await api(`/api/chats/${state.chatId}/messages`, { method: "POST", body: { text, model: $("modelPick").value } });
    $("input").value = "";
    await pollMessages(); loadChats();
  } catch (err) { toast(err.message); }
};
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); }
});

// ---------- computer view ----------
$("toggleComputer").onclick = () => {
  const panel = $("computer");
  const show = panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !show);
  if (show && !$("computerFrame").src) {
    if (!state.computerUrl) { toast("No computer URL set. See README."); return; }
    $("computerFrame").src = state.computerUrl; $("computerPop").href = state.computerUrl;
  }
};

// ---------- approvals ----------
async function loadApprovals() {
  const items = await api("/api/approvals?status=pending");
  const badge = $("apprBadge");
  badge.textContent = items.length; badge.classList.toggle("hidden", !items.length);
  for (const a of items) {
    if (!state.seenApprovals.has(a.id)) { state.seenApprovals.add(a.id); notify("Orbit needs your approval", `${a.tool}: ${a.detail}`); }
  }
  const list = $("approvalList");
  if ($("view-approvals").classList.contains("hidden")) return;
  list.innerHTML = items.length ? "" : '<p class="hint">Nothing waiting.</p>';
  for (const a of items) {
    const row = document.createElement("div"); row.className = "row";
    const info = document.createElement("div"); info.className = "info";
    const t = document.createElement("strong"); t.textContent = `${a.tool} · ${a.chat_title || ""}`;
    const d = document.createElement("div"); d.textContent = a.detail;
    info.append(t, d);
    const act = document.createElement("div"); act.className = "actions";
    const yes = document.createElement("button"); yes.className = "ok"; yes.textContent = "Approve";
    const no = document.createElement("button"); no.className = "no"; no.textContent = "Deny";
    yes.onclick = async () => { await api(`/api/approvals/${a.id}`, { method: "POST", body: { approve: true } }); loadApprovals(); };
    no.onclick = async () => { await api(`/api/approvals/${a.id}`, { method: "POST", body: { approve: false } }); loadApprovals(); };
    act.append(yes, no); row.append(info, act); list.appendChild(row);
  }
}

// ---------- routines ----------
async function loadRoutines() {
  fillModelSelect($("routineModel"), "auto");
  const items = await api("/api/routines");
  const list = $("routineList"); list.innerHTML = items.length ? "" : '<p class="hint">No routines yet.</p>';
  for (const r of items) {
    const row = document.createElement("div"); row.className = "row";
    const info = document.createElement("div"); info.className = "info";
    const t = document.createElement("strong"); t.textContent = `${r.name}  ·  ${r.cron}  ·  ${r.model}${r.enabled ? "" : "  · paused"}`;
    const d = document.createElement("div"); d.textContent = r.prompt;
    const n = document.createElement("div"); n.className = "hint";
    n.textContent = r.next_run ? "Next run: " + new Date(r.next_run * 1000).toLocaleString() : "";
    info.append(t, d, n);
    const act = document.createElement("div"); act.className = "actions";
    const mk = (label, cls, fn) => { const b = document.createElement("button"); b.className = cls; b.textContent = label; b.onclick = fn; act.appendChild(b); };
    mk("Run now", "ghost", async () => { const { chat_id } = await api(`/api/routines/${r.id}/run`, { method: "POST" }); openChat(chat_id); });
    mk(r.enabled ? "Pause" : "Resume", "ghost", async () => {
      await api(`/api/routines/${r.id}`, { method: "PUT", body: { ...r, enabled: !r.enabled } }); loadRoutines();
    });
    mk("Delete", "no", async () => { if (confirm("Delete this routine?")) { await api(`/api/routines/${r.id}`, { method: "DELETE" }); loadRoutines(); } });
    row.append(info, act); list.appendChild(row);
  }
}
$("routineForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/routines", { method: "POST", body: Object.fromEntries(f.entries()) });
    e.target.reset(); loadRoutines(); toast("Routine added");
  } catch (err) { toast(err.message); }
};

// ---------- settings ----------
$("modelsSave").onclick = async () => {
  const models = $("modelsText").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const res = await api("/api/models", { method: "PUT", body: models });
  state.models = res.models; fillModelSelect($("modelPick"), $("modelPick").value); toast("Saved");
};

// ---------- start ----------
async function boot() {
  const cfg = await api("/api/config");
  state.models = cfg.models; state.computerUrl = cfg.computer_url;
  fillModelSelect($("modelPick"), "auto");
  $("login").classList.add("hidden"); $("app").classList.remove("hidden");
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  await loadChats(); await loadApprovals();
  if (!boot.started) {
    boot.started = true;
    setInterval(() => pollMessages().catch(() => {}), 1200);
    setInterval(() => { loadChats().catch(() => {}); loadApprovals().catch(() => {}); }, 4000);
  }
}

state.token = getToken();
if (state.token) boot().catch((e) => { if (e.message !== "unauthorized") showLogin(e.message); });
else showLogin();
