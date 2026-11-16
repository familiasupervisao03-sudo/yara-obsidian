import { useCallback, useEffect, useState, type FormEvent } from "react";
import type { SystemStatus } from "@titan/api-contracts";
import { brain, displayName, fmtWhen, type Goal, type HomeData, type Todo } from "../brain";
import { remindersChanged } from "../reminders";
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

/** Início: continuar conversa, metas, o que tem hoje e o botão de falar. Nada some daqui. */
export function Home({ username, status, offline, pendingApprovals, onGo, onChat, onOpenConversation, onError, version }: {
  username: string;
  status: SystemStatus | null;
  offline: boolean;
  pendingApprovals: number;
  onGo: (v: View) => void;
  onChat: (intent: ChatIntent) => void;
  onOpenConversation: (id: string) => void;
  onError: (e: unknown) => void;
  version?: number;
}) {
  const [data, setData] = useState<HomeData | null>(null);
  const [allTodos, setAllTodos] = useState<Todo[] | null>(null);

  const load = useCallback(() => {
    brain.home().then(setData).catch(onError);
  }, [onError]);
  useEffect(() => { load(); }, [load, version]);

  const reloadAll = () => {
    load();
    remindersChanged();
    if (allTodos) brain.todos().then(setAllTodos).catch(onError);
  };

  const web = status?.services.some((s) => s.name === "internet" && s.state === "online");
  const cont = data?.continue_conversation;

  return (
    <section className="home" aria-labelledby="home-title">
      <header className="home-head">
        <p className="eyebrow">Início · {new Date().toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "short" })}</p>
        <h1 id="home-title" className="home-title">{data?.greeting ?? "Olá"}, {displayName(username)}.</h1>
        {offline && <p className="muted small">Sem conexão com o notebook.</p>}
      </header>

      {cont && (
        <section className="card continue" aria-label="Continuar conversa">
          <h2 className="card-title">{cont.origin === "titan" ? "O TITAN te mandou" : "Continuar conversa"}</h2>
          <div className="continue-row">
            <div className="continue-text">
              <strong>{cont.title}</strong>
              <span className="muted small">{cont.last_role === "user" ? "Você" : "TITAN"}: “{cont.last_text}”</span>
            </div>
            <button onClick={() => onOpenConversation(cont.conversation_id)}>Abrir ›</button>
          </div>
        </section>
      )}

      <GoalsCard goals={data?.goals ?? null} onChanged={load} onError={onError} onChat={onChat} />

      <section className="card" aria-labelledby="home-today">
        <header className="card-head">
          <h2 id="home-today" className="card-title">Hoje</h2>
          <button className="ghost small" onClick={() => {
            if (allTodos) setAllTodos(null);
            else brain.todos().then(setAllTodos).catch(onError);
          }}>{allTodos ? "Só hoje" : `Ver todas${data ? ` (${data.open_todos})` : ""}`}</button>
        </header>
        {data === null ? <p className="muted small">Carregando…</p> : (
          <TodoList items={allTodos ?? data.today} onChanged={reloadAll} onError={onError}
                    empty={allTodos ? "Nenhuma tarefa aberta." : "Nada para hoje. Fale “me lembra…” ou “anota…”."} />
        )}
        <AddTodo onAdded={reloadAll} onError={onError} />
      </section>

      {data && data.pending_memories > 0 && (
        <div className="card card-attention" role="status">
          <span><Icon name="brain" size={16} /> {data.pending_memories === 1 ? "1 coisa que aprendi espera você aprovar"
            : `${data.pending_memories} coisas que aprendi esperam você aprovar`}</span>
          <button className="small" onClick={() => onGo("memory")}>Ver na Memória</button>
        </div>
      )}
      {pendingApprovals > 0 && (
        <div className="card card-attention" role="status">
          <span>{pendingApprovals === 1 ? "1 aprovação aguardando você" : `${pendingApprovals} aprovações aguardando você`}</span>
          <button className="small" onClick={() => onGo("tasks")}>Revisar aprovações</button>
        </div>
      )}

      <div className="home-actions">
        <button className="action" onClick={() => onChat({ newConversation: true })}>
          <span className="action-icon"><Icon name="chat" size={22} /></span>
          <span className="action-text"><strong>Escrever</strong><span>Nova conversa</span></span>
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
        <button className="action" onClick={() => onGo("memory")}>
          <span className="action-icon"><Icon name="brain" size={22} /></span>
          <span className="action-text"><strong>Memória</strong><span>O que eu lembro</span></span>
        </button>
      </div>

      {status && (
        <details className="card meters">
          <summary className="card-title">Status do sistema</summary>
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
        </details>
      )}

      <div className="talk-dock">
        <button className="talk" onClick={() => onGo("voice")}><Icon name="mic" size={20} /> Falar com o TITAN</button>
      </div>
    </section>
  );
}

