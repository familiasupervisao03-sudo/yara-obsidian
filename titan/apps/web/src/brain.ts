// Sócio do TITAN: Início, metas, lembretes/tarefas, memória, perguntas, resumo 📌 e mensagens.
// Espelha apps/api/titan_api/routers/brain.py.
import { HttpError } from "./api";

export type Category = "sobre" | "gostos" | "negocio" | "estudos" | "resumo" | "outros";
export const CATEGORY_LABEL: Record<Category, string> = {
  sobre: "Sobre você", gostos: "Gostos", negocio: "Negócio", estudos: "Estudos", resumo: "Conversas 📌", outros: "Outros",
};

export interface Goal {
  id: string; title: string; unit: string; target: number; current: number; deadline: string | null;
  done: boolean; percent: number; pace: string; days_left: number | null; line: string;
}
export interface Todo {
  id: string; kind: "lembrete" | "tarefa"; title: string; due_at: string | null; done_at: string | null;
  late: boolean; conversation_id: string | null;
}
export interface Memory {
  id: string; category: Category; content: string; status: "pending" | "active" | "archived";
  origin: "conversa" | "voce" | "pergunta" | "resumo"; topic: "open" | "resolved" | null;
  conversation_id: string | null; conversation_title: string | null; replaces: string | null;
  created_at: string; updated_at: string;
}
export interface HomeData {
  greeting: string; now: string;
  continue_conversation: { conversation_id: string; title: string; last_role: string; last_text: string;
                           updated_at: string; origin: string } | null;
  goals: Goal[]; today: Todo[]; open_todos: number; pending_memories: number; memory_total: number;
}
export interface Question { key: string; category: Category; question: string; options: string[]; answered: number; total: number }
export interface Note { id: string; kind: string; title: string; body: string; conversation_id: string | null;
                        todo_id: string | null; created_at: string; delivered: boolean }
export interface BrainPrefs {
  auto_save: boolean; bom_dia: string; boa_noite: string; papo: boolean; papo_max: number;
  socio_semana: boolean; acompanhar: boolean; silencio_inicio: string; silencio_fim: string;
}
export type Action =
  | { type: "lembrete"; id: string; title: string; due_at: string }
  | { type: "tarefa"; id: string; title: string; due_at: string | null }
  | { type: "memoria"; id: string; content: string; status: string; updated: boolean; topic: string | null }
  | { type: "resolvido"; id: string; content: string }
  | { type: "meta"; id: string; title: string; added: number; line: string }
  | { type: "meta_nova"; id: string; title: string; line: string }
  | { type: "bloqueado"; detail: string };

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Titan-Request"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api/v1/brain${path}`, { method, headers, credentials: "same-origin",
                                                 body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new HttpError(0, "network", "Sem conexão com o servidor do notebook.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error;
    throw new HttpError(res.status, err?.code ?? "http_error", err?.message ?? `HTTP ${res.status}`);
  }
  return data as T;
}

const q = (p: Record<string, string | boolean | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== "") s.set(k, String(v));
  const t = s.toString();
  return t ? `?${t}` : "";
};

export const brain = {
  home: () => req<HomeData>("GET", "/home"),
  goals: (all = false) => req<Goal[]>("GET", `/goals${q({ all: all || undefined })}`),
  addGoal: (g: { title: string; unit: string; target: number; deadline?: string | null }) => req<Goal>("POST", "/goals", g),
  patchGoal: (id: string, p: Partial<{ title: string; unit: string; target: number; current: number; add: number;
                                       deadline: string; clear_deadline: boolean; done: boolean }>) =>
    req<Goal>("PATCH", `/goals/${id}`, p),
  deleteGoal: (id: string) => req<void>("DELETE", `/goals/${id}`),
  todos: (all = false) => req<Todo[]>("GET", `/todos${q({ all: all || undefined })}`),
  addTodo: (t: { title: string; kind: "lembrete" | "tarefa"; due_at?: string | null }) => req<Todo>("POST", "/todos", t),
  patchTodo: (id: string, p: Partial<{ title: string; due_at: string; clear_due: boolean; done: boolean; snooze_minutes: number }>) =>
    req<Todo>("PATCH", `/todos/${id}`, p),
  deleteTodo: (id: string) => req<void>("DELETE", `/todos/${id}`),
  upcoming: () => req<{ id: string; title: string; due_at: string }[]>("GET", "/reminders/upcoming"),
  memories: (p: { q?: string; category?: string; status?: string } = {}) =>
    req<{ items: Memory[]; counts: Record<string, number> }>("GET", `/memories${q(p)}`),
  addMemory: (content: string, category: Category) => req<Memory>("POST", "/memories", { content, category }),
  patchMemory: (id: string, p: Partial<{ content: string; category: Category; status: "active" | "archived";
                                         topic: "open" | "resolved" | "none" }>) => req<Memory>("PATCH", `/memories/${id}`, p),
  approveMemory: (id: string) => req<Memory>("POST", `/memories/${id}/approve`),
  deleteMemory: (id: string) => req<void>("DELETE", `/memories/${id}`),
  eraseMemories: () => req<void>("POST", "/memories/erase", { confirm: "APAGAR" }),
  nextQuestion: () => req<Question | null>("GET", "/questions/next"),
  answer: (key: string, answer: string) => req<Memory>("POST", `/questions/${key}/answer`, { answer }),
  skip: (key: string) => req<void>("POST", `/questions/${key}/skip`),
  summarize: (conversationId: string) => req<Memory>("POST", `/conversations/${conversationId}/summary`),
  actions: (conversationId: string) => req<Record<string, Action[]>>("GET", `/conversations/${conversationId}/actions`),
  notes: () => req<Note[]>("GET", "/notes"),
  delivered: (ids: string[]) => req<void>("POST", "/notes/delivered", { ids }),
  prefs: () => req<BrainPrefs>("GET", "/prefs"),
  savePrefs: (p: BrainPrefs) => req<BrainPrefs>("PUT", "/prefs", p),
};

export function fmtWhen(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const hm = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const diff = Math.round((day - today) / 86_400_000);
  if (diff === 0) return `hoje ${hm}`;
  if (diff === 1) return `amanhã ${hm}`;
  if (diff === -1) return `ontem ${hm}`;
  return `${d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" })} ${hm}`;
}

/** "luiz" → "Luiz" (só para exibir). */
export function displayName(username: string): string {
  return username ? username.charAt(0).toUpperCase() + username.slice(1) : username;
}
