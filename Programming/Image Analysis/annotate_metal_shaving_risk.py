"""Annotate PCB image with data-driven metal shaving short-circuit risks.

Uses a simple linear transform (no warping) calibrated from fiducials
and mounting holes. Draws pad positions, 0603 bridging circles, and
highlights where circles from different nets overlap.
"""

import numpy as np
import json
import math
from PIL import Image, ImageDraw, ImageFont
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_IMG = "/var/folders/f3/_z71yhs51pv3llyhxpt8w4yr0000gn/T/TemporaryItems/NSIRD_screencaptureui_P2xP7B/Screenshot 2026-04-23 at 19.15.39.png"
OUTPUT = os.path.join(DATA_DIR, "R3_metal_shaving_risk_analysis.png")

pad_data = json.load(open(os.path.join(DATA_DIR, "pad_data.json")))
overlap_data = json.load(open(os.path.join(DATA_DIR, "overlap_data.json")))

img = Image.open(INPUT_IMG).convert("RGBA")
W, H = img.size
overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
draw = ImageDraw.Draw(overlay)

try:
    font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
    font_legend = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
except Exception:
    font_small = ImageFont.load_default()
    font_title = font_small
    font_legend = font_small

# ============================================================
# Linear transform: px = sx*kx + tx, py = sy*ky + ty
# Calibrated from fiducials + mounting holes (perimeter points)
# Scale: ~21 px/mm, no rotation
# ============================================================
sx, tx = 20.9849, -2616.65
sy, ty = 21.0113, -1234.30

def k2p(kx_val, ky_val):
    return (int(sx * kx_val + tx), int(sy * ky_val + ty))

def mm_to_px(mm_val):
    return int(mm_val * (sx + sy) / 2)

BRIDGE_MM = 0.8  # half of 0603 long dimension
bridge_px = mm_to_px(BRIDGE_MM)

# ============================================================
# Classify severity
# ============================================================
POWER_NETS = {"/BAT+", "GND", "+5v", "+3v3", "AGND", "/BAT-"}
I2C_NETS = {"/SCL", "/SDA"}

def classify_severity(net1, net2):
    nets = {net1, net2}
    # BAT+ to GND/AGND = dead short across battery
    if "/BAT+" in nets and ("GND" in nets or "AGND" in nets):
        return "CRITICAL"
    # BAT+ to any low-voltage signal/pin = overvoltage destruction
    # (25.6V exceeds abs max of every IC except the buck VIN)
    if "/BAT+" in nets:
        return "CRITICAL"
    # Power rail shorts (+5v/+3v3 to GND)
    if ("+5v" in nets or "+3v3" in nets) and ("GND" in nets or "AGND" in nets):
        return "CRITICAL"
    # I2C to power — latch-up risk (BQ34Z100 has only 500V HBM ESD,
    # INA226 SCL max is only VS+0.3V)
    if nets & I2C_NETS and nets & POWER_NETS:
        return "CRITICAL"
    # Different power rails shorting
    if len(nets & POWER_NETS) == 2:
        return "HIGH"
    # FB network — 5.5V max pin next to 25V+ VIN (confirmed R2 failure)
    if any("FB" in n for n in nets):
        return "CRITICAL"
    # ENABLE/VEN to power or ground — uncontrolled FET switching
    if any("ENABLE" in n or "VEN" in n for n in nets):
        return "HIGH"
    # VTRANS to anything — op-amp input, 16.5V max on TLV271
    if any("VTRANS" in n for n in nets):
        return "HIGH"
    # I2C signal to signal
    if nets & I2C_NETS:
        return "MODERATE"
    # BAT- to GND (sense resistor bypass)
    if "/BAT-" in nets and "GND" in nets:
        return "HIGH"
    return "LOW"

SEVERITY_COLORS = {
    "CRITICAL": ((255, 40, 40, 200), (255, 40, 40, 50)),
    "HIGH":     ((255, 165, 0, 180), (255, 165, 0, 35)),
    "MODERATE": ((255, 255, 0, 140), (255, 255, 0, 25)),
}

# ============================================================
# Draw pads as small green rectangles + 0603 bridging reach
# as rounded rectangles (pad edges + half 0603 length)
# ============================================================
for ref, pad_num, kx, ky, net_num, net_name, pw, ph in pad_data:
    if net_num == 0:
        continue
    px, py = k2p(kx, ky)
    half_w = max(2, mm_to_px(pw / 2))
    half_h = max(2, mm_to_px(ph / 2))

    # Pad fill
    draw.rectangle([px - half_w, py - half_h, px + half_w, py + half_h],
                   fill=(0, 255, 0, 50), outline=(0, 255, 0, 120), width=1)

    # Rounded rectangle: pad edges expanded by half 0603 length (0.8mm)
    rx1 = px - half_w - bridge_px
    ry1 = py - half_h - bridge_px
    rx2 = px + half_w + bridge_px
    ry2 = py + half_h + bridge_px
    draw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=bridge_px,
                           outline=(0, 255, 0, 60), width=1)

# ============================================================
# Group overlaps and draw risk zones + lines
# ============================================================
from collections import defaultdict
comp_pair_risks = defaultdict(list)

