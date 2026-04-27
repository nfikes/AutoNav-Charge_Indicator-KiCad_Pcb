"""GUI for clicking component centers on the PCB image.

Click on each component center when prompted. Press 'r' to redo the last click.
Press 'q' to quit and save. Results are saved to calibration_points.json.
"""

import tkinter as tk
from PIL import Image, ImageTk
import json
import os

INPUT_IMG = "/var/folders/f3/_z71yhs51pv3llyhxpt8w4yr0000gn/T/TemporaryItems/NSIRD_screencaptureui_P2xP7B/Screenshot 2026-04-23 at 19.15.39.png"
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration_points.json")

# Components to calibrate — KiCad (x, y) coordinates from PCB file
COMPONENTS = [
    ("FID1", 131.5, 72.5),
    ("FID3", 131.5, 115.0),
    ("FID2", 183.0, 124.0),
    ("M1", 189.5, 66.0),
    ("M4", 143.5, 65.0),
    ("M3", 135.5, 120.0),
    ("M2", 190.5, 112.0),
    ("R26", 145.1, 76.55),
    ("J2", 168.46, 66.5),
    ("J3", 178.96, 66.5),
    ("U4", 155.5, 87.5),
    ("U1", 149.5, 101.5),
    ("U3", 177.5, 95.25),
    ("U2", 176.5, 103.5),
    ("SW1", 139.5, 106.0),
    ("L2", 162.0, 110.0),
    ("J1", 137.23, 91.5),
]


class CalibrationApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PCB Calibration — Click Component Centers")

        # Load image
        self.pil_img = Image.open(INPUT_IMG)
        self.img_w, self.img_h = self.pil_img.size

        # Scale to fit screen (leave room for status bar)
        screen_w = self.root.winfo_screenwidth() - 100
        screen_h = self.root.winfo_screenheight() - 200
        self.scale = min(screen_w / self.img_w, screen_h / self.img_h, 1.0)
        self.disp_w = int(self.img_w * self.scale)
        self.disp_h = int(self.img_h * self.scale)

        self.disp_img = self.pil_img.resize((self.disp_w, self.disp_h), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(self.disp_img)

        # Status label
        self.status = tk.Label(self.root, text="", font=("Helvetica", 16), bg="black", fg="yellow")
        self.status.pack(fill=tk.X)

        # Canvas
        self.canvas = tk.Canvas(self.root, width=self.disp_w, height=self.disp_h)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)

        # State
        self.current_idx = 0
        self.results = []
        self.markers = []

        # Bindings
        self.canvas.bind("<Button-1>", self.on_click)
        self.root.bind("r", self.redo_last)
        self.root.bind("q", self.quit_save)

        self.update_status()

    def update_status(self):
        if self.current_idx < len(COMPONENTS):
            name, kx, ky = COMPONENTS[self.current_idx]
            self.status.config(
                text=f"  [{self.current_idx+1}/{len(COMPONENTS)}]  Click the CENTER of: {name}  "
                     f"(KiCad: {kx}, {ky})    |    'r' = redo last    'q' = quit & save",
                fg="yellow"
            )
        else:
            self.status.config(text="  All done! Press 'q' to save and quit.", fg="lime")

    def on_click(self, event):
        if self.current_idx >= len(COMPONENTS):
            return

        # Convert display coords to full-image coords
        px = int(event.x / self.scale)
        py = int(event.y / self.scale)

        name, kx, ky = COMPONENTS[self.current_idx]
        self.results.append({
            "name": name,
            "kicad_x": kx,
            "kicad_y": ky,
            "pixel_x": px,
            "pixel_y": py,
        })

        # Draw marker on canvas
        r = 6
        cx, cy = event.x, event.y
        m1 = self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline="cyan", width=2)
        m2 = self.canvas.create_text(cx+12, cy, text=name, fill="cyan", anchor=tk.W,
                                      font=("Helvetica", 10))
        self.markers.append((m1, m2))

        print(f"  {name}: pixel ({px}, {py})")

        self.current_idx += 1
        self.update_status()

    def redo_last(self, event=None):
        if self.current_idx > 0 and self.markers:
            self.current_idx -= 1
            self.results.pop()
            m1, m2 = self.markers.pop()
            self.canvas.delete(m1)
            self.canvas.delete(m2)
            self.update_status()
            print(f"  Redo: {COMPONENTS[self.current_idx][0]}")

    def quit_save(self, event=None):
        with open(OUTPUT, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nSaved {len(self.results)} calibration points to {OUTPUT}")
        self.root.destroy()

    def run(self):
        print("Click the center of each component as prompted.")
        print("Press 'r' to redo the last click, 'q' to save and quit.\n")
        self.root.mainloop()


if __name__ == "__main__":
    app = CalibrationApp()
    app.run()
