// Jarvis service worker: shows push notifications and keeps the app shell available offline.
// API calls always go to the network, so data on screen is never stale.
const SHELL = "jarvis-shell-v1";
const SHELL_FILES = ["/", "/static/app.css", "/static/app.js", "/static/icons/icon-192.png", "/manifest.webmanifest"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(SHELL).then(cache => cache.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Network first, so a new version shows at once; the cached shell only when offline.
  event.respondWith(fetch(event.request)
    .then(response => {
      if (response.ok) { const copy = response.clone(); caches.open(SHELL).then(c => c.put(event.request, copy)); }
      return response;
    })
    .catch(() => caches.match(event.request).then(hit => hit || caches.match("/"))));
});

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
