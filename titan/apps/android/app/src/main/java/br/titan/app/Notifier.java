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

/**
 * Avisos do sistema: lembretes e mensagens do TITAN, como os do WhatsApp:
 * prioridade alta (aparecem por cima da tela, com som e vibração) e conteúdo visível na tela
 * bloqueada. (Os canais antigos eram de prioridade normal; o Android não deixa mudar a
 * prioridade de um canal que já existe, por isso os canais novos têm outro nome.)
 */
final class Notifier {
    static final String CHANNEL = "titan-mensagens";
    static final String CHANNEL_REMINDERS = "titan-lembretes-alta";
    private static final String[] OLD_CHANNELS = {"titan", "titan-lembretes"};

    private Notifier() {}

    static boolean allowed(Context c) {
        return Build.VERSION.SDK_INT < 33
                || c.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    private static void ensureChannels(NotificationManager nm) {
        if (Build.VERSION.SDK_INT < 26) return;
        for (String old : OLD_CHANNELS) if (nm.getNotificationChannel(old) != null) nm.deleteNotificationChannel(old);
        if (nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Mensagens do TITAN", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("Bom dia, avisos e mensagens que o TITAN manda por conta própria.");
            ch.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            ch.enableVibration(true);
            nm.createNotificationChannel(ch);
        }
        if (nm.getNotificationChannel(CHANNEL_REMINDERS) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL_REMINDERS, "Lembretes do TITAN", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("Lembretes na hora marcada.");
            ch.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            ch.enableVibration(true);
            ch.setVibrationPattern(new long[]{0, 300, 200, 300});
            nm.createNotificationChannel(ch);
        }
    }

    /** ``target``: titan://acao/inicio, titan://conversa/<id>… (abre o app no lugar certo). */
    @SuppressWarnings("deprecation")
    static void show(Context c, int id, String title, String body, String target, boolean reminder) {
        if (!allowed(c)) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        ensureChannels(nm);
        String channel = reminder ? CHANNEL_REMINDERS : CHANNEL;
        Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse(target == null ? "titan://acao/inicio" : target),
                c, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(c, id, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, channel)
                : new Notification.Builder(c);
        String text = body == null ? "" : body;
        b.setSmallIcon(R.drawable.ic_stat_titan)          // ícone branco da barra (o colorido vira quadrado)
                .setColor(0xFF3EE8FF)
                .setContentTitle(title == null ? "TITAN" : title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(pi)
                .setAutoCancel(true)
                .setShowWhen(true)
                .setVisibility(Notification.VISIBILITY_PUBLIC)   // aparece na tela bloqueada
                .setCategory(reminder ? Notification.CATEGORY_REMINDER : Notification.CATEGORY_MESSAGE);
        if (Build.VERSION.SDK_INT < 26) {                  // Androids antigos: prioridade no próprio aviso
            b.setPriority(Notification.PRIORITY_HIGH).setDefaults(Notification.DEFAULT_ALL);
        }
        nm.notify(id, b.build());
    }
}
