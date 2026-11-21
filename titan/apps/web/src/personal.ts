// Você → Personalizar: o jeito desta conta (espelha /api/v1/brain/personal). Fica guardado no
// servidor (cada conta o seu) e uma cópia no aparelho, para abrir já com as cores certas.
import { useEffect, useState } from "react";
import { HttpError } from "./api";

export type CardId = "orbe" | "clima" | "continuar" | "protocolos" | "hoje" | "metas" | "avisos" | "atalhos" | "status";
export type NavId = "home" | "chat" | "news" | "memory" | "system" | "casa";
export interface Personal {
  color: "azul" | "roxo" | "verde" | "laranja" | "vermelho" | "rosa" | "livre"; custom: string;
  bg: "brilho" | "liso" | "preto"; orb: "vidro" | "reator" | "simples"; orb_anim: boolean;
  cards: { id: CardId; on: boolean }[]; nav: NavId[];
  font: "P" | "M" | "G" | "GG"; name: string; call: "senhor" | "chefe" | "nome" | "livre"; call_custom: string;
  tone: "formal" | "amigo" | "direto";
}

export const CARD_LABEL: Record<CardId, string> = {
  orbe: "Orbe e saudação", clima: "Clima", continuar: "Continuar conversa", protocolos: "Protocolos",
  hoje: "Hoje (lembretes e tarefas)", metas: "Metas", avisos: "Avisos (memória e aprovações)",
  atalhos: "Atalhos (Escrever, Aula…)", status: "Status do sistema",
};
export const NAV_LABEL: Record<NavId, string> = {
  home: "Início", chat: "Conversa", news: "Notícias", memory: "Memória", system: "Você", casa: "Casa",
};

export const DEFAULT_PERSONAL: Personal = {
  color: "azul", custom: "#3ee8ff", bg: "brilho", orb: "vidro", orb_anim: true,
  cards: (["orbe", "clima", "continuar", "protocolos", "hoje", "metas", "avisos", "atalhos", "status"] as CardId[])
    .map((id) => ({ id, on: id !== "status" })),
  nav: ["home", "chat", "news", "system"], font: "M", name: "TITAN", call: "senhor", call_custom: "", tone: "formal",
};

// [destaque, segunda cor (brilho/orbe), terceira (botões/balões)]
export const PALETTES: Record<Exclude<Personal["color"], "livre">, [string, string, string]> = {
  azul: ["#3ee8ff", "#9a6bff", "#4f8dff"], roxo: ["#b48cff", "#d06bff", "#8a5cff"],
  verde: ["#3dffa8", "#3ee8ff", "#1fbf7a"], laranja: ["#ffb547", "#ff6b81", "#ff8a3d"],
  vermelho: ["#ff6b81", "#ffb547", "#e8364f"], rosa: ["#ff6fd8", "#9a6bff", "#ff3ea5"],
};

async function req<T>(method: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Titan-Request"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch("/api/v1/brain/personal", { method, headers, credentials: "same-origin",
                                                 body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new HttpError(0, "network", "Sem conexão com o notebook.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new HttpError(res.status, data?.error?.code ?? "http_error", data?.error?.message ?? `HTTP ${res.status}`);
  return data as T;
}

export const personalApi = {
  get: () => req<Personal>("GET"),
  save: (p: Personal) => req<Personal>("PUT", p),
  reset: () => req<Personal>("DELETE"),
};

const KEY = "titan.personal";

export function cachedPersonal(): Personal {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return v && typeof v === "object" ? { ...DEFAULT_PERSONAL, ...v } : DEFAULT_PERSONAL;
  } catch {
    return DEFAULT_PERSONAL;
  }
}

function hexRgb(h: string): [number, number, number] {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbHex(r: number, g: number, b: number): string {
  return "#" + [r, g, b].map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0")).join("");
}
/** Gira a cor no círculo de cores (cor livre ganha uma "parceira" para o brilho da orbe). */
function rotate(h: string, deg: number): string {
  const [r, g, b] = hexRgb(h).map((x) => x / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  let hue = 0;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  if (d) hue = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  hue = (hue * 60 + deg + 360) % 360;
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((hue / 60) % 2) - 1)), m = l - c / 2;
  const [a, bb, cc] = hue < 60 ? [c, x, 0] : hue < 120 ? [x, c, 0] : hue < 180 ? [0, c, x] : hue < 240 ? [0, x, c] : hue < 300 ? [x, 0, c] : [c, 0, x];
  return rgbHex((a + m) * 255, (bb + m) * 255, (cc + m) * 255);
}

