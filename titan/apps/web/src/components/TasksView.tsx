import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ActionInfo,
  ApprovalItem,
  Criterion,
  ExecutionItem,
  StepInput,
  TaskDetail,
  TaskEvent,
  TaskSummary,
} from "@titan/api-contracts";
import { api, HttpError, newRequestId } from "../api";

const STATUS_LABEL: Record<string, string> = {
  RECEIVED: "Recebida", PLANNING: "Aguardando plano", PENDING_APPROVAL: "Aguardando aprovação",
  READY: "Pronta", RUNNING: "Executando", VERIFYING: "Verificando", WAITING_FOR_USER: "Aguardando você",
  CANCEL_REQUESTED: "Cancelando", CANCELLED: "Cancelada", INTERRUPTED: "Interrompida",
  COMPLETED: "Concluída", FAILED: "Falhou",
};
const TERMINAL = new Set(["CANCELLED", "COMPLETED", "FAILED"]);
const CRITERIA: { type: Criterion["type"]; label: string; needsValue: boolean }[] = [
  { type: "output_nonempty", label: "resultado não vazio", needsValue: false },
  { type: "contains", label: "resultado contém", needsValue: true },
  { type: "not_contains", label: "resultado não contém", needsValue: true },
  { type: "equals", label: "resultado é exatamente", needsValue: true },
  { type: "max_length", label: "no máximo N caracteres", needsValue: true },
];

