use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::collections::HashMap;
use std::net::{TcpStream, SocketAddr};
use std::time::Duration;
use std::path::PathBuf;
use std::thread;
use tauri::{AppHandle, Emitter};
use serde::{Deserialize, Serialize};

// ─── Global State ───────────────────────────────────────────
struct AppState {
    scrcpy_proc: Option<std::process::Child>,
    stop_requested: bool,
    scrcpy_dir: PathBuf,
    adb_path: PathBuf,
    scrcpy_path: PathBuf,
}

impl AppState {
    fn new() -> Self {
        let exe_dir = std::env::current_exe()
            .unwrap_or_default()
            .parent()
            .unwrap_or(&PathBuf::from("."))
            .to_path_buf();
            
        let mut scrcpy_dir = exe_dir.clone();
        
        // Cari adb.exe ke folder atas (berguna saat npm run tauri dev)
        for _ in 0..4 {
            if scrcpy_dir.join("adb.exe").exists() {
                break;
            }
            if let Some(parent) = scrcpy_dir.parent() {
                scrcpy_dir = parent.to_path_buf();
            } else {
                break;
            }
        }

        Self {
            scrcpy_proc: None,
            stop_requested: false,
            adb_path: scrcpy_dir.join("adb.exe"),
            scrcpy_path: scrcpy_dir.join("scrcpy.exe"),
            scrcpy_dir,
        }
    }
}

type State = Arc<Mutex<AppState>>;

// ─── Helper: run ADB command ─────────────────────────────────
fn adb_run(adb: &PathBuf, args: &[&str], timeout_ms: u64) -> (i32, String, String) {
    let mut command = Command::new(adb);
    command.args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    let result = command.spawn();

    match result {
        Err(e) => (-1, String::new(), e.to_string()),
        Ok(mut child) => {
            let stdout = child.stdout.take();
            let stderr = child.stderr.take();
            let child_shared = Arc::new(Mutex::new(Some(child)));
            let child_clone = child_shared.clone();

            // Spawn threads to read stdout and stderr concurrently to prevent pipe buffer deadlock
            let stdout_data = Arc::new(Mutex::new(Vec::new()));
            let stdout_data_clone = stdout_data.clone();
            if let Some(mut out) = stdout {
                thread::spawn(move || {
                    let mut buf = Vec::new();
                    use std::io::Read;
                    let _ = out.read_to_end(&mut buf);
                    *stdout_data_clone.lock().unwrap() = buf;
                });
            }

            let stderr_data = Arc::new(Mutex::new(Vec::new()));
            let stderr_data_clone = stderr_data.clone();
            if let Some(mut err) = stderr {
                thread::spawn(move || {
                    let mut buf = Vec::new();
                    use std::io::Read;
                    let _ = err.read_to_end(&mut buf);
                    *stderr_data_clone.lock().unwrap() = buf;
                });
            }

            // Basic timeout via thread
            let done = Arc::new(Mutex::new(false));
            let done_clone = done.clone();
            thread::spawn(move || {
                thread::sleep(Duration::from_millis(timeout_ms));
                let _ = done_clone.lock().map(|mut d| *d = true);
            });

            loop {
                let mut st_lock = child_clone.lock().unwrap();
                if let Some(ref mut c) = *st_lock {
                    match c.try_wait() {
                        Ok(Some(status)) => {
                            let code = status.code().unwrap_or(-1);
                            drop(st_lock);
                            // Wait briefly for the reader threads to finish reading remaining buffer
                            thread::sleep(Duration::from_millis(50));
                            let stdout_str = String::from_utf8_lossy(&stdout_data.lock().unwrap()).into_owned();
                            let stderr_str = String::from_utf8_lossy(&stderr_data.lock().unwrap()).into_owned();
                            return (code, stdout_str, stderr_str);
                        }
                        Ok(None) => {
                            if *done.lock().unwrap() {
                                let _ = c.kill();
                                drop(st_lock);
                                return (-1, String::new(), "timeout".to_string());
                            }
                            drop(st_lock);
                            thread::sleep(Duration::from_millis(50));
                        }
                        Err(e) => {
                            drop(st_lock);
                            return (-1, String::new(), e.to_string());
                        }
                    }
                } else {
                    return (-1, String::new(), "process error".to_string());
                }
            }
        }
    }
}

// ─── Tauri Commands ──────────────────────────────────────────