for gap, dist, p1, p2 in overlap_data:
    ref1, pad1, x1, y1, net1_n, net1, w1, h1 = p1
    ref2, pad2, x2, y2, net2_n, net2, w2, h2 = p2
    if net1_n == 0 or net2_n == 0:
        continue
    if "unconnected" in net1 or "unconnected" in net2:
        continue
    severity = classify_severity(net1, net2)
    if severity == "LOW":
        continue
    key = tuple(sorted([ref1, ref2]))
    comp_pair_risks[key].append((gap, severity, ref1, pad1, net1, ref2, pad2, net2, x1, y1, x2, y2))

risk_annotations = []

for comp_pair, risks in comp_pair_risks.items():
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2}
    worst = min(risks, key=lambda r: sev_order[r[1]])
    severity = worst[1]
    line_color, zone_color = SEVERITY_COLORS[severity]

    all_kx = [r[8] for r in risks] + [r[10] for r in risks]
    all_ky = [r[9] for r in risks] + [r[11] for r in risks]
    min_kx, max_kx = min(all_kx), max(all_kx)
    min_ky, max_ky = min(all_ky), max(all_ky)

    pad_mm = 0.3
    p1 = k2p(min_kx - pad_mm, min_ky - pad_mm)
    p2 = k2p(max_kx + pad_mm, max_ky + pad_mm)
    bx1, by1 = min(p1[0], p2[0]), min(p1[1], p2[1])
    bx2, by2 = max(p1[0], p2[0]), max(p1[1], p2[1])

    draw.rectangle([bx1, by1, bx2, by2], fill=zone_color, outline=line_color, width=2)

    for gap, sev, ref1, pad1n, net1, ref2, pad2n, net2, kx1, ky1, kx2, ky2 in risks:
        px1, py1 = k2p(kx1, ky1)
        px2, py2 = k2p(kx2, ky2)
        lc = SEVERITY_COLORS[sev][0]
        draw.line([px1, py1, px2, py2], fill=lc, width=2)

    nets_involved = set()
    for r in risks:
        nets_involved.add(r[4])
        nets_involved.add(r[7])
    risk_annotations.append((bx1, by1, bx2, by2, severity, comp_pair, nets_involved, len(risks)))

# Number each zone and draw the number on the image
try:
    font_num = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
except Exception:
    font_num = font_small

# Sort by severity then by position for consistent numbering
sev_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2}
numbered = sorted(enumerate(risk_annotations), key=lambda x: (sev_order[x[1][4]], x[1][1]))
zone_number_map = {}
for new_idx, (orig_idx, ann) in enumerate(numbered):
    zone_number_map[orig_idx] = new_idx + 1

for orig_idx, ann in enumerate(risk_annotations):
    bx1, by1, bx2, by2, severity, comp_pair, nets, count = ann
    num = zone_number_map[orig_idx]

    # Draw number with background
    num_str = str(num)
    # Position: top-left corner of the zone box
    nx, ny = bx1 - 2, by1 - 18
    if ny < 55:
        ny = by2 + 2

    color = SEVERITY_COLORS[severity][0]
    # Small background rectangle for readability
    tw = len(num_str) * 10 + 4
    draw.rectangle([nx, ny, nx + tw, ny + 16], fill=(0, 0, 0, 200))
    draw.text((nx + 2, ny), num_str, fill=color, font=font_num)

# ============================================================
# Composite and legend
# ============================================================
result = Image.alpha_composite(img, overlay)
final = result.convert("RGB")
ld = ImageDraw.Draw(final)

ld.rectangle([0, 0, W, 50], fill=(10, 10, 30))
ld.text((15, 6), "METAL SHAVING SHORT-CIRCUIT RISK ANALYSIS — Rev 3 PCB",
        fill=(255, 255, 255), font=font_title)

n_crit = len([r for r in risk_annotations if r[4] == "CRITICAL"])
n_high = len([r for r in risk_annotations if r[4] == "HIGH"])
n_mod = len([r for r in risk_annotations if r[4] == "MODERATE"])
total_pairs = sum(r[7] for r in risk_annotations)
ld.text((15, 34),
    f"0603 shaving (1.6x0.8mm) — {n_crit} critical, {n_high} high, {n_mod} moderate zones  |  "
    f"{total_pairs} bridgeable pad pairs",
    fill=(200, 200, 200), font=font_small)

ly = H - 50
ld.rectangle([0, ly, W, H], fill=(10, 10, 30))
for x, color, label in [
    (20, (0, 255, 0), "Pad + 0603 reach"),
    (230, (255, 40, 40), "Critical (power short)"),
    (490, (255, 165, 0), "High (IC damage)"),
    (700, (255, 255, 0), "Moderate (signal)"),
]:
    ld.rectangle([x, ly + 8, x + 20, ly + 22], fill=color, outline=color)
    ld.text((x + 26, ly + 6), label, fill=(200, 200, 200), font=font_legend)

ld.text((20, ly + 30),
    "Lines connect pad pairs a 0603 shaving could bridge across different nets.",
    fill=(180, 180, 180), font=font_small)

final.save(OUTPUT, "PNG", quality=95)
print(f"Saved: {OUTPUT}")

print(f"\n{'='*60}")
print("NUMBERED RISK ZONES")
print(f"{'='*60}")
for orig_idx, ann in enumerate(risk_annotations):
    _, _, _, _, severity, comp_pair, nets, count = ann
    num = zone_number_map[orig_idx]
    clean = sorted(n.replace("{slash}", "/").replace("Net-(", "").rstrip(")") for n in nets)
    print(f"  #{num:2d}  [{severity:8s}]  {'/'.join(comp_pair):12s}  {count} pairs — {', '.join(clean[:6])}")
