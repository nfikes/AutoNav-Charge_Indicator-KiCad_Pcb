"""INA226 Real-Time Monitor GUI
Displays bus voltage, current, and power from the INA226 (U3)
using the Aardvark I2C adapter with oscilloscope-style rolling plots.

Sampling runs in a dedicated thread at maximum I2C speed (~500+ Hz at
400 kHz fast-mode).  The GUI refreshes at 20 Hz and shows the last
HISTORY samples.  Every sample is logged to a timestamped CSV in
the outputs/ folder.
"""
import sys, os, csv, time, threading
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array
import tkinter as tk
from collections import deque

# --- INA226 constants ---
INA  = 0x40
REG_CONFIG  = 0x00
REG_BUS_V   = 0x02
REG_POWER   = 0x03
REG_CURRENT = 0x04
REG_CAL     = 0x05

R_SHUNT      = 0.010        # 10 mOhm
CURRENT_LSB  = 0.00025      # 250 uA/bit
POWER_LSB    = 25 * CURRENT_LSB  # 6.25 mW/bit
CAL_VALUE    = int(0.00512 / (CURRENT_LSB * R_SHUNT))  # 2048

# INA226 config: AVG=1, VBUSCT=140us, VSHCT=140us, continuous shunt+bus
# Bits: 0 100 000 000 000 111 = 0x4007
CONFIG_FAST  = 0x4007

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
handle = aa_open(0)
if handle <= 0:
    print(f"ERROR: Cannot open Aardvark (error {handle})")
    sys.exit(1)
aa_configure(handle, AA_CONFIG_SPI_I2C)
actual_bitrate = aa_i2c_bitrate(handle, 400)   # 400 kHz fast-mode
print(f"I2C bitrate set to {actual_bitrate} kHz")
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(200)

# Configure for fastest conversion (140us bus + shunt, no averaging)
cfg_msb = (CONFIG_FAST >> 8) & 0xFF
cfg_lsb = CONFIG_FAST & 0xFF
aa_i2c_write(handle, INA, AA_I2C_NO_FLAGS,
             array('B', [REG_CONFIG, cfg_msb, cfg_lsb]))

cal_msb = (CAL_VALUE >> 8) & 0xFF
cal_lsb = CAL_VALUE & 0xFF
aa_i2c_write(handle, INA, AA_I2C_NO_FLAGS,
             array('B', [REG_CAL, cal_msb, cal_lsb]))

# --- CSV logging (deferred until sample rate is measured) ---
out_base = os.path.join(os.path.dirname(__file__), "..", "outputs")
csv_file   = None
csv_writer = None
csv_path   = None
t_start    = time.time()

# --- Shared state between sampling thread and GUI ---
buf_lock   = threading.Lock()
buf_samples = []        # list of (v, i, p) accumulated between GUI frames
sample_count = 0        # total samples taken (for rate calc)
sampling   = True       # flag to stop the thread


def _open_csv(rate_hz):
    """Create the rate-named subfolder and open the CSV file."""
    global csv_file, csv_writer, csv_path
    folder = os.path.join(out_base, f"{rate_hz}hz")
    os.makedirs(folder, exist_ok=True)
    csv_name = datetime.now().strftime("ina226_%Y%m%d_%H%M%S.csv")
    csv_path = os.path.join(folder, csv_name)
    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["timestamp", "voltage_V", "current_A", "power_W"])
    print(f"Logging to {csv_path}")


def sample_loop():
    """Tight loop — reads all 3 registers back-to-back, writes CSV."""
    global sample_count
    warmup_start = time.time()
    warmup_count = 0
    csv_ready = False
    pending_rows = []      # buffer rows during warm-up

    while sampling:
        raw_v = read_u16(handle, INA, REG_BUS_V)
        raw_i = read_s16(handle, INA, REG_CURRENT)
        raw_p = read_u16(handle, INA, REG_POWER)

        v = raw_v * 1.25e-3 if raw_v is not None else None
        i = raw_i * CURRENT_LSB if raw_i is not None else None
        p = raw_p * POWER_LSB if raw_p is not None else None

        ts = time.time() - t_start
        row = [f"{ts:.4f}",
               f"{v:.4f}" if v is not None else "",
               f"{i:.5f}" if i is not None else "",
               f"{p:.3f}" if p is not None else ""]

        if not csv_ready:
            pending_rows.append(row)
            warmup_count += 1
            if time.time() - warmup_start >= 1.0:
                rate = int(round(warmup_count / (time.time() - warmup_start)))
                _open_csv(rate)
                for r in pending_rows:
                    csv_writer.writerow(r)
                pending_rows = None
                csv_ready = True
        else:
            csv_writer.writerow(row)

        with buf_lock:
            buf_samples.append((v, i, p))
            sample_count += 1


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

tr_v = Trace(frame, 0, "Voltage", "V",  "#4fc3f7", 20.0, 30.0, ".2f")
tr_i = Trace(frame, 1, "Current", "A",  "#aed581",  0.0,  3.0, ".3f")
tr_p = Trace(frame, 2, "Power",   "W",  "#ffb74d",  0.0, 80.0, ".1f")

# sample-rate label at the bottom
rate_lbl = tk.Label(frame, text="0 Hz", font=FONT_RATE, fg=FGDM, bg=BG)
rate_lbl.grid(row=6, column=0, sticky="e", padx=(0, 18), pady=(6, 0))

last_rate_time  = time.time()
last_rate_count = 0


def update_gui():
    """Drain sample buffer into traces and redraw (called at 20 Hz)."""
    global last_rate_time, last_rate_count

    with buf_lock:
        new_samples = list(buf_samples)
        buf_samples.clear()
        total = sample_count

    for v, i, p in new_samples:
        tr_v.push(v)
        tr_i.push(i)
        tr_p.push(p)

    tr_v.redraw()
    tr_i.redraw()
    tr_p.redraw()

    # Update rate display every ~1 s
    now = time.time()
    dt = now - last_rate_time
    if dt >= 1.0:
        rate = (total - last_rate_count) / dt
        rate_lbl.config(text=f"{rate:.0f} Hz")
        last_rate_time  = now
        last_rate_count = total

    root.after(GUI_MS, update_gui)


def on_close():
    global sampling
    sampling = False
    sample_thread.join(timeout=1.0)
    elapsed = time.time() - t_start
    if csv_file is not None:
        csv_file.close()
        print(f"CSV saved: {csv_path}")
        print(f"  {sample_count} samples in {elapsed:.1f}s "
              f"({sample_count/elapsed:.0f} Hz avg)")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)

# Start sampling thread, then GUI loop
sample_thread = threading.Thread(target=sample_loop, daemon=True)
sample_thread.start()
update_gui()
root.mainloop()
