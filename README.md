# 🚀 Scrcpy Pro Launcher v4.0

Selamat datang di **Scrcpy Pro Launcher**, solusi GUI modern dan canggih untuk mengontrol perangkat Android Anda melalui PC menggunakan engine **scrcpy**. Launcher ini dirancang untuk memberikan pengalaman "plug-and-play" dengan fitur profesional yang mudah diakses.

---

## 🌟 Fitur Utama

- **Konektivitas Fleksibel**: Mendukung koneksi via USB maupun WiFi ADB secara otomatis.
- **Wireless Debugging Toggle**: Aktifkan atau matikan fitur *Wireless Debugging* langsung dari aplikasi tanpa menyentuh HP.
- **Network Scanner**: Cari perangkat Android di jaringan lokal Anda yang siap untuk di-remote.
- **Multi-Tasking (Virtual Display)**: Buat layar virtual terpisah! Anda bisa membuka aplikasi di window PC sementara layar fisik HP tetap bisa digunakan untuk hal lain (Memerlukan Android 13+).
- **Preset Kualitas**: Pilihan cepat mulai dari resolusi Rendah hingga **2K Ultra High Performance**.
- **Audio Output**: Teruskan suara HP ke speaker PC pilihan Anda dengan sinkronisasi buffer yang dapat disesuaikan.
- **Screen Recording**: Rekam aktivitas layar langsung ke format `.mp4` atau `.mkv`.
- **Profil Pengaturan**: Simpan konfigurasi favorit Anda untuk berbagai skenario penggunaan.
- **UI Modern**: Dibangun dengan *CustomTkinter* untuk tampilan Dark Mode yang elegan dan responsif.

---

## 🛠️ Persyaratan Sistem

1. **Perangkat Android**: Pastikan *Developer Options* dan *USB Debugging* sudah aktif.
2. **PC Windows**: Aplikasi ini dioptimalkan untuk Windows.
3. **Python (Jika menjalankan via script)**:
   - Install dependencies: `pip install customtkinter sounddevice`
4. **Scrcpy Binaries**: Semua file pendukung (adb.exe, scrcpy.exe) harus berada di folder yang sama.

---

## 🚀 Cara Penggunaan

### 1. Menjalankan Aplikasi
- Klik dua kali pada `Scrcpy-Modern-Launcher.exe` atau jalankan `Scrcpy-Modern-Launcher.bat`.
- Jika Anda pengembang, jalankan `python scrcpy_launcher.py`.

### 2. Menyambungkan Perangkat
- **USB**: Hubungkan HP via kabel data, klik tombol 🔄 untuk refresh.
- **WiFi**:
  - Jika sudah tersambung USB, klik **🌐 Aktifkan** pada bagian WiFi ADB untuk mendapatkan IP otomatis.
  - Atau masukkan IP manual pada kolom IP:Port lalu klik **🔗 Sambung**.

### 3. Menggunakan Multi-Tasking (Virtual Display)
- Centang **Aktifkan Layar Virtual**.
- Masukkan nama package aplikasi (misal: `com.instagram.android`) atau kata kunci (misal: `instagram`).
- Klik **Jalankan**. Window baru akan muncul menampilkan aplikasi tersebut secara terpisah!

### 4. Menyimpan Profil
- Atur resolusi, bitrate, dan audio sesuai keinginan.
- Masukkan nama di kolom profil, lalu klik **💾 Simpan**. Anda bisa memuatnya kembali kapan saja.

---

## 📂 Struktur File

- `scrcpy_launcher.py`: Source code utama aplikasi.
- `adb.exe` & `scrcpy.exe`: Mesin utama komunikasi Android & streaming.
- `scrcpy_profiles.json`: File penyimpanan profil (dibuat otomatis).
- `Scrcpy-Modern-Launcher.bat`: Script pembantu untuk menjalankan launcher.
- `icon.png`: Ikon aplikasi.

---

## 💡 Tips Performa
- Gunakan **Codec AV1** atau **H.265** jika perangkat Anda mendukung untuk kualitas gambar lebih tajam dengan bitrate rendah.
- Jika audio terasa delay, turunkan nilai **Audio Buffer** ke 50ms atau 100ms.
- Gunakan koneksi kabel USB 3.0 untuk latensi paling rendah (hampir nol).

---

## 🤝 Kontribusi
Jika Anda menemukan bug atau ingin menambahkan fitur, silakan buat *Issue* atau *Pull Request* di repository ini.

**Dibuat dengan ❤️ oleh [aziz4212isx](https://github.com/aziz4212isx)**
