import { useCallback, useEffect, useRef, useState } from "react";
import type { SessionInfo, SettingsView, SystemStatus } from "@titan/api-contracts";
import { api, HttpError } from "../api";
import { ChatView } from "./ChatView";
import { VoiceView } from "./VoiceView";
import { TasksView } from "./TasksView";
import { SystemView } from "./SystemView";
import { Home } from "./Home";
import { Icon, type IconName } from "./icons";
import { OfflineScreen } from "./OfflineScreen";
import { ShareView, type Shared } from "./ShareView";
import { notify } from "../notify";

export type View = "home" | "chat" | "voice" | "tasks" | "system";

/** Pedido para abrir a conversa num modo (vindo do Início, de um atalho ou de algo compartilhado). */
export interface ChatIntent {
  lesson?: boolean;      // abre as opções de vídeo-aula
  web?: boolean;         // liga a pesquisa na internet
  draft?: string;        // texto já escrito na caixa
  send?: boolean;        // envia o texto sem esperar
  newConversation?: boolean;
  at?: number;
}

/** Atalhos do ícone (manifest) e "Compartilhar → TITAN" chegam pelo endereço. */
function readLaunch(): { view?: View; intent?: ChatIntent; shared?: Shared } {
  const q = new URLSearchParams(window.location.search);
  const acao = q.get("acao");
  if (window.location.pathname === "/compartilhar") {
    const shared = { title: q.get("title") ?? "", text: q.get("text") ?? "", url: q.get("url") ?? "" };
    if (shared.title || shared.text || shared.url) return { shared };
  }
  if (acao === "voz") return { view: "voice" };
  if (acao === "conversa") return { view: "chat", intent: { newConversation: true } };
  if (acao === "aula") return { view: "chat", intent: { lesson: true } };
  if (acao === "aprovacoes") return { view: "tasks" };
  return {};
}

const TABS: { id: View; label: string; icon: IconName }[] = [
  { id: "home", label: "Início", icon: "home" },
  { id: "chat", label: "Conversa", icon: "chat" },
  { id: "voice", label: "Voz", icon: "mic" },
  { id: "tasks", label: "Tarefas", icon: "tasks" },
  { id: "system", label: "Sistema", icon: "system" },
];

function loadView(): View {
  try {
    const v = localStorage.getItem("titan.view");
    if (v && TABS.some((t) => t.id === v)) return v as View;
  } catch {
    /* armazenamento indisponível */
  }
  return "home";
}

