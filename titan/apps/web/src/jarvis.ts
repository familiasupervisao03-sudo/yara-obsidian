// Funções do Jarvis: clima, chegada/saída e protocolos. Espelha apps/api/titan_api/routers/jarvis.py.
import { HttpError } from "./api";

export interface Place { name: string; admin1: string; country: string; lat: number; lon: number }
export interface Step { device_id: string; do: "on" | "off" | "dim" }
export interface JarvisSettings {
  place: Place | null; rain_alert: boolean; welcome: boolean; ask_leave: boolean; arrive_steps: Step[];
  presence: string; presence_at: string | null; quiet_until: string | null;
}
export interface Device { id: string; name: string; kind: string; on: boolean; online: boolean }
export interface Day { date: string; weekday: string; text: string; emoji: string; min: number | null; max: number | null; rain: number | null }
export interface Weather {
  place: Place | null; error?: string; source?: string; source_url?: string; updated_at?: string | null;
  now?: { temp: number | null; text: string; emoji: string };
  today?: Day | null; hours?: { time: string; rain: number | null; temp: number | null }[]; days?: Day[]; tip?: string;
}
export interface Result { name: string; ok: boolean; detail: string }
export interface Protocol {
  id: string; name: string; emoji: string; special: string; quiet_until: string; steps: Step[];
  lines: string[]; summary: string; custom: boolean;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Titan-Request"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api/v1/jarvis${path}`, { method, headers, credentials: "same-origin",
                                                  body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new HttpError(0, "network", "Sem conexão com o notebook.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new HttpError(res.status, data?.error?.code ?? "http_error", data?.error?.message ?? `HTTP ${res.status}`);
  return data as T;
}

export const jarvis = {
  settings: () => req<JarvisSettings>("GET", "/settings"),
  saveSettings: (s: Partial<Pick<JarvisSettings, "rain_alert" | "welcome" | "ask_leave" | "arrive_steps">>) =>
    req<JarvisSettings>("PUT", "/settings", s),
  devices: () => req<Device[]>("GET", "/devices"),
  places: (q: string) => req<Place[]>("GET", `/places?q=${encodeURIComponent(q)}`),
  setPlace: (p: Place) => req<JarvisSettings>("PUT", "/place", p),
  clearPlace: () => req<void>("DELETE", "/place"),
  weather: () => req<Weather>("GET", "/weather"),
  leave: () => req<Device[]>("GET", "/leave"),
  turnOff: (ids: string[]) => req<Result[]>("POST", "/leave/off", { device_ids: ids }),
  protocols: () => req<Protocol[]>("GET", "/protocols"),
  saveProtocol: (id: string | null, p: { name: string; emoji: string; steps: Step[]; quiet_until: string }) =>
    id ? req<Protocol>("PUT", `/protocols/${id}`, p) : req<Protocol>("POST", "/protocols", p),
  deleteProtocol: (id: string) => req<void>("DELETE", `/protocols/${id}`),
  run: (id: string) => req<{ text: string; results: Result[] }>("POST", `/protocols/${id}/run`),
};

export const DO_LABEL: Record<Step["do"], string> = { on: "ligar", off: "desligar", dim: "luz baixa" };

/** "31°" (sem casas decimais). */
export function deg(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : `${Math.round(v)}°`;
}
