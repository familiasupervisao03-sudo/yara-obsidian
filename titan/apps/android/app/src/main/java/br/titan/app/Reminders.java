package br.titan.app;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashSet;
import java.util.Set;

/**
 * Lembretes com hora agendados NO CELULAR: tocam na hora mesmo com o notebook desligado
 * ou sem internet. A lista vem do TITAN (próximos 7 dias) sempre que o app abre.
 */
public final class Reminders extends BroadcastReceiver {
    static final String PREFS = "titan-lembretes";
    private static final String KEY_JSON = "json";
    private static final String KEY_IDS = "ids";
    private static final String ACTION = "br.titan.app.LEMBRETE";

    /** Chamado pela tela (ponte) e depois de reiniciar o celular. */
    static void schedule(Context c, String json) {
        SharedPreferences p = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        AlarmManager am = c.getSystemService(AlarmManager.class);
        for (String old : p.getStringSet(KEY_IDS, new HashSet<>())) am.cancel(pending(c, old, "", false));
        Set<String> ids = new HashSet<>();
        long now = System.currentTimeMillis();
        try {
            JSONArray arr = new JSONArray(json);
            for (int i = 0; i < arr.length() && i < 60; i++) {
                JSONObject r = arr.getJSONObject(i);
                String id = r.optString("id", "");
                long at = r.optLong("at", 0);
                String title = r.optString("title", "Lembrete");
                if (id.isEmpty() || at < now - 60_000) continue;
                PendingIntent pi = pending(c, id, title, true);
                boolean exact = Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms();
                if (exact) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
                else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
                ids.add(id);
            }
        } catch (Exception ignored) {
            return; // lista inválida: mantém nada agendado
        }
        p.edit().putString(KEY_JSON, json).putStringSet(KEY_IDS, ids).apply();
    }

    /** Lembretes já agendados aqui (o aviso do servidor para eles é ignorado, sem duplicar). */
    static Set<String> scheduledIds(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getStringSet(KEY_IDS, new HashSet<>());
    }

    private static PendingIntent pending(Context c, String id, String title, boolean withExtras) {
        Intent i = new Intent(c, Reminders.class).setAction(ACTION).putExtra("id", id);
        if (withExtras) i.putExtra("title", title);
        return PendingIntent.getBroadcast(c, id.hashCode(), i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    @Override
    public void onReceive(Context c, Intent intent) {
        String action = intent.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(action) || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            String json = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_JSON, "[]");
            schedule(c, json);
            NotesJob.ensure(c);
            return;
        }
        if (!ACTION.equals(action)) return;
        String id = intent.getStringExtra("id");
        String title = intent.getStringExtra("title");
        Notifier.show(c, id == null ? 1 : id.hashCode(), "TITAN · Lembrete", title, "titan://acao/inicio", true);
    }
}