export function TasksView({ onError, onChanged }: { onError: (e: unknown) => void; onChanged: () => void }) {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);

  const load = useCallback(() => {
    Promise.all([api.tasks(), api.approvals()])
      .then(([t, a]) => { setTasks(t.items); setApprovals(a); })
      .catch(onError);
  }, [onError]);
  useEffect(load, [load]);

  if (creating) {
    return <TaskForm onCancel={() => setCreating(false)} onError={onError}
                     onCreated={(d) => { setCreating(false); setSelected(d.task.id); load(); onChanged(); }} />;
  }
  if (selected) {
    return <TaskPanel id={selected} onBack={() => { setSelected(null); load(); onChanged(); }}
                      onError={onError} onChanged={() => { load(); onChanged(); }} />;
  }
  return (
    <section className="tasks-view">
      <div className="row between">
        <h2 className="section-title">Tarefas</h2>
        <button onClick={() => setCreating(true)}>+ Nova tarefa</button>
      </div>
      {approvals.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">Aprovações pendentes ({approvals.length})</h3>
          {approvals.map((a) => (
            <button key={a.id} className="list-item" onClick={() => setSelected(a.task_id)}>
              <strong>{a.task_title}</strong>
              <span className="small muted">Etapa {a.step_position}: {a.action_label}</span>
            </button>
          ))}
        </div>
      )}
      {tasks.length === 0 && <p className="muted">Nenhuma tarefa ainda.</p>}
      <ul className="task-list">
        {tasks.map((t) => (
          <li key={t.id}>
            <button className="list-item" onClick={() => setSelected(t.id)}>
              <span className="row between">
                <strong>{t.title}</strong>
                <span className={`status status-${t.status}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
              </span>
              {t.status_reason && <span className="small muted">{t.status_reason}</span>}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------- criação ----------

function emptyStep(): StepInput {
  return { title: "", action_type: "note", parameters: {}, success_criteria: [{ type: "output_nonempty" }] };
}

function TaskForm({ onCancel, onCreated, onError }: {
  onCancel: () => void;
  onCreated: (d: TaskDetail) => void;
  onError: (e: unknown) => void;
}) {
  const [actions, setActions] = useState<ActionInfo[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState<StepInput[]>([emptyStep()]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const key = useRef(newRequestId()); // reenvio do mesmo formulário não duplica a tarefa

  useEffect(() => { api.catalog().then((c) => setActions(c.actions)).catch(onError); }, [onError]);

  const update = (i: number, patch: Partial<StepInput>) =>
    setSteps((s) => s.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  async function submit() {
    setBusy(true);
    setProblem(null);
    try {
      onCreated(await api.createTask(title, description, steps, key.current));
    } catch (e) {
      if (e instanceof HttpError && e.status === 422) setProblem(e.message);
      else onError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="tasks-view">
      <div className="row between">
        <h2 className="section-title">Nova tarefa</h2>
        <button className="ghost" onClick={onCancel}>Voltar</button>
      </div>
      <label>Objetivo<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
      <label>Descrição<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} /></label>
      <h3 className="panel-title">Plano (etapas em ordem)</h3>
      {steps.map((s, i) => {
        const spec = actions.find((a) => a.name === s.action_type);
        const crit = s.success_criteria[0] ?? { type: "output_nonempty" };
        const critSpec = CRITERIA.find((c) => c.type === crit.type);
        return (
          <div className="panel step-edit" key={i}>
            <div className="row between">
              <strong>Etapa {i + 1}</strong>
              {steps.length > 1 && (
                <button className="ghost small" onClick={() => setSteps(steps.filter((_, j) => j !== i))}>Remover</button>
              )}
            </div>
            <label>Título<input value={s.title} onChange={(e) => update(i, { title: e.target.value })} /></label>
            <label>
              Ação
              <select value={s.action_type} onChange={(e) => update(i, { action_type: e.target.value, parameters: {} })}>
                {actions.map((a) => (
                  <option key={a.name} value={a.name} disabled={!a.available}>
                    {a.label}{a.sensitive ? " — exige aprovação" : ""}{a.available ? "" : " — indisponível"}
                  </option>
                ))}
              </select>
            </label>
            {spec && <p className="small muted">{spec.risk}</p>}
            {spec?.required_params.map((p) => (
              <label key={p}>
                {PARAM_LABEL[p] ?? p}
                <textarea rows={2} value={s.parameters[p] ?? ""}
                          onChange={(e) => update(i, { parameters: { ...s.parameters, [p]: e.target.value } })} />
              </label>
            ))}
            <label>
              Critério de sucesso
              <select value={crit.type}
                      onChange={(e) => update(i, { success_criteria: [{ type: e.target.value as Criterion["type"] }] })}>
                {CRITERIA.map((c) => <option key={c.type} value={c.type}>{c.label}</option>)}
              </select>
            </label>
            {critSpec?.needsValue && (
              <input placeholder="valor" value={String(crit.value ?? "")}
                     onChange={(e) => update(i, { success_criteria: [{ type: crit.type, value: e.target.value }] })} />
            )}
          </div>
        );
      })}
      <button className="ghost" onClick={() => setSteps([...steps, emptyStep()])}>+ Etapa</button>
      {problem && <p className="banner banner-error">{problem}</p>}
      <div className="row">
        <button onClick={submit} disabled={busy || !title.trim()}>{busy ? "Criando…" : "Criar tarefa"}</button>
      </div>
    </section>
  );
}

const PARAM_LABEL: Record<string, string> = {
  text: "Texto a anotar", prompt: "Pergunta para a IA", question: "Pergunta para você",
  language: "Linguagem", code: "Código",
};

// ---------- detalhe ----------

function TaskPanel({ id, onBack, onError, onChanged }: {
  id: string;
  onBack: () => void;
  onError: (e: unknown) => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [executions, setExecutions] = useState<ExecutionItem[]>([]);
  const [reply, setReply] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [live, setLive] = useState<"on" | "reconnecting" | "off">("off");

  const reload = useCallback(() => {
    Promise.all([api.task(id), api.executions(id)])
      .then(([d, ex]) => { setDetail(d); setExecutions(ex); })
      .catch(onError);
  }, [id, onError]);
  useEffect(reload, [reload]);

  // Eventos ao vivo (SSE). O navegador reconecta sozinho com Last-Event-ID.
  useEffect(() => {
    const es = new EventSource(`/api/v1/tasks/${id}/events`, { withCredentials: true });
    let timer: number | undefined;
    es.onopen = () => setLive("on");
    es.onerror = () => setLive(es.readyState === EventSource.CLOSED ? "off" : "reconnecting");
    es.addEventListener("task", (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as TaskEvent;
      setEvents((list) => [...list.slice(-49), ev]);
      window.clearTimeout(timer);
      timer = window.setTimeout(reload, 250);
    });
    es.addEventListener("end", () => { es.close(); setLive("off"); });
    return () => { es.close(); window.clearTimeout(timer); };
  }, [id, reload]);

  async function act(fn: () => Promise<TaskDetail>) {
    setProblem(null);
    try {
      setDetail(await fn());
      onChanged();
      reload();
    } catch (e) {
      if (e instanceof HttpError && e.status !== 401 && e.status !== 0) {
        if (e.code === "needs_confirmation" && confirm(`${e.message}\n\nExecutar novamente?`)) {
          return act(() => api.resumeTask(id, true));
        }
        setProblem(e.message);
      } else onError(e);
    }
  }

  if (!detail) return <p className="muted">Carregando…</p>;
  const t = detail.task;
  const pending = detail.approvals.filter((a) => a.status === "PENDING" && a.plan_version === t.plan_version);
  const waiting = t.status === "WAITING_FOR_USER" && detail.steps.some((s) => s.status === "WAITING");

  return (
    <section className="tasks-view">
      <div className="row between">
        <button className="ghost small" onClick={onBack}>← Tarefas</button>
        <span className={`live live-${live}`}>{live === "on" ? "ao vivo" : live === "reconnecting" ? "reconectando…" : ""}</span>
      </div>
      <h2 className="section-title">{t.title}</h2>
      <p>
        <span className={`status status-${t.status}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
        {" "}<span className="small muted">plano v{t.plan_version}</span>
      </p>
      {t.status_reason && <p className="small">{t.status_reason}</p>}
      {t.description && <p className="muted small">{t.description}</p>}

      <div className="row wrap">
        {t.status === "READY" && <button onClick={() => act(() => api.startTask(id))}>Executar</button>}
        {(t.status === "INTERRUPTED" || (t.status === "WAITING_FOR_USER" && !waiting)) && (
          <button onClick={() => act(() => api.resumeTask(id, false))}>Retomar</button>
        )}
        {!TERMINAL.has(t.status) && (
          <button className="ghost danger" onClick={() => act(() => api.cancelTask(id, "cancelada pela interface"))}>
            Cancelar
          </button>
        )}
      </div>
      {problem && <p className="banner banner-error">{problem}</p>}

      {pending.map((a) => <ApprovalCard key={a.id} a={a} onDecide={(d) => act(() => api.decide(a.id, d, a.scope_hash))} />)}

      {waiting && (
        <div className="panel">
          <p><strong>Pergunta:</strong> {String(detail.steps.find((s) => s.status === "WAITING")?.parameters.question ?? "")}</p>
          <textarea rows={2} value={reply} onChange={(e) => setReply(e.target.value)} />
          <button onClick={() => act(() => api.replyTask(id, reply))} disabled={!reply.trim()}>Responder</button>
        </div>
      )}

      <h3 className="panel-title">Etapas</h3>
      <ol className="steps">
        {detail.steps.map((s) => (
          <li key={s.id} className={`step step-${s.status}`}>
            <div className="row between">
              <strong>{s.position}. {s.title}</strong>
              <span className="small">{s.status}</span>
            </div>
            <span className="small muted">{s.action_label}{s.requires_approval ? " · exige aprovação" : ""}</span>
            <span className="small muted">Sucesso se: {s.success_criteria.map(describe).join("; ")}</span>
            {s.last_output && <details><summary className="small">Resultado</summary><pre>{s.last_output}</pre></details>}
            {s.last_error && <p className="small bad">{s.last_error}</p>}
          </li>
        ))}
        {detail.steps.length === 0 && <li className="muted small">Sem plano ainda.</li>}
      </ol>

      {detail.verification.length > 0 && (
        <>
          <h3 className="panel-title">Verificação</h3>
          <ul className="small">
            {detail.verification.map((v, i) => (
              <li key={i} className={v.passed ? "ok" : "bad"}>{v.passed ? "✔" : "✘"} {v.criterion} — {v.details}</li>
            ))}
          </ul>
        </>
      )}

      <details className="panel">
        <summary>Histórico (planos, execuções, eventos)</summary>
        <h4>Versões do plano</h4>
        <ul className="small">
          {detail.plans.map((p) => <li key={p.version}>v{p.version} por {p.created_by}: {p.change_note}</li>)}
        </ul>
        <h4>Execuções</h4>
        <ul className="small">
          {executions.map((e) => <li key={e.id}>{e.command} · tentativa {e.attempt} · {e.status}</li>)}
          {executions.length === 0 && <li className="muted">Nenhuma execução.</li>}
        </ul>
        <h4>Eventos ao vivo</h4>
        <ul className="small mono">
          {events.map((e, i) => <li key={i}>{new Date(e.created_at).toLocaleTimeString("pt-BR")} {e.event_type}</li>)}
        </ul>
      </details>
    </section>
  );
}

function describe(c: Criterion): string {
  const spec = CRITERIA.find((x) => x.type === c.type);
  return spec ? `${spec.label}${spec.needsValue ? ` "${c.value}"` : ""}` : c.type;
}

function ApprovalCard({ a, onDecide }: { a: ApprovalItem; onDecide: (d: "approve" | "reject") => void }) {
  return (
    <div className="panel approval">
      <h3 className="panel-title">Aprovação necessária — etapa {a.step_position}</h3>
      <p><strong>{a.action_label}</strong></p>
      <pre className="params">{JSON.stringify(a.parameters, null, 2)}</pre>
      <p className="small">{a.risk}</p>
      <p className="small muted">
        Vale para o plano v{a.plan_version}
        {a.expires_at && ` até ${new Date(a.expires_at).toLocaleString("pt-BR")}`}. Se o plano mudar, esta
        aprovação deixa de valer.
      </p>
      <div className="row">
        <button onClick={() => onDecide("approve")}>Aprovar esta ação</button>
        <button className="ghost danger" onClick={() => onDecide("reject")}>Rejeitar</button>
      </div>
    </div>
  );
}
