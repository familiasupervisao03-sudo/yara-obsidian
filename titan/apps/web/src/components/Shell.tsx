import { useCallback, useEffect, useRef, useState } from "react";
import type { SessionInfo, SettingsView, SystemStatus } from "@titan/api-contracts";
import { api, HttpError } from "../api";
import { ChatView } from "./ChatView";
import { VoiceView } from "./VoiceView";
import { CallScreen } from "./CallScreen";
import { TasksView } from "./TasksView";
import { SystemView } from "./SystemView";
import { Home } from "./Home";
import { MemoryView } from "./MemoryView";
import { NewsView } from "./NewsView";
import { brain, type Note } from "../brain";
import { syncReminders } from "../reminders";
import { Icon, type IconName } from "./icons";
import { OfflineScreen } from "./OfflineScreen";
import { ShareView, type Shared } from "./ShareView";
import { androidApp, diagNote, notify } from "../notify";
import { applyPersonal, personalApi, usePersonal, type NavId } from "../personal";
import { PersonalizeView } from "./PersonalizeView";

export type View = "home" | "chat" | "voice" | "news" | "memory" | "tasks" | "system" | "personalize";

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
function readLaunch(): { view?: View; intent?: ChatIntent; shared?: Shared; conversation?: string; call?: boolean } {
  const q = new URLSearchParams(window.location.search);
  const acao = q.get("acao");
  const conversa = q.get("conversa");
  if (conversa && /^[0-9a-f-]{36}$/.test(conversa)) return { view: "chat", conversation: conversa };
  if (acao === "inicio" || acao === "saida") return { view: "home" };
  if (acao === "memoria") return { view: "memory" };
  if (acao === "noticias") return { view: "news" };   // aviso de notícia/jornal no celular
  if (window.location.pathname === "/compartilhar") {
    const shared = { title: q.get("title") ?? "", text: q.get("text") ?? "", url: q.get("url") ?? "" };
    if (shared.title || shared.text || shared.url) return { shared };
  }
  if (acao === "ligar") return { call: true };  // ícone "Ligar TITAN" da tela inicial
  if (acao === "voz") return { view: "voice" };
  if (acao === "conversa") return { view: "chat", intent: { newConversation: true } };
  if (acao === "aula") return { view: "chat", intent: { lesson: true } };
  if (acao === "aprovacoes") return { view: "tasks" };
  return {};
}

// Barra de baixo da interface nova: 4 botões que o dono escolhe (Você → Personalizar) e a orbe
// "Falar" no meio. Padrão: Início · Conversa · orbe · Notícias · Você ("Você" junta Memória e Sistema).
type Tab = { id: View | "casa"; label: string; icon: IconName; orb?: boolean };
const NAV_TAB: Record<NavId, Tab> = {
  home: { id: "home", label: "Início", icon: "home" }, chat: { id: "chat", label: "Conversa", icon: "chat" },
  news: { id: "news", label: "Notícias", icon: "news" }, memory: { id: "memory", label: "Memória", icon: "brain" },
  system: { id: "system", label: "Você", icon: "user" }, casa: { id: "casa", label: "Casa", icon: "plug" },
};
const ORB_TAB: Tab = { id: "voice", label: "Falar", icon: "mic", orb: true };
function tabsFor(nav: NavId[]): Tab[] {
  const t = nav.map((n) => NAV_TAB[n] ?? NAV_TAB.home);
  return [t[0], t[1], ORB_TAB, t[2], t[3]];
}
const VIEWS: View[] = ["home", "chat", "voice", "news", "memory", "tasks", "system", "personalize"];

