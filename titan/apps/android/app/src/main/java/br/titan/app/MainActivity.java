package br.titan.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
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
    static final String KEY_ALT = "server_alt";
    private static final int REQ_MEDIA = 10;

    private WebView web;
    private String server; // ex.: https://100.101.102.103:8000 (sem barra no fim)
    private String alt;    // reserva (ex.: Wi-Fi de casa): usado se o principal não responder
    private boolean triedAlt = false;
    private boolean loaded = false;
    private boolean errorSeen = false;
    private TextView connecting;
    private final android.os.Handler ui = new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable timeout = this::connectionFailed;
    private static final long CONNECT_TIMEOUT_MS = 12_000;
    private PermissionRequest pendingPermission;
    private int notifyId = 1;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        server = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, null);
        alt = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_ALT, null);
        NotesJob.ensure(this);
        if (askConfigLink(getIntent())) return;
        if (server == null) showSetup(null);
        else openTitan(pathFor(getIntent()));
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (askConfigLink(intent)) return;
        if (isConfigure(intent) || server == null) { showSetup(null); return; }
        String path = pathFor(intent);
        if (web != null) load(server + path);
        else openTitan(path);
    }

    // --- endereço do servidor -------------------------------------------------------

    private static boolean isConfigure(Intent i) {
        Uri d = i == null ? null : i.getData();
        return d != null && "titan".equals(d.getScheme()) && "configurar".equals(d.getHost());
    }

    /**
     * Link da página de instalação (titan://configurar?s=…&alt=…): preenche os endereços,
     * mas SEMPRE pergunta antes (outro site não consegue trocar o servidor sem você ver).
     */
    private boolean askConfigLink(Intent i) {
        if (!isConfigure(i)) return false;
        Uri d = i.getData();
        String s = normalize(d.getQueryParameter("s"));
        if (s == null) return false;
        String a = normalize(d.getQueryParameter("alt"));
        if (a != null && a.equals(s)) a = null;
        final String fa = a;
        if (web == null) showSetup(null);
        new AlertDialog.Builder(this)
                .setTitle("Usar este TITAN?")
                .setMessage("Endereço principal:\n" + s + (fa != null ? "\n\nReserva (se o principal não responder):\n" + fa : "")
                        + "\n\nSó confirme se veio da página de instalação do SEU notebook.")
                .setPositiveButton("Usar", (dlg, w) -> {
                    server = s;
                    alt = fa;
                    triedAlt = false;
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_SERVER, s)
                            .putString(KEY_ALT, fa).apply();
                    if (web != null) { web.destroy(); web = null; }
                    openTitan("/");
                })
                .setNegativeButton("Cancelar", null)
                .show();
        return true;
    }

    /** Converte atalho / compartilhamento no caminho da interface do TITAN. */
    private String pathFor(Intent i) {
        if (i == null) return "/";
        if (isConfigure(i)) return "/";
        Uri d = i.getData();
        if (d != null && "titan".equals(d.getScheme()) && "acao".equals(d.getHost())) {
            String acao = d.getLastPathSegment();
            if ("voz".equals(acao) || "conversa".equals(acao) || "aula".equals(acao) || "aprovacoes".equals(acao)
                    || "inicio".equals(acao) || "memoria".equals(acao)) {
                return "/?acao=" + acao;
            }
        }
        // Aviso de mensagem do TITAN: abre direto a conversa que ele começou.
        if (d != null && "titan".equals(d.getScheme()) && "conversa".equals(d.getHost())) {
            String id = d.getLastPathSegment();
            if (id != null && id.matches("^[0-9a-f-]{36}$")) return "/?conversa=" + id;
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
        help.setText("Endereço do TITAN no seu notebook.\n\nNo notebook, rode \"titan ligar\": ele mostra os "
                + "endereços e um QR code. Na página do QR, instale o cadeado e toque em \"CONFIGURAR O APP SOZINHO\" "
                + "(ou digite aqui).");
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

        TextView altLabel = new TextView(this);
        altLabel.setText("Reserva (opcional): usado se o primeiro não responder. Ex.: Tailscale em cima, Wi-Fi de casa aqui.");
        altLabel.setTextColor(Color.parseColor("#86aebe"));
        altLabel.setTextSize(13);
        altLabel.setPadding(0, 32, 0, 8);
        box.addView(altLabel);
        EditText altInput = new EditText(this);
        altInput.setHint("https://100.x.x.x:8000");
        altInput.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        altInput.setTextColor(Color.WHITE);
        altInput.setHintTextColor(Color.parseColor("#4b6a78"));
        altInput.setSingleLine(true);
        if (alt != null) altInput.setText(alt);
        box.addView(altInput);

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
            String a = altInput.getText().toString().trim().isEmpty() ? null : normalize(altInput.getText().toString());
            if (a == null && !altInput.getText().toString().trim().isEmpty()) {
                showSetup("O endereço de reserva também precisa começar com https://."); return;
            }
            server = s;
            alt = s.equals(a) ? null : a;
            triedAlt = false;
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_SERVER, s).putString(KEY_ALT, alt).apply();
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
                if (!req.isForMainFrame()) return;
                errorSeen = true;
                runOnUiThread(() -> connectionFailed());
            }

            @Override
            public void onPageCommitVisible(WebView view, String url) {
                pageArrived(url);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                pageArrived(url);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> handleMediaPermission(request));
            }
        });

        android.widget.FrameLayout frame = new android.widget.FrameLayout(this);
        frame.setBackgroundColor(Color.parseColor("#03070c"));
        frame.addView(web);
        connecting = new TextView(this);
        connecting.setTextColor(Color.parseColor("#3ee8ff"));
        connecting.setTextSize(16);
        connecting.setGravity(Gravity.CENTER);
        connecting.setPadding(48, 48, 48, 48);
        frame.addView(connecting, new android.widget.FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(frame);
        load(server + path);
    }

    /** Carrega mostrando "Conectando…"; se nada chegar em 12 s, tenta a reserva ou avisa. */
    private void load(String url) {
        loaded = false;
        errorSeen = false;
        if (connecting != null) {
            connecting.setText("Conectando ao notebook…\n\n" + server
                    + "\n\nFora de casa, o Tailscale precisa estar ligado no celular.");
            connecting.setVisibility(android.view.View.VISIBLE);
        }
        ui.removeCallbacks(timeout);
        ui.postDelayed(timeout, CONNECT_TIMEOUT_MS);
        web.loadUrl(url);
    }

    private void pageArrived(String url) {
        // A página de erro do Android também "termina": só conta a do TITAN de verdade.
        if (errorSeen || url == null || !sameServer(Uri.parse(url))) return;
        loaded = true;
        triedAlt = false; // carregou: na próxima falha pode tentar o outro de novo
        ui.removeCallbacks(timeout);
        if (connecting != null) connecting.setVisibility(android.view.View.GONE);
    }

    private void connectionFailed() {
        ui.removeCallbacks(timeout);
        if (web == null || loaded) return;
        web.stopLoading();
        // Principal fora do alcance (ex.: Tailscale desligado em casa): tenta a reserva sozinho.
        if (alt != null && !triedAlt) {
            triedAlt = true;
            String other = alt;
            alt = server;
            server = other;
            load(server + "/");
            return;
        }
        if (connecting != null) connecting.setText("Sem resposta do notebook.");
        showOffline();
    }

    private void showOffline() {
        new AlertDialog.Builder(this)
                .setTitle("Notebook fora do alcance")
                .setMessage("Não consegui falar com o TITAN em " + server + (alt != null ? " nem em " + alt : "")
                        + ".\n\nConfira se o notebook está ligado com o TITAN aberto e, fora de casa, se o "
                        + "Tailscale está ligado no celular e no notebook.")
                .setPositiveButton("Tentar de novo", (d, w) -> { triedAlt = false; if (web != null) load(server + "/"); })
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
        ui.removeCallbacks(timeout);
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

        /** Aviso do sistema (aprovação pendente, resposta pronta, mensagem do TITAN). */
        @JavascriptInterface
        public void notify(String title, String body, String path) {
            String safe = path != null && path.startsWith("/") ? path : "/";
            String target = "titan://acao/inicio";
            if (safe.contains("aprovacoes")) target = "titan://acao/aprovacoes";
            int at = safe.indexOf("conversa=");
            if (at >= 0) {
                String id = safe.substring(at + 9).split("&")[0];
                if (id.matches("^[0-9a-f-]{36}$")) target = "titan://conversa/" + id;
            }
            Notifier.show(MainActivity.this, notifyId++, title, body, target, false);
        }

        /** Lembretes com hora: agendados no próprio celular (tocam mesmo sem o notebook). */
        @JavascriptInterface
        public void scheduleReminders(String json) {
            Reminders.schedule(MainActivity.this, json == null ? "[]" : json);
        }
    }

}
