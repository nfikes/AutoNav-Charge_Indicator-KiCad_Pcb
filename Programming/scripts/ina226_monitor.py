"""INA226 Real-Time Monitor GUI
Displays bus voltage, current, and power from the INA226 (U3)
using the Aardvark I2C adapter with oscilloscope-style rolling plots.

Sampling runs in a dedicated thread at maximum I2C speed (~500+ Hz at
400 kHz fast-mode).  The GUI refreshes at 20 Hz and shows the last
HISTORY samples.  Every sample is logged to a timestamped CSV in
the outputs/ folder.
"""
import csv, time, threading
from datetime import datetime
from hw_common import *
import tkinter as tk
from collections import deque

R_SHUNT      = 0.010        # 10 mOhm
CURRENT_LSB  = 0.00025      # 250 uA/bit
POWER_LSB    = 25 * CURRENT_LSB  # 6.25 mW/bit
CAL_VALUE    = int(0.00512 / (CURRENT_LSB * R_SHUNT))  # 2048

# INA226 config: AVG=1, VBUSCT=140us, VSHCT=140us, continuous shunt+bus
# Bits: 0 100 000 000 000 111 = 0x4007
CONFIG_FAST  = 0x4007

CELLS_SERIES = 8

# LiFePO4 voltage-to-SOC lookup table (per-cell OCV, mV)
# Empirically measured from Battery A full discharge (20.476 Ah, 4 sessions).
LFP_SOC_TABLE = [
    (3323, 100), (3322, 97.5), (3321, 95), (3320, 90), (3319, 85),
    (3318, 80), (3313, 75), (3307, 70), (3290, 65), (3288, 60),
    (3287, 55), (3284, 50), (3281, 45), (3276, 40), (3269, 35),
    (3260, 30), (3248, 25), (3232, 20), (3211, 15), (3196, 10),
    (3179, 7.5), (3138, 5), (3044, 2.5), (2922, 0),
]


def voltage_to_soc(bus_v):
    """Estimate SOC% from bus voltage (in volts) using LFP lookup table."""
    cell_mv = (bus_v * 1000) / CELLS_SERIES
    if cell_mv >= LFP_SOC_TABLE[0][0]:
        return 100.0
    if cell_mv <= LFP_SOC_TABLE[-1][0]:
        return 0.0
    for i in range(len(LFP_SOC_TABLE) - 1):
        v_hi, soc_hi = LFP_SOC_TABLE[i]
        v_lo, soc_lo = LFP_SOC_TABLE[i + 1]
        if v_lo <= cell_mv <= v_hi:
            frac = (cell_mv - v_lo) / (v_hi - v_lo)
            return soc_lo + frac * (soc_hi - soc_lo)
    return 50.0

GUI_MS     = 50    # GUI refresh interval (ms) — 20 Hz display
HISTORY    = 500   # samples shown on plot (~1 s at 500 Hz)
PLOT_W     = 600   # plot canvas width (px)
PLOT_H     = 120   # plot canvas height (px)
GRID_LINES = 4     # horizontal grid divisions


# --- I2C helpers ---
def i2c_read_reg(handle, addr, reg, n=2):
    aa_i2c_write(handle, addr, AA_I2C_NO_STOP, array('B', [reg]))
    rc, data = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, n)
    if rc != n:
        return None
    return data


def read_u16(handle, addr, reg):
    d = i2c_read_reg(handle, addr, reg)
    if d is None:
        return None
    return (d[0] << 8) | d[1]


def read_s16(handle, addr, reg):
    v = read_u16(handle, addr, reg)
    if v is None:
        return None
    return v - 0x10000 if v >= 0x8000 else v


# --- Open Aardvark & configure INA226 ---
handle = aardvark_init(bitrate=400)

# Configure for fastest conversion (140us bus + shunt, no averaging)
cfg_msb = (CONFIG_FAST >> 8) & 0xFF
cfg_lsb = CONFIG_FAST & 0xFF
aa_i2c_write(handle, INA, AA_I2C_NO_FLAGS,
             array('B', [REG_CONFIG, cfg_msb, cfg_lsb]))

