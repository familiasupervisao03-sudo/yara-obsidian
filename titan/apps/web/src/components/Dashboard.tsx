import { useCallback, useEffect, useState } from "react";
import type { SessionInfo, SettingsView, SystemStatus } from "@titan/api-contracts";
import { api, HttpError } from "../api";
import { Panel, NotYet } from "./Panel";
import { Chat } from "./Chat";

const STATE_LABEL: Record<string, string> = {
  online: "ONLINE",
  offline: "OFFLINE",
  disabled: "DESATIVADO",
  unavailable: "INDISPONÍVEL",
  planned: "PLANEJADO",
};

export function Dashboard({
  session,
  onLogout,
  onExpired,
}: {
  session: SessionInfo;
  onLogout: () => void;
  onExpired: () => void;
}) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleError = useCallback(
    (e: unknown) => {
      if (e instanceof HttpError && e.status === 401) onExpired();
      else setError((e as Error).message);
    },
    [onExpired],
  );

  const refresh = useCallback(() => {
    Promise.all([api.status(), api.settings()])
      .then(([st, se]) => {
        setStatus(st);
        setSettings(se);
        setError(null);
      })
      .catch(handleError);
  }, [handleError]);

  useEffect(() => {
    refresh();
    // Atualização leve: a cada 60 s e só com a aba visível.
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 60_000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const budget = settings?.config.daily_paid_budget_brl;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand-row">
          <span className="brand">TITAN</span>
          <span className="muted small">{status ? `${status.phase} · v${status.version}` : "…"}</span>
        </div>
        <div className="badges">
          <span className={`badge ${status?.external_provider_active ? "badge-warn" : "badge-ok"}`}>
            {status?.external_provider_active ? "MODO HÍBRIDO" : "MODO LOCAL"}
          </span>
          <span className={`badge ${status?.paid_apis_blocked ? "badge-block" : "badge-warn"}`}>
            {!status
              ? "APIs PAGAS: …"
              : status.paid_apis_blocked
                ? `APIs PAGAS: BLOQUEADAS · R$ ${budget ?? 0}/dia`
                : `APIs PAGAS: LIBERADAS · gasto hoje R$ ${status.paid_spent_today_brl.toFixed(2)} de R$ ${status.paid_budget_brl.toFixed(2)}`}
          </span>
          <span className={`badge ${status?.external_provider_active ? "badge-warn" : "badge-block"}`}>
            {!status
              ? "MODELOS EXTERNOS: …"
              : status.external_provider_active
                ? `MODELO EXTERNO ATIVO: ${String(settings?.config.model_provider ?? "")} — conversas saem do notebook`
                : "MODELOS EXTERNOS: BLOQUEADOS"}
          </span>
        </div>
        <div className="user">
          <span className="muted small">{session.user.username}</span>
          <button className="ghost" onClick={onLogout}>Sair</button>
        </div>
      </header>

      {error && <p className="alert" role="alert">Erro: {error}</p>}

      <main className="grid">
        <Panel title="Visão geral" tag="SISTEMA" className="area-overview">
          {status ? (
            <dl className="kv">
              <dt>Fase</dt><dd>{status.phase}</dd>
              <dt>Banco</dt><dd>{String(settings?.config.database_backend ?? "…")}</dd>
              <dt>Escuta</dt><dd>{settings ? `${settings.config.host}:${settings.config.port}` : "…"}</dd>
              <dt>Auditoria</dt>
              <dd className={status.audit_chain_ok ? "ok" : "bad"}>
                {status.audit_chain_ok ? "cadeia íntegra" : "CADEIA ADULTERADA"}
              </dd>
              <dt>Exposição pública</dt><dd>nenhuma (sem túneis/portas)</dd>
            </dl>
          ) : (
            <p className="muted">Carregando…</p>
          )}
          <button className="ghost small" onClick={refresh}>Atualizar</button>
        </Panel>

        <Panel title="Serviços" tag="ESTADO" className="area-services">
          <ul className="services">
            {status?.services.map((s) => (
              <li key={s.name}>
                <span className={`dot dot-${s.state}`} aria-hidden />
                <strong>{s.name}</strong>
                <span className={`state state-${s.state}`}>{STATE_LABEL[s.state] ?? s.state}</span>
                <p className="muted small">{s.detail}</p>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Conversa" tag="CANAL" className="area-chat">
          <Chat onError={handleError} />
        </Panel>

        <Panel title="Tarefas" tag="FILA" className="area-tasks">
          <NotYet phase="FASE 2">
            Criação de tarefas, planos com etapas e critérios de sucesso ainda não foram
            implementados. Nenhuma tarefa é exibida porque nenhuma existe.
          </NotYet>
        </Panel>

        <Panel title="Autorizações" tag="APROVAÇÃO" className="area-approvals">
          <NotYet phase="FASE 2">
            Aprovações vinculadas à ação, aos parâmetros e à versão do plano serão
            registradas no servidor. Não há pedidos pendentes.
          </NotYet>
        </Panel>

        <Panel title="Histórico de execuções" tag="LAB" className="area-executions">
          <NotYet phase="FASE 3">
            A execução de código está desativada até que um sandbox isolado seja
            implementado e validado. Nenhuma execução foi realizada.
          </NotYet>
        </Panel>
      </main>
    </div>
  );
}
