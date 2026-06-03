"""INA226 Real-Time Monitor GUI
Displays bus voltage, current, and power from the INA226 (U3)
using the Aardvark I2C adapter with oscilloscope-style rolling plots.

Sampling runs in a dedicated thread at maximum I2C speed (~500+ Hz at
400 kHz fast-mode).  The GUI refreshes at 20 Hz and shows the last
HISTORY samples.  Every sample is logged to a timestamped CSV in
the outputs/ folder.

UI: window is resizable; F11 or Cmd+F toggles fullscreen, Esc exits.
The right-side stats panel + bottom console give a console-style view
of session totals, ranges, and events.
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
CONFIG_FAST  = 0x4007

CELLS_SERIES = 8
CAPACITY_AH  = 20.476       # Battery A measured full capacity

# LiFePO4 voltage-to-SOC lookup table (per-cell OCV, mV)
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
PLOT_W     = 600   # initial plot canvas width (px) — grows with window
PLOT_H     = 120   # initial plot canvas height (px) — grows with window
GRID_LINES = 4


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

cfg_msb = (CONFIG_FAST >> 8) & 0xFF
cfg_lsb = CONFIG_FAST & 0xFF
aa_i2c_write(handle, INA, AA_I2C_NO_FLAGS,
             array('B', [REG_CONFIG, cfg_msb, cfg_lsb]))

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
buf_lock    = threading.Lock()
buf_samples = []        # list of (v, i, p, soc) accumulated between GUI frames
sample_count = 0        # total samples taken (for rate calc)
sampling    = True      # flag to stop the thread
latest      = [None, None, None, None]  # most recent (v, i, p, soc) for CSV

# --- Session running totals / extrema (updated in sample_loop) ---
total_charge_as = 0.0   # accumulated charge (amp-seconds), |I|*dt
total_energy_ws = 0.0   # accumulated energy (watt-seconds), |P|*dt
v_min = v_max = None
i_min = i_max = None
p_min = p_max = None
read_errors = 0         # I2C reads that returned None


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
    log_console(f"Recording → {os.path.basename(csv_path)}", "ok")


def _stop_recording():
    """Close the CSV file."""
    global csv_file, csv_writer, recording
    recording = False
    if csv_file is not None:
        csv_file.close()
        log_console(f"Saved {os.path.basename(csv_path)}", "ok")
        csv_file = None
        csv_writer = None


R_INTERNAL   = 0.060        # estimated pack internal resistance (ohms)
CAPACITY_AS  = CAPACITY_AH * 3600
coulomb_soc  = None
_last_sample_time = None


def sample_loop():
    """Tight loop — reads all 3 registers back-to-back, feeds GUI buffer.
    SOC is computed via coulomb counting (integrating current over time),
    initialized from IR-compensated OCV on first sample."""
    global sample_count, coulomb_soc, _last_sample_time
    global total_charge_as, total_energy_ws, read_errors
    global v_min, v_max, i_min, i_max, p_min, p_max

    while sampling:
        raw_v = read_u16(handle, INA, REG_BUS_V)
        raw_i = read_s16(handle, INA, REG_CURRENT)
        raw_p = read_u16(handle, INA, REG_POWER)

        if raw_v is None or raw_i is None or raw_p is None:
            read_errors += 1

        v = raw_v * 1.25e-3 if raw_v is not None else None
        i = raw_i * CURRENT_LSB if raw_i is not None else None
        p = raw_p * POWER_LSB if raw_p is not None else None

        now = time.time()
        if v is not None and i is not None:
            if coulomb_soc is None:
                ocv = v + abs(i) * R_INTERNAL
                coulomb_soc = voltage_to_soc(ocv)
                _last_sample_time = now
            else:
                dt = now - _last_sample_time
                _last_sample_time = now
                ai = abs(i)
                coulomb_soc -= (ai * dt / CAPACITY_AS) * 100.0
                coulomb_soc = max(0.0, min(100.0, coulomb_soc))
                total_charge_as += ai * dt
                if p is not None:
                    total_energy_ws += abs(p) * dt
        soc = coulomb_soc

        # session min/max tracking
        if v is not None:
            v_min = v if v_min is None else min(v_min, v)
            v_max = v if v_max is None else max(v_max, v)
        if i is not None:
            i_min = i if i_min is None else min(i_min, i)
            i_max = i if i_max is None else max(i_max, i)
        if p is not None:
            p_min = p if p_min is None else min(p_min, p)
            p_max = p if p_max is None else max(p_max, p)

        with buf_lock:
            buf_samples.append((v, i, p, soc))
            sample_count += 1
            latest[:] = [v, i, p, soc]


# --- GUI ---
root = tk.Tk()
root.title("INA226 Monitor")
root.configure(bg="#1e1e1e")
root.resizable(True, True)
root.minsize(980, 600)
root.geometry("1280x780")

BG          = "#1e1e1e"
BG_PANEL    = "#252525"
GRID_CLR    = "#2a2a2a"
FGDM        = "#888888"
FG          = "#dddddd"
FONT_LBL    = ("Menlo", 12)
FONT_VAL    = ("Menlo", 22, "bold")
FONT_AX     = ("Menlo", 9)
FONT_RATE   = ("Menlo", 10)
FONT_STAT   = ("Menlo", 11)
FONT_STAT_B = ("Menlo", 11, "bold")
FONT_HDR    = ("Menlo", 11, "bold")
FONT_LOG    = ("Menlo", 10)
FONT_REC    = ("Menlo", 11, "bold")

PAD   = 40   # left margin for axis labels
PAD_R = 10   # right margin


class Trace:
    """One oscilloscope channel: numeric readout + rolling canvas plot.
    Canvas resizes with the window via the <Configure> event."""

    def __init__(self, parent, row, label, unit, color, y_min, y_max, fmt):
        self.color = color
        self.y_min = y_min
        self.y_max = y_max
        self.fmt   = fmt
        self.unit  = unit
        self.data  = deque([0.0] * HISTORY, maxlen=HISTORY)
        self.plot_w = PLOT_W
        self.plot_h = PLOT_H

        hdr = tk.Frame(parent, bg=BG)
        hdr.grid(row=row * 2, column=0, sticky="ew", padx=(8, 8), pady=(8, 0))
        tk.Label(hdr, text=label, font=FONT_LBL, fg=FGDM, bg=BG,
                 anchor="w").pack(side="left")
        self.val_lbl = tk.Label(hdr, text="---", font=FONT_VAL, fg=color,
                                bg=BG, anchor="e")
        self.val_lbl.pack(side="right")

        cw = self.plot_w + PAD + PAD_R
        self.canvas = tk.Canvas(parent, width=cw, height=self.plot_h,
                                bg=BG, highlightthickness=0)
        self.canvas.grid(row=row * 2 + 1, column=0, sticky="nsew",
                         padx=(8, 8), pady=(2, 0))
        self.canvas.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self.plot_w = max(120, event.width - PAD - PAD_R)
        self.plot_h = max(60, event.height)

    def push(self, value):
        if value is None:
            value = self.data[-1]
        self.data.append(value)
        self.val_lbl.config(text=f"{value:{self.fmt}} {self.unit}")

    def redraw(self):
        c = self.canvas
        c.delete("all")

        d_min = min(self.data)
        d_max = max(self.data)
        y_lo = min(self.y_min, d_min * 0.95) if d_min < self.y_min else self.y_min
        y_hi = max(self.y_max, d_max * 1.05) if d_max > self.y_max else self.y_max
        span = y_hi - y_lo if y_hi != y_lo else 1

        # grid lines + axis labels
        for i in range(GRID_LINES + 1):
            y = int(i * self.plot_h / GRID_LINES)
            c.create_line(PAD, y, PAD + self.plot_w, y, fill=GRID_CLR)
            val = y_hi - i * (y_hi - y_lo) / GRID_LINES
            c.create_text(PAD - 4, y, text=f"{val:{self.fmt}}",
                          anchor="e", fill=FGDM, font=FONT_AX)
        c.create_line(PAD, 0, PAD, self.plot_h, fill=GRID_CLR)

        # trace
        dx = self.plot_w / (HISTORY - 1)
        pts = []
        for i, v in enumerate(self.data):
            x = PAD + i * dx
            frac = (v - y_lo) / span
            y = self.plot_h - frac * self.plot_h
            y = max(0, min(self.plot_h, y))
            pts.append(x)
            pts.append(y)

        if len(pts) >= 4:
            c.create_line(*pts, fill=self.color, width=2, smooth=True)


# Top-level layout: row 0 = main (traces | soc | stats), row 1 = console.
root.grid_rowconfigure(0, weight=1)
root.grid_rowconfigure(1, weight=0)
root.grid_columnconfigure(0, weight=1)

main = tk.Frame(root, bg=BG)
main.grid(row=0, column=0, sticky="nsew")
main.grid_rowconfigure(0, weight=1)
main.grid_columnconfigure(0, weight=3)  # traces (expands)
main.grid_columnconfigure(1, weight=0)  # SOC bar (fixed-ish)
main.grid_columnconfigure(2, weight=2)  # stats panel (expands)

# --- Oscilloscope traces (left column) ---
trace_frame = tk.Frame(main, bg=BG)
trace_frame.grid(row=0, column=0, sticky="nsew")
trace_frame.grid_columnconfigure(0, weight=1)
for r in (1, 3, 5):
    trace_frame.grid_rowconfigure(r, weight=1)

tr_v = Trace(trace_frame, 0, "Voltage", "V", "#4fc3f7", 20.0, 30.0, ".2f")
tr_i = Trace(trace_frame, 1, "Current", "A", "#aed581",  0.0,  3.0, ".3f")
tr_p = Trace(trace_frame, 2, "Power",   "W", "#ffb74d",  0.0, 80.0, ".1f")

bot_frame = tk.Frame(trace_frame, bg=BG)
bot_frame.grid(row=6, column=0, sticky="ew", padx=(8, 8), pady=(6, 4))

rate_lbl = tk.Label(bot_frame, text="0 Hz", font=FONT_RATE, fg=FGDM, bg=BG)
rate_lbl.pack(side="left")

fs_btn = tk.Button(bot_frame, text="Fullscreen", font=FONT_REC,
                   fg=FGDM, bg="#333333", activebackground="#444444",
                   activeforeground=FG, highlightthickness=0,
                   bd=0, padx=12, pady=2)
fs_btn.pack(side="left", padx=(12, 0))


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

# --- SOC battery bar (middle column) ---
BAR_W      = 60
BAR_H_MIN  = 240
FONT_SOC   = ("Menlo", 28, "bold")
FONT_SOC_S = ("Menlo", 11)
FONT_ETA   = ("Menlo", 13)

soc_frame = tk.Frame(main, bg=BG)
soc_frame.grid(row=0, column=1, sticky="ns", padx=(4, 8), pady=(10, 0))

soc_lbl = tk.Label(soc_frame, text="---%", font=FONT_SOC, fg="#ce93d8", bg=BG)
soc_lbl.pack(pady=(0, 2))

eta_lbl = tk.Label(soc_frame, text="--:--", font=FONT_ETA, fg=FGDM, bg=BG)
eta_lbl.pack(pady=(0, 6))

soc_canvas = tk.Canvas(soc_frame, width=BAR_W, height=BAR_H_MIN,
                       bg=BG, highlightthickness=0)
soc_canvas.pack(fill="y", expand=True)

soc_sub_lbl = tk.Label(soc_frame, text="Charge", font=FONT_SOC_S,
                       fg=FGDM, bg=BG)
soc_sub_lbl.pack(pady=(4, 0))

soc_history = deque(maxlen=HISTORY)
cur_history = deque(maxlen=HISTORY)
vi_history  = deque(maxlen=HISTORY)  # paired (v, i) for live R_int regression

# R_int regression thresholds
RINT_MIN_SAMPLES = 30      # need at least this many paired samples
RINT_MIN_ISTD    = 0.030   # need >=30 mA std(I) for slope to be meaningful
RINT_MIN_R2      = 0.30    # below this R², treat the fit as untrustworthy
RINT_MIN_OHMS    = 0.001
RINT_MAX_OHMS    = 5.0


def soc_color(pct):
    if pct >= 60:
        return "#4caf50"
    elif pct >= 30:
        return "#ff9800"
    return "#f44336"


def redraw_soc_bar():
    """Redraw the filled portion of the SOC bar (averaged over window)."""
    soc = sum(soc_history) / len(soc_history) if soc_history else 0.0
    soc_canvas.delete("all")
    h = max(BAR_H_MIN, soc_canvas.winfo_height())
    w = max(BAR_W, soc_canvas.winfo_width())
    x0 = (w - BAR_W) // 2
    frac = max(0.0, min(1.0, soc / 100.0))
    fill_h = int(frac * h)
    if fill_h > 0:
        soc_canvas.create_rectangle(
            x0 + 1, h - fill_h, x0 + BAR_W - 1, h,
            fill=soc_color(soc), outline="")
    soc_canvas.create_rectangle(x0, 0, x0 + BAR_W, h,
                                outline="#444444", width=2)
    soc_lbl.config(text=f"{soc:.0f}%", fg=soc_color(soc))

    global ema_eta_hours
    avg_i = sum(cur_history) / len(cur_history) if cur_history else 0.0
    if avg_i > 0.01:
        raw_hours = (soc / 100.0) * CAPACITY_AH / avg_i
        if ema_eta_hours is None:
            ema_eta_hours = raw_hours
        else:
            smoothed = ETA_ALPHA * raw_hours + (1 - ETA_ALPHA) * ema_eta_hours
            ema_eta_hours = min(ema_eta_hours, smoothed)
        hh = int(ema_eta_hours)
        mm = int((ema_eta_hours - hh) * 60)
        eta_lbl.config(text=f"{hh}h {mm:02d}m")
    else:
        eta_lbl.config(text="--:--")


# --- Stats / readouts panel (right column) ---
stats_frame = tk.Frame(main, bg=BG_PANEL, padx=12, pady=10)
stats_frame.grid(row=0, column=2, sticky="nsew", padx=(0, 8), pady=(10, 0))


def _section(parent, title):
    tk.Label(parent, text=title, font=FONT_HDR, fg=FGDM, bg=BG_PANEL,
             anchor="w").pack(fill="x", pady=(6, 2))


def _stat_row(parent, key, init="—", val_fg=FG):
    row = tk.Frame(parent, bg=BG_PANEL)
    row.pack(fill="x", pady=1)
    tk.Label(row, text=key, font=FONT_STAT, fg=FGDM, bg=BG_PANEL,
             anchor="w", width=16).pack(side="left")
    val = tk.Label(row, text=init, font=FONT_STAT_B, fg=val_fg, bg=BG_PANEL,
                   anchor="e")
    val.pack(side="right", fill="x", expand=True)
    return val


_section(stats_frame, "NOW")
stat_now_v   = _stat_row(stats_frame, "Bus voltage",  val_fg="#4fc3f7")
stat_now_i   = _stat_row(stats_frame, "Current",      val_fg="#aed581")
stat_now_p   = _stat_row(stats_frame, "Power",        val_fg="#ffb74d")
stat_cellv   = _stat_row(stats_frame, "Cell voltage")
stat_shuntv  = _stat_row(stats_frame, "Shunt drop")
stat_rint    = _stat_row(stats_frame, "R_int (live)")
stat_rint_q  = _stat_row(stats_frame, "  fit R²")

_section(stats_frame, "SESSION")
stat_runtime = _stat_row(stats_frame, "Runtime")
stat_charge  = _stat_row(stats_frame, "Charge used")
stat_energy  = _stat_row(stats_frame, "Energy used")
stat_avg_p   = _stat_row(stats_frame, "Avg power")
stat_avg_i   = _stat_row(stats_frame, "Avg current")
stat_samples = _stat_row(stats_frame, "Samples")
stat_errors  = _stat_row(stats_frame, "I2C errors")

_section(stats_frame, "MIN / MAX")
stat_v_range = _stat_row(stats_frame, "Voltage")
stat_i_range = _stat_row(stats_frame, "Current")
stat_p_range = _stat_row(stats_frame, "Power")

_section(stats_frame, "CONFIG")
_stat_row(stats_frame, "R_shunt",    f"{R_SHUNT*1000:.1f} mΩ")
_stat_row(stats_frame, "Capacity",   f"{CAPACITY_AH:.2f} Ah")
_stat_row(stats_frame, "Cells (S)",  f"{CELLS_SERIES}")
_stat_row(stats_frame, "Current LSB", f"{CURRENT_LSB*1e6:.0f} µA")
_stat_row(stats_frame, "R_internal", f"{R_INTERNAL*1000:.0f} mΩ")
_stat_row(stats_frame, "INA addr",   f"0x{INA:02X}")

# --- Console log (bottom, spans full width) ---
console_frame = tk.Frame(root, bg=BG)
console_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))

console_hdr = tk.Frame(console_frame, bg=BG)
console_hdr.pack(fill="x")
tk.Label(console_hdr, text="CONSOLE", font=FONT_HDR, fg=FGDM, bg=BG,
         anchor="w").pack(side="left")


def _clear_console():
    console_text.configure(state="normal")
    console_text.delete("1.0", "end")
    console_text.configure(state="disabled")


clear_btn = tk.Button(console_hdr, text="Clear", font=("Menlo", 9),
                      fg=FGDM, bg="#333333", activebackground="#444444",
                      activeforeground=FG, highlightthickness=0,
                      bd=0, padx=8, pady=0, command=_clear_console)
clear_btn.pack(side="right")

console_inner = tk.Frame(console_frame, bg=BG)
console_inner.pack(fill="both", expand=True, pady=(4, 0))

console_text = tk.Text(console_inner, height=8, bg="#141414", fg="#cfcfcf",
                       font=FONT_LOG, insertbackground=FG,
                       highlightthickness=0, bd=0, wrap="none")
console_scroll = tk.Scrollbar(console_inner, orient="vertical",
                              command=console_text.yview)
console_text.configure(yscrollcommand=console_scroll.set)
console_text.pack(side="left", fill="both", expand=True)
console_scroll.pack(side="right", fill="y")
console_text.tag_configure("info", foreground="#9fb8d0")
console_text.tag_configure("warn", foreground="#ffb74d")
console_text.tag_configure("err",  foreground="#ef5350")
console_text.tag_configure("ok",   foreground="#aed581")
console_text.configure(state="disabled")


def log_console(msg, tag="info"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)  # also echo to stderr/stdout for the launching terminal
    console_text.configure(state="normal")
    console_text.insert("end", line + "\n", tag)
    n = int(console_text.index("end-1c").split(".")[0])
    if n > 500:
        console_text.delete("1.0", f"{n - 500}.0")
    console_text.see("end")
    console_text.configure(state="disabled")


# --- Fullscreen toggle ---
_is_fullscreen = False


def toggle_fullscreen(event=None):
    global _is_fullscreen
    _is_fullscreen = not _is_fullscreen
    root.attributes("-fullscreen", _is_fullscreen)
    fs_btn.config(text="Windowed" if _is_fullscreen else "Fullscreen")
    log_console("Entered fullscreen" if _is_fullscreen else "Exited fullscreen")


def exit_fullscreen(event=None):
    global _is_fullscreen
    if _is_fullscreen:
        _is_fullscreen = False
        root.attributes("-fullscreen", False)
        fs_btn.config(text="Fullscreen")
        log_console("Exited fullscreen")


fs_btn.config(command=toggle_fullscreen)
root.bind("<F11>", toggle_fullscreen)
root.bind("<Command-f>", toggle_fullscreen)
root.bind("<Escape>", exit_fullscreen)

# --- Rate / ETA state ---
last_rate_time  = time.time()
last_rate_count = 0
ETA_ALPHA       = 0.05
ema_eta_hours   = None

# Notable-event triggers for the console
_last_error_logged = 0
_peak_current_announced = 0.0
_low_soc_announced = False


def _fmt_duration(secs):
    secs = int(secs)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def update_gui():
    """Drain sample buffer into traces and redraw (called at 20 Hz)."""
    global last_rate_time, last_rate_count
    global _last_error_logged, _peak_current_announced, _low_soc_announced

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
        if i is not None:
            cur_history.append(i)
        if v is not None and i is not None:
            vi_history.append((v, i))

    tr_v.redraw()
    tr_i.redraw()
    tr_p.redraw()

    now = time.time()
    redraw_soc_bar()

    dt = now - last_rate_time
    if dt >= 1.0:
        rate = (total - last_rate_count) / dt
        rate_lbl.config(text=f"{rate:.0f} Hz")
        last_rate_time  = now
        last_rate_count = total

    # --- Stats panel ---
    runtime = now - t_start
    v_now, i_now, p_now, soc_now = latest

    if v_now is not None:
        stat_now_v.config(text=f"{v_now:.3f} V")
        stat_cellv.config(text=f"{(v_now/CELLS_SERIES)*1000:.0f} mV")
    if i_now is not None:
        stat_now_i.config(text=f"{i_now*1000:.0f} mA")
        # shunt voltage = I * R_shunt
        stat_shuntv.config(text=f"{i_now*R_SHUNT*1e6:.0f} µV")
    if p_now is not None:
        stat_now_p.config(text=f"{p_now:.2f} W")

    stat_runtime.config(text=_fmt_duration(runtime))
    stat_charge.config(text=f"{total_charge_as/3600:.4f} Ah")
    stat_energy.config(text=f"{total_energy_ws/3600:.3f} Wh")
    if runtime > 0:
        stat_avg_p.config(text=f"{total_energy_ws/runtime:.2f} W")
        stat_avg_i.config(text=f"{(total_charge_as/runtime)*1000:.0f} mA")
    stat_samples.config(text=f"{total}")
    stat_errors.config(text=f"{read_errors}",
                       fg="#ef5350" if read_errors else FG)

    if v_min is not None:
        stat_v_range.config(text=f"{v_min:.2f} / {v_max:.2f} V")
    if i_min is not None:
        stat_i_range.config(text=f"{i_min:.3f} / {i_max:.3f} A")
    if p_min is not None:
        stat_p_range.config(text=f"{p_min:.1f} / {p_max:.1f} W")

    # --- Live R_int via ΔV/ΔI linear regression over the sliding window ---
    n = len(vi_history)
    rint_ohms = None
    rint_r2 = None
    if n >= RINT_MIN_SAMPLES:
        sum_v = sum_i = 0.0
        for vv, ii in vi_history:
            sum_v += vv
            sum_i += ii
        mean_v = sum_v / n
        mean_i = sum_i / n
        cov_vi = 0.0
        var_i  = 0.0
        var_v  = 0.0
        for vv, ii in vi_history:
            dv = vv - mean_v
            di = ii - mean_i
            cov_vi += dv * di
            var_i  += di * di
            var_v  += dv * dv
        std_i = (var_i / n) ** 0.5
        if std_i >= RINT_MIN_ISTD and var_i > 0 and var_v > 0:
            slope = cov_vi / var_i           # V = slope * I + intercept
            r2    = (cov_vi * cov_vi) / (var_i * var_v)
            r_est = -slope                   # R_int = -dV/dI
            if RINT_MIN_OHMS <= r_est <= RINT_MAX_OHMS and r2 >= RINT_MIN_R2:
                rint_ohms = r_est
                rint_r2   = r2

    if rint_ohms is not None:
        stat_rint.config(text=f"{rint_ohms*1000:.0f} mΩ", fg=FG)
        stat_rint_q.config(text=f"{rint_r2:.2f}", fg=FG)
    else:
        # not enough current variation (or poor fit) — grey out
        stat_rint.config(text="—", fg=FGDM)
        stat_rint_q.config(text="—", fg=FGDM)

    # --- Notable-event detection -> console log ---
    # New I2C errors since last announce
    if read_errors > _last_error_logged and read_errors - _last_error_logged >= 5:
        log_console(f"I2C read errors: {read_errors} total", "warn")
        _last_error_logged = read_errors

    # Peak current (announce every 0.5 A above prior peak)
    if i_max is not None and i_max >= _peak_current_announced + 0.5:
        log_console(f"New peak current: {i_max:.3f} A", "warn")
        _peak_current_announced = i_max

    # Low SOC warning
    if soc_now is not None and soc_now < 15 and not _low_soc_announced:
        log_console(f"Low SOC: {soc_now:.1f}%", "warn")
        _low_soc_announced = True
    elif soc_now is not None and soc_now > 25 and _low_soc_announced:
        _low_soc_announced = False  # rearm hysteresis

    root.after(GUI_MS, update_gui)


def csv_tick():
    """Write one row to CSV at 10 Hz when recording."""
    if recording and csv_writer is not None:
        with buf_lock:
            v, i, p, soc = latest
        ts = int((time.time() - t_start) * 1e9)
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

log_console("INA226 monitor started", "ok")
log_console(f"I2C @ 400 kHz · CAL={CAL_VALUE} · LSB={CURRENT_LSB*1e6:.0f} µA · "
            f"R_shunt={R_SHUNT*1000:.1f} mΩ")
log_console("F11 or ⌘F toggles fullscreen · Esc exits fullscreen")

sample_thread = threading.Thread(target=sample_loop, daemon=True)
sample_thread.start()
update_gui()
csv_tick()
root.mainloop()
