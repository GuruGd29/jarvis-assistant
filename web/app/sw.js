// Jarvis service worker: shows push notifications, and keeps the app and what each screen last showed on the phone,
// so the app still opens (to read, not to act) when Jarvis's computer is off or out of reach.
const SHELL = "jarvis-shell-v1";
const DATA = "jarvis-data-v1";
const SHELL_FILES = ["/", "/static/app.css", "/static/app.js", "/static/icons/icon-192.png", "/manifest.webmanifest"];
// The screens' data, saved for reading offline. Chat replies, health and push always need the computer.
const SAVED_API = /^\/api\/(today|iphone-reminders|money|cards|more|settings|activity|chats)/;
// Every screen answers in well under a second when the computer is reachable (0.25 s at most, measured); when it is
// off, the phone can wait a minute for an answer that never comes. After this long the saved copy is shown.
const WAIT_MS = 4000;
const KEEP = 150; // saved answers (each money period and date is one); the oldest go first

self.addEventListener("install", event => {
  event.waitUntil(caches.open(SHELL).then(cache => cache.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== DATA).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;
  if (!url.pathname.startsWith("/api/")) event.respondWith(networkOrSaved(event, SHELL, "/"));
  else if (SAVED_API.test(url.pathname)) event.respondWith(networkOrSaved(event, DATA));
});

// Network first, so a new version and fresh data show at once. The saved copy when the network fails or is slower
// than WAIT_MS; with nothing saved, keep waiting for the network.
function networkOrSaved(event, name, fallback) {
  const network = fetch(event.request);
  event.waitUntil(network.then(response => response.ok && save(name, event.request, response.clone())).catch(() => {}));
  const saved = () => caches.open(name).then(cache => cache.match(event.request))
    .then(hit => hit || (fallback && caches.match(fallback)));
  const late = new Promise(resolve => setTimeout(resolve, WAIT_MS)).then(saved).then(hit => hit || network);
  return Promise.race([network.catch(() => saved().then(hit => hit || Promise.reject(new TypeError("offline")))), late]);
}

// Saved copies carry X-Jarvis-Saved (when they were saved), so the app can say how old what it shows is.
async function save(name, request, response) {
  const headers = new Headers(response.headers);
  headers.set("X-Jarvis-Saved", new Date().toISOString());
  const cache = await caches.open(name);
  await cache.put(request, new Response(await response.blob(), { status: response.status, headers }));
  if (name === DATA) { const keys = await cache.keys(); await Promise.all(keys.slice(0, -KEEP).map(k => cache.delete(k))); }
}

self.addEventListener("push", event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || "Jarvis", {
    body: data.body || "",
    tag: data.id ? `jarvis-${data.id}` : undefined,
    icon: "/static/icons/icon-192.png",
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const target = new URL(event.notification.data && event.notification.data.url || "/", location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    const open = list.find(c => c.url.startsWith(location.origin));
    if (open) { open.navigate(target).catch(() => {}); return open.focus(); }
    return self.clients.openWindow(target);
  }));
});