export function Shell({ session, onLogout, onExpired }: {
  session: SessionInfo;
  onLogout: () => void;
  onExpired: () => void;
}) {
  const [launch] = useState(readLaunch);
  const [view, setView] = useState<View>(() => launch.view ?? loadView());
  const [chatIntent, setChatIntent] = useState<ChatIntent | null>(launch.intent ? { ...launch.intent, at: Date.now() } : null);
  const [shared, setShared] = useState<Shared | null>(launch.shared ?? null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [offline, setOffline] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chatVersion, setChatVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const seenApprovals = useRef<number | null>(null);
  const wasOffline = useRef(false);

  // Limpa o endereço do atalho/compartilhamento (recarregar não repete a ação).
  useEffect(() => {
    if (window.location.search || window.location.pathname !== "/") window.history.replaceState(null, "", "/");
  }, []);

  const handleError = useCallback((e: unknown) => {
    if (e instanceof HttpError && e.status === 401) onExpired();
    else if (e instanceof HttpError && e.status === 0) { wasOffline.current = true; setOffline(true); }
    else setError((e as Error).message);
  }, [onExpired]);

  const refresh = useCallback(() => {
    Promise.all([api.status(), api.settings(), api.approvals()])
      .then(([st, se, ap]) => {
        setStatus(st);
        setSettings(se);
        setPendingApprovals(ap.length);
        if (seenApprovals.current !== null && ap.length > seenApprovals.current) {
          notify("Aprovação pendente", ap.length === 1 ? "1 ação está esperando você aprovar."
            : `${ap.length} ações estão esperando você aprovar.`, "aprovacoes", "/?acao=aprovacoes");
        }
        seenApprovals.current = ap.length;
        setOffline(false);
        if (wasOffline.current) {
          wasOffline.current = false;
          window.dispatchEvent(new Event("titan:reconectado")); // reenvia o que ficou pendente
        }
      })
      .catch(handleError);
  }, [handleError]);

  useEffect(() => {
    refresh();
    // Visível: a cada 30 s. Em segundo plano: a cada 60 s, só para os avisos de aprovação.
    let last = Date.now();
    const id = window.setInterval(() => {
      const every = document.visibilityState === "visible" ? 30_000 : 60_000;
      if (Date.now() - last >= every) { last = Date.now(); refresh(); }
    }, 10_000);
    const online = () => refresh();
    window.addEventListener("online", online);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("online", online);
    };
  }, [refresh]);

  const openChat = (intent: ChatIntent) => {
    setShared(null);
    setChatIntent({ ...intent, at: Date.now() });
    go("chat");
  };

  const go = (v: View) => {
    setView(v);
    setError(null);
    try {
      localStorage.setItem("titan.view", v);
    } catch {
      /* ignora */
    }
  };

  const hybrid = status?.external_provider_active
    || status?.services.some((s) => s.name === "internet" && s.state === "online");

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => go("home")} aria-label="TITAN — ir para o início">TITAN</button>
        {status && (
          <span className={`badge ${hybrid ? "badge-warn" : "badge-ok"}`}>{hybrid ? "HÍBRIDO" : "LOCAL"}</span>
        )}
        {status && !status.paid_apis_blocked && (
          <span className="badge badge-neutral" title="Gasto do dia com APIs pagas">
            R$ {status.paid_spent_today_brl.toFixed(2)}/{status.paid_budget_brl.toFixed(0)}
          </span>
        )}
        <span className="spacer" />
        <span className="muted small hide-mobile">{session.user.username}</span>
        <button className="ghost small" onClick={onLogout}><Icon name="logout" size={16} /> Sair</button>
      </header>

      {offline && <OfflineScreen onRetry={refresh} />}
      {error && (
        <div className="banner banner-error" role="alert">
          {error} <button className="ghost small" onClick={() => setError(null)}>OK</button>
        </div>
      )}

      <nav className="tabs" aria-label="Seções">
        {TABS.map((t) => (
          <button key={t.id} className={`tab ${view === t.id ? "active" : ""}`} onClick={() => go(t.id)}
                  aria-current={view === t.id ? "page" : undefined}>
            <span className="tab-icon"><Icon name={t.icon} size={20} /></span>
            <span>{t.label}</span>
            {t.id === "tasks" && pendingApprovals > 0 && <span className="pill">{pendingApprovals}</span>}
          </button>
        ))}
      </nav>

      <main className={`content content-${view}`}>
        {view === "home" && (
          <Home username={session.user.username} status={status} offline={offline}
                pendingApprovals={pendingApprovals} onGo={go} onChat={openChat} onError={handleError}
                onOpenConversation={(id) => { setConversationId(id); go("chat"); }} />
        )}
        {view === "chat" && (
          <ChatView conversationId={conversationId} onConversation={setConversationId}
                    version={chatVersion} onError={handleError} intent={chatIntent}
                    onIntentDone={() => setChatIntent(null)} />
        )}
        {view === "voice" && (
          <VoiceView conversationId={conversationId} onConversation={setConversationId}
                     onTurn={() => setChatVersion((v) => v + 1)} onUseText={() => go("chat")}
                     onError={handleError} />
        )}
        {view === "tasks" && <TasksView onError={handleError} onChanged={refresh} />}
        {view === "system" && <SystemView status={status} settings={settings} onRefresh={refresh} />}
      </main>
      {shared && <ShareView shared={shared} webEnabled={settings?.config.web_enabled === true}
                            onAction={openChat} onClose={() => setShared(null)} />}
    </div>
  );
}
