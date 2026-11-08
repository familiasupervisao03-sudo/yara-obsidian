// Sistema → Avisos: liga os avisos do próprio aparelho (aprovação, aula pronta, resposta pronta).
// No app Android: diagnóstico (o que está ligado, última checagem) e botão de teste.
import { useEffect, useState } from "react";
import { androidApp, enableNotifications, notificationsSupported } from "../notify";

interface PhoneStatus {
  enabled: boolean; version: string; android: string; exact: boolean; battery: boolean;
  reminders: number; lastAt: number; last: string;
}

function readStatus(): PhoneStatus | null {
  const app = androidApp();
  if (!app || typeof app.notifyStatus !== "function") return null;
  try {
    const s = JSON.parse(app.notifyStatus()) as PhoneStatus;
    return typeof s.enabled === "boolean" ? s : null;
  } catch {
    return null;
  }
}

function ago(ms: number): string {
  if (!ms) return "nunca";
  const min = Math.round((Date.now() - ms) / 60_000);
  return min < 1 ? "agora" : min < 60 ? `há ${min} min` : `há ${Math.round(min / 60)} h`;
}

function PhoneDiag() {
  const app = androidApp()!;
  const [st, setSt] = useState<PhoneStatus | null>(readStatus);
  const [tested, setTested] = useState(false);
  useEffect(() => {
    const id = window.setInterval(() => setSt(readStatus()), 3000);
    return () => window.clearInterval(id);
  }, []);
  if (!st) return null;
  const row = (ok: boolean, text: string, fix?: { label: string; run: () => void }) => (
    <li className={ok ? "ok" : "warn"}>
      {ok ? "✔" : "✖"} {text}
      {!ok && fix && <> <button className="small" onClick={fix.run}>{fix.label}</button></>}
    </li>
  );
  const connected = st.last.startsWith("ok");
  return (
    <div className="phone-diag">
      <ul className="small" style={{ listStyle: "none", paddingLeft: 0, lineHeight: 1.9 }}>
        {row(st.enabled, st.enabled ? "Avisos do app ligados" : "Avisos do app DESLIGADOS no Android",
          { label: "Ligar", run: () => app.openNotifySettings?.() })}
        {row(st.battery, st.battery ? "Sem economia de bateria (app pode ficar ligado)" : "Economia de bateria pode fechar o TITAN",
          { label: "Ajustar", run: () => app.openBatterySettings?.() })}
        {row(st.exact, st.exact ? "Lembretes na hora exata" : "Lembretes podem atrasar (alarmes exatos desligados)",
          { label: "Ajustar", run: () => app.openNotifySettings?.() })}
        {row(connected, `Última conferência com o notebook: ${ago(st.lastAt)} — ${st.last}`)}
        <li className="muted">Lembretes marcados neste celular: {st.reminders} · app {st.version} · Android {st.android}</li>
      </ul>
      <button className="small" onClick={() => { app.testNotify?.(); setTested(true); }}>Testar aviso</button>
      {tested && <p className="small muted">Apareceu um aviso agora? Em 1 minuto vem outro: feche o app e bloqueie o
        celular para ver se ele chega com a tela apagada.</p>}
    </div>
  );
}

export function NotificationsPanel() {
  const supported = notificationsSupported();
  const app = androidApp();
  const [perm, setPerm] = useState<string>(app ? (app.canNotify() ? "granted" : "default")
    : supported ? Notification.permission : "unsupported");
  const diag = app && typeof app.notifyStatus === "function";
  return (
    <div className="panel">
      <h3 className="panel-title">Avisos</h3>
      {diag ? <PhoneDiag /> : !supported ? (
        <p className="small muted">Este navegador não permite avisos aqui. No celular, eles funcionam no app instalado com cadeado (HTTPS).</p>
      ) : perm === "granted" ? (
        <p className="small ok">Avisos ligados: aprovação pendente, vídeo-aula pronta e resposta pronta, quando o TITAN estiver em segundo plano.</p>
      ) : perm === "denied" ? (
        <p className="small muted">Avisos bloqueados neste navegador. Para liberar: configurações do site → Notificações → Permitir.</p>
      ) : (
        <>
          <p className="small muted">Receba um aviso quando uma aprovação estiver esperando ou uma aula/resposta ficar pronta
            com o TITAN aberto em segundo plano. Os avisos são gerados pelo próprio aparelho.</p>
          <button className="small" onClick={() => void enableNotifications().then(setPerm)}>Ativar avisos</button>
        </>
      )}
    </div>
  );
}