#[derive(Serialize)]
pub struct DeviceListResult {
    devices: Vec<String>,
    error: Option<String>,
}

#[tauri::command]
async fn get_devices(state: tauri::State<'_, State>) -> Result<DeviceListResult, String> {
    let adb = state.lock().unwrap().adb_path.clone();
    let (rc, stdout, stderr) = adb_run(&adb, &["devices"], 8000);

    if (rc == -1 && stderr.contains("tidak ditemukan")) || (rc == -1 && stderr.contains("not found")) {
        return Ok(DeviceListResult {
            devices: vec![],
            error: Some("adb.exe tidak ditemukan di folder scrcpy!".to_string()),
        });
    }

    let devices: Vec<String> = stdout
        .lines()
        .skip(1)
        .filter(|l| l.contains("\tdevice"))
        .map(|l| l.split('\t').next().unwrap_or("").trim().to_string())
        .collect();

    Ok(DeviceListResult {
        devices,
        error: None,
    })
}

#[derive(Serialize)]
pub struct WifiAdbStatus {
    status: String, // "on", "off", "unknown"
}

#[tauri::command]
async fn check_wifi_adb_status(device_id: String, state: tauri::State<'_, State>) -> Result<WifiAdbStatus, String> {
    let adb = state.lock().unwrap().adb_path.clone();
    let (_, stdout, _) = adb_run(
        &adb,
        &["-s", &device_id, "shell", "settings", "get", "global", "adb_wifi_enabled"],
        8000,
    );
    let val = stdout.trim().to_string();
    let status = match val.as_str() {
        "1" => "on",
        "0" => "off",
        _ => "unknown",
    };
    Ok(WifiAdbStatus { status: status.to_string() })
}

#[derive(Serialize)]
pub struct ConnectResult {
    success: bool,
    message: String,
}

#[tauri::command]
async fn connect_wifi(ip_port: String, state: tauri::State<'_, State>) -> Result<ConnectResult, String> {
    let adb = state.lock().unwrap().adb_path.clone();
    let (_, stdout, stderr) = adb_run(&adb, &["connect", &ip_port], 10000);
    let msg = if !stdout.trim().is_empty() { stdout.trim().to_string() } else { stderr.trim().to_string() };
    let success = msg.to_lowercase().contains("connected");
    Ok(ConnectResult { success, message: msg })
}

#[derive(Serialize)]
pub struct EnableWifiResult {
    success: bool,
    ip_port: Option<String>,
    error: Option<String>,
}

#[tauri::command]
async fn enable_wifi_adb(device_id: String, state: tauri::State<'_, State>) -> Result<EnableWifiResult, String> {
    let adb = state.lock().unwrap().adb_path.clone();

    // Step 1: tcpip 5555
    let (rc, stdout, stderr) = adb_run(&adb, &["-s", &device_id, "tcpip", "5555"], 12000);
    if rc != 0 && !stdout.to_lowercase().contains("restarting") {
        let err = if !stderr.trim().is_empty() { stderr.trim().to_string() } else { stdout.trim().to_string() };
        return Ok(EnableWifiResult { success: false, ip_port: None, error: Some(err) });
    }

    // Step 2: get IP from wlan interfaces
    let mut device_ip: Option<String> = None;
    for iface in &["wlan0", "wlan1", "swlan0"] {
        let (_, ip_raw, _) = adb_run(
            &adb,
            &["-s", &device_id, "shell", "ip", "-f", "inet", "addr", "show", iface],
            8000,
        );
        for line in ip_raw.lines() {
            let line = line.trim();
            if line.starts_with("inet ") && !line.split_whitespace().nth(1).unwrap_or("").starts_with("127") {
                if let Some(ip) = line.split_whitespace().nth(1) {
                    device_ip = Some(ip.split('/').next().unwrap_or("").to_string());
                    break;
                }
            }
        }
        if device_ip.is_some() { break; }
    }

    match device_ip {
        Some(ip) => Ok(EnableWifiResult {
            success: true,
            ip_port: Some(format!("{}:5555", ip)),
            error: None,
        }),
        None => Ok(EnableWifiResult {
            success: false,
            ip_port: None,
            error: Some("IP tidak ditemukan — pastikan HP terhubung WiFi".to_string()),
        }),
    }
}

