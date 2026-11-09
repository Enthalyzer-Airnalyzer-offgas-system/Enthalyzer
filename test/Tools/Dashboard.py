"""!
@file Dashboard.py
@brief Live dashboard for the ESP32 Enthalyzer

A Python script to log, parse, and visualize the 6-column timestamped 
raw serial data from the ESP32 Enthalyzer in real-time. 

v2.0.0 - Gas sensors removed. Redesigned into a 2x2 grid focusing 
         strictly on Water Temperatures, Delta T, Flow, and Q_water_gain.

@author Ayur Jitendra Ghalot
@contact ayur.ghalot@tu-dresden.de
@copyright Copyright (c) 2026 Ayur Jitendra Ghalot, TU Dresden, Chair of Bioprocess Engineering.

@license MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

@date 2026-11-06
@version 2.0.0
"""

import sys
import time
import csv
import threading
from collections import deque
from datetime import datetime

import numpy as np
import serial
import serial.tools.list_ports
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button

# ============================================================
# CONFIGURATION
# ============================================================
PORT               = "COM3" # Select the correct COM port for your ESP32
BAUD               = 115200
CONNECT_TIMEOUT_S  = 30
WINDOW_MIN         = 15
MAXPTS             = 8000
STALE_TIMEOUT_S    = 20
FLOW_AVG_N         = 10          
LOG_FILE           = f"run_{datetime.now():%Y%m%d_%H%M%S}.csv"
SNAPSHOT_FMT       = "snapshot_{ts}.png"

# 6 columns - MUST match Arduino header exactly, in order
COLS = [
    "Runtime_ms",
    "Flow_Lpm_raw",       
    "Flow_Lpm",           
    "T_water_in_C",
    "T_water_out_C",
    "Q_water_gain_W"
]

# ============================================================
# STYLING
# ============================================================
plt.style.use("dark_background")
plt.rcParams.update({
    "figure.facecolor": "#0e1117",
    "axes.facecolor":   "#161b22",
    "axes.edgecolor":   "#30363d",
    "axes.labelcolor":  "#c9d1d9",
    "xtick.color":      "#8b949e",
    "ytick.color":      "#8b949e",
    "grid.color":       "#30363d",
    "grid.alpha":       0.35,
    "text.color":       "#c9d1d9",
    "font.family":      "DejaVu Sans",
    "font.size":        10,
    "axes.titlesize":   11,
    "axes.titleweight": "bold",
    "legend.facecolor": "#161b22",
    "legend.edgecolor": "#30363d",
    "legend.framealpha":0.85,
})

PALETTE = {
    "w_in":    "#58a6ff", 
    "w_out":   "#f0883e",
    "delta":   "#bc8cff",
    "flow":    "#39d0d8", 
    "q_water": "#a2d2ff"
}

# ============================================================
# 1) CONNECTION CHECK
# ============================================================
def list_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

def open_and_verify(port, baud):
    print(f"[INFO] Available ports: {list_ports()}")
    print(f"[INFO] Opening {port} @ {baud} ...")
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print(f"[FATAL] Could not open {port}: {e}")
        sys.exit(1)

    time.sleep(2.0)
    ser.reset_input_buffer()
    print("[INFO] Waiting for first CSV frame ...")
    start = time.time()
    first_frame = None

    while time.time() - start < CONNECT_TIMEOUT_S:
        try:
            line = ser.readline().decode(errors="ignore").strip()
        except Exception:
            continue
        if not line:
            continue
        print(f"  > {line}")
        parts = [p.strip() for p in line.split(";")]
        if len(parts) == len(COLS):
            try:
                [float(x) for x in parts]
                first_frame = parts
                break
            except ValueError:
                pass

    if first_frame is None:
        print(f"[FATAL] No valid data frame received in {CONNECT_TIMEOUT_S}s.")
        print(f"        Expected {len(COLS)} ';'-separated fields per row.")
        ser.close()
        sys.exit(1)

    print("[ OK ] Connection verified. First frame:")
    for name, val in zip(COLS, first_frame):
        print(f"        {name:<16} = {val}")
    return ser, first_frame

