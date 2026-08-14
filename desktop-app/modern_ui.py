"""Taste-led Kova Hand desktop UI.

Only layout and presentation live here. BLE and MediaPipe behavior remain in main.py.
"""

from __future__ import annotations

import tkinter as tk
from io import BytesIO
from pathlib import Path
from typing import Callable

import customtkinter as ctk
import config

try:
    import resvg_py
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    resvg_py = None
    Image = None
    ImageDraw = None
    ImageTk = None


BG = "#F5F5F7"
SURFACE = "#FFFFFF"
TEXT = "#1D1D1F"
MUTED = "#6E6E73"
HAIRLINE = "#D2D2D7"
ACCENT = "#0071E3"
ACCENT_HOVER = "#0064C8"
ACTION = "#202124"
ACTION_HOVER = "#343538"
CONTROL = "#F1F1F3"
CONTROL_HOVER = "#E5E5E8"
DARK = "#FFFFFF"
DARK_2 = "#F5F5F7"
DARK_TEXT = TEXT
DARK_MUTED = MUTED
ICON_DIR = Path(__file__).resolve().parent / "assets" / "icons"
BRAND_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "kova-logo.png"


def _font(size: int, weight: str = "normal", mono: bool = False):
    family = "Cascadia Mono" if mono else "Microsoft JhengHei UI"
    if not mono:
        if size <= 11:
            size += 2
        elif size <= 14:
            size += 1
    return ctk.CTkFont(family=family, size=size, weight=weight)


def load_icon(name: str, color: str, size: int):
    if Image is None or resvg_py is None:
        return None
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        return None
    svg = path.read_text(encoding="utf-8").replace("#000", color)
    png = resvg_py.svg_to_bytes(svg_string=svg, width=size * 2, height=size * 2)
    image = Image.open(BytesIO(png)).convert("RGBA")
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


