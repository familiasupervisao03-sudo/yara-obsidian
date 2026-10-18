import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Conversation, Message, ModelStatus } from "@titan/api-contracts";
import { api, newRequestId } from "../api";

export function Chat({ onError }: { onError: (e: unknown) => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [model, setModel] = useState<ModelStatus | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  // Reutiliza a mesma chave se o envio falhar e o usuário tentar de novo,
  // para que o servidor não grave a mensagem duas vezes.
  const pending = useRef<{ text: string; id: string } | null>(null);

  useEffect(() => {
    api
      .conversations()
      .then((list) => {
        setConversations(list.items);
        if (list.items.length) setActiveId(list.items[0].id);
      })
      .catch(onError);
  }, [onError]);

  useEffect(() => {
    if (!activeId) return setMessages([]);
    api.conversation(activeId).then((c) => setMessages(c.messages)).catch(onError);
  }, [activeId, onError]);

  useEffect(() => endRef.current?.scrollIntoView({ block: "end" }), [messages]);

  async function newConversation() {
    try {
      const c = await api.createConversation(`Conversa ${new Date().toLocaleString("pt-BR")}`);
      setConversations((cs) => [c, ...cs]);
      setActiveId(c.id);
    } catch (e) {
      onError(e);
    }
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      let id = activeId;
      if (!id) {
        const c = await api.createConversation(text.slice(0, 60));
        setConversations((cs) => [c, ...cs]);
        setActiveId(c.id);
        id = c.id;
      }
      if (pending.current?.text !== text) pending.current = { text, id: newRequestId() };
      const res = await api.sendMessage(id, text, pending.current.id);
      pending.current = null;
      setMessages((ms) => [...ms, res.user_message, ...(res.reply ? [res.reply] : [])]);
      setModel(res.model);
      setDraft("");
    } catch (err) {
      onError(err);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="chat">
      <div className="chat-side">
        <button className="small" onClick={newConversation}>+ Nova</button>
        <ul>
          {conversations.map((c) => (
            <li key={c.id}>
              <button className={`link ${c.id === activeId ? "active" : ""}`} onClick={() => setActiveId(c.id)}>
                {c.title}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="chat-main">
        <div className="messages" aria-live="polite">
          {messages.length === 0 && <p className="muted">Nenhuma mensagem nesta conversa.</p>}
          {messages.map((m) => (
            <div key={m.id} className={`msg msg-${m.role}`}>
              <span className="msg-meta">
                {m.role === "user" ? "VOCÊ" : m.role === "assistant" ? `TITAN · ${m.model_name ?? "?"}` : "SISTEMA"}
                {" · "}
                {new Date(m.created_at).toLocaleTimeString("pt-BR")}
              </span>
              <p>{m.content}</p>
            </div>
          ))}
          <div ref={endRef} />
        </div>
        {model && !model.available && (
          <p className="notice">
            Mensagem salva. Sem resposta da IA: {model.detail}
          </p>
        )}
        <form className="composer" onSubmit={send}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Digite uma mensagem…"
            rows={2}
            maxLength={20000}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button type="submit" disabled={sending || !draft.trim()}>
            {sending ? "…" : "Enviar"}
          </button>
        </form>
      </div>
    </div>
  );
}
