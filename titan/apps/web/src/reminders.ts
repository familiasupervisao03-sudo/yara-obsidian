// Lembretes com hora: o app Android agenda os avisos NO PRÓPRIO CELULAR (tocam na hora
// mesmo com o notebook desligado). No navegador, o aviso vem do servidor (mensagens do TITAN).
import { brain } from "./brain";
import { androidApp } from "./notify";

interface ReminderBridge {
  scheduleReminders?: (json: string) => void;
}

let last = "";
let lastAt = 0;

export function syncReminders(): void {
  const app = androidApp() as unknown as ReminderBridge | null;
  if (!app || typeof app.scheduleReminders !== "function") return;
  if (Date.now() - lastAt < 60_000) return;
  lastAt = Date.now();
  brain.upcoming().then((items) => {
    const json = JSON.stringify(items.map((r) => ({ id: r.id, title: r.title, at: Date.parse(r.due_at) })));
    if (json !== last) {
      last = json;
      app.scheduleReminders!(json);
    }
  }).catch(() => undefined);
}

/** Força a próxima sincronização (ex.: depois de criar ou adiar um lembrete). */
export function remindersChanged(): void {
  lastAt = 0;
  syncReminders();
}
