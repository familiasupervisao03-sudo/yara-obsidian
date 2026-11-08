package br.titan.app;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.webkit.CookieManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * A cada ~15 minutos (com rede), pergunta ao TITAN do notebook se ele mandou mensagem
 * (bom dia, papo, "e aí, resolveu?") e mostra o aviso — mesmo com o app fechado.
 * Usa a mesma sessão (cookie) da tela e só fala com o endereço salvo, em https.
 */
public class NotesJob extends JobService {
    private static final int JOB_ID = 4242;
    private static final Pattern UUID = Pattern.compile("^[0-9a-f-]{36}$");

    static void ensure(Context c) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        if (js.getPendingJob(JOB_ID) != null) return;
        js.schedule(new JobInfo.Builder(JOB_ID, new ComponentName(c, NotesJob.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .setPersisted(true)
                .build());
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            try { check(NotesJob.this); } catch (Exception ignored) { /* notebook desligado ou sem sessão */ }
            jobFinished(params, false);
        }, "titan-notes").start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) { return true; }

    /** Uma checagem: mensagens novas + lembretes marcados (de qualquer lugar) agendados aqui. */
    static synchronized void check(Context c) throws Exception {
        android.content.SharedPreferences p = c.getSharedPreferences("titan", Context.MODE_PRIVATE);
        Exception last = null;
        for (String server : new String[]{p.getString("server", null), p.getString(MainActivity.KEY_ALT, null)}) {
            if (server == null || !server.startsWith("https://")) continue;
            try { checkAt(c, server); return; } catch (Exception e) { last = e; } // tenta a reserva
        }
        if (last != null) throw last;
    }

    private static void checkAt(Context c, String server) throws Exception {
        String cookie = CookieManager.getInstance().getCookie(server);
        if (cookie == null || cookie.isEmpty()) return;
        syncReminders(c, server, cookie);
        JSONArray notes = new JSONArray(request(server + "/api/v1/brain/notes", "GET", cookie, null));
        if (notes.length() == 0) return;
        Set<String> local = Reminders.scheduledIds(c);
        JSONArray ids = new JSONArray();
        for (int i = 0; i < notes.length() && i < 5; i++) {
            JSONObject n = notes.getJSONObject(i);
            ids.put(n.getString("id"));
            String todo = n.optString("todo_id", "");
            if ("lembrete".equals(n.optString("kind")) && local.contains(todo)) continue; // já tocou aqui
            String conv = n.optString("conversation_id", "");
            String target = UUID.matcher(conv).matches() ? "titan://conversa/" + conv : "titan://acao/inicio";
            Notifier.show(c, n.getString("id").hashCode(), n.optString("title", "TITAN"), n.optString("body", ""),
                    target, "lembrete".equals(n.optString("kind")));
        }
        request(server + "/api/v1/brain/notes/delivered", "POST", cookie, new JSONObject().put("ids", ids).toString());
    }

    /**
     * Lembretes criados em qualquer lugar (Central, Casa, chat no notebook) ficam agendados
     * NO CELULAR também: tocam na hora certa mesmo com o app fechado.
     */
    private static void syncReminders(Context c, String server, String cookie) throws Exception {
        JSONArray up = new JSONArray(request(server + "/api/v1/brain/reminders/upcoming", "GET", cookie, null));
        JSONArray out = new JSONArray();
        for (int i = 0; i < up.length(); i++) {
            JSONObject r = up.getJSONObject(i);
            long at = parseIso(r.optString("due_at", ""));
            if (at > 0) out.put(new JSONObject().put("id", r.getString("id")).put("title", r.optString("title", "Lembrete")).put("at", at));
        }
        Reminders.scheduleIfChanged(c, out.toString());
    }

    /** "2026-11-08T17:30:00.123+00:00" → milissegundos (0 se não entender). */
    static long parseIso(String s) {
        try {
            java.util.regex.Matcher m = Pattern.compile("^(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2})(?:\\.\\d+)?(Z|[+-]\\d{2}:?\\d{2})?$").matcher(s);
            if (!m.matches()) return 0;
            String zone = m.group(2) == null || m.group(2).equals("Z") ? "+0000" : m.group(2).replace(":", "");
            java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssZ", java.util.Locale.US);
            java.util.Date d = f.parse(m.group(1) + zone);
            return d == null ? 0 : d.getTime();
        } catch (Exception e) {
            return 0;
        }
    }

    private static String request(String url, String method, String cookie, String body) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setConnectTimeout(8000);
        con.setReadTimeout(8000);
        con.setRequestMethod(method);
        con.setRequestProperty("Cookie", cookie);
        con.setRequestProperty("Accept", "application/json");
        if (body != null) {
            con.setRequestProperty("X-Titan-Request", "1");
            con.setRequestProperty("Content-Type", "application/json");
            con.setDoOutput(true);
            try (OutputStream os = con.getOutputStream()) { os.write(body.getBytes(StandardCharsets.UTF_8)); }
        }
        int code = con.getResponseCode();
        if (code == 204) return "";
        if (code != 200) throw new IllegalStateException("HTTP " + code);
        try (InputStream in = con.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0 && out.size() < 512 * 1024) out.write(buf, 0, n);
            return out.toString("UTF-8");
        }
    }
}
