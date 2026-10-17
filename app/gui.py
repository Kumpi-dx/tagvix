import logging
import os
import queue
import threading
from datetime import datetime

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk

from .config_loader import Config
from .logger_setup import setup_logging
from .middleware import Middleware
from .paths import resource_path
from .tags import parse_tags

COLORS = {
    "bg": "#eef1f6",
    "bg2": "#e4e9f1",
    "header": "#ffffff",
    "panel": "#ffffff",
    "panel2": "#f4f6fb",
    "panel3": "#e9edf5",
    "border": "#ccd4e0",
    "border_strong": "#aab6c8",
    "shadow": "#c2c9d6",
    "shadow_soft": "#dbe0e9",
    "text": "#0f172a",
    "muted": "#475569",
    "accent": "#f97316",
    "accent_hover": "#ea580c",
    "accent_dark": "#b8420a",
    "accent_soft": "#fff3e7",
    "good": "#16a34a",
    "good_hover": "#15803d",
    "good_dark": "#0f5132",
    "good_soft": "#e9f7ef",
    "bad": "#dc2626",
    "bad_hover": "#b91c1c",
    "bad_dark": "#7f1d1d",
    "bad_soft": "#fdecec",
    "white": "#ffffff",
}

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


def fmt_value(value):
    if value is None:
        return "---"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    if abs(number) >= 1e6 or (0 < abs(number) < 1e-3):
        return "{:.4e}".format(number)
    return "{:.4f}".format(number).rstrip("0").rstrip(".")


class QueueLogHandler(logging.Handler):
    def __init__(self, target_queue):
        super().__init__()
        self.target_queue = target_queue

    def emit(self, record):
        try:
            self.target_queue.put(("log", record.levelno, self.format(record)))
        except Exception:
            pass


def save_config_file(path, scalars, tag_lines):
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    out = []
    section = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            out.append(line)
            i += 1
            if section == "tags":
                while i < len(lines):
                    nxt = lines[i].strip()
                    if nxt.startswith("[") and nxt.endswith("]"):
                        break
                    i += 1
                out.extend(tag_lines)
                continue
            continue
        if stripped and not stripped.startswith((";", "#")) and "=" in line:
            key = line.split("=", 1)[0].strip()
            lookup = (section, key.lower())
            if lookup in scalars:
                indent = line[: len(line) - len(line.lstrip())]
                out.append("{}{} = {}".format(indent, key, scalars[lookup]))
                i += 1
                continue
        out.append(line)
        i += 1

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