# Write calibration register so current & power registers give real values
cal_msb = (CAL_VALUE >> 8) & 0xFF
cal_lsb = CAL_VALUE & 0xFF
aa_i2c_write(handle, INA, AA_I2C_NO_FLAGS,
             array('B', [REG_CAL, cal_msb, cal_lsb]))

# --- CSV recording (toggled by Record button, 10 Hz) ---
out_base = os.path.join(os.path.dirname(__file__), "..", "empirical_results")
csv_file     = None
csv_writer   = None
csv_path     = None
recording    = False
t_start      = time.time()
REC_INTERVAL = 100   # ms between CSV rows (10 Hz)

# --- Shared state between sampling thread and GUI ---
buf_lock   = threading.Lock()
buf_samples = []        # list of (v, i, p, soc) accumulated between GUI frames
sample_count = 0        # total samples taken (for rate calc)
sampling   = True       # flag to stop the thread
latest      = [None, None, None, None]  # most recent (v, i, p, soc) for CSV


def _start_recording():
    """Open a new CSV file using the AutoNav naming convention."""
    global csv_file, csv_writer, csv_path, recording
    test_id = "ina226"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_stem = f"{test_id}_{stamp}"
    run_dir = os.path.join(out_base, run_stem)
    os.makedirs(run_dir, exist_ok=True)
    csv_path = os.path.join(run_dir, f"{run_stem}.csv")
    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["ROS2_Clock", "Topic_Name", "Data_Keys",
                         "Value_0", "Value_1", "Value_2", "Value_3"])
    recording = True
    print(f"Recording to {csv_path}")


def _stop_recording():
    """Close the CSV file."""
    global csv_file, csv_writer, recording
    recording = False
    if csv_file is not None:
        csv_file.close()
        print(f"CSV saved: {csv_path}")
        csv_file = None
        csv_writer = None


def sample_loop():
    """Tight loop — reads all 3 registers back-to-back, feeds GUI buffer."""
    global sample_count

    while sampling:
        raw_v = read_u16(handle, INA, REG_BUS_V)
        raw_i = read_s16(handle, INA, REG_CURRENT)
        raw_p = read_u16(handle, INA, REG_POWER)

        v = raw_v * 1.25e-3 if raw_v is not None else None
        i = raw_i * CURRENT_LSB if raw_i is not None else None
        p = raw_p * POWER_LSB if raw_p is not None else None
        soc = voltage_to_soc(v) if v is not None else None

        with buf_lock:
            buf_samples.append((v, i, p, soc))
            sample_count += 1
            latest[:] = [v, i, p, soc]


# --- GUI ---
root = tk.Tk()
root.title("INA226 Monitor")
root.configure(bg="#1e1e1e")
root.resizable(False, False)

BG       = "#1e1e1e"
GRID_CLR = "#2a2a2a"
FGDM     = "#888888"
FONT_LBL = ("Menlo", 12)
FONT_VAL = ("Menlo", 22, "bold")
FONT_AX  = ("Menlo", 9)
FONT_RATE = ("Menlo", 10)

PAD   = 40   # left margin for axis labels
PAD_R = 10   # right margin