#[tauri::command]
async fn disable_wifi_adb(ip_port: String, state: tauri::State<'_, State>) -> Result<bool, String> {
    let adb = state.lock().unwrap().adb_path.clone();
    adb_run(&adb, &["disconnect", &ip_port], 8000);
    adb_run(&adb, &["usb"], 12000);
    Ok(true)
}

#[tauri::command]
async fn toggle_wifi_debug(device_id: String, state: tauri::State<'_, State>) -> Result<WifiAdbStatus, String> {
    let adb = state.lock().unwrap().adb_path.clone();
    let (_, stdout, _) = adb_run(
        &adb,
        &["-s", &device_id, "shell", "settings", "get", "global", "adb_wifi_enabled"],
        8000,
    );
    let current = stdout.trim().to_string();

    match current.as_str() {
        "1" => {
            adb_run(&adb, &["-s", &device_id, "shell", "settings", "put", "global", "adb_wifi_enabled", "0"], 8000);
            Ok(WifiAdbStatus { status: "off".to_string() })
        }
        "0" => {
            adb_run(&adb, &["-s", &device_id, "shell", "settings", "put", "global", "adb_wifi_enabled", "1"], 8000);
            Ok(WifiAdbStatus { status: "on".to_string() })
        }
        _ => Ok(WifiAdbStatus { status: "unknown".to_string() }),
    }
}

#[derive(Serialize)]
pub struct ScanResult {
    devices: HashMap<String, String>,
}

#[tauri::command]
async fn scan_wifi_devices(state: tauri::State<'_, State>) -> Result<ScanResult, String> {
    let adb = state.lock().unwrap().adb_path.clone();
    let mut found: Vec<String> = vec![];

    // Method 1: mDNS (Android 11+) — jalankan di blocking thread agar tidak blokir async executor
    let adb_clone = adb.clone();
    let mdns_out = tokio::task::spawn_blocking(move || adb_run(&adb_clone, &["mdns", "services"], 6000))
        .await.unwrap_or((-1, String::new(), String::new())).1;
    for line in mdns_out.lines() {
        let parts: Vec<&str> = line.trim().split_whitespace().collect();
        if let Some(last) = parts.last() {
            if last.contains(':') && line.to_lowercase().contains("adb") && !found.contains(&last.to_string()) {
                found.push(last.to_string());
            }
        }
    }

    // Method 2: existing TCP devices
    let adb_clone = adb.clone();
    let dev_out = tokio::task::spawn_blocking(move || adb_run(&adb_clone, &["devices"], 8000))
        .await.unwrap_or((-1, String::new(), String::new())).1;
    for line in dev_out.lines().skip(1) {
        if line.contains("\tdevice") && line.split('\t').next().unwrap_or("").contains(':') {
            let ip_port = line.split('\t').next().unwrap_or("").trim().to_string();
            if !found.contains(&ip_port) {
                found.push(ip_port);
            }
        }
    }

    // Method 3: Port scan /24 subnet (parallelized)

    let local_ip = local_ip_address();
    if let Some(local) = &local_ip {
        let parts: Vec<&str> = local.split('.').collect();
        if parts.len() == 4 {
            let prefix = format!("{}.{}.{}.", parts[0], parts[1], parts[2]);
            let found_arc = Arc::new(Mutex::new(found.clone()));
            let mut handles = vec![];

            for i in 1u8..=254 {
                let host = format!("{}{}", prefix, i);
                if host == *local { continue; }
                let found_clone = found_arc.clone();
                // BUG FIX: gunakan if let agar tidak panic jika parse gagal
                handles.push(thread::spawn(move || {
                    if let Ok(addr) = format!("{}:5555", host).parse::<SocketAddr>() {
                        if TcpStream::connect_timeout(&addr, Duration::from_millis(450)).is_ok() {
                            let entry = format!("{}:5555", host);
                            let mut f = found_clone.lock().unwrap();
                            if !f.contains(&entry) {
                                f.push(entry);
                            }
                        }
                    }
                }));
            }

            // BUG FIX: join semua thread agar hasil scan benar-benar ditunggu
            for handle in handles {
                let _ = handle.join();
            }
            found = found_arc.lock().unwrap().clone();
        }
    }

    // Get device names without auto-connecting — jalankan di blocking thread
    let mut devices: HashMap<String, String> = HashMap::new();
    for ip_port in &found {
        let adb_c = adb.clone();
        let ip_c = ip_port.clone();
        let name = tokio::task::spawn_blocking(move || get_device_name_no_connect(&adb_c, &ip_c))
            .await.unwrap_or_else(|_| "Perangkat Android".to_string());
        devices.insert(ip_port.clone(), name);
    }

    Ok(ScanResult { devices })
}

