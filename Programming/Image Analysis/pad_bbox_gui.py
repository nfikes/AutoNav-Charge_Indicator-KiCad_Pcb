"""GUI for drawing bounding boxes around visible pad clumps.

Click and drag to draw a box around each group of purple pads.
Type the component reference (e.g. U1, U4, R26) after drawing each box.
Press 'z' to undo the last box. Press 'q' to save and quit.
"""

import tkinter as tk
from tkinter import simpledialog
from PIL import Image, ImageTk, ImageDraw
import json
import os

INPUT_IMG = "/var/folders/f3/_z71yhs51pv3llyhxpt8w4yr0000gn/T/TemporaryItems/NSIRD_screencaptureui_P2xP7B/Screenshot 2026-04-23 at 19.15.39.png"
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pad_bboxes.json")


class PadBBoxApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Draw boxes around pad clumps — type ref name after each")

        self.pil_img = Image.open(INPUT_IMG)
        self.img_w, self.img_h = self.pil_img.size

        screen_w = self.root.winfo_screenwidth() - 100
        screen_h = self.root.winfo_screenheight() - 200
        self.scale = min(screen_w / self.img_w, screen_h / self.img_h, 1.0)
        self.disp_w = int(self.img_w * self.scale)
        self.disp_h = int(self.img_h * self.scale)

        self.disp_img = self.pil_img.resize((self.disp_w, self.disp_h), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(self.disp_img)

        self.status = tk.Label(self.root, text="  Draw a box around a clump of purple pads, then type the ref name. 'z'=undo 'q'=save&quit",
                               font=("Helvetica", 14), bg="black", fg="yellow")
        self.status.pack(fill=tk.X)

        self.canvas = tk.Canvas(self.root, width=self.disp_w, height=self.disp_h)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)

        self.boxes = []  # list of (ref, x1, y1, x2, y2) in full-image coords
        self.canvas_items = []
        self.drawing = False
        self.start_x = 0
        self.start_y = 0
        self.current_rect = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("z", self.undo)
        self.root.bind("q", self.save_quit)

    def on_press(self, event):
        self.drawing = True
        self.start_x = event.x
        self.start_y = event.y
        self.current_rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="cyan", width=2)

    def on_drag(self, event):
        if self.drawing and self.current_rect:
            self.canvas.coords(self.current_rect,
                               self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        if not self.drawing:
            return
        self.drawing = False

        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)

        # Convert to full image coords
        fx1 = int(x1 / self.scale)
        fy1 = int(y1 / self.scale)
        fx2 = int(x2 / self.scale)
        fy2 = int(y2 / self.scale)

        # Ask for reference name
        ref = simpledialog.askstring("Component Reference",
                                      "Enter the component reference\n(e.g. U1, U4, R26, J2):",
                                      parent=self.root)
        if ref:
            ref = ref.strip().upper()
            self.boxes.append({"ref": ref, "x1": fx1, "y1": fy1, "x2": fx2, "y2": fy2})

            # Update rectangle color and add label
            self.canvas.itemconfig(self.current_rect, outline="lime")
            label = self.canvas.create_text(x1 + 3, y1 - 12, text=ref,
                                            fill="lime", anchor=tk.W,
                                            font=("Helvetica", 11))
            self.canvas_items.append((self.current_rect, label))

            self.status.config(text=f"  Added {ref} — {len(self.boxes)} boxes total. Draw next or 'q' to save.")
            print(f"  {ref}: ({fx1}, {fy1}) - ({fx2}, {fy2})")
        else:
            self.canvas.delete(self.current_rect)

        self.current_rect = None

    def undo(self, event=None):
        if self.boxes and self.canvas_items:
            self.boxes.pop()
            rect, label = self.canvas_items.pop()
            self.canvas.delete(rect)
            self.canvas.delete(label)
            self.status.config(text=f"  Undone. {len(self.boxes)} boxes remain.")

    def save_quit(self, event=None):
        with open(OUTPUT, 'w') as f:
            json.dump(self.boxes, f, indent=2)
        print(f"\nSaved {len(self.boxes)} bounding boxes to {OUTPUT}")
        self.root.destroy()

    def run(self):
        print("Draw boxes around visible purple pad clumps.")
        print("After each box, type the component reference name.")
        print("'z' to undo, 'q' to save and quit.\n")
        self.root.mainloop()


if __name__ == "__main__":
    app = PadBBoxApp()
    app.run()
