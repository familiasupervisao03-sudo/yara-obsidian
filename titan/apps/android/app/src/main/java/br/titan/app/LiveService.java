package br.titan.app;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.SystemClock;

/**
 * Deixa o TITAN "ligado" no celular, como o WhatsApp: confere a cada minuto se chegou mensagem
 * ou lembrete novo, mesmo com o app fechado. O Android exige um aviso fixo e discreto
 * ("TITAN conectado") enquanto isso roda; dá para escondê-lo nas configurações do app.
 * Sem Google/Firebase: fala só com o notebook, pela mesma sessão do app.
 */
public class LiveService extends Service {
    static final String ACTION_CHECK = "br.titan.app.CHECAR";
    private static final String CHANNEL = "titan-conectado";
    private static final int NOTIFY_ID = 7;
    private static final long EVERY_MS = 60_000;
    private static final long BACKUP_MS = 10 * 60_000;

    private HandlerThread thread;
    private Handler handler;
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            try { NotesJob.check(LiveService.this); } catch (Exception ignored) { /* notebook fora do ar */ }
            handler.postDelayed(this, EVERY_MS);
        }
    };

    static void start(Context c) {
        Intent i = new Intent(c, LiveService.class);
        try {
            // Com o app na tela, um início normal basta (o próprio serviço vira "ligado");
            // assim o Android não exige prazo e não fecha o app se algo falhar.
            c.startService(i);
        } catch (Throwable notNow) {
            try {
                if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
            } catch (Throwable ignored) {
                // o Android não deixou agora (app em segundo plano): o alarme reserva continua checando
            }
        }
        armBackup(c);
    }

    /** Reserva: um alarme a cada ~10 min que funciona até com o celular dormindo. */
    static void armBackup(Context c) {
        AlarmManager am = c.getSystemService(AlarmManager.class);
        Intent i = new Intent(c, Reminders.class).setAction(ACTION_CHECK);
        PendingIntent pi = PendingIntent.getBroadcast(c, 9191, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime() + BACKUP_MS, pi);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        try {
            begin();
        } catch (Throwable e) {   // algum celular não deixou: sem o modo "ligado", o app segue normal
            android.util.Log.w("TITAN", "Modo ligado indisponível", e);
            stopSelf();
        }
    }

    private void begin() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "TITAN conectado (fixo)", NotificationManager.IMPORTANCE_MIN);
            ch.setDescription("Aviso discreto que o Android exige para o TITAN receber mensagens com o app fechado. Pode desligar este; as mensagens continuam.");
            ch.setShowBadge(false);
            nm.createNotificationChannel(ch);
        }
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        b.setSmallIcon(R.drawable.ic_stat_titan).setColor(0xFF3EE8FF)
                .setContentTitle("TITAN conectado").setContentText("Recebendo mensagens e lembretes")
                .setContentIntent(open).setOngoing(true).setShowWhen(false);
        if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_MIN);
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFY_ID, b.build(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        else startForeground(NOTIFY_ID, b.build());
        thread = new HandlerThread("titan-live");
        thread.start();
        handler = new Handler(thread.getLooper());
        handler.post(tick);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) { return START_STICKY; }

    @Override
    public void onDestroy() {
        if (handler != null) handler.removeCallbacks(tick);
        if (thread != null) thread.quitSafely();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
