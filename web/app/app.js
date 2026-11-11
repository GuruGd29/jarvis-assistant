// Jarvis web app. One page; views are drawn from state and re-drawn on change.
// Everything from the server is escaped before it reaches the page.

// ---------- helpers ----------
const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const isTouch = matchMedia("(pointer: coarse)").matches;
const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
// The owner's name, number/date style and currency, from .env via a <meta> tag the server adds (server.py _profile).
const P = (() => { try { return JSON.parse($('meta[name="jarvis-profile"]')?.content || "{}"); } catch { return {}; } })();
const LOCALE = P.locale || "en-IN";
const CURRENCY = P.currency || "INR";
const moneyFmt = new Intl.NumberFormat(LOCALE, { style: "currency", currency: CURRENCY });
const moneyRound = new Intl.NumberFormat(LOCALE, { style: "currency", currency: CURRENCY, minimumFractionDigits: 0, maximumFractionDigits: 0 });
const fmtMoney = n => moneyFmt.format(Number(n) || 0);
const fmtMoney0 = n => moneyRound.format(Number(n) || 0);
const withName = text => P.name ? `${text}, ${esc(P.name)}` : text;
const todayISO = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

function dayLabel(iso) {
  const d = new Date(`${iso}T00:00:00`);
  const diff = Math.round((d - new Date(`${todayISO()}T00:00:00`)) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  const year = d.getFullYear() === new Date().getFullYear() ? {} : { year: "numeric" };
  return d.toLocaleDateString(LOCALE, { weekday: "short", day: "numeric", month: "short", ...year });
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
  return new Date(iso).toLocaleDateString(LOCALE, { day: "numeric", month: "short" });
}
// No arrow when the earlier amount is below `small` (10 times the usual payment, from the server; fits any currency).
function change(now, before, small = 1000) {
  if (!before || before < small) return "";
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

// Signed out, or the sign-in ran out: go to the sign-in page. Never resolves, so nothing shows an error meanwhile.
function toSignIn() { location.replace("/login"); return new Promise(() => {}); }
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  if (init.method !== "GET" && !await reachable()) throw new Error(OFFLINE);
  let res;
  try { res = await fetch(path, init); } catch { setOffline(true); throw new Error("Can't reach Jarvis. Check your Wi-Fi or VPN."); }
  if (res.status === 401) return toSignIn();
  S.savedAt = res.headers.get("X-Jarvis-Saved"); // set when the service worker answered with the phone's saved copy
  setOffline(!!S.savedAt, S.savedAt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
  return data;
}
function setOffline(on, savedAt) {
  const el = $("#offline"); if (!el) return;
  const at = savedAt && new Date(savedAt), today = at && at.toDateString() === new Date().toDateString();
  el.textContent = at ? `Offline · last updated ${at.toLocaleString(LOCALE, { ...(today ? {} : { weekday: "short" }), hour: "numeric", minute: "2-digit" })}`
    : "Offline · can't reach Jarvis";
  el.classList.toggle("show", on);
  $("#app").classList.toggle("is-offline", on);
}
// While the screens show saved data, check that the computer answers before an action, rather than wait a minute.
const OFFLINE = "Jarvis's computer is off or out of reach. This works again once it's back.";
async function reachable() {
  if (!S.savedAt) return true;
  try { await fetch("/", { method: "HEAD", cache: "no-store", signal: AbortSignal.timeout(3000) }); return true; }
  catch { return false; }
}
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
  // A rupee sign for INR, a wallet for every other currency.
  money: CURRENCY === "INR" ? sv('<path d="M7 5h10M7 9h10M7 5c4 0 6 1.6 6 4s-2 4-6 4h-.5L14 20"/>')
    : sv('<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10.5h18M15.5 15h2"/>'),
  more: sv('<rect x="4" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6"/>'),
  menu: sv('<path d="M4 8h16M4 16h11"/>', 2), edit: sv('<path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6M17.5 3.5l3 3L12 15H9v-3z"/>', 1.9),
  mic: sv('<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"/>', 2),
  send: sv('<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/>', 2.3), stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/></svg>',
  copy: sv('<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'),
  speak: sv('<path d="M4 9.5v5h3.5L12 18V6L7.5 9.5zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>'),
  redo: sv('<path d="M19 8a7.5 7.5 0 1 0 1 5M19 3.5V8h-4.5"/>'), ok: sv('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 2.4),
  spin: sv('<path d="M12 3a9 9 0 1 0 9 9"/>', 2.2), trash: sv('<path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13"/>'),
  back: sv('<path d="M15 5l-7 7 7 7"/>', 2.2), chev: sv('<path d="M9 5l7 7-7 7"/>', 2.2),
  pill: sv('<rect x="3" y="8" width="18" height="8" rx="4" transform="rotate(-35 12 12)"/><path d="M9.5 8.7l5 6.6"/>'),
  renew: sv('<path d="M19 8a7.5 7.5 0 0 0-13.5 1M5 16a7.5 7.5 0 0 0 13.5-1M19 3.5V8h-4.5M5 20.5V16h4.5"/>'),
  brain: sv('<path d="M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-1.5 5.5A3 3 0 0 0 9 18v1.5M15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 1.5 5.5A3 3 0 0 1 15 18v1.5M9 4.5a3 3 0 0 1 6 0V19.5"/>'),
  file: sv('<path d="M6 3h8l4 4v14H6zM14 3v4h4"/>'), photo: sv('<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.5 3.5 3 3-2.5 4.5 4"/>'),
  bell: sv('<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0"/>'),
  inbox: sv('<path d="M4 13l2.5-8h11L20 13v6H4zM4 13h5l1 2h4l1-2h5"/>'), share: sv('<path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M5 12v7.5h14V12"/>'),
  list: sv('<path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/>', 2.2),
  watches: sv('<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>'),
  plus: sv('<path d="M12 5v14M5 12h14"/>', 2.2),
  clip: sv('<path d="M20 11.5l-8.1 8.1a5 5 0 0 1-7.1-7.1l8.5-8.5a3.4 3.4 0 0 1 4.8 4.8l-8.5 8.5a1.8 1.8 0 0 1-2.5-2.5l7.8-7.8"/>', 1.9),
  upload: sv('<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M5 14v5.5h14V14"/>', 2),
  x: sv('<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>', 2.2),
  out: sv('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>'),
  bus: sv('<rect x="4.5" y="3.5" width="15" height="14" rx="3"/><path d="M4.5 10.5h15M8 17.5V20M16 17.5V20M8 14h.01M16 14h.01"/>'),
  film: sv('<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M3.5 9.5h17M8 5l2 4.5M13 5l2 4.5"/>'),
  globe: sv('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.6 3.5 5.4 3.5 8.5s-1 5.9-3.5 8.5c-2.5-2.6-3.5-5.4-3.5-8.5s1-5.9 3.5-8.5z"/>'),
};
const KIND_LABEL = { reminders: "Reminder", renewals: "Bills & renewals", problems: "Needs attention", reports: "Report", replies: "Chat reply" };

// ---------- state ----------
const S = {
  route: "chat", chatId: null, chats: [], msgs: [], streaming: null, drawer: false,
  today: null, todayErr: null, iphone: null, money: {}, period: "week", moneyErr: null, moneyTab: "spending", cards: null, cardSel: null, syncing: false, savedAt: null,
  watches: null, watchErr: null, watch: {}, warg: "", wtext: "", wform: null, wtest: null, wbusy: false, wstart: null, wplaces: null,
  attach: null, files: null, filesErr: null, fileFolder: "documents", fileBusy: false, // chat attachment; your files
  moneyOn: { today: null, week: null, month: null, year: null }, cat: null, allPays: false, // null = the current period
  mic: "idle", // idle | rec | busy (turning the recording into text)
  more: null, settings: null, activity: null, unread: 0, pushState: "unknown",
};

// ---------- shell ----------
document.getElementById("app").innerHTML = `
  <aside class="side" id="side" aria-label="Jarvis"></aside>
  <div id="view"></div>
  <nav class="tabbar frost" id="tabbar" aria-label="Main"></nav>
  <div class="scrim" id="scrim" data-act="drawer-close"></div>
  <aside class="drawer" id="drawer" aria-label="Chats"></aside>
  <div class="toast" id="toast" role="status"></div>
  <div class="offline" id="offline">Offline · can't reach Jarvis</div>`;

const TABS = [["chat", "Chat"], ["today", "Today"], ["money", "Money"], ["watches", "Watches"], ["more", "More"]];
const mainTab = () => ["settings", "activity", "renewals", "files", "siri"].includes(S.route) ? "more" : S.route;
function tabBadge(k) {
  if (k === "today") return S.today ? S.today.tasks.filter(t => !t.done && t.due_on && t.due_on <= todayISO()).length
    + S.today.medicines.filter(m => m.past && m.status === "due").length : 0;
  if (k === "watches") return S.watches ? S.watches.found.length : S.today && S.today.watch_found ? S.today.watch_found.length : 0;
  return k === "more" ? S.unread || 0 : 0;
}
// On a big screen (1024 px and wider) the tab bar and the chat drawer become this sidebar.
const BIG = matchMedia("(min-width: 1024px)");
function renderSide() {
  const side = $("#side");
  if (!side || !BIG.matches) return;
  const main = mainTab(), hour = new Date().getHours(), scrolled = side.querySelector(".list")?.scrollTop || 0;
  const hello = hour >= 21 || hour < 5 ? "Good night" : hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  side.innerHTML = `<div class="brand"><img src="/static/icons/icon-192.png" alt=""><div><b>Jarvis</b><span>${withName(hello)}</span></div></div>
    <nav class="nav">${TABS.map(([k, n]) => { const c = tabBadge(k);
      return `<button class="${k === main ? "on" : ""}" data-act="go" data-v="${k}" ${k === main ? 'aria-current="page"' : ""}>${I[k]}${n}${c ? `<span class="count">${c > 9 ? "9+" : c}</span>` : ""}</button>`; }).join("")}</nav>
    <button class="btn s newchat" data-act="new-chat">${I.edit} New chat</button>
    <div class="label">Recent chats</div>
    <div class="list">${S.chats.length ? S.chats.slice(0, 40).map(c => `<div class="chat ${S.route === "chat" && c.id === S.chatId ? "on" : ""}">
      <button class="open" data-act="open-chat" data-v="${esc(c.id)}"><div class="t">${esc(c.title)}</div><div class="s">${esc(c.preview || "No reply yet")}</div></button>
      <button class="del" data-act="delete-chat" data-v="${esc(c.id)}" aria-label="Delete chat">${I.trash}</button></div>`).join("")
      : '<div class="empty">No chats yet.</div>'}</div>
    <div class="foot"><i class="${S.savedAt ? "off" : ""}"></i>${S.savedAt ? "Offline · showing saved data" : `Runs on your ${P.host === "mac" ? "Mac" : "own computer"}`}</div>`;
  if (scrolled) side.querySelector(".list").scrollTop = scrolled;
}
BIG.addEventListener("change", () => render(false));

function renderTabs() {
  renderSide();
  const main = mainTab();
  $("#tabbar").innerHTML = TABS.map(([k, n]) => {
    const badge = tabBadge(k);
    return `<button class="tab ${k === main ? "on" : ""}" data-act="go" data-v="${k}" aria-label="${n}" ${k === main ? 'aria-current="page"' : ""}>
      ${I[k]}${badge ? `<span class="badge">${badge > 9 ? "9+" : badge}</span>` : ""}<span>${n}</span></button>`;
  }).join("");
}

// A Home Screen app on iPhone forgets the microphone permission whenever its address changes (WebKit bug 215884),
// so there the screen on show is kept here and the address stays as it was opened. In a browser tab it is the #hash.
const STANDALONE = navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
let here = location.hash;
function setAddress(hash) { here = hash; if (!STANDALONE) history.replaceState(null, "", hash); }
function navigate(hash, replace = false) {
  if (here === hash) { route(); return; }
  if (replace || STANDALONE) { setAddress(hash); route(); } else location.hash = hash;
}
function route() {
  const [name, arg] = here.replace(/^#/, "").split("/");
  const known = ["chat", "today", "money", "watches", "more", "settings", "activity", "renewals", "files", "siri"];
  S.route = known.includes(name) ? name : "chat";
  if (S.route !== "siri") S.siriKey = null; // a new Siri key is shown once, only while you're on that screen
  S.warg = name === "watches" ? (arg || "") : "";
  try { S.farg = name === "files" && arg ? decodeURIComponent(arg) : ""; } catch { S.farg = ""; } // #files/<path>: a file opened
  if (S.route === "chat") openChat(arg || null);
  else { render(); load(S.route); }
}

function render(animate = true) {
  const views = { chat: viewChat, today: viewToday, money: viewMoney, watches: viewWatchesRoute, more: viewMore, settings: viewSettings, activity: viewActivity, renewals: viewRenewals, files: () => S.farg ? viewFile() : viewFiles(), siri: viewSiri };
  const keep = S.route === "watches" && !animate ? [...$$("#view .scroll, #view .listcol")].map(e => e.scrollTop) : []; // a refresh keeps your place
  $("#app").dataset.route = S.route;
  $("#view").innerHTML = views[S.route]();
  if (keep.length) [...$$("#view .scroll, #view .listcol")].forEach((e, i) => { if (keep[i]) e.scrollTop = keep[i]; });
  if (animate) { const sc = $("#view .scroll"); if (sc) sc.classList.add("slide"); }
  renderTabs();
  if (S.route === "chat") afterChatRender();
}

async function load(name) {
  try {
    if (name === "today") { S.today = await api("/api/today"); S.todayErr = null; loadIphone(); }
    if (name === "money") { // keep each answer under the period it was asked for, even if they arrive out of order
      const key = moneyKey(), on = S.moneyOn[S.period];
      if (S.moneyTab === "cards") S.cards = await api("/api/cards");
      else S.money[key] = await api(`/api/money?period=${S.period}${on ? `&on=${on}` : ""}`);
      S.moneyErr = null;
    }
    if (name === "watches") {
      const a = S.warg, id = /^\d+$/.test(a) ? a : a.startsWith("start-") ? a.slice(6) : null;
      if (id) {
        const w = S.watch[id] = await api(`/api/watches/${id}`);
        if (/^\d+$/.test(a) && w.found_at && !w.seen) { api(`/api/watches/${id}/seen`, { method: "POST" }).catch(() => {}); if (S.watches) S.watches = null; }
      }
      if (!id || !S.watches) S.watches = await api("/api/watches");
      if (a === "form" && S.wform && S.wform.kind === "bus" && !S.wplaces) S.wplaces = await api("/api/watches/places");
      S.watchErr = null;
    }
    if (name === "more") { S.more = await api("/api/more"); await loadActivity(false); }
    if (name === "files" && S.farg) { // one file opened: its details and what Jarvis read, the list only if not there yet
      const path = S.farg; S.fviewErr = null;
      const v = await api(`/api/files/view?path=${encodeURIComponent(path)}`);
      if (S.farg === path) S.fview = v;
    } else if (name === "files") { S.files = await api("/api/files"); S.filesErr = null; }
    if (name === "settings") { S.settings = await api("/api/settings"); await refreshPushState(); }
    if (name === "siri") S.siri = await api("/api/siri");
    if (name === "activity") { S.activity = await api("/api/activity", S.savedAt ? {} : { method: "POST" }); S.unread = 0; }
    if (name === "renewals" && !S.today) { S.today = await api("/api/today"); }
  } catch (e) {
    if (name === "today") S.todayErr = e.message;
    else if (name === "money") S.moneyErr = e.message;
    else if (name === "watches") S.watchErr = e.message;
    else if (name === "files" && S.farg) S.fviewErr = e.message;
    else if (name === "files") S.filesErr = e.message;
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
      catch (e) { toast(e.message); S.chatId = null; setAddress("#chat"); }
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
  if (m.role === "user") return `<div class="u">${m.file ? `<div class="fchip">${isPhoto(m.file.name) ? I.photo : I.file}<span><b>${esc(m.file.name)}</b>${esc(m.file.info || "")}</span></div>` : ""}${esc(m.text)}</div>`;
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
  // night is 9 pm to 5 am, the same as the Today screen
  const hello = hour >= 21 || hour < 5 ? "Good night" : hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const welcome = `<div class="welcome"><h2>${withName(hello)}.</h2></div>`;
  const sugg = !S.msgs.length ? `<div class="sugg">
      <button data-act="ask" data-v="Plan my day: events, tasks, bills and medicines.">Plan my day<small>events, tasks, bills</small></button>
      <button data-act="ask" data-v="How much did I spend this week, by category?">This week's spending<small>by category</small></button>
      <button data-act="ask" data-v="Which bills or renewals are coming up?">Renewals<small>next 30 days</small></button>
      <button data-act="ask" data-v="Do I have any unread important emails?">Email<small>unread & important</small></button></div>` : "";
  return `<section class="view chat">
    <div class="cbar"><button class="ib" data-act="drawer-open" aria-label="Chats">${I.menu}</button>
      <div class="ttl"><b>${esc(title)}</b><span>Qwen3.5 4B · on your ${P.host === "mac" ? "Mac" : "own computer"}</span></div>
      <button class="ib" data-act="new-chat" aria-label="New chat">${I.edit}</button></div>
    <div class="thread" id="thread">${S.msgs.length ? S.msgs.map(msgHtml).join("") : welcome}</div>
    ${sugg}
    <div class="dock">${attachChip()}<form class="composer frost" data-form="send">
      <button class="mic" id="attachBtn" type="button" data-act="attach" aria-label="Attach a file to this chat">${I.clip}</button>
      <input type="file" id="attachInput" accept="${ACCEPT}" hidden>
      <textarea id="box" rows="1" placeholder="${MIC_HINT[S.mic]}" aria-label="Message" enterkeyhint="send"></textarea>
      ${P.voice ? `<button class="mic ${S.mic}" id="micBtn" type="button" data-act="mic" aria-label="${S.mic === "rec" ? "Stop recording" : "Voice message"}" ${S.mic === "busy" ? "disabled" : ""}>${S.mic === "rec" ? I.stop : I.mic}</button>` : ""}
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
  btn.disabled = !S.streaming && !draft.trim() && !(S.attach && S.attach.id);
}

// ---------- files ----------
// The 📎 in Chat is for that chat only (like ChatGPT or Claude); More → Your files adds to what Jarvis can search.
const ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.csv,.json,.html,.htm" + (P.photos ? ",.jpg,.jpeg,.png,.webp,.heic,image/*" : "");
const sizeLabel = b => b < 1024 ? `${b} B` : b < 1048576 ? `${Math.round(b / 1024)} KB` : `${(b / 1048576).toFixed(1)} MB`;
async function upload(url, file) {
  if (file.size > 20e6) throw new Error("That file is over 20 MB.");
  if (!await reachable()) throw new Error(OFFLINE);
  let res;
  try { res = await fetch(url, { method: "POST", headers: { "X-File-Name": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" }, body: file }); }
  catch { throw new Error("Can't reach Jarvis. Check your Wi-Fi or VPN."); }
  if (res.status === 401) return toSignIn();
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
  return data;
}
function attachChip() {
  const a = S.attach;
  if (!a) return "";
  return `<div class="attached ${a.state}">${a.state === "reading" ? I.spin : isPhoto(a.name) ? I.photo : I.file}<span><b>${esc(a.name)}</b>${a.state === "reading" ? "Reading…" : esc(a.info || "")}${a.cut ? " · only the first part fits" : ""}</span>
    <button type="button" data-act="attach-remove" aria-label="Remove the file">${I.x}</button></div>`;
}
async function addMyFile(file) {
  if (!file) return;
  S.fileBusy = true; render(false);
  try { const r = await upload(`/api/files?folder=${S.fileFolder}`, file); toast(r.note); await load("files"); }
  catch (e) { toast(e.message); }
  S.fileBusy = false; render(false);
}
function viewFiles() {
  const F = S.files;
  const folders = [["documents", "Documents"], ["finance", "Finance"], ["health", "Health"], ["notes", "Notes"]];
  const label = Object.fromEntries([...folders, ["email-export", "Email exports"]]);
  const add = `<div class="card big"><div class="k">Add a file</div>
      <div class="text">Jarvis reads it now and can answer from it in any chat, naming the file. PDF, Word, ${P.photos ? "photos and scans, " : ""}text, Markdown or CSV, up to 20 MB. It stays on your computer.</div>
      <div class="k" style="margin:14px 0 8px">Put it in</div>
      <div class="seg">${folders.map(([k, n]) => `<button class="${S.fileFolder === k ? "on" : ""}" data-act="files-folder" data-v="${k}">${n}</button>`).join("")}</div>
      <button class="btn p wide" data-act="files-add" ${S.fileBusy ? "disabled" : ""}>${S.fileBusy ? "Reading the file…" : `${I.upload} Choose a file`}</button>
      <input type="file" id="filesInput" accept="${ACCEPT}" hidden>
      ${isTouch ? "" : '<div class="note">Or drop a file anywhere on this page.</div>'}</div>`;
  if (!F) return sub("Your files", `${add}${S.filesErr ? `<div class="card empty">${esc(S.filesErr)} <button class="btn s" data-act="reload">Try again</button></div>` : wskel}`);
  const lists = F.folders.filter(f => f.files.length).map(f => `<div class="sec">${label[f.folder] || f.folder} · ${f.files.length}</div><div class="card">${f.files.map(x =>
    `<div class="row tap" data-act="file-open" data-v="${esc(x.path)}" role="button" aria-label="Open ${esc(x.name)}"><span class="ic">${isPhoto(x.name) ? I.photo : I.file}</span>
      <div class="m"><div class="t">${esc(x.name)}</div><div class="s">${sizeLabel(x.size)} · ${dayLabel(x.added.slice(0, 10))} · ${fileState(x)}</div></div>
      <button class="ib" data-act="files-remove" data-v="${esc(x.path)}" aria-label="Delete ${esc(x.name)}">${I.trash}</button></div>`).join("")}</div>`).join("");
  return sub("Your files", `${add}${lists || '<div class="note">No files yet. Add your first one above.</div>'}
    <div class="note">A file you attach in Chat with the paperclip is for that chat only: it isn't added here and Jarvis doesn't keep it.</div>`);
}
const isPhoto = name => /\.(jpe?g|png|webp|heic|gif)$/i.test(name);
const fileState = x => x.searchable ? "Jarvis can search it" : x.readable ? "Not read yet" : "Jarvis can't read this kind of file";
// Quick view of one of your files: the file itself (a photo, or a PDF's pages as pictures) and the text Jarvis read in it.
function viewFile() {
  const V = S.fview && S.fview.path === S.farg ? S.fview : null;
  const name = S.farg.split("/").pop();
  const page = body => `<section class="view sub fv"><div class="navbar"><button class="back" data-act="go" data-v="files">${I.back} Your files</button><div class="title">${esc(name)}</div></div>
    <div class="scroll">${body}</div></section>`;
  if (!V) return page(S.fviewErr ? `<div class="card empty">${esc(S.fviewErr)} <button class="btn s" data-act="reload">Try again</button></div>`
    : `<div class="card big"><div class="skel" style="width:70%"></div><div class="skel"></div><div class="skel" style="width:40%"></div></div>`);
  const q = encodeURIComponent(V.path), raw = `/api/files/raw?path=${q}`, folder = { "email-export": "Email exports" }[V.folder] || V.folder[0].toUpperCase() + V.folder.slice(1);
  const shown = Math.min(V.pages || 0, S.fpages || 10);
  const preview = V.kind === "photo" ? `<img class="fpic" src="${V.picture ? `/api/files/picture?path=${q}` : raw}" alt="${esc(V.name)}">`
    : V.kind === "pdf" ? Array.from({ length: shown }, (_, i) => `<img class="fpage" loading="lazy" src="/api/files/picture?path=${q}&page=${i + 1}" alt="Page ${i + 1} of ${V.pages}">`).join("")
      + (V.pages > shown ? `<button class="btn s wide" data-act="file-more">Show more pages · ${shown} of ${V.pages}</button>` : "") : "";
  const mono = /\.(csv|json)$/i.test(V.name) ? " mono" : "";
  const read = V.error ? `<div class="err">${esc(V.error)}</div>`
    : !V.readable ? '<div class="text">Jarvis can\'t read this kind of file, so there is nothing to show here. Download it to open it on this device.</div>'
    : !V.sections.length ? '<div class="text">Jarvis found no words in this file.</div>'
    : V.sections.map(x => `${x.page && V.pages > 1 ? `<div class="k">Page ${x.page}</div>` : x.heading ? `<div class="k">${esc(x.heading)}</div>` : ""}<div class="ftext${mono}">${esc(x.text)}</div>`).join("")
      + (V.cut ? '<div class="note">Only the first part is shown here. Open the file to see all of it.</div>' : "");
  const opens = V.kind !== "other";
  const about = `<div class="card big"><div class="fname">${esc(V.name)}</div><div class="d">${esc(folder)} · ${sizeLabel(V.size)}${V.pages ? ` · ${V.pages} page${V.pages === 1 ? "" : "s"}` : ""} · ${dayLabel(V.added.slice(0, 10))}</div>
      <div class="d">${fileState(V)}</div>
      <div class="two"><a class="btn p" href="${raw}" target="_blank" rel="noopener" ${opens ? "" : `download="${esc(V.name)}"`}>${opens ? "Open" : "Download"}</a>
        <button class="btn s" data-act="files-remove" data-v="${esc(V.path)}">Delete</button></div></div>`;
  const what = V.kind === "text" ? "In this file" : V.kind === "photo" ? "Text Jarvis read in the photo" : V.kind === "pdf" ? "Text Jarvis read" : "Text";
  if (!preview) return page(`${about}<div class="sec">${what}</div><div class="card big">${read}</div>`);
  return page(`<div class="cols"><div>${about}<div class="sec">${V.kind === "pdf" ? "Pages" : "Photo"}</div><div class="fview">${preview}</div></div>
    <div><div class="sec">${what}</div><div class="card big">${read}</div></div></div>`);
}
async function attachFile(file) {
  if (!file) return;
  if (S.streaming) { toast("Wait for the reply to finish"); return; }
  S.attach = { state: "reading", name: file.name }; render(false);
  try { S.attach = { state: "ready", ...(await upload("/api/attach", file)) }; }
  catch (e) { S.attach = null; toast(e.message); }
  render(false);
}

// ---------- voice messages ----------
// The recording becomes 16 kHz WAV here in the browser, the Mac turns it into text, and the text lands in the
// message box to check before sending.
const MIC_HINT = { idle: "Ask Jarvis anything", rec: "Listening… tap ■ when done", busy: "Turning your voice into text…" };
let recording = null;
function setMic(state) {
  S.mic = state;
  const btn = $("#micBtn"), box = $("#box");
  if (box) box.placeholder = MIC_HINT[state];
  if (!btn) return;
  btn.className = `mic ${state}`; btn.disabled = state === "busy";
  btn.innerHTML = state === "rec" ? I.stop : I.mic;
  btn.setAttribute("aria-label", state === "rec" ? "Stop recording" : "Voice message");
}
async function micToggle() {
  if (recording) { recording.stop(); return; }
  if (!await reachable()) { toast(OFFLINE); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { toast("Allow the microphone for Jarvis to send voice messages"); return; }
  let recorder;
  try { recorder = new MediaRecorder(stream); recorder.start(); } // handlers below still catch every event
  catch { stream.getTracks().forEach(t => t.stop()); toast("Couldn't start recording. Try again."); return; }
  const chunks = [];
  const limit = setTimeout(() => recorder.state === "recording" && recorder.stop(), 120000); // 2 minutes at most
  recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  recorder.onstop = async () => {
    clearTimeout(limit); stream.getTracks().forEach(t => t.stop()); recording = null; setMic("busy");
    try {
      const res = await fetch("/api/voice", { method: "POST", headers: { "Content-Type": "audio/wav" },
        body: await toWav(new Blob(chunks, { type: recorder.mimeType })) });
      if (res.status === 401) return toSignIn();
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
      if (!data.text) toast("Didn't catch that. Try again a little closer to the phone.");
      else {
        const wbox = $("#wtext");
        if (wbox) { S.wtext = wbox.value = wbox.value.trim() ? `${wbox.value.trimEnd()} ${data.text}` : data.text; }
        else {
          draft = draft.trim() ? `${draft.trimEnd()} ${data.text}` : data.text;
          const box = $("#box"); if (box) { box.value = draft; autosize(box); }
          updateSend();
        }
      }
    } catch (e) { toast(e.message.startsWith("Failed to fetch") ? "Can't reach Jarvis. Check your Wi-Fi or VPN." : e.message); }
    setMic("idle");
  };
  recording = recorder; setMic("rec");
}
async function toWav(blob) { // mono 16-bit PCM at 16 kHz, what Whisper reads
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
  ctx.close();
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(audio.duration * 16000)), 16000);
  const src = off.createBufferSource(); src.buffer = audio; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const v = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const tag = (at, s) => [...s].forEach((c, i) => v.setUint8(at + i, c.charCodeAt(0)));
  tag(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); tag(8, "WAVEfmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 16000, true); v.setUint32(28, 32000, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); tag(36, "data"); v.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
  return v.buffer;
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
  const attached = S.attach && S.attach.id ? S.attach : null;
  if ((!text && !attached) || S.streaming) return;
  draft = "";
  try {
    if (!S.chatId) {
      const chat = await api("/api/chats", { method: "POST" });
      S.chatId = chat.id; S.chats.unshift(chat);
      setAddress(`#chat/${chat.id}`);
    }
    if (!await reachable()) throw new Error(OFFLINE);
  } catch (e) { toast(e.message); draft = text; render(false); return; }
  const reply = { role: "assistant", text: "", tools: [], pending: true };
  S.msgs.push({ role: "user", text: text || (attached ? "What's in this file? Give me a short summary." : ""),
    ...(attached ? { file: { name: attached.name, info: attached.info } } : {}) }, reply);
  S.attach = null;
  const controller = new AbortController();
  S.streaming = controller;
  render(false);
  try {
    const res = await fetch(`/api/chats/${encodeURIComponent(S.chatId)}/send`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, attachment: attached ? attached.id : undefined }), signal: controller.signal });
    if (res.status === 401) return toSignIn();
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
  renderSide();
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
  const head = `<div class="h1">Today</div><div class="sub">${new Date().toLocaleDateString(LOCALE, { weekday: "long", day: "numeric", month: "long" })}${T ? ` · ${withName(esc(T.greeting))}` : ""}</div>`;
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
    : !S.iphone.available && !S.iphone.off ? `<div class="row"><div class="m"><div class="s">${esc(S.iphone.reason || "iPhone Reminders unavailable")}</div></div></div>` : "";
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
  const finds = (T.watch_found || []).map(f => `<div class="card big found-card"><div class="k">Found by a watch</div>
      <div class="text"><b>${esc(f.title)}</b>: ${esc(f.summary || "")}</div>
      <div class="acts2">${f.url ? `<a class="btn p" href="${esc(f.url)}" target="_blank" rel="noopener">Book</a>` : ""}<button class="btn s" data-act="watch-open" data-v="${f.id}">Open</button><button class="btn s" data-act="watch-seen" data-v="${f.id}">Seen</button></div></div>`).join("");
  return `<section class="view"><div class="scroll">${head}${finds}<div class="cols"><div>
    <div class="card big"><div class="k">Summary</div><div class="text">${summary}.</div>
      <div class="kpis"><div class="tap" data-act="money-today" role="button"><b>${fmtMoney0(T.spent_today)}</b><span>spent today</span></div><div><b>${dueToday}</b><span>due today</span></div>
      <div><b>${iph ? iph.length : "–"}</b><span>reminders</span></div><div><b>${medsLeft}</b><span>doses left</span></div></div></div>
    ${T.calendar_errors.length ? `<div class="note">Couldn't read the ${esc(T.calendar_errors.join(" and "))} calendar, so the schedule may be incomplete.</div>` : ""}
    <div class="sec">Schedule · next 7 days</div><div class="card">${events}</div>
    </div><div>
    <div class="sec">To do</div><div class="card">${tasks}${iphRows}${iphState}${!tasks && iph && !iph.length ? '<div class="empty">Nothing to do. Nice.</div>' : ""}</div>
    <div class="sec">Medicines</div><div class="card">${meds}</div>
    ${renewals ? `<div class="sec">Bills & renewals <button data-act="go" data-v="renewals">All</button></div><div class="card">${renewals}</div>` : ""}
  </div></div></div></section>`;
}

// ---------- watches ----------
const W_KIND = { bus: ["bus", "Bus fare", "redBus"], movie: ["film", "Movie bookings", "BookMyShow"], page: ["globe", "Web page", "the page"] };
const W_EVERY = { bus: [5, 10, 15, 30], movie: [5, 10, 15, 30], page: [15, 60, 360, 1440] };
const everyLabel = m => m < 60 ? `${m} min` : m < 1440 ? `${m / 60} hour${m === 60 ? "" : "s"}` : "1 day";
const shortDay = iso => new Date(`${iso.slice(0, 10)}T00:00`).toLocaleDateString(LOCALE, { weekday: "short", day: "numeric", month: "short" });
const clock12 = hhmm => { const [h, m] = (hhmm || "00:00").split(":").map(Number); return new Date(2000, 0, 1, h, m).toLocaleTimeString(LOCALE, { hour: "numeric", minute: m ? "2-digit" : undefined }); };
const busTime = iso => new Date(iso).toLocaleTimeString(LOCALE, { hour: "numeric", minute: "2-digit" });
function checkedAgo(iso) {
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : dayLabel(iso.slice(0, 10));
}
function watchWhat(w) { // what the watch waits for
  const p = w.params;
  if (w.kind === "bus") return `${w.watch_on ? `${shortDay(w.watch_on)} · ` : ""}${clock12(p.leave_from)}–${clock12(p.leave_to)}${p.max_price ? ` · under ${fmtMoney0(p.max_price)}` : ""}`;
  if (w.kind === "movie") return `${w.watch_on ? `${shortDay(w.watch_on)} · ` : ""}${p.after && p.after !== "00:00" ? `after ${clock12(p.after)} · ` : ""}bookings open`;
  return p.what === "price" ? `Price under ${((p.sample || "").match(/^[^\d]*/) || [""])[0].trim()}${Number(p.below).toLocaleString(LOCALE)}` : `When “${p.baseline || p.sample}” changes`;
}
function savedWhat(w) {
  const p = w.params;
  if (w.kind === "bus") return `Bus${p.max_price ? ` under ${fmtMoney0(p.max_price)}` : ""} · ${clock12(p.leave_from)}–${clock12(p.leave_to)}`;
  if (w.kind === "movie") return `Bookings opening · ${(p.theatres || []).join(", ") || p.city}`;
  return watchWhat(w);
}
function watchNow(w) { // the latest check, in a few words
  const r = w.result;
  if (w.state === "paused") return "Paused";
  if (!r) return "First check in a moment…";
  if (!r.ok) return `<span style="color:var(--danger)">${esc(r.error)}</span>`;
  const now = w.kind === "movie" ? (r.open ? (r.items && r.items.length ? "Open" : "Open, not for you yet") : "Not open yet")
    : w.kind === "page" ? `Now “${esc(r.text)}”` : r.value != null ? `Now ${fmtMoney0(r.value)}` : esc(r.summary);
  return `${now}${w.checked_at ? ` · ${checkedAgo(w.checked_at)}` : ""}`;
}
function watchRow(w, section) {
  const r = w.result, broken = r && !r.ok && w.state !== "paused";
  const right = section === "found"
    ? `<div class="rt">${w.found && w.found.value != null ? `<span class="v">${fmtMoney0(w.found.value)}</span>` : ""}<span class="tag found">Found</span></div>`
    : section === "saved" ? `<button class="btn s" data-act="watch-start-open" data-v="${w.id}">Start</button>`
    : w.state === "paused" || broken ? `<div class="rt"><span class="tag ${broken ? "warn" : "dim"}">${w.state === "paused" ? "Paused" : "Check"}</span></div>` : "";
  const third = section === "found" ? esc(w.found ? w.found.text : "")
    : section === "saved" ? (w.last_on ? `Last used ${shortDay(w.last_on)}${w.last_best != null ? ` · lowest ${fmtMoney0(w.last_best)}` : ""}` : "Ready to start")
    : watchNow(w);
  return `<div class="row tap ${String(w.id) === S.warg ? "sel" : ""}" data-act="watch-open" data-v="${w.id}" role="button"><span class="ic">${I[W_KIND[w.kind][0]]}</span>
    <div class="m"><div class="t">${esc(w.title)}</div><div class="s">${esc(section === "saved" ? savedWhat(w) : watchWhat(w))}</div><div class="s">${third}</div></div>${right}</div>`;
}
const W_BACK = { act: "go", v: "watches", label: "Watches", icon: true };
const wsub = (title, body, back = W_BACK) => `<section class="view sub w"><div class="navbar"><button class="back" data-act="${back.act}" data-v="${back.v}">${back.icon ? I.back : ""} ${back.label}</button><div class="title">${esc(title)}</div></div><div class="scroll">${body}</div></section>`;
const wskel = `<div class="card big"><div class="skel" style="width:40%"></div><div class="skel" style="height:30px;width:55%"></div><div class="skel"></div></div>`;

function viewWatchesRoute() {
  const a = S.warg || "";
  const pane = /^\d+$/.test(a) ? viewWatch(a) : a.startsWith("start-") ? viewWatchStart(a.slice(6))
    : a === "form" && S.wform ? viewWatchForm() : a === "new" || a === "form" ? viewWatchNew() : "";
  if (!BIG.matches) return pane || viewWatches();
  const any = S.watches && S.watches.found.length + S.watches.watching.length + S.watches.saved.length;
  return `<section class="view md"><div class="listcol">${watchesList()}</div><div class="detail">${pane
    || `<div class="pick">${any ? "Pick a watch to see it here, or tap + for a new one." : ""}</div>`}</div></section>`;
}

const viewWatches = () => `<section class="view"><div class="scroll">${watchesList()}</div></section>`;
function watchesList() {
  const L = S.watches;
  const head = `<div class="h1 hrow">Watches<button class="ib" data-act="watch-new" aria-label="New watch">${I.plus}</button></div>`;
  if (!L) return `${head}${S.watchErr ? `<div class="card empty">${esc(S.watchErr)} <button class="btn s" data-act="reload">Try again</button></div>` : wskel}`;
  const [f, w, s] = [L.found.length, L.watching.length, L.saved.length];
  if (!f && !w && !s) return `${head}<div class="sub">Jarvis checks a bus fare, movie bookings or a price on a page for you, and tells you when it finds what you asked for.</div>
    <button class="btn p wide" data-act="watch-new">New watch</button>
    <div class="note">Like “Silk Board to Tambaram on Friday night under ₹500” or “tell me when Jailer 2 bookings open at PVR Forum on Saturday”.</div>`;
  const sec = (title, rows, kind) => rows.length ? `<div class="sec">${title}</div><div class="card">${rows.map(x => watchRow(x, kind)).join("")}</div>` : "";
  return `${head}<div class="sub">${[f && `${f} found something`, w && `${w} watching`, s && `${s} saved`].filter(Boolean).join(" · ")}</div>
    ${sec("Found something", L.found, "found")}${sec("Watching", L.watching, "watching")}${sec("Saved · start any time", L.saved, "saved")}
    <div class="note">Jarvis checks one watch at a time and only tells you when something good happens. A watch is kept after its day: start it again any time.</div>`;
}

function viewWatch(id) {
  const w = S.watch[id];
  if (!w) return wsub("Watch", wskel);
  const p = w.params, r = w.result || {}, kind = W_KIND[w.kind];
  const head = `${esc(w.title)}${w.watch_on ? ` · ${shortDay(w.watch_on)}` : ""}${w.kind === "bus" ? `, ${clock12(p.leave_from)}–${clock12(p.leave_to)}` : ""}`;
  const big = w.kind === "movie" ? (r.ok ? (r.open ? "Open" : "Not open yet") : "–") : w.kind === "page" ? esc(r.text || "–") : r.value != null ? fmtMoney0(r.value) : "–";
  const kpis = w.kind === "bus" ? [[w.lowest != null ? fmtMoney0(w.lowest) : "–", "lowest seen"], [r.count ?? "–", "buses match"], [everyLabel(w.every_minutes), "between checks"]]
    : w.kind === "movie" ? [[r.theatres_open ?? "–", "theatres open"], [r.count ?? "–", "shows for you"], [everyLabel(w.every_minutes), "between checks"]]
    : [[w.lowest != null ? w.lowest.toLocaleString(LOCALE) : "–", "lowest seen"], [everyLabel(w.every_minutes), "between checks"]];
  const items = w.kind === "bus" ? (r.items || []).slice(0, 5).map(b => `<div class="row"><div class="m"><div class="t">${esc(b.name)}</div><div class="s">${busTime(b.leaves)} · ${b.seats} seats · ${esc(b.type)}</div></div><span class="v">${fmtMoney0(b.fare)}</span></div>`).join("")
    : w.kind === "movie" ? (r.items || []).map(v => `<div class="row"><div class="m"><div class="t wrap">${esc(v.name)}</div><div class="s">${v.times.map(esc).join(" · ")}</div></div></div>`).join("") : "";
  const until = w.state === "saved" ? "Saved: start it again for another day" : w.until_at ? `${shortDay(w.until_at)}, ${busTime(w.until_at)}, then back to Saved` : "Until you pause it";
  const tell = w.kind === "bus" ? (p.max_price ? `Cheapest is under ${fmtMoney0(p.max_price)}` : "Any bus has seats") : w.kind === "movie" ? `Bookings open${(p.theatres || []).length ? ` at ${p.theatres.join(", ")}` : ""}` : watchWhat(w);
  const uses = (w.uses || []).map(u => `<div class="row"><div class="m"><div class="t">${u.watch_on ? shortDay(u.watch_on) : dayLabel(u.ended_at.slice(0, 10))}</div><div class="s">${u.found_at ? `Found at ${busTime(u.found_at)}` : "Nothing found"}</div></div>${u.best != null ? `<span class="v">${fmtMoney0(u.best)}</span>` : ""}</div>`).join("");
  return wsub(kind[1], `
    <div class="card big"><div class="k">${head}</div><div class="n">${big}</div><div class="d">${r.ok ? esc(r.summary) : r.error ? `<span style="color:var(--danger)">${esc(r.error)}</span>` : "First check in a moment…"}</div>
      ${spark(w.points)}<div class="kpis">${kpis.map(([b, s]) => `<div><b>${b}</b><span>${s}</span></div>`).join("")}</div></div>
    ${r.url ? `<a class="btn p wide" style="margin-top:12px" href="${esc(r.url)}" target="_blank" rel="noopener">${w.kind === "page" ? "Open the page" : `Book on ${kind[2]}`}</a>` : ""}
    ${w.state === "saved" ? `<button class="btn p wide" style="margin-top:10px" data-act="watch-start-open" data-v="${w.id}">Start again</button>` : ""}
    ${items ? `<div class="sec">${w.kind === "bus" ? "Cheapest now" : "Shows for you"}</div><div class="card">${items}</div>` : ""}
    <div class="sec">This watch</div><div class="card">
      <div class="row fld"><div class="m"><div class="s">Tell me when</div><div class="t">${esc(tell)}</div></div></div>
      <div class="row fld"><div class="m"><div class="s">Check every</div><div class="seg in">${W_EVERY[w.kind].map(m => `<button class="${m === w.every_minutes ? "on" : ""}" data-act="watch-every" data-v="${m}">${everyLabel(m)}</button>`).join("")}</div></div></div>
      <div class="row fld"><div class="m"><div class="s">Watching until</div><div class="t">${until}</div></div></div>
      ${w.state !== "saved" ? `<button class="row" data-act="watch-pause"><div class="m"><div class="t">Watching</div><div class="s">${w.state === "paused" ? "Paused: tap to check again" : "Tap to pause checking for now"}</div></div><span class="tog ${w.state === "paused" ? "off" : ""}"></span></button>` : ""}
      <button class="row" data-act="watch-edit" data-v="${w.id}"><div class="m"><div class="t">Change the details</div></div><span class="chev">${I.chev}</span></button>
    </div>
    ${uses ? `<div class="sec">Used before</div><div class="card">${uses}</div>` : ""}
    <div class="note">${w.checked_at ? `Last checked ${checkedAgo(w.checked_at)}` : "Not checked yet"}${w.state === "watching" && w.next_at ? ` · next at ${busTime(w.next_at)}` : ""}. You're told again only if it gets better.</div>
    <button class="danger" data-act="watch-delete">Delete watch</button>`);
}

function viewWatchNew() {
  return wsub("New watch", `
    <div class="card ask"><textarea id="wtext" rows="3" placeholder="Like: Silk Board to Tambaram on Friday night, under ₹500">${esc(S.wtext)}</textarea>
      <div class="askbar">${P.voice ? `<button class="mic ${S.mic}" id="micBtn" type="button" data-act="mic" aria-label="Voice message">${S.mic === "rec" ? I.stop : I.mic}</button>` : "<span></span>"}
      <button class="btn p" data-act="watch-fill" ${S.wbusy ? "disabled" : ""}>${S.wbusy === "fill" ? "Reading…" : "Fill in"}</button></div></div>
    <div class="hint">Say what to watch and Jarvis's AI fills in the details for you to check. Or pick a type:</div>
    <div class="sec">Pick a type</div><div class="card">
      ${[["bus", "Bus fare", "redBus · tell me when it's under a price"], ["movie", "Movie bookings", "BookMyShow · tell me when they open"], ["page", "Any web page", "A price or some words on a page"]]
        .map(([k, t, s]) => `<button class="row" data-act="watch-type" data-v="${k}"><span class="ic">${I[W_KIND[k][0]]}</span><div class="m"><div class="t">${t}</div><div class="s">${s}</div></div><span class="chev">${I.chev}</span></button>`).join("")}
    </div>
    <div class="note">Rides (BlaBlaCar) can't be watched: the site blocks automatic checks.</div>`, { act: "go", v: "watches", label: "Cancel" });
}

