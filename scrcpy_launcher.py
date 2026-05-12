"""
Scrcpy Pro Launcher v4.0
Perbaikan & peningkatan dari v3.3.4:
- Fix race condition threading (semua UI update via self.after())
- Fix import time di dalam thread → pakai threading.Event + sleep
- Fix build_command: prefix logic --start-app, flag audio scrcpy native
- Fix path profil konsisten frozen vs dev
- Fix run_scrcpy: error update UI via after()
- Tambah: fetch daftar app terpasang, copy command, disconnect button
- Tambah: validasi IP:Port sebelum connect
- Tambah: timeout handling lebih robust
- Tambah: status bar lebih informatif
- Tambah: keyboard shortcut Ctrl+C copy preview
"""

import customtkinter as ctk
import subprocess
import os
import threading
import sys
import json
import socket
import ipaddress
import re
import time

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

PROFILES_FILE = "scrcpy_profiles.json"
ADB_TIMEOUT   = 8   # detik default untuk subprocess ADB
SCAN_TIMEOUT  = 0.45 # detik per host saat port scan


# ──────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────
def _adb_run(adb: str, args: list[str], timeout: int = ADB_TIMEOUT) -> subprocess.CompletedProcess:
    """Jalankan perintah ADB dan kembalikan CompletedProcess. Tidak raise exception."""
    try:
        return subprocess.run(
            [adb] + args,
            capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, returncode=-1, stdout="", stderr="timeout")
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, returncode=-1, stdout="", stderr="adb.exe tidak ditemukan")
    except Exception as e:
        return subprocess.CompletedProcess(args, returncode=-1, stdout="", stderr=str(e))


def _validate_ip_port(text: str) -> bool:
    """Validasi format IP:Port (misal 192.168.1.5:5555)."""
    pattern = r"^(\d{1,3}\.){3}\d{1,3}:\d{1,5}$"
    if not re.match(pattern, text):
        return False
    ip, port = text.rsplit(":", 1)
    try:
        ipaddress.IPv4Address(ip)
        return 1 <= int(port) <= 65535
    except Exception:
        return False


