package com.servocom.remote;

import android.Manifest;
import android.app.Activity;
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
            STATUS = Color.rgb(160, 160, 160), BG = Color.BLACK;

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

    private TextView status, dir, en, jog;
    private Typeface font;

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
        buildUi();
    }

    /** FWD / EN / JOG in one row across the top, all the same size, in
     *  either orientation; the status line along the bottom; the space
     *  between is left free. */
    private void buildUi() {
        boolean land = getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        int gap = dp(8), pad = dp(12);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setPadding(pad, dp(land ? 8 : 16), pad, pad);

        // square buttons, but never taller than about 40 % of a landscape screen
        android.util.DisplayMetrics dm = getResources().getDisplayMetrics();
        int cell = (dm.widthPixels - 2 * pad - 2 * gap) / 3;
        int height = land ? Math.min(cell, (int) (dm.heightPixels * 0.4)) : cell;

        dir = button("FWD");
        en = button("EN");
        jog = button("JOG");
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        TextView[] buttons = {dir, en, jog};
        for (int i = 0; i < buttons.length; i++) {
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, -1, 1f);
            if (i < buttons.length - 1) p.setMarginEnd(gap);
            row.addView(buttons[i], p);
        }
        root.addView(row, new LinearLayout.LayoutParams(-1, height));
        root.addView(new View(this), new LinearLayout.LayoutParams(-1, 0, 1f));   // free space

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
        render();
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
            ui.post(() -> {
                flags = f;
                lastState = System.currentTimeMillis();
                if (jogHeld && !(has(F_JOG) || has(F_JOG_OK))) jogRelease();
                render();
            });
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
        SharedPreferences p = getSharedPreferences("remote", MODE_PRIVATE);
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
