import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { Conversation, Message } from "@titan/api-contracts";
import { api, newRequestId } from "../api";
import { StreamingChat, type ResearchEvent } from "../voice/browser";
import { Icon } from "./icons";

interface Pending {
  text: string;
  requestId: string;
  error?: string;
}

export function ChatView({ conversationId, onConversation, version, onError }: {
  conversationId: string | null;
  onConversation: (id: string) => void;
  version: number;
  onError: (e: unknown) => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showList, setShowList] = useState(false);
  const [webEnabled, setWebEnabled] = useState(false);
  const [webOn, setWebOn] = useState(false);
  const [research, setResearch] = useState<ResearchEvent | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const loadList = useCallback(() => {
    api.conversations().then((l) => {
      setConversations(l.items);
      if (!conversationId && l.items.length) onConversation(l.items[0].id);
    }).catch(onError);
  }, [conversationId, onConversation, onError]);

  useEffect(loadList, [loadList]);
  useEffect(() => {
    api.settings().then((v) => setWebEnabled(v.config.web_enabled === true)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!conversationId) return setMessages([]);
    api.conversation(conversationId).then((c) => setMessages(c.messages)).catch(onError);
  }, [conversationId, version, onError]);

  useEffect(() => endRef.current?.scrollIntoView({ block: "end" }), [messages, streaming]);
  useEffect(() => () => abortRef.current?.abort(), []);

  async function ensureConversation(seed: string): Promise<string> {
    if (conversationId) return conversationId;
    const c = await api.createConversation(seed.slice(0, 60) || "Conversa");
    setConversations((cs) => [c, ...cs]);
    onConversation(c.id);
    return c.id;
  }

  async function send(p: Pending) {
    setPending({ ...p, error: undefined });
    setNotice(null);
    setStreaming("");
    setResearch(null);
    const abort = new AbortController();
    abortRef.current = abort;
    let cid: string;
    try {
      cid = await ensureConversation(p.text);
    } catch (e) {
      setPending({ ...p, error: (e as Error).message });
      setStreaming(null);
      return;
    }
    const chat = new StreamingChat(async () => cid, "text",
                                   { web: webOn ? true : undefined, onResearch: setResearch });
    let acc = "";
    try {
      await chat.send(p.text, p.requestId, abort.signal, (d) => {
        acc += d;
        setStreaming(acc);
      });
      setPending(null);
    } catch (e) {
      if (abort.signal.aborted) return;
      const err = e as Error & { fatal?: boolean };
      if (err.fatal) {
        setNotice(err.message);
        setPending(null);
      } else {
        // falha de rede: a mensagem fica pendente e o reenvio usa o MESMO id (sem duplicar)
        setPending({ ...p, error: "Falha de conexão. Toque em reenviar." });
      }
    } finally {
      setStreaming(null);
      setResearch(null);
      const c = await api.conversation(cid).catch(() => null);
      if (c) setMessages(c.messages);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || streaming !== null) return;
    setDraft("");
    void send({ text, requestId: newRequestId() });
  }

  async function newConversation() {
    try {
      const c = await api.createConversation(`Conversa ${new Date().toLocaleString("pt-BR")}`);
      setConversations((cs) => [c, ...cs]);
      onConversation(c.id);
      setShowList(false);
    } catch (e) {
      onError(e);
    }
  }

  const title = conversations.find((c) => c.id === conversationId)?.title ?? "Nova conversa";

  return (
    <section className="chat-view">
      <div className="chat-header">
        <button className="ghost small" onClick={() => setShowList((s) => !s)} aria-expanded={showList}>
          <Icon name="list" size={16} /> Conversas
        </button>
        <span className="chat-title" title={title}>{title}</span>
        <button className="small" onClick={newConversation}><Icon name="plus" size={16} /> Nova</button>
      </div>
      {showList && (
        <ul className="conv-list">
          {conversations.map((c) => (
            <li key={c.id}>
              <button className={`link ${c.id === conversationId ? "active" : ""}`}
                      onClick={() => { onConversation(c.id); setShowList(false); }}>{c.title}</button>
            </li>
          ))}
          {conversations.length === 0 && <li className="muted small">Nenhuma conversa ainda.</li>}
        </ul>
      )}
      <div className="messages" aria-live="polite">
        {messages.length === 0 && streaming === null && !pending && (
          <p className="muted empty-chat">Escreva uma mensagem para começar.</p>
        )}
        {messages.map((m) => <Bubble key={m.id} m={m} />)}
        {pending && (() => {
          const last = [...messages].reverse().find((m) => m.role === "user");
          const saved = Boolean(pending.error && last && last.content === pending.text);
          return (
            <div className={`msg msg-user pending ${saved ? "retry-only" : ""}`}>
              {!saved && (
                <>
                  <span className="msg-meta">VOCÊ · {pending.error ? "não enviada" : "enviando…"}</span>
                  <p>{pending.text}</p>
                </>
              )}
              {pending.error && (
                <div className="row">
                  <span className="small bad">{saved ? "Resposta não recebida." : pending.error}</span>
                  <button className="small" onClick={() => void send(pending)}>Reenviar</button>
                </div>
              )}
            </div>
          );
        })()}
        {streaming !== null && (
          <div className={`msg msg-assistant ${streaming ? "streaming" : "thinking"}`}>
            <span className="msg-meta">TITAN · {streaming ? "respondendo…"
              : research?.status === "searching" ? "pesquisando na internet…" : "pensando…"}</span>
            {research && <ResearchLine r={research} />}
            <p>{streaming || "…"}</p>
          </div>
        )}
        {notice && <p className="notice">Sem resposta da IA: {notice}</p>}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={submit}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Mensagem para o TITAN…"
          rows={1}
          maxLength={20000}
          enterKeyHint="send"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        {webEnabled && (
          <button type="button" className={`ghost web-toggle ${webOn ? "on" : ""}`} aria-pressed={webOn}
                  title={webOn ? "Pesquisa na internet ligada para as próximas mensagens"
                    : "Pesquisar na internet (ou escreva: pesquisa na internet …)"}
                  onClick={() => setWebOn((v) => !v)}>
            <Icon name="globe" size={18} /><span className="web-label">Internet</span>
          </button>
        )}
        {streaming !== null ? (
          <button type="button" className="ghost" onClick={() => abortRef.current?.abort()}>Parar</button>
        ) : (
          <button type="submit" disabled={!draft.trim()}>Enviar</button>
        )}
      </form>
    </section>
  );
}