function wfield(label, key, value, type = "text", hint = "", list = "") {
  return `<label class="row fld"><div class="m"><div class="s">${label}</div><input data-wf="${key}" type="${type}" value="${esc(value ?? "")}" placeholder="${esc(hint)}" ${type === "number" ? 'inputmode="numeric" min="1"' : ""} ${list ? `list="${list}"` : ""} autocomplete="off"></div></label>`;
}
// Bus routes watched before: one tap fills the route, its time window and price; only the day is left to pick.
const sameRoute = (a, b) => ["from", "to", "boarding", "dropping"].every(k => (a[k] || "").trim().toLowerCase() === (b[k] || "").trim().toLowerCase());
function routeNote(r) {
  const any = (r.leave_from || "00:00") === "00:00" && (r.leave_to || "23:59") === "23:59";
  return [r.boarding && r.boarding !== r.from ? `from ${r.boarding}` : "", any ? "any time" : `${clock12(r.leave_from)}–${clock12(r.leave_to)}`,
    r.max_price ? `under ${fmtMoney0(r.max_price)}` : ""].filter(Boolean).join(" · ");
}
function pastRoutes() {
  const P2 = S.wplaces;
  if (!P2) return "";
  const lists = [["wcities", P2.cities], ["wboarding", P2.boarding], ["wdropping", P2.dropping]]
    .map(([id, names]) => `<datalist id="${id}">${(names || []).map(n => `<option value="${esc(n)}"></option>`).join("")}</datalist>`).join("");
  const chips = (P2.routes || []).slice(0, 4).map((r, i) => `<button class="${sameRoute(r, S.wform.params) ? "on" : ""}" data-act="watch-route" data-v="${i}">${esc(r.from)} → ${esc(r.to)}<small>${esc(routeNote(r))}</small></button>`).join("");
  return `${lists}${chips ? `<div class="sec" style="margin-top:6px">Your routes</div><div class="chips" style="margin-bottom:12px">${chips}</div>` : ""}`;
}

