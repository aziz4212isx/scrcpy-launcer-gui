export interface LaunchConfig {
  device: string;
  res: string;
  fps: string;
  bitrate: string;
  codec: string;
  audio_buffer: string;
  stay_awake: boolean;
  turn_off: boolean;
  on_top: boolean;
  no_audio: boolean;
  fullscreen: boolean;
  show_touches: boolean;
  borderless: boolean;
  no_control: boolean;
  otg: boolean;
  uhid: boolean;
  copy_paste: boolean;
  volume_keys: boolean;
  new_display: boolean;
  vdisplay_res: string;
  vd_mouse_mode: string;
  vd_kbd_mode: string;
  start_app: string;
  new_task: boolean;
  record: boolean;
  record_path: string;
  video_source: string;
  camera_facing: string;
  audio_source: string;
  rotation: string;
  display_id: string;
  print_fps: boolean;
  extra_args: string;
}

export const DEFAULT_CONFIG: LaunchConfig = {
  device: "",
  res: "1280",
  fps: "60",
  bitrate: "8M",
  codec: "h264",
  audio_buffer: "200",
  stay_awake: false,
  turn_off: false,
  on_top: false,
  no_audio: false,
  fullscreen: false,
  show_touches: false,
  borderless: false,
  no_control: false,
  otg: false,
  uhid: false,
  copy_paste: true,
  volume_keys: true,
  new_display: false,
  vdisplay_res: "Bawaan",
  vd_mouse_mode: "uhid",
  vd_kbd_mode: "uhid",
  start_app: "",
  new_task: true,
  record: false,
  record_path: "",
  video_source: "display",
  camera_facing: "any",
  audio_source: "output",
  rotation: "0",
  display_id: "Bawaan",
  print_fps: true,
  extra_args: "",
};

export const PRESETS: Record<string, Partial<LaunchConfig>> = {
  "2K":     { res: "2560", fps: "120", bitrate: "32M", codec: "h265" },
  "Tinggi": { res: "1920", fps: "120", bitrate: "24M", codec: "h264" },
  "Sedang": { res: "1280", fps: "60",  bitrate: "8M",  codec: "h264" },
  "Rendah": { res: "800",  fps: "30",  bitrate: "2M",  codec: "h264" },
};
