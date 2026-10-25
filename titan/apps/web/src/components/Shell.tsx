import { useCallback, useEffect, useState } from "react";
import type { SessionInfo, SettingsView, SystemStatus } from "@titan/api-contracts";
import { api, HttpError } from "../api";
import { ChatView } from "./ChatView";
import { VoiceView } from "./VoiceView";
import { TasksView } from "./TasksView";
import { SystemView } from "./SystemView";
import { Home } from "./Home";
import { Icon, type IconName } from "./icons";

export type View = "home" | "chat" | "voice" | "tasks" | "system";

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
  const [view, setView] = useState<View>(loadView);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [offline, setOffline] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chatVersion, setChatVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const handleError = useCallback((e: unknown) => {
    if (e instanceof HttpError && e.status === 401) onExpired();
    else if (e instanceof HttpError && e.status === 0) setOffline(true);
    else setError((e as Error).message);
  }, [onExpired]);

  const refresh = useCallback(() => {
    Promise.all([api.status(), api.settings(), api.approvals()])
      .then(([st, se, ap]) => {
        setStatus(st);
        setSettings(se);
        setPendingApprovals(ap.length);
        setOffline(false);
      })
      .catch(handleError);
  }, [handleError]);

  useEffect(() => {
    refresh();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 30_000);
    const online = () => refresh();
    window.addEventListener("online", online);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("online", online);
    };
  }, [refresh]);

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

      {offline && (
        <div className="banner banner-warn" role="status">
          Sem conexão com o notebook. Suas mensagens não se perdem; reconectando…
          <button className="ghost small" onClick={refresh}>Tentar agora</button>
        </div>
      )}
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
                pendingApprovals={pendingApprovals} onGo={go} onError={handleError}
                onOpenConversation={(id) => { setConversationId(id); go("chat"); }} />
        )}
        {view === "chat" && (
          <ChatView conversationId={conversationId} onConversation={setConversationId}
                    version={chatVersion} onError={handleError} />
        )}
        {view === "voice" && (
          <VoiceView conversationId={conversationId} onConversation={setConversationId}
                     onTurn={() => setChatVersion((v) => v + 1)} onUseText={() => go("chat")}
                     onError={handleError} />
        )}
        {view === "tasks" && <TasksView onError={handleError} onChanged={refresh} />}
        {view === "system" && <SystemView status={status} settings={settings} onRefresh={refresh} />}
      </main>
    </div>
  );
}
