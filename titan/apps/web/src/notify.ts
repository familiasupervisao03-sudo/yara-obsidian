// Avisos do celular/computador (aprovação pendente, aula pronta, resposta pronta).
// Só aparecem se você ativar em Sistema → Avisos e o TITAN estiver em segundo plano.
// São gerados pelo próprio aparelho: nada passa por servidores de terceiros.
// Dentro do app Android do TITAN, usam os avisos do sistema (ponte "TitanAndroid").

interface AndroidBridge {
  isApp(): boolean;
  keepAwake(on: boolean): void;
  canNotify(): boolean;
  askNotify(): void;
  notify(title: string, body: string, path: string): void;
  // app 1.8+: diagnóstico dos avisos
  notifyStatus?(): string;
  testNotify?(): void;
  openNotifySettings?(): void;
  openBatterySettings?(): void;
}

export function androidApp(): AndroidBridge | null {
  const b = (window as unknown as { TitanAndroid?: AndroidBridge }).TitanAndroid;
  return b && typeof b.isApp === "function" ? b : null;
}

export function notificationsSupported(): boolean {
  if (androidApp()) return true;
  return typeof window !== "undefined" && "Notification" in window && window.isSecureContext;
}

export async function enableNotifications(): Promise<NotificationPermission | "unsupported"> {
  const app = androidApp();
  if (app) {
    app.askNotify();
    await new Promise((r) => setTimeout(r, 1500));
    return app.canNotify() ? "granted" : "default";
  }
  if (!notificationsSupported()) return "unsupported";
  return Notification.requestPermission();
}

export function notify(title: string, body: string, tag: string, url = "/"): void {
  const app = androidApp();
  if (app) {
    if (document.visibilityState !== "visible" && app.canNotify()) app.notify(title, body, url);
    return;
  }
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
