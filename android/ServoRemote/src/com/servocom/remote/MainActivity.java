package com.servocom.remote;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.SharedPreferences;
import android.content.pm.ActivityInfo;
import android.content.res.Configuration;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.UUID;

/**
 * Servo Remote: four buttons for the Servo Commander panel over Bluetooth LE.
 *
 * The panel does the work: this only says which button was pressed (see
 * phone_remote.py on the panel for the protocol).  JOG is hold-to-run: while
 * it is held the app repeats "held" every 150 ms and the panel stops the jog
 * by itself half a second after the last one, so a dropped link stops it.
 */
public class MainActivity extends Activity {
    private static final String TAG = "ServoRemote";
    private static final UUID SERVICE = UUID.fromString("5e7a1001-8d2c-4b1e-9c3a-2f6d0a1b3c4d");
    private static final UUID CMD = UUID.fromString("5e7a1002-8d2c-4b1e-9c3a-2f6d0a1b3c4d");
    private static final UUID STATE = UUID.fromString("5e7a1003-8d2c-4b1e-9c3a-2f6d0a1b3c4d");
    private static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    // state flags from the panel
    private static final int F_PAIRED = 1, F_ENABLED = 2, F_REV = 4, F_JOG = 8, F_ONLINE = 16,
            F_JOG_OK = 32, F_LEVER = 64, F_REFUSED = 128;

    private static final int JOG_REPEAT_MS = 150;
    private static final int STATE_TIMEOUT_MS = 3000;     // the panel sends state every second
    private static final int CONNECT_TIMEOUT_MS = 12000;  // a connection attempt that never finishes

    // the panel's own colours (ui.kv): ACCENT, PANEL, the EN-off fill, BTN_GRAY
    private static final int ACCENT = Color.rgb(0, 128, 255), PANEL = Color.rgb(41, 41, 41),
            EN_OFF = Color.rgb(27, 27, 27), PRESSED = Color.rgb(80, 80, 80), DIM = Color.rgb(80, 80, 80),
            STATUS = Color.rgb(160, 160, 160), BG = Color.BLACK, RED = Color.rgb(240, 64, 51);

    private final Handler ui = new Handler(Looper.getMainLooper());
    private BluetoothAdapter adapter;
    private BluetoothLeScanner scanner;
    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic cmdChr;
    private boolean scanning, linked, jogHeld;
    private int flags = -1;
    private long lastState;
    private long connectStarted;
    private byte[] phoneId;

    /** One queued write: the bytes, and whether it goes without a response. */
    private static final class Pending {
        final byte[] data;
        final boolean noResponse;

        Pending(byte[] data, boolean noResponse) {
            this.data = data;
            this.noResponse = noResponse;
        }
    }

    private final ArrayDeque<Pending> queue = new ArrayDeque<>();
    private boolean writing;

    private TextView status, dir, en, jog, plus, minus;
    private int step;                       // the panel's +/- step: from its state, remembered
    private final int[] presetVals = new int[6];   // the panel's presets 1-6: from its state, remembered
    private int top;                        // the largest speed the panel accepts
    private final TextView[] presets = new TextView[6];
    private TextView custom;
    private final TextView[] tools = new TextView[4];   // DRILL, TAP, CSFM, SFM: open on the panel
    private boolean keypadOpen;
    private String entry = "";
    private TextView entryView, entryHint, setKey;
    private Typeface font, icons;
    private boolean settingsOpen;
    private TextView setPanel, setSignal, setDrive, setPairing;
    private int rssi;                       // signal to the panel, dBm (0 = not read yet)
    private String panelName = "";          // from the panel's advertisement

