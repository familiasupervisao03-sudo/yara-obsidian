package br.titan.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

/**
 * App TITAN: abre o TITAN que roda no notebook (o servidor é um só, o do notebook).
 *
 * Segurança:
 * - só abre endereços https:// (o cadeado do TITAN é instalado em Configurações);
 * - certificado inválido = não abre (nunca "continuar mesmo assim");
 * - microfone e câmera só para páginas do próprio servidor;
 * - links de fora abrem no navegador, fora do app.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "titan";
    private static final String KEY_SERVER = "server";
    private static final int REQ_MEDIA = 10;
    private static final String CHANNEL = "titan";

    private WebView web;
    private String server; // ex.: https://192.168.0.10:8000 (sem barra no fim)
    private PermissionRequest pendingPermission;
    private int notifyId = 1;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        server = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, null);
        if (server == null) showSetup(null);
        else openTitan(pathFor(getIntent()));
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (isConfigure(intent) || server == null) { showSetup(null); return; }
        String path = pathFor(intent);
        if (web != null) web.loadUrl(server + path);
        else openTitan(path);
    }

    // --- endereço do servidor -------------------------------------------------------

    private static boolean isConfigure(Intent i) {
        Uri d = i == null ? null : i.getData();
        return d != null && "titan".equals(d.getScheme()) && "configurar".equals(d.getHost());
    }

    /** Converte atalho / compartilhamento no caminho da interface do TITAN. */
    private String pathFor(Intent i) {
        if (i == null) return "/";
        if (isConfigure(i)) { showSetup(null); return "/"; }
        Uri d = i.getData();
        if (d != null && "titan".equals(d.getScheme()) && "acao".equals(d.getHost())) {
            String acao = d.getLastPathSegment();
            if ("voz".equals(acao) || "conversa".equals(acao) || "aula".equals(acao) || "aprovacoes".equals(acao)) {
                return "/?acao=" + acao;
            }
        }
        if (Intent.ACTION_SEND.equals(i.getAction())) {
            String text = i.getStringExtra(Intent.EXTRA_TEXT);
            String title = i.getStringExtra(Intent.EXTRA_SUBJECT);
            return "/compartilhar?title=" + Uri.encode(title == null ? "" : title)
                    + "&text=" + Uri.encode(text == null ? "" : text) + "&url=";
        }
        return "/";
    }

    static String normalize(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) return null;
        if (!s.contains("://")) s = "https://" + s;
        Uri u = Uri.parse(s);
        if (!"https".equals(u.getScheme()) || u.getHost() == null || u.getHost().isEmpty()) return null;
        String port = u.getPort() > 0 ? ":" + u.getPort() : "";
        return "https://" + u.getHost() + port;
    }

    private void showSetup(String error) {
        if (web != null) { web.destroy(); web = null; }
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(56, 120, 56, 56);
        box.setBackgroundColor(Color.parseColor("#03070c"));

        TextView title = new TextView(this);
        title.setText("T I T A N");
        title.setTextColor(Color.parseColor("#3ee8ff"));
        title.setTextSize(30);
        title.setGravity(Gravity.CENTER);
        box.addView(title);

        TextView help = new TextView(this);
        help.setText("Endereço do TITAN no seu notebook.\n\nNo notebook, rode \"titan ligar-celular\": ele mostra o "
                + "endereço (ex.: https://192.168.0.10:8000) e a página para instalar o cadeado. Instale o cadeado "
                + "antes de continuar.");
        help.setTextColor(Color.parseColor("#86aebe"));
        help.setTextSize(15);
        help.setPadding(0, 48, 0, 24);
        box.addView(help);

        EditText input = new EditText(this);
        input.setHint("https://192.168.0.10:8000");
        input.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        input.setTextColor(Color.WHITE);
        input.setHintTextColor(Color.parseColor("#4b6a78"));
        input.setSingleLine(true);
        if (server != null) input.setText(server);
        box.addView(input);

        if (error != null) {
            TextView err = new TextView(this);
            err.setText(error);
            err.setTextColor(Color.parseColor("#ffb547"));
            err.setPadding(0, 24, 0, 0);
            box.addView(err);
        }

        Button go = new Button(this);
        go.setText("CONECTAR");
        go.setOnClickListener(v -> {
            String s = normalize(input.getText().toString());
            if (s == null) { showSetup("Use um endereço que comece com https:// (o TITAN só abre com cadeado)."); return; }
            server = s;
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_SERVER, s).apply();
            openTitan("/");
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = 40;
        box.addView(go, lp);
        setContentView(box);
    }

    // --- o TITAN ----------------------------------------------------------------------

    private boolean sameServer(Uri u) {
        Uri s = Uri.parse(server);
        return u != null && "https".equals(u.getScheme()) && s.getHost().equalsIgnoreCase(u.getHost())
                && s.getPort() == u.getPort();
    }

    private void openTitan(String path) {
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#03070c"));
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false); // a voz do TITAN toca sem precisar de toque
        ws.setAllowFileAccess(false);
        ws.setAllowContentAccess(false);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        ws.setSupportMultipleWindows(false);
        web.addJavascriptInterface(new Bridge(), "TitanAndroid");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (sameServer(u)) return false;
                // Fontes, links das aulas etc.: abrem no navegador, fora do app.
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel(); // nunca continua sem cadeado válido
                runOnUiThread(() -> showSetup("O cadeado do TITAN não está instalado neste celular (ou o endereço "
                        + "mudou). Rode \"titan ligar-celular\" no notebook e siga a página de instalação."));
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame() && view.getUrl() == null) {
                    runOnUiThread(() -> showOffline());
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> handleMediaPermission(request));
            }
        });

        setContentView(web);
        web.loadUrl(server + path);
    }

    private void showOffline() {
        new AlertDialog.Builder(this)
                .setTitle("Notebook fora do alcance")
                .setMessage("Não consegui falar com o TITAN em " + server + ".\n\nConfira se o notebook está ligado, "
                        + "com o TITAN aberto, e se o celular está na mesma Wi-Fi (ou no Tailscale).")
                .setPositiveButton("Tentar de novo", (d, w) -> { if (web != null) web.loadUrl(server + "/"); })
                .setNegativeButton("Trocar endereço", (d, w) -> showSetup(null))
                .show();
    }

    // --- microfone e câmera ------------------------------------------------------------

    private void handleMediaPermission(PermissionRequest request) {
        if (!sameServer(request.getOrigin())) { request.deny(); return; }
        List<String> need = new ArrayList<>();
        for (String r : request.getResources()) {
            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) need.add(Manifest.permission.RECORD_AUDIO);
            if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(r)) need.add(Manifest.permission.CAMERA);
        }
        List<String> missing = new ArrayList<>();
        for (String p : need) if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) missing.add(p);
        if (missing.isEmpty()) { request.grant(request.getResources()); return; }
        pendingPermission = request;
        requestPermissions(missing.toArray(new String[0]), REQ_MEDIA);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (code != REQ_MEDIA || pendingPermission == null) return;
        boolean ok = results.length > 0;
        for (int r : results) ok &= r == PackageManager.PERMISSION_GRANTED;
        if (ok) pendingPermission.grant(pendingPermission.getResources());
        else pendingPermission.deny();
        pendingPermission = null;
    }

    // --- voltar ------------------------------------------------------------------------

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }

    // --- ponte com a interface do TITAN (tela acesa e avisos) --------------------------

    private class Bridge {
        @JavascriptInterface
        public boolean isApp() { return true; }

        /** Tela acesa durante a conversa por voz. */
        @JavascriptInterface
        public void keepAwake(boolean on) {
            runOnUiThread(() -> {
                if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            });
        }

        @JavascriptInterface
        public boolean canNotify() {
            return Build.VERSION.SDK_INT < 33
                    || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
        }

        @JavascriptInterface
        public void askNotify() {
            if (Build.VERSION.SDK_INT >= 33) runOnUiThread(() ->
                    requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 11));
        }

        /** Aviso do sistema (aprovação pendente, aula pronta, resposta pronta). */
        @JavascriptInterface
        public void notify(String title, String body, String path) {
            if (!canNotify()) return;
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
                nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Avisos do TITAN",
                        NotificationManager.IMPORTANCE_DEFAULT));
            }
            String safe = path != null && path.startsWith("/") ? path : "/";
            Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse("titan://acao" + (safe.contains("aprovacoes")
                    ? "/aprovacoes" : "/inicio")), MainActivity.this, MainActivity.class);
            PendingIntent pi = PendingIntent.getActivity(MainActivity.this, 0, open,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            Notification.Builder b = Build.VERSION.SDK_INT >= 26
                    ? new Notification.Builder(MainActivity.this, CHANNEL)
                    : new Notification.Builder(MainActivity.this);
            b.setSmallIcon(R.mipmap.ic_launcher)
                    .setContentTitle(title == null ? "TITAN" : title)
                    .setContentText(body == null ? "" : body)
                    .setStyle(new Notification.BigTextStyle().bigText(body == null ? "" : body))
                    .setContentIntent(pi)
                    .setAutoCancel(true);
            nm.notify(notifyId++, b.build());
        }
    }

}