# ============================================================
# 2) STATE
# ============================================================
buffers     = {c: deque(maxlen=MAXPTS) for c in COLS}
t_wall      = deque(maxlen=MAXPTS)
t0          = time.time()
_lock       = threading.Lock()
paused      = [False]
last_rx_ts  = [time.time()]
frame_count = [0]

# ============================================================
# 3) READER THREAD
# ============================================================
def reader_thread(ser, first_frame, csv_writer):
    def push(parts):
        with _lock:
            t_wall.append(time.time() - t0)
            for name, val in zip(COLS, parts):
                buffers[name].append(float(val))
            last_rx_ts[0] = time.time()
            frame_count[0] += 1
        now = datetime.now()
        csv_writer.writerow(
            [now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")] + parts
        )

    push(first_frame)
    while True:
        try:
            line = ser.readline().decode(errors="ignore").strip()
        except Exception:
            continue
        if not line:
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) != len(COLS):
            print(f"[esp32] {line}")
            continue
        try:
            if not paused[0]:
                push(parts)
        except ValueError:
            print(f"[warn] non-numeric row: {line}")

# ============================================================
# 4) FOOTER / MATH HELPERS
# ============================================================
def live_val(values, unit="", fmt="{:.2f}"):
    if not values: return "--"
    return f"{fmt.format(values[-1])}{unit}"

def rolling_mean(values, w):
    a = np.asarray(values, dtype=float)
    if a.size == 0: return a
    c   = np.cumsum(np.insert(a, 0, 0.0))
    idx = np.arange(a.size)
    lo  = np.maximum(0, idx - w + 1)
    return (c[idx + 1] - c[lo]) / (idx - lo + 1)

def flow_val(values, unit=" L/min", fmt="{:.2f}", n=FLOW_AVG_N):
    if not values: return "--"
    arr = np.asarray(values)
    avg = arr[-n:].mean()
    return (f"raw={fmt.format(arr[-1])}{unit}  "
            f"avg{n}={fmt.format(avg)}{unit}")

# ============================================================
# 5) BUILD FIGURE 
# ============================================================
def build_figure():
    fig = plt.figure(figsize=(16, 9))
    fig.canvas.manager.set_window_title("ESP32 Enthalyzer - Water-Side Dashboard")

    gs = fig.add_gridspec(
        nrows=2, ncols=2,
        left=0.06, right=0.94, top=0.88, bottom=0.12,
        hspace=0.40, wspace=0.20,
    )

    ax_T  = fig.add_subplot(gs[0, 0])   # Water Temperatures
    ax_dT = fig.add_subplot(gs[0, 1])   # Water Delta T
    ax_F  = fig.add_subplot(gs[1, 0])   # Water Flow
    ax_Q  = fig.add_subplot(gs[1, 1])   # Q_water_gain

    all_axes = [ax_T, ax_dT, ax_F, ax_Q]

    # ---- Panel 1: Water In/Out Temperatures ----
    ln_win, = ax_T.plot([], [], color=PALETTE["w_in"],   lw=2.0, label="H2O Inlet")
    ln_wout,= ax_T.plot([], [], color=PALETTE["w_out"],  lw=2.0, label="H2O Outlet")
    ax_T.set_title("Water Temperatures")
    ax_T.set_ylabel("degC")
    ax_T.legend(loc="upper left", fontsize=9, ncol=2)

    # ---- Panel 2: Water Delta T (Out - In) ----
    ln_dT,  = ax_dT.plot([], [], color=PALETTE["delta"], lw=2.0, label="Delta T (Outlet - Inlet)")
    ax_dT.set_title("Water-Side Differential (ΔT)")
    ax_dT.set_ylabel("degC")
    ax_dT.axhline(0, color="#30363d", lw=0.8)
    ax_dT.legend(loc="upper left", fontsize=9)

    # ---- Panel 3: Water Flow RAW + avg ----
    ln_flow_raw, = ax_F.plot([], [], color=PALETTE["flow"], lw=1.0, alpha=0.45, label="Flow raw (L/min)")
    ln_flow_avg, = ax_F.plot([], [], color="#ffffff", lw=2.0, label=f"Flow avg-{FLOW_AVG_N} (L/min)")
    ax_F.set_title("Cooling Water Flow Rate")
    ax_F.set_ylabel("L/min")
    ax_F.set_ylim(bottom=0)
    ax_F.legend(loc="upper left", fontsize=9, ncol=2)

    # ---- Panel 4: Heat Gain (Q_water) ----
    ln_qw,  = ax_Q.plot([], [], color=PALETTE["q_water"], lw=2.2, label="Q water gain")
    ax_Q.set_title("Water-Side Heat Gain (Cooling Duty)")
    ax_Q.set_ylabel("W")
    ax_Q.axhline(0, color="#30363d", lw=0.6)
    ax_Q.legend(loc="upper left", fontsize=9)

    for ax in all_axes:
        ax.grid(True, alpha=0.3)
        ax.set_xlabel("Time (min)", fontsize=9)

    # ============================================================
    # HEADER & FOOTER
    # ============================================================
    fig.suptitle("ESP32 Enthalyzer - Live Water-Side Diagnostic Dashboard",
                 fontsize=15, fontweight="bold", color="#f0f6fc", x=0.06, y=0.96, ha="left")

    info_text = fig.text(0.40, 0.94, "", fontsize=10, color="#8b949e", ha="left")
    status_text = fig.text(0.94, 0.94, "CONNECTING...", fontsize=12, fontweight="bold", 
                           color="#f0b429", ha="right", va="center",
                           bbox=dict(boxstyle="round,pad=0.4", facecolor="#161b22", edgecolor="#30363d", alpha=0.9))

    stats_box = fig.text(0.50, 0.030, "", fontsize=11, color="#c9d1d9", ha="center", family="DejaVu Sans Mono",
                         bbox=dict(boxstyle="round,pad=0.6", facecolor="#161b22", edgecolor="#30363d", alpha=0.9))

    lines = {
        "T_water_in_C":  ln_win,  
        "T_water_out_C": ln_wout,
        "dT": ln_dT,
        "Flow_Lpm_raw": ln_flow_raw, 
        "Flow_avg10": ln_flow_avg,
        "Q_water_gain_W": ln_qw,
    }

    return (fig, lines, all_axes, status_text, info_text, stats_box)