function viewWatchForm() {
  const f = S.wform, p = f.params, t = S.wtest;
  let fields = "";
  if (f.kind === "bus") fields = `${pastRoutes()}<div class="card">
    ${wfield("From (city)", "from", p.from, "text", "e.g. Bangalore", "wcities")}${wfield("Boarding point (optional)", "boarding", p.boarding, "text", "e.g. Silk Board", "wboarding")}
    ${wfield("To (city)", "to", p.to, "text", "e.g. Chennai", "wcities")}${wfield("Dropping point (optional)", "dropping", p.dropping, "text", "e.g. Tambaram", "wdropping")}
    ${wfield("Date", "day", f.day, "date")}
    <div class="row fld"><div class="m"><div class="s">Leaving between</div><div class="times"><input data-wf="leave_from" type="time" value="${esc(p.leave_from || "00:00")}"> and <input data-wf="leave_to" type="time" value="${esc(p.leave_to || "23:59")}"></div></div></div>
    ${wfield("Tell me when the cheapest is under ₹ (optional)", "max_price", p.max_price, "number", "e.g. 500")}</div>`;
  else if (f.kind === "movie") fields = `<div class="card">
    ${wfield("Movie (name or BookMyShow link)", "movie", p.movie, "text", "e.g. Jailer 2")}${wfield("City", "city", p.city, "text", "e.g. Bengaluru")}
    ${wfield("Theatres (optional, separated by commas)", "theatres", (p.theatres || []).join(", "), "text", "e.g. PVR Forum, Nexus")}
    ${wfield("Date", "day", f.day, "date")}${wfield("Shows after", "after", p.after || "00:00", "time")}</div>`;
  else {
    const opts = f.options || [];
    fields = `<div class="card">${wfield("Page link", "url", p.url, "url", "https://…")}</div>
      <button class="btn s wide" style="margin-top:10px" data-act="watch-read" ${S.wbusy ? "disabled" : ""}>${S.wbusy === "read" ? "Reading the page…" : "Read page"}</button>
      ${opts.length ? `<div class="sec">Jarvis found on this page</div><div class="card">${opts.map((o, i) => `<button class="row" data-act="watch-pick" data-v="${i}"><span class="radio ${p.selector === o.selector ? "on" : ""}"></span><div class="m"><div class="t">${o.what === "price" ? "Price" : "Words"}</div><div class="s">${esc(o.text)}</div></div></button>`).join("")}</div>`
        : f.options ? `<div class="note">Nothing to watch found on this page: no prices or words like “In stock”.</div>` : ""}
      ${p.selector ? (p.what === "price" ? `<div class="sec">Tell me when</div><div class="card">${wfield("The price is under (₹)", "below", p.below, "number", "")}</div>`
        : `<div class="note">Jarvis tells you when “${esc(p.sample)}” changes.</div>`) : ""}`;
  }
  const result = !t ? "" : !t.ok ? `<div class="card empty" id="wresult" style="margin-top:14px;color:var(--danger)">${esc(t.error)}</div>`
    : `<div class="card big" id="wresult" style="margin-top:14px"><div class="k">Test check · just now</div><div class="n">${f.kind === "movie" ? (t.open ? "Open" : "Not open yet") : f.kind === "page" ? esc(t.text) : t.value != null ? fmtMoney0(t.value) : "–"}</div><div class="d">${esc(t.summary)}${f.kind === "bus" ? ` · ${t.count} bus${t.count === 1 ? "" : "es"} match` : ""}</div>
      ${t.met ? `<div class="text">That's what you asked for: Jarvis will tell you when you save it.</div>` : `<div class="text">Not yet. Jarvis will keep checking and tell you when it is.</div>`}</div>
      ${f.kind === "bus" && t.items.length ? `<div class="card" style="margin-top:10px">${t.items.slice(0, 4).map(b => `<div class="row"><div class="m"><div class="t">${esc(b.name)}</div><div class="s">${busTime(b.leaves)} · ${b.seats} seats</div></div><span class="v">${fmtMoney0(b.fare)}</span></div>`).join("")}</div>` : ""}
      ${f.kind === "movie" && t.items.length ? `<div class="card" style="margin-top:10px">${t.items.slice(0, 4).map(v => `<div class="row"><div class="m"><div class="t wrap">${esc(v.name)}</div><div class="s">${v.times.map(esc).join(" · ")}</div></div></div>`).join("")}</div>` : ""}`;
  return wsub(W_KIND[f.kind][1], `
    ${f.filled ? `<div class="filled">${I.ok}Filled in from what you said. Check it, then test.</div>` : ""}
    ${fields}
    <div class="sec">Check every</div><div class="seg">${W_EVERY[f.kind].map(m => `<button class="${m === f.every ? "on" : ""}" data-act="watch-every-form" data-v="${m}">${everyLabel(m)}</button>`).join("")}</div>
    <div class="note" style="margin-top:4px">${f.kind === "page" ? "Checks until you pause it." : "After the day it stops checking and stays in Saved, so you can start it again for another day."}</div>
    ${result}
    <div class="two"><button class="btn s" data-act="watch-test" ${S.wbusy ? "disabled" : ""}>${S.wbusy === "test" ? "Checking…" : "Test now"}</button><button class="btn p" data-act="watch-save" ${S.wbusy ? "disabled" : ""}>${f.id ? "Save changes" : "Save watch"}</button></div>
    ${S.wbusy === "test" ? `<div class="note">A check opens the site in a browser on your computer; it takes 10–30 seconds.</div>` : ""}`,
    { act: "watch-back", v: "", label: "Back", icon: true });
}

function nextWeekday(day) { // the next date with that weekday (0 Sunday), today included
  const d = new Date(); d.setDate(d.getDate() + ((day - d.getDay() + 7) % 7));
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
function viewWatchStart(id) {
  const w = S.watch[id] || (S.watches ? [...S.watches.found, ...S.watches.watching, ...S.watches.saved].find(x => String(x.id) === id) : null);
  if (!w || !S.wstart) return wsub("Start watch", wskel);
  const st = S.wstart, tomorrow = new Date(Date.now() + 86400000);
  const iso = d => new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const days = [[iso(new Date()), "Today"], [iso(tomorrow), "Tomorrow"]];
  if (w.last_on || w.watch_on) { const same = nextWeekday(new Date(`${(w.last_on || w.watch_on)}T00:00`).getDay()); if (!days.some(d => d[0] === same)) days.push([same, new Date(`${same}T00:00`).toLocaleDateString(LOCALE, { weekday: "long" })]); }
  if (st.day && !days.some(d => d[0] === st.day)) days.push([st.day, "Picked"]);
  return wsub("Start watch", `
    <div class="card big"><div class="k">Saved watch</div><div class="text"><b>${esc(w.title)}</b><br>${esc(savedWhat(w))} · ${W_KIND[w.kind][2]}</div></div>
    ${w.kind === "movie" ? `<div class="sec">Which movie?</div><div class="card">${wfield("Movie (name or BookMyShow link)", "start_movie", st.movie ?? w.params.movie_name ?? w.params.movie, "text")}</div>` : ""}
    ${w.kind !== "page" ? `<div class="sec">Which day?</div><div class="chips">${days.map(([d, n]) => `<button class="${st.day === d ? "on" : ""}" data-act="watch-day" data-v="${d}">${n}<small>${shortDay(d)}</small></button>`).join("")}
      <label class="pick"><span>Pick a date<small>Calendar</small></span><input type="date" data-wstart="day" min="${iso(new Date())}"></label></div>` : ""}
    <div class="sec">Check every</div><div class="seg">${W_EVERY[w.kind].map(m => `<button class="${m === (st.every || w.every_minutes) ? "on" : ""}" data-act="watch-start-every" data-v="${m}">${everyLabel(m)}</button>`).join("")}</div>
    <button class="btn p wide" style="margin-top:16px" data-act="watch-start" ${S.wbusy ? "disabled" : ""}>Start watching</button>
    <button class="btn s wide" style="margin-top:10px" data-act="watch-edit" data-v="${w.id}">Change the other details</button>
    <div class="note">Everything else stays as you saved it.</div>`);
}
const blankWatch = kind => ({ kind, params: kind === "bus" ? { leave_from: "00:00", leave_to: "23:59" } : kind === "movie" ? { after: "00:00", theatres: [] } : {}, day: kind === "page" ? null : todayISO(), every: { bus: 10, movie: 15, page: 60 }[kind] });

// ---------- money ----------
function spark(points) {
  if (!points || points.length < 2) return "";
  const max = Math.max(...points, 1), w = 320, h = 46;
  const d = points.map((p, i) => `${i ? "L" : "M"}${(i / (points.length - 1) * w).toFixed(1)} ${(h - 4 - p / max * (h - 8)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="var(--text)" stroke-width="1.8" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`;
}
const moneyKey = () => `${S.period}|${S.moneyOn[S.period] || ""}`;
// The refresh button reads new bank emails now; they are also read on their own every 30 minutes.
const moneyHead = () => `<div class="h1 hrow">Money<button class="ib${S.syncing ? " busy" : ""}" data-act="money-sync" ${S.syncing ? "disabled" : ""} aria-label="Check for new payments">${S.syncing ? I.spin : I.redo}</button></div>`;
function payRow(p, showDay) {
  const when = [showDay ? dayLabel(p.on) : "", p.time, esc(p.via)].filter(Boolean).join(" · ");
  return `<div class="row"><div class="m"><div class="t">${esc(p.to || "Payment")}</div><div class="s">${when}</div></div>
    <span class="v"${p.amount < 0 ? ' style="color:var(--down)"' : ""}>${p.amount < 0 ? "−" : ""}${fmtMoney(Math.abs(p.amount)).replace(/\.00$/, "")}</span></div>`;
}
function viewMoneyCategory(m) { // one category's payments for the period on screen
  const list = m.list.filter(p => p.category === S.cat);
  const total = list.reduce((sum, p) => sum + p.amount, 0), n = list.filter(p => p.amount > 0).length;
  return `<section class="view sub"><div class="navbar"><button class="back" data-act="cat-close">${I.back} Money</button><div class="title">${esc(S.cat)}</div></div>
    <div class="scroll"><div class="card big"><div class="k">${esc(m.label)}</div><div class="n">${fmtMoney(total)}</div><div class="d">${n} payment${n === 1 ? "" : "s"}</div></div>
    <div class="sec">Payments</div><div class="card">${list.map(p => payRow(p, m.period !== "today")).join("") || '<div class="empty">No payments.</div>'}</div></div></section>`;
}
function viewMoney() {
  const m = S.money[moneyKey()];
  if (S.cat && m && S.moneyTab === "spending") return viewMoneyCategory(m);
  const pick = `<div class="seg" role="tablist">${[["spending", "Spending"], ["cards", "Cards"]].map(([k, n]) =>
    `<button class="${k === S.moneyTab ? "on" : ""}" data-act="money-tab" data-v="${k}" role="tab" aria-selected="${k === S.moneyTab}">${n}</button>`).join("")}</div>`;
  if (S.moneyTab === "cards") return viewCards(pick);
  const seg = `<div class="seg" role="tablist">${[["today", "Today"], ["week", "Week"], ["month", "Month"], ["year", "Year"]].map(([k, n]) =>
    `<button class="${k === S.period ? "on" : ""}" data-act="period" data-v="${k}" role="tab" aria-selected="${k === S.period}">${n}</button>`).join("")}</div>`;
  const head = `<div class="toprow">${moneyHead()}${pick}</div>${seg}`;
  if (!m) return `<section class="view"><div class="scroll">${head}${S.moneyErr ? `<div class="card empty">${esc(S.moneyErr)} <button class="btn s" data-act="reload">Try again</button></div>`
    : `<div class="card big"><div class="skel" style="width:35%"></div><div class="skel" style="height:30px;width:60%"></div><div class="skel"></div></div>`}</div></section>`;
  const ch = change(m.spent, m.previous, m.small);
  const prevName = { today: m.on === m.today ? "yesterday" : "the day before", week: "the week before", month: "the month before", year: "the year before" }[m.period];
  const max = Math.max(...m.categories.map(c => c.total), 1);
  const cats = m.categories.map(c => {
    const cc = change(c.total, c.previous, m.small);
    const share = m.spent > 0 ? Math.round(c.total / Math.max(m.spent, 1) * 100) : 0;
    return `<button class="catrow tap" data-act="cat" data-v="${esc(c.category)}"><div class="top"><span>${esc(c.category)}</span><b>${fmtMoney0(c.total)}</b></div>
      <div class="meta"><span>${c.payments} payment${c.payments === 1 ? "" : "s"}${share ? ` · ${share}%` : ""}</span><span style="color:${cc.startsWith("↓") ? "var(--down)" : "var(--up)"}">${cc}</span></div>
      <div class="bar"><i style="width:${Math.max(2, c.total / max * 100).toFixed(1)}%"></i></div></button>`;
  }).join("");
  const pays = (S.allPays ? m.list : m.list.slice(0, 30)).map(p => payRow(p, m.period !== "today")).join("");
  const nav = `<div class="k pernav">Spent
      <button class="arr" data-act="money-step" data-v="${m.earlier || ""}" ${m.earlier ? "" : "disabled"} aria-label="Earlier">${I.back}</button>
      <label class="when">${esc(m.label)}<input type="date" class="pick-day" value="${m.on}" max="${m.today}" aria-label="Pick a date"></label>
      <button class="arr" data-act="money-step" data-v="${m.later || ""}" ${m.later ? "" : "disabled"} aria-label="Later">${I.chev}</button></div>`;
  const unusual = m.unusual.map(u => `<div class="row"><div class="m"><div class="t">${esc(u.counterparty || "Payment")}</div><div class="s">${dayLabel(u.on)}${u.category ? ` · ${esc(u.category)}` : ""}</div></div><span class="v">${u.amount % 1 ? fmtMoney(u.amount) : fmtMoney0(u.amount)}</span></div>`).join("");
  return `<section class="view"><div class="scroll">${head}<div class="cols"><div>
    <div class="card big">${nav}<div class="n">${fmtMoney(m.spent)}</div>
      <div class="d">${ch ? `<span style="color:${ch.startsWith("↓") ? "var(--down)" : "var(--up)"}">${ch}</span> vs ${prevName} · ` : ""}${m.payments} payment${m.payments === 1 ? "" : "s"}</div>
      ${spark(m.points)}
      <div class="kpis"><div><b>${fmtMoney0(m.refunds)}</b><span>refunds</span></div><div><b>${fmtMoney0(m.received)}</b><span>received</span></div><div><b>${fmtMoney0(m.own_transfers)}</b><span>own transfers</span></div></div>
      ${m.card_bills > 0 ? `<div class="d">Card bills paid: ${fmtMoney0(m.card_bills)} · not counted again</div>` : ""}</div>
    <div class="sec">By category</div><div class="card">${cats || '<div class="empty">No payments in this period.</div>'}</div>
    ${unusual ? `<div class="sec">Unusually large</div><div class="card">${unusual}</div>` : ""}
    ${m.new_merchants.length ? `<div class="sec">New this period</div><div class="card"><div class="empty">${m.new_merchants.map(esc).join(", ")}</div></div>` : ""}
    </div><div>
    ${m.list.length ? `<div class="sec">Payments · ${m.list.length}${m.list.length > 30 && !S.allPays ? '<button data-act="all-pays">Show all</button>' : ""}</div><div class="card">${pays}</div>` : ""}
  </div></div></div></section>`;
}

function viewCards(pick) {
  const head = `<div class="toprow">${moneyHead()}${pick}</div>`;
  const c = S.cards;
  if (!c) return `<section class="view"><div class="scroll">${head}${S.moneyErr ? `<div class="card empty">${esc(S.moneyErr)} <button class="btn s" data-act="reload">Try again</button></div>`
    : `<div class="card big"><div class="skel" style="width:35%"></div><div class="skel" style="height:30px;width:60%"></div><div class="skel"></div></div>`}</div></section>`;
  if (!c.cards.length) return `<section class="view"><div class="scroll">${head}<div class="card empty">No credit cards found yet.</div></div></section>`;
  const k = c.cards.find(x => x.card === S.cardSel) || c.cards[0];
  const switcher = `<div class="seg" role="tablist">${c.cards.map(x =>
    `<button class="${x === k ? "on" : ""}" data-act="card" data-v="${esc(x.card)}" role="tab" aria-selected="${x === k}">${esc(x.bank)} ··${esc(x.last4)}</button>`).join("")}</div>`;

  let top;
  if (k.total_due === null) {
    top = `<div class="k">${esc(k.name)} ·· ${esc(k.last4)}</div><div class="n">${fmtMoney(k.purchases_total)}</div>
      <div class="d">spent in the last 30 days · bill amount is only in the statement PDF</div>
      <div class="kpis"><div><b>${fmtMoney0(k.paid)}</b><span>paid, 30 days</span></div><div><b>${k.payments.length}</b><span>payments</span></div></div>`;
  } else {
    const days = Math.round((new Date(`${k.due_on}T00:00`) - new Date(`${c.today}T00:00`)) / 864e5);
    const when = days < 0 ? `${-days} day${days === -1 ? "" : "s"} overdue` : days === 0 ? "due today" : `due in ${days} day${days === 1 ? "" : "s"}`;
    const pct = Math.min(100, k.total_due > 0 ? k.paid / k.total_due * 100 : 100);
    const status = k.left > 0
      ? `<div class="d" style="color:${days <= 3 ? "var(--up)" : "var(--text-2)"}">${dayLabel(k.due_on)} · ${when}</div>`
      : `<div class="d" style="color:var(--down)">Bill fully paid${k.extra > 0 ? ` · ${fmtMoney0(k.extra)} extra goes to the next bill` : ""}</div>`;
    top = `<div class="k">${esc(k.name)} ·· ${esc(k.last4)} · ${k.left > 0 ? "left to pay" : "this bill"}</div>
      <div class="n">${k.left > 0 ? fmtMoney(k.left) : "Paid"}</div>${status}
      <div class="bar" style="margin-top:12px"><i style="width:${pct.toFixed(1)}%;background:var(--down)"></i></div>
      <div class="kpis"><div><b>${fmtMoney0(k.total_due)}</b><span>bill</span></div><div><b>${fmtMoney0(k.paid)}</b><span>paid so far</span></div>
        <div><b>${k.min_due === null ? "–" : fmtMoney0(k.min_due)}</b><span>minimum</span></div></div>`;
  }
  const since = dayLabel(k.since);
  const pays = k.payments.map(p => `<div class="row"><div class="m"><div class="t">Part payment</div><div class="s">${dayLabel(p.date)}</div></div><span class="v">${fmtMoney0(p.amount)}</span></div>`).join("");
  const buys = k.purchases.map(b => `<div class="row"><div class="m"><div class="t">${esc(b.merchant || "Purchase")}</div><div class="s">${dayLabel(b.date)}${b.refund ? " · refund" : ""}</div></div>
    <span class="v" style="${b.refund ? "color:var(--down)" : ""}">${b.refund ? "−" : ""}${fmtMoney(b.amount).replace(/\.00$/, "")}</span></div>`).join("");
  const window_ = k.statement_on ? `since the statement (${since})` : "in the last 30 days";
  return `<section class="view"><div class="scroll">${head}${switcher}
    <div class="card big">${top}</div>
    <div class="sec">${k.statement_on ? "Payments towards this bill" : "Payments in the last 30 days"}</div><div class="card">${pays || '<div class="empty">No payments yet for this bill.</div>'}</div>
    <div class="sec">Spends ${window_} · ${fmtMoney0(k.purchases_total)}</div><div class="card">${buys || '<div class="empty">No spends on this card since then.</div>'}</div>
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
      ${row("go", "siri", I.mic, "Siri & Shortcuts", "“Hey Siri, Ask Jarvis”")}
      ${row("go", "renewals", I.renew, "Bills & renewals", M && M.next_renewal ? `Next: ${esc(M.next_renewal.item)} ${dayLabel(M.next_renewal.date)}` : "From your files")}
    </div>
    <div class="sec">Your data</div>
    <div class="card">
      ${info(I.brain, "Memory", M ? `${M.facts} facts · ${M.episodes} chat summaries${M.memory_review ? ` · ${M.memory_review} to review: reply “clean up” in chat` : ""}` : "…")}
      ${row("go", "files", I.file, "Your files", M ? `${M.documents} documents Jarvis can search · add more` : "Documents Jarvis can search")}
      ${info(I.list, "Tasks", M ? `${M.open_tasks} open Jarvis task${M.open_tasks === 1 ? "" : "s"}` : "…")}
    </div>
    ${P.signin ? `<div class="sec">Account</div>
    <div class="card">${row("sign-out", "", I.out, "Sign out", "On this device", "")}</div>` : ""}
    <div class="note">Jarvis runs on your own computer. Ask in chat “what do you know about me” to see your memory, or “forget …” to remove something.</div>
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
function viewSiri() {
  const s = S.siri;
  if (!s) return sub("Siri & Shortcuts", `<div class="card big"><div class="skel"></div><div class="skel" style="width:60%"></div></div>`);
  const key = S.siriKey;
  const top = key
    ? `<div class="text">Your Siri key, shown only now. Copy it into the Shortcut (step 3). Anyone with it can ask Jarvis, so keep it there only.</div>
       <div class="keybox">Bearer ${esc(key)}</div><button class="btn p wide" data-act="siri-copy" data-v="key">Copy the key</button>`
    : `<div class="text">Say <b>“Hey Siri, Ask Jarvis”</b>, then your question. Siri reads the answer out; one that takes longer comes as a notification. It works from the lock screen and in the car.</div>
       <button class="btn p wide" data-act="siri-new">${s.on ? "Make a new key" : "Make a Siri key"}</button>
       ${s.on ? `<div class="note">A key is set up. A new one replaces it, and the Shortcut needs the new one.</div>` : ""}`;
  return sub("Siri & Shortcuts", `
    <div class="card big"><div class="k">Ask Jarvis with Siri</div>${top}</div>
    <div class="sec">Make the Shortcut once, on this iPhone</div>
    <div class="card big"><ol class="steps">
      <li>Open the <b>Shortcuts</b> app, tap <b>+</b>, and name it <b>Ask Jarvis</b>.</li>
      <li>Add the action <b>Dictate Text</b>.</li>
      <li>Add <b>Get Contents of URL</b> with this address: <span class="keybox">${esc(s.url)}</span>
        <button class="btn s" data-act="siri-copy" data-v="url">Copy the address</button><br>
        Tap the arrow to show more: <b>Method</b> POST. <b>Headers</b>: add one, key <b>Authorization</b>, value: paste your Siri key. <b>Request Body</b> JSON: add a text field, key <b>text</b>, value <b>Dictated Text</b>.</li>
      <li>Add <b>Get Dictionary Value</b>: get <b>Value</b> for <b>reply</b> in <b>Contents of URL</b>.</li>
      <li>Add <b>Show Result</b> with the <b>Dictionary Value</b>. Siri reads it out.</li>
    </ol></div>
    <div class="note">Try it: “Hey Siri, Ask Jarvis”, then “What's on my calendar today?”. Each question is saved as a chat here.</div>
    ${s.on && !key ? `<div class="card" style="margin-top:14px"><button class="row" data-act="siri-off"><div class="m"><div class="t">Turn off the Siri key</div><div class="s">The Shortcut stops working</div></div></button></div>` : ""}`);
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
  const pick = e.target.closest(".pick-day"); // phones open the date picker on tap; desktop browsers need asking
  if (pick && !isTouch && pick.showPicker) try { pick.showPicker(); } catch { /* already open */ }
  const el = e.target.closest("[data-act]");
  if (!el) return;
  const v = el.dataset.v;
  switch (el.dataset.act) {
    // The Chat tab returns to the conversation you were in, not a blank chat.
    case "go": if (v === "money") S.cat = null; navigate(v === "chat" && S.chatId ? `#chat/${S.chatId}` : `#${v}`); break;
    case "reload": load(S.route); break;
    case "sign-out":
      if (!confirm("Sign out of Jarvis on this device?")) break;
      try { await fetch("/logout", { method: "POST" }); } catch { toast("Can't reach Jarvis. Try again when it's back."); break; }
      if ("caches" in window) await caches.delete("jarvis-data-v1").catch(() => {}); // what the screens last showed
      location.replace("/login"); break;
    case "watch-new": S.wtext = ""; S.wform = null; S.wtest = null; navigate("#watches/new"); break;
    case "watch-type": S.wform = blankWatch(v); S.wtest = null; navigate("#watches/form"); break;
    case "watch-open": navigate(`#watches/${v}`); break;
    case "watch-back": navigate(S.wform && S.wform.id ? `#watches/${S.wform.id}` : "#watches/new"); break;
    case "watch-fill": {
      const text = ($("#wtext") || {}).value || "";
      if (!text.trim()) { toast("Type or say what to watch first"); break; }
      S.wbusy = "fill"; render(false);
      try { S.wform = { ...(await api("/api/watches/fill", { method: "POST", body: { text } })), filled: true }; S.wtest = null; S.wbusy = false; navigate("#watches/form"); }
      catch (err) { S.wbusy = false; render(false); toast(err.message); }
      break;
    }
    case "watch-every-form": S.wform.every = Number(v); render(false); break;
    case "watch-route": {
      const r = S.wplaces.routes[Number(v)], f = S.wform.params;
      ["from", "to", "boarding", "dropping", "leave_from", "leave_to", "max_price", "from_id", "to_id", "from_name", "to_name"].forEach(k => delete f[k]);
      Object.assign(f, { leave_from: "00:00", leave_to: "23:59" }, r); S.wtest = null; render(false); break;
    }
    case "watch-read": {
      S.wbusy = "read"; render(false);
      try { const r = await api("/api/watches/read", { method: "POST", body: { url: S.wform.params.url } }); S.wform.options = r.options; S.wform.params.name = r.title; }
      catch (err) { toast(err.message); }
      S.wbusy = false; render(false); break;
    }
    case "watch-pick": { const o = S.wform.options[Number(v)]; Object.assign(S.wform.params, { what: o.what, selector: o.selector, sample: o.text }); S.wtest = null; render(false); break; }
    case "watch-test": {
      S.wbusy = "test"; S.wtest = null; render(false);
      try {
        const f = S.wform, r = await api("/api/watches/test", { method: "POST", body: { kind: f.kind, params: f.params, day: f.day } });
        S.wtest = r; if (r.resolved) Object.assign(f.params, r.resolved);
      } catch (err) { toast(err.message); }
      S.wbusy = false; render(false);
      const shown = $("#wresult"); if (shown) shown.scrollIntoView({ block: "center", behavior: "smooth" });
      break;
    }
    case "watch-save": {
      const f = S.wform; S.wbusy = "save"; render(false);
      try {
        const w = f.id ? await api(`/api/watches/${f.id}`, { method: "PUT", body: { params: f.params, every: f.every, day: f.day } })
          : await api("/api/watches", { method: "POST", body: { kind: f.kind, params: f.params, day: f.day, every: f.every } });
        S.wbusy = false; S.watches = null; S.wform = null; S.wtest = null; S.wplaces = null; delete S.watch[w.id];
        toast(f.id ? "Saved" : "Watching. Jarvis tells you when it finds it."); navigate(`#watches/${w.id}`);
      } catch (err) { S.wbusy = false; render(false); toast(err.message); }
      break;
    }
    case "watch-every": case "watch-pause": {
      const id = S.warg, w = S.watch[id];
      const body = el.dataset.act === "watch-every" ? { every: Number(v) } : { paused: w.state !== "paused" };
      try { S.watch[id] = { ...w, ...(await api(`/api/watches/${id}`, { method: "PUT", body })) }; S.watches = null; render(false); } catch (err) { toast(err.message); }
      break;
    }
    case "watch-delete": {
      if (!confirm("Delete this watch? Its history goes too.")) break;
      try { await api(`/api/watches/${S.warg}`, { method: "DELETE" }); delete S.watch[S.warg]; S.watches = null; toast("Watch deleted"); navigate("#watches"); } catch (err) { toast(err.message); }
      break;
    }
    case "watch-edit": {
      const w = S.watch[v] || [...(S.watches ? [...S.watches.found, ...S.watches.watching, ...S.watches.saved] : [])].find(x => String(x.id) === v);
      if (!w) break;
      S.wform = { id: w.id, kind: w.kind, params: { ...w.params }, day: w.watch_on, every: w.every_minutes, options: null }; S.wtest = null;
      navigate("#watches/form"); break;
    }
    case "watch-start-open": S.wstart = { day: null, every: null }; navigate(`#watches/start-${v}`); break;
    case "watch-day": S.wstart.day = v; render(false); break;
    case "watch-start-every": S.wstart.every = Number(v); render(false); break;
    case "watch-start": {
      const id = S.warg.slice(6), st = S.wstart, w = S.watch[id];
      if (w.kind !== "page" && !st.day) { toast("Pick the day to watch"); break; }
      S.wbusy = "start"; render(false);
      try {
        const named = st.movie && st.movie !== (w.params.movie_name || w.params.movie);
        if (named) await api(`/api/watches/${id}`, { method: "PUT", body: { params: { movie: st.movie, code: null, slug: null, city_slug: null, movie_name: null } } });
        await api(`/api/watches/${id}/start`, { method: "POST", body: { day: st.day, every: st.every } });
        S.wbusy = false; S.watches = null; delete S.watch[id]; toast("Watching again"); navigate(`#watches/${id}`);
      } catch (err) { S.wbusy = false; render(false); toast(err.message); }
      break;
    }
    case "watch-seen":
      try { await api(`/api/watches/${v}/seen`, { method: "POST" }); if (S.today) S.today.watch_found = (S.today.watch_found || []).filter(f => String(f.id) !== v); S.watches = null; render(false); } catch (err) { toast(err.message); }
      break;
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
    case "mic": micToggle(); break;
    case "attach": $("#attachInput").click(); break;
    case "attach-remove": S.attach = null; render(false); break;
    case "files-folder": S.fileFolder = v; render(false); break;
    case "files-add": $("#filesInput").click(); break;
    case "file-open": S.fview = null; S.fpages = 10; navigate(`#files/${encodeURIComponent(v)}`); break;
    case "file-more": S.fpages = (S.fpages || 10) + 10; render(false); break;
    case "files-remove": {
      if (!confirm(`Delete ${v.split("/").pop()} from your files? Jarvis will no longer find it.`)) break;
      try {
        await api(`/api/files?path=${encodeURIComponent(v)}`, { method: "DELETE" }); toast("Deleted"); S.files = null;
        if (S.farg) navigate("#files"); else load("files");
      } catch (err) { toast(err.message); }
      break;
    }
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
      u.lang = /[஀-௿]/.test(m.text) ? "ta-IN" : LOCALE;
      speechSynthesis.speak(u);
      break;
    }
    case "money-tab": S.moneyTab = v; S.cat = null; render(false); load("money"); break;
    case "card": S.cardSel = v; render(false); break;
    case "period": S.period = v; S.cat = null; S.allPays = false; render(false); load("money"); break; // cached figures show at once, then refresh
    case "money-step": S.moneyOn[S.period] = v && v < todayISO() ? v : null; S.allPays = false; render(false); load("money"); break;
    case "money-today": S.moneyTab = "spending"; S.period = "today"; S.moneyOn.today = null; S.cat = null; navigate("#money"); break;
    case "money-sync":
      if (S.syncing) break;
      S.syncing = true; render(false);
      try {
        const r = await api("/api/money/sync", { method: "POST" });
        toast(r.added ? `${r.added} new transaction${r.added === 1 ? "" : "s"} added` : "Up to date · no new payments");
        await load("money");
      } catch (err) { toast(err.message); }
      S.syncing = false; if (S.route === "money") render(false);
      break;
    case "cat": S.moneyScroll = $("#view .scroll").scrollTop; S.cat = v; render(); break;
    case "cat-close": S.cat = null; render(false); $("#view .scroll").scrollTop = S.moneyScroll || 0; break;
    case "all-pays": S.allPays = true; render(false); break;
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
    case "siri-new":
      if (S.siri.on && !confirm("Make a new Siri key? The Shortcut stops working until you paste the new one.")) break;
      try { const r = await api("/api/siri", { method: "POST" }); S.siri = r; S.siriKey = r.key; render(false); } catch (err) { toast(err.message); }
      break;
    case "siri-copy":
      try { await navigator.clipboard.writeText(v === "key" ? `Bearer ${S.siriKey}` : S.siri.url); toast("Copied"); }
      catch { toast("Couldn't copy. Press and hold the text to copy it."); }
      break;
    case "siri-off":
      if (!confirm("Turn off the Siri key? The Shortcut stops working.")) break;
      try { S.siri = await api("/api/siri", { method: "DELETE" }); S.siriKey = null; render(false); } catch (err) { toast(err.message); }
      break;
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
  if (e.target.id === "attachInput" || e.target.id === "filesInput") {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";  // choosing the same file again still counts
    if (file) (e.target.id === "attachInput" ? attachFile : addMyFile)(file);
    return;
  }
  const q = e.target.closest("[data-quiet]");
  if (q && q.value) saveSettings({ quiet: { [q.dataset.quiet]: q.value } });
  if (e.target.dataset.wstart === "day" && e.target.value && S.wstart) { S.wstart.day = e.target.value; render(false); }
  if (e.target.matches(".pick-day") && e.target.value) {
    S.moneyOn[S.period] = e.target.value < todayISO() ? e.target.value : null;
    S.allPays = false; render(false); load("money");
  }
});
document.addEventListener("input", e => {
  if (e.target.id === "box") { draft = e.target.value; autosize(e.target); updateSend(); }
  if (e.target.id === "wtext") S.wtext = e.target.value;
  const wf = e.target.dataset.wf;
  if (wf === "start_movie" && S.wstart) S.wstart.movie = e.target.value;
  else if (wf && S.wform) {
    const f = S.wform, value = e.target.value;
    if (wf === "day") f.day = value;
    else if (wf === "theatres") f.params.theatres = value.split(",").map(s => s.trim()).filter(Boolean);
    else if (wf === "max_price" || wf === "below") f.params[wf] = value ? Number(value) : null;
    else f.params[wf] = value;
    if (wf === "url") { f.options = null; delete f.params.selector; }
    if (wf === "movie") ["code", "slug", "city_slug", "movie_name"].forEach(k => delete f.params[k]);
    if (wf === "from" || wf === "to") ["from_id", "to_id", "from_name", "to_name"].forEach(k => delete f.params[k]);
  }
});
// iOS keeps the page full height under the keyboard and scrolls it instead, leaving a gap:
// while typing, size the app to the visible area so the message box sits on the keyboard.
function fitKeyboard() {
  const typing = document.body.classList.contains("typing") && window.visualViewport;
  $("#app").style.height = typing ? `${visualViewport.height}px` : "";
  if (typing) window.scrollTo(0, 0);
}
if (isTouch) {
  document.addEventListener("focusin", e => { if (e.target.id === "box") { document.body.classList.add("typing"); fitKeyboard(); } });
  document.addEventListener("focusout", e => { if (e.target.id === "box") { document.body.classList.remove("typing"); fitKeyboard(); } });
  window.visualViewport?.addEventListener("resize", fitKeyboard);
  window.visualViewport?.addEventListener("scroll", fitKeyboard);
}
// A photo or page the browser can't show (HEIC without a converter, a damaged file): say so instead of a broken image.
document.addEventListener("error", e => {
  if (!e.target.matches?.(".fpic, .fpage")) return;
  e.target.replaceWith(Object.assign(document.createElement("div"), { className: "card empty", textContent: "This can't be shown here. Open it to see it." }));
}, true);
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
  if (["today", "money", "more", "activity"].includes(S.route) || (S.route === "watches" && !/new|form|start/.test(S.warg))) load(S.route);
  else loadActivity(false).then(renderTabs).catch(() => {});
  if (S.route === "chat") refreshChat();
});
addEventListener("hashchange", () => { here = location.hash; route(); }); // the browser's Back and Forward
addEventListener("online", () => setOffline(false));
addEventListener("offline", () => setOffline(true));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
route();
// The sidebar lists your chats on every screen, so on a big screen they load at the start, not only in Chat.
const loadChatList = () => { if (BIG.matches && !S.chats.length) api("/api/chats").then(list => { S.chats = list; renderDrawer(); }).catch(() => {}); };
loadChatList();
BIG.addEventListener("change", loadChatList);
renderDrawer();
loadActivity(false).then(renderTabs).catch(() => {});
api("/api/today").then(t => { S.today = t; renderTabs(); }).catch(() => {});
setInterval(() => { if (document.visibilityState === "visible" && S.route === "watches" && !/new|form|start/.test(S.warg)) load("watches"); }, 30000);
// On a computer a file dropped on Chat is attached to that chat; dropped on Your files it is added to your files.
const dropTarget = () => ({ chat: attachFile, files: addMyFile })[S.route];
addEventListener("dragover", e => {
  if (!dropTarget() || !e.dataTransfer || !Array.from(e.dataTransfer.types).includes("Files")) return;
  e.preventDefault(); document.body.classList.add("dropping");
});
addEventListener("dragleave", e => { if (!e.relatedTarget) document.body.classList.remove("dropping"); });
addEventListener("drop", e => {
  document.body.classList.remove("dropping");
  const file = e.dataTransfer && e.dataTransfer.files[0], take = dropTarget();
  if (!file || !take) return;
  e.preventDefault(); take(file);
});
