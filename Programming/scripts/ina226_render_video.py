"""INA226 GUI Recreation -> MP4 (Pillow renderer).

Pixel-accurate recreation of the ina226_monitor.py Tk GUI. Draws each
frame with Pillow at 1280x780 using the same Menlo point sizes and
exact layout as the Tk widget tree, then pipes RGB frames into ffmpeg
to produce an MP4.

Default replay: outputs/50hz/ina226_20260304_174552.csv, t=3 -> 13 s.
Override with --csv / --start / --duration / --fps / --output.
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
from collections import deque
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFont


# --- INA226 / pack constants (mirror ina226_monitor.py) -------------------
R_SHUNT      = 0.010
CURRENT_LSB  = 0.00025
CAL_VALUE    = 2048
CELLS_SERIES = 8
CAPACITY_AH  = 20.476
CAPACITY_AS  = CAPACITY_AH * 3600
R_INTERNAL   = 0.060
INA_ADDR     = 0x40

LFP_SOC_TABLE = [
    (3323, 100), (3322, 97.5), (3321, 95), (3320, 90), (3319, 85),
    (3318, 80),  (3313, 75),   (3307, 70), (3290, 65), (3288, 60),
    (3287, 55),  (3284, 50),   (3281, 45), (3276, 40), (3269, 35),
    (3260, 30),  (3248, 25),   (3232, 20), (3211, 15), (3196, 10),
    (3179, 7.5), (3138, 5),    (3044, 2.5), (2922, 0),
]

ETA_ALPHA        = 0.05
RINT_MIN_SAMPLES = 30
RINT_MIN_ISTD    = 0.030
RINT_MIN_R2      = 0.30
RINT_MIN_OHMS    = 0.001
RINT_MAX_OHMS    = 5.0

HISTORY = 500
GRID_LINES = 4

# --- Visual theme ---------------------------------------------------------
BG         = (0x1e, 0x1e, 0x1e)
BG_PANEL   = (0x25, 0x25, 0x25)
BG_CONSOLE = (0x14, 0x14, 0x14)
BG_BTN     = (0x33, 0x33, 0x33)
GRID_CLR   = (0x2a, 0x2a, 0x2a)
FGDM       = (0x88, 0x88, 0x88)
FG         = (0xdd, 0xdd, 0xdd)
FG_LOG     = (0xcf, 0xcf, 0xcf)
BAR_OUT    = (0x44, 0x44, 0x44)
C_V        = (0x4f, 0xc3, 0xf7)
C_I        = (0xae, 0xd5, 0x81)
C_P        = (0xff, 0xb7, 0x4d)
C_PURPLE   = (0xce, 0x93, 0xd8)
C_SOC_HI   = (0x4c, 0xaf, 0x50)
C_SOC_MID  = (0xff, 0x98, 0x00)
C_SOC_LO   = (0xf4, 0x43, 0x36)
C_INFO     = (0x9f, 0xb8, 0xd0)
C_WARN     = (0xff, 0xb7, 0x4d)
C_ERR      = (0xef, 0x53, 0x50)
C_OK       = (0xae, 0xd5, 0x81)

# --- Font loading (Menlo @ Tk's point sizes) ------------------------------
MENLO_PATH = "/System/Library/Fonts/Menlo.ttc"
IDX_REGULAR, IDX_BOLD = 0, 1


def _font(pt, bold=False):
    return ImageFont.truetype(MENLO_PATH, size=pt,
                              index=IDX_BOLD if bold else IDX_REGULAR)


# Match Tk font sizes in ina226_monitor.py
F_LBL     = _font(12)
F_VAL     = _font(22, bold=True)
F_AX      = _font(9)
F_RATE    = _font(10)
F_STAT    = _font(11)
F_STAT_B  = _font(11, bold=True)
F_HDR     = _font(11, bold=True)
F_LOG     = _font(10)
F_REC     = _font(11, bold=True)
F_SOC     = _font(28, bold=True)
F_SOC_S   = _font(11)
F_ETA     = _font(13)

# --- Layout (px positions; mirror Tk widget tree at 1280x780) -------------
W, H = 1280, 780

# Bottom console band
CONSOLE_PAD   = 8
CONSOLE_HDR_H = 18
CONSOLE_TXT_H = 8 * 14 + 10   # 8 lines @ ~14 px line height + padding
CONSOLE_H     = CONSOLE_HDR_H + CONSOLE_TXT_H + 12  # = ~132
CONSOLE_TOP   = H - CONSOLE_H - CONSOLE_PAD
CONSOLE_BOT   = H - CONSOLE_PAD
CONSOLE_X0    = CONSOLE_PAD
CONSOLE_X1    = W - CONSOLE_PAD
CONSOLE_TXT_Y0 = CONSOLE_TOP + CONSOLE_HDR_H + 4
CONSOLE_TXT_Y1 = CONSOLE_BOT

# Top section: three columns
TOP_BOT = CONSOLE_TOP - 4

# Column widths: Tk weights are 3:0:2 with SOC fixed-ish
SOC_COL_W = 100
TRACES_COL_W = int((W - SOC_COL_W) * 3 / 5)  # ~708
STATS_COL_W  = W - SOC_COL_W - TRACES_COL_W  # ~472

TRACES_X0 = 0
TRACES_X1 = TRACES_COL_W
SOC_X0    = TRACES_X1
SOC_X1    = SOC_X0 + SOC_COL_W
STATS_X0  = SOC_X1
STATS_X1  = W

# Trace area
TRACE_LEFT_PAD  = 8
TRACE_RIGHT_PAD = 8
TRACE_TOP_PAD   = 8

# Bot frame (rate + buttons) inside trace column at bottom
BOT_FRAME_H = 26
BOT_FRAME_Y = TOP_BOT - BOT_FRAME_H - 4

# Three traces above bot_frame
TRACES_AREA_TOP = TRACE_TOP_PAD
TRACES_AREA_BOT = BOT_FRAME_Y - 4

# Each trace: header row + canvas row
TRACE_HDR_H = 30
N_TRACES = 3
_AREA = TRACES_AREA_BOT - TRACES_AREA_TOP
_PER_TRACE = _AREA / N_TRACES
TRACE_CANVAS_H = int(_PER_TRACE - TRACE_HDR_H - 2)

# Canvas-internal: PAD for left axis labels, PAD_R for right margin
PAD   = 40
PAD_R = 10

# SOC column layout
SOC_BAR_W      = 60
SOC_HEADER_TOP = 10
SOC_PCT_H      = 36
SOC_ETA_H      = 16

# Stats panel
STATS_PAD_X = 12
STATS_PAD_Y = 10
STATS_ROW_H = 18
STATS_SECT_PAD_TOP = 6
STATS_SECT_PAD_BOT = 2

DEFAULT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "outputs", "50hz", "ina226_20260304_174552.csv",
)


# --- Helpers --------------------------------------------------------------
def voltage_to_soc(bus_v):
    cell_mv = (bus_v * 1000.0) / CELLS_SERIES
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


def soc_color(pct):
    if pct >= 60: return C_SOC_HI
    if pct >= 30: return C_SOC_MID
    return C_SOC_LO


def fmt_duration(secs):
    secs = int(secs)
    h = secs // 3600; m = (secs % 3600) // 60; s = secs % 60
    if h: return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def load_csv(path):
    ts, V, I, P = [], [], [], []
    with open(path) as fp:
        for row in csv.DictReader(fp):
            try:
                ts.append(float(row["timestamp"]))
                V.append(float(row["voltage_V"]))
                I.append(float(row["current_A"]))
                P.append(float(row["power_W"]))
            except Exception:
                continue
    return np.asarray(ts), np.asarray(V), np.asarray(I), np.asarray(P)


def text_size(font, text):
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# --- Trace drawing --------------------------------------------------------
def draw_trace(draw, x0, y0, w, h, data, color, label, value_text,
               y_min_init, y_max_init, fmt):
    """Draws one oscilloscope channel: header row, then canvas with grid + line.
    Exactly mirrors the Tk Trace class in ina226_monitor.py."""
    # Header row: label (left) + big numeric value (right)
    hdr_x0 = x0 + TRACE_LEFT_PAD
    hdr_x1 = x0 + w - TRACE_RIGHT_PAD
    # Label (anchor lt)
    draw.text((hdr_x0, y0 + 4), label, font=F_LBL, fill=FGDM)
    # Value (anchor right)
    vw, _ = text_size(F_VAL, value_text)
    draw.text((hdr_x1 - vw, y0), value_text, font=F_VAL, fill=color)

    # Canvas area
    cv_x0 = x0 + TRACE_LEFT_PAD
    cv_y0 = y0 + TRACE_HDR_H
    cv_x1 = x0 + w - TRACE_RIGHT_PAD
    cv_y1 = cv_y0 + h - TRACE_HDR_H
    plot_w = (cv_x1 - cv_x0) - PAD - PAD_R
    plot_h = cv_y1 - cv_y0
    plot_x0 = cv_x0 + PAD

    # Adaptive y limits (matches Trace.redraw())
    d_min = min(data); d_max = max(data)
    y_lo = min(y_min_init, d_min * 0.95) if d_min < y_min_init else y_min_init
    y_hi = max(y_max_init, d_max * 1.05) if d_max > y_max_init else y_max_init
    span = y_hi - y_lo if y_hi != y_lo else 1.0

    # Horizontal gridlines + Y axis labels (GRID_LINES+1 lines)
    for i in range(GRID_LINES + 1):
        y = cv_y0 + int(i * plot_h / GRID_LINES)
        draw.line([(plot_x0, y), (plot_x0 + plot_w, y)], fill=GRID_CLR)
        val = y_hi - i * (y_hi - y_lo) / GRID_LINES
        ltxt = f"{val:{fmt}}"
        lw, lh = text_size(F_AX, ltxt)
        draw.text((plot_x0 - 4 - lw, y - lh // 2), ltxt, font=F_AX, fill=FGDM)
    # Vertical line at PAD (left edge of plot)
    draw.line([(plot_x0, cv_y0), (plot_x0, cv_y1)], fill=GRID_CLR)

    # Trace polyline
    n = len(data)
    if n >= 2:
        dx = plot_w / (HISTORY - 1)
        pts = []
        for i, v in enumerate(data):
            x = plot_x0 + i * dx
            frac = (v - y_lo) / span
            y = cv_y1 - frac * plot_h
            if y < cv_y0: y = cv_y0
            if y > cv_y1: y = cv_y1
            pts.append((x, y))
        draw.line(pts, fill=color, width=2, joint="curve")


# --- Stats panel drawing --------------------------------------------------
class StatsPanel:
    """Mirrors the right-side stats frame in the Tk app."""

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.now = {}
        self.session = {}
        self.range = {}

    def _row(self, draw, y, key, value, val_color=FG, val_bold=True):
        kx = self.x0 + STATS_PAD_X
        vx = self.x1 - STATS_PAD_X
        draw.text((kx, y), key, font=F_STAT, fill=FGDM)
        f = F_STAT_B if val_bold else F_STAT
        vw, _ = text_size(f, value)
        draw.text((vx - vw, y), value, font=f, fill=val_color)
        return y + STATS_ROW_H

    def _section(self, draw, y, title):
        y += STATS_SECT_PAD_TOP
        draw.text((self.x0 + STATS_PAD_X, y), title, font=F_HDR, fill=FGDM)
        return y + 14 + STATS_SECT_PAD_BOT

    def draw(self, draw, s):
        # Background fill (the whole right column)
        draw.rectangle([(self.x0, self.y0), (self.x1, self.y1)],
                       fill=BG_PANEL)

        y = self.y0 + STATS_PAD_Y

        y = self._section(draw, y, "NOW")
        y = self._row(draw, y, "Bus voltage",  s["now_v"],   val_color=C_V)
        y = self._row(draw, y, "Current",      s["now_i"],   val_color=C_I)
        y = self._row(draw, y, "Power",        s["now_p"],   val_color=C_P)
        y = self._row(draw, y, "Cell voltage", s["cellv"])
        y = self._row(draw, y, "Shunt drop",   s["shuntv"])
        y = self._row(draw, y, "R_int (live)", s["rint"],
                      val_color=s["rint_col"])
        y = self._row(draw, y, "  fit R²",     s["rint_r2"],
                      val_color=s["rint_col"])

        y = self._section(draw, y, "SESSION")
        y = self._row(draw, y, "Runtime",     s["runtime"])
        y = self._row(draw, y, "Charge used", s["charge"])
        y = self._row(draw, y, "Energy used", s["energy"])
        y = self._row(draw, y, "Avg power",   s["avg_p"])
        y = self._row(draw, y, "Avg current", s["avg_i"])
        y = self._row(draw, y, "Samples",     s["samples"])
        y = self._row(draw, y, "I2C errors",  s["errors"],
                      val_color=s["errors_col"])

        y = self._section(draw, y, "MIN / MAX")
        y = self._row(draw, y, "Voltage", s["v_range"])
        y = self._row(draw, y, "Current", s["i_range"])
        y = self._row(draw, y, "Power",   s["p_range"])

        y = self._section(draw, y, "CONFIG")
        y = self._row(draw, y, "R_shunt",     f"{R_SHUNT*1000:.1f} mΩ")
        y = self._row(draw, y, "Capacity",    f"{CAPACITY_AH:.2f} Ah")
        y = self._row(draw, y, "Cells (S)",   f"{CELLS_SERIES}")
        y = self._row(draw, y, "Current LSB", f"{CURRENT_LSB*1e6:.0f} µA")
        y = self._row(draw, y, "R_internal",  f"{R_INTERNAL*1000:.0f} mΩ")
        y = self._row(draw, y, "INA addr",    f"0x{INA_ADDR:02X}")


# --- SOC column drawing ---------------------------------------------------
def draw_soc(draw, soc_pct, eta_text):
    # Percentage label (large, centered)
    soc_text = f"{soc_pct:.0f}%"
    color = soc_color(soc_pct)
    tw, _ = text_size(F_SOC, soc_text)
    cx = (SOC_X0 + SOC_X1) // 2
    soc_pct_y = SOC_HEADER_TOP
    draw.text((cx - tw // 2, soc_pct_y), soc_text, font=F_SOC, fill=color)

    # ETA label
    ew, _ = text_size(F_ETA, eta_text)
    eta_y = soc_pct_y + SOC_PCT_H
    draw.text((cx - ew // 2, eta_y), eta_text, font=F_ETA, fill=FGDM)

    # Bar
    bar_top = eta_y + SOC_ETA_H + 8
    bar_bot = TOP_BOT - 30  # leave room for "Charge" sublabel
    bar_x0 = cx - SOC_BAR_W // 2
    bar_x1 = cx + SOC_BAR_W // 2
    # Outline
    draw.rectangle([(bar_x0, bar_top), (bar_x1, bar_bot)],
                   outline=BAR_OUT, width=2)
    # Fill (from bottom up)
    frac = max(0.0, min(1.0, soc_pct / 100.0))
    bar_h = bar_bot - bar_top
    fill_h = int(frac * bar_h)
    if fill_h > 0:
        draw.rectangle([(bar_x0 + 2, bar_bot - fill_h),
                        (bar_x1 - 1, bar_bot - 1)], fill=color)

    # "Charge" sublabel
    sub = "Charge"
    sw, _ = text_size(F_SOC_S, sub)
    draw.text((cx - sw // 2, bar_bot + 6), sub, font=F_SOC_S, fill=FGDM)


# --- Console drawing ------------------------------------------------------
def draw_console(draw, log_lines):
    # Header bar with "CONSOLE" label + "Clear" button
    hdr_y = CONSOLE_TOP
    draw.text((CONSOLE_X0 + 4, hdr_y), "CONSOLE", font=F_HDR, fill=FGDM)

    # Clear button (right-aligned, small)
    btn_text = " Clear "
    bw, bh = text_size(F_AX, btn_text)
    bx1 = CONSOLE_X1 - 2
    bx0 = bx1 - bw - 8
    by0 = hdr_y - 2
    by1 = by0 + bh + 4
    draw.rectangle([(bx0, by0), (bx1, by1)], fill=BG_BTN)
    draw.text((bx0 + 4, by0 + 2), "Clear", font=F_AX, fill=FGDM)

    # Console text body
    body_y0 = CONSOLE_TXT_Y0
    body_y1 = CONSOLE_TXT_Y1
    draw.rectangle([(CONSOLE_X0, body_y0), (CONSOLE_X1, body_y1)],
                   fill=BG_CONSOLE)

    # Lines: render oldest at top, newest at bottom (Tk autoscroll behavior).
    # log_lines is a list of (text, color) with newest LAST.
    line_h = 14
    max_lines = (body_y1 - body_y0 - 8) // line_h
    visible = log_lines[-max_lines:] if max_lines > 0 else []
    for k, (line, col) in enumerate(visible):
        y = body_y0 + 4 + k * line_h
        draw.text((CONSOLE_X0 + 6, y), line, font=F_LOG, fill=col)


# --- Bot frame (rate label + buttons) -------------------------------------
def draw_bot_frame(draw, rate_text):
    y = BOT_FRAME_Y
    x = TRACES_X0 + TRACE_LEFT_PAD

    # Rate label, left
    draw.text((x, y + 4), rate_text, font=F_RATE, fill=FGDM)
    rw, _ = text_size(F_RATE, rate_text)

    # Fullscreen button (next to rate)
    fx0 = x + rw + 12
    fs_text = "Fullscreen"
    fw, fh = text_size(F_REC, fs_text)
    fx1 = fx0 + fw + 24
    draw.rectangle([(fx0, y), (fx1, y + BOT_FRAME_H - 2)], fill=BG_BTN)
    draw.text((fx0 + 12, y + (BOT_FRAME_H - fh) // 2 - 2),
              fs_text, font=F_REC, fill=FGDM)

    # Record button, right
    rec_text = "Record"
    rw2, rh2 = text_size(F_REC, rec_text)
    rx1 = TRACES_X1 - TRACE_RIGHT_PAD
    rx0 = rx1 - rw2 - 24
    draw.rectangle([(rx0, y), (rx1, y + BOT_FRAME_H - 2)], fill=BG_BTN)
    draw.text((rx0 + 12, y + (BOT_FRAME_H - rh2) // 2 - 2),
              rec_text, font=F_REC, fill=C_OK)


# --- Frame composer -------------------------------------------------------
def render_frame(state, rate_text, log_lines):
    img = Image.new("RGB", (W, H), BG)
    d   = ImageDraw.Draw(img)

    # Trace column (3 stacked traces + bot frame)
    trace_y = TRACES_AREA_TOP
    trace_w = TRACES_COL_W
    each_h = int(_PER_TRACE)

    def cur_val(hist, fmt, unit):
        v = hist[-1]
        return f"{v:{fmt}} {unit}"

    draw_trace(d, TRACES_X0, trace_y, trace_w, each_h,
               list(state["hist_v"]), C_V,
               "Voltage", cur_val(state["hist_v"], ".2f", "V"),
               20.0, 30.0, ".2f")
    trace_y += each_h

    draw_trace(d, TRACES_X0, trace_y, trace_w, each_h,
               list(state["hist_i"]), C_I,
               "Current", cur_val(state["hist_i"], ".3f", "A"),
               0.0, 3.0, ".3f")
    trace_y += each_h

    draw_trace(d, TRACES_X0, trace_y, trace_w, each_h,
               list(state["hist_p"]), C_P,
               "Power",   cur_val(state["hist_p"], ".1f", "W"),
               0.0, 80.0, ".1f")

    draw_bot_frame(d, rate_text)

    # SOC column
    draw_soc(d, state["soc"] if state["soc"] is not None else 0.0,
             state["eta_text"])

    # Stats panel (right)
    panel = StatsPanel(STATS_X0, 0, STATS_X1, TOP_BOT)
    panel.draw(d, state["stats"])

    # Console (bottom)
    draw_console(d, log_lines)

    return img


# --- Replay driver --------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=DEFAULT_CSV)
    parser.add_argument("--start", type=float, default=3.0)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--output", default=None)
    parser.add_argument("--soc-start", type=float, default=95.0,
                        help="Initial SOC %% to seed the coulomb counter "
                             "(default 95). Use -1 to fall back to OCV.")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("error: ffmpeg not found on PATH (brew install ffmpeg)")
    if not os.path.exists(args.csv):
        sys.exit(f"error: CSV not found: {args.csv}")
    if not os.path.exists(MENLO_PATH):
        sys.exit(f"error: Menlo not found at {MENLO_PATH}")

    ts, V, I, P = load_csv(args.csv)
    if len(ts) < 10:
        sys.exit(f"error: CSV has too few rows: {args.csv}")

    t0 = float(args.start); t1 = t0 + float(args.duration)
    if t1 > ts[-1]:
        t1 = float(ts[-1]); t0 = max(float(ts[0]), t1 - args.duration)
    s = int(np.searchsorted(ts, t0))
    e = int(np.searchsorted(ts, t1))
    if e - s < 2:
        sys.exit("error: chosen window has no samples")

    ts_w = ts[s:e] - ts[s]
    V_w, I_w, P_w = V[s:e], I[s:e], P[s:e]
    duration = float(ts_w[-1])
    src_rate = (len(ts_w) - 1) / duration if duration > 0 else 0.0

    if args.output is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "outputs", "videos")
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = os.path.join(out_dir, f"ina226_render_{stamp}.mp4")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".",
                    exist_ok=True)

    n_frames = int(round(args.fps * duration))
    print(f"source        : {args.csv}")
    print(f"window        : t=[{t0:.3f}, {t1:.3f}]s  ({duration:.3f}s, "
          f"{len(ts_w)} samples, {src_rate:.0f} Hz)")
    print(f"I range       : [{I_w.min():.3f}, {I_w.max():.3f}] A")
    print(f"V range       : [{V_w.min():.3f}, {V_w.max():.3f}] V")
    print(f"output        : {args.output}")
    print(f"render        : {n_frames} frames @ {args.fps} fps  ({W}x{H})")

    # Rolling history buffers pre-filled with zeros (matches Tk init)
    hist_v = deque([0.0] * HISTORY, maxlen=HISTORY)
    hist_i = deque([0.0] * HISTORY, maxlen=HISTORY)
    hist_p = deque([0.0] * HISTORY, maxlen=HISTORY)
    cur_history = deque(maxlen=HISTORY)
    soc_history = deque(maxlen=HISTORY)
    vi_history  = deque(maxlen=HISTORY)

    state = {
        "src_idx": 0,
        "hist_v": hist_v, "hist_i": hist_i, "hist_p": hist_p,
        "soc": None, "ema_eta_hours": None,
        "eta_text": "--:--",
        "last_t": None,
        "v_min": None, "v_max": None,
        "i_min": None, "i_max": None,
        "p_min": None, "p_max": None,
        "charge_as": 0.0, "energy_ws": 0.0,
        "samples_seen": 0,
        "peak_announced": 0.0,
        "low_soc_announced": False,
    }

    wall_clock = datetime.now()

    def tstamp():
        return wall_clock.strftime("%H:%M:%S")

    log_lines = []  # list of (text, color); newest last
    def log(msg, color=C_INFO):
        log_lines.append((f"[{tstamp()}] {msg}", color))

    log("INA226 monitor started", C_OK)
    log(f"I2C @ 400 kHz · CAL={CAL_VALUE} · LSB={CURRENT_LSB*1e6:.0f} µA · "
        f"R_shunt={R_SHUNT*1000:.1f} mΩ")
    log("F11 or ⌘F toggles fullscreen · Esc exits fullscreen")

    # Start ffmpeg subprocess
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(args.fps),
        "-i", "-",
        "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "20",
        "-movflags", "+faststart",
        args.output,
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                            stderr=subprocess.PIPE)

    def build_stats_dict():
        v = hist_v[-1]; i = hist_i[-1]; p = hist_p[-1]
        # Live R_int regression on the vi_history sliding window
        rint_text = "—"; rint_q_text = "—"; rint_col = FGDM
        n = len(vi_history)
        if n >= RINT_MIN_SAMPLES:
            arr_v = np.asarray([vv for vv, _ in vi_history])
            arr_i = np.asarray([ii for _, ii in vi_history])
            std_i = arr_i.std()
            if std_i >= RINT_MIN_ISTD and arr_v.var() > 0 and arr_i.var() > 0:
                slope, intercept = np.polyfit(arr_i, arr_v, 1)
                r_est = -slope
                pred = slope * arr_i + intercept
                ss_res = float(np.sum((arr_v - pred) ** 2))
                ss_tot = float(np.sum((arr_v - arr_v.mean()) ** 2))
                r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
                if (RINT_MIN_OHMS <= r_est <= RINT_MAX_OHMS
                        and r2 >= RINT_MIN_R2):
                    rint_text = f"{r_est*1000:.0f} mΩ"
                    rint_q_text = f"{r2:.2f}"
                    rint_col = FG

        runtime = state["samples_seen"] / src_rate if src_rate > 0 else 0.0
        # Use video time for the runtime/avg readouts so they line up with
        # what's on-screen.
        return {
            "now_v":   f"{v:.3f} V",
            "now_i":   f"{i*1000:.0f} mA",
            "now_p":   f"{p:.2f} W",
            "cellv":   f"{(v/CELLS_SERIES)*1000:.0f} mV",
            "shuntv":  f"{i*R_SHUNT*1e6:.0f} µV",
            "rint":    rint_text,
            "rint_r2": rint_q_text,
            "rint_col": rint_col,
            "runtime": fmt_duration(state["_video_t"]),
            "charge":  f"{state['charge_as']/3600:.4f} Ah",
            "energy":  f"{state['energy_ws']/3600:.3f} Wh",
            "avg_p":   f"{state['energy_ws']/max(state['_video_t'],1e-6):.2f} W",
            "avg_i":   f"{(state['charge_as']/max(state['_video_t'],1e-6))*1000:.0f} mA",
            "samples": f"{state['samples_seen']}",
            "errors":  "0",
            "errors_col": FG,
            "v_range": (f"{state['v_min']:.2f} / {state['v_max']:.2f} V"
                        if state['v_min'] is not None else "—"),
            "i_range": (f"{state['i_min']:.3f} / {state['i_max']:.3f} A"
                        if state['i_min'] is not None else "—"),
            "p_range": (f"{state['p_min']:.1f} / {state['p_max']:.1f} W"
                        if state['p_min'] is not None else "—"),
        }

    try:
        for frame_idx in range(n_frames):
            t_video = (frame_idx + 1) * duration / n_frames
            state["_video_t"] = t_video

            while (state["src_idx"] < len(ts_w)
                   and ts_w[state["src_idx"]] <= t_video):
                k = state["src_idx"]
                v = float(V_w[k]); i = float(I_w[k]); p = float(P_w[k])
                t_now = float(ts_w[k])

                hist_v.append(v); hist_i.append(i); hist_p.append(p)
                cur_history.append(i); vi_history.append((v, i))

                if state["soc"] is None:
                    if args.soc_start >= 0:
                        state["soc"] = float(args.soc_start)
                    else:
                        ocv = v + abs(i) * R_INTERNAL
                        state["soc"] = voltage_to_soc(ocv)
                    state["last_t"] = t_now
                else:
                    dt = t_now - state["last_t"]
                    state["last_t"] = t_now
                    if dt > 0:
                        state["soc"] -= (abs(i) * dt / CAPACITY_AS) * 100.0
                        state["soc"] = max(0.0, min(100.0, state["soc"]))
                        state["charge_as"] += abs(i) * dt
                        state["energy_ws"] += abs(p) * dt
                soc_history.append(state["soc"])

                state["v_min"] = v if state["v_min"] is None else min(state["v_min"], v)
                state["v_max"] = v if state["v_max"] is None else max(state["v_max"], v)
                state["i_min"] = i if state["i_min"] is None else min(state["i_min"], i)
                state["i_max"] = i if state["i_max"] is None else max(state["i_max"], i)
                state["p_min"] = p if state["p_min"] is None else min(state["p_min"], p)
                state["p_max"] = p if state["p_max"] is None else max(state["p_max"], p)
                state["samples_seen"] += 1
                state["src_idx"] += 1

            # Notable events
            if (state["i_max"] is not None
                    and state["i_max"] >= state["peak_announced"] + 0.5):
                log(f"New peak current: {state['i_max']:.3f} A", C_WARN)
                state["peak_announced"] = state["i_max"]
            if (state["soc"] is not None and state["soc"] < 15
                    and not state["low_soc_announced"]):
                log(f"Low SOC: {state['soc']:.1f}%", C_WARN)
                state["low_soc_announced"] = True

            # ETA EMA based on avg current
            avg_i = sum(cur_history) / len(cur_history) if cur_history else 0.0
            soc_now = state["soc"] if state["soc"] is not None else 0.0
            if avg_i > 0.01:
                raw_hours = (soc_now / 100.0) * CAPACITY_AH / avg_i
                if state["ema_eta_hours"] is None:
                    state["ema_eta_hours"] = raw_hours
                else:
                    smoothed = (ETA_ALPHA * raw_hours
                                + (1 - ETA_ALPHA) * state["ema_eta_hours"])
                    state["ema_eta_hours"] = min(state["ema_eta_hours"],
                                                 smoothed)
                hh = int(state["ema_eta_hours"])
                mm = int((state["ema_eta_hours"] - hh) * 60)
                state["eta_text"] = f"{hh}h {mm:02d}m"
            else:
                state["eta_text"] = "--:--"

            state["stats"] = build_stats_dict()
            rate_text = f"{src_rate:.0f} Hz"

            img = render_frame(state, rate_text, log_lines)
            proc.stdin.write(img.tobytes())

        proc.stdin.close()
        proc.wait()
        if proc.returncode != 0:
            err = proc.stderr.read().decode("utf-8", "replace")
            sys.exit(f"ffmpeg failed (rc={proc.returncode}):\n{err}")
    except BrokenPipeError:
        err = proc.stderr.read().decode("utf-8", "replace")
        sys.exit(f"ffmpeg closed pipe early:\n{err}")

    print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