export function palette(p: Personal): [string, string, string] {
  if (p.color !== "livre") return PALETTES[p.color];
  const [r, g, b] = hexRgb(p.custom);
  return [p.custom, rotate(p.custom, 50), rgbHex(r * 0.8, g * 0.8, b * 0.8)];
}

const FONT_SCALE: Record<Personal["font"], string> = { P: "0.9", M: "1", G: "1.12", GG: "1.25" };

/** Aplica no <html>. Cores e fundo só no tema Vidro (os temas antigos têm as cores deles). */
export function applyPersonal(p: Personal): void {
  const root = document.documentElement;
  const st = root.style;
  root.dataset.orb = p.orb;
  if (p.orb_anim) delete root.dataset.orbStill; else root.dataset.orbStill = "";
  st.setProperty("--fscale", FONT_SCALE[p.font] ?? "1");
  const vidro = (root.dataset.theme ?? "").startsWith("vidro");
  const keys = ["--accent", "--accent-rgb", "--accent-strong", "--accent-2", "--accent-3", "--user", "--user-rgb",
                "--user-bg", "--user-line", "--info", "--app-bg", "--bg", "--panel-bg", "--accent-ink"];
  keys.forEach((k) => st.removeProperty(k));
  if (vidro && (p.color !== "azul" || p.bg !== "brilho")) {
    const [a, b, c] = palette(p);
    const [ar, ag, ab] = hexRgb(a), [br, bg, bb] = hexRgb(b), [cr, cg, cb] = hexRgb(c);
    if (p.color !== "azul") {
      st.setProperty("--accent", a); st.setProperty("--accent-rgb", `${ar}, ${ag}, ${ab}`);
      st.setProperty("--accent-strong", rgbHex(ar + (255 - ar) * 0.45, ag + (255 - ag) * 0.45, ab + (255 - ab) * 0.45));
      st.setProperty("--accent-2", b); st.setProperty("--accent-3", c); st.setProperty("--info", a);
      st.setProperty("--user", c); st.setProperty("--user-rgb", `${cr}, ${cg}, ${cb}`);
      st.setProperty("--user-bg", `rgba(${cr}, ${cg}, ${cb}, 0.16)`); st.setProperty("--user-line", `rgba(${cr}, ${cg}, ${cb}, 0.5)`);
      st.setProperty("--accent-ink", ar * 0.3 + ag * 0.59 + ab * 0.11 > 150 ? "#06101a" : "#ffffff");
    }
    if (p.bg === "brilho") {
      st.setProperty("--app-bg", `radial-gradient(120% 60% at 50% -10%, rgba(${cr}, ${cg}, ${cb}, 0.22), transparent 60%),
        radial-gradient(80% 50% at 100% 105%, rgba(${br}, ${bg}, ${bb}, 0.18), transparent 60%), var(--bg)`);
    } else if (p.bg === "liso") {
      st.setProperty("--app-bg", "var(--bg)");
    } else {
      st.setProperty("--bg", "#000000"); st.setProperty("--app-bg", "#000000"); st.setProperty("--panel-bg", "rgba(255, 255, 255, 0.06)");
    }
  }
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* sem espaço */ }
  window.dispatchEvent(new CustomEvent("titan:personal", { detail: p }));
}

/** "senhor", "chefe", "Luiz" ou o que o dono escreveu. */
export function addressOf(p: Personal, username: string): string {
  if (p.call === "chefe") return "chefe";
  if (p.call === "nome") return (username.split("@")[0].replace(/\./g, " ").trim().replace(/\b\w/g, (c) => c.toUpperCase())) || "senhor";
  if (p.call === "livre" && p.call_custom) return p.call_custom;
  return "senhor";
}

export function sampleLine(p: Personal, username: string): string {
  const n = addressOf(p, username);
  if (p.tone === "amigo") return `E aí, ${n}! Bora fazer o quê hoje?`;
  if (p.tone === "direto") return `${n[0].toUpperCase()}${n.slice(1)}, pronto. O que precisa?`;
  return `Boa noite, ${n}. Em que posso ser útil?`;
}

/** O jeito atual (atualiza quando o dono muda em Personalizar). */
export function usePersonal(): Personal {
  const [p, setP] = useState<Personal>(cachedPersonal);
  useEffect(() => {
    const on = (e: Event) => setP((e as CustomEvent<Personal>).detail);
    window.addEventListener("titan:personal", on);
    return () => window.removeEventListener("titan:personal", on);
  }, []);
  return p;
}