# ============================================================
# 6) UPDATER
# ============================================================
def make_updater(lines, all_axes, status_text, info_text, stats_box):

    def autoscale_y(ax, values_list, pad_frac=0.10, floor=None, ceil=None):
        flat = []
        for v in values_list:
            if v: flat.extend(v)
        if not flat: return
        lo, hi = min(flat), max(flat)
        if lo == hi: lo -= 0.5; hi += 0.5
        span = hi - lo
        lo -= span * pad_frac
        hi += span * pad_frac
        if floor is not None: lo = max(lo, floor)
        if ceil  is not None: hi = min(hi, ceil)
        ax.set_ylim(lo, hi)

    def update(_):
        with _lock:
            if not t_wall: return
            xs = np.array(t_wall) / 60.0
            snap = {k: list(v) for k, v in buffers.items()}
            n_frames = frame_count[0]

        age = time.time() - last_rx_ts[0]
        if paused[0]:
            status_text.set_text("PAUSED");  status_text.set_color("#f0b429")
        elif age > STALE_TIMEOUT_S:
            status_text.set_text(f"STALE ({age:.0f}s)"); status_text.set_color("#f85149")
        else:
            status_text.set_text(f"LIVE ({age:.1f}s)");  status_text.set_color("#56d364")

        info_text.set_text(f"frames: {n_frames}   |   port: {PORT}   |   log: {LOG_FILE}   |   {datetime.now():%H:%M:%S}")

        for key, ln in lines.items():
            if key == "dT":
                if snap["T_water_in_C"] and snap["T_water_out_C"]:
                    dT = np.array(snap["T_water_out_C"]) - np.array(snap["T_water_in_C"])
                    ln.set_data(xs, dT)
            elif key == "Flow_avg10":
                if snap["Flow_Lpm_raw"]:
                    ln.set_data(xs, rolling_mean(snap["Flow_Lpm_raw"], FLOW_AVG_N))
            else:
                ln.set_data(xs, snap[key])

        xmax = xs[-1]; xmin = max(0, xmax - WINDOW_MIN)
        for ax in all_axes: ax.set_xlim(xmin, xmax + 0.05)

        ax_T, ax_dT, ax_F, ax_Q = all_axes
        autoscale_y(ax_T,  [snap["T_water_in_C"], snap["T_water_out_C"]])
        if snap["T_water_in_C"] and snap["T_water_out_C"]:
            dT_arr = np.array(snap["T_water_out_C"]) - np.array(snap["T_water_in_C"])
            autoscale_y(ax_dT, [list(dT_arr)])
        autoscale_y(ax_F,  [snap["Flow_Lpm_raw"]], floor=0)   
        autoscale_y(ax_Q,  [snap["Q_water_gain_W"]])

        # ---- Footer Readout ----
        s = (
            f"H2O_Inlet: {live_val(snap['T_water_in_C'],' °C','{:6.2f}')}   |   "
            f"H2O_Outlet: {live_val(snap['T_water_out_C'],' °C','{:6.2f}')}   |   "
            f"Flow: {flow_val(snap['Flow_Lpm_raw'],' L/min','{:5.2f}')}   |   "
            f"Heat Gain (Q): {live_val(snap['Q_water_gain_W'],' W','{:6.2f}')}"
        )
        stats_box.set_text(s)

    return update

