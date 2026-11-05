package br.titan.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;

/** Avisos do sistema: lembretes (tocam alto) e mensagens do TITAN. */
final class Notifier {
    static final String CHANNEL = "titan";
    static final String CHANNEL_REMINDERS = "titan-lembretes";

    private Notifier() {}

    static boolean allowed(Context c) {
        return Build.VERSION.SDK_INT < 33
                || c.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    /** ``target``: titan://acao/inicio, titan://conversa/<id>… (abre o app no lugar certo). */
    static void show(Context c, int id, String title, String body, String target, boolean reminder) {
        if (!allowed(c)) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        String channel = reminder ? CHANNEL_REMINDERS : CHANNEL;
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(channel) == null) {
            nm.createNotificationChannel(new NotificationChannel(channel,
                    reminder ? "Lembretes do TITAN" : "Mensagens do TITAN",
                    reminder ? NotificationManager.IMPORTANCE_HIGH : NotificationManager.IMPORTANCE_DEFAULT));
        }
        Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse(target == null ? "titan://acao/inicio" : target),
                c, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(c, id, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, channel)
                : new Notification.Builder(c);
        String text = body == null ? "" : body;
        b.setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title == null ? "TITAN" : title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(pi)
                .setAutoCancel(true);
        if (reminder) b.setCategory(Notification.CATEGORY_REMINDER);
        nm.notify(id, b.build());
    }
}
