import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { Conversation, Lesson, LessonLength, LessonLevel, LessonOptions, Message } from "@titan/api-contracts";
import { api, newRequestId } from "../api";
import { StreamingChat, type ResearchEvent } from "../voice/browser";
import { Icon } from "./icons";
import { LessonPlayer } from "./LessonPlayer";
import type { ChatIntent } from "./Shell";
import { notify } from "../notify";

const LESSON_MARKER = "▶ Vídeo-aula: ";
// Mesmo critério do servidor (titan/lessons/script.py): pedido explícito de vídeo-aula.
const LESSON_REQUEST = new RegExp(
  "(?:^|[^\\p{L}])(?:v[íi]deo[\\s-]?aula|aula\\s+(?:animada|em\\s+v[íi]deo)|" +
  "(?:explic|ensin|mostr)\\p{L}*(?:\\s+\\S+){0,6}?\\s+em\\s+(?:um\\s+)?v[íi]deo|" +
  "(?:fa[zç]|cri|mont|gera)\\p{L}*\\s+(?:uma?\\s+)?(?:v[íi]deo|aula)(?:\\s+explicativ[oa])?\\s+(?:sobre|de|explicando))",
  "iu");
export const wantsLesson = (text: string) => LESSON_REQUEST.test(text);

interface LessonPrefs { level: LessonLevel; length: LessonLength }
function loadLessonPrefs(): LessonPrefs {
  try {
    const v = JSON.parse(localStorage.getItem("titan.lesson") ?? "{}");
    return { level: v.level ?? "basico", length: v.length ?? "normal" };
  } catch {
    return { level: "basico", length: "normal" };
  }
}

interface Pending {
  text: string;
  requestId: string;
  error?: string;
}

