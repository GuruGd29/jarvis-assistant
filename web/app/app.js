// Jarvis web app. One page; views are drawn from state and re-drawn on change.
// Everything from the server is escaped before it reaches the page.

// ---------- helpers ----------
const $ = sel => document.querySelector(sel);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const isTouch = matchMedia("(pointer: coarse)").matches;
const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const inrFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const inrRound = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr = n => `₹${inrFmt.format(Number(n) || 0)}`;
const inr0 = n => `₹${inrRound.format(Number(n) || 0)}`;
const todayISO = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

function dayLabel(iso) {
  const d = new Date(`${iso}T00:00:00`);
  const diff = Math.round((d - new Date(`${todayISO()}T00:00:00`)) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  const year = d.getFullYear() === new Date().getFullYear() ? {} : { year: "numeric" };
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", ...year });
}
// Inside a sentence: "today", "tomorrow", "on Thu, 5 Nov".
function dayInSentence(iso) {
  const label = dayLabel(iso);
  return ["Today", "Tomorrow", "Yesterday"].includes(label) ? label.toLowerCase() : `on ${label}`;
}
function ago(iso) {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
function change(now, before) {
  if (!before || before < 1000) return "";
  if (now >= 3 * before) return `×${Math.round(now / before)}`;
  const pct = Math.round(((now - before) / before) * 100);
  return `${pct >= 0 ? "↑" : "↓"} ${Math.abs(pct)}%`;
}

// Small, safe Markdown: text is escaped first, then **bold**, *italic*, `code`, links, lists and headings.
function md(src) {
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  const out = [];
  let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of String(src || "").split("\n")) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^#{1,4}\s+(.*)/))) { close(); out.push(`<h3>${inline(m[1])}</h3>`); }
    else if (!line.trim()) { close(); }
    else { close(); out.push(`<p>${inline(line)}</p>`); }
  }
  close();
  return out.join("");
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  let res;
  try { res = await fetch(path, init); } catch { setOffline(true); throw new Error("Can't reach Jarvis. Check your Wi-Fi or VPN."); }
  setOffline(false);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
  return data;
}
function setOffline(on) { const el = $("#offline"); if (el) el.classList.toggle("show", on); }
let toastTimer;
function toast(msg) {
  const el = $("#toast"); el.textContent = msg; el.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

// ---------- icons ----------
const sv = (d, w = 1.8) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const I = {
  chat: sv('<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12Z"/>'),
  today: sv('<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'),
  money: sv('<path d="M7 5h10M7 9h10M7 5c4 0 6 1.6 6 4s-2 4-6 4h-.5L14 20"/>'),
  more: sv('<rect x="4" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6"/>'),
  menu: sv('<path d="M4 8h16M4 16h11"/>', 2), edit: sv('<path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6M17.5 3.5l3 3L12 15H9v-3z"/>', 1.9),
  send: sv('<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/>', 2.3), stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/></svg>',
  copy: sv('<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'),
  speak: sv('<path d="M4 9.5v5h3.5L12 18V6L7.5 9.5zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>'),
  redo: sv('<path d="M19 8a7.5 7.5 0 1 0 1 5M19 3.5V8h-4.5"/>'), ok: sv('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 2.4),
  spin: sv('<path d="M12 3a9 9 0 1 0 9 9"/>', 2.2), trash: sv('<path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13"/>'),
  back: sv('<path d="M15 5l-7 7 7 7"/>', 2.2), chev: sv('<path d="M9 5l7 7-7 7"/>', 2.2),
  pill: sv('<rect x="3" y="8" width="18" height="8" rx="4" transform="rotate(-35 12 12)"/><path d="M9.5 8.7l5 6.6"/>'),
  renew: sv('<path d="M19 8a7.5 7.5 0 0 0-13.5 1M5 16a7.5 7.5 0 0 0 13.5-1M19 3.5V8h-4.5M5 20.5V16h4.5"/>'),
  brain: sv('<path d="M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-1.5 5.5A3 3 0 0 0 9 18v1.5M15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 1.5 5.5A3 3 0 0 1 15 18v1.5M9 4.5a3 3 0 0 1 6 0V19.5"/>'),
  file: sv('<path d="M6 3h8l4 4v14H6zM14 3v4h4"/>'), bell: sv('<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0"/>'),
  inbox: sv('<path d="M4 13l2.5-8h11L20 13v6H4zM4 13h5l1 2h4l1-2h5"/>'), share: sv('<path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M5 12v7.5h14V12"/>'),
  list: sv('<path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/>', 2.2),
};
const KIND_LABEL = { reminders: "Reminder", renewals: "Bills & renewals", problems: "Needs attention", reports: "Report", replies: "Chat reply" };

// ---------- state ----------
const S = {
  route: "chat", chatId: null, chats: [], msgs: [], streaming: null, drawer: false,
  today: null, todayErr: null, iphone: null, money: {}, period: "week", moneyErr: null,
  more: null, settings: null, activity: null, unread: 0, pushState: "unknown",
};

// ---------- shell ----------
document.getElementById("app").innerHTML = `
  <div id="view"></div>
  <nav class="tabbar frost" id="tabbar" aria-label="Main"></nav>
  <div class="scrim" id="scrim" data-act="drawer-close"></div>
  <aside class="drawer" id="drawer" aria-label="Chats"></aside>
  <div class="toast" id="toast" role="status"></div>
  <div class="offline" id="offline">Offline · can't reach Jarvis</div>`;

function renderTabs() {
  const tabs = [["chat", "Chat"], ["today", "Today"], ["money", "Money"], ["more", "More"]];
  const main = ["settings", "activity", "renewals"].includes(S.route) ? "more" : S.route;
  const todayBadge = S.today ? S.today.tasks.filter(t => !t.done && t.due_on && t.due_on <= todayISO()).length
    + S.today.medicines.filter(m => m.past && m.status === "due").length : 0;
  $("#tabbar").innerHTML = tabs.map(([k, n]) => {
    const badge = k === "today" && todayBadge ? todayBadge : k === "more" && S.unread ? S.unread : 0;
    return `<button class="tab ${k === main ? "on" : ""}" data-act="go" data-v="${k}" aria-label="${n}" ${k === main ? 'aria-current="page"' : ""}>
      ${I[k]}${badge ? `<span class="badge">${badge > 9 ? "9+" : badge}</span>` : ""}<span>${n}</span></button>`;
  }).join("");
}

function navigate(hash, replace = false) {
  if (location.hash === hash) { route(); return; }
  if (replace) { history.replaceState(null, "", hash); route(); } else location.hash = hash;
}
function route() {
  const [name, arg] = location.hash.replace(/^#/, "").split("/");
  const known = ["chat", "today", "money", "more", "settings", "activity", "renewals"];
  S.route = known.includes(name) ? name : "chat";
  if (S.route === "chat") openChat(arg || null);
  else { render(); load(S.route); }
}

function render(animate = true) {
  const views = { chat: viewChat, today: viewToday, money: viewMoney, more: viewMore, settings: viewSettings, activity: viewActivity, renewals: viewRenewals };
  $("#view").innerHTML = views[S.route]();
  if (animate) { const sc = $("#view .scroll"); if (sc) sc.classList.add("slide"); }
  renderTabs();
  if (S.route === "chat") afterChatRender();
}

async function load(name) {
  try {
    if (name === "today") { S.today = await api("/api/today"); S.todayErr = null; loadIphone(); }
    if (name === "money") { // keep each answer under the period it was asked for, even if they arrive out of order
      const period = S.period;
      S.money[period] = await api(`/api/money?period=${period}`); S.moneyErr = null;
    }
    if (name === "more") { S.more = await api("/api/more"); await loadActivity(false); }
    if (name === "settings") { S.settings = await api("/api/settings"); await refreshPushState(); }
    if (name === "activity") { S.activity = await api("/api/activity", { method: "POST" }); S.unread = 0; }
    if (name === "renewals" && !S.today) { S.today = await api("/api/today"); }
  } catch (e) {
    if (name === "today") S.todayErr = e.message;
    else if (name === "money") S.moneyErr = e.message;
    else toast(e.message);
  }
  if (S.route === name) render(false);
}
async function loadActivity(markRead) {
  const list = await api("/api/activity", markRead ? { method: "POST" } : {});
  S.unread = list.filter(a => !a.read_at).length;
  return list;
}
async function loadIphone() {
  try { S.iphone = await api("/api/iphone-reminders"); } catch (e) { S.iphone = { available: false, reason: e.message }; }
  if (S.route === "today") render(false);
}

// ---------- chat ----------
async function openChat(id) {
  S.drawer = false;
  if (id !== S.chatId || !id) {
    S.chatId = id; S.msgs = [];
    if (id) {
      render();
      try { S.msgs = (await api(`/api/chats/${encodeURIComponent(id)}`)).messages; }
      catch (e) { toast(e.message); S.chatId = null; history.replaceState(null, "", "#chat"); }
    }
  }
  render();
  api("/api/chats").then(list => { S.chats = list; renderDrawer(); }).catch(() => {});
  refreshChat();
}

// A reply that was stopped or cut off (iPhone ends connections when you leave the app) still finishes on
// the Mac; fetch the saved chat again until the answer is there.
async function refreshChat() {
  const id = S.chatId, last = S.msgs[S.msgs.length - 1];
  if (!id || S.streaming || !last || last.role !== "assistant" || !last.error) return false;
  try {
    const fresh = (await api(`/api/chats/${encodeURIComponent(id)}`)).messages;
    if (S.chatId !== id || S.streaming) return false;
    if (fresh.length && fresh[fresh.length - 1].role === "assistant") {
      S.msgs = fresh;
      if (S.route === "chat") render(false);
      return true;
    }
  } catch { /* offline: try again later */ }
  return false;
}
function watchForReply(id) {
  let tries = 0;
  const timer = setInterval(async () => {
    tries += 1;
    if (S.chatId !== id || tries > 36 || await refreshChat()) clearInterval(timer);
  }, 5000);
}

function msgHtml(m, i) {
  if (m.role === "user") return `<div class="u">${esc(m.text)}</div>`;
  const tools = (m.tools || []).map((t, k) => {
    const live = m.pending && k === m.tools.length - 1 && !m.text;
    return `<div class="tool ${live ? "live" : ""}">${live ? I.spin : I.ok} ${esc(t)}</div>`;
  }).join("");
  const body = m.error ? `<div class="err">${esc(m.error)}</div>`
    : m.text ? md(m.text) : m.pending ? `<div class="dots" aria-label="Jarvis is replying"><i></i><i></i><i></i></div>` : "";
  const acts = !m.pending && !m.error && m.text ? `<div class="acts">
      <button data-act="copy" data-i="${i}" aria-label="Copy">${I.copy}</button>
      <button data-act="speak" data-i="${i}" aria-label="Read aloud">${I.speak}</button>
      ${i === S.msgs.length - 1 ? `<button data-act="retry" aria-label="Ask again">${I.redo}</button>` : ""}</div>`
    : m.error ? `<div class="acts"><button data-act="retry" aria-label="Try again">${I.redo}</button></div>` : "";
  return `<div class="a">${tools ? `<div class="tools">${tools}</div>` : ""}${body}${acts}</div>`;
}

function viewChat() {
  const title = S.chatId ? (S.chats.find(c => c.id === S.chatId)?.title || "Jarvis") : "Jarvis";
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const welcome = `<div class="welcome"><h2>${hello}, Guru.</h2><p>Ask about your day, money, bills, health records or anything else, in English or Tamil.</p></div>`;
  const sugg = !S.msgs.length ? `<div class="sugg">
      <button data-act="ask" data-v="Plan my day: events, tasks, bills and medicines.">Plan my day<small>events, tasks, bills</small></button>
      <button data-act="ask" data-v="How much did I spend this week, by category?">This week's spending<small>by category</small></button>
      <button data-act="ask" data-v="Which bills or renewals are coming up?">Renewals<small>next 30 days</small></button>
      <button data-act="ask" data-v="Do I have any unread important emails?">Email<small>unread & important</small></button></div>` : "";
  return `<section class="view chat">
    <div class="cbar"><button class="ib" data-act="drawer-open" aria-label="Chats">${I.menu}</button>
      <div class="ttl"><b>${esc(title)}</b><span>Qwen3 4B · on your Mac</span></div>
      <button class="ib" data-act="new-chat" aria-label="New chat">${I.edit}</button></div>
    <div class="thread" id="thread">${S.msgs.length ? S.msgs.map(msgHtml).join("") : welcome}</div>
    ${sugg}
    <div class="dock"><form class="composer frost" data-form="send">
      <textarea id="box" rows="1" placeholder="Ask Jarvis anything" aria-label="Message" enterkeyhint="send"></textarea>
      <button class="send" id="sendBtn" type="submit" aria-label="${S.streaming ? "Stop" : "Send"}" ${S.streaming ? "" : "disabled"}>${S.streaming ? I.stop : I.send}</button>
    </form></div></section>`;
}
let draft = "";
function afterChatRender() {
  const box = $("#box"), t = $("#thread");
  box.value = draft; autosize(box); updateSend();
  if (t) t.scrollTop = t.scrollHeight;
  if (!isTouch) box.focus({ preventScroll: true });
}
function autosize(el) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  el.style.overflowY = el.scrollHeight > 140 ? "auto" : "hidden"; // no empty scrollbar for short messages
}
function updateSend() {
  const btn = $("#sendBtn"); if (!btn) return;
  btn.disabled = !S.streaming && !draft.trim();
}
let rafPending = false;
function redrawThread() {
  if (rafPending) return;
  rafPending = true;
  requestAnimationFrame(() => {
    rafPending = false;
    const t = $("#thread"); if (!t || S.route !== "chat") return;
    const nearBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 120;
    t.innerHTML = S.msgs.map(msgHtml).join("");
    if (nearBottom) t.scrollTop = t.scrollHeight;
  });
}

async function send(text) {
  text = (text || "").trim();
  if (!text || S.streaming) return;
  draft = "";
  try {
    if (!S.chatId) {
      const chat = await api("/api/chats", { method: "POST" });
      S.chatId = chat.id; S.chats.unshift(chat);
      history.replaceState(null, "", `#chat/${chat.id}`);
    }
  } catch (e) { toast(e.message); draft = text; render(false); return; }
  const reply = { role: "assistant", text: "", tools: [], pending: true };
  S.msgs.push({ role: "user", text }, reply);
  const controller = new AbortController();
  S.streaming = controller;
  render(false);
  try {
    const res = await fetch(`/api/chats/${encodeURIComponent(S.chatId)}/send`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }), signal: controller.signal });
    if (!res.ok || !res.body) { const d = await res.json().catch(() => ({})); throw new Error(d.error || "Jarvis could not answer."); }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.t === "delta") reply.text += ev.text;
        else if (ev.t === "tool" && !reply.tools.includes(ev.label)) reply.tools.push(ev.label);
        else if (ev.t === "done") { if (ev.text) reply.text = ev.text; reply.pending = false; }
        else if (ev.t === "error") { reply.error = ev.message; reply.pending = false; }
        redrawThread();
      }
    }
    if (reply.pending) { reply.pending = false; if (!reply.text) reply.error = "The reply was cut off. Try again."; }
  } catch (e) {
    reply.pending = false;
    reply.error = e.name === "AbortError" ? "Stopped. Jarvis is still finishing this answer; it will appear here."
      : "The connection dropped. Jarvis is still finishing this answer; it will appear here.";
  }
  S.streaming = null;
  if (reply.error) watchForReply(S.chatId);
  const chat = S.chats.find(c => c.id === S.chatId);
  if (chat && chat.title === "New chat") chat.title = text.slice(0, 60);
  render(false);
}