    // ------------------------------------------------------------------ UI
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        phoneId = loadPhoneId();
        try {
            font = Typeface.createFromAsset(getAssets(), "Orbitron-Medium.ttf");   // the panel's font
        } catch (RuntimeException e) {
            font = Typeface.DEFAULT_BOLD;
        }
        try {
            icons = Typeface.createFromAsset(getAssets(), "fa-solid-900.ttf");    // the panel's icons
        } catch (RuntimeException e) {
            icons = Typeface.DEFAULT;
        }
        applyOrientation();
        step = prefs().getInt("step", 0);         // the last step the panel sent, shown while away
        String savedPresets = prefs().getString("presets", "");
        String[] parts = savedPresets.split(",");
        for (int i = 0; i < 6 && parts.length == 6; i++) presetVals[i] = Integer.parseInt(parts[i]);
        top = prefs().getInt("top", 0);
        BluetoothManager bm = (BluetoothManager) getSystemService(BLUETOOTH_SERVICE);
        adapter = bm == null ? null : bm.getAdapter();
        buildUi();
        ui.postDelayed(watchdog, 1000);
    }

    /** Turning the phone rebuilds the screen only: the Bluetooth link stays up. */
    @Override
    public void onConfigurationChanged(Configuration c) {
        super.onConfigurationChanged(c);
        jogRelease();
        if (settingsOpen) showSettings();
        else if (keypadOpen) {
            String keep = entry;
            showKeypad();
            entry = keep;
            render();
        } else buildUi();
    }

    /** The panel's title bar: name on the left, an icon button on the right. */
    private LinearLayout titleBar(String title, String icon, View.OnClickListener onIcon) {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackground(fill(PANEL));
        bar.setPadding(dp(14), 0, dp(4), 0);
        TextView t = new TextView(this);
        t.setText(title);
        t.setTypeface(font);
        t.setTextColor(Color.WHITE);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        bar.addView(t, new LinearLayout.LayoutParams(0, -2, 1f));
        TextView b = new TextView(this);
        b.setText(icon);
        b.setTypeface(icons);
        b.setTextColor(Color.rgb(200, 200, 200));
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 24);
        b.setGravity(Gravity.CENTER);
        b.setClickable(true);
        b.setOnClickListener(onIcon);
        bar.addView(b, new LinearLayout.LayoutParams(dp(52), -1));
        return bar;
    }

    /** Portrait: FWD / EN / JOG across the top, + / - full width under them,
     *  the presets 2 x 3, then CUSTOM, DRILL, TAP, CSFM, SFM down the screen.
     *  Landscape: all five in one row across the top, the same size, presets
     *  1 x 6, then CUSTOM and the four tools in one row.  The status line
     *  along the bottom; the space between is left free. */
    private void buildUi() {
        boolean land = getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        int gap = dp(8), pad = dp(12);
        LinearLayout plusMinusRow = null;
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setPadding(pad, dp(8), pad, pad);
        LinearLayout.LayoutParams tb = new LinearLayout.LayoutParams(-1, dp(48));
        tb.bottomMargin = gap;
        root.addView(titleBar("Servo Remote", "\uf013", v -> showSettings()), tb);

        // portrait: FWD / EN / JOG in a row of squares, + / - full width under
        // them.  landscape: all five in one row, the same size.
        android.util.DisplayMetrics dm = getResources().getDisplayMetrics();
        int across = land ? 5 : 3;
        int cell = (dm.widthPixels - 2 * pad - (across - 1) * gap) / across;
        int height = land ? Math.min(cell, (int) (dm.heightPixels * 0.30)) : cell;

        dir = button("FWD");
        en = button("EN");
        jog = button("JOG");
        plus = button("+");
        minus = button("-");
        TextView[] top = land ? new TextView[]{dir, en, jog, plus, minus} : new TextView[]{dir, en, jog};
        root.addView(rowOf(top, gap), new LinearLayout.LayoutParams(-1, height));
        if (!land) {
            plusMinusRow = rowOf(new TextView[]{plus, minus}, gap);
            root.addView(plusMinusRow);
        }

        // the panel's speed presets 1-6, and CUSTOM under them
        for (int i = 0; i < 6; i++) {
            presets[i] = button("-");
            presets[i].setTextSize(TypedValue.COMPLEX_UNIT_SP, 24);
        }
        custom = button("CUSTOM");
        custom.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        String[] toolNames = {"DRILL", "TAP", "CSFM", "SFM"};
        for (int i = 0; i < 4; i++) {
            tools[i] = button(toolNames[i]);
            tools[i].setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        }
        int presetH = (int) (height * 0.6);
        if (!land) {
            // eight rows under FWD / EN / JOG (+/-, presets x2, CUSTOM, four
            // tools), all one height: shrunk to fit the screen if they must
            int sb = getResources().getIdentifier("status_bar_height", "dimen", "android");
            int avail = dm.heightPixels - (sb > 0 ? getResources().getDimensionPixelSize(sb) : dp(24))
                    - dp(8) - dp(48) - gap - height - pad - dp(32);
            presetH = Math.min(presetH, avail / 8 - gap);
        }
        if (land) {
            root.addView(rowOf(presets, gap), spaced(presetH, gap));
        } else {
            root.addView(rowOf(new TextView[]{presets[0], presets[1], presets[2]}, gap), spaced(presetH, gap));
            root.addView(rowOf(new TextView[]{presets[3], presets[4], presets[5]}, gap), spaced(presetH, gap));
        }
        if (land) {
            // CUSTOM shrinks to the left, the tools beside it, all the same size
            root.addView(rowOf(new TextView[]{custom, tools[0], tools[1], tools[2], tools[3]}, gap),
                    spaced((int) (height * 0.45), gap));
        } else {
            plusMinusRow.setLayoutParams(spaced(presetH, gap));
            root.addView(custom, spaced(presetH, gap));
            for (TextView t : tools) root.addView(t, spaced(presetH, gap));
        }

        root.addView(new View(this), new LinearLayout.LayoutParams(-1, 0, 1f));   // free space
        settingsOpen = false;

        status = new TextView(this);                    // always along the bottom
        status.setTypeface(font);
        status.setTextColor(STATUS);
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        status.setPadding(dp(4), dp(6), dp(4), 0);
        root.addView(status, new LinearLayout.LayoutParams(-1, -2));
        setContentView(root);

        dir.setOnClickListener(v -> press(v, new byte[]{'D', (byte) (has(F_REV) ? 'F' : 'R')}));
        en.setOnClickListener(v -> press(v, new byte[]{'E', (byte) (has(F_ENABLED) ? 0 : 1)}));
        jog.setOnTouchListener(this::jogTouch);
        plus.setOnClickListener(v -> press(v, new byte[]{'+'}));
        minus.setOnClickListener(v -> press(v, new byte[]{'-'}));
        for (int i = 0; i < 6; i++) {
            final byte pos = (byte) (i + 1);
            presets[i].setOnClickListener(v -> press(v, new byte[]{'P', pos}));
        }
        custom.setOnClickListener(v -> {
            if (usable()) showKeypad();
        });
        for (int i = 0; i < 4; i++) {
            final byte id = (byte) (i + 1);
            tools[i].setOnClickListener(v -> press(v, new byte[]{'T', id}));
        }
        keypadOpen = false;
        render();
    }

    private LinearLayout.LayoutParams spaced(int height, int gap) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, height);
        p.topMargin = gap;
        return p;
    }

    // ------------------------------------------------------------------ custom speed
    /** The panel's CUSTOM numpad: type a speed, SET sends it. */
    private void showKeypad() {
        jogRelease();
        keypadOpen = true;
        entry = "";
        boolean land = getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        int gap = dp(8);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setPadding(dp(12), dp(8), dp(12), dp(12));
        LinearLayout.LayoutParams tb = new LinearLayout.LayoutParams(-1, dp(48));
        tb.bottomMargin = gap;
        root.addView(titleBar("Custom speed", "\uf057", v -> buildUi()), tb);

        entryView = new TextView(this);
        entryView.setTypeface(font);
        entryView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 48);
        entryView.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        entryView.setPadding(dp(16), 0, dp(16), 0);
        entryView.setBackground(fill(Color.rgb(20, 20, 20)));
        entryHint = new TextView(this);
        entryHint.setTypeface(font);
        entryHint.setTextColor(STATUS);
        entryHint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        entryHint.setPadding(dp(4), dp(6), dp(4), dp(6));
        setKey = button("SET");
        setKey.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        setKey.setOnClickListener(v -> keypadSet());

        String[] keys = {"7", "8", "9", "4", "5", "6", "1", "2", "3", "C", "0", "\uf55a"};
        LinearLayout pad = new LinearLayout(this);
        pad.setOrientation(LinearLayout.VERTICAL);
        for (int r = 0; r < 4; r++) {
            TextView[] row = new TextView[3];
            for (int c = 0; c < 3; c++) {
                final String k = keys[r * 3 + c];
                TextView b = button(k);
                b.setTypeface(k.equals("\uf55a") ? icons : font);
                b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 28);
                b.setBackground(fills(PANEL, ACCENT));
                b.setOnClickListener(v -> keypadKey(k));
                row[c] = b;
            }
            LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(-1, 0, 1f);
            if (r > 0) rp.topMargin = gap;
            pad.addView(rowOf(row, gap), rp);
        }

        if (land) {
            LinearLayout body = new LinearLayout(this);
            body.setOrientation(LinearLayout.HORIZONTAL);
            LinearLayout left = new LinearLayout(this);
            left.setOrientation(LinearLayout.VERTICAL);
            left.addView(entryView, new LinearLayout.LayoutParams(-1, dp(80)));
            left.addView(entryHint, new LinearLayout.LayoutParams(-1, -2));
            left.addView(new View(this), new LinearLayout.LayoutParams(-1, 0, 1f));
            left.addView(setKey, new LinearLayout.LayoutParams(-1, dp(64)));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, -1, 1f);
            lp.setMarginEnd(gap);
            body.addView(left, lp);
            body.addView(pad, new LinearLayout.LayoutParams(0, -1, 1f));
            root.addView(body, new LinearLayout.LayoutParams(-1, 0, 1f));
        } else {
            root.addView(entryView, new LinearLayout.LayoutParams(-1, dp(88)));
            root.addView(entryHint, new LinearLayout.LayoutParams(-1, -2));
            root.addView(pad, new LinearLayout.LayoutParams(-1, 0, 1f));
            root.addView(setKey, spaced(dp(72), gap));
        }
        setContentView(root);
        render();
    }

    private void keypadKey(String k) {
        if (k.equals("C")) {
            entry = "";
        } else if (k.equals("\uf55a")) {
            if (!entry.isEmpty()) entry = entry.substring(0, entry.length() - 1);
        } else if (entry.length() < 5) {
            entry = entry.equals("0") ? k : entry + k;
        }
        render();
    }

    private boolean keypadOver() {
        return !entry.isEmpty() && top > 0 && Integer.parseInt(entry) > top;
    }

    private void keypadSet() {
        if (entry.isEmpty() || keypadOver() || !usable()) return;
        int v = Integer.parseInt(entry);
        send(new byte[]{'C', (byte) (v & 0xFF), (byte) ((v >> 8) & 0xFF)}, true);
        buildUi();
    }

    private void renderKeypad() {
        if (entryView == null) return;
        boolean over = keypadOver();
        entryView.setText((entry.isEmpty() ? "0" : entry) + " rpm");
        entryView.setTextColor(over ? RED : entry.isEmpty() ? DIM : Color.WHITE);
        entryHint.setText(top > 0 ? "0 to " + top + " rpm, the panel's limit" : "Spindle rpm");
        boolean ok = usable() && !entry.isEmpty() && !over;
        setKey.setBackground(fills(PANEL, ACCENT));
        setKey.setTextColor(ok ? Color.rgb(102, 217, 128) : DIM);
        setKey.setEnabled(ok);
    }

    /** Buttons side by side, equal widths, a gap between. */
    private LinearLayout rowOf(TextView[] buttons, int gap) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        for (int i = 0; i < buttons.length; i++) {
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, -1, 1f);
            if (i < buttons.length - 1) p.setMarginEnd(gap);
            row.addView(buttons[i], p);
        }
        return row;
    }

    // ------------------------------------------------------------------ settings
    private SharedPreferences prefs() {
        return getSharedPreferences("remote", MODE_PRIVATE);
    }

    private void applyOrientation() {
        String o = prefs().getString("orientation", "auto");
        setRequestedOrientation("portrait".equals(o) ? ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT
                : "landscape".equals(o) ? ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                : ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR);
    }

    /** Settings, styled like the panel's settings cards. */
    private void showSettings() {
        jogRelease();
        settingsOpen = true;
        keypadOpen = false;
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setPadding(dp(12), dp(8), dp(12), dp(12));
        LinearLayout.LayoutParams tb = new LinearLayout.LayoutParams(-1, dp(48));
        tb.bottomMargin = dp(8);
        root.addView(titleBar("Settings", "\uf057", v -> buildUi()), tb);

        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);

        // orientation
        LinearLayout c1 = card(list, "Orientation", "How the phone is mounted");
        String o = prefs().getString("orientation", "auto");
        LinearLayout seg = new LinearLayout(this);
        String[][] opts = {{"auto", "AUTO"}, {"portrait", "PORTRAIT"}, {"landscape", "LANDSCAPE"}};
        for (int i = 0; i < opts.length; i++) {
            final String key = opts[i][0];
            TextView b = segment(opts[i][1], key.equals(o));
            b.setOnClickListener(v -> {
                prefs().edit().putString("orientation", key).apply();
                applyOrientation();
                showSettings();
            });
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, dp(52), 1f);
            if (i < opts.length - 1) p.setMarginEnd(dp(4));
            seg.addView(b, p);
        }
        c1.addView(seg, new LinearLayout.LayoutParams(-1, -2));

        // pairing
        LinearLayout c2 = card(list, "Pairing", null);
        setPairing = hint(c2);
        TextView forget = segment("FORGET AND RE-PAIR", false);
        forget.setTextColor(RED);
        forget.setOnClickListener(v -> new AlertDialog.Builder(this)
                .setTitle("Forget the panel?")
                .setMessage("The phone gets a new identity. Press PAIR on the panel "
                        + "(Settings, Connection, Phone remote) to pair it again.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Forget", (d, w) -> forgetPanel())
                .show());
        c2.addView(forget, new LinearLayout.LayoutParams(-1, dp(52)));

        // connection details
        LinearLayout c3 = card(list, "Connection", null);
        setPanel = hint(c3);
        setSignal = hint(c3);
        setDrive = hint(c3);
        TextView ver = hint(c3);
        ver.setText("Servo Remote " + appVersion());

        ScrollView sv = new ScrollView(this);
        sv.addView(list);
        root.addView(sv, new LinearLayout.LayoutParams(-1, 0, 1f));
        setContentView(root);
        render();
    }

    private LinearLayout card(LinearLayout parent, String label, String hint) {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setBackground(fill(Color.rgb(20, 20, 20)));
        c.setPadding(dp(12), dp(8), dp(12), dp(12));
        TextView t = new TextView(this);
        t.setText(label);
        t.setTypeface(font);
        t.setTextColor(Color.WHITE);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        c.addView(t);
        if (hint != null) hint(c).setText(hint);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2);
        p.bottomMargin = dp(8);
        parent.addView(c, p);
        return c;
    }

    private TextView hint(LinearLayout parent) {
        TextView h = new TextView(this);
        h.setTypeface(font);
        h.setTextColor(STATUS);
        h.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        h.setPadding(0, dp(2), 0, dp(8));
        parent.addView(h);
        return h;
    }

    /** The panel's segment button: blue when it is the current choice. */
    private TextView segment(String text, boolean active) {
        TextView b = new TextView(this);
        b.setText(text);
        b.setTypeface(font);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        b.setGravity(Gravity.CENTER);
        b.setTextColor(active ? Color.WHITE : Color.rgb(180, 180, 180));
        b.setBackground(fills(active ? ACCENT : PANEL, PRESSED));
        b.setClickable(true);
        return b;
    }

    private String appVersion() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "?";
        }
    }

    /** A new identity: the panel no longer knows this phone until PAIR. */
    private void forgetPanel() {
        prefs().edit().remove("id").remove("panel").apply();
        phoneId = loadPhoneId();
        dropLink();
        showSettings();
    }

    private void renderSettings() {
        if (setPanel == null) return;
        String panel = prefs().getString("panel", "");
        setPairing.setText(has(F_PAIRED) ? "Paired with " + (panelName.isEmpty() ? "the panel" : panelName)
                + (panel.isEmpty() ? "" : " (" + panel + ")")
                : has(F_REFUSED) ? "Not paired: press PAIR on the panel"
                : panel.isEmpty() ? "Not paired yet" : "Last paired with " + panel);
        String addr = "";
        try {
            if (gatt != null) addr = gatt.getDevice().getAddress();
        } catch (SecurityException ignored) {
        }
        setPanel.setText(linked ? "Panel: " + (panelName.isEmpty() ? "connected" : panelName) + "  " + addr
                : scanning ? "Panel: looking for it..." : "Panel: not connected");
        String q = rssi == 0 ? "" : rssi > -70 ? "good" : rssi > -85 ? "fair" : "weak";
        setSignal.setText(linked && rssi != 0 ? "Signal: " + rssi + " dBm, " + q : "Signal: -");
        setDrive.setText(!usable() ? "Drive: -" : "Drive: " + (has(F_ONLINE) ? "online" : "OFFLINE")
                + (has(F_ENABLED) ? ", enabled" : ", disabled")
                + (has(F_LEVER) ? ", lever not OFF" : ", lever OFF"));
    }

    private TextView button(String text) {
        TextView b = new TextView(this);
        b.setText(text);
        b.setGravity(Gravity.CENTER);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 30);
        b.setTypeface(font);
        b.setTextColor(Color.WHITE);
        b.setClickable(true);
        b.setHapticFeedbackEnabled(true);
        return b;
    }

    private GradientDrawable fill(int color) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(10));
        return d;
    }

    /** A fill, and the panel's grey while the finger is on it. */
    private StateListDrawable fills(int normal, int pressed) {
        StateListDrawable s = new StateListDrawable();
        s.addState(new int[]{android.R.attr.state_pressed}, fill(pressed));
        s.addState(new int[]{}, fill(normal));
        return s;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private boolean has(int f) {
        return flags >= 0 && (flags & f) != 0;
    }

    private boolean usable() {
        return linked && has(F_PAIRED) && has(F_ONLINE) && System.currentTimeMillis() - lastState < STATE_TIMEOUT_MS;
    }

    /** Buttons and status line from the panel's last state, styled like the
     *  panel: the direction button is blue and names the direction, EN is
     *  dark until the drive is enabled, then blue, JOG is blue while held. */
    private void render() {
        if (settingsOpen) {
            renderSettings();
            return;
        }
        if (keypadOpen) {
            renderKeypad();
            return;
        }
        boolean ok = usable();
        String s;
        if (adapter == null || !adapter.isEnabled()) {
            s = "Bluetooth is off";
        } else if (!linked) {
            s = scanning ? "Looking for the panel..." : "Not connected";
        } else if (flags < 0 || System.currentTimeMillis() - lastState >= STATE_TIMEOUT_MS) {
            s = "Connected, waiting for the panel...";
        } else if (has(F_REFUSED) && !has(F_PAIRED)) {
            s = "Not paired: press PAIR on the panel (Settings, Connection, Phone remote)";
        } else if (!has(F_ONLINE)) {
            s = "Panel connected, drive OFFLINE";
        } else if (has(F_LEVER)) {
            s = "Connected  -  lever is not OFF";
        } else {
            s = "Connected";
        }
        status.setText(s);

        dir.setText(has(F_REV) ? "REV" : "FWD");
        dir.setBackground(fills(ok ? ACCENT : PANEL, PRESSED));
        dir.setTextColor(ok ? Color.WHITE : DIM);
        dir.setEnabled(ok);

        boolean on = has(F_ENABLED);
        en.setBackground(fills(ok && on ? ACCENT : EN_OFF, PRESSED));
        en.setTextColor(ok ? Color.WHITE : DIM);
        en.setEnabled(ok);

        // the panel's step buttons: grey, blue while pressed, labelled with its step
        plus.setText(step > 0 ? "+" + step : "+");
        minus.setText(step > 0 ? "-" + step : "-");
        for (TextView b : new TextView[]{plus, minus}) {
            b.setBackground(fills(ok ? PRESSED : PANEL, ACCENT));
            b.setTextColor(ok ? Color.WHITE : DIM);
            b.setEnabled(ok);
        }

        // presets: the panel's values, its preset look (blue while pressed)
        for (int i = 0; i < 6; i++) {
            presets[i].setText(presetVals[i] > 0 ? String.valueOf(presetVals[i]) : "-");
            presets[i].setBackground(fills(PANEL, ACCENT));
            presets[i].setTextColor(ok && presetVals[i] > 0 ? Color.WHITE : DIM);
            presets[i].setEnabled(ok && presetVals[i] > 0);
        }
        for (TextView b : new TextView[]{custom, tools[0], tools[1], tools[2], tools[3]}) {
            b.setBackground(fills(PANEL, ACCENT));
            b.setTextColor(ok ? Color.WHITE : DIM);
            b.setEnabled(ok);
        }

        boolean canJog = ok && (has(F_JOG_OK) || has(F_JOG) || jogHeld);
        jog.setBackground(fill(canJog && (jogHeld || has(F_JOG)) ? ACCENT : PANEL));
        jog.setTextColor(canJog ? Color.WHITE : DIM);
        jog.setEnabled(canJog);
    }

    private void press(View v, byte[] cmd) {
        if (!usable()) return;
        v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
        send(cmd, true);
    }

    // ------------------------------------------------------------------ jog
    private final Runnable jogRepeat = new Runnable() {
        @Override
        public void run() {
            if (!jogHeld) return;
            send(new byte[]{'J'}, false);
            ui.postDelayed(this, JOG_REPEAT_MS);
        }
    };

    private boolean jogTouch(View v, MotionEvent e) {
        switch (e.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (!usable() || !(has(F_JOG_OK) || has(F_JOG))) return true;
                v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                jogHeld = true;
                jogRepeat.run();
                render();
                return true;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                jogRelease();
                return true;
            default:
                return true;
        }
    }

    private void jogRelease() {
        if (!jogHeld) return;
        jogHeld = false;
        ui.removeCallbacks(jogRepeat);
        send(new byte[]{'j'}, true);
        render();
    }

    // ------------------------------------------------------------------ lifecycle
    /** Back closes Settings or the keypad; on the main buttons it does nothing,
     *  so a stray press never closes the remote. */
    @Override
    public void onBackPressed() {
        if (settingsOpen || keypadOpen) buildUi();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (needPermissions()) {
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT}, 1);
        } else {
            startScan();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        jogRelease();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (!needPermissions()) startScan();
        else status.setText("Servo Remote needs the Nearby devices permission");
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        ui.removeCallbacksAndMessages(null);
        stopScan();
        try {
            if (gatt != null) gatt.close();
        } catch (SecurityException ignored) {
        }
    }

    private boolean needPermissions() {
        return checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED;
    }

    /** Re-renders, and drops a link the panel stopped talking on. */
    private final Runnable watchdog = new Runnable() {
        @Override
        public void run() {
            long now = System.currentTimeMillis();
            if (linked && flags >= 0 && now - lastState > 3 * STATE_TIMEOUT_MS) {
                Log.i(TAG, "no state from the panel: reconnecting");
                dropLink();
            } else if (!linked && gatt != null && now - connectStarted > CONNECT_TIMEOUT_MS) {
                Log.i(TAG, "connection attempt timed out: retrying");
                dropLink();
            }
            if (!linked && !scanning && gatt == null && !needPermissions()) startScan();
            if (settingsOpen && linked && gatt != null) {
                try {
                    gatt.readRemoteRssi();
                } catch (SecurityException ignored) {
                }
            }
            render();
            ui.postDelayed(this, 1000);
        }
    };

    // ------------------------------------------------------------------ Bluetooth
    private void startScan() {
        // never scan while a connection is being made: Android drops the attempt (status 133)
        if (adapter == null || !adapter.isEnabled() || linked || scanning || gatt != null) {
            render();
            return;
        }
        try {
            scanner = adapter.getBluetoothLeScanner();
            if (scanner == null) return;
            ScanFilter f = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(SERVICE)).build();
            ScanSettings st = new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build();
            scanner.startScan(Collections.singletonList(f), st, scanCb);
            scanning = true;
            Log.i(TAG, "scanning");
        } catch (SecurityException e) {
            Log.w(TAG, "scan refused", e);
        }
        render();
    }

    private void stopScan() {
        if (!scanning || scanner == null) return;
        try {
            scanner.stopScan(scanCb);
        } catch (SecurityException | IllegalStateException ignored) {
        }
        scanning = false;
    }

    private final ScanCallback scanCb = new ScanCallback() {
        @Override
        public void onScanResult(int type, ScanResult r) {
            if (linked || gatt != null) return;
            stopScan();
            BluetoothDevice d = r.getDevice();
            Log.i(TAG, "found the panel " + d.getAddress());
            if (r.getScanRecord() != null && r.getScanRecord().getDeviceName() != null) {
                panelName = r.getScanRecord().getDeviceName();
            }
            rssi = r.getRssi();
            try {
                connectStarted = System.currentTimeMillis();
                gatt = d.connectGatt(MainActivity.this, false, gattCb, BluetoothDevice.TRANSPORT_LE);
            } catch (SecurityException e) {
                Log.w(TAG, "connect refused", e);
            }
            ui.post(MainActivity.this::render);
        }

        @Override
        public void onScanFailed(int code) {
            Log.w(TAG, "scan failed " + code);
            scanning = false;
        }
    };

    private void dropLink() {
        linked = false;
        flags = -1;
        cmdChr = null;
        synchronized (queue) {
            queue.clear();
            writing = false;
        }
        try {
            if (gatt != null) {
                gatt.disconnect();
                gatt.close();
            }
        } catch (SecurityException ignored) {
        }
        gatt = null;
        jogHeld = false;
        ui.removeCallbacks(jogRepeat);
    }

    private final BluetoothGattCallback gattCb = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt g, int st, int newState) {
            try {
                if (newState == BluetoothProfile.STATE_CONNECTED) {
                    Log.i(TAG, "connected");
                    g.discoverServices();
                } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                    Log.i(TAG, "disconnected " + st);
                    ui.post(() -> {
                        if (gatt == g) dropLink();
                        render();
                    });
                }
            } catch (SecurityException ignored) {
            }
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int st) {
            BluetoothGattService s = g.getService(SERVICE);
            if (s == null) {
                Log.w(TAG, "no remote service on that device");
                ui.post(() -> {
                    dropLink();
                    render();
                });
                return;
            }
            cmdChr = s.getCharacteristic(CMD);
            try {
                g.requestMtu(64);
            } catch (SecurityException ignored) {
            }
        }

        @Override
        public void onMtuChanged(BluetoothGatt g, int mtu, int st) {
            BluetoothGattService s = g.getService(SERVICE);
            BluetoothGattCharacteristic state = s == null ? null : s.getCharacteristic(STATE);
            if (state == null) return;
            try {
                g.setCharacteristicNotification(state, true);
                BluetoothGattDescriptor d = state.getDescriptor(CCCD);
                d.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                g.writeDescriptor(d);
            } catch (SecurityException ignored) {
            }
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int st) {
            linked = true;
            send(hello(), true);
            ui.post(MainActivity.this::render);
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
            byte[] v = c.getValue();
            if (v == null || v.length < 1) return;
            final int f = v[0] & 0xFF;
            final int st2 = v.length >= 6 ? (v[4] & 0xFF) | ((v[5] & 0xFF) << 8) : 0;
            final int[] pv = new int[7];
            final boolean hasPresets = v.length >= 20;
            for (int i = 0; hasPresets && i < 7; i++) pv[i] = (v[6 + 2 * i] & 0xFF) | ((v[7 + 2 * i] & 0xFF) << 8);
            ui.post(() -> {
                flags = f;
                if (st2 > 0 && st2 != step) {
                    step = st2;
                    prefs().edit().putInt("step", step).apply();
                }
                if (hasPresets) {
                    boolean changed = pv[6] != top;
                    for (int i = 0; i < 6; i++) changed |= pv[i] != presetVals[i];
                    if (changed) {
                        StringBuilder sb = new StringBuilder();
                        for (int i = 0; i < 6; i++) {
                            presetVals[i] = pv[i];
                            sb.append(i > 0 ? "," : "").append(pv[i]);
                        }
                        top = pv[6];
                        prefs().edit().putString("presets", sb.toString()).putInt("top", top).apply();
                    }
                }
                lastState = System.currentTimeMillis();
                if ((f & F_PAIRED) != 0 && gatt != null) {
                    String a = gatt.getDevice().getAddress();
                    if (!a.equals(prefs().getString("panel", ""))) prefs().edit().putString("panel", a).apply();
                }
                if (jogHeld && !(has(F_JOG) || has(F_JOG_OK))) jogRelease();
                render();
            });
        }

        @Override
        public void onReadRemoteRssi(BluetoothGatt g, int value, int st) {
            if (st == BluetoothGatt.GATT_SUCCESS) {
                rssi = value;
                ui.post(MainActivity.this::render);
            }
        }

        @Override
        public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int st) {
            synchronized (queue) {
                writing = false;
            }
            pump();
        }
    };

    private byte[] hello() {
        byte[] name = Build.MODEL.getBytes(StandardCharsets.UTF_8);
        int n = Math.min(name.length, 11);
        byte[] out = new byte[1 + 8 + n];
        out[0] = 'H';
        System.arraycopy(phoneId, 0, out, 1, 8);
        System.arraycopy(name, 0, out, 9, n);
        return out;
    }

    /** Commands go out one at a time (Android's GATT takes one operation at once). */
    private void send(byte[] cmd, boolean withResponse) {
        synchronized (queue) {
            // a held jog only needs its latest keep-alive queued
            Pending last = queue.peekLast();
            if (cmd.length == 1 && cmd[0] == 'J' && last != null && last.data[0] == 'J') return;
            queue.add(new Pending(cmd, !withResponse));
        }
        pump();
    }

    private void pump() {
        Pending item;
        synchronized (queue) {
            if (writing || queue.isEmpty() || gatt == null || cmdChr == null) return;
            item = queue.poll();
            writing = true;
        }
        try {
            cmdChr.setWriteType(item.noResponse ? BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                    : BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            cmdChr.setValue(item.data);
            if (!gatt.writeCharacteristic(cmdChr)) {
                synchronized (queue) {
                    queue.addFirst(item);             // the stack was busy: try it again shortly
                    writing = false;
                }
                ui.postDelayed(this::pump, 30);
            }
        } catch (SecurityException e) {
            synchronized (queue) {
                writing = false;
            }
        }
    }

    // ------------------------------------------------------------------ identity
    /** A random id made on first run: what the panel pairs with. */
    private byte[] loadPhoneId() {
        SharedPreferences p = prefs();
        String hex = p.getString("id", null);
        if (hex == null || hex.length() != 16) {
            byte[] b = new byte[8];
            new SecureRandom().nextBytes(b);
            StringBuilder sb = new StringBuilder();
            for (byte x : b) sb.append(String.format("%02x", x));
            hex = sb.toString();
            p.edit().putString("id", hex).apply();
        }
        byte[] out = new byte[8];
        for (int i = 0; i < 8; i++) out[i] = (byte) Integer.parseInt(hex.substring(2 * i, 2 * i + 2), 16);
        return out;
    }
}