export function ChatView({ conversationId, onConversation, version, onError, intent, onIntentDone }: {
  conversationId: string | null;
  onConversation: (id: string | null) => void;
  version: number;
  onError: (e: unknown) => void;
  intent?: ChatIntent | null;
  onIntentDone?: () => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  pendingRef.current = pending;
  const [notice, setNotice] = useState<string | null>(null);
  const [showList, setShowList] = useState(false);
  const [webEnabled, setWebEnabled] = useState(false);
  const [webOn, setWebOn] = useState(false);
  const [research, setResearch] = useState<ResearchEvent | null>(null);
  const [lesson, setLesson] = useState<{ lesson: Lesson; conversationId: string; messageId: string } | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [lessonPrefs, setLessonPrefs] = useState<LessonPrefs>(loadLessonPrefs);
  const [lessonPanel, setLessonPanel] = useState(false);
  const [videoReply, setVideoReply] = useState(true);
  // Logo depois de uma aula, a próxima pergunta ou teoria continua em vídeo (dá para desligar).
  const lastMsg = messages[messages.length - 1];
  const lastLesson = lastMsg && lastMsg.role === "assistant" && lastMsg.content.startsWith(LESSON_MARKER) ? lastMsg : null;
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
    try { localStorage.setItem("titan.lesson", JSON.stringify(lessonPrefs)); } catch { /* ignora */ }
  }, [lessonPrefs]);
  useEffect(() => setVideoReply(true), [lastLesson?.id]);

  // Pedido vindo do Início, de um atalho do ícone ou de algo compartilhado.
  useEffect(() => {
    if (!intent) return;
    onIntentDone?.();
    if (intent.web) setWebOn(true);
    if (intent.lesson) setLessonPanel(true);
    if (intent.newConversation && !intent.send) onConversation(null);
    const text = intent.draft?.trim() ?? "";
    if (!text) return;
    if (!intent.send) { setDraft(intent.draft ?? ""); return; }
    if (wantsLesson(text)) void sendLesson(text, intent.web ? { web: true } : {}, Boolean(intent.newConversation));
    else void send({ text, requestId: newRequestId() }, { forceNew: intent.newConversation, web: intent.web });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent?.at]);

  // O notebook voltou: reenvia sozinha a mensagem que ficou pendente (mesmo id, sem duplicar).
  useEffect(() => {
    const again = () => { if (pendingRef.current?.error) void send(pendingRef.current); };
    window.addEventListener("titan:reconectado", again);
    return () => window.removeEventListener("titan:reconectado", again);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    api.settings().then((v) => setWebEnabled(v.config.web_enabled === true)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!conversationId) return setMessages([]);
    api.conversation(conversationId).then((c) => setMessages(c.messages)).catch(onError);
  }, [conversationId, version, onError]);

  useEffect(() => endRef.current?.scrollIntoView({ block: "end" }), [messages, streaming]);
  useEffect(() => () => abortRef.current?.abort(), []);

  async function ensureConversation(seed: string, forceNew = false): Promise<string> {
    if (conversationId && !forceNew) return conversationId;
    const c = await api.createConversation(seed.slice(0, 60) || "Conversa");
    setConversations((cs) => [c, ...cs]);
    onConversation(c.id);
    return c.id;
  }

  async function send(p: Pending, opts: { forceNew?: boolean; web?: boolean } = {}) {
    setPending({ ...p, error: undefined });
    setNotice(null);
    setStreaming("");
    setResearch(null);
    const abort = new AbortController();
    abortRef.current = abort;
    let cid: string;
    try {
      cid = await ensureConversation(p.text, opts.forceNew);
    } catch (e) {
      setPending({ ...p, error: (e as Error).message });
      setStreaming(null);
      return;
    }
    const chat = new StreamingChat(async () => cid, "text",
                                   { web: (opts.web ?? webOn) ? true : undefined, onResearch: setResearch });
    let acc = "";
    try {
      const res = await chat.send(p.text, p.requestId, abort.signal, (d) => {
        acc += d;
        setStreaming(acc);
      });
      setPending(null);
      notify("Resposta pronta", res.content.slice(0, 120), "resposta");
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

  async function sendLesson(text: string, extra: LessonOptions = {}, forceNew = false) {
    setNotice(null);
    setPreparing(true);
    setLessonPanel(false);
    try {
      const cid = await ensureConversation(text, forceNew);
      const r = await api.createLesson(cid, text, newRequestId(), {
        level: lessonPrefs.level, length: lessonPrefs.length, ...(webOn ? { web: true } : {}), ...extra,
      });
      if (r.lesson && r.reply) {
        setLesson({ lesson: r.lesson, conversationId: cid, messageId: r.reply.id });
        notify("Vídeo-aula pronta", `"${r.lesson.titulo}" · ${r.lesson.cenas.length} cenas`, "aula");
      }
      else setNotice(r.model.detail);
      const c = await api.conversation(cid).catch(() => null);
      if (c) setMessages(c.messages);
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setPreparing(false);
    }
  }

  async function openLesson(messageId: string) {
    if (!conversationId) return;
    try {
      const r = await api.lesson(messageId);
      setLesson({ lesson: r.lesson, conversationId, messageId });
    } catch (e) {
      onError(e);
    }
  }

  function submit(e: FormEvent, asLesson = false) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || streaming !== null || preparing) return;
    setDraft("");
    if (lastLesson && videoReply && !asLesson) void sendLesson(text, { continues: lastLesson.id });
    else if (asLesson || wantsLesson(text)) void sendLesson(text);
    else void send({ text, requestId: newRequestId() });
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
        {messages.map((m) => <Bubble key={m.id} m={m} onWatch={openLesson} />)}
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
        {preparing && (
          <div className="msg msg-assistant thinking">
            <span className="msg-meta">TITAN · preparando a vídeo-aula…</span>
            <p>Montando o roteiro e as cenas{lessonPrefs.length === "completa" ? " (aula completa: pode levar até um minuto)" : ". Leva uns segundos"}.</p>
          </div>
        )}
        {notice && <p className="notice">Sem resposta da IA: {notice}</p>}
        <div ref={endRef} />
      </div>
      {lastLesson && streaming === null && !preparing && (
        <div className="lesson-followup">
          <button type="button" className={`ghost small ${videoReply ? "on" : ""}`} aria-pressed={videoReply}
                  onClick={() => setVideoReply((v) => !v)}>
            <Icon name="play" size={16} /> {videoReply ? "Responder em vídeo: ligado" : "Responder em vídeo: desligado"}
          </button>
          <span className="small muted">
            {videoReply ? "Sua próxima pergunta ou teoria continua a aula em vídeo." : "A próxima mensagem será respondida em texto."}
          </span>
        </div>
      )}
      {lessonPanel && (
        <div className="lesson-panel">
          <label>Nível
            <select value={lessonPrefs.level} onChange={(e) => setLessonPrefs({ ...lessonPrefs, level: e.target.value as LessonLevel })}>
              <option value="crianca">Para criança</option><option value="basico">Básico</option><option value="avancado">Avançado</option>
            </select>
          </label>
          <label>Duração
            <select value={lessonPrefs.length} onChange={(e) => setLessonPrefs({ ...lessonPrefs, length: e.target.value as LessonLength })}>
              <option value="rapida">Rápida (~2 min)</option><option value="normal">Normal (~5 min)</option><option value="completa">Completa (~10 min)</option>
            </select>
          </label>
          <button type="button" className="small" disabled={!draft.trim() || streaming !== null || preparing}
                  onClick={(e) => submit(e as unknown as FormEvent, true)}>
            <Icon name="play" size={16} /> Criar aula
          </button>
          <span className="small muted">{draft.trim() ? "Sobre o que está escrito na caixa." : "Escreva o assunto na caixa abaixo."}</span>
        </div>
      )}
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
        <button type="button" className={`ghost lesson-btn ${lessonPanel ? "on" : ""}`} disabled={streaming !== null || preparing}
                aria-expanded={lessonPanel} title="Vídeo-aula (ou escreva: explica em vídeo …)"
                onClick={() => setLessonPanel((v) => !v)}>
          <Icon name="play" size={18} /><span className="web-label">Aula</span>
        </button>
        {streaming !== null ? (
          <button type="button" className="ghost" onClick={() => abortRef.current?.abort()}>Parar</button>
        ) : (
          <button type="submit" disabled={!draft.trim() || preparing}>Enviar</button>
        )}
      </form>
      {lesson && (
        <LessonPlayer lesson={lesson.lesson} conversationId={lesson.conversationId} messageId={lesson.messageId}
                      onChanged={() => { if (conversationId) api.conversation(conversationId).then((c) => setMessages(c.messages)).catch(() => {}); }}
                      onClose={() => {
                        setLesson(null);
                        if (conversationId) api.conversation(conversationId).then((c) => setMessages(c.messages)).catch(() => {});
                      }} />
      )}
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

function Bubble({ m, onWatch }: { m: Message; onWatch: (id: string) => void }) {
  const who = m.role === "user" ? "VOCÊ" : m.role === "assistant" ? `TITAN · ${m.model_name ?? "?"}` : "SISTEMA";
  const interrupted = m.status === "interrupted";
  return (
    <div className={`msg msg-${m.role} ${interrupted ? "interrupted" : ""}`}>
      <span className="msg-meta">
        {who} · {new Date(m.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
        {interrupted && " · interrompida"}
      </span>
      {m.role === "assistant" && m.content.startsWith(LESSON_MARKER) ? (
        <div className="lesson-card">
          <p><Icon name="play" size={18} /> <b>{m.content.slice(LESSON_MARKER.length).split("\n")[0]}</b></p>
          <button className="small" onClick={() => onWatch(m.id)}>▶ Assistir a aula</button>
          <details><summary className="small muted">Ver o texto da aula</summary><p>{m.content.split("\n").slice(2).join("\n")}</p></details>
        </div>
      ) : (() => {
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
