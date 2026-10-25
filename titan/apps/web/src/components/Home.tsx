import { useEffect, useState } from "react";
import type { Conversation, SystemStatus } from "@titan/api-contracts";
import { api } from "../api";
import { Icon } from "./icons";
import type { View } from "./Shell";

// Rótulos de apresentação para os serviços informados por /system/status.
const SERVICE_LABEL: Record<string, string> = {
  database: "Banco de dados", model: "Modelo de IA", sandbox: "Laboratório de código",
  orchestrator: "Tarefas", voice: "Voz",
};
const STATE_LABEL: Record<string, string> = {
  online: "online", offline: "offline", disabled: "desativado", unavailable: "indisponível", planned: "planejado",
};

/** Centro de comando: atalhos para as funções existentes e estado real dos serviços. */
export function Home({ username, status, offline, pendingApprovals, onGo, onOpenConversation, onError }: {
  username: string;
  status: SystemStatus | null;
  offline: boolean;
  pendingApprovals: number;
  onGo: (v: View) => void;
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
        <button className="action" onClick={() => onGo("chat")}>
          <span className="action-icon"><Icon name="chat" size={20} /></span>
          <span className="action-text"><strong>Conversar</strong><span>Texto, com histórico</span></span>
        </button>
        <button className="action" onClick={() => onGo("voice")}>
          <span className="action-icon"><Icon name="mic" size={20} /></span>
          <span className="action-text"><strong>Modo de voz</strong><span>Falar e ouvir</span></span>
        </button>
      </div>

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

        <section className="card" aria-labelledby="home-services">
          <header className="card-head">
            <h2 id="home-services" className="card-title"><Icon name="system" size={16} /> Serviços</h2>
            <button className="ghost small" onClick={() => onGo("system")}>Configurações</button>
          </header>
          {!status ? <p className="muted small">{offline ? "Sem conexão: estado desconhecido." : "Carregando…"}</p> : (
            <ul className="svc">
              {status.services.map((s) => (
                <li key={s.name} title={s.detail}>
                  <span className={`dot dot-${s.state}`} aria-hidden />
                  <span className="svc-name">{SERVICE_LABEL[s.name] ?? s.name}</span>
                  <span className={`state state-${s.state}`}>{STATE_LABEL[s.state] ?? s.state}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </section>
  );
}
