// Ícones das vídeo-aulas (traço, 24×24, herdam a cor). Lista fechada igual à do servidor
// (titan/lessons/script.py ICONS): a IA só escolhe o nome, nunca o desenho.
import type { ReactNode } from "react";

const P: Record<string, ReactNode> = {
  folha: <><path d="M5 19c0-8 5-13 14-14-1 9-6 14-14 14z" /><path d="M5 19 13 11" /></>,
  sol: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  gota: <path d="M12 3c3.5 4.5 6 7.6 6 11a6 6 0 0 1-12 0c0-3.4 2.5-6.5 6-11z" />,
  nuvem: <path d="M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 18z" />,
  vento: <path d="M3 9h11a3 3 0 1 0-3-3M3 15h15a3 3 0 1 1-3 3M3 12h8" />,
  fogo: <path d="M12 3c1 3 4 4.5 4 9a4 4 0 0 1-8 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 0-8z" />,
  terra: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.5 2.5 3.5 5.2 3.5 8.5s-1 6-3.5 8.5c-2.5-2.5-3.5-5.2-3.5-8.5s1-6 3.5-8.5z" /></>,
  lua: <path d="M19 14.5A8 8 0 1 1 9.5 5a6.5 6.5 0 0 0 9.5 9.5z" />,
  estrela: <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.9z" />,
  atomo: <><circle cx="12" cy="12" r="1.5" /><ellipse cx="12" cy="12" rx="9" ry="3.6" /><ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(60 12 12)" /><ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(120 12 12)" /></>,
  dna: <path d="M7 3c0 6 10 6 10 12s-10 6-10 6M17 3c0 6-10 6-10 12M8.5 7h7M8.5 17h7M10 12h4" />,
  coracao: <path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.6 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z" />,
  cerebro: <path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3h1V4zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3h-1V4z" />,
  olho: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="3" /></>,
  pessoa: <><circle cx="12" cy="8" r="3.5" /><path d="M5 20c0-4 3-6.5 7-6.5s7 2.5 7 6.5" /></>,
  grupo: <><circle cx="9" cy="8.5" r="3" /><circle cx="16.5" cy="9.5" r="2.5" /><path d="M3 19.5c0-3.3 2.6-5.5 6-5.5s6 2.2 6 5.5M15 14.2c3 0 5.5 1.8 5.5 5" /></>,
  casa: <><path d="M4 11.5 12 5l8 6.5" /><path d="M6.5 10v9.5h11V10M10 19.5v-5h4v5" /></>,
  predio: <><rect x="5" y="3.5" width="9" height="17" /><path d="M14 9h5v11.5h-5M8 7.5h3M8 11h3M8 14.5h3M16.5 12.5h1M16.5 16h1" /></>,
  carro: <><path d="M4 16v-3.5L6.2 8h11.6L20 12.5V16z" /><circle cx="7.5" cy="16.5" r="1.8" /><circle cx="16.5" cy="16.5" r="1.8" /></>,
  aviao: <path d="M21 4 3 11l7 2.5L12.5 21 21 4zM10 13.5l4-4" />,
  relogio: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3.5 2" /></>,
  calendario: <><rect x="4" y="5.5" width="16" height="14" rx="2" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" /></>,
  livro: <path d="M4 5.5A2 2 0 0 1 6 4h13v14H6a2 2 0 0 0-2 2zM4 20V5.5M8 8h7" />,
  lapis: <path d="M4 20l1-4L16 5l3 3L8 19zM14 7l3 3" />,
  lampada: <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z" />,
  engrenagem: <><circle cx="12" cy="12" r="3" /><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" /></>,
  computador: <><rect x="3.5" y="4.5" width="17" height="11" rx="1.5" /><path d="M8 20h8M12 15.5V20" /></>,
  celular: <><rect x="7" y="3" width="10" height="18" rx="2" /><path d="M11 17.5h2" /></>,
  internet: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.5 2.5 3.5 5.2 3.5 8.5s-1 6-3.5 8.5M12 3.5C9.5 6 8.5 8.7 8.5 12s1 6 3.5 8.5" /></>,
  cadeado: <><rect x="5" y="10.5" width="14" height="10" rx="2" /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3M12 14.5v2" /></>,
  dinheiro: <><rect x="3" y="6.5" width="18" height="11" rx="2" /><circle cx="12" cy="12" r="2.5" /><path d="M6.5 9.5v5M17.5 9.5v5" /></>,
  grafico: <path d="M4 20V4M4 20h16M8 16v-4M12 16V8M16 16v-6" />,
  calculadora: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 7h8M8.5 11h.01M12 11h.01M15.5 11h.01M8.5 14.5h.01M12 14.5h.01M15.5 14.5h.01M8.5 18h.01M12 18h3.5" /></>,
  balanca: <path d="M12 4v16M7 20h10M5 7h14M5 7l-2.5 6a3 3 0 0 0 5 0zM19 7l-2.5 6a3 3 0 0 0 5 0z" />,
  alvo: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" /></>,
  bandeira: <path d="M5 21V4M5 4h11l-2 4 2 4H5" />,
  mapa: <path d="M3.5 6.5 9 4l6 2.5L20.5 4v13.5L15 20l-6-2.5L3.5 20zM9 4v13.5M15 6.5V20" />,
  comida: <path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10M16 3c-2 1.5-3 4-3 7h3v11" />,
  musica: <><path d="M9 17.5V5l11-2v12.5" /><circle cx="6.5" cy="17.5" r="2.5" /><circle cx="17.5" cy="15.5" r="2.5" /></>,
  pincel: <path d="M14 4l6 6-8 8-4-4zM8 14c-3 0-4 2.5-4 6 3.5 0 6-1 6-4" />,
  raio: <path d="M13 3 5 13.5h6l-1 7.5 8-10.5h-6z" />,
  escudo: <path d="M12 3 5 6v5.5c0 4.3 3 7.7 7 9.5 4-1.8 7-5.2 7-9.5V6z" />,
  alerta: <><path d="M12 4 2.5 20h19z" /><path d="M12 10v4.5M12 17.5h.01" /></>,
  check: <path d="M5 12.5 10 17 19 7" />,
  pergunta: <><circle cx="12" cy="12" r="8.5" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 16.5h.01" /></>,
  seta: <path d="M4 12h15M14 7l5 5-5 5" />,
  cubo: <><path d="M12 3 20 7.5v9L12 21 4 16.5v-9z" /><path d="M12 12 20 7.5M12 12v9M12 12 4 7.5" /></>,
  planta: <path d="M12 21v-9M12 12c0-4 3-7 7-7 0 4-3 7-7 7zM12 15c0-3-2.5-5.5-6-5.5 0 3 2.5 5.5 6 5.5zM8 21h8" />,
  ima: <path d="M6 4v8a6 6 0 0 0 12 0V4h-4v8a2 2 0 0 1-4 0V4zM6 8h4M14 8h4" />,
};

export function LessonIcon({ name, size = 24, className }: { name?: string; size?: number; className?: string }) {
  const path = name ? P[name] : undefined;
  if (!path) return null;
  return (
    <svg className={`licon ${className ?? ""}`} width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {path}
    </svg>
  );
}

export const hasLessonIcon = (name?: string) => Boolean(name && P[name]);