fn get_device_name_no_connect(adb: &PathBuf, ip_port: &str) -> String {
    let (rc, model_out, _) = adb_run(adb, &["-s", ip_port, "shell", "getprop", "ro.product.model"], 3000);
    if rc != 0 { return "Perangkat Android".to_string(); }
    let model = model_out.trim().to_string();
    let (_, brand_out, _) = adb_run(adb, &["-s", ip_port, "shell", "getprop", "ro.product.brand"], 3000);
    let brand = brand_out.trim().to_string();
    if model.is_empty() { return "Perangkat Android".to_string(); }
    if brand.is_empty() { model } else { format!("{} {}", brand, model) }
}

fn local_ip_address() -> Option<String> {
    use std::net::UdpSocket;
    let socket = UdpSocket::bind("0.0.0.0:0").ok()?;
    socket.connect("8.8.8.8:80").ok()?;
    let addr = socket.local_addr().ok()?;
    Some(addr.ip().to_string())
}

#[tauri::command]
async fn get_installed_apps(device_id: String, state: tauri::State<'_, State>) -> Result<Vec<String>, String> {
    let adb = state.lock().unwrap().adb_path.clone();
    let (_, stdout, _) = adb_run(
        &adb,
        &["-s", &device_id, "shell", "pm", "list", "packages", "-3"],
        15000,
    );
    let mut packages: Vec<String> = stdout
        .lines()
        .filter(|l| l.starts_with("package:"))
        .map(|l| l.replace("package:", "").trim().to_string())
        .collect();
    packages.sort();
    Ok(packages)
}

// ─── Profiles ────────────────────────────────────────────────

fn profiles_path() -> PathBuf {
    // BUG FIX: cari folder scrcpy (tempat adb.exe) agar profil disimpan di tempat yang konsisten
    let exe_dir = std::env::current_exe()
        .unwrap_or_default()
        .parent()
        .unwrap_or(&PathBuf::from("."))
        .to_path_buf();
    let mut dir = exe_dir.clone();
    for _ in 0..4 {
        if dir.join("adb.exe").exists() { break; }
        if let Some(p) = dir.parent() { dir = p.to_path_buf(); } else { break; }
    }
    dir.join("scrcpy_profiles.json")
}

#[tauri::command]
async fn load_profiles() -> Result<serde_json::Value, String> {
    let path = profiles_path();
    if path.exists() {
        let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
        let v: serde_json::Value = serde_json::from_str(&content).unwrap_or(serde_json::json!({}));
        Ok(v)
    } else {
        Ok(serde_json::json!({}))
    }
}

#[tauri::command]
async fn save_profiles(profiles: serde_json::Value) -> Result<bool, String> {
    let path = profiles_path();
    let content = serde_json::to_string_pretty(&profiles).map_err(|e| e.to_string())?;
    std::fs::write(&path, content).map_err(|e| e.to_string())?;
    Ok(true)
}

// ─── Build Command & Launch ───────────────────────────────────

#[derive(Deserialize)]
pub struct LaunchConfig {
    device: Option<String>,
    res: String,
    fps: String,
    bitrate: String,
    codec: String,
    audio_buffer: String,
    stay_awake: bool,
    turn_off: bool,
    on_top: bool,
    no_audio: bool,
    fullscreen: bool,
    show_touches: bool,
    borderless: bool,
    no_control: bool,
    otg: bool,
    uhid: bool,
    copy_paste: bool,
    volume_keys: bool,
    new_display: bool,
    vdisplay_res: String,
    vd_mouse_mode: String,
    vd_kbd_mode: String,
    start_app: String,
    new_task: bool,
    record: bool,
    record_path: String,
    video_source: String,
    camera_facing: String,
    audio_source: String,
    rotation: String,
    display_id: String,
    print_fps: bool,
    extra_args: String,
}

