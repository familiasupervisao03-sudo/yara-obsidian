// TITAN Central: chamadas ao servidor (espelha apps/api/titan_api/routers/central.py).
import { HttpError } from "../api";

export interface GoalBrief { id: string; title: string; unit: string; current: number; target: number; pct: number | null }
export interface TodoBrief { id: string; title: string; kind: string; due_at: string | null; done: boolean }
export interface DeviceBrief { id: string; name: string; kind: string; icon: string; room: string; on: boolean; online: boolean; watts?: number | null }
export interface EventBrief { id: number; at: string; source: string; action: string; ok: boolean; device: string | null; scene: string | null }
export interface Weather { city: string; temp: number | null; humidity: number | null; text: string; icon: string;
  max: number | null; min: number | null; rain_chance: number | null }
export interface ShowItem { id: string; title: string; text: string; at: string }
export interface Overview {
  greeting: string; username: string; now: string; goals: GoalBrief[]; today: TodoBrief[];
  casa: { demo: boolean; devices: DeviceBrief[]; on: number; last_event: EventBrief | null };
  weather: Weather | null; show: ShowItem | null;
}
export interface Alert {
  key: string; level: "crit" | "warn"; title: string; value: number; unit: string; limit: number; max: number;
  text: string; todo: string; history: number[]; culprit?: string | null;
  plug?: { id: string; name: string; on: boolean; watts: number | null } | null;
}
export interface Telemetry {
  available: boolean; alerts: Alert[];
  now?: { cpu: number | null; mem: number | null; temp: number | null; bat_temp: number | null; bat_pct: number | null;
    charging: boolean | null; spend_pct: number | null; charger_w: number | null };
  history?: { cpu: (number | null)[]; temp: (number | null)[]; mem: (number | null)[] };
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Titan-Request"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new HttpError(0, "network", "Sem conexão com o notebook.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new HttpError(res.status, data?.error?.code ?? "http_error", data?.error?.message ?? `HTTP ${res.status}`);
  return data as T;
}

export const central = {
  overview: () => req<Overview>("GET", "/api/v1/central/overview"),
  telemetry: () => req<Telemetry>("GET", "/api/v1/central/telemetry"),
  show: (title: string, text: string) => req<ShowItem>("POST", "/api/v1/central/show", { title, text }),
  clearShow: () => req<void>("DELETE", "/api/v1/central/show"),
};

// Conversa do TITAN usada pela Central (perguntas que não são comandos da casa).
interface Msg { id: string; role: string; content: string }
interface PostResult { reply: Msg | null; model: { available: boolean; reason?: string | null; detail?: string } }
let convId: string | null = null;
export async function askTitan(text: string): Promise<string> {
  if (!convId) {
    const list = await req<{ items: { id: string; title: string }[] }>("GET", "/api/v1/conversations");
    convId = list.items.find((c) => c.title === "TITAN Central")?.id
      ?? (await req<{ id: string }>("POST", "/api/v1/conversations", { title: "TITAN Central" })).id;
  }
  const rid = `central-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const r = await req<PostResult>("POST", `/api/v1/conversations/${convId}/messages`,
    { content: text, client_request_id: rid, mode: "voice" });
  if (r.reply?.content) return r.reply.content;
  return "O núcleo de IA está em pausa agora. Comandos da casa continuam funcionando.";
}
