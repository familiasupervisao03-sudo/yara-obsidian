import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { Conversation, Message } from "@titan/api-contracts";
import { api, newRequestId } from "../api";
import { StreamingChat } from "../voice/browser";

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
    const chat = new StreamingChat(async () => cid);
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
          ☰ Conversas
        </button>
        <span className="chat-title" title={title}>{title}</span>
        <button className="small" onClick={newConversation}>+ Nova</button>
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
          <div className="msg msg-assistant">
            <span className="msg-meta">TITAN · {streaming ? "respondendo…" : "pensando…"}</span>
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
        {streaming !== null ? (
          <button type="button" className="ghost" onClick={() => abortRef.current?.abort()}>Parar</button>
        ) : (
          <button type="submit" disabled={!draft.trim()}>Enviar</button>
        )}
      </form>
    </section>
  );
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
      <p>{m.content}</p>
    </div>
  );
}