def load_brand_logo(size: int):
    """Load the user's original raster logo without redrawing its geometry."""

    if Image is None or not BRAND_LOGO_PATH.exists():
        return None
    logo = Image.open(BRAND_LOGO_PATH).convert("RGBA")
    logo.thumbnail((size * 2, size * 2), Image.Resampling.LANCZOS)
    display_size = (max(1, logo.width // 2), max(1, logo.height // 2))
    return ctk.CTkImage(light_image=logo, dark_image=logo, size=display_size)


def make_window_icon():
    """Build the native window icon from the user's original logo pixels."""

    if Image is None or ImageDraw is None or ImageTk is None or not BRAND_LOGO_PATH.exists():
        return None
    glyph = Image.open(BRAND_LOGO_PATH).convert("RGBA")
    glyph.thumbnail((44, 44), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).rounded_rectangle((4, 4, 60, 60), radius=15, fill=ACTION)
    canvas.alpha_composite(glyph, ((64 - glyph.width) // 2, (64 - glyph.height) // 2))
    return ImageTk.PhotoImage(canvas)


class DeviceCombo(ctk.CTkComboBox):
    """Compatibility shim for the existing ttk-style event code."""

    def __setitem__(self, key, value):
        if key == "values":
            self.configure(values=value or ["尚未找到裝置"])
            return
        return super().__setitem__(key, value)

    def current(self, index: int):
        values = self.cget("values")
        if 0 <= index < len(values):
            self.set(values[index])


class StyledButton(ctk.CTkButton):
    """Maps the legacy style names to the new visual states."""

    def configure(self, require_redraw=False, **kwargs):
        style = kwargs.pop("style", None)
        if style == "Danger.TButton":
            kwargs.update(
                fg_color="#E9E9ED",
                hover_color="#DDDDE2",
                text_color=TEXT,
                border_width=0,
            )
        elif style == "Primary.TButton":
            kwargs.update(
                fg_color=ACTION,
                hover_color=ACTION_HOVER,
                text_color="#FFFFFF",
                border_width=0,
            )
        return super().configure(require_redraw=require_redraw, **kwargs)


class AngleSlider(tk.Canvas):
    """A precise slider whose physical midpoint is exactly width / 2."""

    HORIZONTAL_PADDING = 11

    def __init__(self, master, minimum: int, maximum: int, value: int, command: Callable):
        super().__init__(
            master,
            height=25,
            bg=SURFACE,
            highlightthickness=0,
            cursor="hand2",
            takefocus=True,
        )
        self.minimum = minimum
        self.maximum = maximum
        self.value = value
        self.command = command
        self.dragging = False
        self.hovered = False
        self.focused = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Left>", lambda _event: self._step(-1))
        self.bind("<Right>", lambda _event: self._step(1))
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)

    def _x_for_value(self) -> float:
        usable = max(1, self.winfo_width() - self.HORIZONTAL_PADDING * 2)
        ratio = (self.value - self.minimum) / max(1, self.maximum - self.minimum)
        return self.HORIZONTAL_PADDING + ratio * usable

    def _value_for_x(self, x: float) -> int:
        usable = max(1, self.winfo_width() - self.HORIZONTAL_PADDING * 2)
        ratio = min(1.0, max(0.0, (x - self.HORIZONTAL_PADDING) / usable))
        return round(self.minimum + ratio * (self.maximum - self.minimum))

    def _draw(self):
        self.delete("all")
        y = 12
        start = self.HORIZONTAL_PADDING
        end = max(start, self.winfo_width() - start)
        knob_x = self._x_for_value()
        self.create_line(start, y, end, y, fill="#D1D1D6", width=3, capstyle="round")
        self.create_line(start, y, knob_x, y, fill=ACCENT, width=3, capstyle="round")
        if self.focused:
            self.create_oval(
                knob_x - 11,
                y - 11,
                knob_x + 11,
                y + 11,
                fill="#D6EBFF",
                outline="",
            )
        radius = 8 if self.hovered or self.dragging else 7
        self.create_oval(
            knob_x - radius - 1,
            y - radius,
            knob_x + radius + 1,
            y + radius + 2,
            fill="#BFC3CA",
            outline="",
        )
        self.create_oval(
            knob_x - radius,
            y - radius,
            knob_x + radius,
            y + radius,
            fill=SURFACE,
            outline="#C7C7CC",
            width=1,
        )

    def set_value(self, value: int, notify: bool = True):
        self.value = min(self.maximum, max(self.minimum, round(value)))
        self._draw()
        if notify:
            self.command(self.value)

    def _press(self, event):
        self.focus_set()
        self.dragging = True
        self.set_value(self._value_for_x(event.x))

    def _move(self, event):
        if self.dragging:
            self.set_value(self._value_for_x(event.x))

    def _release(self, event):
        self.dragging = False
        self.set_value(self._value_for_x(event.x))
        self.event_generate("<<SliderReleased>>")

    def _step(self, amount: int):
        self.set_value(self.value + amount)
        self.event_generate("<<SliderReleased>>")

    def _enter(self, _event):
        self.hovered = True
        self._draw()

    def _leave(self, _event):
        self.hovered = False
        self._draw()

    def _focus_in(self, _event):
        self.focused = True
        self._draw()

    def _focus_out(self, _event):
        self.focused = False
        self._draw()


class MotorRow(ctk.CTkFrame):
    def __init__(self, master, motor: dict, on_change: Callable[[int, int], None], divider: bool):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.motor = motor
        self.on_change = on_change
        self.value = tk.IntVar(value=motor["initial"])
        self.pending_send = None
        self.grid_columnconfigure(1, weight=1, minsize=260)

        ctk.CTkLabel(
            self,
            text=motor["title"],
            text_color=TEXT,
            font=_font(14, "bold"),
            anchor="w",
            width=72,
        ).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))

        values = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        values.grid(row=0, column=1, sticky="ew")
        values.grid_columnconfigure((0, 1, 2), weight=1, uniform="angle_labels")
        ctk.CTkLabel(values, text=f"{motor['min']}°", text_color=MUTED, font=_font(11)).grid(
            row=0, column=0, sticky="w"
        )
        self.value_label = ctk.CTkLabel(
            values,
            text=f"{self.value.get()}°",
            text_color=TEXT,
            font=_font(19, "bold", mono=True),
        )
        self.value_label.grid(row=0, column=1)
        ctk.CTkLabel(values, text=f"{motor['max']}°", text_color=MUTED, font=_font(11)).grid(
            row=0, column=2, sticky="e"
        )

        self.scale = AngleSlider(
            self,
            minimum=motor["min"],
            maximum=motor["max"],
            value=motor["initial"],
            command=self._slider_changed,
        )
        self.scale.grid(row=1, column=1, sticky="ew")
        self.scale.bind("<<SliderReleased>>", self._released)

        if divider:
            ctk.CTkFrame(self, height=1, fg_color=HAIRLINE, corner_radius=0).grid(
                row=2, column=0, columnspan=2, sticky="ew", pady=(9, 0)
            )

    def _slider_changed(self, raw_value):
        angle = round(float(raw_value))
        self.value.set(angle)
        self.value_label.configure(text=f"{angle}°")
        if self.pending_send:
            self.after_cancel(self.pending_send)
        self.pending_send = self.after(
            config.SEND_INTERVAL_MS,
            lambda: self.on_change(self.motor["channel"], self.value.get()),
        )

    def _released(self, _event):
        if self.pending_send:
            self.after_cancel(self.pending_send)
            self.pending_send = None
        self.on_change(self.motor["channel"], self.value.get())

    def center(self):
        center = round((self.motor["min"] + self.motor["max"]) / 2)
        self.value.set(center)
        self.value_label.configure(text=f"{center}°")
        self.scale.set_value(center, notify=False)
        self.on_change(self.motor["channel"], center)


def build_ui(app):
    ctk.set_appearance_mode("light")
    icons = {
        "brand": load_brand_logo(35),
        "bluetooth": load_icon("bluetooth", ACCENT, 18),
        "scan": load_icon("refresh", TEXT, 17),
        "connect": load_icon("link", "#FFFFFF", 17),
        "unlink": load_icon("unlink", TEXT, 17),
        "center": load_icon("target", ACCENT, 17),
        "camera": load_icon("camera", "#D6DBE3", 42),
        "play": load_icon("player-play", "#FFFFFF", 18),
        "stop": load_icon("player-stop", "#FFFFFF", 18),
        "info": load_icon("info-circle", MUTED, 19),
    }
    app.ui_icons = icons

    shell = ctk.CTkFrame(app, fg_color=BG, corner_radius=0)
    shell.pack(fill="both", expand=True, padx=28, pady=(18, 20))
    shell.grid_columnconfigure(0, weight=1)
    shell.grid_rowconfigure(1, weight=1)

    header = ctk.CTkFrame(
        shell,
        fg_color=SURFACE,
        border_width=1,
        border_color=HAIRLINE,
        corner_radius=16,
        height=108,
    )
    header.grid(row=0, column=0, sticky="ew")
    header.grid_propagate(False)
    header.grid_columnconfigure(1, weight=1)

    identity = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0)
    identity.grid(row=0, column=0, sticky="w", padx=(18, 0), pady=(7, 13))
    ctk.CTkLabel(identity, text="", image=icons["brand"], width=48).grid(
        row=0, column=0, rowspan=2, padx=(2, 13)
    )
    ctk.CTkLabel(
        identity, text=config.APP_TITLE, text_color=TEXT, font=_font(25, "bold"), anchor="w"
    ).grid(row=0, column=1, sticky="sw")
    ctk.CTkLabel(
        identity, text="機器人手部控制台", text_color=MUTED, font=_font(12), anchor="w"
    ).grid(row=1, column=1, sticky="nw", pady=(1, 0))

    connection = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0)
    connection.grid(row=0, column=1, sticky="e", padx=(0, 18), pady=(7, 13))
    ctk.CTkLabel(connection, text="", image=icons["bluetooth"], width=22).grid(
        row=0, column=0, rowspan=2, padx=(0, 6)
    )
    ctk.CTkLabel(
        connection, text="藍牙裝置", text_color=TEXT, font=_font(11, "bold"), anchor="w"
    ).grid(row=0, column=1, sticky="w", pady=(0, 3))

    app.device_box = DeviceCombo(
        connection,
        values=["尚未掃描裝置"],
        state="readonly",
        width=222,
        height=38,
        fg_color=SURFACE,
        border_color="#C9CFD8",
        button_color=SURFACE,
        button_hover_color="#E8ECF2",
        text_color=TEXT,
        dropdown_fg_color=SURFACE,
        dropdown_text_color=TEXT,
        dropdown_hover_color="#E8EEF9",
        corner_radius=9,
        font=_font(12),
    )
    app.device_box.grid(row=1, column=1, padx=(0, 9))
    app.device_box.set("尚未掃描裝置")

    app.scan_button = StyledButton(
        connection,
        text="掃描",
        image=icons["scan"],
        command=app._scan,
        width=86,
        height=38,
        fg_color=SURFACE,
        hover_color="#E8ECF2",
        text_color=TEXT,
        border_width=1,
        border_color="#C9CFD8",
        corner_radius=9,
        font=_font(12, "bold"),
    )
    app.scan_button.grid(row=1, column=2, padx=(0, 8))
    app.connect_button = StyledButton(
        connection,
        text="連線",
        image=icons["connect"],
        command=app._connect,
        width=96,
        height=38,
        fg_color=ACCENT,
        hover_color=ACCENT_HOVER,
        corner_radius=9,
        font=_font(12, "bold"),
    )
    app.connect_button.grid(row=1, column=3, padx=(0, 16))

    status = ctk.CTkFrame(connection, fg_color="transparent", corner_radius=0)
    status.grid(row=1, column=4)
    app.status_dot = tk.Canvas(status, width=12, height=12, bg=SURFACE, highlightthickness=0)
    app.dot = app.status_dot.create_oval(2, 2, 10, 10, fill="#9EA6B2", outline="")
    app.status_dot.pack(side="left", padx=(0, 6))
    app.status_label = ctk.CTkLabel(
        status, text="尚未連線", width=76, anchor="w", text_color=MUTED, font=_font(11)
    )
    app.status_label.pack(side="left")

    workspace = ctk.CTkFrame(shell, fg_color="transparent", corner_radius=0)
    workspace.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
    workspace.grid_columnconfigure(0, weight=43, uniform="workspace")
    workspace.grid_columnconfigure(1, weight=57, uniform="workspace")
    workspace.grid_rowconfigure(0, weight=1)

    motor_panel = ctk.CTkFrame(
        workspace,
        fg_color=SURFACE,
        border_width=1,
        border_color=HAIRLINE,
        corner_radius=16,
    )
    motor_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    motor_panel.grid_columnconfigure(0, weight=1)
    motor_panel.grid_rowconfigure(1, weight=1)

    motor_header = ctk.CTkFrame(motor_panel, fg_color="transparent", corner_radius=0)
    motor_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 8))
    motor_header.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(
        motor_header, text="馬達控制", text_color=TEXT, font=_font(18, "bold"), anchor="w"
    ).grid(row=0, column=0, sticky="w")
    ctk.CTkButton(
        motor_header,
        text="全部置中",
        image=icons["center"],
        command=app._center_all,
        width=104,
        height=36,
        fg_color="transparent",
        hover_color="#E2E8F1",
        text_color=ACCENT,
        border_width=1,
        border_color=ACCENT,
        corner_radius=9,
        font=_font(12, "bold"),
    ).grid(row=0, column=1)

    motor_list = ctk.CTkFrame(motor_panel, fg_color="transparent", corner_radius=0)
    motor_list.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))
    motor_list.grid_columnconfigure(0, weight=1)
    app.motor_rows = []
    for index, motor in enumerate(config.MOTORS):
        row = MotorRow(
            motor_list,
            motor,
            app._send_angle,
            divider=index < len(config.MOTORS) - 1,
        )
        row.grid(row=index, column=0, sticky="nsew", pady=(0, 2))
        motor_list.grid_rowconfigure(index, weight=1, uniform="motor_rows")
        app.motor_rows.append(row)

    camera_holder = ctk.CTkFrame(workspace, fg_color="transparent", corner_radius=0)
    camera_holder.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
    shadow = ctk.CTkFrame(camera_holder, fg_color="#D8DEE6", corner_radius=16)
    shadow.place(x=0, y=4, relwidth=1, relheight=1, height=-4)
    camera_surface = ctk.CTkFrame(
        camera_holder,
        fg_color=SURFACE,
        border_width=1,
        border_color=HAIRLINE,
        corner_radius=16,
    )
    camera_surface.place(x=0, y=0, relwidth=1, relheight=1, height=-4)

    app.camera_label = ctk.CTkLabel(
        camera_surface,
        text="MediaPipe Hands\n攝影機預覽",
        image=icons["camera"],
        compound="top",
        fg_color="#F7F9FC",
        text_color=DARK_TEXT,
        font=_font(20, "bold"),
        corner_radius=15,
    )
    app.camera_label.place(x=0, y=0, relwidth=1, relheight=1)

    camera_status = ctk.CTkFrame(camera_surface, fg_color=DARK_2, corner_radius=10)
    camera_status.place(relx=0.5, rely=0.64, anchor="center")
    app.hand_status_dot = tk.Canvas(
        camera_status, width=12, height=12, bg=DARK_2, highlightthickness=0
    )
    app.hand_dot = app.hand_status_dot.create_oval(2, 2, 10, 10, fill="#808A98", outline="")
    app.hand_status_dot.pack(side="left", padx=(12, 7), pady=9)
    app.hand_status_label = ctk.CTkLabel(
        camera_status,
        text="手部辨識尚未啟動",
        text_color=DARK_MUTED,
        font=_font(12),
    )
    app.hand_status_label.pack(side="left", padx=(0, 12), pady=7)

    app.hand_button = StyledButton(
        camera_surface,
        text="開啟手部辨識",
        image=icons["play"],
        command=app._toggle_hand_tracking,
        width=160,
        height=42,
        fg_color=ACCENT,
        hover_color=ACCENT_HOVER,
        corner_radius=9,
        font=_font(13, "bold"),
    )
    app.hand_button.place(relx=0.5, rely=0.75, anchor="center")

    note = ctk.CTkFrame(camera_surface, fg_color="transparent", corner_radius=0)
    note.place(relx=0.5, rely=0.86, anchor="center")
    ctk.CTkLabel(note, text="", image=icons["info"], width=22).pack(side="left", padx=(0, 7))
    ctk.CTkLabel(
        note,
        text="目前只顯示辨識骨架，不會傳送馬達控制訊號。",
        text_color=DARK_MUTED,
        font=_font(11),
    ).pack(side="left")