// --- metas ---------------------------------------------------------------------------

function GoalsCard({ goals, onChanged, onError, onChat }: {
  goals: Goal[] | null; onChanged: () => void; onError: (e: unknown) => void; onChat: (i: ChatIntent) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section className="card" aria-labelledby="home-goals">
      <header className="card-head">
        <h2 id="home-goals" className="card-title"><Icon name="target" size={16} /> Minhas metas</h2>
      </header>
      {goals === null ? <p className="muted small">Carregando…</p>
        : goals.length === 0 && !adding ? <p className="muted small">Nenhuma meta ainda. Ex.: “Ganhar R$ 300 com o negócio”.</p>
        : (
          <ul className="goals">
            {goals.map((g) => (
              <li key={g.id} className={open === g.id ? "open" : ""}>
                <button className="goal" onClick={() => setOpen(open === g.id ? null : g.id)} aria-expanded={open === g.id}>
                  <strong>{g.title}</strong>
                  {g.target > 0 && <span className="goal-bar" aria-hidden="true"><i style={{ width: `${g.percent}%` }} /></span>}
                  <span className="muted small">
                    {g.target > 0 ? (g.unit === "R$" ? `R$ ${g.current} de R$ ${g.target}` : `${g.current} de ${g.target} ${g.unit}`) : "sem número"}
                    {g.days_left !== null && ` · faltam ${g.days_left} dias`}
                    {g.pace && <> · <span className={g.pace === "no ritmo" ? "ok" : "warn"}>{g.pace}</span></>}
                  </span>
                </button>
                {open === g.id && <GoalDetail g={g} onChanged={onChanged} onError={onError} onChat={onChat} />}
              </li>
            ))}
          </ul>
        )}
      {adding ? <AddGoal onDone={() => { setAdding(false); onChanged(); }} onError={onError} />
        : <button className="ghost small wide" onClick={() => setAdding(true)}><Icon name="plus" size={14} /> Nova meta</button>}
    </section>
  );
}

function GoalDetail({ g, onChanged, onError, onChat }: {
  g: Goal; onChanged: () => void; onError: (e: unknown) => void; onChat: (i: ChatIntent) => void;
}) {
  const [add, setAdd] = useState("");
  const act = (p: Promise<unknown>) => p.then(onChanged).catch(onError);
  return (
    <div className="goal-detail">
      {g.target > 0 && (
        <form className="row" onSubmit={(e) => {
          e.preventDefault();
          const n = Number(add.replace(",", "."));
          if (Number.isFinite(n) && n !== 0) { act(brain.patchGoal(g.id, { add: n })); setAdd(""); }
        }}>
          <input inputMode="decimal" placeholder={g.unit === "R$" ? "Somar (ex.: 30)" : "Somar"} value={add}
                 onChange={(e) => setAdd(e.target.value)} aria-label="Somar ao progresso" />
          <button className="small" type="submit">Somar</button>
        </form>
      )}
      <div className="row wrap">
        <button className="small" onClick={() => onChat({ newConversation: true, draft: `Sobre a minha meta “${g.title}” (${g.line}): ` })}>
          <Icon name="chat" size={14} /> Conversar sobre esta meta
        </button>
        <button className="ghost small" onClick={() => act(brain.patchGoal(g.id, { done: true }))}><Icon name="check" size={14} /> Concluída</button>
        <button className="ghost small" onClick={() => { if (confirm(`Apagar a meta “${g.title}”?`)) act(brain.deleteGoal(g.id)); }}>
          <Icon name="trash" size={14} /> Apagar
        </button>
      </div>
    </div>
  );
}

function AddGoal({ onDone, onError }: { onDone: () => void; onError: (e: unknown) => void }) {
  const [title, setTitle] = useState("");
  const [target, setTarget] = useState("");
  const [unit, setUnit] = useState("R$");
  const [deadline, setDeadline] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    const n = Number(target.replace(",", "."));
    brain.addGoal({ title: title.trim(), unit: target ? unit : "", target: Number.isFinite(n) ? n : 0,
                    deadline: deadline ? new Date(`${deadline}T23:59`).toISOString() : null })
      .then(onDone).catch(onError);
  };
  return (
    <form className="add-form" onSubmit={submit}>
      <input autoFocus placeholder="Qual é a meta? (ex.: Ganhar R$ 300 com o negócio)" value={title}
             onChange={(e) => setTitle(e.target.value)} maxLength={160} aria-label="Meta" />
      <div className="row">
        <input inputMode="decimal" placeholder="Alvo (opcional)" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Alvo" />
        <select value={unit} onChange={(e) => setUnit(e.target.value)} aria-label="Unidade">
          <option value="R$">R$</option><option value="aulas">aulas</option><option value="vendas">vendas</option>
          <option value="vezes">vezes</option><option value="kg">kg</option><option value="páginas">páginas</option>
        </select>
        <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} aria-label="Prazo" />
      </div>
      <div className="row">
        <button className="small" type="submit">Criar meta</button>
        <button className="ghost small" type="button" onClick={onDone}>Cancelar</button>
      </div>
    </form>
  );
}

