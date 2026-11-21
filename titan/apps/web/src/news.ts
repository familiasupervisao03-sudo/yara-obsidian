// Notícias do TITAN: chamadas ao servidor (espelha apps/api/titan_api/routers/news.py) e cópia
// guardada no aparelho para ler mesmo com o notebook desligado.
import { HttpError } from "./api";

export interface SourceLink { name: string; url: string; title: string; published_at: string }
export interface Analysis {
  resumo: string; por_que_importa: string; afeta_titan: string; oportunidade: string;
  discordam: boolean; discordancia: string;
}
export interface Story {
  id: string; title: string; category: string; first_at: string; last_at: string;
  sources: SourceLink[]; n_sources: number; read: boolean; saved: boolean; vote: number;
  important: boolean; affects: boolean; analysis: Analysis | null; checks: SourceLink[];
}
export interface NewsList { enabled: boolean; stories: Story[]; total_items: number }
export interface Source { name: string; url: string; site: string; category: string; enabled: boolean; custom: boolean }
export interface Hit { title: string; url: string; source: string; published_at: string; price: number | null; quote: string }
export interface Follow {
  id: string; topic: string; prices: boolean; since: string; until: string; store_url: string;
  last_checked_at: string | null; trend: string; hits: Hit[];
}
export interface Term { term: string; explanation: string; created_at: string }
export type Cat = "tudo" | "tecnologia" | "ia" | "negocios" | "jogos" | "esportes" | "brasil" | "ceara" | "salvas";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Titan-Request"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api/v1/news${path}`, { method, headers, credentials: "same-origin",
                                                body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new HttpError(0, "network", "Sem conexão com o notebook.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new HttpError(res.status, data?.error?.code ?? "http_error", data?.error?.message ?? `HTTP ${res.status}`);
  return data as T;
}

const CACHE = "titan.noticias";

/** Guarda as últimas notícias no aparelho (para ler sem o notebook). */
function keep(cat: Cat, list: NewsList): void {
  try {
    const all = JSON.parse(localStorage.getItem(CACHE) ?? "{}");
    all[cat] = { at: Date.now(), list: { ...list, stories: list.stories.slice(0, 50) } };
    localStorage.setItem(CACHE, JSON.stringify(all));
  } catch { /* sem espaço: segue sem cópia */ }
}

export function cached(cat: Cat): { at: number; list: NewsList } | null {
  try {
    return JSON.parse(localStorage.getItem(CACHE) ?? "{}")[cat] ?? null;
  } catch {
    return null;
  }
}

export const news = {
  list: async (cat: Cat) => { const l = await req<NewsList>("GET", `?cat=${cat}`); keep(cat, l); return l; },
  state: (id: string, s: { read?: boolean; saved?: boolean; vote?: number }) => req<Story>("POST", `/stories/${id}/state`, s),
  explain: (id: string, mode: "melhor" | "facil") =>
    req<{ text: string; sources: SourceLink[] }>("POST", `/stories/${id}/explain`, { mode }),
  sources: () => req<Source[]>("GET", "/sources"),
  setSource: (url: string, enabled: boolean, name = "", category = "tecnologia") =>
    req<Source[]>("PUT", "/sources", { url, enabled, name, category }),
  removeSource: (url: string) => req<Source[]>("DELETE", `/sources?url=${encodeURIComponent(url)}`),
  follows: () => req<Follow[]>("GET", "/follows"),
  addFollow: (f: { topic: string; prices: boolean; past_weeks: number; future_weeks: number; store_url: string }) =>
    req<Follow>("POST", "/follows", f),
  followFromText: (text: string) => req<Follow>("POST", "/follows/from-text", { text }),
  removeFollow: (id: string) => req<void>("DELETE", `/follows/${id}`),
  terms: () => req<Term[]>("GET", "/terms"),
  jornal: () => req<{ title: string; body: string; created_at: string | null }>("GET", "/jornal"),
  headlines: () => req<{ title: string; source: string }[]>("GET", "/headlines"),
};

/** "13/03/26" (data real de cada site). */
export function dmy(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "2-digit", timeZone: "America/Sao_Paulo" });
}

export function ago(iso: string, now = Date.now()): string {
  const min = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (min < 60) return `há ${min} min`;
  if (min < 48 * 60) return `há ${Math.round(min / 60)} h`;
  return dmy(iso);
}

export function brl(v: number): string {
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/** Texto para compartilhar (título + link do site, nada inventado). */
export function shareText(s: Story): string {
  const src = s.sources[s.sources.length - 1];
  return `${s.title}\n${src ? `${src.name}: ${src.url}` : ""}`.trim();
}
