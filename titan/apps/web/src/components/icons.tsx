// Ícones próprios em SVG (traço de 1.75px, herdam a cor do texto). Sem bibliotecas externas.
import type { ReactNode } from "react";

export type IconName = "home" | "chat" | "mic" | "tasks" | "system" | "history" | "plus" | "list" | "logout" | "globe" | "play" | "plug" | "bell" | "brain" | "pin" | "target" | "check" | "clock" | "trash" | "edit";

const PATHS: Record<IconName, ReactNode> = {
  home: <><path d="M4 11.5 12 5l8 6.5" /><path d="M6.5 10v8.5h11V10" /></>,
  chat: <path d="M5 6.5h14v9H10l-4 3v-3H5z" />,
  mic: <><rect x="9.5" y="4" width="5" height="10" rx="2.5" /><path d="M6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v3" /></>,
  tasks: <><path d="M5 7.5 6.5 9 9 6.5M5 14.5 6.5 16 9 13.5" /><path d="M11.5 8h7.5M11.5 15h7.5" /></>,
  system: <><circle cx="12" cy="12" r="2.75" /><path d="M12 4.5v2.2M12 17.3v2.2M4.5 12h2.2M17.3 12h2.2M6.7 6.7l1.6 1.6M15.7 15.7l1.6 1.6M6.7 17.3l1.6-1.6M15.7 8.3l1.6-1.6" /></>,
  history: <><path d="M5 12a7 7 0 1 0 2.1-5" /><path d="M5 5v3.5h3.5M12 8.5V12l2.5 1.5" /></>,
  plus: <path d="M12 6v12M6 12h12" />,
  list: <path d="M5 7h14M5 12h14M5 17h14" />,
  globe: <><circle cx="12" cy="12" r="7.5" /><path d="M4.5 12h15M12 4.5c2.2 2.2 3.2 4.7 3.2 7.5s-1 5.3-3.2 7.5c-2.2-2.2-3.2-4.7-3.2-7.5s1-5.3 3.2-7.5z" /></>,
  play: <><rect x="4" y="5.5" width="16" height="13" rx="2.5" /><path d="M10.5 9.5v5l4-2.5z" /></>,
  plug: <><path d="M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5" /><path d="M4 4l16 16" /></>,
  bell: <><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></>,
  brain: <><path d="M9.5 5a3 3 0 0 0-3 3 3 3 0 0 0-1.5 5.3A3 3 0 0 0 9 18.5h.5V5z" /><path d="M14.5 5a3 3 0 0 1 3 3 3 3 0 0 1 1.5 5.3 3 3 0 0 1-4 5.2h-.5V5z" /><path d="M9.5 9.5H8M14.5 9.5H16M9.5 14H8M14.5 14H16" /></>,
  pin: <><path d="M9 4h6l-1 5 3 3H7l3-3z" /><path d="M12 12v8" /></>,
  target: <><circle cx="12" cy="12" r="7.5" /><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="0.8" /></>,
  check: <path d="M5.5 12.5 10 17l8.5-9.5" />,
  clock: <><circle cx="12" cy="12" r="7.5" /><path d="M12 8v4.5l3 1.5" /></>,
  trash: <><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" /></>,
  edit: <><path d="M5 19h4L19 9l-4-4L5 15z" /><path d="M13.5 6.5l4 4" /></>,
  logout: <><path d="M10 5H6v14h4" /><path d="M14 8.5 17.5 12 14 15.5M17.5 12H9.5" /></>,
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}