class Trace:
    """One oscilloscope channel: numeric readout + rolling canvas plot."""

    def __init__(self, parent, row, label, unit, color, y_min, y_max, fmt):
        self.color = color
        self.y_min = y_min
        self.y_max = y_max
        self.fmt   = fmt
        self.unit  = unit
        self.data  = deque([0.0] * HISTORY, maxlen=HISTORY)

        # --- header row: label + value ---
        hdr = tk.Frame(parent, bg=BG)
        hdr.grid(row=row * 2, column=0, sticky="ew", padx=(8, 8), pady=(10, 0))
        tk.Label(hdr, text=label, font=FONT_LBL, fg=FGDM, bg=BG,
                 anchor="w").pack(side="left")
        self.val_lbl = tk.Label(hdr, text="---", font=FONT_VAL, fg=color,
                                bg=BG, anchor="e")
        self.val_lbl.pack(side="right")

        # --- canvas plot ---
        cw = PLOT_W + PAD + PAD_R
        self.canvas = tk.Canvas(parent, width=cw, height=PLOT_H,
                                bg=BG, highlightthickness=0)
        self.canvas.grid(row=row * 2 + 1, column=0, padx=(8, 8), pady=(2, 0))

        # pre-draw static grid + axis labels
        self._draw_grid()

    def _draw_grid(self):
        c = self.canvas
        # horizontal grid lines + labels
        for i in range(GRID_LINES + 1):
            y = int(i * PLOT_H / GRID_LINES)
            c.create_line(PAD, y, PAD + PLOT_W, y, fill=GRID_CLR)
            val = self.y_max - i * (self.y_max - self.y_min) / GRID_LINES
            c.create_text(PAD - 4, y, text=f"{val:{self.fmt}}",
                          anchor="e", fill=FGDM, font=FONT_AX, tags="axlbl")
        # vertical border
        c.create_line(PAD, 0, PAD, PLOT_H, fill=GRID_CLR)

    def push(self, value):
        if value is None:
            value = self.data[-1]  # hold last value on error
        self.data.append(value)
        self.val_lbl.config(text=f"{value:{self.fmt}} {self.unit}")

    def redraw(self):
        c = self.canvas
        c.delete("trace")

        pts = []
        dx = PLOT_W / (HISTORY - 1)
        span = self.y_max - self.y_min
        if span == 0:
            span = 1

        # auto-scale: if data exceeds range, expand
        d_min = min(self.data)
        d_max = max(self.data)
        y_lo = min(self.y_min, d_min * 0.95) if d_min < self.y_min else self.y_min
        y_hi = max(self.y_max, d_max * 1.05) if d_max > self.y_max else self.y_max
        span = y_hi - y_lo if y_hi != y_lo else 1

        for i, v in enumerate(self.data):
            x = PAD + i * dx
            frac = (v - y_lo) / span
            y = PLOT_H - frac * PLOT_H
            y = max(0, min(PLOT_H, y))
            pts.append(x)
            pts.append(y)

        if len(pts) >= 4:
            c.create_line(*pts, fill=self.color, width=2, tags="trace",
                          smooth=True)

        # update axis labels if range shifted
        c.delete("axlbl")
        for i in range(GRID_LINES + 1):
            yp = int(i * PLOT_H / GRID_LINES)
            val = y_hi - i * (y_hi - y_lo) / GRID_LINES
            c.create_text(PAD - 4, yp, text=f"{val:{self.fmt}}",
                          anchor="e", fill=FGDM, font=FONT_AX, tags="axlbl")


frame = tk.Frame(root, bg=BG)
frame.pack(padx=0, pady=(0, 10))

# --- Oscilloscope traces (left column) ---
trace_frame = tk.Frame(frame, bg=BG)
trace_frame.grid(row=0, column=0, sticky="nsew")

tr_v = Trace(trace_frame, 0, "Voltage", "V",  "#4fc3f7", 20.0, 30.0, ".2f")
tr_i = Trace(trace_frame, 1, "Current", "A",  "#aed581",  0.0,  3.0, ".3f")
tr_p = Trace(trace_frame, 2, "Power",   "W",  "#ffb74d",  0.0, 80.0, ".1f")

# bottom bar: sample rate + record button
bot_frame = tk.Frame(trace_frame, bg=BG)
bot_frame.grid(row=6, column=0, sticky="ew", padx=(8, 8), pady=(6, 0))

FONT_REC = ("Menlo", 11, "bold")

rate_lbl = tk.Label(bot_frame, text="0 Hz", font=FONT_RATE, fg=FGDM, bg=BG)
rate_lbl.pack(side="left")


def toggle_record():
    global recording
    if recording:
        _stop_recording()
        rec_btn.config(text="Record", fg="#aed581", activeforeground="#aed581")
    else:
        _start_recording()
        rec_btn.config(text="Stop", fg="#f44336", activeforeground="#f44336")


rec_btn = tk.Button(bot_frame, text="Record", font=FONT_REC,
                    fg="#aed581", bg="#333333", activebackground="#444444",
                    activeforeground="#aed581", highlightthickness=0,
                    bd=0, padx=12, pady=2, command=toggle_record)
rec_btn.pack(side="right")

# --- SOC battery bar (right column) ---
BAR_W      = 60    # bar width (px)
BAR_H      = 360   # bar height (px) — spans the 3 traces
BAR_PAD    = 16    # internal padding from canvas edge to bar rect
FONT_SOC   = ("Menlo", 28, "bold")
FONT_SOC_S = ("Menlo", 11)