# ============================================================
# 7) CONTROL BUTTONS
# ============================================================
def add_controls(fig):
    ax_pause  = fig.add_axes([0.06, 0.015, 0.08, 0.035])
    ax_snap   = fig.add_axes([0.15, 0.015, 0.08, 0.035])
    ax_clear  = fig.add_axes([0.24, 0.015, 0.08, 0.035])

    btn_pause = Button(ax_pause, "Pause",    color="#21262d", hovercolor="#30363d")
    btn_snap  = Button(ax_snap,  "Snapshot", color="#21262d", hovercolor="#30363d")
    btn_clear = Button(ax_clear, "Clear",    color="#21262d", hovercolor="#30363d")

    for b in (btn_pause, btn_snap, btn_clear):
        b.label.set_color("#c9d1d9")
        b.label.set_fontsize(10)

    def on_pause(_):
        paused[0] = not paused[0]
        btn_pause.label.set_text("Resume" if paused[0] else "Pause")
        fig.canvas.draw_idle()

    def on_snap(_):
        fn = SNAPSHOT_FMT.format(ts=datetime.now().strftime("%Y%m%d_%H%M%S"))
        fig.savefig(fn, dpi=150, facecolor=fig.get_facecolor())
        print(f"[INFO] Snapshot saved -> {fn}")

    def on_clear(_):
        with _lock:
            t_wall.clear()
            for k in buffers: buffers[k].clear()
        print("[INFO] Buffers cleared")

    btn_pause.on_clicked(on_pause)
    btn_snap.on_clicked(on_snap)
    btn_clear.on_clicked(on_clear)
    fig._widgets = [btn_pause, btn_snap, btn_clear]

# ============================================================
# 8) MAIN
# ============================================================
def main():
    ser, first_frame = open_and_verify(PORT, BAUD)

    log = open(LOG_FILE, "w", newline="", encoding="utf-8")
    writer = csv.writer(log)
    writer.writerow(["date", "time"] + COLS)     
    print(f"[INFO] Logging raw frames to {LOG_FILE}")

    t = threading.Thread(target=reader_thread, args=(ser, first_frame, writer), daemon=True)
    t.start()

    (fig, lines, all_axes, status_text, info_text, stats_box) = build_figure()
    add_controls(fig)

    ani = FuncAnimation(
        fig,
        make_updater(lines, all_axes, status_text, info_text, stats_box),
        interval=1000, blit=False, cache_frame_data=False,
    )

    try:
        plt.show()
    finally:
        final_png = SNAPSHOT_FMT.format(ts=datetime.now().strftime("%Y%m%d_%H%M%S_final"))
        try:
            fig.savefig(final_png, dpi=150, facecolor=fig.get_facecolor())
        except Exception:
            pass
        log.flush(); log.close()
        ser.close()

if __name__ == "__main__":
    main()