function loadView(): View {
  try {
    const v = localStorage.getItem("titan.view");
    if (v && VIEWS.includes(v as View)) return v as View;
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
  const [calling, setCalling] = useState(Boolean(launch.call));
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [offline, setOffline] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [conversationId, setConversationId] = useState<string | null>(launch.conversation ?? null);
  const [chatVersion, setChatVersion] = useState(0);
  const [homeVersion, setHomeVersion] = useState(0);
  const [toast, setToast] = useState<Note | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seenApprovals = useRef<number | null>(null);
  const wasOffline = useRef(false);
  const personal = usePersonal();
  const tabs = tabsFor(personal.nav);
  // aba acesa: Memória/Tarefas/Personalizar ficam dentro de "Você" (se a Memória não estiver na barra)
  const tabOf = (v: View): string => (v === "memory" && personal.nav.includes("memory") ? "memory"
    : v === "memory" || v === "tasks" || v === "personalize" ? "system" : v);
  useEffect(() => { personalApi.get().then(applyPersonal).catch(() => undefined); }, []);

  // Limpa o endereço do atalho/compartilhamento (recarregar não repete a ação).
  useEffect(() => {
    if (window.location.search || window.location.pathname !== "/") window.history.replaceState(null, "", "/");
  }, []);

  const handleError = useCallback((e: unknown) => {
    if (e instanceof HttpError && e.status === 401) { diagNote("login venceu (401)"); onExpired(); }
    else if (e instanceof HttpError && e.status === 0) { diagNote("sem conexão com o notebook"); wasOffline.current = true; setOffline(true); }
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
        void checkNotes();
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

  // Mensagens do TITAN: aviso no aparelho (se em segundo plano) ou faixa na tela.
  const checkNotes = useCallback(async () => {
    try {
      const notes = await brain.notes();
      if (!notes.length) return;
      const visible = document.visibilityState === "visible";
      // No app Android, os lembretes com hora já tocam pelo próprio celular (sem repetir aqui).
      const phoneAlarms = typeof (androidApp() as unknown as { scheduleReminders?: unknown } | null)?.scheduleReminders === "function";
      for (const n of notes.slice(0, 3).reverse()) {
        if (phoneAlarms && n.kind === "lembrete" && !visible) continue;
        const url = n.conversation_id ? `/?conversa=${n.conversation_id}` : "/?acao=inicio";
        if (visible) setToast(n);
        else notify(n.title.replace(/^TITAN · /, ""), n.body, `titan-${n.kind}`, url);
      }
      // no app Android, marca também a entrega geral: o aviso em segundo plano não repete no celular
      await brain.delivered(notes.map((n) => n.id), androidApp() !== null);
      setHomeVersion((v) => v + 1);
    } catch {
      /* sem mensagens agora */
    }
    syncReminders();
  }, []);

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

  if (calling) {
    return <CallScreen username={session.user.username} onClose={() => { setCalling(false); go("home"); }} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => go("home")} aria-label={`${personal.name} — ir para o início`}>{personal.name.toUpperCase()}</button>
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

      {toast && (
        <div className="banner banner-titan" role="status">
          <span><strong>{toast.title}</strong> {toast.body}</span>
          {toast.conversation_id && (
            <button className="small" onClick={() => { setConversationId(toast.conversation_id); setToast(null); go("chat"); }}>
              Responder
            </button>
          )}
          <button className="ghost small" onClick={() => setToast(null)} aria-label="Fechar">✕</button>
        </div>
      )}

      <nav className="tabs" aria-label="Seções">
        {tabs.map((t) => (
          <button key={t.id} className={`tab ${t.orb ? "tab-orb" : ""} ${tabOf(view) === t.id ? "active" : ""}`}
                  onClick={() => (t.id === "casa" ? window.location.assign("/casa") : go(t.id))}
                  aria-current={tabOf(view) === t.id ? "page" : undefined}>
            <span className="tab-icon"><Icon name={t.icon} size={20} /></span>
            {t.orb && <span className="tab-orb-ball" aria-hidden="true"><Icon name="mic" size={22} /></span>}
            <span>{t.label}</span>
            {t.id === "system" && pendingApprovals > 0 && <span className="pill">{pendingApprovals}</span>}
          </button>
        ))}
      </nav>

      <main className={`content content-${view}`}>
        {view === "home" && (
          <Home username={session.user.username} status={status} offline={offline}
                pendingApprovals={pendingApprovals} onGo={go} onChat={openChat} onError={handleError}
                version={homeVersion}
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
        {view === "news" && <NewsView onError={handleError} />}
        {view === "memory" && (
          <MemoryView onError={handleError} onOpenConversation={(id) => { setConversationId(id); go("chat"); }} />
        )}
        {view === "tasks" && <TasksView onError={handleError} onChanged={refresh} />}
        {view === "system" && <SystemView status={status} settings={settings} onRefresh={refresh}
                                          pendingApprovals={pendingApprovals} onTasks={() => go("tasks")}
                                          onMemory={() => go("memory")} onPersonalize={() => go("personalize")} />}
        {view === "personalize" && <PersonalizeView username={session.user.username} onBack={() => go("system")} />}
      </main>
      {shared && <ShareView shared={shared} webEnabled={settings?.config.web_enabled === true}
                            onAction={openChat} onClose={() => setShared(null)} />}
    </div>
  );
}