FIELD_MAP = {
    "protocol": ("plc", "protocol"),
    "port": ("plc", "port"),
    "baudrate": ("plc", "baudrate"),
    "bytesize": ("plc", "bytesize"),
    "parity": ("plc", "parity"),
    "stopbits": ("plc", "stopbits"),
    "unit_no": ("plc", "unit_no"),
    "slave_id": ("plc", "slave_id"),
    "tcp_host": ("plc", "tcp_host"),
    "tcp_port": ("plc", "tcp_port"),
    "fins_host": ("plc", "fins_host"),
    "fins_port": ("plc", "fins_port"),
    "fins_dest_node": ("plc", "fins_dest_node"),
    "fins_src_node": ("plc", "fins_src_node"),
    "address_base": ("plc", "address_base"),
    "word_order": ("plc", "word_order"),
    "timeout": ("plc", "timeout"),
    "retries": ("plc", "retries"),
    "simulate": ("plc", "simulate"),
    "interval": ("polling", "interval"),
    "reconnect_delay": ("polling", "reconnect_delay"),
    "db_host": ("database", "host"),
    "db_port": ("database", "port"),
    "db_user": ("database", "user"),
    "db_password": ("database", "password"),
    "db_name": ("database", "database"),
    "table_reg": ("database", "table_reg"),
    "table_transmit": ("database", "table_transmit"),
    "dev_name": ("database", "dev_name"),
    "group_name": ("database", "group_name"),
    "db_enabled": ("database", "enabled"),
    "autocreate": ("database", "autocreate"),
}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TagVix - Omron / Modbus")
        self.geometry("1000x660")
        self.minsize(880, 560)
        self.configure(fg_color=COLORS["bg"])
        self._apply_icon()

        self.log_queue = queue.Queue()
        self.event_queue = queue.Queue()
        self.row_ids = {}
        self.mw = None
        self.worker = None
        self.config = None
        self.log = None
        self.log_handler = None
        self.widgets = {}
        self.cards = {}
        self._toasts = []

        self._build_style()
        self._build_layout()
        self._load_config(show_error=True)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self._drain_queues)

    def _apply_icon(self):
        try:
            ico = resource_path("icon.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
                return
        except Exception:
            pass
        try:
            png = resource_path("icon.png")
            if os.path.isfile(png):
                img = tk.PhotoImage(file=png)
                self.iconphoto(True, img)
                self._icon_img = img
        except Exception:
            pass

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Industrial.Treeview",
            background=COLORS["panel"],
            fieldbackground=COLORS["panel"],
            foreground=COLORS["text"],
            rowheight=48,
            borderwidth=0,
            font=("Segoe UI", 13, "bold"),
        )
        style.map(
            "Industrial.Treeview",
            background=[("selected", COLORS["accent"])],
            foreground=[("selected", COLORS["white"])],
        )
        style.configure(
            "Industrial.Treeview.Heading",
            background=COLORS["header"],
            foreground=COLORS["text"],
            relief="flat",
            padding=(10, 12),
            font=("Segoe UI", 11, "bold"),
        )
        style.map("Industrial.Treeview.Heading",
                  background=[("active", COLORS["panel3"])])

    def _build_layout(self):
        self._build_header()

        self.tabbar = ctk.CTkFrame(self, fg_color="transparent")
        self.tabbar.pack(fill="x", padx=12, pady=(8, 0))

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=12, pady=(6, 4))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        builders = [
            ("Monitor", "\u25c9  Monitor", self._build_monitor),
            ("Settings", "\u2699  Settings", self._build_settings),
            ("Log", "\u2261  Log", self._build_log),
        ]
        self.tabs = {}
        self.tab_buttons = {}
        for name, label, builder in builders:
            btn = ctk.CTkButton(
                self.tabbar, text=label, width=140, height=38, corner_radius=9,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda n=name: self._select_tab(n),
            )
            btn.pack(side="left", padx=(0, 8))
            self.tab_buttons[name] = btn
            frame = ctk.CTkFrame(self.content, fg_color="transparent")
            frame.grid(row=0, column=0, sticky="nsew")
            builder(frame)
            self.tabs[name] = frame

        self._build_statusbar()
        self._select_tab("Monitor")

    def _select_tab(self, name):
        frame = self.tabs.get(name)
        if frame is None:
            return
        frame.tkraise()
        for key, btn in self.tab_buttons.items():
            if key == name:
                btn.configure(fg_color=COLORS["accent"], text_color=COLORS["white"],
                              hover_color=COLORS["accent_hover"], border_width=0)
            else:
                btn.configure(fg_color=COLORS["panel"], text_color=COLORS["muted"],
                              hover_color=COLORS["panel2"], border_width=1,
                              border_color=COLORS["border"])


    def _build_header(self):
        strip = ctk.CTkFrame(self, fg_color=COLORS["accent"], corner_radius=0, height=4)
        strip.pack(fill="x")

        header = ctk.CTkFrame(self, fg_color=COLORS["header"], corner_radius=0, height=68)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=(16, 8), pady=8)

        logo = ctk.CTkFrame(title_box, fg_color=COLORS["accent"], width=42, height=42,
                            corner_radius=12)
        logo.pack(side="left", padx=(0, 12))
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="\u25a3", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=COLORS["white"]).pack(expand=True)

        text_box = ctk.CTkFrame(title_box, fg_color="transparent")
        text_box.pack(side="left")
        ctk.CTkLabel(text_box, text="TAGVIX",
                     font=ctk.CTkFont(size=19, weight="bold"),
                     text_color=COLORS["text"]).pack(anchor="w")
        ctk.CTkLabel(text_box, text="Omron Host Link / FINS  \u00b7  Modbus RTU/TCP  \u2192  MySQL",
                     font=ctk.CTkFont(size=11), text_color=COLORS["muted"]).pack(anchor="w")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right", padx=(0, 14))

        self.btn_start = self._btn(
            actions, "\u25b6  Start", self.on_start, kind="good", width=104, height=38,
            pack={"side": "left", "padx": 6},
        )
        self.btn_stop = self._btn(
            actions, "\u25a0  Stop", self.on_stop, kind="bad", width=104, height=38,
            pack={"side": "left", "padx": 6},
        )
        self.btn_stop.configure(state="disabled")

        sep = ctk.CTkFrame(header, fg_color=COLORS["border"], width=1, height=36)
        sep.pack(side="right", padx=8)
        sep.pack_propagate(False)

        status = ctk.CTkFrame(header, fg_color="transparent")
        status.pack(side="right")

        def make_led(text):
            pill = ctk.CTkFrame(status, fg_color=COLORS["panel2"], corner_radius=10,
                                border_width=1, border_color=COLORS["border"])
            pill.pack(side="left", padx=5)

            inner = ctk.CTkFrame(pill, fg_color="transparent")
            inner.pack(padx=11, pady=6)
            dot = ctk.CTkLabel(inner, text="\u25cf", font=ctk.CTkFont(size=13),
                               text_color=COLORS["muted"])
            dot.pack(side="left", padx=(0, 7))
            ctk.CTkLabel(inner, text=text, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=COLORS["text"]).pack(side="left")
            return dot, pill

        self.plc_led, self.plc_pill = make_led("PLC")
        self.db_led, self.db_pill = make_led("DB")

    def _reset_leds(self):
        for pill in (self.plc_pill, self.db_pill):
            pill.configure(fg_color=COLORS["panel2"], border_color=COLORS["border"])
        for led in (self.plc_led, self.db_led):
            led.configure(text_color=COLORS["muted"])

    def _build_monitor(self, parent):
        table_wrap = ctk.CTkFrame(parent, fg_color=COLORS["panel"], corner_radius=12,
                                  border_width=1, border_color=COLORS["border"])
        table_wrap.pack(fill="both", expand=True, padx=5, pady=(6, 6))

        thead = ctk.CTkFrame(table_wrap, fg_color="transparent")
        thead.pack(fill="x", padx=18, pady=(14, 8))
        bar = ctk.CTkFrame(thead, fg_color=COLORS["accent"], width=5, height=20,
                           corner_radius=2)
        bar.pack(side="left", padx=(0, 10))
        bar.pack_propagate(False)
        ctk.CTkLabel(thead, text="LIVE TAG READINGS",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left")
        self.tree_count = ctk.CTkLabel(thead, text="0 tag",
                                       font=ctk.CTkFont(size=12),
                                       text_color=COLORS["muted"])
        self.tree_count.pack(side="right")

        tree_area = ctk.CTkFrame(table_wrap, fg_color="transparent")
        tree_area.pack(fill="both", expand=True, padx=(10, 8), pady=(0, 10))

        columns = ("tag", "address", "value", "unit", "quality", "time")
        self.tree = ttk.Treeview(tree_area, columns=columns, show="headings",
                                 style="Industrial.Treeview")
        headings = {
            "tag": ("TAG", 240, "center"), "address": ("ADDRESS", 170, "center"),
            "value": ("VALUE", 220, "center"), "unit": ("UNIT", 110, "center"),
            "quality": ("QUALITY", 130, "center"), "time": ("TIME", 160, "center"),
        }
        for col, (text, width, anchor) in headings.items():
            self.tree.heading(col, text=text, anchor="center")
            self.tree.column(col, width=width, minwidth=90, anchor=anchor,
                             stretch=True)

        self.tree.tag_configure("even", background=COLORS["panel"])
        self.tree.tag_configure("odd", background=COLORS["panel2"])
        self.tree.tag_configure("bad", foreground=COLORS["bad"])
        self.tree.tag_configure("good", foreground=COLORS["text"])

        scroll = ttk.Scrollbar(tree_area, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll.pack(side="right", fill="y", pady=10, padx=(0, 8))

    def _build_settings(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=COLORS["panel2"], corner_radius=0, height=58)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self.save_hint = ctk.CTkLabel(
            bar, text="Pengaturan disimpan ke file config.ini",
            font=ctk.CTkFont(size=11), text_color=COLORS["muted"],
        )
        self.save_hint.pack(side="left", padx=14)
        self._btn(
            bar, "Simpan & Terapkan", self.on_save, kind="accent",
            width=190, height=38, font=ctk.CTkFont(size=12, weight="bold"),
            pack={"side": "right", "padx": 14, "pady": 10},
        )
        self._btn(
            bar, "Muat Ulang", self._load_config, kind="ghost",
            width=128, height=38, font=ctk.CTkFont(size=12, weight="bold"),
            pack={"side": "right", "padx": 8, "pady": 10},
        )

        container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        container.grid_columnconfigure(0, weight=1)

        row = 0
        body = self._card(container, row, "protocol", "Protokol & Mode")
        row += 1
        self._field(body, 0, 0, "Protokol", "protocol",
                    values=["hostlink", "modbus_rtu", "modbus_tcp", "fins_tcp"],
                    on_change=self._on_protocol_change)
        self._switch(body, 0, 1, "Simulasi (tanpa perangkat)", "simulate")
        self.proto_desc = ctk.CTkLabel(
            body, text="", font=ctk.CTkFont(size=11), text_color=COLORS["muted"],
            justify="left", anchor="w", wraplength=780,
        )
        self.proto_desc.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 0))

        body = self._card(container, row, "serial", "Komunikasi Serial")
        row += 1
        self._field(body, 0, 0, "Port", "port")
        self._field(body, 0, 1, "Baudrate", "baudrate")
        self._field(body, 1, 0, "Data bits", "bytesize", values=["7", "8"])
        self._field(body, 1, 1, "Parity", "parity", values=["N", "E", "O"])
        self._field(body, 2, 0, "Stop bits", "stopbits", values=["1", "2"])

        body = self._card(container, row, "hostlink", "Host Link (Omron)")
        row += 1
        self._field(body, 0, 0, "Unit No (0-31)", "unit_no")

        body = self._card(container, row, "modbus", "Modbus")
        row += 1
        self._field(body, 0, 0, "Slave ID (1-247)", "slave_id")
        self._field(body, 0, 1, "Address base (0/1)", "address_base", values=["0", "1"])
        self._field(body, 1, 0, "Word order 32-bit", "word_order", values=["little", "big"])

        body = self._card(container, row, "tcp", "Modbus TCP")
        row += 1
        self._field(body, 0, 0, "Host / IP", "tcp_host")
        self._field(body, 0, 1, "TCP port", "tcp_port")

        body = self._card(container, row, "fins", "Omron FINS/TCP")
        row += 1
        self._field(body, 0, 0, "Host / IP", "fins_host")
        self._field(body, 0, 1, "TCP port (default 9600)", "fins_port")
        self._field(body, 1, 0, "Dest node (0-254)", "fins_dest_node")
        self._field(body, 1, 1, "Source node (0-254)", "fins_src_node")

        body = self._card(container, row, "polling", "Polling & Timeout")
        row += 1
        self._field(body, 0, 0, "Interval (detik)", "interval")
        self._field(body, 0, 1, "Reconnect delay (detik)", "reconnect_delay")
        self._field(body, 1, 0, "Timeout (detik)", "timeout")
        self._field(body, 1, 1, "Retries", "retries")

        body = self._card(container, row, "database", "Database (MySQL)")
        row += 1
        self._field(body, 0, 0, "Host", "db_host")
        self._field(body, 0, 1, "Port", "db_port")
        self._field(body, 1, 0, "User", "db_user")
        self._field(body, 1, 1, "Password", "db_password", show="*")
        self._field(body, 2, 0, "Database", "db_name")
        self._field(body, 3, 0, "Tabel baca (status)", "table_reg")
        self._field(body, 3, 1, "Tabel tulis (transmit)", "table_transmit")
        self._field(body, 4, 0, "DEV_NAME", "dev_name")
        self._field(body, 4, 1, "GROUP_NAME", "group_name")
        self._switch(body, 5, 0, "Aktifkan penyimpanan DB", "db_enabled")
        self._switch(body, 5, 1, "Auto-create DB/tabel", "autocreate")

        body = self._card(
            container, row, "tags", "Definisi Tag",
            subtitle="Format: NAMA = AREA:ALAMAT:TIPE:SCALE:UNIT   (satu tag per baris)",
        )
        row += 1
        self.tags_text = ctk.CTkTextbox(
            body, height=170, fg_color=COLORS["panel2"], text_color=COLORS["text"],
            font=ctk.CTkFont(family="Consolas", size=12), corner_radius=8,
            border_width=2, border_color=COLORS["border"],
        )
        self.tags_text.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6)
        self.tags_hint = ctk.CTkLabel(
            body, text="", font=ctk.CTkFont(size=11), text_color=COLORS["accent"],
            justify="left", anchor="w", wraplength=780,
        )
        self.tags_hint.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 0))

    def _build_log(self, parent):
        self.log_text = ctk.CTkTextbox(
            parent, fg_color=COLORS["panel"], text_color=COLORS["text"],
            font=ctk.CTkFont(family="Consolas", size=12), corner_radius=10,
        )
        self.log_text.pack(fill="both", expand=True, padx=4, pady=6)
        self.log_text.configure(state="disabled")

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color=COLORS["header"], corner_radius=0, height=26)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status_label = ctk.CTkLabel(bar, text="Siap.",
                                         font=ctk.CTkFont(size=11),
                                         text_color=COLORS["muted"])
        self.status_label.pack(side="left", padx=12)
        self.clock_label = ctk.CTkLabel(bar, text="", font=ctk.CTkFont(size=11),
                                        text_color=COLORS["muted"])
        self.clock_label.pack(side="right", padx=12)
        self.proto_label = ctk.CTkLabel(bar, text="", font=ctk.CTkFont(size=10),
                                        text_color=COLORS["muted"])
        self.proto_label.pack(side="right", padx=8)

    def _btn(self, parent, text, command, kind="accent", width=140, height=40,
             font=None, pack=None):
        palettes = {
            "accent": (COLORS["accent"], COLORS["accent_hover"],
                       COLORS["accent_dark"], COLORS["white"]),
            "good": (COLORS["good"], COLORS["good_hover"],
                     COLORS["good_dark"], COLORS["white"]),
            "bad": (COLORS["bad"], COLORS["bad_hover"],
                    COLORS["bad_dark"], COLORS["white"]),
            "ghost": (COLORS["white"], COLORS["panel2"],
                      COLORS["border"], COLORS["text"]),
        }
        fg, hover, border, txt = palettes[kind]
        font = font or ctk.CTkFont(size=13, weight="bold")
        btn = ctk.CTkButton(
            parent, text=text, command=command, width=width, height=height,
            corner_radius=9, fg_color=fg, hover_color=hover, border_width=2,
            border_color=border, font=font, text_color=txt,
        )
        if pack:
            btn.pack(**pack)
        return btn

    def _card(self, parent, row, key, title, subtitle=None):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 12))
        container.grid_columnconfigure(0, weight=1)

        shadow = ctk.CTkFrame(container, fg_color=COLORS["shadow_soft"], corner_radius=13)
        shadow.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=(4, 0))

        card = ctk.CTkFrame(container, fg_color=COLORS["panel"], corner_radius=12,
                            border_width=1, border_color=COLORS["border"])
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 4))
        card.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(13, 2))
        accent = ctk.CTkFrame(head, fg_color=COLORS["accent"], width=4, height=18,
                              corner_radius=2)
        accent.pack(side="left", padx=(0, 8))
        accent.pack_propagate(False)
        ctk.CTkLabel(head, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left")

        divider = ctk.CTkFrame(card, fg_color=COLORS["border"], height=1, corner_radius=0)
        divider.grid(row=1, column=0, sticky="ew", padx=14, pady=(8, 0))

        body_row = 2
        if subtitle:
            ctk.CTkLabel(card, text=subtitle, font=ctk.CTkFont(size=11),
                         text_color=COLORS["muted"], justify="left", anchor="w",
                         wraplength=780).grid(row=2, column=0, sticky="w",
                                              padx=14, pady=(6, 0))
            body_row = 3

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=body_row, column=0, sticky="ew", padx=8, pady=(8, 14))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        self.cards[key] = container
        return body

    def _field(self, body, row, col, label, key, show=None, values=None, on_change=None):
        cell = ctk.CTkFrame(body, fg_color="transparent")
        cell.grid(row=row, column=col, sticky="ew", padx=6, pady=5)
        cell.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(cell, text=label, width=150, anchor="w",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["muted"]).grid(row=0, column=0, sticky="w")
        if values is not None:
            var = ctk.StringVar(value=str(values[0]))
            wrap = ctk.CTkFrame(cell, fg_color=COLORS["panel"], corner_radius=9,
                                border_width=2, border_color=COLORS["border"])
            wrap.grid(row=0, column=1, sticky="ew")
            wrap.grid_columnconfigure(0, weight=1)
            widget = ctk.CTkOptionMenu(
                wrap, values=[str(v) for v in values], variable=var, height=32,
                corner_radius=8, fg_color=COLORS["panel2"], button_color=COLORS["panel2"],
                button_hover_color=COLORS["accent"], text_color=COLORS["text"],
                dropdown_fg_color=COLORS["panel2"], dropdown_text_color=COLORS["text"],
                command=on_change,
            )
            widget.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
            wrap.bind("<Enter>",
                      lambda e, w=wrap: w.configure(border_color=COLORS["border_strong"]))
            wrap.bind("<Leave>",
                      lambda e, w=wrap: w.configure(border_color=COLORS["border"]))
            self.widgets[key] = ("menu", var)
            return widget
        entry = ctk.CTkEntry(cell, height=32, corner_radius=8, fg_color=COLORS["panel2"],
                             border_width=2, border_color=COLORS["border"],
                             text_color=COLORS["text"], show=show)
        entry.grid(row=0, column=1, sticky="ew")
        entry.bind("<FocusIn>",
                   lambda e, w=entry: w.configure(border_color=COLORS["accent"]))
        entry.bind("<FocusOut>",
                   lambda e, w=entry: w.configure(border_color=COLORS["border"]))
        self.widgets[key] = ("entry", entry)
        return entry

    def _switch(self, body, row, col, label, key):
        cell = ctk.CTkFrame(body, fg_color="transparent")
        cell.grid(row=row, column=col, sticky="w", padx=6, pady=5)
        var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(cell, text=label, variable=var, font=ctk.CTkFont(size=12),
                      text_color=COLORS["text"], progress_color=COLORS["accent"],
                      button_color=COLORS["white"], button_hover_color="#fed7aa"
                      ).pack(anchor="w")
        self.widgets[key] = ("check", var)

    def _load_config(self, show_error=False):
        try:
            self.config = Config()
        except Exception as exc:
            if show_error:
                self.toast("Konfigurasi tidak valid", str(exc), kind="error")
            self.config = None
            self._update_protocol_label()
            return False

        if self.log is None:
            self.log = setup_logging(
                level=self.config.log_level, log_file=self.config.log_file,
                max_bytes=self.config.log_max_bytes,
                backup_count=self.config.log_backup_count, console=False,
            )
        if getattr(self, "log_handler", None) is not None:
            self.log.removeHandler(self.log_handler)
        self.log_handler = QueueLogHandler(self.log_queue)
        self.log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        self.log.addHandler(self.log_handler)

        self._populate_fields()
        self._populate_tags()
        self._populate_tree()
        self.status_label.configure(text="Config: " + self.config.path)
        return True

    def _populate_fields(self):
        c = self.config
        values = {
            "protocol": c.protocol, "port": c.port, "baudrate": c.baudrate,
            "bytesize": c.bytesize, "parity": c.parity, "stopbits": c.stopbits,
            "unit_no": c.unit_no, "slave_id": c.slave_id, "timeout": c.timeout,
            "retries": c.retries, "interval": c.interval,
            "reconnect_delay": c.reconnect_delay, "tcp_host": c.tcp_host,
            "tcp_port": c.tcp_port, "address_base": c.address_base,
            "fins_host": c.fins_host, "fins_port": c.fins_port,
            "fins_dest_node": c.fins_dest_node, "fins_src_node": c.fins_src_node,
            "word_order": c.word_order, "db_host": c.db_host,
            "db_port": c.db_port, "db_user": c.db_user, "db_password": c.db_password,
            "db_name": c.db_name, "table_reg": c.table_reg,
            "table_transmit": c.table_transmit, "dev_name": c.dev_name,
            "group_name": c.group_name,
        }
        for key, value in values.items():
            kind, widget = self.widgets[key]
            if kind == "menu":
                if isinstance(value, float) and value == int(value):
                    value = int(value)
                widget.set(str(value))
            else:
                widget.delete(0, "end")
                widget.insert(0, str(value))
        checks = {"simulate": c.simulate, "db_enabled": c.db_enabled,
                  "autocreate": c.autocreate}
        for key, value in checks.items():
            self.widgets[key][1].set(bool(value))
        self._apply_protocol_state()
        self._update_protocol_label()

    def _on_protocol_change(self, _value=None):
        if getattr(self, "widgets", None):
            self._apply_protocol_state()

    def _apply_protocol_state(self):
        if "protocol" not in self.widgets:
            return
        proto = self.widgets["protocol"][1].get()
        visible = {
            "serial": proto in ("hostlink", "modbus_rtu"),
            "hostlink": proto == "hostlink",
            "modbus": proto in ("modbus_rtu", "modbus_tcp"),
            "tcp": proto == "modbus_tcp",
            "fins": proto == "fins_tcp",
        }
        for key, card in getattr(self, "cards", {}).items():
            if key not in visible:
                continue
            if visible[key]:
                card.grid()
            else:
                card.grid_remove()

        if proto == "hostlink":
            desc = ("Omron Host Link (C-mode) melalui port serial. "
                    "Baca area: DM | CIO | IR | LR.")
            hint = "AREA: DM | CIO | IR | LR    contoh: motor = CIO:0.00:BIT:1:"
        elif proto == "fins_tcp":
            desc = ("Omron FINS/TCP via Ethernet (CJ2M, CS, CP). "
                    "Area: DM | CIO | WR | HR | AR.")
            hint = "AREA: DM | CIO | WR | HR | AR    contoh: motor = CIO:0.00:BIT:1:"
        elif proto == "modbus_rtu":
            desc = ("Modbus RTU melalui port serial (RS-232 / RS-485). "
                    "Area: HR (holding), IR (input), CO (coil), DI (discrete).")
            hint = "AREA: HR | IR | CO | DI   (4x=HR, 3x=IR, 0x=CO, 1x=DI)"
        else:
            desc = ("Modbus TCP melalui jaringan Ethernet. "
                    "Area: HR (holding), IR (input), CO (coil), DI (discrete).")
            hint = "AREA: HR | IR | CO | DI   (4x=HR, 3x=IR, 0x=CO, 1x=DI)"

        if getattr(self, "proto_desc", None) is not None:
            self.proto_desc.configure(text=desc)
        if getattr(self, "tags_hint", None) is not None:
            self.tags_hint.configure(text=hint)

    def _update_protocol_label(self):
        label = getattr(self, "proto_label", None)
        if label is None:
            return
        cfg = self.config
        if cfg is None:
            label.configure(text="")
            return
        proto = cfg.protocol
        if proto == "hostlink":
            text = "Host Link @ {}".format(cfg.port)
        elif proto == "modbus_rtu":
            text = "Modbus RTU @ {}".format(cfg.port)
        elif proto == "modbus_tcp":
            text = "Modbus TCP @ {}:{}".format(cfg.tcp_host, cfg.tcp_port)
        elif proto == "fins_tcp":
            text = "FINS/TCP @ {}:{}".format(cfg.fins_host, cfg.fins_port)
        else:
            text = proto
        label.configure(text="Protokol: " + text)

    def _populate_tags(self):
        self.tags_text.delete("1.0", "end")
        for name, spec in self.config.tags:
            self.tags_text.insert("end", "{} = {}\n".format(name, spec))

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.row_ids = {}
        for idx, tag in enumerate(parse_tags(self.config.tags)):
            item = self.tree.insert(
                "", "end",
                values=(tag.name, tag.address_label, "---", tag.unit, "---", "--:--:--"),
                tags=("odd" if idx % 2 else "even",),
            )
            self.row_ids[tag.name] = item
        if getattr(self, "tree_count", None) is not None:
            self.tree_count.configure(text="{} tag".format(len(self.row_ids)))

    def toast(self, title, message="", kind="info", duration=3600):
        try:
            self.update_idletasks()
            accent = {"info": COLORS["accent"], "success": COLORS["good"],
                      "error": COLORS["bad"], "warn": "#d97706"}.get(kind, COLORS["accent"])
            mark = {"info": "\u2139", "success": "\u2714",
                    "error": "\u2716", "warn": "\u26a0"}.get(kind, "\u2139")
            try:
                scale = self._get_window_scaling() or 1.0
            except Exception:
                scale = 1.0
            width = 300
            rw, rh = self.winfo_width(), self.winfo_height()
            x = self.winfo_rootx() + rw - width - 20

            win = ctk.CTkToplevel(self)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(fg_color=accent)

            card = ctk.CTkFrame(win, fg_color=COLORS["panel"], corner_radius=10,
                                border_width=1, border_color=COLORS["border"])
            card.pack(fill="both", expand=True)
            bar = ctk.CTkFrame(card, fg_color=accent, width=4, corner_radius=0)
            bar.pack(side="left", fill="y")
            bar.pack_propagate(False)
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(side="left", fill="both", expand=True, padx=10, pady=6)
            ctk.CTkLabel(body, text="{}  {}".format(mark, title),
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=COLORS["text"]).pack(anchor="w")
            if message:
                ctk.CTkLabel(body, text=message, font=ctk.CTkFont(size=10),
                             text_color=COLORS["muted"], justify="left", anchor="w",
                             wraplength=width - 44).pack(anchor="w", pady=(2, 0))

            win.update_idletasks()
            h = max(body.winfo_reqheight() + 4, 40)
            offset = 0
            for tw in list(self._toasts):
                try:
                    offset += tw.winfo_height() + 8
                except Exception:
                    pass
            y = self.winfo_rooty() + rh - h - 40 - offset
            w_set = max(1, int(round(width / scale)))
            h_set = max(1, int(round(h / scale)))
            win.geometry("{}x{}+{}+{}".format(w_set, h_set, x, y))
            win.attributes("-alpha", 0.0)
            self._toasts.append(win)
            self._fade(win, 0.0, 1.0)
            win.after(duration, lambda: self._dismiss_toast(win))
        except Exception:
            pass

    def _fade(self, win, start, end, step=0.10):
        try:
            val = start + (end - start) * step
            win.attributes("-alpha", max(0.0, min(1.0, val)))
            if step < 1.0:
                win.after(16, lambda: self._fade(win, start, end, step + 0.12))
        except Exception:
            pass

    def _dismiss_toast(self, win):
        try:
            if win in self._toasts:
                self._toasts.remove(win)
            win.destroy()
        except Exception:
            pass

    def ask(self, title, message, yes="Ya", no="Batal", kind="question", danger=False):
        result = {"v": False}
        try:
            dlg = ctk.CTkToplevel(self)
            dlg.title(title)
            dlg.configure(fg_color=COLORS["bg"])
            dlg.resizable(False, False)
            dlg.transient(self)

            accent = {"question": COLORS["accent"], "warning": "#d97706",
                      "error": COLORS["bad"]}.get(kind, COLORS["accent"])
            card = ctk.CTkFrame(dlg, fg_color=COLORS["panel"], corner_radius=12,
                                border_width=1, border_color=COLORS["border"])
            card.pack(fill="both", expand=True, padx=1, pady=1)

            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=16, pady=(14, 4))
            bar = ctk.CTkFrame(head, fg_color=accent, width=4, height=18, corner_radius=2)
            bar.pack(side="left", padx=(0, 8))
            bar.pack_propagate(False)
            ctk.CTkLabel(head, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=COLORS["text"]).pack(side="left")
            ctk.CTkLabel(card, text=message, font=ctk.CTkFont(size=12),
                         text_color=COLORS["muted"], justify="left", anchor="w",
                         wraplength=360).pack(fill="x", padx=16, pady=(2, 16))

            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.pack(fill="x", padx=16, pady=(0, 16))

            def close(val):
                result["v"] = val
                try:
                    dlg.grab_release()
                except Exception:
                    pass
                dlg.destroy()

            ctk.CTkButton(btns, text=no, width=112, height=36, corner_radius=8,
                          fg_color=COLORS["panel"], hover_color=COLORS["panel2"],
                          text_color=COLORS["text"], border_width=1,
                          border_color=COLORS["border"],
                          command=lambda: close(False)).pack(side="right", padx=(8, 0))
            ctk.CTkButton(btns, text=yes, width=112, height=36, corner_radius=8,
                          fg_color=COLORS["bad"] if danger else COLORS["accent"],
                          hover_color=COLORS["bad_hover"] if danger else COLORS["accent_hover"],
                          text_color=COLORS["white"],
                          command=lambda: close(True)).pack(side="right")

            dlg.update_idletasks()
            w = max(dlg.winfo_reqwidth(), 320)
            h = dlg.winfo_reqheight()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            rw, rh = self.winfo_width(), self.winfo_height()
            dlg.geometry("{}x{}+{}+{}".format(w, h, rx + (rw - w) // 2, ry + (rh - h) // 2))
            dlg.bind("<Escape>", lambda e: close(False))
            dlg.protocol("WM_DELETE_WINDOW", lambda: close(False))
            dlg.grab_set()
            dlg.focus_force()
            self.wait_window(dlg)
        except Exception:
            pass
        return result["v"]

    def on_start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        if self.config is None:
            self.toast("Konfigurasi tidak valid", "Periksa tab Settings.", kind="error")
            return

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._reset_leds()
        self.status_label.configure(text="Menjalankan...")

        try:
            self.mw = Middleware(self.config, self.log,
                                 on_reading=self._on_reading, on_status=self._on_status)
            self.worker = threading.Thread(target=self._run_worker, daemon=True)
            self.worker.start()
        except Exception as exc:
            self.log.exception("Gagal start: %s", exc)
            self.mw = None
            self.worker = None
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.status_label.configure(text="Gagal start.")
            self.toast("Gagal menjalankan", str(exc), kind="error")
            return
        self.toast("TagVix dijalankan", "Mulai membaca data perangkat.", kind="success")

    def _run_worker(self):
        code = 1
        try:
            code = self.mw.run()
        except Exception as exc:
            self.log.exception("Worker error: %s", exc)
        self.event_queue.put(("stopped", code))

    def _on_reading(self, readings, ts, duration):
        self.event_queue.put(("reading", readings, ts, duration))

    def _on_status(self, component, ok, message):
        self.event_queue.put(("status", component, ok, message))

    def on_stop(self):
        worker_alive = self.worker is not None and self.worker.is_alive()
        if self.mw is None and not worker_alive:
            return
        self.status_label.configure(text="Menghentikan...")
        self.btn_stop.configure(state="disabled")
        self.toast("Menghentikan TagVix", "Menunggu siklus berhenti...",
                   kind="info", duration=2200)
        if self.mw is not None:
            self.mw.stop()
        self._stop_watchdog(0)

    def _stop_watchdog(self, ticks):
        if self.worker is None or not self.worker.is_alive():
            return
        if ticks == 12:
            self.status_label.configure(text="Masih menghentikan...")
        if ticks >= 60:
            self._set_stopped()
            return
        self.after(250, lambda: self._stop_watchdog(ticks + 1))

    def on_save(self):
        if self.config is None:
            self.toast("Gagal menyimpan", "Konfigurasi belum dimuat.", kind="error")
            return
        try:
            scalars = {}
            for key, (kind, widget) in self.widgets.items():
                if kind in ("entry", "menu"):
                    scalars[key] = widget.get().strip()
                else:
                    scalars[key] = "true" if widget.get() else "false"

            ini_values = {}
            for key, section_key in FIELD_MAP.items():
                ini_values[section_key] = scalars[key]

            tag_lines = []
            for line in self.tags_text.get("1.0", "end").splitlines():
                line = line.strip()
                if not line or line.startswith((";", "#")):
                    continue
                if "=" not in line:
                    raise ValueError("Baris tag tidak valid: " + line)
                tag_lines.append(line)
            if not tag_lines:
                raise ValueError("Minimal satu tag harus didefinisikan.")

            save_config_file(self.config.path, ini_values, tag_lines)
            self.log.info("Konfigurasi disimpan: %s", self.config.path)

            if self.worker is not None and self.worker.is_alive():
                apply_now = self.ask(
                    "Konfigurasi tersimpan",
                    "Konfigurasi berhasil disimpan.\nTerapkan sekarang dengan me-restart?",
                    yes="Restart", no="Nanti",
                )
                if apply_now:
                    self.on_stop()
                    self.after(600, self._reload_and_restart)
                else:
                    self.toast("Konfigurasi tersimpan",
                               "Akan berlaku saat Start berikutnya.", kind="success")
            else:
                self.toast("Konfigurasi tersimpan", "Pengaturan diperbarui.",
                           kind="success")
                self._load_config()
        except Exception as exc:
            self.toast("Gagal menyimpan", str(exc), kind="error")

    def _reload_and_restart(self):
        if self.worker is not None and self.worker.is_alive():
            self.worker.join(timeout=3.0)
        self._load_config()
        self.on_start()

    def _drain_queues(self):
        while True:
            try:
                _, level, text = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(level, text)

        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)

        self.clock_label.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.after(150, self._drain_queues)

    def _append_log(self, level, text):
        tag = {logging.ERROR: "ERR ", logging.WARNING: "WARN",
               logging.INFO: "INFO", logging.DEBUG: "DBG "}.get(level, "INFO")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "{} | {}\n".format(tag, text))
        self.log_text.see("end")
        if int(self.log_text.index("end-1c").split(".")[0]) > 800:
            self.log_text.delete("1.0", "200.0")
        self.log_text.configure(state="disabled")

    def _on_event_status(self, component, ok):
        color = COLORS["good"] if ok else COLORS["bad"]
        soft = COLORS["good_soft"] if ok else COLORS["bad_soft"]
        if component == "plc":
            self.plc_led.configure(text_color=color)
            self.plc_pill.configure(fg_color=soft, border_color=color)
        else:
            self.db_led.configure(text_color=color)
            self.db_pill.configure(fg_color=soft, border_color=color)

    def _handle_event(self, event):
        kind = event[0]
        if kind == "reading":
            self._update_readings(event[1], event[2], event[3])
        elif kind == "status":
            self._on_event_status(event[1], event[2])
        elif kind == "stopped":
            self._set_stopped()

    def _update_readings(self, readings, ts, duration):
        for idx, r in enumerate(readings):
            item = self.row_ids.get(r.tag)
            if item is not None:
                zebra = "odd" if idx % 2 else "even"
                self.tree.item(
                    item,
                    values=(r.tag, r.address, fmt_value(r.value), r.unit,
                            r.quality, ts.strftime("%H:%M:%S")),
                    tags=(zebra, "good" if r.quality == "GOOD" else "bad"),
                )
        self.status_label.configure(
            text="Update terakhir: " + ts.strftime("%Y-%m-%d %H:%M:%S"))

    def _set_stopped(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._reset_leds()
        self.status_label.configure(text="Berhenti.")
        self.toast("TagVix dihentikan", "Proses polling dihentikan.", kind="info")

    def on_close(self):
        running = self.worker is not None and self.worker.is_alive()
        if running:
            message = ("TagVix sedang berjalan.\n"
                       "Yakin ingin keluar dan menghentikannya?")
        else:
            message = "Yakin ingin menutup aplikasi ini?"
        if not self.ask("Keluar aplikasi", message, yes="Keluar", no="Batal",
                        kind="warning", danger=True):
            return
        if self.mw is not None:
            self.mw.stop()
        if self.worker is not None and self.worker.is_alive():
            self.worker.join(timeout=2.0)
        self.destroy()


def launch():
    app = App()
    app.mainloop()
