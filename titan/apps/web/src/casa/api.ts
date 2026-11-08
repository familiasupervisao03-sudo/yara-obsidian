// TITAN Casa: chamadas ao servidor (espelha apps/api/titan_api/routers/casa.py).
import { HttpError } from "../api";

export type Kind = "plug" | "light" | "tv" | "ac" | "fan" | "other";
export interface Device {
  id: string; kind: Kind; name: string; icon: string; room: string; aliases: string; configured: boolean;
  online: boolean; state: { on?: boolean; bright?: number; white?: string; watts?: number; ac_temp?: number;
  ac_mode?: string; ac_fan?: number; vol?: number }; provider_name: string; infrared: boolean;
}
export interface SceneAction { device_id: string; action: "on" | "off" | "dim"; ac_temp?: number | null }
export interface Scene { id: string; name: string; phrases: string; reply: string; actions: SceneAction[] }
export interface Status { provider: string; cloud: boolean; linked: boolean; home: string; devices: number; new: number; on: number; scenes: number }
export interface UndoStep { device_id: string; action: Record<string, unknown> }
export interface CommandResult { understood: boolean; kind: string; reply: string; device: Device | null; scene: string | null; failed: string[]; undo: UndoStep[] }
export interface CasaEvent { at: string; source: string; action: string; ok: boolean; detail: string; device: string | null; scene: string | null }
export type Action = { do: "on" | "off" | "toggle" | "bright" | "white" | "ac" | "key"; value?: unknown; on?: boolean;
  ac_temp?: number; ac_mode?: string; ac_fan?: number };

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Titan-Request"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api/v1/casa${path}`, { method, headers, credentials: "same-origin",
                                               body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new HttpError(0, "network", "Sem conexão com o notebook.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new HttpError(res.status, data?.error?.code ?? "http_error", data?.error?.message ?? `HTTP ${res.status}`);
  return data as T;
}

export const casa = {
  status: () => req<Status>("GET", "/status"),
  devices: (all = false) => req<Device[]>("GET", `/devices${all ? "?all=1" : ""}`),
  discover: () => req<{ found: number; new: number }>("POST", "/devices/discover"),
  patch: (id: string, p: Partial<Pick<Device, "name" | "icon" | "room" | "aliases" | "configured">> & { kind?: "plug" | "fan" }) =>
    req<Device>("PATCH", `/devices/${id}`, p),
  forget: (id: string) => req<void>("DELETE", `/devices/${id}`),
  act: (id: string, a: Action) => req<Device>("POST", `/devices/${id}/action`, a),
  identify: (id: string) => req<Device>("POST", `/devices/${id}/identify`),
  scenes: () => req<Scene[]>("GET", "/scenes"),
  createScene: (s: Omit<Scene, "id">) => req<Scene>("POST", "/scenes", s),
  updateScene: (id: string, s: Omit<Scene, "id">) => req<Scene>("PUT", `/scenes/${id}`, s),
  deleteScene: (id: string) => req<void>("DELETE", `/scenes/${id}`),
  runScene: (id: string) => req<CommandResult>("POST", `/scenes/${id}/run`),
  command: (text: string, source: "voz" | "texto", requireWake = false) =>
    req<CommandResult>("POST", "/command", { text, source, require_wake: requireWake }),
  events: () => req<CasaEvent[]>("GET", "/events?limit=25"),
};

export const ICONS: Record<string, string> = {
  light: "💡", plug: "🔌", fan: "🌀", laptop: "💻", tv: "📺", ac: "❄️", lamp: "🛋️", speaker: "🔊", game: "🎮",
  charger: "🔋", heater: "🔥", router: "📶",
};
export const ICON_LABEL: Record<string, string> = {
  light: "lâmpada", plug: "tomada", fan: "ventilador", laptop: "notebook / PC", tv: "TV", ac: "ar-condicionado",
  lamp: "luminária", speaker: "caixa de som", game: "videogame", charger: "carregador", heater: "aquecedor", router: "roteador / Wi-Fi",
};
const FEM = /^(luz|tv|lâmpada|lampada|tomada|luminária|luminaria|caixa|geladeira|cafeteira)/i;
export const isFem = (d: Device) => d.kind === "light" || d.kind === "tv" || FEM.test(d.name);
export const stateWord = (d: Device) => d.state.on ? (isFem(d) ? "LIGADA" : "LIGADO") : (isFem(d) ? "DESLIGADA" : "DESLIGADO");
export function subtitle(d: Device): string {
  if (!d.online) return "sem conexão";
  if (d.kind === "light") return d.state.on ? `${d.state.bright ?? 100}% · branco ${d.state.white ?? "neutro"}` : "lâmpada";
  if (d.kind === "ac") return `infravermelho · ${d.state.ac_temp ?? 24}° ${d.state.ac_mode ?? "frio"}`;
  if (d.kind === "tv") return "infravermelho";
  if (d.state.watts !== undefined && d.state.on) return `tomada · ${d.state.watts} W`;
  return "tomada";
}
