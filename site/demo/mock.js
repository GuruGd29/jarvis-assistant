// The online demo's stand-in for the Jarvis server (site/README.md). The page runs the real phone app (web/app); this
// script answers its requests from data.json, which site/demo/make_data.py recorded from a real Jarvis filled with
// made-up data. Dates are moved so "today" is today. Chat replies are written below; nothing leaves the browser.
(() => {
  const realFetch = window.fetch.bind(window);
  const DAY = 86400000;
  const pad = n => String(n).padStart(2, "0");
  const isoDay = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December"];

  // ---- the recorded screens, with every date moved forward to today ----
  const ready = realFetch("data.json").then(r => r.json()).then(raw => {
    const made = new Date(`${raw.made_on}T00:00:00`), now = new Date();
    const shift = Math.round((new Date(isoDay(now) + "T00:00:00") - made) / DAY);
    const move = s => s
      .replace(/\b(\d{4})-(\d{2})-(\d{2})(?=T|\b)/g, (m, y, mo, d) => isoDay(new Date(+y, +mo - 1, +d + shift)))
      .replace(new RegExp(`\\b(\\d{1,2}) (${MONTHS.join("|")}) (\\d{4})\\b`, "g"), (m, d, mo, y) => {
        const t = new Date(+y, MONTHS.indexOf(mo), +d + shift);
        return `${t.getDate()} ${MONTHS[t.getMonth()]} ${t.getFullYear()}`;
      });
    const walk = v => typeof v === "string" ? move(v) : Array.isArray(v) ? v.map(walk)
      : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x)])) : v;
    const screens = walk(raw.screens);
    const h = now.getHours();
    screens["/api/today"].greeting = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
    return screens;
  });

  // ---- chats ----
  const today = new Date();
  const at = (days, hh, mm) => { const d = new Date(today); d.setDate(d.getDate() - days); d.setHours(hh, mm, 0, 0); return d.toISOString(); };
  const chats = [
    { id: "welcome", title: "Welcome to the demo", preview: "This is Jarvis with made-up data…", updated_at: at(0, 9, 0), messages: [
      { role: "assistant", tools: [], text: "Hi! This is **Jarvis with made-up data**, running right in your browser. Look around: **Today**, **Money**, **Cards** and **Watches** show what Jarvis keeps for you.\n\nA few chat answers are ready to try:\n- Plan my day\n- How much did I spend this week?\n- When does my car insurance renew?\n- Remind me to call the plumber tomorrow at 10\n- What did my blood test say?\n\nYour own Jarvis answers anything, on your own computer." }] },
    { id: "insurance", title: "When does my car insurance renew?", preview: "Your car insurance renews on…", updated_at: at(2, 19, 12), messages: [] },
  ];
  let counter = 0, hidden = []; // hidden: Activity entries the last Clear took away, for Undo

  // ---- written replies: [pattern, tools, reply(screens)] ----
  const money = n => "₹" + Math.round(n).toLocaleString("en-IN");
  const REPLIES = [
    [/[஀-௿]/, [], () => "வணக்கம் Priya! இது ஒரு டெமோ, இதில் சில கேள்விகளுக்கு மட்டுமே பதில்கள் தயாராக உள்ளன. உங்கள் சொந்த Jarvis-இடம் எதை வேண்டுமானாலும் தமிழில் கேட்கலாம்."],
    [/plan|my day|today|calendar|schedule/i, ["Calendar", "Tasks"], s => {
      const t = s["/api/today"], ev = t.events.filter(e => e.day === t.date);
      const meds = t.medicines.map(m => `${m.name} at ${m.time}`).join(", ");
      return `Here's your day, Priya:\n\n${ev.map(e => `- **${e.time}** ${e.title}${e.where ? ` (${e.where})` : ""}`).join("\n")}\n- Due today: **${t.tasks[0].title}**\n- Medicines: ${meds}\n\nYou've spent ${money(t.spent_today)} so far today. Tomorrow is Deepa's birthday.`;
    }],
    [/spen|spent|money|expense|₹/i, ["Money"], s => {
      const w = s["/api/money?period=week"], cats = (w.categories || []).slice(0, 3);
      return `This week you spent **${money(w.spent)}** across ${w.payments} payments.\n\nBiggest categories:\n${cats.map(c => `- ${c.category}: ${money(c.total)}`).join("\n")}\n\nThe rent payment is the largest single one. Tap **Money** for the details.`;
    }],
    [/insur|renew|policy/i, ["Search your files"], s => {
      const r = s["/api/today"].renewals.find(x => /insurance/i.test(x.item)) || s["/api/today"].renewals[0];
      const d = new Date(r.date + "T00:00:00");
      return `Your car insurance renews on **${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}**. The premium is ${r.amount || "₹12,480"} a year, and the policy number is SSM-4471-2026.\n\nSource: car-insurance.md`;
    }],
    [/remind|task|todo|to-do/i, ["Add a task"], () => "Done: I've added **Call the plumber** for tomorrow at 10:00 am, and I'll remind you then."],
    [/blood|vitamin|test|health|doctor/i, ["Search your files"], () => "Your blood test from last month:\n\n- **Vitamin D: 18 ng/mL, LOW** (normal 30–100)\n- Haemoglobin 12.1 g/dL, just inside normal\n- HbA1c 5.4%, normal\n\nThe doctor suggested Vitamin D3 every night for 8 weeks; it's in your medicines. I summarise; I don't diagnose.\n\nSource: blood-test.md"],
    [/bus|chennai|watch|ticket/i, ["Watches"], () => "Yes: your watch found a bus from Bengaluru to Chennai for **₹649**, KPN Travels at 9:45 pm, under your ₹700 limit. Open **Watches** to see all three buses and book."],
    [/wifi|wi-fi|router/i, ["Search your files"], () => "Your home Wi-Fi is **Lakeview-3B**; the router is in the hall cupboard.\n\nSource: wifi.md"],
    [/^(hi|hello|hey|good (morning|afternoon|evening))\b/i, [], () => "Hello Priya! What can I do for you? Try **Plan my day** or **How much did I spend this week?**"],
  ];
  const FALLBACK = "This is a demo with made-up data, so only a few answers are ready. Try:\n- Plan my day\n- How much did I spend this week?\n- When does my car insurance renew?\n- Remind me to call the plumber tomorrow at 10\n- Any cheap bus to Chennai?\n\nYour own Jarvis answers anything, in your language, on your own computer.";

  function stream(question, chat, screens) {
    const [, tools, reply] = REPLIES.find(([re]) => re.test(question)) || [null, [], () => FALLBACK];
    const text = reply(screens);
    chat.messages.push({ role: "user", text: question });
    const encoder = new TextEncoder(), sleep = ms => new Promise(r => setTimeout(r, ms));
    return new ReadableStream({
      async start(controller) {
        const send = e => controller.enqueue(encoder.encode(JSON.stringify(e) + "\n"));
        for (const label of tools) { await sleep(500); send({ t: "tool", label }); }
        await sleep(400);
        for (const piece of text.match(/\S+\s*|\s+/g)) { send({ t: "delta", text: piece }); await sleep(22); }
        send({ t: "done", text });
        chat.messages.push({ role: "assistant", text, tools });
        if (chat.title === "New chat") chat.title = question.slice(0, 60);
        chat.preview = text.replace(/[*#\n-]+/g, " ").trim().slice(0, 140);
        chat.updated_at = new Date().toISOString();
        controller.close();
      },
    });
  }

  // ---- the server ----
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const NOT_HERE = msg => json({ error: msg || "That needs your own Jarvis: this demo saves nothing and sends nothing." }, 400);
  const list = () => chats.slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .map(({ id, title, preview, updated_at }) => ({ id, title, preview, updated_at }));

  async function answer(url, init) {
    const s = await ready, method = (init && init.method || "GET").toUpperCase(), path = url.pathname;
    const body = init && typeof init.body === "string" ? (() => { try { return JSON.parse(init.body); } catch { return {}; } })() : {};
    const key = path + url.search;
    let m;
    if (path === "/api/health") return json({ ok: true, database: "ok", hermes: "ok", ollama: "ok" });
    if (path === "/api/chats") {
      if (method === "POST") { const c = { id: `demo-${++counter}`, title: "New chat", preview: "", updated_at: new Date().toISOString(), messages: [] }; chats.push(c); return json(c, 201); }
      return json(list());
    }
    if ((m = path.match(/^\/api\/chats\/([^/]+)(\/send)?$/))) {
      const chat = chats.find(c => c.id === decodeURIComponent(m[1]));
      if (!chat) return json({ error: "no such chat" }, 404);
      if (m[2]) return new Response(stream(String(body.text || ""), chat, s), { headers: { "Content-Type": "application/x-ndjson" } });
      if (method === "DELETE") { chats.splice(chats.indexOf(chat), 1); return json({ ok: true }); }
      if (chat.id === "insurance" && !chat.messages.length) {
        const r = s["/api/today"].renewals[0], d = new Date(r.date + "T00:00:00");
        chat.messages.push({ role: "user", text: "When does my car insurance renew?" },
          { role: "assistant", tools: ["Search your files"], text: `Your car insurance renews on **${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}**. The premium is ₹12,480 a year.\n\nSource: car-insurance.md` });
      }
      return json({ id: chat.id, messages: chat.messages });
    }
    if (path === "/api/money") return json(s[`/api/money?period=${url.searchParams.get("period") || "week"}`] || s["/api/money?period=week"]);
    if ((m = path.match(/^\/api\/tasks\/(\d+)\/done$/))) {
      const t = s["/api/today"].tasks.find(x => x.id === +m[1]);
      if (t) t.done = !!body.done;
      return json({ id: +m[1], done: !!body.done });
    }
    if (path === "/api/medicine") {
      const med = s["/api/today"].medicines.find(x => x.medication_id === body.medication_id && x.time === body.time);
      if (med) med.status = body.status === "undo" ? "due" : body.status;
      return json(med || {});
    }
    if (path === "/api/settings" && method === "PUT") { Object.assign(s["/api/settings"], body); return json(s["/api/settings"]); }
    if (path === "/api/activity" && method === "DELETE") {
      hidden = s["/api/activity"]; s["/api/activity"] = [];
      return json({ cleared: hidden.length, undo: hidden.length ? new Date().toISOString() : null });
    }
    if (path === "/api/activity/undo") {
      const n = hidden.length; s["/api/activity"] = hidden.concat(s["/api/activity"]); hidden = [];
      return json({ restored: n });
    }
    if (path === "/api/activity") return json(s["/api/activity"]);
    if (path === "/api/siri") return method === "GET" ? json({ on: false, url: `${location.origin}/api/ask` })
      : NOT_HERE("Siri keys need your own Jarvis: in this demo nothing can be asked from outside.");
    if (path.startsWith("/api/push")) return NOT_HERE("Notifications need your own Jarvis.");
    if ((m = path.match(/^\/api\/watches\/(\d+)\/seen$/))) return json({ ok: true });
    if (method === "GET" && key in s) return json(s[key]);
    if (method === "GET" && path in s) return json(s[path]);
    return NOT_HERE();
  }

  window.fetch = (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin === location.origin && url.pathname.startsWith("/api/")) return answer(url, init);
    if (url.origin === location.origin && (url.pathname === "/" || url.pathname === "/logout")) return Promise.resolve(new Response(""));
    return realFetch(input, init);
  };

  // No service worker in the demo: nothing to keep offline, and no notifications.
  if ("serviceWorker" in navigator) navigator.serviceWorker.register = () => Promise.resolve();
  // Open the welcome chat on the first visit.
  if (!location.hash) history.replaceState(null, "", "#chat/welcome");
})();
