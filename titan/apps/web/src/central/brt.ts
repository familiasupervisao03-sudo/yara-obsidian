// Horário de Brasília para os relógios (não depende do fuso configurado no aparelho).
export const TZ = "America/Sao_Paulo";
const fmt = new Intl.DateTimeFormat("pt-BR", { timeZone: TZ, hour12: false, weekday: "short", year: "numeric",
  month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const DOW: Record<string, number> = { dom: 0, seg: 1, ter: 2, qua: 3, qui: 4, sex: 5, "sáb": 6, sab: 6 };

export interface BrTime { h: number; m: number; s: number; dow: number; day: number; month: number; year: number }

export function brt(d: Date = new Date()): BrTime {
  const p: Record<string, string> = {};
  for (const x of fmt.formatToParts(d)) p[x.type] = x.value;
  return { h: Number(p.hour) % 24, m: Number(p.minute), s: Number(p.second),
    dow: DOW[(p.weekday ?? "").replace(".", "").toLowerCase()] ?? d.getDay(),
    day: Number(p.day), month: Number(p.month) - 1, year: Number(p.year) };
}