// --- lembretes e tarefas -------------------------------------------------------------

export function TodoList({ items, onChanged, onError, empty }: {
  items: Todo[]; onChanged: () => void; onError: (e: unknown) => void; empty: string;
}) {
  const [menu, setMenu] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  if (items.length === 0) return <p className="muted small">{empty}</p>;
  const act = (p: Promise<unknown>) => { setMenu(null); p.then(onChanged).catch(onError); };
  return (
    <ul className="todos">
      {items.map((t) => (
        <li key={t.id} className={`todo ${t.done_at ? "done" : ""}`}>
          <div className="todo-row">
            <button className="todo-check" aria-label={t.done_at ? "Desmarcar" : "Marcar como feita"}
                    aria-pressed={Boolean(t.done_at)} onClick={() => act(brain.patchTodo(t.id, { done: !t.done_at }))}>
              {t.done_at ? <Icon name="check" size={14} /> : t.kind === "lembrete" ? <Icon name="clock" size={14} /> : null}
            </button>
            {editing?.id === t.id ? (
              <form className="todo-edit" onSubmit={(e) => { e.preventDefault(); setEditing(null);
                act(brain.patchTodo(t.id, { title: editing.title })); }}>
                <input autoFocus value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                       aria-label="Editar" maxLength={200} />
              </form>
            ) : (
              <span className="todo-title">
                {t.kind === "lembrete" && t.due_at && <span className="todo-time">{fmtWhen(t.due_at)}</span>}
                {t.kind === "tarefa" && t.due_at && <span className="todo-time">{fmtWhen(t.due_at).split(" ")[0]}</span>}
                <span>{t.title}</span>
                {t.late && <span className="late">{t.kind === "lembrete" ? "PASSOU" : "ATRASADA"}</span>}
              </span>
            )}
            <button className="ghost small todo-more" aria-label="Mais opções" aria-expanded={menu === t.id}
                    onClick={() => setMenu(menu === t.id ? null : t.id)}>⋯</button>
          </div>
          {menu === t.id && (
            <div className="todo-menu row wrap">
              {t.kind === "lembrete" && !t.done_at && <>
                <button className="small" onClick={() => act(brain.patchTodo(t.id, { snooze_minutes: 10 }))}>Adiar 10 min</button>
                <button className="small" onClick={() => act(brain.patchTodo(t.id, { snooze_minutes: 60 }))}>Adiar 1 h</button>
              </>}
              {!t.done_at && <button className="small" onClick={() => act(brain.patchTodo(t.id, { snooze_minutes: 24 * 60 }))}>Para amanhã</button>}
              <button className="ghost small" onClick={() => { setMenu(null); setEditing({ id: t.id, title: t.title }); }}>
                <Icon name="edit" size={14} /> Editar
              </button>
              <button className="ghost small" onClick={() => act(brain.deleteTodo(t.id))}><Icon name="trash" size={14} /> Apagar</button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function AddTodo({ onAdded, onError }: { onAdded: () => void; onError: (e: unknown) => void }) {
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [open, setOpen] = useState(false);
  if (!open) return <button className="ghost small wide" onClick={() => setOpen(true)}><Icon name="plus" size={14} /> Adicionar</button>;
  return (
    <form className="add-form" onSubmit={(e) => {
      e.preventDefault();
      if (!title.trim()) return;
      brain.addTodo({ title: title.trim(), kind: when ? "lembrete" : "tarefa", due_at: when ? new Date(when).toISOString() : null })
        .then(() => { setTitle(""); setWhen(""); setOpen(false); onAdded(); }).catch(onError);
    }}>
      <input autoFocus placeholder="O que precisa fazer?" value={title} onChange={(e) => setTitle(e.target.value)}
             maxLength={200} aria-label="Tarefa" />
      <div className="row">
        <label className="small muted grow">Avisar em (opcional)
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </label>
      </div>
      <div className="row">
        <button className="small" type="submit">{when ? "Criar lembrete" : "Criar tarefa"}</button>
        <button className="ghost small" type="button" onClick={() => setOpen(false)}>Cancelar</button>
      </div>
    </form>
  );
}
