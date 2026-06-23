import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { LaunchConfig, DEFAULT_CONFIG, PRESETS } from "./types";
import "./App.css";

function App() {
  const [config, setConfig] = useState<LaunchConfig>(DEFAULT_CONFIG);
  const [activeTab, setActiveTab] = useState("device");
  const [status, setStatus] = useState({ msg: "Siap.", color: "var(--text-secondary)" });
  const [simpleMode, setSimpleMode] = useState(true);

  // Device states
  const [devices, setDevices] = useState<string[]>([]);
  const [deviceMap, setDeviceMap] = useState<Record<string, string>>({});
  const [scanning, setScanning] = useState(false);
  const [wifiAdbStatus, setWifiAdbStatus] = useState("unknown");
  const [installedApps, setInstalledApps] = useState<string[]>([]);
  const [wifiIp, setWifiIp] = useState("");

  // Scrcpy states
  const [isRunning, setIsRunning] = useState(false);
  const [cmdPreview, setCmdPreview] = useState("");
  const [profiles, setProfiles] = useState<Record<string, LaunchConfig>>({});
  const [selectedProfile, setSelectedProfile] = useState("");
  const [newProfileName, setNewProfileName] = useState("");

  const [fps, setFps] = useState<string | null>(null);

  const [hwStats, setHwStats] = useState<{temp: string, cpu: string, bat: string} | null>(null);
  const [detailedError, setDetailedError] = useState<string | null>(null);

  const updateConfig = (updates: Partial<LaunchConfig>) => {
    setConfig(c => ({ ...c, ...updates }));
  };

  useEffect(() => {
    refreshDevices();
    loadProfiles();
    checkIsRunning();

    const unlistenStatus = listen<string>("scrcpy-status", (event) => {
      if (event.payload === "running") {
        setIsRunning(true);
        setFps(null);
        setHwStats(null);
        setDetailedError(null);
        setStatus({ msg: "Scrcpy sedang berjalan...", color: "var(--orange)" });
      } else if (event.payload === "stopped") {
        setIsRunning(false);
        setFps(null);
        setHwStats(null);
        setStatus({ msg: "Sesi Scrcpy selesai.", color: "var(--text-secondary)" });
      } else if (event.payload.startsWith("error:")) {
        setIsRunning(false);
        setFps(null);
        setHwStats(null);
        const code = event.payload.split(":").slice(1).join(":");
        setStatus({ msg: `Scrcpy error: ${code}`, color: "var(--red)" });
      }
    });

    const unlistenFps = listen<string>("scrcpy-fps", (event) => {
      setFps(event.payload.trim());
    });

    const unlistenHw = listen<{temp: string, cpu: string, bat: string}>("scrcpy-hw-stats", (event) => {
      setHwStats(event.payload);
    });

    const unlistenStderr = listen<string>("scrcpy-stderr", (event) => {
      setDetailedError(prev => {
        if (!prev) return event.payload;
        const lines = prev.split("\n");
        if (lines.length >= 5) {
          lines.shift();
        }
        lines.push(event.payload);
        return lines.join("\n");
      });
    });

    return () => {
      unlistenStatus.then(f => f());
      unlistenFps.then(f => f());
      unlistenHw.then(f => f());
      unlistenStderr.then(f => f());
    };
  }, []);

  useEffect(() => {
    if (config.device && config.device !== "Mendeteksi..." && config.device !== "Tidak ada perangkat") {
      invoke<{status: string}>("check_wifi_adb_status", { deviceId: config.device })
        .then(res => setWifiAdbStatus(res.status))
        .catch(() => setWifiAdbStatus("unknown"));
    }
  }, [config.device]);

  useEffect(() => {
    invoke<string>("preview_command", { config })
      .then(cmd => setCmdPreview(cmd))
      .catch(console.error);
  }, [config]);

  const loadProfiles = async () => {
    try {
      const p = await invoke<Record<string, LaunchConfig>>("load_profiles");
      setProfiles(p);
      const keys = Object.keys(p);
      if (keys.length > 0) setSelectedProfile(keys[0]);
    } catch (e) { console.error(e); }
  };

  const saveProfile = async () => {
    if (!newProfileName) return;
    const p = { ...profiles, [newProfileName]: config };
    try {
      await invoke("save_profiles", { profiles: p });
      setProfiles(p);
      setSelectedProfile(newProfileName);
      setNewProfileName("");
      setStatus({ msg: `Profil ${newProfileName} disimpan.`, color: "var(--green)" });
    } catch (e) { console.error(e); }
  };

  const loadSelectedProfile = () => {
    if (profiles[selectedProfile]) {
      setConfig(profiles[selectedProfile]);
      setStatus({ msg: `Profil ${selectedProfile} dimuat.`, color: "var(--green)" });
    }
  };

  const deleteProfile = async () => {
    if (!selectedProfile || !profiles[selectedProfile]) return;
    const p = { ...profiles };
    delete p[selectedProfile];
    try {
      await invoke("save_profiles", { profiles: p });
      setProfiles(p);
      const keys = Object.keys(p);
      setSelectedProfile(keys.length > 0 ? keys[0] : "");
      setStatus({ msg: `Profil dihapus.`, color: "var(--text-secondary)" });
    } catch (e) { console.error(e); }
  };

  const checkIsRunning = async () => {
    try {
      const running = await invoke<boolean>("is_scrcpy_running");
      setIsRunning(running);
    } catch (e) { console.error(e); }
  };

  const refreshDevices = async () => {
    setStatus({ msg: "Mendeteksi perangkat...", color: "var(--text-secondary)" });
    try {
      const res = await invoke<{devices: string[], error: string | null}>("get_devices");
      if (res.error) {
        setStatus({ msg: res.error, color: "var(--red)" });
      } else {
        const devs = res.devices.length > 0 ? res.devices : ["Tidak ada perangkat"];
        setDevices(devs);
        if (!devs.includes(config.device)) updateConfig({ device: devs[0] });
        setStatus({
          msg: devs[0] === "Tidak ada perangkat" ? "Tidak ada perangkat terhubung." : `Ditemukan ${devs.length} perangkat.`,
          color: devs[0] === "Tidak ada perangkat" ? "var(--orange)" : "var(--green)"
        });
      }
    } catch (e) {
      setStatus({ msg: `Error: ${e}`, color: "var(--red)" });
    }
  };

  const scanWifi = async () => {
    setScanning(true);
    setStatus({ msg: "Sedang scan jaringan...", color: "var(--orange)" });
    try {
      const res = await invoke<{devices: Record<string, string>}>("scan_wifi_devices");
      setDeviceMap(res.devices);
      const count = Object.keys(res.devices).length;
      setStatus({
        msg: count > 0 ? `Ditemukan ${count} perangkat di jaringan.` : "Tidak ada perangkat WiFi ditemukan.",
        color: count > 0 ? "var(--green)" : "var(--red)"
      });
    } catch (e) {
      setStatus({ msg: `Error scan: ${e}`, color: "var(--red)" });
    } finally {
      setScanning(false);
    }
  };

  const connectWifi = async (ip: string = wifiIp) => {
    if (!ip) return;
    setStatus({ msg: `Menyambung ke ${ip}...`, color: "var(--orange)" });
    try {
      const res = await invoke<{success: boolean, message: string}>("connect_wifi", { ipPort: ip });
      setStatus({ msg: res.message, color: res.success ? "var(--green)" : "var(--red)" });
      refreshDevices();
    } catch (e) {
      setStatus({ msg: `Gagal: ${e}`, color: "var(--red)" });
    }
  };

  const enableWifiAdb = async () => {
    if (!config.device || config.device.includes(":")) return;
    setStatus({ msg: "Mengaktifkan ADB WiFi...", color: "var(--orange)" });
    try {
      const res = await invoke<{success: boolean, ip_port: string | null, error: string | null}>("enable_wifi_adb", { deviceId: config.device });
      if (res.success && res.ip_port) {
        setWifiIp(res.ip_port);
        updateConfig({ device: res.ip_port });
        setStatus({ msg: `ADB WiFi aktif: ${res.ip_port}`, color: "var(--green)" });
        refreshDevices();
      } else {
        setStatus({ msg: res.error || "Gagal", color: "var(--red)" });
      }
    } catch (e) {
      setStatus({ msg: `Error: ${e}`, color: "var(--red)" });
    }
  };

  const toggleDebug = async () => {
    if (!config.device || config.device === "Tidak ada perangkat") return;
    try {
      const res = await invoke<{status: string}>("toggle_wifi_debug", { deviceId: config.device });
      setWifiAdbStatus(res.status);
      setStatus({ msg: `WiFi ADB: ${res.status}`, color: res.status === "on" ? "var(--green)" : "var(--text-secondary)" });
    } catch (e) { console.error(e); }
  };

  const fetchApps = async () => {
    if (!config.device || config.device === "Tidak ada perangkat") return;
    setStatus({ msg: "Mengambil daftar aplikasi...", color: "var(--orange)" });
    try {
      const apps = await invoke<string[]>("get_installed_apps", { deviceId: config.device });
      setInstalledApps(apps);
      setStatus({ msg: `Ditemukan ${apps.length} aplikasi.`, color: "var(--green)" });
    } catch (e) {
      setStatus({ msg: `Gagal ambil app: ${e}`, color: "var(--red)" });
    }
  };

  const launchScrcpy = async () => {
    if (isRunning) return;
    setDetailedError(null);
    try {
      await invoke("launch_scrcpy", { config });
    } catch (e) {
      setStatus({ msg: `Launch error: ${e}`, color: "var(--red)" });
      setDetailedError(String(e));
    }
  };

  const stopScrcpy = async () => {
    try {
      await invoke("stop_scrcpy");
    } catch (e) { console.error(e); }
  };

  const copyCommand = () => {
    navigator.clipboard.writeText(cmdPreview);
    setStatus({ msg: "Perintah disalin!", color: "var(--green)" });
  };

  const applyPreset = (preset: string) => {
    if (PRESETS[preset]) updateConfig(PRESETS[preset]);
  };

  return (
    <div className="app-shell">

      {/* ── Header ─────────────────────────────────────────── */}
      <div className="header">
        <div className="header-logo">
          <span className="logo-icon">⚡</span>
          <h1>Scrcpy Pro Launcher</h1>
          <span className="version">v5.0</span>
        </div>
        <div className="mode-toggle" onClick={() => setSimpleMode(v => !v)} title={simpleMode ? "Beralih ke Mode Pro" : "Beralih ke Mode Pemula"}>
          <span className={`mode-option ${simpleMode ? "mode-active" : ""}`}>👤 Pemula</span>
          <span className="mode-divider">|</span>
          <span className={`mode-option ${!simpleMode ? "mode-active" : ""}`}>⚡ Pro</span>
        </div>
        <div className="header-status" style={{ color: status.color, display: 'flex', alignItems: 'center', gap: '8px' }}>
          {status.msg}
          {isRunning && fps && (
            <span style={{
              background: 'var(--accent)', color: '#000', padding: '2px 8px',
              borderRadius: '12px', fontSize: '11px', fontWeight: 700,
              boxShadow: '0 0 10px rgba(34,197,94,0.3)'
            }}>
              FPS: {fps}
            </span>
          )}
          {isRunning && hwStats && (
            <div style={{ display: 'flex', gap: '6px' }}>
              <span style={{ background: 'var(--bg-3)', color: 'var(--text-1)', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', border: '1px solid var(--border)' }}>
                🌡️ {hwStats.temp}
              </span>
              <span style={{ background: 'var(--bg-3)', color: 'var(--text-1)', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', border: '1px solid var(--border)' }}>
                ⚡ {hwStats.cpu}
              </span>
              <span style={{ background: 'var(--bg-3)', color: 'var(--text-1)', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', border: '1px solid var(--border)' }}>
                🔋 {hwStats.bat}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ── SIMPLE MODE ────────────────────────────────────── */}
      {simpleMode && (
        <div className="simple-body">

          {/* Step 1 */}
          <div className="simple-step">
            <div className="simple-step-header">
              <span className="simple-step-num">1</span>
              <div>
                <div className="simple-step-title">Sambungkan Perangkat</div>
                <div className="simple-step-desc">Hubungkan HP ke PC via kabel USB atau WiFi</div>
              </div>
            </div>
            <div className="simple-step-body">
              <div className="form-row">
                <span className="form-label">Pilih HP:</span>
                <select value={config.device} onChange={e => updateConfig({ device: e.target.value })}>
                  {devices.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
                <button className="btn btn-ghost btn-icon" onClick={refreshDevices} title="Refresh perangkat">🔄</button>
              </div>
              {(devices.length === 0 || devices[0] === "Tidak ada perangkat") && (
                <div className="simple-hint">
                  <span>💡</span>
                  <span>Pastikan USB Debugging aktif: <strong>Pengaturan → Tentang Ponsel → ketuk Nomor Bangun 7x → Opsi Pengembang → USB Debugging</strong></span>
                </div>
              )}
              <div className="form-row" style={{ marginTop: 8 }}>
                <span className="form-label">Atau sambung WiFi:</span>
                <input type="text" placeholder="192.168.x.x:5555" value={wifiIp} onChange={e => setWifiIp(e.target.value)} />
                <button className="btn btn-primary" onClick={() => connectWifi()}>🔗 Sambung</button>
              </div>
            </div>
          </div>

          {/* Step 2 */}
          <div className="simple-step">
            <div className="simple-step-header">
              <span className="simple-step-num">2</span>
              <div>
                <div className="simple-step-title">Pilih Kualitas Tampilan</div>
                <div className="simple-step-desc">Kualitas lebih tinggi butuh koneksi dan PC yang lebih kuat</div>
              </div>
            </div>
            <div className="simple-step-body">
              <div className="quality-grid">
                {([
                  { key: "Rendah", icon: "🔋", desc: "Hemat baterai & CPU",      sub: "800p · 30fps · 2Mbps"            },
                  { key: "Sedang", icon: "⚖️",  desc: "Seimbang (Rekomendasi)",  sub: "1280p · 60fps · 8Mbps"           },
                  { key: "Tinggi", icon: "🚀", desc: "Lancar & tajam",            sub: "1920p · 120fps · 24Mbps"         },
                  { key: "2K",     icon: "💎", desc: "Kualitas maksimal",         sub: "2560p · 120fps · 32Mbps · H265"  },
                ] as const).map(q => (
                  <div
                    key={q.key}
                    className={`quality-card ${config.res === PRESETS[q.key]?.res ? "quality-active" : ""}`}
                    onClick={() => applyPreset(q.key)}
                  >
                    <span className="quality-icon">{q.icon}</span>
                    <div className="quality-name">{q.key}</div>
                    <div className="quality-desc">{q.desc}</div>
                    <div className="quality-sub">{q.sub}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Step 3 */}
          <div className="simple-step">
            <div className="simple-step-header">
              <span className="simple-step-num">3</span>
              <div>
                <div className="simple-step-title">Opsi Tambahan (Opsional)</div>
                <div className="simple-step-desc">Kustomisasi sesuai kebutuhan Anda</div>
              </div>
            </div>
            <div className="simple-step-body">
              <div className="simple-options-grid">
                {[
                  { key: "stay_awake", icon: "☀️", title: "HP Tetap Menyala",   desc: "Layar HP tidak akan mati saat streaming" },
                  { key: "turn_off",   icon: "🌙", title: "Matikan Layar HP",    desc: "Hemat baterai, kontrol tetap bisa dari PC" },
                  { key: "fullscreen", icon: "🖥️", title: "Tampilan Layar Penuh",desc: "Buka scrcpy langsung fullscreen" },
                  { key: "no_audio",   icon: "🔇", title: "Tanpa Suara",         desc: "Tidak meneruskan audio dari HP ke PC" },
                ].map(item => (
                  <label className="simple-toggle" key={item.key}>
                    <input
                      type="checkbox"
                      checked={config[item.key as keyof LaunchConfig] as boolean}
                      onChange={e => updateConfig({ [item.key]: e.target.checked })}
                    />
                    <div className="simple-toggle-content">
                      <span className="simple-toggle-icon">{item.icon}</span>
                      <div>
                        <div className="simple-toggle-title">{item.title}</div>
                        <div className="simple-toggle-desc">{item.desc}</div>
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          </div>

          {/* Step 4 */}
          <div className="simple-step" style={{ borderColor: config.new_display ? "var(--accent)" : "var(--border)" }}>
            <div className="simple-step-header">
              <div className="multitask-header-toggle">
                <div style={{ display: "flex", gap: "13px", alignItems: "center" }}>
                  <span className="simple-step-num" style={{ background: config.new_display ? "var(--accent)" : "var(--bg-3)", color: config.new_display ? "#000" : "var(--text-3)", boxShadow: config.new_display ? "0 0 12px rgba(34,197,94,0.3)" : "none" }}>4</span>
                  <div>
                    <div className="simple-step-title" style={{ color: config.new_display ? "var(--accent)" : "var(--text-1)" }}>Mode Layar Virtual (Multitasking)</div>
                    <div className="simple-step-desc">Khusus Android 13+. Buka aplikasi lain tanpa mengganggu layar utama.</div>
                  </div>
                </div>
                <label className="switch" title="Aktifkan Multitasking">
                  <input
                    type="checkbox"
                    checked={config.new_display}
                    onChange={e => updateConfig({ new_display: e.target.checked })}
                  />
                  <span className="slider"></span>
                </label>
              </div>
            </div>
            {config.new_display && (
              <div className="simple-step-body" style={{ background: "var(--accent-dim)", borderTop: "1px solid rgba(34,197,94,0.15)" }}>
                <div className="cmd-bar">
                  <span className="cmd-bar-icon">📲</span>
                  <input 
                    type="text" 
                    list="apps-list-simple" 
                    placeholder="Ketik nama paket aplikasi (contoh: com.whatsapp)" 
                    value={config.start_app} 
                    onChange={e => updateConfig({ start_app: e.target.value })} 
                  />
                  <button className="cmd-bar-btn" onClick={fetchApps} title="Ambil daftar aplikasi dari HP">
                    <span>📋</span> Daftar App
                  </button>
                  <datalist id="apps-list-simple">
                    {installedApps.map(a => <option key={a} value={a} />)}
                  </datalist>
                </div>
                {!config.start_app.trim() && (
                  <div style={{ color: 'var(--amber)', fontSize: '11px', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span>⚠️</span>
                    <span>Wajib memilih atau mengetik nama paket aplikasi untuk menjalankan Layar Virtual.</span>
                  </div>
                )}
              </div>
            )}
          </div>

        </div>
      )}

      {/* ── PRO MODE ───────────────────────────────────────── */}
      {!simpleMode && (
        <div className="body-split">
          {/* Sidebar */}
          <div className="sidebar">
            <div className="sidebar-label">Navigation</div>
            {[
              { id: "device",    icon: "📱", label: "Perangkat" },
              { id: "video",     icon: "🎥", label: "Video" },
              { id: "audio",     icon: "🔊", label: "Audio" },
              { id: "control",   icon: "⌨️", label: "Kontrol" },
              { id: "multitask", icon: "📲", label: "Multi-Task" },
              { id: "record",    icon: "🎬", label: "Rekaman" },
            ].map(t => (
              <div key={t.id} className={`nav-item ${activeTab === t.id ? "active" : ""}`} onClick={() => setActiveTab(t.id)}>
                <span className="nav-icon">{t.icon}</span>
                {t.label}
              </div>
            ))}
            <div className="sidebar-label" style={{ marginTop: 8 }}>Settings</div>
            <div className={`nav-item ${activeTab === "profiles" ? "active" : ""}`} onClick={() => setActiveTab("profiles")}>
              <span className="nav-icon">💾</span>
              Profil
            </div>
          </div>

          {/* Content */}
          <div className="main-content">

            {/* TAB: DEVICE */}
            {activeTab === "device" && (
              <div className="card">
                <div className="card-header"><span className="card-header-gradient">📱 Koneksi Perangkat</span></div>
                <div className="card-body">
                  <div className="form-row">
                    <span className="form-label">Perangkat USB/WiFi:</span>
                    <select value={config.device} onChange={e => updateConfig({ device: e.target.value })}>
                      {devices.map(d => <option key={d} value={d}>{d}</option>)}
                    </select>
                    <div className="flex gap-2">
                      <button className="btn btn-ghost btn-icon" onClick={refreshDevices}>🔄</button>
                      <button className="btn btn-ghost" onClick={fetchApps}>📋 Apps</button>
                    </div>
                  </div>
                  <div className="divider"></div>
                  <div className="form-row">
                    <span className="form-label">Koneksi Manual:</span>
                    <input type="text" placeholder="192.168.1.x:5555" value={wifiIp} onChange={e => setWifiIp(e.target.value)} />
                    <button className="btn btn-primary" onClick={() => connectWifi()}>🔗 Sambung</button>
                  </div>
                  <div className="form-row">
                    <span className="form-label">Scan Jaringan:</span>
                    <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                      {Object.keys(deviceMap).length > 0
                        ? Object.entries(deviceMap).map(([ip, model]) => (
                            <div key={ip} className="device-card mt-1" onClick={() => { setWifiIp(ip); connectWifi(ip); }}>
                              <div><strong>{model}</strong><br /><span style={{ fontSize: 10 }}>{ip}</span></div>
                            </div>
                          ))
                        : "Belum di-scan"
                      }
                    </div>
                    <button className="btn btn-success" onClick={scanWifi} disabled={scanning}>
                      {scanning ? "⏳ Scan..." : "🔍 Scan WiFi"}
                    </button>
                  </div>
                  <div className="divider"></div>
                  <div className="form-row">
                    <span className="form-label">Ubah USB ke WiFi:</span>
                    <span className="text-sm text-muted">Aktifkan ADB WiFi via kabel USB dulu</span>
                    <button className="btn btn-purple" onClick={enableWifiAdb}>🌐 Aktifkan</button>
                  </div>
                  <div className="form-row">
                    <span className="form-label">Wireless Debugging:</span>
                    <span className="text-sm">Status:
                      <span className={`badge ml-2 ${wifiAdbStatus === "on" ? "badge-green" : wifiAdbStatus === "off" ? "badge-red" : "badge-gray"}`}>
                        {wifiAdbStatus.toUpperCase()}
                      </span>
                    </span>
                    <button className="btn btn-ghost" onClick={toggleDebug}>Toggle Mode</button>
                  </div>
                </div>
              </div>
            )}

            {/* TAB: VIDEO */}
            {activeTab === "video" && (
              <div className="card">
                <div className="card-header"><span className="card-header-gradient">🎥 Kualitas &amp; Resolusi</span></div>
                <div className="card-body">
                  <div className="form-row two-col">
                    <span className="form-label">Preset Cepat:</span>
                    <div className="segment-group">
                      {Object.keys(PRESETS).map(p => (
                        <button key={p} className={`segment-btn ${config.res === PRESETS[p]?.res ? "active" : ""}`} onClick={() => applyPreset(p)}>{p}</button>
                      ))}
                    </div>
                  </div>
                  <div className="divider"></div>
                  <div className="form-row two-col">
                    <span className="form-label">Resolusi Maks:</span>
                    <select value={config.res} onChange={e => updateConfig({ res: e.target.value })}>
                      {["Bawaan", "2560", "1920", "1280", "1024", "800", "600"].map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                  <div className="form-row two-col">
                    <span className="form-label">FPS Maks:</span>
                    <select value={config.fps} onChange={e => updateConfig({ fps: e.target.value })}>
                      {["144", "120", "90", "60", "30", "15"].map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                  <div className="form-row two-col">
                    <span className="form-label">Bitrate:</span>
                    <select value={config.bitrate} onChange={e => updateConfig({ bitrate: e.target.value })}>
                      {["32M", "24M", "16M", "8M", "4M", "2M", "1M"].map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                  <div className="form-row two-col">
                    <span className="form-label">Codec Video:</span>
                    <select value={config.codec} onChange={e => updateConfig({ codec: e.target.value })}>
                      {["h264", "h265", "av1"].map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                  <div className="divider"></div>
                  <div className="form-row two-col">
                    <span className="form-label">Sumber Video:</span>
                    <select value={config.video_source} onChange={e => updateConfig({ video_source: e.target.value })}>
                      <option value="Bawaan">Layar HP (Default)</option>
                      <option value="camera">Kamera HP</option>
                    </select>
                  </div>
                  {config.video_source === "camera" && (
                    <div className="form-row two-col">
                      <span className="form-label">Posisi Kamera:</span>
                      <select value={config.camera_facing} onChange={e => updateConfig({ camera_facing: e.target.value })}>
                        <option value="Bawaan">Default</option>
                        <option value="front">Kamera Depan</option>
                        <option value="back">Kamera Belakang</option>
                      </select>
                    </div>
                  )}
                  <div className="divider"></div>
                  <div className="form-row two-col">
                    <span className="form-label">Rotasi Layar:</span>
                    <select value={config.rotation} onChange={e => updateConfig({ rotation: e.target.value })}>
                      <option value="Bawaan">Mengikuti HP</option>
                      <option value="lock">Kunci Orientasi Awal</option>
                      <option value="0">0°</option>
                      <option value="1">90° (Counter-clockwise)</option>
                      <option value="2">180°</option>
                      <option value="3">90° (Clockwise)</option>
                    </select>
                  </div>
                  <div className="form-row two-col mt-2">
                    <span className="form-label">Display ID:</span>
                    <input type="text" placeholder="Kosongkan jika hanya 1 layar" value={config.display_id} onChange={e => updateConfig({ display_id: e.target.value })} />
                  </div>
                </div>
              </div>
            )}

            {/* TAB: AUDIO */}
            {activeTab === "audio" && (
              <div className="card">
                <div className="card-header"><span className="card-header-gradient">🔊 Pengaturan Audio</span></div>
                <div className="card-body">
                  <div className="checkbox-item">
                    <input type="checkbox" checked={config.no_audio} onChange={e => updateConfig({ no_audio: e.target.checked })} />
                    <label>Matikan Suara (No Audio)</label>
                  </div>
                  <div className="form-row two-col mt-2">
                    <span className="form-label">Sumber Audio:</span>
                    <select value={config.audio_source} onChange={e => updateConfig({ audio_source: e.target.value })} disabled={config.no_audio}>
                      <option value="Bawaan">Internal HP (Default)</option>
                      <option value="mic">Mikrofon HP</option>
                    </select>
                  </div>
                  <div className="form-row two-col mt-2">
                    <span className="form-label">Buffer Audio (ms):</span>
                    <select value={config.audio_buffer} onChange={e => updateConfig({ audio_buffer: e.target.value })} disabled={config.no_audio}>
                      {["50", "100", "200", "300", "500"].map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                </div>
              </div>
            )}

            {/* TAB: CONTROL */}
            {activeTab === "control" && (
              <div className="card">
                <div className="card-header"><span className="card-header-gradient">⌨️ Perilaku &amp; Kontrol</span></div>
                <div className="card-body">
                  <div className="checkbox-grid">
                    {[
                      { k: "stay_awake",   l: "HP Tetap Menyala" },
                      { k: "turn_off",     l: "Matikan Layar HP" },
                      { k: "on_top",       l: "Selalu di Atas" },
                      { k: "fullscreen",   l: "Mulai Fullscreen" },
                      { k: "show_touches", l: "Tampilkan Sentuhan" },
                      { k: "borderless",   l: "Tanpa Border Window" },
                      { k: "no_control",   l: "Hanya Lihat (Read-only)" },
                      { k: "uhid",         l: "Mode UHID (Keyboard/Mouse Asli)" },
                      { k: "otg",          l: "Mode OTG" },
                      { k: "copy_paste",   l: "Sinkronisasi Copy-Paste" },
                      { k: "volume_keys",  l: "Tombol Volume PC" },
                    ].map(item => (
                      <div className="checkbox-item" key={item.k}>
                        <input type="checkbox" checked={config[item.k as keyof LaunchConfig] as boolean}
                          onChange={e => {
                            const updates: Partial<LaunchConfig> = { [item.k]: e.target.checked };
                            if (item.k === "otg" && e.target.checked) updates.uhid = false;
                            if (item.k === "uhid" && e.target.checked) updates.otg = false;
                            updateConfig(updates);
                          }} />
                        <label>{item.l}</label>
                      </div>
                    ))}
                  </div>
                  <div className="divider" style={{ margin: '12px 0' }}></div>
                  <div className="form-row two-col">
                    <span className="form-label">Argumen Kustom (Extra Flags):</span>
                    <input 
                      type="text" 
                      placeholder="Contoh: --render-driver=opengl --window-title='HP Saya'" 
                      value={config.extra_args} 
                      onChange={e => updateConfig({ extra_args: e.target.value })} 
                    />
                  </div>
                </div>
              </div>
            )}

            {/* TAB: MULTITASK */}
            {activeTab === "multitask" && (
              <div className="card">
                <div className="card-header"><span className="card-header-gradient">📲 Layar Virtual (Android 13+)</span></div>
                <div className="card-body">
                  <div className="checkbox-item">
                    <input type="checkbox" checked={config.new_display} onChange={e => updateConfig({ new_display: e.target.checked })} />
                    <label>Aktifkan Layar Virtual Baru</label>
                  </div>
                  {config.new_display && (
                    <>
                      <div className="form-row two-col mt-2">
                        <span className="form-label">Resolusi Virtual:</span>
                        <select value={config.vdisplay_res} onChange={e => updateConfig({ vdisplay_res: e.target.value })}>
                          {["Bawaan", "1280x720", "1920x1080", "2560x1440", "720x1280", "1080x1920"].map(v => <option key={v} value={v}>{v}</option>)}
                        </select>
                      </div>
                      <div className="form-row two-col mt-2">
                        <span className="form-label">Buka Aplikasi:</span>
                        <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
                          <input type="text" list="apps-list" placeholder="Contoh: com.android.chrome" value={config.start_app} onChange={e => updateConfig({ start_app: e.target.value })} />
                          {!config.start_app.trim() && (
                            <div style={{ color: 'var(--amber)', fontSize: '10.5px', marginTop: '4px' }}>
                              ⚠️ Wajib diisi untuk Layar Virtual.
                            </div>
                          )}
                        </div>
                        <datalist id="apps-list">
                          {installedApps.map(a => <option key={a} value={a} />)}
                        </datalist>
                      </div>
                      <div className="checkbox-item mt-1">
                        <input type="checkbox" checked={config.new_task} onChange={e => updateConfig({ new_task: e.target.checked })} />
                        <label>Buka di task baru (+)</label>
                      </div>
                      {!config.uhid && !config.otg && (
                        <>
                          <div className="divider"></div>
                          <div className="form-row two-col">
                            <span className="form-label">Mode Mouse:</span>
                            <select value={config.vd_mouse_mode} onChange={e => updateConfig({ vd_mouse_mode: e.target.value })}>
                              <option value="uhid">UHID (Virtual HID)</option>
                              <option value="disabled">Disabled (Mouse di PC)</option>
                              <option value="sdk">SDK (Default)</option>
                            </select>
                          </div>
                          <div className="form-row two-col">
                            <span className="form-label">Mode Keyboard:</span>
                            <select value={config.vd_kbd_mode} onChange={e => updateConfig({ vd_kbd_mode: e.target.value })}>
                              <option value="uhid">UHID</option>
                              <option value="sdk">SDK (Default)</option>
                              <option value="disabled">Disabled</option>
                            </select>
                          </div>
                        </>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}

            {/* TAB: RECORD */}
            {activeTab === "record" && (
              <div className="card">
                <div className="card-header"><span className="card-header-gradient">🎬 Rekam Layar</span></div>
                <div className="card-body">
                  <div className="checkbox-item">
                    <input type="checkbox" checked={config.record} onChange={e => updateConfig({ record: e.target.checked })} />
                    <label>Simpan ke File</label>
                  </div>
                  <div className="form-row two-col mt-2">
                    <span className="form-label">Simpan sebagai:</span>
                    <input type="text" placeholder="rekaman.mp4" value={config.record_path} onChange={e => updateConfig({ record_path: e.target.value })} disabled={!config.record} />
                  </div>
                </div>
              </div>
            )}

            {/* TAB: PROFILES */}
            {activeTab === "profiles" && (
              <div className="card">
                <div className="card-header"><span className="card-header-gradient">💾 Profil Pengaturan</span></div>
                <div className="card-body">
                  <div className="form-row">
                    <span className="form-label">Profil Tersimpan:</span>
                    <select value={selectedProfile} onChange={e => setSelectedProfile(e.target.value)}>
                      {Object.keys(profiles).length === 0
                        ? <option value="">(Belum ada profil)</option>
                        : Object.keys(profiles).map(p => <option key={p} value={p}>{p}</option>)
                      }
                    </select>
                    <div className="flex gap-2">
                      <button className="btn btn-success" onClick={loadSelectedProfile}>Muat</button>
                      <button className="btn btn-danger" onClick={deleteProfile}>Hapus</button>
                    </div>
                  </div>
                  <div className="divider"></div>
                  <div className="form-row">
                    <span className="form-label">Simpan Profil:</span>
                    <input type="text" placeholder="Nama profil baru..." value={newProfileName} onChange={e => setNewProfileName(e.target.value)} />
                    <button className="btn btn-primary" onClick={saveProfile}>Simpan</button>
                  </div>
                </div>
              </div>
            )}

            {/* Command Preview */}
            <div className="card mt-auto">
              <div className="card-header">
                <span className="card-header-gradient">🔍 Command Preview</span>
                <button className="btn btn-ghost btn-icon ml-auto" onClick={copyCommand}>📋 Copy</button>
              </div>
              <div className="cmd-preview">
                {cmdPreview || <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>Konfigurasi belum dibuat...</span>}
              </div>
            </div>

          </div>
        </div>
      )}

      {/* ── Launch Area ─────────────────────────────────────── */}
      <div className="launch-area">
        {!isRunning && (detailedError || status.color === "var(--red)") && (
          <div className="error-alert-card">
            <div className="error-alert-header">
              <span className="error-alert-icon">⚠️</span>
              <strong>Terjadi Kesalahan Scrcpy</strong>
            </div>
            <div className="error-alert-body">
              {detailedError || status.msg}
            </div>
            {((detailedError || status.msg).includes("INJECT_EVENTS") || 
              (detailedError || status.msg).toLowerCase().includes("security settings") || 
              (detailedError || status.msg).toLowerCase().includes("setelan keamanan")) && (
              <div className="error-alert-solution">
                <strong>💡 Cara Mengatasi (Xiaomi/Redmi/Poco):</strong>
                <ol>
                  <li>Buka <strong>Opsi Pengembang</strong> di HP Anda.</li>
                  <li>Aktifkan <strong>"USB debugging (Setelan Keamanan)"</strong> / <strong>"USB debugging (Security Settings)"</strong>.</li>
                  <li>Mulai ulang (reboot) HP Anda, lalu coba sambungkan kembali.</li>
                </ol>
                <div style={{ marginTop: '8px' }}>
                  <em>Atau, Anda bisa menggunakan mode <strong>"Hanya Lihat (Read-only)"</strong> di tab Kontrol jika tidak perlu mengontrol HP dari PC.</em>
                </div>
              </div>
            )}
          </div>
        )}

        <button
          className={`launch-btn ${isRunning ? "running" : ""}`}
          onClick={launchScrcpy}
          disabled={isRunning || (config.new_display && !config.start_app.trim())}
        >
          {isRunning ? "⏳  SCRCPY SEDANG BERJALAN..." : "🚀  JALANKAN SCRCPY"}
        </button>
        {isRunning && <button className="stop-btn" onClick={stopScrcpy}>⏹  HENTIKAN SESI</button>}
      </div>

    </div>
  );
}

export default App;
