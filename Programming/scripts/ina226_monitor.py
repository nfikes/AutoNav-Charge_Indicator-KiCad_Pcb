"""INA226 Real-Time Monitor GUI
Displays bus voltage, current, and power from the INA226 (U3)
using the Aardvark I2C adapter with oscilloscope-style rolling plots.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array
import tkinter as tk
from collections import deque

# --- INA226 constants ---
INA  = 0x40
REG_BUS_V   = 0x02
REG_POWER   = 0x03
REG_CURRENT = 0x04
REG_CAL     = 0x05

R_SHUNT      = 0.010        # 10 mΩ
CURRENT_LSB  = 0.00025      # 250 µA/bit
POWER_LSB    = 25 * CURRENT_LSB  # 6.25 mW/bit
CAL_VALUE    = int(0.00512 / (CURRENT_LSB * R_SHUNT))  # 2048

POLL_MS    = 250   # refresh interval (ms)
HISTORY    = 200   # number of samples visible on screen
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
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(200)

cal_msb = (CAL_VALUE >> 8) & 0xFF
cal_lsb = CAL_VALUE & 0xFF
aa_i2c_write(handle, INA, AA_I2C_NO_FLAGS,
             array('B', [REG_CAL, cal_msb, cal_lsb]))


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
                          anchor="e", fill=FGDM, font=FONT_AX)
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


def poll():
    raw_v = read_u16(handle, INA, REG_BUS_V)
    raw_i = read_s16(handle, INA, REG_CURRENT)
    raw_p = read_u16(handle, INA, REG_POWER)

    tr_v.push(raw_v * 1.25e-3 if raw_v is not None else None)
    tr_i.push(raw_i * CURRENT_LSB if raw_i is not None else None)
    tr_p.push(raw_p * POWER_LSB if raw_p is not None else None)

    tr_v.redraw()
    tr_i.redraw()
    tr_p.redraw()

    root.after(POLL_MS, poll)


def on_close():
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)
poll()
root.mainloop()
