import type { SettingsView, SystemStatus } from "@titan/api-contracts";

const STATE_LABEL: Record<string, string> = {
  online: "ONLINE", offline: "OFFLINE", disabled: "DESATIVADO", unavailable: "INDISPONÍVEL", planned: "PLANEJADO",
};

export function SystemView({ status, settings, onRefresh }: {
  status: SystemStatus | null;
  settings: SettingsView | null;
  onRefresh: () => void;
}) {
  if (!status) return <p className="muted">Carregando…</p>;
  const c = settings?.config ?? {};
  return (
    <section className="system-view">
      <div className="row between">
        <h2 className="section-title">Sistema</h2>
        <button className="ghost small" onClick={onRefresh}>Atualizar</button>
      </div>
      <div className="panel">
        <dl className="kv">
          <dt>Versão</dt><dd>{status.phase} · v{status.version}</dd>
          <dt>Banco</dt><dd>{String(c.database_backend ?? "?")}</dd>
          <dt>Escuta</dt><dd>{String(c.host ?? "?")}:{String(c.port ?? "?")}</dd>
          <dt>Auditoria</dt>
          <dd className={status.audit_chain_ok ? "ok" : "bad"}>{status.audit_chain_ok ? "íntegra" : "ADULTERADA"}</dd>
          <dt>APIs pagas</dt>
          <dd>{status.paid_apis_blocked ? "bloqueadas (R$ 0/dia)"
            : `liberadas · gasto hoje R$ ${status.paid_spent_today_brl.toFixed(2)} de R$ ${status.paid_budget_brl.toFixed(2)}`}</dd>
          <dt>Modelo externo</dt>
          <dd>{status.external_provider_active ? `${String(c.model_provider)} — conversas saem do notebook` : "nenhum"}</dd>
          <dt>Exposição pública</dt><dd>nenhuma (sem túneis nem portas abertas)</dd>
        </dl>
      </div>
      <div className="panel">
        <h3 className="panel-title">Serviços</h3>
        <ul className="services">
          {status.services.map((s) => (
            <li key={s.name}>
              <span className={`dot dot-${s.state}`} aria-hidden />
              <strong>{s.name}</strong>
              <span className={`state state-${s.state}`}>{STATE_LABEL[s.state] ?? s.state}</span>
              <p className="muted small">{s.detail}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
