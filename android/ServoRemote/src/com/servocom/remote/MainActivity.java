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
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
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

    private static final int BLUE = Color.rgb(0, 128, 255), GREEN = Color.rgb(64, 200, 110),
            PANEL = Color.rgb(44, 46, 52), DIM = Color.rgb(110, 110, 110), BG = Color.rgb(18, 20, 24),
            RED = Color.rgb(240, 70, 60);

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

    private TextView status, fwd, rev, en, jog;

    // ------------------------------------------------------------------ UI
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        phoneId = loadPhoneId();

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        int pad = dp(16);
        root.setPadding(pad, dp(28), pad, pad);

        status = new TextView(this);
        status.setTextColor(Color.rgb(200, 200, 200));
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        status.setPadding(dp(4), 0, dp(4), dp(12));
        root.addView(status, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout dirRow = new LinearLayout(this);
        dirRow.setOrientation(LinearLayout.HORIZONTAL);
        fwd = button("FWD");
        rev = button("REV");
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, -1, 1f);
        half.setMarginEnd(dp(8));
        dirRow.addView(fwd, half);
        dirRow.addView(rev, new LinearLayout.LayoutParams(0, -1, 1f));
        root.addView(dirRow, rowParams(1f));

        en = button("EN");
        root.addView(en, rowParams(1.2f));

        jog = button("JOG");
        root.addView(jog, rowParams(1.6f));
        setContentView(root);

        fwd.setOnClickListener(v -> press(v, new byte[]{'D', 'F'}));
        rev.setOnClickListener(v -> press(v, new byte[]{'D', 'R'}));
        en.setOnClickListener(v -> press(v, new byte[]{'E', (byte) (has(F_ENABLED) ? 0 : 1)}));
        jog.setOnTouchListener(this::jogTouch);

        BluetoothManager bm = (BluetoothManager) getSystemService(BLUETOOTH_SERVICE);
        adapter = bm == null ? null : bm.getAdapter();
        render();
        ui.postDelayed(watchdog, 1000);
    }

    private TextView button(String text) {
        TextView b = new TextView(this);
        b.setText(text);
        b.setGravity(Gravity.CENTER);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 44);
        b.setTypeface(Typeface.DEFAULT_BOLD);
        b.setTextColor(Color.WHITE);
        b.setClickable(true);
        b.setHapticFeedbackEnabled(true);
        paint(b, PANEL);
        return b;
    }

    private LinearLayout.LayoutParams rowParams(float weight) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, 0, weight);
        p.topMargin = dp(10);
        return p;
    }

    private void paint(TextView b, int color) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(14));
        b.setBackground(d);
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

    /** Buttons and status line from the panel's last state. */
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
        } else {
            s = "Connected to the panel" + (has(F_LEVER) ? "  -  lever is not OFF" : "");
        }
        status.setText(s);

        boolean rv = has(F_REV);
        paint(fwd, ok && !rv ? BLUE : PANEL);
        paint(rev, ok && rv ? BLUE : PANEL);
        fwd.setTextColor(ok ? Color.WHITE : DIM);
        rev.setTextColor(ok ? Color.WHITE : DIM);
        fwd.setEnabled(ok);
        rev.setEnabled(ok);

        boolean on = has(F_ENABLED);
        en.setText(on ? "ENABLED" : "EN");
        paint(en, ok && on ? GREEN : PANEL);
        en.setTextColor(ok ? Color.WHITE : DIM);
        en.setEnabled(ok);

        boolean canJog = ok && (has(F_JOG_OK) || has(F_JOG) || jogHeld);
        paint(jog, canJog && (jogHeld || has(F_JOG)) ? BLUE : PANEL);
        jog.setTextColor(canJog ? Color.WHITE : DIM);
        jog.setText(ok && !canJog ? (on ? "JOG\n(drive enabled)" : "JOG\n(lever not OFF)") : "JOG");
        jog.setTextSize(TypedValue.COMPLEX_UNIT_SP, ok && !canJog ? 28 : 44);
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
