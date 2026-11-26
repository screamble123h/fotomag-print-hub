package ru.fotomag.wificonnect;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.net.wifi.WifiNetworkSuggestion;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.ArrayList;

/**
 * One-purpose, no-permissions FotoMag AGFA network provisioning.
 * No Internet, location, contact, storage or background network access.
 * Android must ask the user to approve saving the Wi-Fi network.
 */
public final class MainActivity extends Activity {
    private static final String SSID = "AGFA";
    private static final String PASSWORD = "00001111";
    private static final int ADD_AGFA = 114;
    private static final int DARK = Color.rgb(21, 21, 21);
    private static final int YELLOW = Color.rgb(255, 212, 62);
    private TextView message;
    private boolean showingSystemPrompt;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(DARK);
        getWindow().setNavigationBarColor(DARK);
        showUserInterface();
        if (savedInstanceState == null && isSiteConnectIntent(getIntent())) {
            getWindow().getDecorView().post(this::requestSystemWifiApproval);
        }
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (isSiteConnectIntent(intent)) {
            getWindow().getDecorView().post(this::requestSystemWifiApproval);
        }
    }

    private boolean isSiteConnectIntent(Intent intent) {
        if (intent == null || !Intent.ACTION_VIEW.equals(intent.getAction())) return false;
        Uri data = intent.getData();
        return data != null && "fotomagwifi".equals(data.getScheme()) &&
                "connect".equals(data.getHost());
    }

    private int dp(int n) {
        return (int) (getResources().getDisplayMetrics().density * n + .5f);
    }

    private TextView label(String text, int sp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(color);
        view.setTextSize(sp);
        view.setTypeface(Typeface.DEFAULT, bold ? Typeface.BOLD : Typeface.NORMAL);
        view.setGravity(Gravity.CENTER);
        return view;
    }

    private void showUserInterface() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(DARK);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER);
        col.setPadding(dp(25), dp(40), dp(25), dp(40));
        col.addView(label("FotoMag", 37, YELLOW, true));
        TextView heading = label("Бесплатный Wi-Fi", 25, Color.WHITE, true);
        LinearLayout.LayoutParams headParams = new LinearLayout.LayoutParams(-1,-2);
        headParams.topMargin = dp(19);
        col.addView(heading, headParams);
        TextView intro = label("Сеть AGFA. Пароль вводить не нужно. Android попросит подтвердить её сохранение.", 16,
                Color.rgb(228,222,205), false);
        LinearLayout.LayoutParams introParams = new LinearLayout.LayoutParams(-1,-2);
        introParams.topMargin = dp(15);
        col.addView(intro,introParams);

        Button button = new Button(this);
        button.setAllCaps(false);
        button.setText("Подключиться");
        button.setTextColor(DARK);
        button.setTextSize(18);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        GradientDrawable background = new GradientDrawable();
        background.setColor(YELLOW);
        background.setCornerRadius(dp(18));
        button.setBackground(background);
        LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(-1,dp(60));
        buttonParams.topMargin=dp(27);
        col.addView(button,buttonParams);
        button.setOnClickListener(v -> requestSystemWifiApproval());

        message = label("Приложение не запрашивает разрешений на файлы, контакты или местоположение.",
                14, Color.rgb(209,206,195), false);
        LinearLayout.LayoutParams msgParams = new LinearLayout.LayoutParams(-1,-2);
        msgParams.topMargin = dp(20);
        col.addView(message,msgParams);
        scroll.addView(col);
        setContentView(scroll);
    }

    private void requestSystemWifiApproval() {
        if (showingSystemPrompt) return;
        if (Build.VERSION.SDK_INT < 30) {
            message.setText("Требуется Android 11 или новее.");
            return;
        }
        try {
            WifiNetworkSuggestion suggestion = new WifiNetworkSuggestion.Builder()
                    .setSsid(SSID)
                    .setWpa2Passphrase(PASSWORD)
                    .build();
            ArrayList<WifiNetworkSuggestion> networks = new ArrayList<>();
            networks.add(suggestion);
            Intent add = new Intent(Settings.ACTION_WIFI_ADD_NETWORKS);
            add.putParcelableArrayListExtra(Settings.EXTRA_WIFI_NETWORK_LIST, networks);
            if (add.resolveActivity(getPackageManager()) == null) {
                message.setText("На этом телефоне системное добавление Wi-Fi недоступно.");
                return;
            }
            showingSystemPrompt = true;
            message.setText("Подтвердите AGFA в системном окне Android.");
            startActivityForResult(add, ADD_AGFA);
        } catch (IllegalArgumentException | ActivityNotFoundException | SecurityException ex) {
            showingSystemPrompt = false;
            message.setText("Не удалось открыть добавление AGFA на этом телефоне.");
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode,resultCode,data);
        if (requestCode != ADD_AGFA) return;
        showingSystemPrompt = false;
        if (resultCode == RESULT_OK) {
            message.setText("AGFA сохранена. Android сможет подключаться автоматически, когда сеть доступна. Ручной ввод пароля не требуется.");
        } else {
            message.setText("Добавление отменено. Нажмите «Подключиться», чтобы попробовать снова.");
        }
    }
}
