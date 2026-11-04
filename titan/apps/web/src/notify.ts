// Avisos do celular/computador (aprovação pendente, aula pronta, resposta pronta).
// Só aparecem se você ativar em Sistema → Avisos e o TITAN estiver em segundo plano.
// São gerados pelo próprio aparelho: nada passa por servidores de terceiros.

export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window && window.isSecureContext;
}

export async function enableNotifications(): Promise<NotificationPermission | "unsupported"> {
  if (!notificationsSupported()) return "unsupported";
  return Notification.requestPermission();
}

export function notify(title: string, body: string, tag: string, url = "/"): void {
  if (!notificationsSupported() || Notification.permission !== "granted" || document.visibilityState === "visible") return;
  const opts: NotificationOptions = { body, tag, icon: "/icon-192.png", badge: "/icon-192.png", data: { url } };
  // No Android, avisos precisam passar pelo service worker; no computador, o direto também serve.
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.getRegistration().then((reg) => {
      if (reg) void reg.showNotification(`TITAN · ${title}`, opts);
      else new Notification(`TITAN · ${title}`, opts);
    }).catch(() => undefined);
  } else {
    new Notification(`TITAN · ${title}`, opts);
  }
}
