// "Ei, Titã": palavra de ativação da Central (escuta contínua só obedece com ela).

/** Tira acentos e deixa minúsculo SEM mudar o tamanho do texto (posição a posição). */
export function plain(t: string): string {
  return t.split("").map((ch) => ch.normalize("NFD")[0]).join("").toLowerCase();
}

// Palavra de ativação: "Ei, Titã" (Central e Casa). A Casa também aceita "Ei, Casa".
// (Separar uma palavra para cada app fica para depois.)
export const CENTRAL_WAKE = ["titan", "tita", "tito"];
export const CASA_WAKE = ["titan", "tita", "tito", "casa"];

/** "Ei, Titã, liga a luz" → ["liga a luz", true]; "liga a luz" → ["liga a luz", false]. */
export function stripWake(t: string, names: string[] = CENTRAL_WAKE): [string, boolean] {
  const n = plain(t);
  const re = new RegExp(`^\\s*(?:(?:ei|hey|oi|ok|e ai|eai)[\\s,]+)?(?:${names.join("|")})\\b[\\s,.!:;-]*`);
  const m = n.match(re);
  return m ? [t.slice(m[0].length).trim(), true] : [t.trim(), false];
}
