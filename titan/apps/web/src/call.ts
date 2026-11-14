// "Ligar TITAN": funções simples da tela de chamada (testadas em tests/call.test.ts).

/** Tempo "chamando" antes do TITAN atender. */
export const RING_MS = 3000;

/** "luiz" → "Luiz" (para o "Oi, Luiz! Pode falar."). */
export function greeting(username: string): string {
  const n = username.trim().split(/[\s._-]+/)[0] ?? "";
  return n ? `Oi, ${n.charAt(0).toUpperCase()}${n.slice(1)}! Pode falar.` : "Oi! Pode falar.";
}

export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