soc_frame = tk.Frame(frame, bg=BG)
soc_frame.grid(row=0, column=1, sticky="ns", padx=(4, 12), pady=(10, 0))

soc_lbl = tk.Label(soc_frame, text="---%", font=FONT_SOC, fg="#ce93d8", bg=BG)
soc_lbl.pack(pady=(0, 6))

soc_canvas = tk.Canvas(soc_frame, width=BAR_W, height=BAR_H,
                        bg=BG, highlightthickness=0)
soc_canvas.pack()

soc_sub_lbl = tk.Label(soc_frame, text="Charge", font=FONT_SOC_S, fg=FGDM, bg=BG)
soc_sub_lbl.pack(pady=(4, 0))

# Draw the static bar outline
soc_canvas.create_rectangle(0, 0, BAR_W, BAR_H, outline="#444444", width=2, tags="outline")

soc_history = deque(maxlen=HISTORY)  # rolling window matching the trace plots


def soc_color(pct):
    """Return fill color based on SOC level."""
    if pct >= 60:
        return "#4caf50"   # green
    elif pct >= 30:
        return "#ff9800"   # amber
    else:
        return "#f44336"   # red


def redraw_soc_bar():
    """Redraw the filled portion of the SOC bar (averaged over window)."""
    soc = sum(soc_history) / len(soc_history) if soc_history else 0.0
    soc_canvas.delete("fill")
    frac = max(0.0, min(1.0, soc / 100.0))
    fill_h = int(frac * BAR_H)
    if fill_h > 0:
        soc_canvas.create_rectangle(
            1, BAR_H - fill_h, BAR_W - 1, BAR_H,
            fill=soc_color(soc), outline="", tags="fill")
    # re-draw outline on top
    soc_canvas.delete("outline")
    soc_canvas.create_rectangle(0, 0, BAR_W, BAR_H,
                                 outline="#444444", width=2, tags="outline")
    soc_lbl.config(text=f"{soc:.0f}%", fg=soc_color(soc))

last_rate_time  = time.time()
last_rate_count = 0


def update_gui():
    """Drain sample buffer into traces and redraw (called at 20 Hz)."""
    global last_rate_time, last_rate_count

    with buf_lock:
        new_samples = list(buf_samples)
        buf_samples.clear()
        total = sample_count

    for v, i, p, soc in new_samples:
        tr_v.push(v)
        tr_i.push(i)
        tr_p.push(p)
        if soc is not None:
            soc_history.append(soc)

    tr_v.redraw()
    tr_i.redraw()
    tr_p.redraw()
    redraw_soc_bar()

    # Update rate display every ~1 s
    now = time.time()
    dt = now - last_rate_time
    if dt >= 1.0:
        rate = (total - last_rate_count) / dt
        rate_lbl.config(text=f"{rate:.0f} Hz")
        last_rate_time  = now
        last_rate_count = total

    root.after(GUI_MS, update_gui)


def csv_tick():
    """Write one row to CSV at 10 Hz when recording."""
    if recording and csv_writer is not None:
        with buf_lock:
            v, i, p, soc = latest
        ts = int((time.time() - t_start) * 1e9)  # nanoseconds like ROS2_Clock
        if v is not None:
            csv_writer.writerow([ts, "/electrical/voltage", "voltage_V", f"{v:.4f}"])
        if i is not None:
            csv_writer.writerow([ts, "/electrical/current", "current_A", f"{i:.5f}"])
        if p is not None:
            csv_writer.writerow([ts, "/electrical/power", "power_W", f"{p:.3f}"])
        if soc is not None:
            csv_writer.writerow([ts, "/electrical/soc", "soc_pct", f"{soc:.1f}"])
    root.after(REC_INTERVAL, csv_tick)


def on_close():
    global sampling
    sampling = False
    sample_thread.join(timeout=1.0)
    if recording:
        _stop_recording()
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)

# Start sampling thread, then GUI loop
sample_thread = threading.Thread(target=sample_loop, daemon=True)
sample_thread.start()
update_gui()
csv_tick()
root.mainloop()
