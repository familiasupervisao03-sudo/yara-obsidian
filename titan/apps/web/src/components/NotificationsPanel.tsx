// Sistema → Avisos: liga os avisos do próprio aparelho (aprovação, aula pronta, resposta pronta).
import { useState } from "react";
import { androidApp, enableNotifications, notificationsSupported } from "../notify";

export function NotificationsPanel() {
  const supported = notificationsSupported();
  const app = androidApp();
  const [perm, setPerm] = useState<string>(app ? (app.canNotify() ? "granted" : "default")
    : supported ? Notification.permission : "unsupported");
  return (
    <div className="panel">
      <h3 className="panel-title">Avisos</h3>
      {!supported ? (
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
