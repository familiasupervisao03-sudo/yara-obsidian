import { useCallback, useEffect, useState, type FormEvent } from "react";
import { HttpError } from "../api";
import { brain, CATEGORY_LABEL, type Category, type Memory, type Question } from "../brain";
import { Icon } from "./icons";

const CATS: Category[] = ["sobre", "gostos", "negocio", "estudos", "resumo", "outros"];
const ORIGIN: Record<Memory["origin"], string> = {
  conversa: "da conversa", voce: "você adicionou", pergunta: "você respondeu", resumo: "resumo 📌",
};

function when(iso: string) {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

/** Aba Memória: tudo o que o TITAN lembra. Nada entra sem aparecer aqui. */
export function MemoryView({ onError, onOpenConversation }: {
  onError: (e: unknown) => void;
  onOpenConversation: (id: string) => void;
}) {
  const [items, setItems] = useState<Memory[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState<string>("");
  const [teaching, setTeaching] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    brain.memories({ q: query, category: cat }).then((r) => { setItems(r.items); setCounts(r.counts); }).catch(onError);
  }, [query, cat, onError]);
  useEffect(() => {
    const id = window.setTimeout(load, query ? 250 : 0);
    return () => window.clearTimeout(id);
  }, [load, query]);

  const fail = (e: unknown) => {
    if (e instanceof HttpError && e.status === 422) setNotice(e.message);
    else onError(e);
  };
  const act = (p: Promise<unknown>) => p.then(() => { setNotice(null); load(); }).catch(fail);

  const pending = (items ?? []).filter((m) => m.status === "pending");
  const active = (items ?? []).filter((m) => m.status === "active");
  const archived = (items ?? []).filter((m) => m.status === "archived");

  return (
    <section className="memory-view" aria-labelledby="mem-title">
      <header className="home-head">
        <p className="eyebrow">Memória</p>
        <h1 id="mem-title" className="home-title"><Icon name="brain" size={26} /> O que eu lembro</h1>
        <p className="muted small">{counts.total ?? 0} lembranças · ficam só no seu notebook · nada é guardado sem aparecer aqui</p>
      </header>

      <QuestionCard onAnswered={load} onError={fail} />

      <input className="search" type="search" placeholder="Buscar na memória…" value={query}
             onChange={(e) => setQuery(e.target.value)} aria-label="Buscar na memória" />
      <div className="chips" role="group" aria-label="Categorias">
        <button className={`chip ${cat === "" ? "on" : ""}`} onClick={() => setCat("")}>Tudo {counts.total ?? 0}</button>
        {CATS.map((c) => (
          <button key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(cat === c ? "" : c)}>
            {CATEGORY_LABEL[c]} {counts[c] ?? 0}
          </button>
        ))}
      </div>
      {notice && <p className="notice" role="alert">{notice}</p>}

      {pending.length > 0 && (
        <section className="card card-pending" aria-label="Esperando você aprovar">
          <h2 className="card-title">Esperando você aprovar · {pending.length}</h2>
          <ul className="mem-list">
            {pending.map((m) => (
              <li key={m.id}>
                <div className="mem-text">
                  <span>“{m.content}”</span>
                  {m.replaces && <span className="muted small">substitui: “{m.replaces}”</span>}
                  <Source m={m} onOpen={onOpenConversation} />
                </div>
                <div className="mem-actions">
                  <button className="small" onClick={() => act(brain.approveMemory(m.id))}><Icon name="check" size={14} /> Guardar</button>
                  <button className="ghost small" aria-label="Não guardar" onClick={() => act(brain.deleteMemory(m.id))}>✕</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card" aria-label="Lembranças">
        <h2 className="card-title">{query || cat ? "Encontradas" : "Recentes"}</h2>
        {items === null ? <p className="muted small">Carregando…</p>
          : active.length === 0 ? <p className="muted small">{query ? "Nada encontrado." : "Ainda não lembro de nada. Converse comigo, responda às perguntas acima ou toque em “Ensinar algo”."}</p>
          : <ul className="mem-list">{active.map((m) => <MemoryRow key={m.id} m={m} act={act} onOpen={onOpenConversation} />)}</ul>}
      </section>

      {archived.length > 0 && (
        <details className="card">
          <summary className="card-title">Antigas · {archived.length}</summary>
          <p className="muted small">Não aparecem há um tempo. Ainda uso se o assunto voltar.</p>
          <ul className="mem-list">{archived.map((m) => <MemoryRow key={m.id} m={m} act={act} onOpen={onOpenConversation} />)}</ul>
        </details>
      )}

      {teaching ? <Teach onDone={() => { setTeaching(false); load(); }} onError={fail} />
        : (
          <div className="row">
            <button onClick={() => setTeaching(true)}><Icon name="plus" size={16} /> Ensinar algo</button>
            <button className="ghost" onClick={() => {
              const typed = prompt("Isso apaga TODA a memória do TITAN. Para confirmar, digite APAGAR:");
              if (typed === "APAGAR") act(brain.eraseMemories());
            }}><Icon name="trash" size={16} /> Apagar tudo</button>
          </div>
        )}
      <p className="muted small">
        Guardado em <code>var/titan.db</code>, no seu notebook (não vai para o GitHub). Quando a IA é on-line,
        só as lembranças ligadas ao assunto vão junto com a mensagem. Documentos, endereço, escola, contatos,
        senhas, banco, saúde e dados de outras pessoas nunca são guardados.
      </p>
    </section>
  );
}

function Source({ m, onOpen }: { m: Memory; onOpen: (id: string) => void }) {
  return (
    <span className="muted small">
      {CATEGORY_LABEL[m.category]} · {m.conversation_id && m.conversation_title
        ? <button className="link small" onClick={() => onOpen(m.conversation_id!)}>{ORIGIN[m.origin]} “{m.conversation_title}”</button>
        : ORIGIN[m.origin]} · {when(m.updated_at)}
      {m.topic === "open" && <> · <span className="warn">assunto em aberto</span></>}
      {m.topic === "resolved" && <> · <span className="ok">resolvido</span></>}
    </span>
  );
}

function MemoryRow({ m, act, onOpen }: { m: Memory; act: (p: Promise<unknown>) => void; onOpen: (id: string) => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  const [cat, setCat] = useState<Category>(m.category);
  if (edit !== null) {
    return (
      <li>
        <form className="add-form grow" onSubmit={(e) => { e.preventDefault();
          act(brain.patchMemory(m.id, { content: edit, category: cat })); setEdit(null); }}>
          <textarea value={edit} onChange={(e) => setEdit(e.target.value)} maxLength={m.category === "resumo" ? 1500 : 300}
                    rows={m.category === "resumo" ? 5 : 2} aria-label="Editar lembrança" autoFocus />
          <div className="row">
            <select value={cat} onChange={(e) => setCat(e.target.value as Category)} aria-label="Categoria">
              {CATS.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
            </select>
            <button className="small" type="submit">Salvar</button>
            <button className="ghost small" type="button" onClick={() => setEdit(null)}>Cancelar</button>
          </div>
        </form>
      </li>
    );
  }
  return (
    <li>
      <div className="mem-text">
        <span>{m.content}</span>
        <Source m={m} onOpen={onOpen} />
      </div>
      <div className="mem-actions">
        {m.topic === "open" && (
          <button className="ghost small" title="Marcar como resolvido" onClick={() => act(brain.patchMemory(m.id, { topic: "resolved" }))}>
            <Icon name="check" size={14} />
          </button>
        )}
        {m.category !== "resumo" && (
          <button className="ghost small" aria-label="Editar" onClick={() => setEdit(m.content)}><Icon name="edit" size={14} /></button>
        )}
        <button className="ghost small" aria-label="Apagar" onClick={() => act(brain.deleteMemory(m.id))}>✕</button>
      </div>
    </li>
  );
}

function Teach({ onDone, onError }: { onDone: () => void; onError: (e: unknown) => void }) {
  const [text, setText] = useState("");
  const [cat, setCat] = useState<Category>("sobre");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) brain.addMemory(text.trim(), cat).then(onDone).catch(onError);
  };
  return (
    <form className="card add-form" onSubmit={submit}>
      <h2 className="card-title">Ensinar algo</h2>
      <input autoFocus placeholder="Ex.: Prefiro explicação curta e com exemplo" value={text}
             onChange={(e) => setText(e.target.value)} maxLength={300} aria-label="O que o TITAN deve lembrar" />
      <div className="row">
        <select value={cat} onChange={(e) => setCat(e.target.value as Category)} aria-label="Categoria">
          {CATS.filter((c) => c !== "resumo").map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
        </select>
        <button className="small" type="submit">Guardar</button>
        <button className="ghost small" type="button" onClick={onDone}>Cancelar</button>
      </div>
    </form>
  );
}

function QuestionCard({ onAnswered, onError }: { onAnswered: () => void; onError: (e: unknown) => void }) {
  const [q, setQ] = useState<Question | null | undefined>(undefined);
  const [text, setText] = useState("");
  const [hidden, setHidden] = useState(false);
  const next = useCallback(() => { brain.nextQuestion().then(setQ).catch(() => setQ(null)); }, []);
  useEffect(next, [next]);
  if (!q || hidden) return null;
  const send = (answer: string) => {
    if (!answer.trim()) return;
    brain.answer(q.key, answer.trim()).then(() => { setText(""); onAnswered(); next(); }).catch(onError);
  };
  return (
    <section className="card question" aria-label="Me conta de você">
      <header className="card-head">
        <h2 className="card-title">Me conta de você · {q.answered} de {q.total}</h2>
        <button className="ghost small" onClick={() => setHidden(true)} aria-label="Esconder as perguntas por agora">Depois</button>
      </header>
      <span className="goal-bar" aria-hidden="true"><i style={{ width: `${(q.answered / q.total) * 100}%` }} /></span>
      <p className="question-text">{q.question}</p>
      {q.options.length > 0 && (
        <div className="row wrap">
          {q.options.map((o) => <button key={o} className="small" onClick={() => send(o)}>{o}</button>)}
        </div>
      )}
      <form className="row" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input placeholder={q.options.length ? "Ou escreva do seu jeito…" : "Sua resposta…"} value={text}
               onChange={(e) => setText(e.target.value)} maxLength={200} aria-label="Resposta" />
        <button className="small" type="submit">OK</button>
        <button className="ghost small" type="button" onClick={() => brain.skip(q.key).then(next).catch(onError)}>Pular</button>
      </form>
      <p className="muted small">Responda só o que quiser. Nunca pergunto endereço, escola, documentos, senhas ou banco.</p>
    </section>
  );
}
