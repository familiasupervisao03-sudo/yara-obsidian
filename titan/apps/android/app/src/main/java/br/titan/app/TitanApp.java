package br.titan.app;

import android.app.Application;
import android.content.Context;
import android.os.Build;

import java.io.PrintWriter;
import java.io.StringWriter;

/**
 * Se o app fechar sozinho por algum erro, guarda o motivo; na próxima vez que abrir,
 * a tela mostra o erro (para tirar print e corrigir). Nada sai do celular.
 */
public class TitanApp extends Application {
    static final String CRASH_PREFS = "titan-erro";

    @Override
    public void onCreate() {
        super.onCreate();
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
            try {
                StringWriter sw = new StringWriter();
                e.printStackTrace(new PrintWriter(sw));
                String text = "App " + BuildConfig.VERSION_NAME + " · Android " + Build.VERSION.RELEASE
                        + " · " + Build.MANUFACTURER + " " + Build.MODEL + "\n\n" + sw;
                getSharedPreferences(CRASH_PREFS, Context.MODE_PRIVATE).edit()
                        .putString("ultimo", text.length() > 6000 ? text.substring(0, 6000) : text).commit();
            } catch (Throwable ignored) { /* não piora o erro */ }
            if (previous != null) previous.uncaughtException(t, e);
        });
    }
}
