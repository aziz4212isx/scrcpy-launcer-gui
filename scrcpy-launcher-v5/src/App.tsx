import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { LaunchConfig, DEFAULT_CONFIG, PRESETS } from "./types";
import "./App.css";

function App() {
  const [config, setConfig] = useState<LaunchConfig>(DEFAULT_CONFIG);
  const [activeTab, setActiveTab] = useState("perangkat");
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
    setStatus({ msg: "Mendeteksi perangkat...", color: "var(--orange)" });
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
    if (!config.device || config.device.includes(":") || config.device === "Tidak ada perangkat") {
      setStatus({ msg: "Pilih perangkat USB terlebih dahulu", color: "var(--red)" });
      return;
    }
    setStatus({ msg: "Mengaktifkan ADB WiFi...", color: "var(--orange)" });
    try {
      const res = await invoke<{success: boolean, ip_port: string | null, error: string | null}>("enable_wifi_adb", { deviceId: config.device });
      if (res.success && res.ip_port) {
        setWifiIp(res.ip_port);
        updateConfig({ device: res.ip_port });
        setStatus({ msg: `ADB WiFi aktif: ${res.ip_port}`, color: "var(--green)" });
        refreshDevices();
      } else {
        setStatus({ msg: res.error || "Gagal mengaktifkan ADB WiFi", color: "var(--red)" });
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
      setStatus({ msg: `WiFi ADB: ${res.status.toUpperCase()}`, color: res.status === "on" ? "var(--green)" : "var(--text-secondary)" });
    } catch (e) { console.error(e); }
  };

  const fetchApps = async () => {
    if (!config.device || config.device === "Tidak ada perangkat") {
      setStatus({ msg: "Hubungkan perangkat terlebih dahulu", color: "var(--red)" });
      return;
    }
    setStatus({ msg: "Mengambil daftar aplikasi...", color: "var(--orange)" });
    try {
      const apps = await invoke<string[]>("get_installed_apps", { deviceId: config.device });
      setInstalledApps(apps);
      setStatus({ msg: `Ditemukan ${apps.length} aplikasi pihak ketiga.`, color: "var(--green)" });
    } catch (e) {
      setStatus({ msg: `Gagal mengambil daftar aplikasi: ${e}`, color: "var(--red)" });
    }
  };

  const launchScrcpy = async () => {
    if (isRunning) return;
    setDetailedError(null);
    try {
      await invoke("launch_scrcpy", { config });
    } catch (e) {
      setStatus({ msg: `Gagal menjalankan Scrcpy: ${e}`, color: "var(--red)" });
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

  // Convert functional colors to Tailwind classes
  const getStatusClasses = () => {
    if (status.color === "var(--green)" || status.color === "var(--accent)") {
      return { dot: "bg-emerald-400 animate-pulse", text: "text-emerald-400" };
    } else if (status.color === "var(--orange)" || status.color === "var(--amber)") {
      return { dot: "bg-amber-400 animate-pulse", text: "text-amber-400" };
    } else if (status.color === "var(--red)") {
      return { dot: "bg-red-400 animate-pulse", text: "text-error" };
    }
    return { dot: "bg-zinc-400", text: "text-on-surface-variant" };
  };

  const statusStyle = getStatusClasses();

  return (
    <div className="h-screen flex flex-col" id="app">
      {/* TopAppBar */}
      <header className="h-14 flex items-center justify-between px-6 border-b border-outline-variant bg-surface/80 backdrop-blur-md z-50">
        <div className="flex items-center gap-6">
          <span className="text-xl font-bold tracking-tighter text-primary font-display-lg">SCRCPY PRO</span>
          {/* Mode Toggle */}
          <div className="flex bg-surface-container-lowest p-1 rounded border border-outline-variant">
            <button
              className={`px-4 py-1 text-[10px] font-bold rounded transition-all ${simpleMode ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-on-surface"}`}
              onClick={() => setSimpleMode(true)}
            >
              SIMPLE
            </button>
            <button
              className={`px-4 py-1 text-[10px] font-bold rounded transition-all ${!simpleMode ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-on-surface"}`}
              onClick={() => setSimpleMode(false)}
            >
              PRO
            </button>
          </div>
          {/* Operation Status */}
          <div className="hidden md:flex items-center gap-2 text-[11px] font-medium border-l border-outline-variant/30 pl-4" id="header-status">
            <span className={`w-1.5 h-1.5 rounded-full ${statusStyle.dot}`}></span>
            <span className={`font-code ${statusStyle.text}`}>{status.msg}</span>
          </div>
          {/* HUD Stats */}
          {isRunning && (
            <div className="hidden lg:flex items-center gap-3">
              {fps && (
                <div className="flex items-center gap-2 px-3 py-1 bg-surface-container-lowest rounded border border-outline-variant">
                  <span className="w-1.5 h-1.5 bg-white rounded-full pulse-white"></span>
                  <span className="text-[11px] font-code text-on-surface-variant">FPS: <span className="text-primary">{fps}</span></span>
                </div>
              )}
              {hwStats && (
                <>
                  <div className="flex items-center gap-2 px-3 py-1 bg-surface-container-lowest rounded border border-outline-variant">
                    <span className="text-[11px] font-code text-on-surface-variant">CPU: <span className="text-on-surface">{hwStats.cpu}</span></span>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1 bg-surface-container-lowest rounded border border-outline-variant">
                    <span className="text-[11px] font-code text-on-surface-variant">TEMP: <span className="text-on-surface">{hwStats.temp}</span></span>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1 bg-surface-container-lowest rounded border border-outline-variant">
                    <span className="material-symbols-outlined text-[14px] text-on-surface-variant">battery_full</span>
                    <span className="text-[11px] font-code text-on-surface-variant">{hwStats.bat}</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* SideNavBar (Only for PRO Mode) */}
        {!simpleMode && (
          <aside className="w-60 border-r border-outline-variant bg-surface-container-low flex flex-col p-4">
            <div className="mb-6 flex items-center gap-3 px-2">
              <span className="material-symbols-outlined text-primary">terminal</span>
              <span className="font-bold text-sm font-headline-lg-mobile tracking-tight">Dashboard Pro</span>
            </div>
            <nav className="flex-1 space-y-1">
              {[
                { id: "perangkat", icon: "smartphone", label: "Perangkat" },
                { id: "video", icon: "videocam", label: "Video" },
                { id: "audio", icon: "volume_up", label: "Audio" },
                { id: "kontrol", icon: "keyboard", label: "Kontrol" },
                { id: "multitask", icon: "grid_view", label: "Multi-Task" },
                { id: "rekaman", icon: "radio_button_checked", label: "Rekaman" },
                { id: "profil", icon: "account_circle", label: "Profil" },
              ].map(t => (
                <button
                  key={t.id}
                  className={`flex w-full items-center gap-3 px-3 py-2 rounded text-sm transition-colors ${activeTab === t.id ? "text-primary bg-surface-variant font-bold active" : "text-on-surface-variant hover:bg-white/5"}`}
                  onClick={() => setActiveTab(t.id)}
                >
                  <span className="material-symbols-outlined text-[20px]">{t.icon}</span> {t.label}
                </button>
              ))}
            </nav>
          </aside>
        )}

        {/* Workspace */}
        <main className="flex-1 overflow-y-auto p-8 bg-background relative">
          {/* SIMPLE MODE CONTENT */}
          {simpleMode && (
            <div className="max-w-4xl mx-auto space-y-10 pb-32" id="simple-content">
              <div className="space-y-1">
                <h1 className="text-3xl font-bold text-on-surface font-headline-lg">Panduan Cepat</h1>
                <p className="text-on-surface-variant font-body-md">Hubungkan perangkat Anda dalam 4 langkah mudah.</p>
              </div>

              {/* Step 1: Device */}
              <section className="space-y-4">
                <div className="flex items-center gap-3 text-primary font-bold">
                  <span className="w-6 h-6 rounded bg-primary text-on-primary flex items-center justify-center text-xs">1</span>
                  <span className="font-label-md">Pilih Perangkat</span>
                </div>
                <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                  <div className="flex gap-4">
                    <select
                      id="simple-device-select"
                      className="flex-1 rounded px-4 py-3 text-sm focus:outline-none"
                      value={config.device}
                      onChange={e => updateConfig({ device: e.target.value })}
                    >
                      {devices.map(d => <option key={d} value={d}>{d}</option>)}
                    </select>
                    <button className="px-6 py-3 bg-surface-container-high border border-outline-variant rounded hover:bg-surface-variant transition-all flex items-center gap-2" onClick={refreshDevices}>
                      <span className="material-symbols-outlined text-[18px]">refresh</span> Scan
                    </button>
                    <div className="flex gap-2 flex-1 max-w-[320px]">
                      <input
                        className="w-full rounded px-4 py-3 text-sm focus:outline-none font-code"
                        placeholder="192.168.x.x:5555"
                        type="text"
                        value={wifiIp}
                        onChange={e => setWifiIp(e.target.value)}
                      />
                      <button className="px-4 py-3 bg-primary text-on-primary rounded text-xs font-bold hover:brightness-90 transition-all whitespace-nowrap" onClick={() => connectWifi()}>🔗 SAMBUNG</button>
                    </div>
                  </div>
                  {/* Hint Opsi Pengembang */}
                  {(devices.length === 0 || devices[0] === "Tidak ada perangkat") && (
                    <div className="flex items-start gap-2 text-[11px] text-on-surface-variant bg-surface-container-low p-3 rounded border border-outline-variant/30">
                      <span className="material-symbols-outlined text-white text-[16px] mt-0.5">info</span>
                      <span>Jika HP tidak terdeteksi, pastikan USB Debugging aktif: <strong>Pengaturan → Tentang HP → Ketuk Nomor Bentukan 7x → Opsi Pengembang → USB Debugging</strong>.</span>
                    </div>
                  )}
                </div>
              </section>

              {/* Step 2: Quality */}
              <section className="space-y-4">
                <div className="flex items-center gap-3 text-primary font-bold">
                  <span className="w-6 h-6 rounded bg-primary text-on-primary flex items-center justify-center text-xs">2</span>
                  <span className="font-label-md">Preset Kualitas</span>
                </div>
                <div className="grid grid-cols-4 gap-4">
                  {([
                    { key: "Rendah", title: "RENDAH", desc: "800p", sub: "30 FPS / 2 Mbps" },
                    { key: "Sedang", title: "SEDANG", desc: "1280p", sub: "60 FPS / 8 Mbps" },
                    { key: "Tinggi", title: "TINGGI", desc: "1920p", sub: "120 FPS / 24 Mbps" },
                    { key: "2K", title: "ULTRA", desc: "2K", sub: "120 FPS / 32 Mbps" },
                  ] as const).map(q => (
                    <button
                      key={q.key}
                      className={`obsidian-noir-glass p-4 rounded-lg text-center group transition-all ${config.res === PRESETS[q.key]?.res ? "active-preset" : "hover:border-on-surface-variant"}`}
                      onClick={() => applyPreset(q.key)}
                    >
                      <div className="text-[10px] font-bold text-on-surface-variant group-hover:text-primary transition-colors font-label-sm">{q.title}</div>
                      <div className="text-xl font-bold font-display-lg">{q.desc}</div>
                      <div className="text-[10px] text-on-surface-variant mt-1 font-label-sm">{q.sub}</div>
                    </button>
                  ))}
                </div>
              </section>

              {/* Step 3: Features */}
              <section className="space-y-4">
                <div className="flex items-center gap-3 text-primary font-bold">
                  <span className="w-6 h-6 rounded bg-primary text-on-primary flex items-center justify-center text-xs">3</span>
                  <span className="font-label-md">Fitur Utama</span>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  {[
                    { key: "stay_awake", icon: "light_mode", label: "Layar Tetap Menyala" },
                    { key: "turn_off", icon: "phonelink_erase", label: "Matikan Layar HP" },
                    { key: "fullscreen", icon: "fullscreen", label: "Mulai Fullscreen" },
                    { key: "no_audio", icon: "volume_off", label: "Tanpa Audio" },
                  ].map(item => (
                    <label key={item.key} className="obsidian-noir-glass p-4 rounded-lg flex items-center justify-between cursor-pointer group hover:bg-white/5 transition-all">
                      <div className="flex items-center gap-3">
                        <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary">{item.icon}</span>
                        <span className="text-sm font-medium">{item.label}</span>
                      </div>
                      <input
                        type="checkbox"
                        className="rounded bg-black border-outline-variant text-on-surface focus:ring-on-surface"
                        checked={config[item.key as keyof LaunchConfig] as boolean}
                        onChange={e => updateConfig({ [item.key]: e.target.checked })}
                      />
                    </label>
                  ))}
                </div>
              </section>

              {/* Step 4: Virtual */}
              <section className="space-y-4 pb-12">
                <div className="flex items-center gap-3 text-primary font-bold">
                  <span className="w-6 h-6 rounded bg-primary text-on-primary flex items-center justify-center text-xs">4</span>
                  <span className="font-label-md">Layar Virtual (Opsional)</span>
                </div>
                <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-bold text-sm">Aktifkan Display Virtual</h3>
                      <p className="text-[10px] text-on-surface-variant font-label-sm">Menjalankan aplikasi di jendela terpisah tanpa mengganggu HP.</p>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        className="sr-only peer"
                        checked={config.new_display}
                        onChange={e => updateConfig({ new_display: e.target.checked })}
                      />
                      <div className="w-11 h-6 bg-surface-container-highest border border-outline-variant rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-primary after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-on-surface-variant after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-white"></div>
                    </label>
                  </div>
                  {config.new_display && (
                    <div className="mt-4 pt-4 border-t border-outline-variant/30 space-y-3">
                      <div className="flex gap-2">
                        <input
                          className="flex-1 rounded px-4 py-2 text-sm focus:outline-none"
                          placeholder="Ketik nama paket aplikasi (contoh: com.whatsapp)"
                          type="text"
                          list="apps-list-simple"
                          value={config.start_app}
                          onChange={e => updateConfig({ start_app: e.target.value })}
                        />
                        <button className="px-4 py-2 bg-surface-container border border-outline-variant rounded text-[11px] font-bold hover:bg-surface-variant transition-all flex items-center gap-1" onClick={fetchApps}>
                          <span className="material-symbols-outlined text-[14px]">list_alt</span> DAFTAR APP
                        </button>
                      </div>
                      <datalist id="apps-list-simple">
                        {installedApps.map(a => <option key={a} value={a} />)}
                      </datalist>
                      {!config.start_app.trim() && (
                        <div className="text-[10px] text-amber-400 flex items-center gap-1">
                          <span className="material-symbols-outlined text-[14px]">warning</span>
                          <span>Wajib memilih atau mengetik nama paket aplikasi untuk menjalankan Layar Virtual.</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </section>
            </div>
          )}

          {/* PRO MODE CONTENT */}
          {!simpleMode && (
            <div className="space-y-8 pb-32" id="pro-content">
              <div className="flex justify-between items-end mb-4">
                <div>
                  <h1 className="text-3xl font-bold font-headline-lg">Konfigurasi Lanjutan</h1>
                  <p className="text-on-surface-variant font-body-md">Manajemen detail performa dan kontrol sistem.</p>
                </div>
              </div>

              <div id="tab-panels">
                {/* TAB: PERANGKAT */}
                {activeTab === "perangkat" && (
                  <div id="tab-perangkat" className="tab-panel grid grid-cols-12 gap-6">
                    <div className="col-span-12 lg:col-span-5 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">router</span>
                          <h3 className="font-bold text-sm font-label-md">Koneksi Utama</h3>
                        </div>
                        <div className="space-y-3">
                          <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Device Selector</label>
                          <select
                            id="pro-device-select"
                            className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                            value={config.device}
                            onChange={e => updateConfig({ device: e.target.value })}
                          >
                            {devices.map(d => <option key={d} value={d}>{d}</option>)}
                          </select>
                          <div className="flex gap-2">
                            <input
                              className="flex-1 rounded px-4 py-2 text-sm font-code focus:outline-none"
                              placeholder="192.168.1.104:5555"
                              type="text"
                              value={wifiIp}
                              onChange={e => setWifiIp(e.target.value)}
                            />
                            <button className="bg-primary text-on-primary px-4 py-2 rounded text-[11px] font-bold whitespace-nowrap" onClick={() => connectWifi()}>SAMBUNG</button>
                          </div>
                          <div className="flex gap-2 mt-4">
                            <button className="flex-1 py-2 bg-surface-container border border-outline-variant rounded text-[11px] font-bold hover:bg-surface-variant transition-all" onClick={refreshDevices}>REFRESH (🔄)</button>
                            <button className="flex-1 py-2 bg-surface-container border border-outline-variant rounded text-[11px] font-bold hover:bg-surface-variant transition-all" onClick={fetchApps}>DAFTAR APP (📋)</button>
                          </div>
                        </div>
                      </div>
                      {/* Wireless Debugging Option */}
                      <div className="obsidian-noir-glass p-6 rounded-lg bg-white/5 border-primary/20 space-y-3">
                        <div className="flex items-center gap-2">
                          <span className="material-symbols-outlined text-primary">settings_remote</span>
                          <h3 className="font-bold text-sm font-label-md">Wireless Debugging</h3>
                        </div>
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="text-on-surface-variant font-medium">
                            Status:
                            <span className={`px-2 py-0.5 rounded font-bold border ml-1 ${wifiAdbStatus === "on" ? "bg-emerald-950 text-emerald-400 border-emerald-800" : wifiAdbStatus === "off" ? "bg-red-950 text-red-400 border-red-800" : "bg-zinc-800 text-zinc-400 border-zinc-700"}`}>
                              {wifiAdbStatus.toUpperCase()}
                            </span>
                          </span>
                          <button className="px-3 py-1.5 bg-surface-container border border-outline-variant rounded hover:bg-surface-variant text-[10px] font-bold" onClick={toggleDebug}>TOGGLE MODE</button>
                        </div>
                      </div>
                      <div className="obsidian-noir-glass p-6 rounded-lg bg-white/5 border-primary/20">
                        <div className="flex items-center gap-2 mb-4">
                          <span className="material-symbols-outlined text-primary">wifi</span>
                          <h3 className="font-bold text-sm font-label-md">Wifi ADB Converter</h3>
                        </div>
                        <p className="text-[11px] text-on-surface-variant mb-4 leading-relaxed font-body-sm">Konversikan koneksi USB Anda menjadi Wireless secara otomatis hanya dengan satu klik.</p>
                        <button className="w-full py-3 bg-primary text-on-primary rounded text-xs font-bold hover:brightness-90 transition-all uppercase tracking-wider" onClick={enableWifiAdb}>
                          🌐 Aktifkan Wifi ADB
                        </button>
                      </div>
                    </div>
                    {/* Network Scanner */}
                    <div className="col-span-12 lg:col-span-7 obsidian-noir-glass rounded-lg overflow-hidden flex flex-col min-h-[300px]">
                      <div className="p-4 border-b border-outline-variant flex justify-between items-center bg-surface-container-low">
                        <div className="flex items-center gap-2">
                          <span className="material-symbols-outlined text-on-surface text-[20px]">search</span>
                          <span className="font-bold text-sm font-label-md">Network Scanner</span>
                        </div>
                        <div className="flex items-center gap-3">
                          {scanning && <span className="text-[10px] text-primary animate-pulse font-code uppercase">Scanning Subnet...</span>}
                          <button className="px-3 py-1.5 bg-primary text-on-primary text-[10px] font-bold rounded flex items-center gap-1" onClick={scanWifi} disabled={scanning}>
                            <span className="material-symbols-outlined text-[14px]">wifi_find</span> SCAN WIFI
                          </button>
                        </div>
                      </div>
                      <div className="flex-1">
                        <table className="w-full text-[12px] text-left">
                          <thead className="bg-surface-container-lowest text-on-surface-variant font-bold border-b border-outline-variant">
                            <tr>
                              <th className="px-6 py-3 font-label-sm">IDENTITY</th>
                              <th className="px-6 py-3 font-label-sm">ADDRESS</th>
                              <th className="px-6 py-3 font-label-sm">ACTION</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-outline-variant/30">
                            {Object.keys(deviceMap).length > 0 ? (
                              Object.entries(deviceMap).map(([ip, model]) => (
                                <tr key={ip} className="hover:bg-white/5 transition-colors">
                                  <td className="px-6 py-4 flex items-center gap-2 font-body-sm"><span className="material-symbols-outlined text-on-surface-variant text-[16px]">smartphone</span> {model}</td>
                                  <td className="px-6 py-4 font-code">{ip}</td>
                                  <td className="px-6 py-4"><button className="text-on-surface hover:underline font-bold font-label-sm" onClick={() => { setWifiIp(ip); connectWifi(ip); }}>CONNECT</button></td>
                                </tr>
                              ))
                            ) : (
                              <tr>
                                <td colSpan={3} className="px-6 py-8 text-center text-on-surface-variant">Tidak ada hasil scan. Silakan jalankan Scan WiFi.</td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB: VIDEO */}
                {activeTab === "video" && (
                  <div id="tab-video" className="tab-panel grid grid-cols-12 gap-6">
                    <div className="col-span-12 lg:col-span-5 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">aspect_ratio</span>
                          <h3 className="font-bold text-sm font-label-md">Resolusi & Bitrate</h3>
                        </div>
                        <div className="space-y-4">
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Preset Cepat</label>
                            <div className="grid grid-cols-4 gap-1 bg-surface-container-lowest p-0.5 rounded border border-outline-variant">
                              {Object.keys(PRESETS).map(p => (
                                <button
                                  key={p}
                                  className={`py-1 text-[10px] font-bold rounded ${config.res === PRESETS[p]?.res ? "bg-surface-variant text-primary" : "text-on-surface-variant hover:text-on-surface"}`}
                                  onClick={() => applyPreset(p)}
                                >
                                  {p}
                                </button>
                              ))}
                            </div>
                          </div>
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Resolusi Maks</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.res}
                              onChange={e => updateConfig({ res: e.target.value })}
                            >
                              {["Bawaan", "2560", "1920", "1280", "1024", "800", "600"].map(v => <option key={v} value={v}>{v}</option>)}
                            </select>
                          </div>
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">FPS Maks</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.fps}
                              onChange={e => updateConfig({ fps: e.target.value })}
                            >
                              {["60", "144", "120", "90", "30", "15"].map(v => <option key={v} value={v}>{v}</option>)}
                            </select>
                          </div>
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Bitrate Video</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.bitrate}
                              onChange={e => updateConfig({ bitrate: e.target.value })}
                            >
                              {["8M", "32M", "24M", "16M", "4M", "2M", "1M"].map(v => <option key={v} value={v}>{v === "8M" ? "8 Mbps" : v === "32M" ? "32 Mbps" : v === "24M" ? "24 Mbps" : v === "16M" ? "16 Mbps" : v === "4M" ? "4 Mbps" : v === "2M" ? "2 Mbps" : "1 Mbps"}</option>)}
                            </select>
                          </div>
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Codec Video</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.codec}
                              onChange={e => updateConfig({ codec: e.target.value })}
                            >
                              {["h264", "h265", "av1"].map(v => <option key={v} value={v}>{v}</option>)}
                            </select>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="col-span-12 lg:col-span-7 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">videocam</span>
                          <h3 className="font-bold text-sm font-label-md">Kamera &amp; Sizing</h3>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Sumber Video</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.video_source}
                              onChange={e => updateConfig({ video_source: e.target.value })}
                            >
                              <option value="Bawaan">Layar HP</option>
                              <option value="camera">Kamera HP</option>
                            </select>
                          </div>
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Posisi Kamera</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.camera_facing}
                              onChange={e => updateConfig({ camera_facing: e.target.value })}
                              disabled={config.video_source !== "camera"}
                            >
                              <option value="Bawaan">Bawaan (Default)</option>
                              <option value="front">Kamera Depan</option>
                              <option value="back">Kamera Belakang</option>
                            </select>
                          </div>
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Rotasi Layar</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.rotation}
                              onChange={e => updateConfig({ rotation: e.target.value })}
                            >
                              <option value="Bawaan">Mengikuti HP</option>
                              <option value="lock">Kunci Orientasi Awal</option>
                              <option value="0">0°</option>
                              <option value="1">90° CCW</option>
                              <option value="2">180°</option>
                              <option value="3">90° CW</option>
                            </select>
                          </div>
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Display ID</label>
                            <input
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              placeholder="ID Layar HP..."
                              type="text"
                              value={config.display_id}
                              onChange={e => updateConfig({ display_id: e.target.value })}
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB: AUDIO */}
                {activeTab === "audio" && (
                  <div id="tab-audio" className="tab-panel grid grid-cols-12 gap-6">
                    <div className="col-span-12 lg:col-span-6 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">settings_voice</span>
                          <h3 className="font-bold text-sm font-label-md">Codec &amp; Input</h3>
                        </div>
                        <div className="space-y-4">
                          <label className="flex items-center justify-between cursor-pointer group p-2 rounded hover:bg-white/5 transition-all">
                            <span className="text-sm font-medium">Matikan Suara (No Audio)</span>
                            <input
                              type="checkbox"
                              className="rounded bg-black border-outline-variant text-on-surface focus:ring-on-surface"
                              checked={config.no_audio}
                              onChange={e => updateConfig({ no_audio: e.target.checked })}
                            />
                          </label>
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Sumber Audio</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.audio_source}
                              onChange={e => updateConfig({ audio_source: e.target.value })}
                              disabled={config.no_audio}
                            >
                              <option value="Bawaan">Internal Audio (Default)</option>
                              <option value="mic">Mikrofon</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="col-span-12 lg:col-span-6 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">slow_motion_video</span>
                          <h3 className="font-bold text-sm font-label-md">Buffer</h3>
                        </div>
                        <div className="space-y-4">
                          <div className="space-y-2">
                            <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Buffer Audio (ms)</label>
                            <select
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              value={config.audio_buffer}
                              onChange={e => updateConfig({ audio_buffer: e.target.value })}
                              disabled={config.no_audio}
                            >
                              {["200", "100", "50", "300", "500"].map(v => <option key={v} value={v}>{v} ms</option>)}
                            </select>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB: KONTROL */}
                {activeTab === "kontrol" && (
                  <div id="tab-kontrol" className="tab-panel grid grid-cols-12 gap-6">
                    <div className="col-span-12 lg:col-span-6 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">mouse</span>
                          <h3 className="font-bold text-sm font-label-md">Input &amp; Clipboard</h3>
                        </div>
                        <div className="space-y-3">
                          {[
                            { key: "copy_paste", label: "Sinkronisasi Clipboard" },
                            { key: "volume_keys", label: "Forward Tombol Volume PC" },
                            { key: "uhid", label: "Mode Keyboard UHID" },
                            { key: "otg", label: "Mode OTG (Kabel USB)" },
                          ].map(item => (
                            <label key={item.key} className="flex items-center justify-between cursor-pointer p-2 rounded hover:bg-white/5 transition-all">
                              <span className="text-sm font-medium">{item.label}</span>
                              <input
                                type="checkbox"
                                className="rounded bg-black border-outline-variant text-on-surface focus:ring-on-surface"
                                checked={config[item.key as keyof LaunchConfig] as boolean}
                                onChange={e => {
                                  const updates: Partial<LaunchConfig> = { [item.key]: e.target.checked };
                                  if (item.key === "otg" && e.target.checked) updates.uhid = false;
                                  if (item.key === "uhid" && e.target.checked) updates.otg = false;
                                  updateConfig(updates);
                                }}
                              />
                            </label>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div className="col-span-12 lg:col-span-6 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">settings_system_daydream</span>
                          <h3 className="font-bold text-sm font-label-md">Perilaku Window</h3>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          {[
                            { key: "stay_awake", label: "HP Tetap Menyala" },
                            { key: "turn_off", label: "Matikan Layar HP" },
                            { key: "on_top", label: "Selalu Di Atas" },
                            { key: "fullscreen", label: "Mulai Fullscreen" },
                            { key: "show_touches", label: "Tampilkan Sentuhan" },
                            { key: "borderless", label: "Tanpa Border" },
                            { key: "no_control", label: "Hanya Lihat" },
                          ].map(item => (
                            <label key={item.key} className="flex items-center gap-3 cursor-pointer p-2 rounded hover:bg-white/5 transition-all">
                              <input
                                type="checkbox"
                                className="rounded bg-black border-outline-variant text-on-surface focus:ring-on-surface"
                                checked={config[item.key as keyof LaunchConfig] as boolean}
                                onChange={e => updateConfig({ [item.key]: e.target.checked })}
                              />
                              <span className="text-xs">{item.label}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div className="col-span-12 obsidian-noir-glass p-6 rounded-lg space-y-2">
                      <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Argumen Tambahan (Extra CLI Flags)</label>
                      <input
                        className="w-full rounded px-4 py-3 text-sm font-code focus:outline-none"
                        placeholder="Contoh: --render-driver=opengl --window-x=100"
                        type="text"
                        value={config.extra_args}
                        onChange={e => updateConfig({ extra_args: e.target.value })}
                      />
                    </div>
                  </div>
                )}

                {/* TAB: MULTITASK */}
                {activeTab === "multitask" && (
                  <div id="tab-multitask" className="tab-panel grid grid-cols-12 gap-6">
                    <div className="col-span-12 lg:col-span-6 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">layers</span>
                          <h3 className="font-bold text-sm font-label-md">Display Virtual</h3>
                        </div>
                        <div className="space-y-4">
                          <label className="flex items-center justify-between cursor-pointer p-2 rounded hover:bg-white/5 transition-all">
                            <span className="text-sm font-medium">Aktifkan Layar Virtual Baru</span>
                            <input
                              type="checkbox"
                              className="rounded bg-black border-outline-variant text-on-surface focus:ring-on-surface"
                              checked={config.new_display}
                              onChange={e => updateConfig({ new_display: e.target.checked })}
                            />
                          </label>
                          {config.new_display && (
                            <>
                              <div className="space-y-2">
                                <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Resolusi Layar Virtual</label>
                                <select
                                  className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                                  value={config.vdisplay_res}
                                  onChange={e => updateConfig({ vdisplay_res: e.target.value })}
                                >
                                  {["Bawaan", "1920x1080", "1280x720", "1080x1920"].map(v => <option key={v} value={v}>{v}</option>)}
                                </select>
                              </div>
                              {!config.uhid && !config.otg && (
                                <>
                                  <div className="space-y-2">
                                    <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Mode Mouse Virtual</label>
                                    <select
                                      className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                                      value={config.vd_mouse_mode}
                                      onChange={e => updateConfig({ vd_mouse_mode: e.target.value })}
                                    >
                                      <option value="uhid">UHID (Virtual HID)</option>
                                      <option value="disabled">Disabled (Mouse Tetap di PC)</option>
                                      <option value="sdk">SDK (Default)</option>
                                    </select>
                                  </div>
                                  <div className="space-y-2">
                                    <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Mode Keyboard Virtual</label>
                                    <select
                                      className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                                      value={config.vd_kbd_mode}
                                      onChange={e => updateConfig({ vd_kbd_mode: e.target.value })}
                                    >
                                      <option value="uhid">UHID (Virtual HID)</option>
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
                    </div>
                    {config.new_display && (
                      <div className="col-span-12 lg:col-span-6 space-y-6">
                        <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                          <div className="flex items-center gap-2 mb-2">
                            <span className="material-symbols-outlined text-primary">open_in_new</span>
                            <h3 className="font-bold text-sm font-label-md">Mulai Aplikasi</h3>
                          </div>
                          <div className="space-y-4">
                            <div className="space-y-2">
                              <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Nama Paket Aplikasi (Package Name)</label>
                              <div className="flex gap-2">
                                <input
                                  id="pro-start-app"
                                  className="flex-1 rounded px-4 py-2 text-sm focus:outline-none"
                                  placeholder="Contoh: com.android.chrome"
                                  type="text"
                                  list="apps-list-pro"
                                  value={config.start_app}
                                  onChange={e => updateConfig({ start_app: e.target.value })}
                                />
                                <button className="bg-surface-container border border-outline-variant text-[11px] font-bold px-3 rounded hover:bg-surface-variant transition-all" onClick={fetchApps}>📋 DAFTAR APP</button>
                              </div>
                              <datalist id="apps-list-pro">
                                {installedApps.map(a => <option key={a} value={a} />)}
                              </datalist>
                              <div id="pro-app-warning" className="text-[10.5px] text-amber-400 flex items-center gap-1 mt-1">
                                <span className="material-symbols-outlined text-[14px]">warning</span>
                                <span>Wajib diisi untuk Layar Virtual.</span>
                              </div>
                            </div>
                            <label className="flex items-center gap-3 cursor-pointer p-2 rounded hover:bg-white/5 transition-all">
                              <input
                                id="pro-new-task"
                                type="checkbox"
                                className="rounded bg-black border-outline-variant text-on-surface focus:ring-on-surface"
                                checked={config.new_task}
                                onChange={e => updateConfig({ new_task: e.target.checked })}
                              />
                              <span className="text-sm font-medium">Buka di Task Baru (+)</span>
                            </label>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* TAB: REKAMAN */}
                {activeTab === "rekaman" && (
                  <div id="tab-rekaman" className="tab-panel grid grid-cols-12 gap-6">
                    <div className="col-span-12 obsidian-noir-glass p-6 rounded-lg space-y-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="material-symbols-outlined text-primary">videocam</span>
                        <h3 className="font-bold text-sm font-label-md">Perekam Video Layar</h3>
                      </div>
                      <div className="space-y-4">
                        <label className="flex items-center gap-3 cursor-pointer p-2 rounded hover:bg-white/5 transition-all">
                          <input
                            type="checkbox"
                            className="rounded bg-black border-outline-variant text-on-surface focus:ring-on-surface"
                            checked={config.record}
                            onChange={e => updateConfig({ record: e.target.checked })}
                          />
                          <span className="text-sm font-medium">Simpan Sesi Streaming ke File</span>
                        </label>
                        <div className="space-y-2">
                          <label className="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold font-label-sm block">Lokasi Penyimpanan &amp; Nama Berkas</label>
                          <input
                            className="w-full rounded px-4 py-3 text-sm font-code focus:outline-none"
                            placeholder="Misal: C:/Users/aziz/Videos/rekaman.mp4"
                            type="text"
                            value={config.record_path}
                            onChange={e => updateConfig({ record_path: e.target.value })}
                            disabled={!config.record}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB: PROFIL */}
                {activeTab === "profil" && (
                  <div id="tab-profil" className="tab-panel grid grid-cols-12 gap-6">
                    <div className="col-span-12 lg:col-span-6 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">folder_special</span>
                          <h3 className="font-bold text-sm font-label-md">Profil Tersimpan</h3>
                        </div>
                        <div className="space-y-3">
                          <select
                            className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                            value={selectedProfile}
                            onChange={e => setSelectedProfile(e.target.value)}
                          >
                            {Object.keys(profiles).length === 0 ? (
                              <option value="">(Belum ada profil)</option>
                            ) : (
                              Object.keys(profiles).map(p => <option key={p} value={p}>{p}</option>)
                            )}
                          </select>
                          <div className="flex gap-2">
                            <button className="flex-1 py-2 bg-primary text-on-primary rounded text-[11px] font-bold" onClick={loadSelectedProfile}>MUAT</button>
                            <button className="flex-1 py-2 bg-surface-container border border-outline-variant text-error rounded text-[11px] font-bold hover:bg-error/10 transition-all border-error/20" onClick={deleteProfile}>HAPUS</button>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="col-span-12 lg:col-span-6 space-y-6">
                      <div className="obsidian-noir-glass p-6 rounded-lg space-y-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="material-symbols-outlined text-primary">create_new_folder</span>
                          <h3 className="font-bold text-sm font-label-md">Simpan Profil Baru</h3>
                        </div>
                        <div className="space-y-4">
                          <div className="space-y-2">
                            <input
                              className="w-full rounded px-4 py-2 text-sm focus:outline-none"
                              placeholder="Nama profil baru..."
                              type="text"
                              value={newProfileName}
                              onChange={e => setNewProfileName(e.target.value)}
                            />
                          </div>
                          <button className="w-full py-3 bg-primary text-on-primary rounded text-xs font-bold hover:brightness-90 transition-all uppercase tracking-wider" onClick={saveProfile}>
                            💾 Simpan Konfigurasi
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Command Preview Card */}
              <div className="obsidian-noir-glass p-6 rounded-lg mt-6 space-y-3">
                <div className="flex justify-between items-center border-b border-outline-variant/30 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-[20px]">visibility</span>
                    <span className="font-bold text-sm font-label-md">Command Preview</span>
                  </div>
                  <button className="px-3 py-1.5 bg-surface-container border border-outline-variant rounded hover:bg-surface-variant text-[10px] font-bold flex items-center gap-1" onClick={copyCommand}>
                    <span className="material-symbols-outlined text-[14px]">content_copy</span> COPY
                  </button>
                </div>
                <div id="pro-command-preview" className="bg-surface-container-lowest/80 p-4 rounded font-code text-[11px] text-on-surface border border-outline-variant/30 select-all whitespace-normal break-all">
                  {cmdPreview || <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>Konfigurasi belum dibuat...</span>}
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* BottomNavBar / Terminal */}
      <footer className="h-[240px] obsidian-noir-glass border-t border-outline-variant z-50 flex flex-col relative">
        {/* Xiaomi/General Error Alert Card */}
        {!isRunning && (detailedError || status.color === "var(--red)") && (
          <div id="error-alert" className="absolute bottom-16 left-6 right-6 p-4 rounded bg-red-950/40 border border-error/25 text-sm z-50 animate-fadeUp max-h-48 overflow-y-auto">
            <div className="flex items-center gap-2 mb-1 text-error font-bold">
              <span className="material-symbols-outlined text-error text-[18px]">warning</span>
              <span>Terjadi Kesalahan Scrcpy</span>
            </div>
            <div className="text-[11px] text-on-surface-variant leading-relaxed">
              {detailedError || status.msg}
              {((detailedError || status.msg || "").includes("INJECT_EVENTS") || 
                (detailedError || status.msg || "").toLowerCase().includes("security settings") || 
                (detailedError || status.msg || "").toLowerCase().includes("setelan keamanan")) && (
                <div className="mt-2 text-primary font-medium">
                  💡 Cara Mengatasi (Xiaomi/Redmi/Poco):
                  <ol className="list-decimal list-inside text-on-surface mt-1 pl-1 space-y-0.5 font-sans">
                    <li>Buka <strong>Opsi Pengembang</strong> di HP Anda.</li>
                    <li>Aktifkan <strong>"USB debugging (Setelan Keamanan)"</strong> / <strong>"USB debugging (Security Settings)"</strong>.</li>
                    <li>Mulai ulang (reboot) HP Anda, lalu coba sambungkan kembali.</li>
                  </ol>
                  <div className="mt-2">
                    <em>Atau, Anda bisa menggunakan mode <strong>"Hanya Lihat"</strong> di tab Kontrol jika tidak perlu mengontrol HP dari PC.</em>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Terminal Header */}
        <div className="h-10 bg-surface-container-lowest flex items-center justify-between px-6 border-b border-outline-variant">
          <div className="flex items-center gap-4">
            <span className="text-[10px] font-bold text-on-surface-variant tracking-widest font-label-sm">TERMINAL OUTPUT</span>
            <div className="flex gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-surface-variant"></span>
              <span className="w-2.5 h-2.5 rounded-sm bg-surface-variant"></span>
              <span className="w-2.5 h-2.5 rounded-sm bg-surface-variant"></span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="material-symbols-outlined text-on-surface-variant hover:text-on-surface cursor-pointer text-[18px]" onClick={copyCommand}>content_copy</span>
            <span className="material-symbols-outlined text-on-surface-variant hover:text-on-surface cursor-pointer text-[18px]" onClick={() => setDetailedError(null)}>delete</span>
          </div>
        </div>

        {/* Terminal Logs */}
        <div className="flex-1 bg-surface-container-lowest/90 p-4 font-code text-[12px] terminal-scroll overflow-y-auto">
          <div className="flex gap-4 text-on-surface-variant">
            <span className="text-on-surface font-bold">[INFO]</span>
            <span>Scrcpy Pro Launcher v5.0 (Obsidian Noir)</span>
          </div>
          <div className="flex gap-4 text-on-surface-variant">
            <span className="text-on-surface font-bold">[INFO]</span>
            <span>Status Sesi: {isRunning ? "Scrcpy sedang berjalan..." : "Siap."}</span>
          </div>
          {cmdPreview && (
            <div className="flex gap-4 text-on-surface-variant mt-1">
              <span className="text-on-surface-variant/60">[CMD]</span>
              <span className="text-on-surface">{cmdPreview}</span>
            </div>
          )}
          {detailedError && (
            <div className="text-error mt-2 whitespace-pre-wrap font-mono">
              {detailedError}
            </div>
          )}
          {isRunning && <div className="mt-4 text-primary animate-pulse">_</div>}
        </div>

        {/* Action Bar */}
        <div className="h-16 border-t border-outline-variant bg-surface flex items-center justify-between px-6">
          <div className="flex items-center gap-6">
            <button
              className="flex items-center gap-2 px-6 py-2 bg-surface-container border border-outline-variant rounded text-error text-xs font-bold hover:bg-error/10 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              onClick={stopScrcpy}
              disabled={!isRunning}
            >
              <span className="material-symbols-outlined text-[18px]">stop</span> STOP
            </button>
            <div className="h-6 w-px bg-outline-variant"></div>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-on-surface-variant font-label-sm">
                STATUS: <span className="font-code text-on-surface">{isRunning ? "RUNNING" : "STOPPED"}</span>
              </span>
            </div>
          </div>
          <button
            className="flex items-center gap-3 px-10 py-3 bg-primary text-on-primary rounded text-sm font-bold hover:scale-[1.02] active:scale-[0.98] transition-all uppercase tracking-tighter disabled:opacity-40 disabled:cursor-not-allowed"
            onClick={launchScrcpy}
            disabled={isRunning || (config.new_display && !config.start_app.trim())}
          >
            <span className="material-symbols-outlined text-[20px]">play_arrow</span> JALANKAN
          </button>
        </div>
      </footer>
    </div>
  );
}

export default App;
