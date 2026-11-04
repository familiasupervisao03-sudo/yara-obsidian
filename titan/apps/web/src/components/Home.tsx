import { useEffect, useState } from "react";
import type { Conversation, SystemStatus } from "@titan/api-contracts";
import { api } from "../api";
import { Icon } from "./icons";
import type { ChatIntent, View } from "./Shell";

// Rótulos de apresentação para os serviços informados por /system/status.
const SERVICE_LABEL: Record<string, string> = {
  database: "Banco de dados", model: "Modelo de IA", sandbox: "Laboratório de código",
  orchestrator: "Tarefas", voice: "Voz", internet: "Internet",
};
const STATE_LABEL: Record<string, string> = {
  online: "online", offline: "offline", disabled: "desativado", unavailable: "indisponível", planned: "planejado",
};

/** Centro de comando: atalhos para as funções existentes e estado real dos serviços. */
export function Home({ username, status, offline, pendingApprovals, onGo, onChat, onOpenConversation, onError }: {
  username: string;
  status: SystemStatus | null;
  offline: boolean;
  pendingApprovals: number;
  onGo: (v: View) => void;
  onChat: (intent: ChatIntent) => void;
  onOpenConversation: (id: string) => void;
  onError: (e: unknown) => void;
}) {
  const [recent, setRecent] = useState<Conversation[] | null>(null);

  useEffect(() => {
    api.conversations().then((l) => setRecent(l.items.slice(0, 4))).catch(onError);
  }, [onError]);

  const web = status?.services.some((s) => s.name === "internet" && s.state === "online");
  const mode = status?.external_provider_active
    ? "Modo híbrido · as conversas são enviadas ao provedor de IA configurado"
      + (web ? "; pesquisas que você pedir vão à internet" : "")
    : web ? "Modo híbrido · só as pesquisas que você pedir vão à internet"
      : "Modo local · tudo fica no notebook";

  return (
    <section className="home" aria-labelledby="home-title">
      <header className="home-head">
        <p className="eyebrow">Centro de comando</p>
        <h1 id="home-title" className="home-title">Olá, {username}</h1>
        <p className="muted small">{status ? mode : offline ? "Sem conexão com o notebook." : "Carregando estado…"}</p>
      </header>

      <div className="home-actions">
        <button className="action" onClick={() => onGo("voice")}>
          <span className="action-icon"><Icon name="mic" size={22} /></span>
          <span className="action-text"><strong>Falar</strong><span>Comando de voz</span></span>
        </button>
        <button className="action" onClick={() => onChat({})}>
          <span className="action-icon"><Icon name="chat" size={22} /></span>
          <span className="action-text"><strong>Escrever</strong><span>Conversa com histórico</span></span>
        </button>
        <button className="action" onClick={() => onChat({ lesson: true })}>
          <span className="action-icon"><Icon name="play" size={22} /></span>
          <span className="action-text"><strong>Aula</strong><span>Vídeo-aula na hora</span></span>
        </button>
        <button className="action" onClick={() => onChat({ web: true })} disabled={!web}
                title={web ? undefined : "Pesquisa na internet desligada (titan enable-web)"}>
          <span className="action-icon"><Icon name="globe" size={22} /></span>
          <span className="action-text"><strong>Pesquisar</strong><span>{web ? "Internet com fontes" : "Desligada"}</span></span>
        </button>
      </div>

      {status && (
        <section className="card meters" aria-label="Status do sistema">
          <h2 className="card-title">Status do sistema</h2>
          {status.services.map((sv) => (
            <div key={sv.name} className={`meter meter-${sv.state}`} title={sv.detail}>
              <span className="meter-name">{SERVICE_LABEL[sv.name] ?? sv.name}</span>
              <span className="meter-bar" aria-hidden="true">
                <i style={{ width: sv.state === "online" ? "100%" : sv.state === "unavailable" ? "35%" : "0%" }} />
              </span>
              <span className={`state state-${sv.state}`}>{STATE_LABEL[sv.state] ?? sv.state}</span>
            </div>
          ))}
          {!status.paid_apis_blocked && status.paid_budget_brl > 0 && (
            <div className="meter" title="Gasto do dia com a IA paga">
              <span className="meter-name">Orçamento hoje</span>
              <span className="meter-bar" aria-hidden="true">
                <i style={{ width: `${Math.min(100, (status.paid_spent_today_brl / status.paid_budget_brl) * 100)}%` }} />
              </span>
              <span className="state">R$ {status.paid_spent_today_brl.toFixed(2)}</span>
            </div>
          )}
        </section>
      )}

      {pendingApprovals > 0 && (
        <div className="card card-attention" role="status">
          <span>{pendingApprovals === 1 ? "1 aprovação aguardando você" : `${pendingApprovals} aprovações aguardando você`}</span>
          <button className="small" onClick={() => onGo("tasks")}>Revisar aprovações</button>
        </div>
      )}

      <div className="home-grid">
        <section className="card" aria-labelledby="home-recent">
          <header className="card-head">
            <h2 id="home-recent" className="card-title"><Icon name="history" size={16} /> Recentes</h2>
            <button className="ghost small" onClick={() => onGo("chat")}>Histórico</button>
          </header>
          {recent === null ? <p className="muted small">Carregando…</p>
            : recent.length === 0 ? <p className="muted small">Nenhuma conversa ainda.</p>
            : (
              <ul className="recent">
                {recent.map((c) => (
                  <li key={c.id}>
                    <button className="link" onClick={() => onOpenConversation(c.id)} title={c.title}>{c.title}</button>
                  </li>
                ))}
              </ul>
            )}
        </section>

      </div>
    </section>
  );
}
