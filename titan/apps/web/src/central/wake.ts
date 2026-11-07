// "Ei, Titã": palavra de ativação da Central (escuta contínua só obedece com ela).

/** Tira acentos e deixa minúsculo SEM mudar o tamanho do texto (posição a posição). */
export function plain(t: string): string {
  return t.split("").map((ch) => ch.normalize("NFD")[0]).join("").toLowerCase();
}

// Cada app tem a sua palavra, para um não responder no lugar do outro:
//   TITAN Central → "Ei, Titã"     TITAN Casa (tablet) → "Ei, Casa"
export const CENTRAL_WAKE = ["titan", "tita", "tito"];
export const CASA_WAKE = ["casa"];

/** "Ei, Titã, liga a luz" → ["liga a luz", true]; "liga a luz" → ["liga a luz", false]. */
export function stripWake(t: string, names: string[] = CENTRAL_WAKE): [string, boolean] {
  const n = plain(t);
  const re = new RegExp(`^\\s*(?:(?:ei|hey|oi|ok|e ai|eai)[\\s,]+)?(?:${names.join("|")})\\b[\\s,.!:;-]*`);
  const m = n.match(re);
  return m ? [t.slice(m[0].length).trim(), true] : [t.trim(), false];
}
