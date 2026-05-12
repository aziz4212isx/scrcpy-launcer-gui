import customtkinter as ctk
import subprocess
import os
import threading
import sys
import json
import socket
import ipaddress

try:
    import sounddevice as sd
    has_sounddevice = True
except ImportError:
    has_sounddevice = False

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

PROFILES_FILE = "scrcpy_profiles.json"

class ScrcpyLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Scrcpy Pro Launcher")
        self.geometry("780x920")
        self.resizable(True, True)
        self.minsize(700, 800)

        if getattr(sys, 'frozen', False):
            self.scrcpy_dir = os.path.dirname(sys.executable)
        else:
            self.scrcpy_dir = os.path.dirname(os.path.abspath(__file__))

        self.profiles = self.load_profiles()
        self._is_fullscreen = False
        self._wifi_adb_active = False
        self._wifi_adb_ip = None
        self._usb_debug_on = True   # asumsi ON karena bisa connect ADB
        self.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.bind("<Return>", lambda e: self.launch_scrcpy())

        # Header
        header = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=0, height=70)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="⚡ Scrcpy Pro Launcher", font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"), text_color="#00d4ff").pack(side="left", padx=25, pady=15)
        ctk.CTkLabel(header, text="v3.3.4", font=ctk.CTkFont(size=12), text_color="#555").pack(side="right", padx=25)

        # Main scrollable
        self.main_frame = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=10)

        # === DEVICE SECTION ===
        self._section("📱 Perangkat", self.main_frame)
        dev_frame = ctk.CTkFrame(self.main_frame)
        dev_frame.pack(fill="x", pady=(0,10))
        dev_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(dev_frame, text="Perangkat Terhubung:").grid(row=0, column=0, padx=15, pady=(15,5), sticky="w")
        self.device_var = ctk.StringVar(value="Deteksi otomatis...")
        self.device_menu = ctk.CTkOptionMenu(
            dev_frame, variable=self.device_var,
            values=["Deteksi otomatis..."], dynamic_resizing=False,
            command=self._on_device_change
        )
        self.device_menu.grid(row=0, column=1, padx=(5,5), pady=(15,5), sticky="we")
        ctk.CTkButton(dev_frame, text="🔄", width=40, command=self.refresh_devices).grid(row=0, column=2, padx=(0,15), pady=(15,5))

        ctk.CTkLabel(dev_frame, text="Koneksi WiFi (IP:Port):").grid(row=1, column=0, padx=15, pady=(5,5), sticky="w")
        self.wifi_var = ctk.StringVar()
        ctk.CTkEntry(dev_frame, textvariable=self.wifi_var, placeholder_text="192.168.1.x:5555").grid(row=1, column=1, padx=(5,5), pady=(5,5), sticky="we")
        ctk.CTkButton(dev_frame, text="🔗 Sambung", width=80, command=self.connect_wifi).grid(row=1, column=2, padx=(0,15), pady=(5,5))

        # Aktifkan WiFi ADB row
        ctk.CTkLabel(dev_frame, text="WiFi ADB (USB→WiFi):").grid(row=2, column=0, padx=15, pady=(5,5), sticky="w")
        self.enable_wifi_status_var = ctk.StringVar(value="Hubungkan USB dulu lalu klik →")
        ctk.CTkLabel(dev_frame, textvariable=self.enable_wifi_status_var, text_color="gray", font=ctk.CTkFont(size=11)).grid(row=2, column=1, padx=(5,5), pady=(5,5), sticky="w")
        self.enable_wifi_btn = ctk.CTkButton(dev_frame, text="🌐 Aktifkan", width=80, command=self.enable_wifi_adb, fg_color="#6a0dad", hover_color="#9b30ff")
        self.enable_wifi_btn.grid(row=2, column=2, padx=(0,15), pady=(5,5))

        # WiFi Scan row
        ctk.CTkLabel(dev_frame, text="Scan Perangkat WiFi:").grid(row=3, column=0, padx=15, pady=(5,5), sticky="w")
        self.scan_status_var = ctk.StringVar(value="Belum di-scan")
        self.scan_status_lbl = ctk.CTkLabel(dev_frame, textvariable=self.scan_status_var, text_color="gray", font=ctk.CTkFont(size=11))
        self.scan_status_lbl.grid(row=3, column=1, padx=(5,5), pady=(5,5), sticky="w")
        self.scan_btn = ctk.CTkButton(dev_frame, text="🔍 Scan", width=80, command=self.scan_wifi_devices, fg_color="#1a472a", hover_color="#2d6a4f")
        self.scan_btn.grid(row=3, column=2, padx=(0,15), pady=(5,5))

        # WiFi ADB toggle (on/off di sisi HP)
        ctk.CTkLabel(dev_frame, text="WiFi ADB di HP:").grid(row=4, column=0, padx=15, pady=(5,15), sticky="w")
        self.usb_debug_status_var = ctk.StringVar(value="Sambung WiFi ADB dulu")
        ctk.CTkLabel(dev_frame, textvariable=self.usb_debug_status_var, text_color="gray", font=ctk.CTkFont(size=11)).grid(row=4, column=1, padx=(5,5), pady=(5,15), sticky="w")
        self.usb_debug_btn = ctk.CTkButton(
            dev_frame, text="🟢 WiFi ADB: ON", width=120,
            command=self.toggle_usb_debug,
            fg_color="#1a472a", hover_color="#2d6a4f"
        )
        self.usb_debug_btn.grid(row=4, column=2, padx=(0,15), pady=(5,15))

        # === QUALITY SECTION ===
        self._section("📐 Kualitas & Resolusi", self.main_frame)
        q_frame = ctk.CTkFrame(self.main_frame)
        q_frame.pack(fill="x", pady=(0,10))
        q_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(q_frame, text="Preset Cepat:").grid(row=0, column=0, padx=15, pady=(15,5), sticky="w")
        self.preset_var = ctk.StringVar(value="Sedang")
        ctk.CTkSegmentedButton(q_frame, values=["2K","Tinggi","Sedang","Rendah","Kustom"], variable=self.preset_var, command=self.apply_preset).grid(row=0, column=1, columnspan=2, padx=15, pady=(15,5), sticky="we")

        ctk.CTkLabel(q_frame, text="Resolusi Maks:").grid(row=1, column=0, padx=15, pady=5, sticky="w")
        self.res_var = ctk.StringVar(value="1280")
        ctk.CTkOptionMenu(q_frame, values=["Bawaan","2560","1920","1280","1024","800"], variable=self.res_var).grid(row=1, column=1, padx=15, pady=5, sticky="we")

        ctk.CTkLabel(q_frame, text="FPS Maks:").grid(row=2, column=0, padx=15, pady=5, sticky="w")
        self.fps_var = ctk.StringVar(value="60")
        ctk.CTkOptionMenu(q_frame, values=["144","120","90","60","30"], variable=self.fps_var).grid(row=2, column=1, padx=15, pady=5, sticky="we")

        ctk.CTkLabel(q_frame, text="Bitrate Video:").grid(row=3, column=0, padx=15, pady=5, sticky="w")
        self.bitrate_var = ctk.StringVar(value="8M")
        ctk.CTkOptionMenu(q_frame, values=["32M","24M","16M","8M","4M","2M"], variable=self.bitrate_var).grid(row=3, column=1, padx=15, pady=5, sticky="we")

        ctk.CTkLabel(q_frame, text="Codec Video:").grid(row=4, column=0, padx=15, pady=(5,15), sticky="w")
        self.codec_var = ctk.StringVar(value="h264")
        ctk.CTkOptionMenu(q_frame, values=["h264","h265","av1"], variable=self.codec_var).grid(row=4, column=1, padx=15, pady=(5,15), sticky="we")

        # === AUDIO SECTION ===
        self._section("🔊 Audio", self.main_frame)
        a_frame = ctk.CTkFrame(self.main_frame)
        a_frame.pack(fill="x", pady=(0,10))
        a_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(a_frame, text="Speaker Keluaran:").grid(row=0, column=0, padx=15, pady=15, sticky="w")
        self.audio_devices = ["Bawaan (Sistem)"]
        if has_sounddevice:
            try:
                seen = set()
                for d in sd.query_devices():
                    if d['max_output_channels'] > 0 and d['name'] not in seen:
                        self.audio_devices.append(d['name']); seen.add(d['name'])
            except: pass
        self.speaker_var = ctk.StringVar(value="Bawaan (Sistem)")
        ctk.CTkOptionMenu(a_frame, values=self.audio_devices, variable=self.speaker_var, dynamic_resizing=False).grid(row=0, column=1, padx=15, pady=15, sticky="we")

        # === BEHAVIOUR SECTION ===
        self._section("🖥️ Perilaku Layar", self.main_frame)
        b_frame = ctk.CTkFrame(self.main_frame)
        b_frame.pack(fill="x", pady=(0,10))
        b_inner = ctk.CTkFrame(b_frame, fg_color="transparent")
        b_inner.pack(fill="x", padx=15, pady=15)

        self.stay_awake_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(b_inner, text="HP Tetap Menyala", variable=self.stay_awake_var).grid(row=0, column=0, sticky="w", pady=5)
        self.turn_off_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(b_inner, text="Matikan Layar HP", variable=self.turn_off_var).grid(row=0, column=1, sticky="w", pady=5, padx=20)
        self.on_top_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(b_inner, text="Selalu di Atas", variable=self.on_top_var).grid(row=1, column=0, sticky="w", pady=5)
        self.no_audio_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(b_inner, text="Matikan Suara HP", variable=self.no_audio_var).grid(row=1, column=1, sticky="w", pady=5, padx=20)
        self.fullscreen_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(b_inner, text="Mulai Fullscreen", variable=self.fullscreen_var).grid(row=2, column=0, sticky="w", pady=5)
        self.show_touches_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(b_inner, text="Tampilkan Sentuhan", variable=self.show_touches_var).grid(row=2, column=1, sticky="w", pady=5, padx=20)
        self.borderless_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(b_inner, text="Tanpa Border Window", variable=self.borderless_var).grid(row=3, column=0, sticky="w", pady=5)

        # === KEYBOARD/MOUSE SECTION ===
        self._section("⌨️ Keyboard & Mouse", self.main_frame)
        km_frame = ctk.CTkFrame(self.main_frame)
        km_frame.pack(fill="x", pady=(0,10))
        km_inner = ctk.CTkFrame(km_frame, fg_color="transparent")
        km_inner.pack(fill="x", padx=15, pady=15)

        self.uhid_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(km_inner, text="Mode UHID (Keyboard/Mouse Asli)", variable=self.uhid_var).grid(row=0, column=0, sticky="w", pady=5)
        self.copy_paste_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(km_inner, text="Sinkronisasi Copy-Paste", variable=self.copy_paste_var).grid(row=0, column=1, sticky="w", pady=5, padx=20)
        self.volume_keys_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(km_inner, text="Tombol Volume PC", variable=self.volume_keys_var).grid(row=1, column=0, sticky="w", pady=5)

        # === MULTI-TASKING SECTION ===
        self._section("📲 Multi-Tasking (Layar Virtual)", self.main_frame)
        mt_frame = ctk.CTkFrame(self.main_frame)
        mt_frame.pack(fill="x", pady=(0,10))
        ctk.CTkLabel(mt_frame,
                     text="Buat layar virtual terpisah — HP bisa buka app lain sementara scrcpy tetap berjalan (Android 13+)",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=15, pady=(8,4))

        mt_inner = ctk.CTkFrame(mt_frame, fg_color="transparent")
        mt_inner.pack(fill="x", padx=15, pady=(0,15))
        mt_inner.grid_columnconfigure(1, weight=1)

        self.new_display_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(mt_inner, text="Aktifkan Layar Virtual",
                        variable=self.new_display_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=5)

        ctk.CTkLabel(mt_inner, text="Resolusi Virtual:").grid(row=1, column=0, sticky="w", pady=5)
        self.vdisplay_res_var = ctk.StringVar(value="Bawaan")
        ctk.CTkOptionMenu(mt_inner,
                          values=["Bawaan", "1280x720", "1920x1080", "2560x1440", "720x1280", "1080x1920"],
                          variable=self.vdisplay_res_var).grid(row=1, column=1, sticky="w", padx=(10,0), pady=5)

        ctk.CTkLabel(mt_inner, text="Buka Aplikasi:").grid(row=2, column=0, sticky="w", pady=(8,2))
        self.start_app_var = ctk.StringVar()
        ctk.CTkEntry(mt_inner, textvariable=self.start_app_var,
                     placeholder_text="Contoh: com.instagram.android atau: instagram",
                     width=350).grid(row=3, column=0, columnspan=2, sticky="we", pady=(0,4))

        ctk.CTkLabel(mt_inner, text_color="gray",
                     text="Nama pendek (instagram) → otomatis fuzzy search. Package lengkap (com.x.y) → langsung.",
                     font=ctk.CTkFont(size=10)).grid(row=4, column=0, columnspan=2, sticky="w")

        self.new_task_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(mt_inner, text="Buka di task baru (seperti tap ikon app)",
                        variable=self.new_task_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6,0))

        # Warning label — muncul jika checkbox aktif tapi app kosong
        self.mt_warning_lbl = ctk.CTkLabel(
            mt_inner,
            text="⚠️ Isi 'Buka Aplikasi' dulu — tanpa app, layar virtual akan hitam!\n"
                 "⚠️ Catatan: beberapa Xiaomi/Samsung mungkin tidak support layar virtual.",
            text_color="#F39C12", font=ctk.CTkFont(size=11), justify="left"
        )
        self.mt_warning_lbl.grid(row=6, column=0, columnspan=2, sticky="w", pady=(4,4))
        self.mt_warning_lbl.grid_remove()  # sembunyikan dulu

        # Tampilkan/sembunyikan warning saat checkbox atau entry berubah
        def _update_mt_warning(*_):
            show = self.new_display_var.get() and not self.start_app_var.get().strip()
            if show:
                self.mt_warning_lbl.grid()
            else:
                self.mt_warning_lbl.grid_remove()
        self.new_display_var.trace_add("write", _update_mt_warning)
        self.start_app_var.trace_add("write", _update_mt_warning)

        # === RECORD SECTION ===
        self._section("🎬 Rekam Layar", self.main_frame)
        rec_frame = ctk.CTkFrame(self.main_frame)
        rec_frame.pack(fill="x", pady=(0,10))
        rec_inner = ctk.CTkFrame(rec_frame, fg_color="transparent")
        rec_inner.pack(fill="x", padx=15, pady=15)

        self.record_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(rec_inner, text="Aktifkan Rekaman", variable=self.record_var).grid(row=0, column=0, sticky="w", pady=5)
        ctk.CTkLabel(rec_inner, text="Simpan ke file:").grid(row=1, column=0, sticky="w", pady=(10,2))
        self.record_path_var = ctk.StringVar(value="rekaman.mp4")
        ctk.CTkEntry(rec_inner, textvariable=self.record_path_var, width=300).grid(row=2, column=0, sticky="we", pady=(0,5))
        ctk.CTkLabel(rec_inner, text="(letakkan di folder manapun, ekstensi .mp4/.mkv)", text_color="gray", font=ctk.CTkFont(size=11)).grid(row=3, column=0, sticky="w")

        # === PROFILES SECTION ===
        self._section("💾 Profil Pengaturan", self.main_frame)
        pf_frame = ctk.CTkFrame(self.main_frame)
        pf_frame.pack(fill="x", pady=(0,10))
        pf_inner = ctk.CTkFrame(pf_frame, fg_color="transparent")
        pf_inner.pack(fill="x", padx=15, pady=15)

        profile_names = list(self.profiles.keys()) if self.profiles else ["(belum ada profil)"]
        self.profile_var = ctk.StringVar(value=profile_names[0])
        self.profile_menu = ctk.CTkOptionMenu(pf_inner, values=profile_names, variable=self.profile_var, width=200)
        self.profile_menu.grid(row=0, column=0, sticky="w", pady=5)
        ctk.CTkButton(pf_inner, text="📂 Muat", width=80, command=self.load_profile).grid(row=0, column=1, padx=10, pady=5)
        self.profile_name_var = ctk.StringVar()
        ctk.CTkEntry(pf_inner, textvariable=self.profile_name_var, placeholder_text="Nama profil baru...", width=200).grid(row=1, column=0, sticky="w", pady=(10,5))
        ctk.CTkButton(pf_inner, text="💾 Simpan", width=80, command=self.save_profile).grid(row=1, column=1, padx=10, pady=(10,5))

        # === COMMAND PREVIEW ===
        self._section("🔍 Pratinjau Perintah", self.main_frame)
        prev_frame = ctk.CTkFrame(self.main_frame)
        prev_frame.pack(fill="x", pady=(0,10))
        self.cmd_preview = ctk.CTkTextbox(prev_frame, height=55, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#0d1117", text_color="#58a6ff")
        self.cmd_preview.pack(fill="x", padx=15, pady=15)
        ctk.CTkButton(prev_frame, text="🔄 Perbarui Pratinjau", command=self.update_preview, width=160).pack(anchor="e", padx=15, pady=(0,10))

        # === STATUS & LAUNCH ===
        self.status_label = ctk.CTkLabel(self.main_frame, text="✅ Siap. Hubungkan HP via USB atau WiFi.", text_color="gray", font=ctk.CTkFont(size=12))
        self.status_label.pack(pady=(5,5))

        self.launch_btn = ctk.CTkButton(
            self.main_frame, text="🚀  JALANKAN SCRCPY",
            font=ctk.CTkFont(weight="bold", size=19), height=60,
            corner_radius=12, fg_color="#0078d4", hover_color="#005fa3",
            command=self.launch_scrcpy
        )
        self.launch_btn.pack(fill="x", padx=30, pady=(5,20))

        self.apply_preset("Sedang")
        self.refresh_devices()
        self.update_preview()

    def _section(self, title, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=(8,2))
        ctk.CTkLabel(f, text=title, font=ctk.CTkFont(weight="bold", size=14), text_color="#00d4ff").pack(anchor="w", padx=5)
        ctk.CTkFrame(parent, height=1, fg_color="#333").pack(fill="x", pady=(0,5))

    def apply_preset(self, preset):
        presets = {
            "2K":    ("2560","120","32M","h265"),
            "Tinggi":("1920","120","24M","h264"),
            "Sedang":("1280","60","8M","h264"),
            "Rendah":("800","30","2M","h264"),
        }
        if preset in presets:
            r,f,b,c = presets[preset]
            self.res_var.set(r); self.fps_var.set(f)
            self.bitrate_var.set(b); self.codec_var.set(c)

    def refresh_devices(self):
        def task():
            try:
                adb = os.path.join(self.scrcpy_dir, "adb.exe")
                result = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=5)
                lines = [l.split("\t")[0] for l in result.stdout.strip().splitlines()[1:] if "device" in l]
                devices = lines if lines else ["Tidak ada perangkat"]
                self.device_var.set(devices[0])
                self.device_menu.configure(values=devices)
                self.status_label.configure(text=f"✅ Ditemukan {len(lines)} perangkat.", text_color="gray")
                # Auto-cek status WiFi ADB pada perangkat pertama
                if lines:
                    self._check_wifi_adb_status(adb, lines[0])
            except Exception as e:
                self.status_label.configure(text=f"⚠️ Gagal scan ADB: {e}", text_color="orange")
        threading.Thread(target=task, daemon=True).start()

    def _check_wifi_adb_status(self, adb, device_id):
        """Cek status adb_wifi_enabled pada perangkat dan update tombol secara otomatis."""
        try:
            r = subprocess.run(
                [adb, "-s", device_id, "shell", "settings", "get", "global", "adb_wifi_enabled"],
                capture_output=True, text=True, timeout=6
            )
            val = r.stdout.strip()
            def update():
                if val == "1":
                    self.usb_debug_status_var.set("🟢 Aktif (terdeteksi otomatis)")
                    self.usb_debug_btn.configure(
                        text="🟢 WiFi ADB: ON",
                        fg_color="#1a472a", hover_color="#2d6a4f"
                    )
                elif val == "0":
                    self.usb_debug_status_var.set("🔴 Tidak aktif (terdeteksi otomatis)")
                    self.usb_debug_btn.configure(
                        text="🔴 WiFi ADB: OFF",
                        fg_color="#7f1d1d", hover_color="#991b1b"
                    )
                else:
                    self.usb_debug_status_var.set("⚪ Status tidak diketahui")
                    self.usb_debug_btn.configure(
                        text="🟢 WiFi ADB: ON",
                        fg_color="#1a472a", hover_color="#2d6a4f"
                    )
            self.after(0, update)
        except Exception:
            pass

    def _on_device_change(self, selected):
        """Dipanggil otomatis saat user ganti perangkat di dropdown."""
        invalid = ("Deteksi otomatis...", "Tidak ada perangkat", "")
        if selected in invalid:
            self.usb_debug_status_var.set("Sambungkan perangkat dulu")
            return
        adb = os.path.join(self.scrcpy_dir, "adb.exe")
        self.usb_debug_status_var.set("Mengecek status WiFi ADB...")
        threading.Thread(
            target=self._check_wifi_adb_status, args=(adb, selected), daemon=True
        ).start()

    def toggle_usb_debug(self):
        """Toggle WiFi ADB (Wireless Debugging) ON/OFF di HP.
        Bisa via WiFi ADB maupun USB — otomatis pilih koneksi yang tersedia.
        """
        # Prioritas: WiFi ADB aktif → kolom IP → perangkat USB di dropdown
        target = (
            self._wifi_adb_ip
            or self.wifi_var.get().strip()
            or self.device_var.get().strip()
        )
        invalid = ("", "Deteksi otomatis...", "Tidak ada perangkat")
        if not target or target in invalid:
            self.usb_debug_status_var.set("⚠️ Tidak ada perangkat terhubung!")
            return

        via = "WiFi" if "." in target else "USB"
        self.usb_debug_btn.configure(state="disabled", text="⏳...")
        self.usb_debug_status_var.set(f"Mengecek via {via}...")

        def task():
            adb = os.path.join(self.scrcpy_dir, "adb.exe")
            try:
                # Baca status adb_wifi_enabled (Wireless Debugging)
                check = subprocess.run(
                    [adb, "-s", target, "shell", "settings", "get", "global", "adb_wifi_enabled"],
                    capture_output=True, text=True, timeout=8
                )
                current = check.stdout.strip()

                if current == "1":
                    # Matikan WiFi ADB di HP
                    subprocess.run(
                        [adb, "-s", target, "shell", "settings", "put", "global", "adb_wifi_enabled", "0"],
                        capture_output=True, text=True, timeout=8
                    )
                    def on_off():
                        self.usb_debug_status_var.set("🔴 WiFi ADB dimatikan di HP")
                        self.usb_debug_btn.configure(
                            state="normal", text="🔴 WiFi ADB: OFF",
                            fg_color="#7f1d1d", hover_color="#991b1b"
                        )
                        self.status_label.configure(
                            text="🔴 Wireless Debugging dinonaktifkan di HP",
                            text_color="gray"
                        )
                    self.after(0, on_off)

                else:
                    # Nyalakan WiFi ADB di HP (current == "0" atau null)
                    subprocess.run(
                        [adb, "-s", target, "shell", "settings", "put", "global", "adb_wifi_enabled", "1"],
                        capture_output=True, text=True, timeout=8
                    )
                    def on_on():
                        self.usb_debug_status_var.set("🟢 WiFi ADB aktif di HP")
                        self.usb_debug_btn.configure(
                            state="normal", text="🟢 WiFi ADB: ON",
                            fg_color="#1a472a", hover_color="#2d6a4f"
                        )
                        self.status_label.configure(
                            text="🟢 Wireless Debugging diaktifkan di HP",
                            text_color="#2FA572"
                        )
                    self.after(0, on_on)

                # Verifikasi ulang status nyata dari HP setelah 1.5 detik (on maupun off)
                import time as _time; _time.sleep(1.5)
                self._check_wifi_adb_status(adb, target)

            except Exception as e:
                def on_err():
                    self.usb_debug_status_var.set(f"❌ Error: {e}")
                    self.usb_debug_btn.configure(
                        state="normal", text="🟢 WiFi ADB: ON",
                        fg_color="#1a472a", hover_color="#2d6a4f"
                    )
                self.after(0, on_err)

        threading.Thread(target=task, daemon=True).start()

    def connect_wifi(self):
        ip = self.wifi_var.get().strip()
        if not ip:
            self.status_label.configure(text="⚠️ Masukkan IP:Port terlebih dahulu.", text_color="orange"); return
        def task():
            try:
                adb = os.path.join(self.scrcpy_dir, "adb.exe")
                result = subprocess.run([adb, "connect", ip], capture_output=True, text=True, timeout=8)
                self.status_label.configure(text=f"WiFi: {result.stdout.strip()}", text_color="#2FA572")
                self.refresh_devices()
            except Exception as e:
                self.status_label.configure(text=f"Gagal: {e}", text_color="#FF5252")
        threading.Thread(target=task, daemon=True).start()

    def enable_wifi_adb(self):
        """Toggle: aktifkan atau nonaktifkan ADB over WiFi."""
        if self._wifi_adb_active:
            self._do_disable_wifi_adb()
        else:
            self._do_enable_wifi_adb()

    def _do_enable_wifi_adb(self):
        """Aktifkan ADB over WiFi pada perangkat USB yang terpilih."""
        sel = self.device_var.get()
        if not sel or sel in ("Deteksi otomatis...", "Tidak ada perangkat"):
            self.enable_wifi_status_var.set("⚠️ Pilih perangkat USB dulu!")
            return
        if ":" in sel:
            self.enable_wifi_status_var.set("⚠️ Perangkat ini sudah via WiFi")
            return

        self.enable_wifi_btn.configure(state="disabled", text="⏳...")
        self.enable_wifi_status_var.set("Mengaktifkan ADB WiFi...")

        def task():
            adb = os.path.join(self.scrcpy_dir, "adb.exe")
            try:
                # 1. Aktifkan mode TCP/IP port 5555
                r = subprocess.run([adb, "-s", sel, "tcpip", "5555"],
                                   capture_output=True, text=True, timeout=10)
                if "restarting" not in r.stdout.lower() and r.returncode != 0:
                    self.after(0, lambda: (
                        self.enable_wifi_status_var.set("❌ Gagal: " + r.stderr.strip()[:40]),
                        self.enable_wifi_btn.configure(state="normal", text="🌐 Aktifkan",
                                                       fg_color="#6a0dad", hover_color="#9b30ff")
                    ))
                    return

                # 2. Ambil IP WiFi dari HP
                ip_raw = subprocess.run(
                    [adb, "-s", sel, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"],
                    capture_output=True, text=True, timeout=8
                ).stdout
                device_ip = None
                for line in ip_raw.splitlines():
                    line = line.strip()
                    if line.startswith("inet "):
                        device_ip = line.split()[1].split("/")[0]
                        break

                # Fallback: interface lain
                if not device_ip:
                    for iface in ("wlan1", "swlan0", "rmnet_data0"):
                        ip_raw2 = subprocess.run(
                            [adb, "-s", sel, "shell", "ip", "-f", "inet", "addr", "show", iface],
                            capture_output=True, text=True, timeout=5
                        ).stdout
                        for line in ip_raw2.splitlines():
                            line = line.strip()
                            if line.startswith("inet ") and not line.split()[1].startswith("127"):
                                device_ip = line.split()[1].split("/")[0]
                                break
                        if device_ip:
                            break

                if device_ip:
                    ip_port = f"{device_ip}:5555"
                    def on_success():
                        self._wifi_adb_active = True
                        self._wifi_adb_ip = ip_port
                        self.wifi_var.set(ip_port)
                        self.enable_wifi_status_var.set(f"🟢 Aktif: {ip_port}")
                        self.enable_wifi_btn.configure(
                            state="normal", text="🔴 Nonaktifkan",
                            fg_color="#7f1d1d", hover_color="#991b1b"
                        )
                        self.status_label.configure(
                            text=f"✅ WiFi ADB aktif di {ip_port} — klik Scan atau Sambung",
                            text_color="#2FA572"
                        )
                    self.after(0, on_success)
                else:
                    def on_no_ip():
                        self.enable_wifi_status_var.set("⚠️ IP tidak ditemukan — pastikan HP terhubung WiFi")
                        self.enable_wifi_btn.configure(state="normal", text="🌐 Aktifkan",
                                                       fg_color="#6a0dad", hover_color="#9b30ff")
                    self.after(0, on_no_ip)

            except Exception as e:
                def on_err():
                    self.enable_wifi_status_var.set(f"❌ Error: {e}")
                    self.enable_wifi_btn.configure(state="normal", text="🌐 Aktifkan",
                                                   fg_color="#6a0dad", hover_color="#9b30ff")
                self.after(0, on_err)

        threading.Thread(target=task, daemon=True).start()

    def _do_disable_wifi_adb(self):
        """Nonaktifkan ADB over WiFi: disconnect dan kembalikan ke mode USB."""
        self.enable_wifi_btn.configure(state="disabled", text="⏳...")
        self.enable_wifi_status_var.set("Menonaktifkan ADB WiFi...")

        ip_to_disconnect = self._wifi_adb_ip

        def task():
            adb = os.path.join(self.scrcpy_dir, "adb.exe")
            try:
                # Disconnect koneksi WiFi
                if ip_to_disconnect:
                    subprocess.run([adb, "disconnect", ip_to_disconnect],
                                   capture_output=True, text=True, timeout=8)
                # Kembalikan ke mode USB
                subprocess.run([adb, "usb"], capture_output=True, text=True, timeout=10)

                def on_done():
                    self._wifi_adb_active = False
                    self._wifi_adb_ip = None
                    self.enable_wifi_status_var.set("🔴 ADB WiFi dinonaktifkan")
                    self.enable_wifi_btn.configure(
                        state="normal", text="🌐 Aktifkan",
                        fg_color="#6a0dad", hover_color="#9b30ff"
                    )
                    self.status_label.configure(
                        text="🔒 ADB WiFi dinonaktifkan — kembali ke mode USB",
                        text_color="gray"
                    )
                    self.refresh_devices()
                self.after(0, on_done)

            except Exception as e:
                def on_err():
                    self.enable_wifi_status_var.set(f"❌ Error nonaktifkan: {e}")
                    self.enable_wifi_btn.configure(
                        state="normal", text="🔴 Nonaktifkan",
                        fg_color="#7f1d1d", hover_color="#991b1b"
                    )
                self.after(0, on_err)

        threading.Thread(target=task, daemon=True).start()

    def scan_wifi_devices(self):
        """Scan jaringan lokal untuk perangkat Android (port ADB 5555)."""
        self.scan_btn.configure(state="disabled", text="⏳ Scan...")
        self.scan_status_var.set("Sedang scan jaringan...")
        self.scan_status_lbl.configure(text_color="#F39C12")

        def task():
            found = []
            # --- Metode 1: ADB mDNS (Android 11+) ---
            try:
                adb = os.path.join(self.scrcpy_dir, "adb.exe")
                r = subprocess.run([adb, "mdns", "services"], capture_output=True, text=True, timeout=5)
                for line in r.stdout.splitlines():
                    parts = line.strip().split()
                    if parts and ":" in parts[-1] and "adb" in line.lower():
                        ip_port = parts[-1]
                        if ip_port not in found:
                            found.append(ip_port)
            except Exception:
                pass

            # --- Metode 2: Perangkat TCP yang sudah terdaftar di ADB ---
            try:
                adb = os.path.join(self.scrcpy_dir, "adb.exe")
                r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=5)
                for line in r.stdout.splitlines()[1:]:
                    if "device" in line and ":" in line.split("\t")[0]:
                        ip_port = line.split("\t")[0].strip()
                        if ip_port not in found:
                            found.append(ip_port)
            except Exception:
                pass

            # --- Metode 3: Scan subnet lokal port 5555 ---
            try:
                local_ip = socket.gethostbyname(socket.gethostname())
                network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
                scan_results = []
                lock = threading.Lock()

                def check_host(host):
                    ip_str = str(host)
                    if ip_str == local_ip:
                        return
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(0.5)
                        if s.connect_ex((ip_str, 5555)) == 0:
                            with lock:
                                entry = f"{ip_str}:5555"
                                if entry not in found and entry not in scan_results:
                                    scan_results.append(entry)
                        s.close()
                    except Exception:
                        pass

                threads = []
                for host in network.hosts():
                    t = threading.Thread(target=check_host, args=(host,), daemon=True)
                    threads.append(t)
                    t.start()
                for t in threads:
                    t.join(timeout=2)
                found.extend(scan_results)
            except Exception:
                pass

            # --- Ambil nama model setiap perangkat ---
            adb = os.path.join(self.scrcpy_dir, "adb.exe")
            devices = {ip: self._get_device_name(adb, ip) for ip in found}

            def update_ui():
                self.scan_btn.configure(state="normal", text="🔍 Scan")
                if devices:
                    self.scan_status_var.set(f"✅ {len(devices)} perangkat ditemukan")
                    self.scan_status_lbl.configure(text_color="#2FA572")
                    self._show_wifi_scan_results(devices)
                else:
                    self.scan_status_var.set("❌ Tidak ada perangkat ditemukan")
                    self.scan_status_lbl.configure(text_color="#FF5252")
            self.after(0, update_ui)

        threading.Thread(target=task, daemon=True).start()

    def _get_device_name(self, adb, ip_port):
        """Ambil brand + model HP via ADB getprop."""
        try:
            subprocess.run([adb, "connect", ip_port], capture_output=True, text=True, timeout=5)
            model = subprocess.run(
                [adb, "-s", ip_port, "shell", "getprop", "ro.product.model"],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()
            brand = subprocess.run(
                [adb, "-s", ip_port, "shell", "getprop", "ro.product.brand"],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if model:
                return f"{brand} {model}".strip() if brand else model
        except Exception:
            pass
        return "Perangkat Android"

    def _show_wifi_scan_results(self, devices):
        """Tampilkan popup daftar perangkat WiFi yang ditemukan.
        devices = dict {ip_port: nama_model} atau list [ip_port]
        """
        # Normalise: pastikan selalu dict
        if isinstance(devices, list):
            devices = {d: "Perangkat Android" for d in devices}

        dialog = ctk.CTkToplevel(self)
        dialog.title("Hasil Scan WiFi")
        dialog.geometry("440x360")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.focus()

        ctk.CTkLabel(dialog, text="📡 Perangkat WiFi Ditemukan",
                     font=ctk.CTkFont(weight="bold", size=14), text_color="#00d4ff").pack(pady=(15, 5))
        ctk.CTkLabel(dialog, text="Pilih perangkat untuk mengisi kolom IP:",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(pady=(0, 10))

        list_frame = ctk.CTkScrollableFrame(dialog, height=185)
        list_frame.pack(fill="x", padx=15, pady=(0, 10))

        ip_ports = list(devices.keys())
        selected_var = ctk.StringVar(value=ip_ports[0])

        for ip_port, model_name in devices.items():
            row = ctk.CTkFrame(list_frame, fg_color="transparent")
            row.pack(fill="x", pady=3, padx=5)
            ctk.CTkRadioButton(row, text="", variable=selected_var, value=ip_port, width=24).pack(side="left")
            card = ctk.CTkFrame(row, fg_color="#1e1e2e", corner_radius=8)
            card.pack(side="left", fill="x", expand=True, padx=(4, 0))
            ctk.CTkLabel(
                card, text=f"📱  {model_name}",
                font=ctk.CTkFont(weight="bold", size=12), anchor="w"
            ).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(
                card, text=ip_port,
                font=ctk.CTkFont(family="Consolas", size=11), text_color="#888", anchor="w"
            ).pack(anchor="w", padx=12, pady=(0, 6))

        def on_select():
            self.wifi_var.set(selected_var.get())
            chosen = devices.get(selected_var.get(), selected_var.get())
            dialog.destroy()
            self.scan_status_var.set(f"Dipilih: {chosen}")

        def on_connect():
            self.wifi_var.set(selected_var.get())
            dialog.destroy()
            self.connect_wifi()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkButton(btn_frame, text="✅ Pilih", command=on_select,
                      fg_color="#333", hover_color="#444").pack(side="left", expand=True, padx=(0, 5))
        ctk.CTkButton(btn_frame, text="🔗 Pilih & Sambung", command=on_connect,
                      fg_color="#0078d4", hover_color="#005fa3").pack(side="left", expand=True, padx=(5, 0))

    def build_command(self):
        cmd = [os.path.join(self.scrcpy_dir, "scrcpy.exe")]
        sel = self.device_var.get()
        if sel and sel not in ("Deteksi otomatis...", "Tidak ada perangkat"):
            cmd += ["-s", sel]
        if self.res_var.get() != "Bawaan":
            cmd.append(f"--max-size={self.res_var.get()}")
        cmd += [f"--max-fps={self.fps_var.get()}", f"--video-bit-rate={self.bitrate_var.get()}", f"--video-codec={self.codec_var.get()}"]
        if self.stay_awake_var.get(): cmd.append("--stay-awake")
        if self.turn_off_var.get(): cmd.append("--turn-screen-off")
        if self.on_top_var.get(): cmd.append("--always-on-top")
        if self.no_audio_var.get(): cmd.append("--no-audio")
        if self.fullscreen_var.get(): cmd.append("--fullscreen")
        if self.show_touches_var.get(): cmd.append("--show-touches")
        if self.borderless_var.get(): cmd.append("--window-borderless")
        if self.uhid_var.get(): cmd += ["--keyboard=uhid", "--mouse=uhid"]
        if not self.copy_paste_var.get(): cmd.append("--no-clipboard-autosync")
        if not self.volume_keys_var.get(): cmd.append("--no-key-inject")
        if self.new_display_var.get():
            res = self.vdisplay_res_var.get()
            if res and res != "Bawaan":
                cmd.append(f"--new-display={res}")
            else:
                cmd.append("--new-display")
        app = self.start_app_var.get().strip()
        if app:
            # Auto prefix: '?' untuk fuzzy jika bukan package name lengkap
            prefix = "+" if self.new_task_var.get() else ""
            if "." not in app:
                prefix += "?"   # fuzzy search untuk nama pendek
            cmd.append(f"--start-app={prefix}{app}")
        if self.record_var.get():
            path = self.record_path_var.get().strip() or "rekaman.mp4"
            cmd += ["--record", path]
        return cmd

    def update_preview(self):
        cmd = self.build_command()
        self.cmd_preview.configure(state="normal")
        self.cmd_preview.delete("1.0", "end")
        self.cmd_preview.insert("1.0", " ".join(cmd))
        self.cmd_preview.configure(state="disabled")

    def save_profile(self):
        name = self.profile_name_var.get().strip()
        if not name:
            self.status_label.configure(text="⚠️ Masukkan nama profil dulu.", text_color="orange"); return
        self.profiles[name] = {
            "res": self.res_var.get(), "fps": self.fps_var.get(),
            "bitrate": self.bitrate_var.get(), "codec": self.codec_var.get(),
            "stay_awake": self.stay_awake_var.get(), "turn_off": self.turn_off_var.get(),
            "on_top": self.on_top_var.get(), "no_audio": self.no_audio_var.get(),
            "fullscreen": self.fullscreen_var.get(), "uhid": self.uhid_var.get(),
            "copy_paste": self.copy_paste_var.get(), "new_display": self.new_display_var.get(),
            "start_app": self.start_app_var.get(), "record": self.record_var.get(),
            "record_path": self.record_path_var.get(),
        }
        self._write_profiles()
        self.profile_menu.configure(values=list(self.profiles.keys()))
        self.profile_var.set(name)
        self.status_label.configure(text=f"✅ Profil '{name}' disimpan.", text_color="#2FA572")

    def load_profile(self):
        name = self.profile_var.get()
        if name not in self.profiles: return
        p = self.profiles[name]
        self.res_var.set(p.get("res","1280")); self.fps_var.set(p.get("fps","60"))
        self.bitrate_var.set(p.get("bitrate","8M")); self.codec_var.set(p.get("codec","h264"))
        self.stay_awake_var.set(p.get("stay_awake",False)); self.turn_off_var.set(p.get("turn_off",False))
        self.on_top_var.set(p.get("on_top",False)); self.no_audio_var.set(p.get("no_audio",False))
        self.fullscreen_var.set(p.get("fullscreen",False)); self.uhid_var.set(p.get("uhid",False))
        self.copy_paste_var.set(p.get("copy_paste",True)); self.new_display_var.set(p.get("new_display",False))
        self.start_app_var.set(p.get("start_app","")); self.record_var.set(p.get("record",False))
        self.record_path_var.set(p.get("record_path","rekaman.mp4"))
        self.status_label.configure(text=f"✅ Profil '{name}' dimuat.", text_color="#2FA572")
        self.update_preview()

    def load_profiles(self):
        path = os.path.join(self.scrcpy_dir if not getattr(sys,'frozen',False) else os.path.dirname(sys.executable), PROFILES_FILE)
        try:
            with open(path) as f: return json.load(f)
        except: return {}

    def _write_profiles(self):
        path = os.path.join(self.scrcpy_dir, PROFILES_FILE)
        with open(path, "w") as f: json.dump(self.profiles, f, indent=2)

    def run_scrcpy(self, cmd, env):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            proc = subprocess.Popen(cmd, cwd=self.scrcpy_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
            _, stderr = proc.communicate()
            if proc.returncode != 0:
                err = stderr.strip().split("\n")[-1] if stderr else f"Kode: {proc.returncode}"
                self.status_label.configure(text=f"❌ Gagal: {err}", text_color="#FF5252")
            else:
                self.status_label.configure(text="✅ Sesi Scrcpy selesai.", text_color="gray")
        except Exception as e:
            self.status_label.configure(text=f"❌ Error: {e}", text_color="#FF5252")
        finally:
            self.launch_btn.configure(state="normal", text="🚀  JALANKAN SCRCPY", fg_color="#0078d4")

    def toggle_fullscreen(self):
        self._is_fullscreen = not self._is_fullscreen
        self.attributes("-fullscreen", self._is_fullscreen)
        if self._is_fullscreen:
            self.bind("<Escape>", lambda e: self.toggle_fullscreen())
        else:
            self.unbind("<Escape>")

    def launch_scrcpy(self):
        # Validasi multi-tasking: new-display butuh start-app
        if self.new_display_var.get() and not self.start_app_var.get().strip():
            self.status_label.configure(
                text="⚠️ Isi kolom 'Buka Aplikasi' dulu — tanpa app, layar virtual akan hitam!",
                text_color="#F39C12"
            )
            return
        self.update_preview()
        cmd = self.build_command()
        env = os.environ.copy()
        audio = self.speaker_var.get()
        if audio != "Bawaan (Sistem)": env["SDL_AUDIO_DEVICE_NAME"] = audio
        self.launch_btn.configure(state="disabled", text="⏳  BERJALAN...", fg_color="#F39C12")
        self.status_label.configure(text="⏳ Memulai Scrcpy...", text_color="#F39C12")
        threading.Thread(target=self.run_scrcpy, args=(cmd, env), daemon=True).start()

if __name__ == "__main__":
    app = ScrcpyLauncher()
    app.mainloop()
