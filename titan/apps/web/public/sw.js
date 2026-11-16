// Service worker do TITAN: guarda só a "casca" da interface para abrir rápido.
// NUNCA guarda respostas da API (conversas, tarefas, voz): elas vêm sempre do notebook.
const CACHE = "titan-shell-v3";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", "/casa", "/central", "/manifest.webmanifest", "/icon.svg"])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname === "/health" || url.pathname === "/ready") return;
  if (e.request.mode === "navigate") {
    // rede primeiro; sem rede, mostra a casca do app certo (TITAN, Casa ou Central),
    // que avisa que o notebook não respondeu e tenta de novo
    const shell = url.pathname.startsWith("/central") ? "/central" : url.pathname.startsWith("/casa") ? "/casa" : "/";
    e.respondWith(fetch(e.request).catch(() => caches.match(shell).then((hit) => hit || caches.match("/"))));
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return res;
    })));
  }
});

// Toque num aviso: abre (ou traz para frente) o TITAN na tela certa.
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) {
      if (new URL(c.url).origin === location.origin) return c.focus().then(() => c.navigate(url)).catch(() => c.focus());
    }
    return self.clients.openWindow(url);
  }));
});