# The user chose the original light two-panel composition as the visual authority.
# This refined implementation intentionally preserves that exact information architecture.
class RefinedMotorRow(ctk.CTkFrame):
    def __init__(self, master, motor: dict, on_change: Callable[[int, int], None], divider: bool):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.motor = motor
        self.on_change = on_change
        self.value = tk.IntVar(value=motor["initial"])
        self.pending_send = None
        self.grid_columnconfigure(0, minsize=120)
        self.grid_columnconfigure(1, minsize=88)
        self.grid_columnconfigure(2, weight=1, minsize=220)

        title_cell = ctk.CTkFrame(
            self, width=112, height=54, fg_color="transparent", corner_radius=0
        )
        title_cell.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 8), pady=(2, 2))
        title_cell.grid_propagate(False)
        ctk.CTkLabel(
            title_cell,
            text=motor["title"],
            text_color=TEXT,
            font=_font(14, "bold"),
            anchor="w",
            width=112,
        ).place(x=0, rely=0.52, anchor="w")

        value_cell = ctk.CTkFrame(
            self, width=76, height=54, fg_color="transparent", corner_radius=0
        )
        value_cell.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 12), pady=(2, 2))
        value_cell.grid_propagate(False)
        self.value_label = ctk.CTkLabel(
            value_cell,
            text=f"{self.value.get()}°",
            text_color=TEXT,
            font=_font(22, "bold", mono=True),
            anchor="e",
            width=76,
        )
        self.value_label.place(relx=1, rely=0.52, anchor="e")

        angle_labels = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        angle_labels.grid(row=0, column=2, sticky="ew", pady=(4, 0))
        angle_labels.grid_columnconfigure((0, 1, 2), weight=1, uniform="range")
        ctk.CTkLabel(
            angle_labels, text=f"{motor['min']}°", text_color=MUTED, font=_font(12, mono=True), anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=(11, 0))
        ctk.CTkLabel(
            angle_labels,
            text=f"{round((motor['min'] + motor['max']) / 2)}°",
            text_color=MUTED,
            font=_font(12, mono=True),
        ).grid(row=0, column=1)
        ctk.CTkLabel(
            angle_labels, text=f"{motor['max']}°", text_color=MUTED, font=_font(12, mono=True), anchor="e"
        ).grid(row=0, column=2, sticky="e", padx=(0, 11))

        self.scale = AngleSlider(
            self,
            minimum=motor["min"],
            maximum=motor["max"],
            value=motor["initial"],
            command=self._slider_changed,
        )
        self.scale.grid(row=1, column=2, sticky="ew", pady=(0, 5))
        self.scale.bind("<<SliderReleased>>", self._released)

        if divider:
            ctk.CTkFrame(self, height=1, fg_color=HAIRLINE, corner_radius=0).grid(
                row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0)
            )

    def _slider_changed(self, raw_value):
        angle = round(float(raw_value))
        self.value.set(angle)
        self.value_label.configure(text=f"{angle}°")
        if self.pending_send:
            self.after_cancel(self.pending_send)
        self.pending_send = self.after(
            config.SEND_INTERVAL_MS,
            lambda: self.on_change(self.motor["channel"], self.value.get()),
        )

    def _released(self, _event):
        if self.pending_send:
            self.after_cancel(self.pending_send)
            self.pending_send = None
        self.on_change(self.motor["channel"], self.value.get())

    def center(self):
        center = round((self.motor["min"] + self.motor["max"]) / 2)
        self.value.set(center)
        self.value_label.configure(text=f"{center}°")
        self.scale.set_value(center, notify=False)
        self.on_change(self.motor["channel"], center)

    def set_external_value(self, angle: int) -> int:
        """Synchronize a MediaPipe angle with the slider and its value label."""
        angle = min(self.motor["max"], max(self.motor["min"], round(angle)))
        if angle != self.value.get():
            self.value.set(angle)
            self.value_label.configure(text=f"{angle}°")
            self.scale.set_value(angle, notify=False)
        return angle