fn build_command(config: &LaunchConfig, scrcpy: &PathBuf) -> Vec<String> {
    let mut cmd: Vec<String> = vec![scrcpy.to_string_lossy().to_string()];

    // Device
    if let Some(dev) = &config.device {
        if !dev.is_empty() && dev != "Tidak ada perangkat" && dev != "Mendeteksi..." {
            cmd.push("-s".to_string());
            cmd.push(dev.clone());
        }
    }

    // Video
    if config.res != "Bawaan" {
        cmd.push(format!("--max-size={}", config.res));
    }
    cmd.push(format!("--max-fps={}", config.fps));
    cmd.push(format!("--video-bit-rate={}", config.bitrate));
    cmd.push(format!("--video-codec={}", config.codec));
    
    if config.video_source != "Bawaan" {
        cmd.push(format!("--video-source={}", config.video_source));
        if config.video_source == "camera" && config.camera_facing != "Bawaan" {
            cmd.push(format!("--camera-facing={}", config.camera_facing));
        }
    }
    
    if config.rotation != "Bawaan" {
        if config.rotation == "lock" {
            cmd.push("--capture-orientation=@".to_string());
        } else {
            let deg = match config.rotation.as_str() {
                "0" => "0",
                "1" => "270",
                "2" => "180",
                "3" => "90",
                _ => "0",
            };
            cmd.push(format!("--orientation={}", deg));
        }
    }
    
    let disp_id = config.display_id.trim();
    if !disp_id.is_empty() && disp_id != "Bawaan" {
        // BUG FIX: flag yang benar di scrcpy v3 adalah --display-id, bukan --display
        cmd.push(format!("--display-id={}", disp_id));
    }

    // Audio buffer — skip if no-audio
    if config.audio_buffer != "200" && !config.no_audio {
        cmd.push(format!("--audio-output-buffer={}", config.audio_buffer));
    }
    if config.audio_source != "Bawaan" && !config.no_audio {
        cmd.push(format!("--audio-source={}", config.audio_source));
    }

    // Behaviour
    if config.stay_awake   { cmd.push("--stay-awake".to_string()); }
    if config.turn_off     { cmd.push("--turn-screen-off".to_string()); }
    if config.on_top       { cmd.push("--always-on-top".to_string()); }
    if config.no_audio     { cmd.push("--no-audio".to_string()); }
    if config.fullscreen   { cmd.push("--fullscreen".to_string()); }
    if config.show_touches { cmd.push("--show-touches".to_string()); }
    if config.borderless   { cmd.push("--window-borderless".to_string()); }
    if config.no_control   { cmd.push("--no-control".to_string()); }

    // Input — OTG and UHID are mutually exclusive
    if config.otg {
        cmd.push("--otg".to_string());
    } else if config.uhid {
        cmd.push("--keyboard=uhid".to_string());
        cmd.push("--mouse=uhid".to_string());
    }
    if !config.copy_paste  { cmd.push("--no-clipboard-autosync".to_string()); }
    if !config.volume_keys { cmd.push("--no-key-inject".to_string()); }

    // Virtual display
    if config.new_display {
        if config.vdisplay_res.is_empty() || config.vdisplay_res == "Bawaan" {
            cmd.push("--new-display".to_string());
        } else {
            cmd.push(format!("--new-display={}", config.vdisplay_res));
        }
        // Override mouse/keyboard for virtual display (only if UHID not active globally)
        if !config.uhid && !config.otg {
            cmd.push(format!("--mouse={}", config.vd_mouse_mode));
            if config.vd_kbd_mode != "sdk" {
                cmd.push(format!("--keyboard={}", config.vd_kbd_mode));
            }
        }
    }

    // Start app
    let app = config.start_app.trim().to_string();
    if !app.is_empty() {
        let task_prefix = if config.new_task { "+" } else { "" };
        let fuzzy_prefix = if !app.contains('.') { "?" } else { "" };
        cmd.push(format!("--start-app={}{}{}", task_prefix, fuzzy_prefix, app));
    }

    // Record
    if config.record {
        let path = if config.record_path.trim().is_empty() { "rekaman.mp4".to_string() } else { config.record_path.trim().to_string() };
        cmd.push("--record".to_string());
        cmd.push(path);
    }
    if config.print_fps {
        cmd.push("--print-fps".to_string());
    }

    // Custom Extra Arguments
    let extra = config.extra_args.trim();
    if !extra.is_empty() {
        for arg in extra.split_whitespace() {
            cmd.push(arg.to_string());
        }
    }

    cmd
}

