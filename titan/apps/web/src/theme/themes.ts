// Temas visuais: a lista mostrada em Sistema → Aparência e a aplicação no <html>.
// Para criar um tema, veja src/theme/README.md.
export interface ThemeInfo { id: string; nome: string; descricao: string }

export const THEMES: ThemeInfo[] = [
  { id: "futurista", nome: "Futurista", descricao: "HUD neon, painéis de vidro e cantos cortados" },
  { id: "classico", nome: "Clássico", descricao: "Grafite sóbrio, sem brilhos" },
];
export const DEFAULT_THEME = "futurista";
const KEY = "titan.aparencia";

export interface Appearance { theme: string; leve: boolean }

export function loadAppearance(): Appearance {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    const theme = THEMES.some((t) => t.id === v.theme) ? v.theme : DEFAULT_THEME;
    return { theme, leve: Boolean(v.leve) };
  } catch {
    return { theme: DEFAULT_THEME, leve: false };
  }
}

export function applyAppearance(a: Appearance): void {
  const root = document.documentElement;
  root.dataset.theme = a.theme;
  if (a.leve) root.dataset.leve = "";
  else delete root.dataset.leve;
  // Cor da barra do navegador/celular acompanha o fundo do tema.
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg || "#03070c");
}

export function saveAppearance(a: Appearance): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(a));
  } catch {
    /* sem armazenamento: vale só nesta visita */
  }
  applyAppearance(a);
  window.dispatchEvent(new CustomEvent("titan:aparencia", { detail: a }));
}