function ResearchLine({ r }: { r: ResearchEvent }) {
  if (r.status === "searching") return <p className="research small">Pesquisando: “{r.query}”</p>;
  if (r.status === "disabled") return <p className="research small warn">Pesquisa na internet desligada.</p>;
  if (r.status === "limited") return <p className="research small warn">{r.detail}</p>;
  if (r.status === "failed") return <p className="research small warn">A pesquisa falhou.</p>;
  if (!r.sources?.length) return <p className="research small warn">Nenhuma fonte encontrada.</p>;
  return <p className="research small">{r.sources.length} fonte(s): {r.sources.map((s) => s.site).join(", ")}</p>;
}

const FOOTER = "\n\nFontes:\n";
const SOURCE_LINE = /^\[(\d+)\] (.+) — (https?:\/\/\S+)$/;

/** Separa a lista de fontes que o servidor acrescenta às respostas pesquisadas. */
function splitSources(content: string): { body: string; sources: { n: string; title: string; url: string }[] } {
  const at = content.lastIndexOf(FOOTER);
  if (at < 0) return { body: content, sources: [] };
  const lines = content.slice(at + FOOTER.length).split("\n");
  const sources = lines.map((l) => SOURCE_LINE.exec(l)).filter((m): m is RegExpExecArray => m !== null)
    .map((m) => ({ n: m[1], title: m[2], url: m[3] }));
  if (sources.length !== lines.length) return { body: content, sources: [] };
  return { body: content.slice(0, at), sources };
}

function Bubble({ m }: { m: Message }) {
  const who = m.role === "user" ? "VOCÊ" : m.role === "assistant" ? `TITAN · ${m.model_name ?? "?"}` : "SISTEMA";
  const interrupted = m.status === "interrupted";
  return (
    <div className={`msg msg-${m.role} ${interrupted ? "interrupted" : ""}`}>
      <span className="msg-meta">
        {who} · {new Date(m.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
        {interrupted && " · interrompida"}
      </span>
      {(() => {
        const { body, sources } = m.role === "assistant" ? splitSources(m.content) : { body: m.content, sources: [] };
        return (
          <>
            <p>{body}</p>
            {sources.length > 0 && (
              <ol className="sources">
                {sources.map((s) => (
                  <li key={s.n}>
                    <span className="src-n">[{s.n}]</span>{" "}
                    <a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.title}</a>
                    <span className="src-site"> · {new URL(s.url).hostname.replace(/^www\./, "")}</span>
                  </li>
                ))}
              </ol>
            )}
          </>
        );
      })()}
    </div>
  );
}
