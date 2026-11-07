// "Cria um lembrete pra me avisar de tirar o bolo às 2:30 da tarde" → { título, quando }.
// Entendido aqui mesmo (sem IA, na hora). Se não achar a hora, a frase vai para a IA do TITAN.
import { plain } from "./wake.ts";

export interface ParsedReminder { title: string; due: Date }

const NUM: Record<string, number> = {
  zero: 0, um: 1, uma: 1, dois: 2, duas: 2, tres: 3, quatro: 4, cinco: 5, seis: 6, sete: 7, oito: 8, nove: 9,
  dez: 10, onze: 11, doze: 12, treze: 13, catorze: 14, quatorze: 14, quinze: 15, dezesseis: 16, dezessete: 17,
  dezoito: 18, dezenove: 19, vinte: 20, trinta: 30, quarenta: 40, cinquenta: 50, meia: 30, meio: 12,
};
const NUMW = Object.keys(NUM).sort((a, b) => b.length - a.length).join("|");
const N = `(?:\\d{1,2}|(?:${NUMW})(?: e (?:${NUMW}))?)`;
// hora: uma palavra só (senão "duas e meia" viraria um número só)
const H = `(?:\\d{1,2}|vinte e (?:um|uma|dois|duas|tres)|${NUMW})`;

/** "vinte e cinco" → 25, "14" → 14, "meia" → 30. */
function num(s: string | undefined): number | null {
  if (!s) return null;
  const t = s.trim();
  if (/^\d+$/.test(t)) return Number(t);
  let total = 0;
  for (const w of t.split(" e ")) {
    if (!(w in NUM)) return null;
    total += NUM[w];
  }
  return total;
}

const TRIGGER = /\b(lembrete|lembra|lembre|lembrar|avisa|avise|avisar|alarme|alerta)\b/;

export function parseReminder(text: string, now: Date = new Date()): ParsedReminder | null {
  const orig = text.replace(/[,.!?]/g, " ").replace(/\s+/g, " ").trim();
  const t = plain(orig);  // mesmo tamanho e mesmas palavras do original, sem acento
  if (!TRIGGER.test(t)) return null;
  let rest = ` ${t} `;
  let due: Date | null = null;

  // "daqui a 10 minutos", "em 2 horas", "daqui a meia hora"
  const rel = rest.match(new RegExp(` (?:daqui a|daqui|em|dentro de) (${N}|meia) (minutos?|min|horas?|h)\\b`));
  if (rel) {
    const n = rel[1] === "meia" ? 30 : num(rel[1]);
    if (n !== null) {
      const mins = rel[1] === "meia" ? 30 : /^h/.test(rel[2]) ? n * 60 : n;
      due = new Date(now.getTime() + mins * 60_000);
      rest = rest.replace(rel[0], " ");
    }
  }

  let dayShift: number | null = null;
  const day = rest.match(/ (depois de amanha|amanha|hoje)\b/);
  if (day) { dayShift = day[1] === "hoje" ? 0 : day[1] === "amanha" ? 1 : 2; rest = rest.replace(day[0], " "); }

  if (!due) {
    // "às 14:30", "as 14h30", "às 2 e meia da tarde", "14 horas", "meio dia", "meia noite"
    let h: number | null = null, m = 0, period = "";
    const special = rest.match(/ (?:as |a )?(meio dia|meio-dia|meia noite|meia-noite)\b/);
    if (special) { h = special[1].startsWith("meio") ? 12 : 0; rest = rest.replace(special[0], " "); }
    else {
      const re = new RegExp(` (?:as |a |pras |para as |pra )?(${H})(?:(?: ?[:h] ?| horas? e | e )(${N}))?(?: ?(?:horas?|h|hrs?))?` +
        `(?: (da manha|da tarde|da noite|da madrugada))?(?= |$)`);
      for (const mm of rest.matchAll(new RegExp(re, "g"))) {
        const hh = num(mm[1]);
        // só conta como hora se tiver "às", "h", ":", "horas" ou período (não pega "3 coisas")
        if (hh === null || hh > 23 || !/ (as|a|pras|pra|para as) |[:h]|hora|da (manha|tarde|noite|madrugada)/.test(mm[0])) continue;
        const mins = num(mm[2]) ?? 0;
        if (mins > 59) continue;
        h = hh; m = mins; period = mm[3] ?? "";
        rest = rest.replace(mm[0], " ");
        break;
      }
    }
    if (h === null) return null;
    if ((period === "da tarde" || period === "da noite") && h < 12) h += 12;
    if (period === "da manha" && h === 12) h = 0;
    due = new Date(now);
    due.setHours(h, m, 0, 0);
    if (dayShift !== null) due.setDate(due.getDate() + dayShift);
    else if (due.getTime() <= now.getTime()) {
      // já passou hoje: "2:30" sem período às 10h → 14:30; senão, amanhã
      const pm = new Date(due); pm.setHours(h + 12);
      if (!period && h < 12 && pm.getTime() > now.getTime()) due = pm;
      else due.setDate(due.getDate() + 1);
    }
  } else if (dayShift) {
    due.setDate(due.getDate() + dayShift);
  }

  // o que sobra é o assunto
  const title = rest
    .replace(/\b(ei |hey |ok )?tita[n]?\b/g, " ")
    .replace(/\b(cria|crie|criar|faz|faca|fazer|coloca|coloque|bota|poe|marca|marque|agenda|agende|adiciona|adicione)\b/g, " ")
    .replace(/\b(um|uma|o|a)? ?(lembrete|alarme|alerta)\b/g, " ")
    .replace(/\b(pra|para|por favor|favor|pfv|que|voce|vc)\b/g, " ")
    .replace(/\b(me )?(lembra|lembre|lembrar|avisa|avise|avisar)( me)?\b/g, " ")
    .replace(/\s+/g, " ").trim()
    .replace(/^(de|do|da|que|sobre|pra|para|e|o|a)\s+/g, "").replace(/^(de|do|da)\s+/, "").trim();
  // devolve as palavras do original (com acento): "mae" → "mãe"
  const ow = orig.split(" "), pw = t.split(" ");
  let from = 0;
  const words = title ? title.split(" ").map((w) => {
    const i = pw.indexOf(w, from);
    if (i < 0) return w;
    from = i + 1;
    return ow[i];
  }) : [];
  const out = words.join(" ");
  return { title: out ? out.charAt(0).toUpperCase() + out.slice(1) : "Lembrete", due };
}

export function whenText(d: Date, now: Date = new Date()): string {
  const p2 = (n: number) => String(n).padStart(2, "0");
  const hm = `${p2(d.getHours())}:${p2(d.getMinutes())}`;
  const day = new Date(now); day.setHours(0, 0, 0, 0);
  const diff = Math.round((new Date(d).setHours(0, 0, 0, 0) - day.getTime()) / 86_400_000);
  return diff === 0 ? `hoje às ${hm}` : diff === 1 ? `amanhã às ${hm}` : `${p2(d.getDate())}/${p2(d.getMonth() + 1)} às ${hm}`;
}