# ──────────────────────────────────────────────────────────
#  Main App
# ──────────────────────────────────────────────────────────
class ScrcpyLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Scrcpy Pro Launcher")
        self.geometry("800x960")
        self.resizable(True, True)
        self.minsize(700, 800)

        # Tentukan direktori scrcpy
        self.scrcpy_dir = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        self._adb = os.path.join(self.scrcpy_dir, "adb.exe")
        self._scrcpy = os.path.join(self.scrcpy_dir, "scrcpy.exe")

        # State internal
        self.profiles:        dict = self._load_profiles()
        self._is_fullscreen:  bool = False
        self._wifi_adb_active: bool = False
        self._wifi_adb_ip:    str | None = None
        self._scrcpy_proc:    subprocess.Popen | None = None
        self._installed_apps: list[str] = []

        # Key bindings
        self.bind("<F11>",    lambda e: self._toggle_fullscreen())
        self.bind("<Return>", lambda e: self.launch_scrcpy())
        self.bind("<Control-r>", lambda e: self.refresh_devices())

        self._build_ui()

        # Init
        self.apply_preset("Sedang")
        self.refresh_devices()
        self.update_preview()

    # ══════════════════════════════════════════════════════
    #  UI Builder
    # ══════════════════════════════════════════════════════
    def _build_ui(self):
        # ── Header ──
        header = ctk.CTkFrame(self, fg_color="#0d1117", corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="⚡  Scrcpy Pro Launcher",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#00d4ff"
        ).pack(side="left", padx=22, pady=12)
        self._header_status = ctk.CTkLabel(
            header, text="", font=ctk.CTkFont(size=11), text_color="#555"
        )
        self._header_status.pack(side="right", padx=22)
        ctk.CTkLabel(
            header, text="v4.0", font=ctk.CTkFont(size=11), text_color="#444"
        ).pack(side="right")

        # ── Scrollable body ──
        self._scroll = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=14, pady=8)

        self._build_device_section()
        self._build_quality_section()
        self._build_audio_section()
        self._build_behaviour_section()
        self._build_keyboard_section()
        self._build_multitask_section()
        self._build_record_section()
        self._build_profiles_section()
        self._build_preview_section()
        self._build_launch_section()

    # ── Section helpers ──
    def _section(self, title: str, parent=None):
        p = parent or self._scroll
        f = ctk.CTkFrame(p, fg_color="transparent")
        f.pack(fill="x", pady=(10, 2))
        ctk.CTkLabel(
            f, text=title,
            font=ctk.CTkFont(weight="bold", size=13), text_color="#00d4ff"
        ).pack(anchor="w", padx=4)
        ctk.CTkFrame(p, height=1, fg_color="#2a2a3a").pack(fill="x", pady=(0, 5))

    def _frame(self, parent=None) -> ctk.CTkFrame:
        p = parent or self._scroll
        fr = ctk.CTkFrame(p)
        fr.pack(fill="x", pady=(0, 10))
        return fr

    # ── Device Section ──
    def _build_device_section(self):
        self._section("📱  Perangkat")
        fr = self._frame()
        fr.grid_columnconfigure(1, weight=1)

        # Baris 0: Dropdown perangkat
        ctk.CTkLabel(fr, text="Perangkat Terhubung:").grid(row=0, column=0, padx=14, pady=(14, 5), sticky="w")
        self.device_var = ctk.StringVar(value="Mendeteksi...")
        self.device_menu = ctk.CTkOptionMenu(
            fr, variable=self.device_var,
            values=["Mendeteksi..."],
            dynamic_resizing=False,
            command=self._on_device_change,
            width=280
        )
        self.device_menu.grid(row=0, column=1, padx=(5, 4), pady=(14, 5), sticky="we")
        ctk.CTkButton(fr, text="🔄", width=36, command=self.refresh_devices).grid(row=0, column=2, padx=(0, 5))
        ctk.CTkButton(fr, text="📋 Apps", width=64, command=self.fetch_installed_apps,
                      fg_color="#2a2a4a", hover_color="#3a3a6a").grid(row=0, column=3, padx=(0, 14), pady=(14, 5))

        # Baris 1: Koneksi WiFi manual
        ctk.CTkLabel(fr, text="Koneksi WiFi (IP:Port):").grid(row=1, column=0, padx=14, pady=5, sticky="w")
        self.wifi_var = ctk.StringVar()
        ctk.CTkEntry(fr, textvariable=self.wifi_var,
                     placeholder_text="192.168.1.x:5555").grid(row=1, column=1, padx=(5, 4), pady=5, sticky="we")
        ctk.CTkButton(fr, text="🔗 Sambung", width=72, command=self.connect_wifi,
                      fg_color="#1a3a5c", hover_color="#1a5280").grid(row=1, column=2, columnspan=2, padx=(0, 14), pady=5)

        # Baris 2: Aktifkan WiFi ADB (USB → WiFi)
        ctk.CTkLabel(fr, text="WiFi ADB (USB→WiFi):").grid(row=2, column=0, padx=14, pady=5, sticky="w")
        self.enable_wifi_status_var = ctk.StringVar(value="Hubungkan HP via USB lalu klik →")
        ctk.CTkLabel(fr, textvariable=self.enable_wifi_status_var,
                     text_color="gray", font=ctk.CTkFont(size=11),
                     wraplength=240, anchor="w").grid(row=2, column=1, padx=(5, 4), pady=5, sticky="we")
        self.enable_wifi_btn = ctk.CTkButton(
            fr, text="🌐 Aktifkan", width=100,
            command=self.toggle_wifi_adb,
            fg_color="#6a0dad", hover_color="#9b30ff"
        )
        self.enable_wifi_btn.grid(row=2, column=2, columnspan=2, padx=(0, 14), pady=5)

        # Baris 3: Scan jaringan
        ctk.CTkLabel(fr, text="Scan Perangkat WiFi:").grid(row=3, column=0, padx=14, pady=5, sticky="w")
        self.scan_status_var = ctk.StringVar(value="Belum di-scan")
        self.scan_status_lbl = ctk.CTkLabel(
            fr, textvariable=self.scan_status_var,
            text_color="gray", font=ctk.CTkFont(size=11), anchor="w"
        )
        self.scan_status_lbl.grid(row=3, column=1, padx=(5, 4), pady=5, sticky="we")
        self.scan_btn = ctk.CTkButton(
            fr, text="🔍 Scan", width=100,
            command=self.scan_wifi_devices,
            fg_color="#1a472a", hover_color="#2d6a4f"
        )
        self.scan_btn.grid(row=3, column=2, columnspan=2, padx=(0, 14), pady=5)

        # Baris 4: Toggle WiFi ADB di HP
        ctk.CTkLabel(fr, text="WiFi ADB di HP:").grid(row=4, column=0, padx=14, pady=(5, 14), sticky="w")
        self.usb_debug_status_var = ctk.StringVar(value="Sambungkan perangkat dulu")
        ctk.CTkLabel(fr, textvariable=self.usb_debug_status_var,
                     text_color="gray", font=ctk.CTkFont(size=11),
                     anchor="w").grid(row=4, column=1, padx=(5, 4), pady=(5, 14), sticky="we")
        self.usb_debug_btn = ctk.CTkButton(
            fr, text="🟢 WiFi ADB: ON", width=130,
            command=self.toggle_usb_debug,
            fg_color="#1a472a", hover_color="#2d6a4f"
        )
        self.usb_debug_btn.grid(row=4, column=2, columnspan=2, padx=(0, 14), pady=(5, 14))

    # ── Quality Section ──
    def _build_quality_section(self):
        self._section("📐  Kualitas & Resolusi")
        fr = self._frame()
        fr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(fr, text="Preset Cepat:").grid(row=0, column=0, padx=14, pady=(14, 5), sticky="w")
        self.preset_var = ctk.StringVar(value="Sedang")
        ctk.CTkSegmentedButton(
            fr, values=["2K", "Tinggi", "Sedang", "Rendah", "Kustom"],
            variable=self.preset_var, command=self.apply_preset
        ).grid(row=0, column=1, columnspan=2, padx=14, pady=(14, 5), sticky="we")

        rows = [
            ("Resolusi Maks:", "res_var", "1280", ["Bawaan", "2560", "1920", "1280", "1024", "800", "600"]),
            ("FPS Maks:",      "fps_var", "60",   ["144", "120", "90", "60", "30", "15"]),
            ("Bitrate Video:", "bitrate_var", "8M", ["32M", "24M", "16M", "8M", "4M", "2M", "1M"]),
            ("Codec Video:",   "codec_var", "h264", ["h264", "h265", "av1"]),
        ]
        for i, (label, var_name, default, values) in enumerate(rows, start=1):
            setattr(self, var_name, ctk.StringVar(value=default))
            ctk.CTkLabel(fr, text=label).grid(row=i, column=0, padx=14, pady=5, sticky="w")
            pad_b = (5, 14) if i == len(rows) else 5
            ctk.CTkOptionMenu(
                fr, values=values,
                variable=getattr(self, var_name),
                command=lambda *_: self.update_preview()
            ).grid(row=i, column=1, padx=14, pady=pad_b, sticky="we")

    # ── Audio Section ──
    def _build_audio_section(self):
        self._section("🔊  Audio")
        fr = self._frame()
        fr.grid_columnconfigure(1, weight=1)

        self.audio_devices = ["Bawaan (Sistem)"]
        if HAS_SOUNDDEVICE:
            try:
                seen: set[str] = set()
                for d in sd.query_devices():
                    if d["max_output_channels"] > 0 and d["name"] not in seen:
                        self.audio_devices.append(d["name"])
                        seen.add(d["name"])
            except Exception:
                pass

        ctk.CTkLabel(fr, text="Speaker Keluaran:").grid(row=0, column=0, padx=14, pady=(14, 5), sticky="w")
        self.speaker_var = ctk.StringVar(value="Bawaan (Sistem)")
        ctk.CTkOptionMenu(
            fr, values=self.audio_devices,
            variable=self.speaker_var, dynamic_resizing=False
        ).grid(row=0, column=1, padx=14, pady=(14, 5), sticky="we")

        ctk.CTkLabel(fr, text="Buffer Audio (ms):").grid(row=1, column=0, padx=14, pady=(5, 14), sticky="w")
        self.audio_buffer_var = ctk.StringVar(value="200")
        ctk.CTkOptionMenu(
            fr, values=["50", "100", "200", "300", "500"],
            variable=self.audio_buffer_var
        ).grid(row=1, column=1, padx=14, pady=(5, 14), sticky="we")

    # ── Behaviour Section ──
    def _build_behaviour_section(self):
        self._section("🖥️  Perilaku Layar")
        fr = self._frame()
        inner = ctk.CTkFrame(fr, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=14)

        checks = [
            ("stay_awake_var",   "HP Tetap Menyala",       False),
            ("turn_off_var",     "Matikan Layar HP",        False),
            ("on_top_var",       "Selalu di Atas",          False),
            ("no_audio_var",     "Matikan Suara HP",        False),
            ("fullscreen_var",   "Mulai Fullscreen",        False),
            ("show_touches_var", "Tampilkan Sentuhan",      False),
            ("borderless_var",   "Tanpa Border Window",     False),
            ("no_control_var",   "Hanya Lihat (Read-only)", False),
        ]
        for idx, (var_name, label, default) in enumerate(checks):
            bv = ctk.BooleanVar(value=default)
            setattr(self, var_name, bv)
            ctk.CTkCheckBox(
                inner, text=label, variable=bv,
                command=self.update_preview
            ).grid(row=idx // 2, column=idx % 2, sticky="w", pady=4, padx=(0, 20))

    # ── Keyboard Section ──
    def _build_keyboard_section(self):
        self._section("⌨️  Keyboard & Mouse")
        fr = self._frame()
        inner = ctk.CTkFrame(fr, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=14)

        checks = [
            ("uhid_var",       "Mode UHID (Keyboard/Mouse Asli)",   False),
            ("copy_paste_var", "Sinkronisasi Copy-Paste",            True),
            ("volume_keys_var","Tombol Volume PC",                   True),
            ("otg_var",        "Teruskan USB OTG",                   False),
        ]
        for idx, (var_name, label, default) in enumerate(checks):
            bv = ctk.BooleanVar(value=default)
            setattr(self, var_name, bv)
            ctk.CTkCheckBox(
                inner, text=label, variable=bv,
                command=self.update_preview
            ).grid(row=idx // 2, column=idx % 2, sticky="w", pady=4, padx=(0, 20))

    # ── Multi-task Section ──
    def _build_multitask_section(self):
        self._section("📲  Multi-Tasking (Layar Virtual)")
        fr = self._frame()
        ctk.CTkLabel(
            fr,
            text="Buat layar virtual terpisah — HP bisa buka app lain sementara scrcpy tetap berjalan (Android 13+)",
            text_color="gray", font=ctk.CTkFont(size=11), wraplength=680, justify="left"
        ).pack(anchor="w", padx=14, pady=(8, 4))

        inner = ctk.CTkFrame(fr, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=(0, 14))
        inner.grid_columnconfigure(1, weight=1)

        self.new_display_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            inner, text="Aktifkan Layar Virtual",
            variable=self.new_display_var,
            command=self._on_multitask_change
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=5)

        ctk.CTkLabel(inner, text="Resolusi Virtual:").grid(row=1, column=0, sticky="w", pady=5)
        self.vdisplay_res_var = ctk.StringVar(value="Bawaan")
        ctk.CTkOptionMenu(
            inner,
            values=["Bawaan", "1280x720", "1920x1080", "2560x1440", "720x1280", "1080x1920"],
            variable=self.vdisplay_res_var,
            command=lambda *_: self.update_preview()
        ).grid(row=1, column=1, sticky="w", padx=(10, 0), pady=5)

        ctk.CTkLabel(inner, text="Buka Aplikasi:").grid(row=2, column=0, sticky="w", pady=(8, 2))
        self.start_app_var = ctk.StringVar()
        self.start_app_var.trace_add("write", lambda *_: self._on_multitask_change())
        self.start_app_entry = ctk.CTkEntry(
            inner, textvariable=self.start_app_var,
            placeholder_text="Contoh: com.instagram.android  atau: instagram",
            width=380
        )
        self.start_app_entry.grid(row=3, column=0, columnspan=2, sticky="we", pady=(0, 4))

        ctk.CTkLabel(
            inner, text_color="gray",
            text="Nama pendek (instagram) → fuzzy search (?).  Package lengkap (com.x.y) → langsung.",
            font=ctk.CTkFont(size=10)
        ).grid(row=4, column=0, columnspan=2, sticky="w")

        self.new_task_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            inner, text="Buka di task baru (seperti tap ikon app)",
            variable=self.new_task_var, command=self.update_preview
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ── Divider ──
        ctk.CTkFrame(inner, height=1, fg_color="#2a2a3a").grid(
            row=6, column=0, columnspan=2, sticky="we", pady=(10, 6))

        # ── Mouse mode ──
        ctk.CTkLabel(inner, text="Mode Mouse (Virtual Display):",
                     font=ctk.CTkFont(weight="bold", size=11)).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.vd_mouse_mode_var = ctk.StringVar(value="disabled")
        mouse_frame = ctk.CTkFrame(inner, fg_color="transparent")
        mouse_frame.grid(row=8, column=0, columnspan=2, sticky="we")

        mouse_modes = [
            ("disabled", "🚫 Disabled  ← Direkomendasikan: mouse TIDAK berpindah ke HP",  "#1a3a1a"),
            ("sdk",      "SDK  — mouse diteruskan ke HP (default scrcpy)",                "#1e1e2e"),
            ("uhid",     "UHID — virtual HID device (Android 13+)",                       "#1a1a2e"),
        ]
        for val, desc, bg in mouse_modes:
            card = ctk.CTkFrame(mouse_frame, fg_color=bg, corner_radius=6)
            card.pack(fill="x", pady=2)
            ctk.CTkRadioButton(
                card, text=desc,
                variable=self.vd_mouse_mode_var, value=val,
                command=self.update_preview,
                font=ctk.CTkFont(size=11)
            ).pack(anchor="w", padx=10, pady=5)

        ctk.CTkLabel(
            inner,
            text="💡 'Disabled' = mouse tetap di PC, tidak bocor ke window HP.\n"
                 "    Kamu masih bisa kontrol app dengan menyentuh layar HP secara langsung.",
            text_color="#888", font=ctk.CTkFont(size=10), justify="left", wraplength=560
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(2, 8))

        # ── Keyboard mode ──
        ctk.CTkLabel(inner, text="Mode Keyboard (Virtual Display):",
                     font=ctk.CTkFont(weight="bold", size=11)).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.vd_kbd_mode_var = ctk.StringVar(value="sdk")
        kbd_frame = ctk.CTkFrame(inner, fg_color="transparent")
        kbd_frame.grid(row=11, column=0, columnspan=2, sticky="we")

        kbd_modes = [
            ("sdk",      "SDK  — ketikan diteruskan ke HP (default)", "#1e1e2e"),
            ("disabled", "Disabled — keyboard tidak diteruskan ke HP", "#2a1a1a"),
        ]
        for val, desc, bg in kbd_modes:
            card = ctk.CTkFrame(kbd_frame, fg_color=bg, corner_radius=6)
            card.pack(fill="x", pady=2)
            ctk.CTkRadioButton(
                card, text=desc,
                variable=self.vd_kbd_mode_var, value=val,
                command=self.update_preview,
                font=ctk.CTkFont(size=11)
            ).pack(anchor="w", padx=10, pady=5)

        # ── Warning label ──
        self.mt_warning_lbl = ctk.CTkLabel(
            inner,
            text="⚠️  Isi 'Buka Aplikasi' dulu — tanpa app, layar virtual akan hitam!\n"
                 "⚠️  Catatan: beberapa Xiaomi/Samsung mungkin tidak support layar virtual.",
            text_color="#F39C12", font=ctk.CTkFont(size=11), justify="left", wraplength=580
        )
        self.mt_warning_lbl.grid(row=12, column=0, columnspan=2, sticky="w", pady=(4, 4))
        self.mt_warning_lbl.grid_remove()

    def _on_multitask_change(self, *_):
        show = self.new_display_var.get() and not self.start_app_var.get().strip()
        if show:
            self.mt_warning_lbl.grid()
        else:
            self.mt_warning_lbl.grid_remove()
        self.update_preview()

    # ── Record Section ──
    def _build_record_section(self):
        self._section("🎬  Rekam Layar")
        fr = self._frame()
        inner = ctk.CTkFrame(fr, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=14)
        inner.grid_columnconfigure(1, weight=1)

        self.record_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            inner, text="Aktifkan Rekaman",
            variable=self.record_var, command=self.update_preview
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=5)

        ctk.CTkLabel(inner, text="Simpan ke:").grid(row=1, column=0, sticky="w", pady=(10, 2))
        self.record_path_var = ctk.StringVar(value="rekaman.mp4")
        ctk.CTkEntry(
            inner, textvariable=self.record_path_var, width=360,
        ).grid(row=1, column=1, sticky="we", padx=(10, 0), pady=(10, 2))

        ctk.CTkLabel(
            inner, text="Ekstensi .mp4 atau .mkv — bisa gunakan path absolut",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).grid(row=2, column=0, columnspan=2, sticky="w")

    # ── Profiles Section ──
    def _build_profiles_section(self):
        self._section("💾  Profil Pengaturan")
        fr = self._frame()
        inner = ctk.CTkFrame(fr, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=14)

        profile_names = list(self.profiles.keys()) or ["(belum ada profil)"]
        self.profile_var = ctk.StringVar(value=profile_names[0])
        self.profile_menu = ctk.CTkOptionMenu(
            inner, values=profile_names,
            variable=self.profile_var, width=220
        )
        self.profile_menu.grid(row=0, column=0, sticky="w", pady=5)
        ctk.CTkButton(inner, text="📂 Muat", width=80, command=self.load_profile).grid(row=0, column=1, padx=10, pady=5)
        ctk.CTkButton(inner, text="🗑 Hapus", width=80, command=self.delete_profile,
                      fg_color="#4a1010", hover_color="#6a1a1a").grid(row=0, column=2, pady=5)

        self.profile_name_var = ctk.StringVar()
        ctk.CTkEntry(
            inner, textvariable=self.profile_name_var,
            placeholder_text="Nama profil baru...", width=220
        ).grid(row=1, column=0, sticky="w", pady=(10, 5))
        ctk.CTkButton(inner, text="💾 Simpan", width=80, command=self.save_profile).grid(row=1, column=1, padx=10, pady=(10, 5))

    # ── Preview Section ──
    def _build_preview_section(self):
        self._section("🔍  Pratinjau Perintah")
        fr = self._frame()
        self.cmd_preview = ctk.CTkTextbox(
            fr, height=58,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0d1117", text_color="#58a6ff",
            wrap="word"
        )
        self.cmd_preview.pack(fill="x", padx=14, pady=(14, 6))

        btn_row = ctk.CTkFrame(fr, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkButton(
            btn_row, text="🔄 Perbarui", command=self.update_preview, width=110
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="📋 Salin", command=self._copy_command, width=90,
            fg_color="#2a2a4a", hover_color="#3a3a6a"
        ).pack(side="left", padx=(8, 0))

    # ── Launch Section ──
    def _build_launch_section(self):
        self.status_label = ctk.CTkLabel(
            self._scroll, text="✅  Siap. Hubungkan HP via USB atau WiFi.",
            text_color="gray", font=ctk.CTkFont(size=12)
        )
        self.status_label.pack(pady=(4, 4))

        self.launch_btn = ctk.CTkButton(
            self._scroll, text="🚀  JALANKAN SCRCPY",
            font=ctk.CTkFont(weight="bold", size=18), height=58,
            corner_radius=10, fg_color="#0078d4", hover_color="#005fa3",
            command=self.launch_scrcpy
        )
        self.launch_btn.pack(fill="x", padx=28, pady=(4, 10))

        self.stop_btn = ctk.CTkButton(
            self._scroll, text="⏹  HENTIKAN",
            font=ctk.CTkFont(size=13), height=36,
            corner_radius=8, fg_color="#7f1d1d", hover_color="#991b1b",
            command=self.stop_scrcpy, state="disabled"
        )
        self.stop_btn.pack(fill="x", padx=28, pady=(0, 18))

    # ══════════════════════════════════════════════════════
    #  Device Management
    # ══════════════════════════════════════════════════════
    def refresh_devices(self):
        self._set_status("🔄 Mendeteksi perangkat...", "gray")
        threading.Thread(target=self._refresh_devices_task, daemon=True).start()

    def _refresh_devices_task(self):
        result = _adb_run(self._adb, ["devices"])
        if result.returncode == -1 and "tidak ditemukan" in result.stderr:
            self.after(0, lambda: self._set_status("❌ adb.exe tidak ditemukan di folder scrcpy!", "#FF5252"))
            return

        lines = [
            l.split("\t")[0].strip()
            for l in result.stdout.strip().splitlines()[1:]
            if "\tdevice" in l
        ]
        devices = lines if lines else ["Tidak ada perangkat"]

        def _update():
            self.device_var.set(devices[0])
            self.device_menu.configure(values=devices)
            count = len(lines)
            self._set_status(
                f"✅ Ditemukan {count} perangkat." if count else "⚠️ Tidak ada perangkat terhubung.",
                "#2FA572" if count else "orange"
            )
            if lines:
                threading.Thread(
                    target=self._check_wifi_adb_status,
                    args=(lines[0],), daemon=True
                ).start()
        self.after(0, _update)

    def _on_device_change(self, selected: str):
        invalid = ("Mendeteksi...", "Tidak ada perangkat", "")
        if selected in invalid:
            self.after(0, lambda: self.usb_debug_status_var.set("Sambungkan perangkat dulu"))
            return
        self.after(0, lambda: self.usb_debug_status_var.set("Mengecek status WiFi ADB..."))
        threading.Thread(
            target=self._check_wifi_adb_status,
            args=(selected,), daemon=True
        ).start()

    def _check_wifi_adb_status(self, device_id: str):
        result = _adb_run(self._adb, ["-s", device_id, "shell", "settings", "get", "global", "adb_wifi_enabled"])
        val = result.stdout.strip()

        def _update():
            if val == "1":
                self.usb_debug_status_var.set("🟢 Aktif (terdeteksi otomatis)")
                self.usb_debug_btn.configure(text="🟢 WiFi ADB: ON", fg_color="#1a472a", hover_color="#2d6a4f")
            elif val == "0":
                self.usb_debug_status_var.set("🔴 Tidak aktif (terdeteksi otomatis)")
                self.usb_debug_btn.configure(text="🔴 WiFi ADB: OFF", fg_color="#7f1d1d", hover_color="#991b1b")
            else:
                self.usb_debug_status_var.set("⚪ Status tidak diketahui")
                self.usb_debug_btn.configure(text="⚪ WiFi ADB: ?", fg_color="#333", hover_color="#444")
        self.after(0, _update)

    def connect_wifi(self):
        ip = self.wifi_var.get().strip()
        if not ip:
            self._set_status("⚠️ Masukkan IP:Port terlebih dahulu.", "orange")
            return
        if not _validate_ip_port(ip):
            self._set_status("⚠️ Format IP:Port tidak valid. Contoh: 192.168.1.5:5555", "orange")
            return
        self._set_status(f"🔗 Menyambung ke {ip}...", "#F39C12")
        threading.Thread(target=self._connect_wifi_task, args=(ip,), daemon=True).start()

    def _connect_wifi_task(self, ip: str):
        result = _adb_run(self._adb, ["connect", ip], timeout=10)
        msg = result.stdout.strip() or result.stderr.strip()
        success = "connected" in msg.lower()

        def _update():
            color = "#2FA572" if success else "#FF5252"
            prefix = "✅" if success else "❌"
            self._set_status(f"{prefix} {msg}", color)
            self._refresh_devices_task()
        self.after(0, _update)

    # ══════════════════════════════════════════════════════
    #  WiFi ADB Toggle (USB → WiFi)
    # ══════════════════════════════════════════════════════
    def toggle_wifi_adb(self):
        if self._wifi_adb_active:
            self._do_disable_wifi_adb()
        else:
            self._do_enable_wifi_adb()

    def _do_enable_wifi_adb(self):
        sel = self.device_var.get()
        if not sel or sel in ("Mendeteksi...", "Tidak ada perangkat"):
            self.enable_wifi_status_var.set("⚠️ Pilih perangkat USB dulu!")
            return
        if ":" in sel:
            self.enable_wifi_status_var.set("⚠️ Perangkat ini sudah via WiFi")
            return

        self.enable_wifi_btn.configure(state="disabled", text="⏳...")
        self.enable_wifi_status_var.set("Mengaktifkan ADB via WiFi...")

        def task():
            # 1. tcpip 5555
            r = _adb_run(self._adb, ["-s", sel, "tcpip", "5555"], timeout=12)
            if r.returncode != 0 and "restarting" not in r.stdout.lower():
                err = (r.stderr or r.stdout).strip()[:60] or "Gagal tcpip"
                def _e():
                    self.enable_wifi_status_var.set(f"❌ {err}")
                    self.enable_wifi_btn.configure(state="normal", text="🌐 Aktifkan",
                                                   fg_color="#6a0dad", hover_color="#9b30ff")
                self.after(0, _e)
                return

            # 2. Ambil IP wlan0 (dan fallback interface lain)
            device_ip = None
            for iface in ("wlan0", "wlan1", "swlan0"):
                ip_raw = _adb_run(self._adb,
                    ["-s", sel, "shell", "ip", "-f", "inet", "addr", "show", iface]
                ).stdout
                for line in ip_raw.splitlines():
                    line = line.strip()
                    if line.startswith("inet ") and not line.split()[1].startswith("127"):
                        device_ip = line.split()[1].split("/")[0]
                        break
                if device_ip:
                    break

            if not device_ip:
                def _no_ip():
                    self.enable_wifi_status_var.set("⚠️ IP tidak ditemukan — pastikan HP terhubung WiFi")
                    self.enable_wifi_btn.configure(state="normal", text="🌐 Aktifkan",
                                                   fg_color="#6a0dad", hover_color="#9b30ff")
                self.after(0, _no_ip)
                return

            ip_port = f"{device_ip}:5555"

            def _ok():
                self._wifi_adb_active = True
                self._wifi_adb_ip = ip_port
                self.wifi_var.set(ip_port)
                self.enable_wifi_status_var.set(f"🟢 Aktif: {ip_port}")
                self.enable_wifi_btn.configure(state="normal", text="🔴 Nonaktifkan",
                                               fg_color="#7f1d1d", hover_color="#991b1b")
                self._set_status(f"✅ WiFi ADB aktif: {ip_port} — klik Scan atau Sambung", "#2FA572")
            self.after(0, _ok)

        threading.Thread(target=task, daemon=True).start()

    def _do_disable_wifi_adb(self):
        self.enable_wifi_btn.configure(state="disabled", text="⏳...")
        self.enable_wifi_status_var.set("Menonaktifkan ADB WiFi...")
        ip_to_disconnect = self._wifi_adb_ip

        def task():
            if ip_to_disconnect:
                _adb_run(self._adb, ["disconnect", ip_to_disconnect])
            _adb_run(self._adb, ["usb"], timeout=12)

            def _done():
                self._wifi_adb_active = False
                self._wifi_adb_ip = None
                self.enable_wifi_status_var.set("🔴 ADB WiFi dinonaktifkan")
                self.enable_wifi_btn.configure(state="normal", text="🌐 Aktifkan",
                                               fg_color="#6a0dad", hover_color="#9b30ff")
                self._set_status("🔒 ADB WiFi dinonaktifkan — kembali mode USB", "gray")
                self._refresh_devices_task()
            self.after(0, _done)

        threading.Thread(target=task, daemon=True).start()

    # ══════════════════════════════════════════════════════
    #  Toggle WiFi ADB di HP (Wireless Debugging)
    # ══════════════════════════════════════════════════════
    def toggle_usb_debug(self):
        target = (
            self._wifi_adb_ip
            or self.wifi_var.get().strip()
            or self.device_var.get().strip()
        )
        invalid = ("", "Mendeteksi...", "Tidak ada perangkat")
        if not target or target in invalid:
            self.usb_debug_status_var.set("⚠️ Tidak ada perangkat terhubung!")
            return

        self.usb_debug_btn.configure(state="disabled", text="⏳...")
        self.usb_debug_status_var.set("Membaca status WiFi ADB...")

        def task():
            check = _adb_run(self._adb,
                ["-s", target, "shell", "settings", "get", "global", "adb_wifi_enabled"])
            current = check.stdout.strip()

            if current == "1":
                _adb_run(self._adb,
                    ["-s", target, "shell", "settings", "put", "global", "adb_wifi_enabled", "0"])
                def _off():
                    self.usb_debug_status_var.set("🔴 WiFi ADB dimatikan di HP")
                    self.usb_debug_btn.configure(state="normal", text="🔴 WiFi ADB: OFF",
                                                 fg_color="#7f1d1d", hover_color="#991b1b")
                    self._set_status("🔴 Wireless Debugging dinonaktifkan di HP", "gray")
                self.after(0, _off)
            else:
                _adb_run(self._adb,
                    ["-s", target, "shell", "settings", "put", "global", "adb_wifi_enabled", "1"])
                def _on():
                    self.usb_debug_status_var.set("🟢 WiFi ADB aktif di HP")
                    self.usb_debug_btn.configure(state="normal", text="🟢 WiFi ADB: ON",
                                                 fg_color="#1a472a", hover_color="#2d6a4f")
                    self._set_status("🟢 Wireless Debugging diaktifkan di HP", "#2FA572")
                self.after(0, _on)

            # Verifikasi ulang setelah 2 detik
            time.sleep(2.0)
            self._check_wifi_adb_status(target)

        threading.Thread(target=task, daemon=True).start()

    # ══════════════════════════════════════════════════════
    #  WiFi Scan
    # ══════════════════════════════════════════════════════
    def scan_wifi_devices(self):
        self.scan_btn.configure(state="disabled", text="⏳ Scan...")
        self.scan_status_var.set("Sedang scan jaringan...")
        self.scan_status_lbl.configure(text_color="#F39C12")
        threading.Thread(target=self._scan_task, daemon=True).start()

    def _scan_task(self):
        found: list[str] = []

        # Metode 1: ADB mDNS (Android 11+)
        r = _adb_run(self._adb, ["mdns", "services"], timeout=6)
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            if parts and ":" in parts[-1] and "adb" in line.lower():
                ip_port = parts[-1]
                if ip_port not in found:
                    found.append(ip_port)

        # Metode 2: Perangkat TCP yang sudah ada di ADB
        r2 = _adb_run(self._adb, ["devices"])
        for line in r2.stdout.splitlines()[1:]:
            if "\tdevice" in line and ":" in line.split("\t")[0]:
                ip_port = line.split("\t")[0].strip()
                if ip_port not in found:
                    found.append(ip_port)

        # Metode 3: Port scan subnet /24
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
            network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
            lock = threading.Lock()
            threads: list[threading.Thread] = []
            scan_extra: list[str] = []

            def _check(host_str: str):
                if host_str == local_ip:
                    return
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(SCAN_TIMEOUT)
                    if s.connect_ex((host_str, 5555)) == 0:
                        entry = f"{host_str}:5555"
                        with lock:
                            if entry not in found and entry not in scan_extra:
                                scan_extra.append(entry)
                    s.close()
                except Exception:
                    pass

            for host in list(network.hosts()):
                t = threading.Thread(target=_check, args=(str(host),), daemon=True)
                threads.append(t)
                t.start()

            # Tunggu semua thread maksimal 4 detik total
            deadline = time.time() + 4.0
            for t in threads:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                t.join(timeout=remaining)
            found.extend(scan_extra)

        except Exception:
            pass

        # Ambil nama model untuk setiap IP
        devices: dict[str, str] = {}
        for ip_port in found:
            devices[ip_port] = self._get_device_name(ip_port)

        def _update():
            self.scan_btn.configure(state="normal", text="🔍 Scan")
            if devices:
                self.scan_status_var.set(f"✅ {len(devices)} perangkat ditemukan")
                self.scan_status_lbl.configure(text_color="#2FA572")
                self.after(0, lambda: self._show_wifi_scan_results(devices))
            else:
                self.scan_status_var.set("❌ Tidak ada perangkat ditemukan di jaringan")
                self.scan_status_lbl.configure(text_color="#FF5252")
        self.after(0, _update)

    def _get_device_name(self, ip_port: str) -> str:
        _adb_run(self._adb, ["connect", ip_port], timeout=5)
        model = _adb_run(self._adb, ["-s", ip_port, "shell", "getprop", "ro.product.model"]).stdout.strip()
        brand = _adb_run(self._adb, ["-s", ip_port, "shell", "getprop", "ro.product.brand"]).stdout.strip()
        if model:
            return f"{brand} {model}".strip() if brand else model
        return "Perangkat Android"

    def _show_wifi_scan_results(self, devices: dict[str, str]):
        if isinstance(devices, list):
            devices = {d: "Perangkat Android" for d in devices}

        dialog = ctk.CTkToplevel(self)
        dialog.title("Hasil Scan WiFi")
        dialog.geometry("460x380")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.focus()
        dialog.lift()

        ctk.CTkLabel(
            dialog, text="📡  Perangkat WiFi Ditemukan",
            font=ctk.CTkFont(weight="bold", size=14), text_color="#00d4ff"
        ).pack(pady=(16, 4))
        ctk.CTkLabel(
            dialog, text="Pilih perangkat untuk mengisi kolom IP:",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).pack(pady=(0, 10))

        ip_ports = list(devices.keys())
        selected_var = ctk.StringVar(value=ip_ports[0] if ip_ports else "")

        list_frame = ctk.CTkScrollableFrame(dialog, height=190)
        list_frame.pack(fill="x", padx=14, pady=(0, 8))

        for ip_port, model_name in devices.items():
            row = ctk.CTkFrame(list_frame, fg_color="transparent")
            row.pack(fill="x", pady=3, padx=4)
            ctk.CTkRadioButton(row, text="", variable=selected_var, value=ip_port, width=24).pack(side="left")
            card = ctk.CTkFrame(row, fg_color="#1a1a2e", corner_radius=8)
            card.pack(side="left", fill="x", expand=True, padx=(4, 0))
            ctk.CTkLabel(card, text=f"📱  {model_name}",
                         font=ctk.CTkFont(weight="bold", size=12), anchor="w").pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(card, text=ip_port,
                         font=ctk.CTkFont(family="Consolas", size=11),
                         text_color="#888", anchor="w").pack(anchor="w", padx=12, pady=(0, 6))

        def on_select():
            chosen = selected_var.get()
            if chosen:
                self.wifi_var.set(chosen)
                self.scan_status_var.set(f"Dipilih: {devices.get(chosen, chosen)}")
            dialog.destroy()

        def on_connect():
            chosen = selected_var.get()
            if chosen:
                self.wifi_var.set(chosen)
            dialog.destroy()
            self.connect_wifi()

        btn_fr = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_fr.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(btn_fr, text="✅ Pilih", command=on_select,
                      fg_color="#333", hover_color="#444").pack(side="left", expand=True, padx=(0, 5))
        ctk.CTkButton(btn_fr, text="🔗 Pilih & Sambung", command=on_connect,
                      fg_color="#0078d4", hover_color="#005fa3").pack(side="left", expand=True, padx=(5, 0))

    # ══════════════════════════════════════════════════════
    #  Fetch Installed Apps
    # ══════════════════════════════════════════════════════
    def fetch_installed_apps(self):
        sel = self.device_var.get()
        if not sel or sel in ("Mendeteksi...", "Tidak ada perangkat"):
            self._set_status("⚠️ Pilih perangkat dulu untuk fetch daftar app.", "orange")
            return
        self._set_status("📋 Mengambil daftar aplikasi terpasang...", "#F39C12")
        threading.Thread(target=self._fetch_apps_task, args=(sel,), daemon=True).start()

    def _fetch_apps_task(self, device_id: str):
        result = _adb_run(self._adb,
            ["-s", device_id, "shell", "pm", "list", "packages", "-3"],
            timeout=15
        )
        packages = sorted([
            line.replace("package:", "").strip()
            for line in result.stdout.splitlines()
            if line.startswith("package:")
        ])

        def _update():
            if packages:
                self._installed_apps = packages
                self._set_status(f"✅ {len(packages)} aplikasi ditemukan. Ketik di kolom 'Buka Aplikasi'.", "#2FA572")
                self._show_app_picker(packages)
            else:
                self._set_status("❌ Gagal mengambil daftar aplikasi.", "#FF5252")
        self.after(0, _update)

    def _show_app_picker(self, packages: list[str]):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Pilih Aplikasi")
        dialog.geometry("460x420")
        dialog.resizable(False, True)
        dialog.grab_set()
        dialog.focus()
        dialog.lift()

        ctk.CTkLabel(dialog, text="📋  Pilih Aplikasi untuk Dibuka",
                     font=ctk.CTkFont(weight="bold", size=14), text_color="#00d4ff").pack(pady=(14, 4))

        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(dialog, textvariable=search_var, placeholder_text="Cari package...", width=400)
        search_entry.pack(padx=14, pady=(0, 8))

        list_frame = ctk.CTkScrollableFrame(dialog, height=270)
        list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        selected_var = ctk.StringVar(value=packages[0] if packages else "")
        buttons: list[ctk.CTkRadioButton] = []

        def _populate(filter_text=""):
            for w in list_frame.winfo_children():
                w.destroy()
            filtered = [p for p in packages if filter_text.lower() in p.lower()]
            for pkg in filtered[:200]:  # cap 200 untuk performa
                rb = ctk.CTkRadioButton(list_frame, text=pkg, variable=selected_var, value=pkg,
                                        font=ctk.CTkFont(family="Consolas", size=11))
                rb.pack(anchor="w", padx=6, pady=2)
                buttons.append(rb)

        _populate()
        search_var.trace_add("write", lambda *_: _populate(search_var.get()))

        def on_ok():
            pkg = selected_var.get()
            if pkg:
                self.start_app_var.set(pkg)
            dialog.destroy()

        ctk.CTkButton(dialog, text="✅ Pilih", command=on_ok,
                      fg_color="#0078d4", hover_color="#005fa3").pack(padx=14, pady=(0, 14))

    # ══════════════════════════════════════════════════════
    #  Command Builder
    # ══════════════════════════════════════════════════════
    def build_command(self) -> list[str]:
        cmd = [self._scrcpy]

        # Perangkat
        sel = self.device_var.get()
        if sel and sel not in ("Mendeteksi...", "Tidak ada perangkat"):
            cmd += ["-s", sel]

        # Video
        if self.res_var.get() != "Bawaan":
            cmd.append(f"--max-size={self.res_var.get()}")
        cmd += [
            f"--max-fps={self.fps_var.get()}",
            f"--video-bit-rate={self.bitrate_var.get()}",
            f"--video-codec={self.codec_var.get()}",
        ]

        # Audio output buffer
        if self.audio_buffer_var.get() != "200":
            cmd.append(f"--audio-output-buffer={self.audio_buffer_var.get()}")

        # Behaviour flags
        if self.stay_awake_var.get():     cmd.append("--stay-awake")
        if self.turn_off_var.get():       cmd.append("--turn-screen-off")
        if self.on_top_var.get():         cmd.append("--always-on-top")
        if self.no_audio_var.get():       cmd.append("--no-audio")
        if self.fullscreen_var.get():     cmd.append("--fullscreen")
        if self.show_touches_var.get():   cmd.append("--show-touches")
        if self.borderless_var.get():     cmd.append("--window-borderless")
        if self.no_control_var.get():     cmd.append("--no-control")

        # Keyboard/Mouse (global)
        if self.uhid_var.get():
            cmd += ["--keyboard=uhid", "--mouse=uhid"]
        if not self.copy_paste_var.get(): cmd.append("--no-clipboard-autosync")
        if not self.volume_keys_var.get():cmd.append("--no-key-inject")
        if self.otg_var.get():            cmd.append("--otg")

        # Multi-tasking / layar virtual
        if self.new_display_var.get():
            res = self.vdisplay_res_var.get()
            cmd.append(f"--new-display={res}" if res and res != "Bawaan" else "--new-display")

            # Override mouse/keyboard mode khusus virtual display
            # (hanya jika UHID global tidak aktif — agar tidak konflik)
            if not self.uhid_var.get():
                mouse_mode = self.vd_mouse_mode_var.get()
                kbd_mode   = self.vd_kbd_mode_var.get()
                if mouse_mode != "sdk":   # sdk = default, tidak perlu flag
                    cmd.append(f"--mouse={mouse_mode}")
                if kbd_mode != "sdk":
                    cmd.append(f"--keyboard={kbd_mode}")

        # Start app
        app = self.start_app_var.get().strip()
        if app:
            # Bangun prefix:
            #   '+' = buka di task baru
            #   '?' = fuzzy search (nama pendek, tidak mengandung '.')
            # Keduanya bisa dikombinasi: '+?' atau '?+'
            task_prefix = "+" if self.new_task_var.get() else ""
            fuzzy_prefix = "?" if "." not in app else ""
            full_prefix = task_prefix + fuzzy_prefix   # urutan: +? atau ?+ → scrcpy terima keduanya
            cmd.append(f"--start-app={full_prefix}{app}")

        # Rekaman
        if self.record_var.get():
            path = self.record_path_var.get().strip() or "rekaman.mp4"
            cmd += ["--record", path]

        return cmd

    def update_preview(self, *_):
        cmd = self.build_command()
        self.cmd_preview.configure(state="normal")
        self.cmd_preview.delete("1.0", "end")
        self.cmd_preview.insert("1.0", " ".join(cmd))
        self.cmd_preview.configure(state="disabled")

    def _copy_command(self):
        cmd = self.build_command()
        self.clipboard_clear()
        self.clipboard_append(" ".join(cmd))
        self._set_status("📋 Perintah disalin ke clipboard!", "#2FA572")

    # ══════════════════════════════════════════════════════
    #  Preset
    # ══════════════════════════════════════════════════════
    def apply_preset(self, preset: str):
        presets = {
            "2K":     ("2560", "120", "32M", "h265"),
            "Tinggi": ("1920", "120", "24M", "h264"),
            "Sedang": ("1280", "60",  "8M",  "h264"),
            "Rendah": ("800",  "30",  "2M",  "h264"),
        }
        if preset in presets:
            r, f, b, c = presets[preset]
            self.res_var.set(r)
            self.fps_var.set(f)
            self.bitrate_var.set(b)
            self.codec_var.set(c)
        self.update_preview()

    # ══════════════════════════════════════════════════════
    #  Profiles
    # ══════════════════════════════════════════════════════
    def _profile_path(self) -> str:
        return os.path.join(self.scrcpy_dir, PROFILES_FILE)

    def _load_profiles(self) -> dict:
        try:
            with open(self._profile_path(), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_profiles(self):
        try:
            with open(self._profile_path(), "w", encoding="utf-8") as f:
                json.dump(self.profiles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._set_status(f"❌ Gagal simpan profil: {e}", "#FF5252")

    def save_profile(self):
        name = self.profile_name_var.get().strip()
        if not name:
            self._set_status("⚠️ Masukkan nama profil dulu.", "orange")
            return
        self.profiles[name] = {
            "res": self.res_var.get(), "fps": self.fps_var.get(),
            "bitrate": self.bitrate_var.get(), "codec": self.codec_var.get(),
            "stay_awake": self.stay_awake_var.get(), "turn_off": self.turn_off_var.get(),
            "on_top": self.on_top_var.get(), "no_audio": self.no_audio_var.get(),
            "fullscreen": self.fullscreen_var.get(), "uhid": self.uhid_var.get(),
            "copy_paste": self.copy_paste_var.get(), "volume_keys": self.volume_keys_var.get(),
            "otg": self.otg_var.get(), "no_control": self.no_control_var.get(),
            "new_display": self.new_display_var.get(), "vdisplay_res": self.vdisplay_res_var.get(),
            "vd_mouse_mode": self.vd_mouse_mode_var.get(), "vd_kbd_mode": self.vd_kbd_mode_var.get(),
            "start_app": self.start_app_var.get(), "new_task": self.new_task_var.get(),
            "record": self.record_var.get(), "record_path": self.record_path_var.get(),
            "audio_buffer": self.audio_buffer_var.get(), "show_touches": self.show_touches_var.get(),
            "borderless": self.borderless_var.get(),
        }
        self._write_profiles()
        names = list(self.profiles.keys())
        self.profile_menu.configure(values=names)
        self.profile_var.set(name)
        self._set_status(f"✅ Profil '{name}' disimpan.", "#2FA572")

    def load_profile(self):
        name = self.profile_var.get()
        if name not in self.profiles:
            return
        p = self.profiles[name]
        self.res_var.set(p.get("res", "1280"))
        self.fps_var.set(p.get("fps", "60"))
        self.bitrate_var.set(p.get("bitrate", "8M"))
        self.codec_var.set(p.get("codec", "h264"))
        self.stay_awake_var.set(p.get("stay_awake", False))
        self.turn_off_var.set(p.get("turn_off", False))
        self.on_top_var.set(p.get("on_top", False))
        self.no_audio_var.set(p.get("no_audio", False))
        self.fullscreen_var.set(p.get("fullscreen", False))
        self.uhid_var.set(p.get("uhid", False))
        self.copy_paste_var.set(p.get("copy_paste", True))
        self.volume_keys_var.set(p.get("volume_keys", True))
        self.otg_var.set(p.get("otg", False))
        self.no_control_var.set(p.get("no_control", False))
        self.new_display_var.set(p.get("new_display", False))
        self.vdisplay_res_var.set(p.get("vdisplay_res", "Bawaan"))
        self.vd_mouse_mode_var.set(p.get("vd_mouse_mode", "disabled"))
        self.vd_kbd_mode_var.set(p.get("vd_kbd_mode", "sdk"))
        self.start_app_var.set(p.get("start_app", ""))
        self.new_task_var.set(p.get("new_task", True))
        self.record_var.set(p.get("record", False))
        self.record_path_var.set(p.get("record_path", "rekaman.mp4"))
        self.audio_buffer_var.set(p.get("audio_buffer", "200"))
        self.show_touches_var.set(p.get("show_touches", False))
        self.borderless_var.set(p.get("borderless", False))
        self._set_status(f"✅ Profil '{name}' dimuat.", "#2FA572")
        self.update_preview()

    def delete_profile(self):
        name = self.profile_var.get()
        if name not in self.profiles:
            return
        del self.profiles[name]
        self._write_profiles()
        names = list(self.profiles.keys()) or ["(belum ada profil)"]
        self.profile_menu.configure(values=names)
        self.profile_var.set(names[0])
        self._set_status(f"🗑 Profil '{name}' dihapus.", "gray")

    # ══════════════════════════════════════════════════════
    #  Launch & Stop
    # ══════════════════════════════════════════════════════
    def launch_scrcpy(self):
        # Validasi layar virtual
        if self.new_display_var.get() and not self.start_app_var.get().strip():
            self._set_status(
                "⚠️ Isi 'Buka Aplikasi' dulu — tanpa app, layar virtual akan hitam!",
                "#F39C12"
            )
            return

        # Cek scrcpy.exe ada
        if not os.path.isfile(self._scrcpy):
            self._set_status(f"❌ scrcpy.exe tidak ditemukan di: {self.scrcpy_dir}", "#FF5252")
            return

        self.update_preview()
        cmd = self.build_command()

        # Siapkan environment (audio speaker)
        env = os.environ.copy()
        audio = self.speaker_var.get()
        if audio != "Bawaan (Sistem)":
            env["SDL_AUDIO_DEVICE_NAME"] = audio

        self.launch_btn.configure(state="disabled", text="⏳  BERJALAN...", fg_color="#F39C12")
        self.stop_btn.configure(state="normal")
        self._set_status("⏳ Memulai Scrcpy...", "#F39C12")

        threading.Thread(target=self._run_scrcpy_task, args=(cmd, env), daemon=True).start()

    def _run_scrcpy_task(self, cmd: list[str], env: dict):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self._scrcpy_proc = subprocess.Popen(
                cmd, cwd=self.scrcpy_dir, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=flags
            )
            _, stderr = self._scrcpy_proc.communicate()
            rc = self._scrcpy_proc.returncode
            self._scrcpy_proc = None

            if rc not in (0, -1):    # -1 = killed via stop
                err_lines = [l.strip() for l in (stderr or "").splitlines() if l.strip()]
                err = err_lines[-1] if err_lines else f"Kode keluar: {rc}"
                def _fail():
                    self._set_status(f"❌ Gagal: {err}", "#FF5252")
                    self._reset_launch_btn()
                self.after(0, _fail)
            else:
                def _ok():
                    self._set_status("✅ Sesi Scrcpy selesai.", "gray")
                    self._reset_launch_btn()
                self.after(0, _ok)

        except FileNotFoundError:
            def _nf():
                self._set_status(f"❌ scrcpy.exe tidak ditemukan!", "#FF5252")
                self._reset_launch_btn()
            self.after(0, _nf)
        except Exception as e:
            def _err():
                self._set_status(f"❌ Error: {e}", "#FF5252")
                self._reset_launch_btn()
            self.after(0, _err)

    def stop_scrcpy(self):
        if self._scrcpy_proc and self._scrcpy_proc.poll() is None:
            try:
                self._scrcpy_proc.terminate()
                self._set_status("⏹ Scrcpy dihentikan.", "gray")
            except Exception as e:
                self._set_status(f"❌ Gagal hentikan: {e}", "#FF5252")
        self._reset_launch_btn()

    def _reset_launch_btn(self):
        self.launch_btn.configure(state="normal", text="🚀  JALANKAN SCRCPY", fg_color="#0078d4")
        self.stop_btn.configure(state="disabled")

    # ══════════════════════════════════════════════════════
    #  Misc Helpers
    # ══════════════════════════════════════════════════════
    def _set_status(self, msg: str, color: str = "gray"):
        """Update status label — aman dipanggil dari thread manapun via after()."""
        self.after(0, lambda: self.status_label.configure(text=msg, text_color=color))

    def _toggle_fullscreen(self):
        self._is_fullscreen = not self._is_fullscreen
        self.attributes("-fullscreen", self._is_fullscreen)
        if self._is_fullscreen:
            self.bind("<Escape>", lambda e: self._toggle_fullscreen())
        else:
            self.unbind("<Escape>")


# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ScrcpyLauncher()
    app.mainloop()