#[tauri::command]
fn preview_command(config: LaunchConfig, state: tauri::State<'_, State>) -> Result<String, String> {
    let scrcpy = state.lock().unwrap().scrcpy_path.clone();
    let cmd = build_command(&config, &scrcpy);
    Ok(cmd.join(" "))
}

#[tauri::command]
async fn launch_scrcpy(
    config: LaunchConfig,
    app_handle: AppHandle,
    state: tauri::State<'_, State>,
) -> Result<bool, String> {
    {
        let st = state.lock().unwrap();
        if !st.scrcpy_path.exists() {
            return Err(format!("scrcpy.exe tidak ditemukan di: {}", st.scrcpy_dir.display()));
        }
    }

    // Check if already running
    {
        let mut st = state.lock().unwrap();
        if let Some(proc) = &mut st.scrcpy_proc {
            if proc.try_wait().map(|s| s.is_none()).unwrap_or(false) {
                return Err("Scrcpy sudah berjalan!".to_string());
            }
        }
        st.stop_requested = false;
    }

    let scrcpy = state.lock().unwrap().scrcpy_path.clone();
    let scrcpy_dir = state.lock().unwrap().scrcpy_dir.clone();
    let cmd = build_command(&config, &scrcpy);

    let mut command = Command::new(&cmd[0]);
    command.args(&cmd[1..]);
    command.current_dir(&scrcpy_dir);
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    let mut child = command.spawn().map_err(|e| e.to_string())?;

    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    {
        let mut st = state.lock().unwrap();
        st.scrcpy_proc = Some(child);
    }

    let _ = app_handle.emit("scrcpy-status", "running");

    // FPS Monitor Thread
    if let Some(stdout) = stdout {
        let handle_clone = app_handle.clone();
        std::thread::spawn(move || {
            use std::io::{BufRead, BufReader};
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                if let Ok(l) = line {
                    if l.contains(" fps") {
                        if let Some(fps_idx) = l.find(" fps") {
                            let prefix = &l[..fps_idx];
                            if let Some(last_space) = prefix.rfind(' ') {
                                let fps_val = &prefix[last_space + 1..];
                                let _ = handle_clone.emit("scrcpy-fps", fps_val.to_string());
                            } else {
                                let _ = handle_clone.emit("scrcpy-fps", prefix.to_string());
                            }
                        }
                    }
                }
            }
        });
    }

    // Stderr Monitor Thread (for errors)
    let err_handle_clone = app_handle.clone();
    std::thread::spawn(move || {
        if let Some(stderr) = stderr {
            use std::io::{BufRead, BufReader};
            let reader = BufReader::new(stderr);
            for line in reader.lines() {
                if let Ok(l) = line {
                    let trim = l.trim();
                    if !trim.is_empty() && !trim.contains("file pushed") && !trim.contains("Killing the server") {
                        let _ = err_handle_clone.emit("scrcpy-stderr", trim.to_string());
                    }
                }
            }
        }
    });

    // Hardware Stats Poller Thread
    let state_clone2 = state.inner().clone();
    let handle_clone2 = app_handle.clone();
    let adb_clone2 = state.lock().unwrap().adb_path.clone();
    let dev_clone2 = config.device.clone().unwrap_or_default();
    
    std::thread::spawn(move || {
        loop {
            // Check if still running
            {
                let st = state_clone2.lock().unwrap();
                if st.scrcpy_proc.is_none() { break; }
            }

            // Get Temperature & Battery
            let mut temp = "N/A".to_string();
            let mut bat = "N/A".to_string();
            let mut cmd = std::process::Command::new(&adb_clone2);
            
            let mut args = Vec::new();
            if !dev_clone2.is_empty() && dev_clone2 != "Tidak ada perangkat" && dev_clone2 != "Mendeteksi..." {
                args.push("-s");
                args.push(&dev_clone2);
            }
            args.extend(["shell", "dumpsys", "battery"]);
            cmd.args(&args);

            #[cfg(target_os = "windows")]
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(0x08000000);
            }
            if let Ok(out) = cmd.output() {
                let s = String::from_utf8_lossy(&out.stdout);
                for line in s.lines() {
                    let l = line.trim();
                    if l.starts_with("temperature:") {
                        if let Ok(t) = l.replace("temperature:", "").trim().parse::<f32>() {
                            temp = format!("{:.1}°C", t / 10.0);
                        }
                    } else if l.starts_with("level:") {
                        bat = format!("{}%", l.replace("level:", "").trim());
                    }
                }
            }

            // Get CPU Usage
            let mut cpu = "N/A".to_string();
            let mut cmd2 = std::process::Command::new(&adb_clone2);
            
            let mut args2 = Vec::new();
            if !dev_clone2.is_empty() && dev_clone2 != "Tidak ada perangkat" && dev_clone2 != "Mendeteksi..." {
                args2.push("-s");
                args2.push(&dev_clone2);
            }
            args2.extend(["shell", "top", "-n", "1", "-m", "1"]);
            cmd2.args(&args2);

            #[cfg(target_os = "windows")]
            {
                use std::os::windows::process::CommandExt;
                cmd2.creation_flags(0x08000000);
            }
            if let Ok(out) = cmd2.output() {
                let s = String::from_utf8_lossy(&out.stdout);
                for line in s.lines() {
                    if line.contains("%cpu") && line.contains("idle") {
                        let parts: Vec<&str> = line.split_whitespace().collect();
                        let mut total_cores = 100.0;
                        let mut idle = 0.0;
                        
                        for p in parts {
                            if p.ends_with("%cpu") {
                                total_cores = p.replace("%cpu", "").parse::<f32>().unwrap_or(100.0);
                            } else if p.ends_with("%idle") {
                                idle = p.replace("%idle", "").parse::<f32>().unwrap_or(0.0);
                            }
                        }
                        
                        if total_cores > 0.0 {
                            let used = total_cores - idle;
                            let pct = (used / total_cores) * 100.0;
                            cpu = format!("{:.0}%", pct.max(0.0).min(100.0));
                        }
                        break;
                    }
                }
            }

            let _ = handle_clone2.emit("scrcpy-hw-stats", serde_json::json!({
                "temp": temp,
                "cpu": cpu,
                "bat": bat
            }));

            // Sleep 3 seconds
            std::thread::sleep(Duration::from_secs(3));
        }
    });

    // Monitor in background
    let state_clone = state.inner().clone();
    let handle_clone = app_handle.clone();
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(Duration::from_millis(200));
            let mut st = state_clone.lock().unwrap();
            if let Some(proc) = &mut st.scrcpy_proc {
                match proc.try_wait() {
                    Ok(Some(status)) => {
                        let rc = status.code().unwrap_or(-1);
                        let stop_req = st.stop_requested;
                        st.scrcpy_proc = None;
                        st.stop_requested = false;
                        drop(st);

                        if rc != 0 && !stop_req {
                            let _ = handle_clone.emit("scrcpy-status", format!("error:{}", rc));
                        } else {
                            let _ = handle_clone.emit("scrcpy-status", "stopped");
                        }
                        break;
                    }
                    Ok(None) => { drop(st); }
                    Err(_) => {
                        st.scrcpy_proc = None;
                        drop(st);
                        let _ = handle_clone.emit("scrcpy-status", "stopped");
                        break;
                    }
                }
            } else {
                drop(st);
                break;
            }
        }
    });

    Ok(true)
}

#[tauri::command]
async fn stop_scrcpy(state: tauri::State<'_, State>) -> Result<bool, String> {
    let mut st = state.lock().unwrap();
    st.stop_requested = true;
    if let Some(proc) = &mut st.scrcpy_proc {
        let _ = proc.kill();
    }
    Ok(true)
}

#[tauri::command]
async fn is_scrcpy_running(state: tauri::State<'_, State>) -> Result<bool, String> {
    // BUG FIX: pisahkan lock dari try_wait agar tidak menahan mutex terlalu lama
    let mut st = state.lock().unwrap();
    let running = st.scrcpy_proc
        .as_mut()
        .map(|p| p.try_wait().map(|s| s.is_none()).unwrap_or(false))
        .unwrap_or(false);
    Ok(running)
}

// ─── Entry ───────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let state: State = Arc::new(Mutex::new(AppState::new()));

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            get_devices,
            check_wifi_adb_status,
            connect_wifi,
            enable_wifi_adb,
            disable_wifi_adb,
            toggle_wifi_debug,
            scan_wifi_devices,
            get_installed_apps,
            load_profiles,
            save_profiles,
            preview_command,
            launch_scrcpy,
            stop_scrcpy,
            is_scrcpy_running,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