def _shadow_card(master, radius: int = 16):
    holder = ctk.CTkFrame(master, fg_color="transparent", corner_radius=0)
    surface = ctk.CTkFrame(
        holder,
        fg_color=SURFACE,
        border_width=1,
        border_color="#E1E1E5",
        corner_radius=radius,
    )
    surface.place(x=0, y=0, relwidth=1, relheight=1)
    return holder, surface


def build_ui(app):
    """Refined version of the user's preferred original light composition."""

    ctk.set_appearance_mode("light")
    app.window_icon = make_window_icon()
    if app.window_icon is not None:
        app.iconphoto(True, app.window_icon)
    icons = {
        "brand": load_brand_logo(28),
        "bluetooth": load_icon("bluetooth", TEXT, 18),
        "scan": load_icon("refresh", TEXT, 17),
        "connect": load_icon("link", "#FFFFFF", 17),
        "unlink": load_icon("unlink", TEXT, 17),
        "center": load_icon("target", TEXT, 16),
        "camera": load_icon("camera", "#86868B", 36),
        "play": load_icon("player-play", "#FFFFFF", 17),
        "stop": load_icon("player-stop", TEXT, 17),
        "info": load_icon("info-circle", MUTED, 16),
    }
    app.ui_icons = icons

    shell = ctk.CTkFrame(app, fg_color=BG, corner_radius=0)
    shell.pack(fill="both", expand=True, padx=30, pady=(22, 14))
    shell.grid_columnconfigure(0, weight=1)
    shell.grid_rowconfigure(2, weight=1)

    heading = ctk.CTkFrame(shell, fg_color="transparent", corner_radius=0)
    heading.grid(row=0, column=0, sticky="ew", pady=(0, 16))
    text_column = 1 if icons["brand"] is not None else 0
    heading.grid_columnconfigure(text_column, weight=1)
    if icons["brand"] is not None:
        mark = ctk.CTkFrame(heading, width=44, height=44, fg_color=ACTION, corner_radius=12)
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 13))
        mark.grid_propagate(False)
        ctk.CTkLabel(mark, text="", image=icons["brand"]).place(
            relx=0.5, rely=0.5, anchor="center"
        )
    ctk.CTkLabel(
        heading, text=config.APP_TITLE, text_color=TEXT, font=_font(25, "bold"), anchor="w"
    ).grid(row=0, column=text_column, sticky="sw")
    ctk.CTkLabel(
        heading, text="機器人手部控制台", text_color=MUTED, font=_font(11), anchor="w"
    ).grid(row=1, column=text_column, sticky="nw", pady=(1, 0))

    connection_holder, connection = _shadow_card(shell, radius=16)
    connection_holder.grid(row=1, column=0, sticky="ew", pady=(0, 16))
    connection_holder.configure(height=64)
    connection_holder.grid_propagate(False)
    connection.grid_columnconfigure(2, weight=1)
    ctk.CTkLabel(connection, text="", image=icons["bluetooth"], width=24).grid(
        row=0, column=0, padx=(18, 7), pady=12
    )
    ctk.CTkLabel(connection, text="藍牙裝置", text_color=TEXT, font=_font(12, "bold")).grid(
        row=0, column=1, padx=(0, 14)
    )

    app.device_box = DeviceCombo(
        connection,
        values=["尚未掃描裝置"],
        state="readonly",
        height=38,
        fg_color="#FBFBFD",
        border_color="#C7C7CC",
        button_color="#F0F0F3",
        button_hover_color="#E5E5E9",
        text_color=TEXT,
        dropdown_fg_color=SURFACE,
        dropdown_text_color=TEXT,
        dropdown_hover_color=CONTROL_HOVER,
        corner_radius=10,
        font=_font(12),
    )
    app.device_box.grid(row=0, column=2, sticky="ew", padx=(0, 10), pady=12)
    app.device_box.set("尚未掃描裝置")

    app.scan_button = StyledButton(
        connection,
        text="掃描",
        image=icons["scan"],
        command=app._scan,
        width=88,
        height=38,
        fg_color=CONTROL,
        hover_color=CONTROL_HOVER,
        text_color=TEXT,
        corner_radius=10,
        font=_font(12, "bold"),
    )
    app.scan_button.grid(row=0, column=3, padx=(0, 8), pady=12)
    app.connect_button = StyledButton(
        connection,
        text="連線",
        image=icons["connect"],
        command=app._connect,
        width=112,
        height=38,
        fg_color=ACTION,
        hover_color=ACTION_HOVER,
        text_color="#FFFFFF",
        corner_radius=10,
        font=_font(12, "bold"),
    )
    app.connect_button.grid(row=0, column=4, padx=(0, 18), pady=12)

    status = ctk.CTkFrame(connection, fg_color="transparent", corner_radius=0)
    status.grid(row=0, column=5, padx=(0, 18))
    app.status_dot = tk.Canvas(status, width=11, height=11, bg=SURFACE, highlightthickness=0)
    app.dot = app.status_dot.create_oval(2, 2, 9, 9, fill="#A3ABB7", outline="")
    app.status_dot.pack(side="left", padx=(0, 6))
    app.status_label = ctk.CTkLabel(
        status, text="尚未連線", width=82, anchor="w", text_color=MUTED, font=_font(11)
    )
    app.status_label.pack(side="left")

    workspace = ctk.CTkFrame(shell, fg_color="transparent", corner_radius=0)
    workspace.grid(row=2, column=0, sticky="nsew")
    workspace.grid_columnconfigure(0, weight=46, uniform="workspace")
    workspace.grid_columnconfigure(1, weight=54, uniform="workspace")
    workspace.grid_rowconfigure(0, weight=1)

    motor_holder, motor_panel = _shadow_card(workspace, radius=18)
    motor_holder.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
    motor_panel.grid_columnconfigure(0, weight=1)
    motor_panel.grid_rowconfigure(1, weight=1)
    motor_header = ctk.CTkFrame(motor_panel, fg_color="transparent", corner_radius=0)
    motor_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 7))
    motor_header.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(
        motor_header, text="馬達控制", text_color=TEXT, font=_font(17, "bold")
    ).grid(row=0, column=0, sticky="w")
    ctk.CTkButton(
        motor_header,
        text="全部置中",
        image=icons["center"],
        command=app._center_all,
        width=102,
        height=34,
        fg_color="#F2F2F4",
        hover_color="#E7E7EA",
        text_color=TEXT,
        border_width=1,
        border_color=HAIRLINE,
        corner_radius=10,
        font=_font(11, "bold"),
    ).grid(row=0, column=1)

    motor_list = ctk.CTkFrame(motor_panel, fg_color="transparent", corner_radius=0)
    motor_list.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 11))
    motor_list.grid_columnconfigure(0, weight=1)
    app.motor_rows = []
    for index, motor in enumerate(config.MOTORS):
        row = RefinedMotorRow(
            motor_list,
            motor,
            app._send_angle,
            divider=index < len(config.MOTORS) - 1,
        )
        row.grid(row=index, column=0, sticky="nsew")
        motor_list.grid_rowconfigure(index, weight=1, uniform="motor_rows")
        app.motor_rows.append(row)
        app.motor_rows_by_channel[motor["channel"]] = row

    hand_holder, hand_panel = _shadow_card(workspace, radius=18)
    hand_holder.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
    hand_panel.grid_columnconfigure(0, weight=1)
    hand_panel.grid_rowconfigure(1, weight=1)
    ctk.CTkLabel(
        hand_panel, text="MediaPipe Hands", text_color=TEXT, font=_font(17, "bold")
    ).grid(row=0, column=0, sticky="w", padx=18, pady=(15, 10))

    preview_frame = ctk.CTkFrame(
        hand_panel,
        fg_color="#F7F7F9",
        border_width=1,
        border_color="#E1E1E5",
        corner_radius=14,
    )
    preview_frame.grid(row=1, column=0, sticky="nsew", padx=18)
    preview_frame.grid_columnconfigure(0, weight=1)
    preview_frame.grid_rowconfigure(0, weight=1)
    app.camera_label = ctk.CTkLabel(
        preview_frame,
        text="攝影機預覽\n開啟後顯示手部辨識畫面",
        image=icons["camera"],
        compound="top",
        fg_color="#F7F7F9",
        text_color=MUTED,
        font=_font(13),
        corner_radius=13,
    )
    app.camera_label.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)

    action_bar = ctk.CTkFrame(hand_panel, fg_color="transparent", corner_radius=0)
    action_bar.grid(row=2, column=0, sticky="ew", padx=18, pady=(12, 7))
    action_bar.grid_columnconfigure(1, weight=1)
    app.hand_status_dot = tk.Canvas(
        action_bar, width=11, height=11, bg=SURFACE, highlightthickness=0
    )
    app.hand_dot = app.hand_status_dot.create_oval(2, 2, 9, 9, fill="#A3ABB7", outline="")
    app.hand_status_dot.grid(row=0, column=0, padx=(0, 6))
    app.hand_status_label = ctk.CTkLabel(
        action_bar, text="手部辨識尚未啟動", text_color=MUTED, anchor="w", font=_font(11)
    )
    app.hand_status_label.grid(row=0, column=1, sticky="w")
    app.hand_button = StyledButton(
        action_bar,
        text="開啟手部辨識",
        image=icons["play"],
        command=app._toggle_hand_tracking,
        width=152,
        height=38,
        fg_color=ACTION,
        hover_color=ACTION_HOVER,
        text_color="#FFFFFF",
        corner_radius=10,
        font=_font(12, "bold"),
    )
    app.hand_button.grid(row=0, column=2)

    ctk.CTkLabel(
        hand_panel,
        text="只追蹤左手 · 食指至小指控制馬達 0～3",
        text_color=MUTED,
        font=_font(10),
    ).grid(row=3, column=0, pady=(0, 12))
    ctk.CTkLabel(
        shell,
        text="滑桿名稱、初始值與角度範圍可在 config.py 修改",
        text_color=MUTED,
        font=_font(10),
    ).grid(row=3, column=0, pady=(9, 0))