function renderDrawer() {
  const d = $("#drawer");
  d.classList.toggle("open", S.drawer); $("#scrim").classList.toggle("open", S.drawer);
  d.innerHTML = `<div class="head"><b>Chats</b><button class="btn s" data-act="new-chat">New chat</button></div>
    <div class="list">${S.chats.length ? S.chats.map(c => `<div class="chat ${c.id === S.chatId ? "on" : ""}">
      <button class="open" data-act="open-chat" data-v="${esc(c.id)}"><div class="t">${esc(c.title)}</div><div class="s">${esc(c.preview || "No reply yet")} · ${ago(c.updated_at)}</div></button>
      <button class="del" data-act="delete-chat" data-v="${esc(c.id)}" aria-label="Delete chat">${I.trash}</button></div>`).join("")
      : `<div class="empty">No chats yet. Your conversations will appear here.</div>`}</div>`;
}

// ---------- today ----------
function viewToday() {
  const T = S.today;
  const head = `<div class="h1">Today</div><div class="sub">${new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}${T ? ` · ${esc(T.greeting)}, Guru` : ""}</div>`;
  if (S.todayErr && !T) return `<section class="view"><div class="scroll">${head}<div class="card empty">${esc(S.todayErr)} <button class="btn s" data-act="reload">Try again</button></div></div></section>`;
  if (!T) return `<section class="view"><div class="scroll">${head}<div class="card big"><div class="skel" style="width:40%"></div><div class="skel"></div><div class="skel" style="width:70%"></div></div></div></section>`;
  const dueToday = T.tasks.filter(t => !t.done && t.due_on && t.due_on <= todayISO()).length;
  const medsLeft = T.medicines.filter(m => m.status === "due").length;
  const iph = S.iphone && S.iphone.available ? S.iphone.open_reminders : null;
  const nextRenewal = T.renewals[0];
  const eventsToday = T.events.filter(e => e.day === T.date);
  const summary = [
    eventsToday.length ? `${eventsToday.length} event${eventsToday.length > 1 ? "s" : ""} today` : "No events today",
    T.due_soon ? `${T.due_soon} task${T.due_soon > 1 ? "s" : ""} due this week` : "no tasks due this week",
    medsLeft ? `${medsLeft} medicine dose${medsLeft > 1 ? "s" : ""} left` : "",
    nextRenewal ? `${esc(nextRenewal.item)} ${esc(nextRenewal.what)} ${dayInSentence(nextRenewal.date)}${nextRenewal.amount ? ` (${esc(nextRenewal.amount)})` : ""}` : "",
  ].filter(Boolean).join(" · ");
  const events = T.events.length ? T.events.map(e => `<div class="row"><span class="time">${esc(e.day === T.date ? (e.time || "All day") : dayLabel(e.day))}</span>
      <span class="vline ${e.day === T.date ? "" : "dim"}"></span><div class="m"><div class="t">${esc(e.title)}</div>
      <div class="s">${e.time ? `${esc(e.time)}${e.end ? `–${esc(e.end)}` : ""}` : "All day"}${e.where ? ` · ${esc(e.where)}` : ""} · ${e.source === "apple" ? "iPhone" : "Google"}</div></div></div>`).join("")
    : `<div class="empty">${T.calendars_connected ? "Nothing on your calendars in the next 7 days." : "No calendar connected yet."}</div>`;
  const tasks = T.tasks.map(t => `<button class="row ${t.done ? "done" : ""}" data-act="task" data-v="${t.id}" aria-pressed="${!!t.done}"><span class="check">${t.done ? I.ok : ""}</span><div class="m"><div class="t wrap">${esc(t.title)}</div>
      <div class="s">Jarvis task${t.due_on ? ` · due ${dayLabel(t.due_on)}` : ""}${t.remind_at ? ` · reminder ${esc(t.remind_at.slice(11))}` : ""}</div></div>
      ${t.priority === 1 && !t.done ? '<span class="tag" style="color:var(--up)">High</span>' : ""}</button>`).join("");
  const iphRows = iph ? iph.slice(0, 8).map(r => `<div class="row"><div class="m"><div class="t wrap">${esc(r.title)}</div>
      <div class="s">iPhone Reminders${r.due ? ` · ${dayLabel(r.due.slice(0, 10))}` : ""}${r.list && r.list !== "Reminders" ? ` · ${esc(r.list)}` : ""}</div></div></div>`).join("") : "";
  const iphState = !S.iphone ? `<div class="row"><div class="m"><div class="s">Loading iPhone Reminders…</div></div></div>`
    : !S.iphone.available ? `<div class="row"><div class="m"><div class="s">${esc(S.iphone.reason || "iPhone Reminders unavailable")}</div></div></div>` : "";
  const meds = T.medicines.length ? T.medicines.map(m => {
    const key = `data-med="${m.medication_id}" data-time="${esc(m.time)}"`;
    const status = m.status === "taken" ? "Taken ✓" : m.status === "skipped" ? "Skipped" : m.past ? "Due now" : `At ${esc(m.time)}`;
    const btns = m.status === "due"
      ? `<button class="btn s" data-act="med" data-status="skipped" ${key}>Skip</button><button class="btn p" data-act="med" data-status="taken" ${key}>Taken</button>`
      : `<button class="btn s" data-act="med" data-status="due" ${key}>Undo</button>`;
    return `<div class="row"><span class="ic">${I.pill}</span><div class="m"><div class="t">${esc(m.name)}</div><div class="s">${esc(m.dose || "")}${m.dose ? " · " : ""}${status}</div></div>${btns}</div>`;
  }).join("") : `<div class="empty">No medicines set up. Tell Jarvis, for example “Remind me to take Vitamin D3 60000 IU every Sunday at 9 am”.</div>`;
  const renewals = T.renewals.slice(0, 4).map(r => `<div class="row"><span class="ic">${I.renew}</span><div class="m"><div class="t">${esc(r.item)}</div>
      <div class="s">${esc(r.what)} ${dayLabel(r.date)} · ${esc(r.source)}</div></div><span class="v">${esc(r.amount || "")}</span></div>`).join("");
  return `<section class="view"><div class="scroll">${head}
    <div class="card big"><div class="k">Summary</div><div class="text">${summary}.</div>
      <div class="kpis"><div><b>${inr0(T.spent_today)}</b><span>spent today</span></div><div><b>${dueToday}</b><span>due today</span></div>
      <div><b>${iph ? iph.length : "–"}</b><span>reminders</span></div><div><b>${medsLeft}</b><span>doses left</span></div></div></div>
    ${T.calendar_errors.length ? `<div class="note">Couldn't read the ${esc(T.calendar_errors.join(" and "))} calendar, so the schedule may be incomplete.</div>` : ""}
    <div class="sec">Schedule · next 7 days</div><div class="card">${events}</div>
    <div class="sec">To do</div><div class="card">${tasks}${iphRows}${iphState}${!tasks && iph && !iph.length ? '<div class="empty">Nothing to do. Nice.</div>' : ""}</div>
    <div class="sec">Medicines</div><div class="card">${meds}</div>
    ${renewals ? `<div class="sec">Bills & renewals <button data-act="go" data-v="renewals">All</button></div><div class="card">${renewals}</div>` : ""}
  </div></section>`;
}

// ---------- money ----------
function spark(points) {
  if (!points || points.length < 2) return "";
  const max = Math.max(...points, 1), w = 320, h = 46;
  const d = points.map((p, i) => `${i ? "L" : "M"}${(i / (points.length - 1) * w).toFixed(1)} ${(h - 4 - p / max * (h - 8)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="var(--text)" stroke-width="1.8" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`;
}
function viewMoney() {
  const m = S.money[S.period];
  const seg = `<div class="seg" role="tablist">${[["today", "Today"], ["week", "Week"], ["month", "Month"], ["year", "Year"]].map(([k, n]) =>
    `<button class="${k === S.period ? "on" : ""}" data-act="period" data-v="${k}" role="tab" aria-selected="${k === S.period}">${n}</button>`).join("")}</div>`;
  const head = `<div class="h1">Money</div><div class="sub">From HDFC + ICICI alert emails</div>${seg}`;
  if (!m) return `<section class="view"><div class="scroll">${head}${S.moneyErr ? `<div class="card empty">${esc(S.moneyErr)} <button class="btn s" data-act="reload">Try again</button></div>`
    : `<div class="card big"><div class="skel" style="width:35%"></div><div class="skel" style="height:30px;width:60%"></div><div class="skel"></div></div>`}</div></section>`;
  const ch = change(m.spent, m.previous);
  const prevName = { today: "yesterday", week: "the week before", month: "the month before", year: "" }[m.period];
  const max = Math.max(...m.categories.map(c => c.total), 1);
  const cats = m.categories.map(c => {
    const cc = change(c.total, c.previous);
    const share = m.spent > 0 ? Math.round(c.total / Math.max(m.spent, 1) * 100) : 0;
    return `<div class="catrow"><div class="top"><span>${esc(c.category)}</span><b>${inr0(c.total)}</b></div>
      <div class="meta"><span>${c.payments} payment${c.payments === 1 ? "" : "s"}${share ? ` · ${share}%` : ""}</span><span style="color:${cc.startsWith("↓") ? "var(--down)" : "var(--up)"}">${cc}</span></div>
      <div class="bar"><i style="width:${Math.max(2, c.total / max * 100).toFixed(1)}%"></i></div></div>`;
  }).join("");
  const unusual = m.unusual.map(u => {
    const parts = u.match(/^(\d{4}-\d{2}-\d{2}) ₹([\d,.]+) (.*?)(?: \(([^)]*)\))?$/);
    return parts ? `<div class="row"><div class="m"><div class="t">${esc(parts[3] || "Payment")}</div><div class="s">${dayLabel(parts[1])}${parts[4] ? ` · ${esc(parts[4])}` : ""}</div></div><span class="v">₹${esc(parts[2].replace(/\.00$/, ""))}</span></div>` : "";
  }).join("");
  return `<section class="view"><div class="scroll">${head}
    <div class="card big"><div class="k">Spent · ${esc(m.label)}</div><div class="n">${inr(m.spent)}</div>
      <div class="d">${ch ? `<span style="color:${ch.startsWith("↓") ? "var(--down)" : "var(--up)"}">${ch}</span> vs ${prevName} · ` : ""}${m.payments} payment${m.payments === 1 ? "" : "s"}</div>
      ${spark(m.points)}
      <div class="kpis"><div><b>${inr0(m.refunds)}</b><span>refunds</span></div><div><b>${inr0(m.received)}</b><span>received</span></div><div><b>${inr0(m.own_transfers)}</b><span>own transfers</span></div></div></div>
    <div class="sec">By category</div><div class="card">${cats || '<div class="empty">No payments in this period.</div>'}</div>
    ${unusual ? `<div class="sec">Unusually large</div><div class="card">${unusual}</div>` : ""}
    ${m.new_merchants.length ? `<div class="sec">New this period</div><div class="card"><div class="empty">${m.new_merchants.map(esc).join(", ")}</div></div>` : ""}
    <div class="note">${esc(m.note)} Categories are guessed from merchant names.</div>
  </div></section>`;
}

// ---------- more, settings, activity, renewals ----------
function sub(title, body) {
  return `<section class="view sub"><div class="navbar"><button class="back" data-act="go" data-v="more">${I.back} More</button><div class="title">${esc(title)}</div></div>
    <div class="scroll">${body}</div></section>`;
}
function viewMore() {
  const M = S.more;
  const install = !standalone ? `<div class="card big" style="margin-bottom:14px"><div class="k">Install</div>
      <div class="text">Add Jarvis to your Home Screen: tap <b>Share</b> ${I.share.replace('aria-hidden="true"', 'style="display:inline;width:16px;height:16px;vertical-align:-3px"')} then <b>Add to Home Screen</b>. Notifications need this.</div></div>` : "";
  const row = (act, v, icon, title, detail, right = `<span class="chev">${I.chev}</span>`) =>
    `<button class="row" data-act="${act}" data-v="${v}"><span class="ic">${icon}</span><div class="m"><div class="t">${title}</div><div class="s">${detail}</div></div>${right}</button>`;
  const info = (icon, title, detail) => `<div class="row"><span class="ic">${icon}</span><div class="m"><div class="t">${title}</div><div class="s">${detail}</div></div></div>`;
  return `<section class="view"><div class="scroll"><div class="h1">More</div><div class="sub">Activity, notifications and your data</div>${install}
    <div class="card">
      ${row("go", "activity", I.inbox, "Activity", S.unread ? `${S.unread} new` : "Everything Jarvis told you", S.unread ? `<span class="dot"></span>` : `<span class="chev">${I.chev}</span>`)}
      ${row("go", "settings", I.bell, "Notifications", "Choose what pops up on your phone")}
      ${row("go", "renewals", I.renew, "Bills & renewals", M && M.next_renewal ? `Next: ${esc(M.next_renewal.item)} ${dayLabel(M.next_renewal.date)}` : "From your files")}
    </div>
    <div class="sec">Your data</div>
    <div class="card">
      ${info(I.brain, "Memory", M ? `${M.facts} facts · ${M.episodes} chat summaries${M.memory_review ? ` · ${M.memory_review} to review: reply “clean up” in chat` : ""}` : "…")}
      ${info(I.file, "Files", M ? `${M.documents} documents indexed from your Jarvis folder` : "…")}
      ${info(I.list, "Tasks", M ? `${M.open_tasks} open Jarvis task${M.open_tasks === 1 ? "" : "s"}` : "…")}
    </div>
    <div class="note">Jarvis runs on your Mac. Ask in chat “what do you know about me” to see your memory, or “forget …” to remove something.</div>
  </div></section>`;
}

async function refreshPushState() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) { S.pushState = "unsupported"; return; }
  if (Notification.permission === "denied") { S.pushState = "denied"; return; }
  // If the service worker never starts, show the page anyway instead of waiting forever.
  const reg = await Promise.race([navigator.serviceWorker.ready, new Promise(r => setTimeout(() => r(null), 4000))]);
  if (!reg) { S.pushState = "unsupported"; return; }
  const sub = await reg.pushManager.getSubscription();
  S.pushState = sub ? "on" : "off";
}
function viewSettings() {
  const st = S.settings;
  if (!st) return sub("Notifications", `<div class="card big"><div class="skel"></div><div class="skel" style="width:60%"></div></div>`);
  const ios = /iPhone|iPad/.test(navigator.userAgent);
  let device;
  if (S.pushState === "unsupported") device = ios && !standalone
    ? `<div class="text">To get notifications, add Jarvis to your Home Screen first (Share → Add to Home Screen), then open it from there.</div>`
    : `<div class="text">This browser can't receive notifications.</div>`;
  else if (S.pushState === "denied") device = `<div class="text">Notifications are blocked for Jarvis. Turn them on in iPhone Settings → Notifications → Jarvis.</div>`;
  else if (S.pushState === "on") device = `<div class="text">This device gets the notifications switched on below.</div>
    <div style="display:flex;gap:8px;margin-top:12px"><button class="btn s" data-act="push-test">Send a test</button><button class="btn s" data-act="push-off">Turn off here</button></div>`;
  else device = `<div class="text">Allow notifications on this device. Only the kinds switched on below will pop up.</div>
    <button class="btn p wide" style="margin-top:12px" data-act="push-on">Turn on notifications</button>`;
  const kinds = st.kinds.map(k => `<button class="row" data-act="kind" data-v="${k.kind}" role="switch" aria-checked="${k.push}"><div class="m"><div class="t">${esc(k.title)}</div>
      <div class="s wrap" style="white-space:normal">${esc(k.detail)}</div></div><span class="tog ${k.push ? "" : "off"}"></span></button>`).join("");
  const q = st.quiet;
  return sub("Notifications", `
    <div class="card big"><div class="k">This device</div>${device}</div>
    <div class="sec">Pop up on my phone</div><div class="card">${kinds}</div>
    <div class="note">Everything else stays quietly in Activity, so you never miss it and your phone stays calm.</div>
    <div class="sec">Quiet hours</div>
    <div class="card"><button class="row" data-act="quiet" role="switch" aria-checked="${q.on}"><div class="m"><div class="t">Quiet hours</div><div class="s">No pop-ups during these hours</div></div><span class="tog ${q.on ? "" : "off"}"></span></button>
      ${q.on ? `<div class="row"><div class="m"><div class="t">From</div></div><input type="time" data-quiet="from" value="${esc(q.from)}"></div>
      <div class="row"><div class="m"><div class="t">To</div></div><input type="time" data-quiet="to" value="${esc(q.to)}"></div>` : ""}</div>
    <div class="sec">Telegram</div>
    <div class="card"><button class="row" data-act="telegram" role="switch" aria-checked="${st.telegram}"><div class="m"><div class="t">Also send to Telegram</div>
      <div class="s">${st.telegram ? `Until ${dayLabel(st.telegram_until)}, while you try the app` : "Off"}</div></div><span class="tog ${st.telegram ? "" : "off"}"></span></button></div>`);
}
function viewActivity() {
  const A = S.activity;
  const body = !A ? `<div class="card big"><div class="skel"></div><div class="skel" style="width:70%"></div></div>`
    : A.length ? `<div class="card">${A.map(a => `<div class="row" style="align-items:flex-start"><div class="m"><div class="s">${esc(KIND_LABEL[a.kind] || a.kind)} · ${ago(a.created_at)}${a.pushed ? " · notified" : ""}</div>
        <div class="t wrap" style="margin-top:2px">${esc(a.title)}</div>${a.body && a.body !== a.title ? `<div class="s" style="white-space:pre-wrap">${esc(a.body)}</div>` : ""}</div></div>`).join("")}</div>`
    : `<div class="card empty">Nothing yet. Reminders, renewals and reports will appear here.</div>`;
  return sub("Activity", body);
}
function viewRenewals() {
  const R = S.today ? S.today.renewals : null;
  const body = !R ? `<div class="card big"><div class="skel"></div></div>`
    : R.length ? `<div class="card">${R.map(r => `<div class="row"><span class="ic">${I.renew}</span><div class="m"><div class="t">${esc(r.item)}</div>
        <div class="s">${esc(r.what)} ${dayLabel(r.date)} · ${esc(r.repeats)} · ${esc(r.source)}</div></div><span class="v">${esc(r.amount || "")}</span></div>`).join("")}</div>
      <div class="note">Found in your files (renews, expires, valid until). Next 30 days.</div>`
    : `<div class="card empty">No bills or renewals in the next 30 days.</div>`;
  return sub("Bills & renewals", body);
}

// ---------- actions ----------
function b64ToBytes(b64) {
  const pad = "=".repeat((4 - b64.length % 4) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, c => c.charCodeAt(0));
}
async function pushOn() {
  try {
    const permission = await Notification.requestPermission(); // first, while the tap still counts as a user gesture
    if (permission !== "granted") { await refreshPushState(); render(false); return; }
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/key");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) });
    await api("/api/push/subscribe", { method: "POST", body: sub.toJSON() });
    toast("Notifications are on");
  } catch (e) { toast(e.message || "Couldn't turn on notifications"); }
  await refreshPushState(); render(false);
}
async function pushOff() {
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) { await api("/api/push/unsubscribe", { method: "POST", body: { endpoint: sub.endpoint } }); await sub.unsubscribe(); }
    toast("Notifications are off on this device");
  } catch (e) { toast(e.message); }
  await refreshPushState(); render(false);
}
async function saveSettings(change) {
  try {
    S.settings = await api("/api/settings", { method: "PUT", body: change });
  } catch (e) { toast(e.message); S.settings = await api("/api/settings").catch(() => S.settings); }
  render(false);
}

