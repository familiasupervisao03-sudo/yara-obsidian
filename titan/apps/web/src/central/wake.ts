// "Ei, Titã": palavra de ativação da Central (escuta contínua só obedece com ela).

/** Tira acentos e deixa minúsculo SEM mudar o tamanho do texto (posição a posição). */
export function plain(t: string): string {
  return t.split("").map((ch) => ch.normalize("NFD")[0]).join("").toLowerCase();
}

/** "Ei, Titã, liga a luz" → ["liga a luz", true]; "liga a luz" → ["liga a luz", false]. */
export function stripWake(t: string): [string, boolean] {
  const n = plain(t);
  const m = n.match(/^\s*(?:(?:ei|hey|oi|ok|e ai|eai)[\s,]+)?(?:titan|tita|tito)\b[\s,.!:;-]*/);
  return m ? [t.slice(m[0].length).trim(), true] : [t.trim(), false];
}