document.addEventListener("click", async e => {
  const el = e.target.closest("[data-act]");
  if (!el) return;
  const v = el.dataset.v;
  switch (el.dataset.act) {
    // The Chat tab returns to the conversation you were in, not a blank chat.
    case "go": navigate(v === "chat" && S.chatId ? `#chat/${S.chatId}` : `#${v}`); break;
    case "reload": load(S.route); break;
    case "drawer-open": S.drawer = true; renderDrawer(); break;
    case "drawer-close": S.drawer = false; renderDrawer(); break;
    case "new-chat": if (S.streaming) { toast("Wait for the reply to finish"); break; } S.drawer = false; renderDrawer(); S.chatId = null; S.msgs = []; navigate("#chat", true); break;
    case "open-chat":
      if (S.streaming && v !== S.chatId) { toast("Wait for the reply to finish"); break; }
      S.drawer = false; renderDrawer(); navigate(`#chat/${v}`); break;
    case "delete-chat":
      if (!confirm("Delete this chat? This can't be undone.")) break;
      try {
        await api(`/api/chats/${encodeURIComponent(v)}`, { method: "DELETE" });
        S.chats = S.chats.filter(c => c.id !== v); renderDrawer();
        if (S.chatId === v) { S.chatId = null; S.msgs = []; navigate("#chat", true); }
        toast("Chat deleted");
      } catch (err) { toast(err.message); }
      break;
    case "ask": send(v); break;
    case "retry": {
      const lastUser = [...S.msgs].reverse().find(m => m.role === "user");
      if (!lastUser || S.streaming) break;
      if (S.msgs[S.msgs.length - 1].role === "assistant") S.msgs.pop();
      S.msgs.pop();
      send(lastUser.text);
      break;
    }
    case "copy": {
      const m = S.msgs[+el.dataset.i];
      try { await navigator.clipboard.writeText(m.text); toast("Copied"); } catch { toast("Couldn't copy"); }
      break;
    }
    case "speak": {
      const m = S.msgs[+el.dataset.i];
      if (!("speechSynthesis" in window)) { toast("Reading aloud isn't available here"); break; }
      if (speechSynthesis.speaking) { speechSynthesis.cancel(); break; }
      const u = new SpeechSynthesisUtterance(m.text.replace(/[*#`_]/g, ""));
      u.lang = /[஀-௿]/.test(m.text) ? "ta-IN" : "en-IN";
      speechSynthesis.speak(u);
      break;
    }
    case "period": S.period = v; render(false); load("money"); break; // cached figures show at once, then refresh
    case "task": { // tap to tick, tap again to undo; ticked tasks stay listed until Today reloads
      const task = S.today.tasks.find(t => t.id === +v);
      if (!task) break;
      const done = !task.done;
      task.done = done; render(false);
      try {
        await api(`/api/tasks/${+v}/done`, { method: "POST", body: { done } });
        toast(done ? `Done: ${task.title} · tap again to undo` : "Marked not done");
      } catch (err) { task.done = !done; render(false); toast(err.message); }
      break;
    }
    case "med": {
      const status = el.dataset.status;
      try {
        await api("/api/medicine", { method: "POST", body: { medication_id: +el.dataset.med, time: el.dataset.time, status } });
        const m = S.today.medicines.find(x => x.medication_id === +el.dataset.med && x.time === el.dataset.time);
        if (m) m.status = status;
        render(false);
        toast(status === "taken" ? "Marked taken" : status === "skipped" ? "Marked skipped" : "Undone");
      } catch (err) { toast(err.message); }
      break;
    }
    case "push-on": pushOn(); break;
    case "push-off": pushOff(); break;
    case "push-test":
      try { const r = await api("/api/push/test", { method: "POST" }); toast(r.sent ? "Test sent" : "No device is registered"); } catch (err) { toast(err.message); }
      break;
    case "kind": {
      const k = S.settings.kinds.find(x => x.kind === v);
      saveSettings({ push: { [v]: !k.push } });
      break;
    }
    case "quiet": saveSettings({ quiet: { on: !S.settings.quiet.on } }); break;
    case "telegram": saveSettings({ telegram: !S.settings.telegram }); break;
  }
});
document.addEventListener("change", e => {
  const q = e.target.closest("[data-quiet]");
  if (q && q.value) saveSettings({ quiet: { [q.dataset.quiet]: q.value } });
});
document.addEventListener("input", e => {
  if (e.target.id === "box") { draft = e.target.value; autosize(e.target); updateSend(); }
});
document.addEventListener("keydown", e => {
  if (e.target.id === "box" && e.key === "Enter" && !e.shiftKey && !isTouch && !e.isComposing) { e.preventDefault(); send(draft); }
  if (e.key === "Escape" && S.drawer) { S.drawer = false; renderDrawer(); }
});
document.addEventListener("submit", e => {
  if (e.target.dataset.form !== "send") return;
  e.preventDefault();
  if (S.streaming) { S.streaming.abort(); return; }
  send(draft);
});

// Refresh what is on screen when the app comes back to the front.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  if (["today", "money", "more", "activity"].includes(S.route)) load(S.route);
  else loadActivity(false).then(renderTabs).catch(() => {});
  if (S.route === "chat") refreshChat();
});
addEventListener("hashchange", route);
addEventListener("online", () => setOffline(false));
addEventListener("offline", () => setOffline(true));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
route();
renderDrawer();
loadActivity(false).then(renderTabs).catch(() => {});
api("/api/today").then(t => { S.today = t; renderTabs(); }).catch(() => {});
