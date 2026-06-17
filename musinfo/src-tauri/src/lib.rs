mod menu;
use rosc::decoder::decode_udp;
use rosc::OscPacket;
use serde_json::Value;
use std::fs;
use std::net::UdpSocket;
use std::path::Path;
use std::process::Stdio;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, Emitter, Manager, State};

// ─── PROCESS STATE ────────────────────────────────────────────────────────────

// Test processes — killed on demand only
struct TestProcess(Mutex<Option<Child>>);
struct MidiTestProcess(Mutex<Option<Child>>);

// PIPELINE TIER — fast processes, killed/restarted freely on stop/start
struct CaptureProcess(Mutex<Option<Child>>);
struct BroadcasterProcess(Mutex<Option<Child>>);
struct WindowsReceiverProcess(Mutex<Option<Child>>);
struct MidiCaptureProcess(Mutex<Option<Child>>);

// PERSISTENT TIER — spawned once at app startup, killed only on app exit.
// These hold the heavy ML models in memory so stop/start is near-instant.
// midi_harmony_analyser runs in-process inside midi_capture.py — not managed here.
struct WslProcess(Mutex<Option<Child>>);
struct WslHeavyProcess(Mutex<Option<Child>>);

// IMAGE GENERATION TIER — spawned at startup, persistent like WSL processes
struct PromptGeneratorProcess(Mutex<Option<Child>>);
struct ImageGenProcess(Mutex<Option<Child>>);
static PIPELINE_RUNNING: AtomicBool = AtomicBool::new(false);

// AUDIO DEVICES CACHE - cached list of audio devices to avoid expensive re-querying on every reconcile

struct AudioDeviceCache(Mutex<Option<Vec<Value>>>);

// DEBUGGING
const OSC_DEBUG: bool = false;

// ─── PATH HELPERS ─────────────────────────────────────────────────────────────

fn instruments_path() -> Result<std::path::PathBuf, String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?;
    Ok(root.join("backend/config/instruments.json"))
}

fn performance_path() -> Result<std::path::PathBuf, String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?;
    Ok(root.join("backend/config/performance.json"))
}

fn sessions_path() -> Result<std::path::PathBuf, String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?;
    Ok(root.join("sessions"))
}

fn project_root_windows() -> Result<&'static Path, String> {
    // CARGO_MANIFEST_DIR is baked in at compile time — safe to return as 'static
    static ROOT: std::sync::OnceLock<std::path::PathBuf> = std::sync::OnceLock::new();
    let root = ROOT.get_or_init(|| {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("Could not resolve project root")
            .to_path_buf()
    });
    Ok(root.as_path())
}

fn project_root_wsl() -> Result<String, String> {
    let win = project_root_windows()?;
    Ok(win
        .to_string_lossy()
        .replace("C:\\", "/mnt/c/")
        .replace('\\', "/")
        .to_lowercase())
}

fn project_root_image_gen() -> Result<std::path::PathBuf, String> {
    let root = project_root_windows()?;
    Ok(root.join("AI_image_generation"))
}

// ─── CONFIG HELPERS ───────────────────────────────────────────────────────────

fn read_config(path: &Path) -> Result<serde_json::Map<String, Value>, String> {
    let raw = fs::read_to_string(path).map_err(|e| format!("Failed to read: {}", e))?;
    serde_json::from_str(&raw).map_err(|e| format!("Failed to parse: {}", e))
}

fn write_config(path: &Path, config: &serde_json::Map<String, Value>) -> Result<(), String> {
    let out =
        serde_json::to_string_pretty(config).map_err(|e| format!("Serialize error: {}", e))?;
    fs::write(path, out).map_err(|e| format!("Write error: {}", e))
}



// ─── PERSISTENT TIER — spawned once, kept alive across pipeline stop/start ───

/// Spawns wsl_receiver.py and wsl_receiver_heavy.py inside WSL.
/// Called once from setup(). These processes hold all TensorFlow/Essentia
/// models in memory — killing them forces a full reload, so we don't.
fn spawn_persistent_processes(
    wsl_state:             &WslProcess,
    wsl_heavy_state:       &WslHeavyProcess,
    prompt_gen_state:      &PromptGeneratorProcess,
    image_gen_state:       &ImageGenProcess,
) -> Result<(), String> {
    let wsl_root = project_root_wsl()?;
    let venv     = format!("{}/backend/wsl/.venv/bin/activate", wsl_root);
    let img_root = project_root_image_gen()?;

    // wsl_receiver.py — unchanged
    {
        let mut guard = wsl_state.0.lock().unwrap();
        if guard.is_none() {
            let script = format!("{}/backend/wsl/wsl_receiver.py", wsl_root);
            let cmd    = format!("source {} && python3 {}", venv, script);
            println!("[Tauri] Spawning persistent wsl_receiver.py...");
            let child = Command::new("wsl")
                .args(["-d", "Ubuntu", "/bin/bash", "-c", &cmd])
                .spawn()
                .map_err(|e| format!("Failed to spawn wsl_receiver.py: {}", e))?;
            *guard = Some(child);
            println!("[Tauri] wsl_receiver.py spawned.");
        }
    }

    // wsl_receiver_heavy.py — unchanged
    {
        let mut guard = wsl_heavy_state.0.lock().unwrap();
        if guard.is_none() {
            let script = format!("{}/backend/wsl/wsl_receiver_heavy.py", wsl_root);
            let cmd    = format!("source {} && python3 {}", venv, script);
            println!("[Tauri] Spawning persistent wsl_receiver_heavy.py...");
            let child = Command::new("wsl")
                .args(["-d", "Ubuntu", "/bin/bash", "-c", &cmd])
                .spawn()
                .map_err(|e| format!("Failed to spawn wsl_receiver_heavy.py: {}", e))?;
            *guard = Some(child);
            println!("[Tauri] wsl_receiver_heavy.py spawned.");
        }
    }

    // prompt_generator.py — Windows side, AI_image_generation/
    {
        let mut guard = prompt_gen_state.0.lock().unwrap();
        if guard.is_none() {
            let script = img_root.join("prompt_generator.py");
            println!("[Tauri] Spawning persistent prompt_generator.py...");
            let child = Command::new("python")
                .arg(&script)
                .spawn()
                .map_err(|e| format!("Failed to spawn prompt_generator.py: {}", e))?;
            *guard = Some(child);
            println!("[Tauri] prompt_generator.py spawned.");
        }
    }

    // generate_image.py — Windows side, AI_image_generation/
    // This takes 15-30s to load the model — spawned early so it's ready by the time
    // the user starts a session.
    {
        let mut guard = image_gen_state.0.lock().unwrap();
        if guard.is_none() {
            let script = img_root.join("generate_image.py");
            println!("[Tauri] Spawning persistent generate_image.py (model loading ~15-30s)...");
            let child = Command::new("python")
                .arg(&script)
                .spawn()
                .map_err(|e| format!("Failed to spawn generate_image.py: {}", e))?;
            *guard = Some(child);
            println!("[Tauri] generate_image.py spawned.");
        }
    }

    Ok(())
}

/// Kills both persistent WSL processes. Called only on app exit.
fn kill_persistent_processes(
    wsl_state:        &WslProcess,
    wsl_heavy_state:  &WslHeavyProcess,
    prompt_gen_state: &PromptGeneratorProcess,
    image_gen_state:  &ImageGenProcess,
) {
    if let Some(mut child) = wsl_state.0.lock().unwrap().take() {
        let _ = child.kill();
        println!("[Tauri] wsl_receiver.py stopped.");
    }
    if let Some(mut child) = wsl_heavy_state.0.lock().unwrap().take() {
        let _ = child.kill();
        println!("[Tauri] wsl_receiver_heavy.py stopped.");
    }
    if let Some(mut child) = prompt_gen_state.0.lock().unwrap().take() {
        let _ = child.kill();
        println!("[Tauri] prompt_generator.py stopped.");
    }
    if let Some(mut child) = image_gen_state.0.lock().unwrap().take() {
        let _ = child.kill();
        println!("[Tauri] generate_image.py stopped.");
    }
}

// ─── PERFORMANCE CONFIG ───────────────────────────────────────────────────────

#[tauri::command]
fn save_performance_config(
    enabled: bool,
    key: Option<String>,
    scale: Option<String>,
) -> Result<(), String> {
    let path = performance_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create config dir: {}", e))?;
    }
    let config = serde_json::json!({
        "Performance": {
            "forcedKey": {
                "enabled": enabled,
                "key": key,
                "scale": scale
            }
        }
    });
    let out = serde_json::to_string_pretty(&config)
        .map_err(|e| format!("Serialize error: {}", e))?;
    fs::write(&path, out).map_err(|e| format!("Write error: {}", e))?;
    Ok(())
}

// ─── IMAGE GENERATION ──────────────────────────────────────────────────────────────

#[tauri::command]
fn toggle_image_generation(enabled: bool) -> Result<(), String> {
    let socket = UdpSocket::bind("0.0.0.0:0")
        .map_err(|e| format!("Failed to bind OSC socket: {}", e))?;

    fn build_osc(address: &str, value: i32) -> Vec<u8> {
        use rosc::{OscMessage, OscPacket, OscType};
        rosc::encoder::encode(&OscPacket::Message(OscMessage {
            addr: address.to_string(),
            args: vec![OscType::Int(value)],
        })).unwrap_or_default()
    }

    let flag: i32 = if enabled { 1 } else { 0 };
    let msg = build_osc("/musinfo/image_gen_enabled", flag);
    socket.send_to(&msg, "127.0.0.1:9001")
        .map_err(|e| format!("Failed to send OSC to prompt_generator: {}", e))?;
    socket.send_to(&msg, "127.0.0.1:9002")
        .map_err(|e| format!("Failed to send OSC to generate_image: {}", e))?;

    println!("[Tauri] image_gen_enabled -> {} (prompt_generator + generate_image)", flag);
    Ok(())
}
// ─── INSTRUMENTS ──────────────────────────────────────────────────────────────

#[tauri::command]
fn save_instrument(_app: AppHandle, instrument: Value) -> Result<String, String> {
    let root = project_root_windows()?;
    let config_path = root.join("backend/config/instruments.json");

    let raw = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read instruments.json: {}", e))?;
    let mut config: serde_json::Map<String, Value> = serde_json::from_str(&raw)
        .map_err(|e| format!("Failed to parse instruments.json: {}", e))?;

    let name = instrument["name"]
        .as_str()
        .ok_or("Instrument has no name")?
        .to_string();

    let mut entry = instrument.clone();
    if let Some(obj) = entry.as_object_mut() {
        obj.remove("name");
    }

    let instruments = config
        .get_mut("instruments")
        .and_then(|v| v.as_object_mut())
        .ok_or("instruments.json has no 'instruments' key")?;

    instruments.insert(name, entry);

    // Sink mix to last entry after every save
    if let Some(mix_entry) = instruments.remove("mix") {
        instruments.insert("mix".to_string(), mix_entry);
    }

    let output = serde_json::to_string_pretty(&config)
        .map_err(|e| format!("Failed to serialize: {}", e))?;
    fs::write(&config_path, output)
        .map_err(|e| format!("Failed to write instruments.json: {}", e))?;


    send_instrument_config_osc(); 


    Ok("Instrument saved".to_string())
}

fn send_instrument_config_osc() {
    let path = match instruments_path() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("[Tauri] send_instrument_config_osc: {}", e);
            return;
        }
    };

    let config = match read_config(&path) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[Tauri] send_instrument_config_osc: {}", e);
            return;
        }
    };

    let instruments = match config.get("instruments").and_then(|v| v.as_object()) {
        Some(i) => i,
        None => {
            eprintln!("[Tauri] send_instrument_config_osc: no instruments key");
            return;
        }
    };

    // Always initialise all known roles to 0 first
    let mut role_counts: std::collections::HashMap<String, i32> = std::collections::HashMap::new();
    for role in &["default", "drums", "bass", "guitar", "vocals", "piano"] {
        role_counts.insert(role.to_string(), 0);
    }

    // Count what's actually in instruments.json, excluding mix
    for (name, data) in instruments.iter() {
        if name == "mix" { continue; }
        let role = data["role"].as_str().unwrap_or("default").to_string();
        *role_counts.entry(role).or_insert(0) += 1;
    }

    let socket = match UdpSocket::bind("0.0.0.0:0") {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[Tauri] send_instrument_config_osc: socket error: {}", e);
            return;
        }
    };

    let td_addr = "127.0.0.1:9103";

    for (role, count) in &role_counts {
        use rosc::{OscMessage, OscPacket, OscType};

        let msg = rosc::encoder::encode(&OscPacket::Message(OscMessage {
            addr: format!("/td/config/{}", role),
            args: vec![OscType::Int(*count)],
        })).unwrap_or_default();

        socket.send_to(&msg, td_addr).ok();
    }

    println!("[Tauri] Role counts sent to TouchDesigner: {:?}", role_counts);
}

#[tauri::command]
fn delete_instrument(_app: AppHandle, name: String) -> Result<String, String> {
    let path = instruments_path()?;
    let mut config = read_config(&path)?;
    config
        .get_mut("instruments")
        .and_then(|v| v.as_object_mut())
        .ok_or("instruments.json has no 'instruments' key")?
        .remove(&name);
    write_config(&path, &config)?;

    send_instrument_config_osc();

    Ok("Instrument deleted".to_string())
}


// ─── AUDIO DEVICES ────────────────────────────────────────────────────────────

/// Spawns Python + PortAudio with ASIO. Only called on cache miss or force-refresh.
/// Returns ALL filtered input devices; each entry carries `is_virtual` so Rust
/// can filter by type without a second spawn.
fn fetch_audio_devices_python() -> Vec<Value> {
    let script = r#"
import json, sounddevice as sd
devices   = sd.query_devices()
host_apis = sd.query_hostapis()
result    = []
VIRTUAL_KEYWORDS = ["vb", "virtual", "cable", "voicemeeter", "stereo mix"]
EXCLUDE_KEYWORDS = [
    "mapper", "ndi", "webcam", "asio4all", "realtek asio",
    "pc speaker", "hfenum", "hands-free", "microphone array", "microphone (realtek",
]
for i, d in enumerate(devices):
    api_name = host_apis[d["hostapi"]]["name"]
    if d["max_input_channels"] == 0:
        continue
    if api_name not in ["Windows WASAPI", "MME", "ASIO"]:
        continue
    name_lower = d["name"].lower()
    if any(k in name_lower for k in EXCLUDE_KEYWORDS):
        continue
    if "focusrite" in name_lower and api_name != "ASIO":
        continue
    is_virtual = any(k in name_lower for k in VIRTUAL_KEYWORDS)
    max_ch = 4 if is_virtual else d["max_input_channels"]
    for ch in range(min(max_ch, d["max_input_channels"])):
        result.append({
            "device_index":       i,
            "name":               d["name"],
            "channel":            ch,
            "host_api":           api_name,
            "max_input_channels": d["max_input_channels"],
            "sample_rate":        int(d["default_samplerate"]),
            "latency":            round(d["default_low_input_latency"] * 1000, 2),
            "is_virtual":         is_virtual,
        })
print(json.dumps(result))
"#;

    match Command::new("python")
        .env("SD_ENABLE_ASIO", "1")
        .args(["-c", script])
        .output()
    {
        Ok(o)  => serde_json::from_str(String::from_utf8_lossy(&o.stdout).trim()).unwrap_or_default(),
        Err(e) => { eprintln!("[fetch_audio_devices_python] spawn failed: {}", e); vec![] }
    }
}

fn filter_audio_by_type(devices: &[Value], device_type: &str) -> Vec<Value> {
    devices.iter().filter(|d| {
        let is_virtual = d["is_virtual"].as_bool().unwrap_or(false);
        match device_type {
            "virtual" => is_virtual,
            "audio"   => !is_virtual,
            _         => true,  // "all"
        }
    }).cloned().collect()
}

#[tauri::command]
fn get_audio_devices(
    device_type:   String,
    force_refresh: Option<bool>,
    cache:         State<AudioDeviceCache>,
) -> Vec<Value> {
    let force = force_refresh.unwrap_or(false);

    if !force {
        let guard = cache.0.lock().unwrap();
        if let Some(ref all) = *guard {
            println!("[get_audio_devices] cache hit ({} entries, type={})", all.len(), device_type);
            return filter_audio_by_type(all, &device_type);
        }
    }

    println!("[get_audio_devices] spawning Python (force={})", force);
    let all = fetch_audio_devices_python();
    *cache.0.lock().unwrap() = Some(all.clone());
    filter_audio_by_type(&all, &device_type)
}


// Reconcile devices 
#[tauri::command]
fn reconcile_devices(_app: AppHandle) -> Result<Value, String> {
    let path = instruments_path()?;
    let mut config = read_config(&path)?;

    fn strip_midi_suffix(name: &str) -> &str {
        if let Some(pos) = name.rfind('-') {
            let suffix = &name[pos + 1..];
            if !suffix.is_empty() && suffix.chars().all(|c| c.is_ascii_digit()) {
                return name[..pos].trim_end();
            }
        }
        name
    }

    let live_audio: Vec<Value> = Command::new("python")
        .env("SD_ENABLE_ASIO", "1")
        .args([
            "-c",
            r#"
import json, sounddevice as sd
devices = sd.query_devices()
host_apis = sd.query_hostapis()
result = []
ALLOWED_APIS = ["Windows WASAPI", "Windows WDM-KS", "MME", "ASIO"]
for i, d in enumerate(devices):
    api_name = host_apis[d["hostapi"]]["name"]
    if d["max_input_channels"] == 0 or api_name not in ALLOWED_APIS:
        continue
    for ch in range(d["max_input_channels"]):
        result.append({"device_index": i, "name": d["name"], "channel": ch, "host_api": api_name})
print(json.dumps(result))
"#,
        ])
        .output()
        .map(|o| {
            serde_json::from_str(String::from_utf8_lossy(&o.stdout).trim()).unwrap_or_default()
        })
        .unwrap_or_default();

    let live_midi: Vec<Value> = Command::new("python")
        .args([
            "-c",
            r#"
import os, json
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame.midi
pygame.midi.init()
result = []
for i in range(pygame.midi.get_count()):
    info = pygame.midi.get_device_info(i)
    if info[2] == 1:
        result.append({"index": i, "name": info[1].decode('utf-8')})
print(json.dumps(result))
pygame.midi.quit()
"#,
        ])
        .output()
        .map(|o| {
            serde_json::from_str(String::from_utf8_lossy(&o.stdout).trim()).unwrap_or_default()
        })
        .unwrap_or_default();

    let instruments = config
        .get_mut("instruments")
        .and_then(|v| v.as_object_mut())
        .ok_or("instruments.json has no 'instruments' key")?;

    for (_, inst) in instruments.iter_mut() {
        let inst_obj = match inst.as_object_mut() {
            Some(o) => o,
            None => continue,
        };

        if let Some(dev) = inst_obj
            .get_mut("audio_device")
            .and_then(|v| v.as_object_mut())
        {
            let name = dev
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let channel = dev.get("channel").and_then(|v| v.as_i64()).unwrap_or(0);
            let host_api = dev
                .get("host_api")
                .and_then(|v| v.as_str())
                .unwrap_or("Windows WASAPI")
                .to_string();

            match live_audio.iter().find(|d| {
                d["name"].as_str().unwrap_or("") == name
                    && d["channel"].as_i64().unwrap_or(0) == channel
                    && d["host_api"].as_str().unwrap_or("") == host_api
            }) {
                Some(live) => {
                    if let Some(id) = live["device_index"].as_i64() {
                        dev.insert("device_id".to_string(), Value::Number(id.into()));
                    }
                    dev.insert("connected".to_string(), Value::Bool(true));
                }
                None => {
                    dev.insert("connected".to_string(), Value::Bool(false));
                }
            }
        }

        if let Some(dev) = inst_obj
            .get_mut("midi_device")
            .and_then(|v| v.as_object_mut())
        {
            let stored_name = dev
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let stored_base = strip_midi_suffix(&stored_name).to_string();

            match live_midi
                .iter()
                .find(|d| strip_midi_suffix(d["name"].as_str().unwrap_or("")) == stored_base)
            {
                Some(live) => {
                    let live_name = live["name"].as_str().unwrap_or(&stored_name).to_string();
                    dev.insert("name".to_string(), Value::String(live_name));
                    dev.insert("connected".to_string(), Value::Bool(true));
                }
                None => {
                    dev.insert("connected".to_string(), Value::Bool(false));
                }
            }
        }
    }

    write_config(&path, &config)?;
    Ok(Value::Object(config))
}



#[tauri::command]
fn get_midi_devices() -> Vec<Value> {
    let output = match Command::new("python")
        .args([
            "-c",
            r#"
import os, json
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame.midi
pygame.midi.init()
result = []
for i in range(pygame.midi.get_count()):
    info = pygame.midi.get_device_info(i)
    name = info[1].decode('utf-8')
    is_input = info[2]
    if is_input:
        result.append({"index": i, "name": name, "port": "input"})
print(json.dumps(result))
pygame.midi.quit()
"#,
        ])
        .output()
    {
        Ok(o) => o,
        Err(e) => {
            eprintln!("[get_midi_devices] {}", e);
            return vec![];
        }
    };
    serde_json::from_str(String::from_utf8_lossy(&output.stdout).trim()).unwrap_or_default()
}

// ─── TEST MIDI ────────────────────────────────────────────────────────────────

#[tauri::command]
fn test_midi_input(
    device_name: String,
    app: AppHandle,
    midi_state: State<MidiTestProcess>,
) -> Result<String, String> {
    if let Some(mut child) = midi_state.0.lock().unwrap().take() {
        let _ = child.kill();
    }

    let script = format!(
        r#"
import os, json, sys, time
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame.midi
pygame.midi.init()

NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
def note_name(n):
    return NOTE_NAMES[n % 12] + str(n // 12 - 1)

device_id = None
for i in range(pygame.midi.get_count()):
    info = pygame.midi.get_device_info(i)
    name = info[1].decode('utf-8')
    if info[2] == 1 and name == '{device_name}':
        device_id = i
        break

if device_id is None:
    print(json.dumps({{"error": "Device not found: {device_name}"}}), flush=True)
    sys.exit(1)

midi_in = pygame.midi.Input(device_id)
while True:
    if midi_in.poll():
        for event in midi_in.read(16):
            data = event[0]
            status = data[0] & 0xF0
            note = data[1]
            velocity = data[2]
            if status == 0x90 and velocity > 0:
                print(json.dumps({{"type": "note_on", "note": note_name(note), "velocity": velocity}}), flush=True)
            elif status == 0x80 or (status == 0x90 and velocity == 0):
                print(json.dumps({{"type": "note_off", "note": note_name(note), "velocity": 0}}), flush=True)
    time.sleep(0.01)
"#
    );

    let mut child = Command::new("python")
        .args(["-c", &script])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn MIDI listener: {}", e))?;

    let stdout = child.stdout.take().ok_or("No stdout")?;
    let stderr = child.stderr.take().ok_or("No stderr")?;
    *midi_state.0.lock().unwrap() = Some(child);

    thread::spawn(move || {
        for line in std::io::BufRead::lines(std::io::BufReader::new(stderr)) {
            if let Ok(line) = line {
                eprintln!("[test_midi_input stderr] {}", line);
            }
        }
    });

    thread::spawn(move || {
        for line in std::io::BufRead::lines(std::io::BufReader::new(stdout)) {
            if let Ok(line) = line {
                eprintln!("[test_midi_input stdout] {}", line);
                if let Ok(event) = serde_json::from_str::<Value>(&line) {
                    let _ = app.emit("midi-event", event);
                }
            }
        }
    });

    Ok("MIDI listener started".to_string())
}

#[tauri::command]
fn stop_midi_test(midi_state: State<MidiTestProcess>) -> Result<String, String> {
    if let Some(mut child) = midi_state.0.lock().unwrap().take() {
        child.kill().map_err(|e| format!("Failed to stop: {}", e))?;
    }
    Ok("MIDI listener stopped".to_string())
}

// ─── TEST AUDIO ───────────────────────────────────────────────────────────────

#[tauri::command]
fn test_device_audio(
    device_id: usize,
    channel: usize,
    app: AppHandle,
    test_state: State<TestProcess>,
) -> Result<String, String> {
    if let Some(mut child) = test_state.0.lock().unwrap().take() {
        let _ = child.kill();
    }

    let script = format!(
        r#"
import sounddevice as sd
import numpy as np

device_info = sd.query_devices({device_id}, 'input')
RATE = int(device_info['default_samplerate'])
CHUNK = int(RATE * 0.05)

def callback(indata, frames, time, status):
    channel_data = indata[:, {channel}]
    rms = float(np.sqrt(np.mean(channel_data ** 2)))
    normalized = min(rms * 20, 1.0)
    print(normalized, flush=True)

with sd.InputStream(
    device={device_id},
    channels={channel} + 1,
    samplerate=RATE,
    blocksize=CHUNK,
    callback=callback
):
    while True:
        sd.sleep(50)
"#
    );

    let mut child = Command::new("python")
        .env("SD_ENABLE_ASIO", "1")
        .args(["-c", &script])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn test stream: {}", e))?;

    let stdout = child.stdout.take().ok_or("No stdout")?;
    let stderr = child.stderr.take().ok_or("No stderr")?;
    *test_state.0.lock().unwrap() = Some(child);

    thread::spawn(move || {
        let reader = std::io::BufReader::new(stderr);
        for line in std::io::BufRead::lines(reader) {
            if let Ok(line) = line {
                eprintln!("[test_device_audio stderr] {}", line);
            }
        }
    });

    thread::spawn(move || {
        let reader = std::io::BufReader::new(stdout);
        for line in std::io::BufRead::lines(reader) {
            if let Ok(line) = line {
                if let Ok(level) = line.trim().parse::<f32>() {
                    let _ = app.emit("test-audio-level", level);
                }
            }
        }
    });

    Ok("Test stream started".to_string())
}

#[tauri::command]
fn stop_device_test(test_state: State<TestProcess>) -> Result<String, String> {
    if let Some(mut child) = test_state.0.lock().unwrap().take() {
        child
            .kill()
            .map_err(|e| format!("Failed to stop test: {}", e))?;
    }
    Ok("Test stream stopped".to_string())
}

// ─── PIPELINE TIER ────────────────────────────────────────────────────────────
//
// start_pipeline spawns only the 4 fast pipeline processes.
// The WSL receivers are already running from app startup — no sleeps needed.
//
// stop_pipeline kills only those same 4 processes + writes the broadcaster
// sentinel. The WSL receivers stay alive, keeping models warm in memory.

#[tauri::command]
fn start_pipeline(
    app: AppHandle,
    capture_state: State<CaptureProcess>,
    broadcaster_state: State<BroadcasterProcess>,
    windows_receiver_state: State<WindowsReceiverProcess>,
    midi_capture_state: State<MidiCaptureProcess>,
) -> Result<String, String> {
    let root = project_root_windows()?;

    // Guard: don't double-spawn if already running
    if capture_state.0.lock().unwrap().is_some() {
        println!("[Tauri] Pipeline already running — ignoring start.");
        return Ok("Already running".to_string());
    }

    // 1. windows_receiver.py — must be up before broadcaster connects
    {
        let script = root.join("backend/windows/windows_receiver.py");
        println!("[Tauri] Spawning windows_receiver.py...");
        let child = Command::new("python")
            .arg(&script)
            .spawn()
            .map_err(|e| format!("Failed to spawn windows_receiver.py: {}", e))?;
        *windows_receiver_state.0.lock().unwrap() = Some(child);
        println!("[Tauri] windows_receiver.py spawned.");
    }

    // 2. broadcaster.py
    {
        let script = root.join("backend/windows/broadcaster.py");
        println!("[Tauri] Spawning broadcaster.py...");
        let child = Command::new("python")
            .arg(&script)
            .spawn()
            .map_err(|e| format!("Failed to spawn broadcaster.py: {}", e))?;
        *broadcaster_state.0.lock().unwrap() = Some(child);
        println!("[Tauri] broadcaster.py spawned.");
    }

    // 3. capture.py
    {
        let script = root.join("backend/windows/capture.py");
        println!("[Tauri] Spawning capture.py...");
        let child = Command::new("python")
            .env("SD_ENABLE_ASIO", "1")
            .arg(&script)
            .spawn()
            .map_err(|e| format!("Failed to spawn capture.py: {}", e))?;
        *capture_state.0.lock().unwrap() = Some(child);
        println!("[Tauri] capture.py spawned.");
    }

    // 4. midi_capture.py
    {
        let script = root.join("backend/windows/midi_capture.py");
        println!("[Tauri] Spawning midi_capture.py...");
        let child = Command::new("python")
            .arg(&script)
            .spawn()
            .map_err(|e| format!("Failed to spawn midi_capture.py: {}", e))?;
        *midi_capture_state.0.lock().unwrap() = Some(child);
        println!("[Tauri] midi_capture.py spawned.");
    }

    // notify image gen processes that pipeline is now running
    {
        let socket = UdpSocket::bind("0.0.0.0:0").ok();
        if let Some(sock) = socket {
            fn build_osc(address: &str, value: i32) -> Vec<u8> {
                use rosc::{OscMessage, OscPacket, OscType};
                rosc::encoder::encode(&OscPacket::Message(OscMessage {
                    addr: address.to_string(),
                    args: vec![OscType::Int(value)],
                })).unwrap_or_default()
            }
            let msg = build_osc("/musinfo/pipeline_running", 1);
            let _ = sock.send_to(&msg, "127.0.0.1:9001");
            let _ = sock.send_to(&msg, "127.0.0.1:9002");
            println!("[Tauri] pipeline_running -> 1 sent to image gen processes");
        }
    }


    // Notify TouchDesigner to reset OSC state
    {
        let socket = UdpSocket::bind("0.0.0.0:0").ok();
        if let Some(sock) = socket {
            fn build_osc_reset(address: &str, value: i32) -> Vec<u8> {
                use rosc::{OscMessage, OscPacket, OscType};
                rosc::encoder::encode(&OscPacket::Message(OscMessage {
                    addr: address.to_string(),
                    args: vec![OscType::Int(value)],
                })).unwrap_or_default()
            }
            let _ = sock.send_to(&build_osc_reset("/musinfo/reset", 1), "127.0.0.1:9099");
            let _ = sock.send_to(&build_osc_reset("/musinfo/reset", 0), "127.0.0.1:9099");
            println!("[Tauri] /musinfo/reset pulse sent to TouchDesigner on port 9099");
        }
    }

    send_instrument_config_osc();
    
    app.emit("pipeline-ready", ())
        .unwrap_or_else(|e| eprintln!("[Tauri] emit error: {}", e));

    Ok("Pipeline started".to_string())
}

#[tauri::command]
fn stop_pipeline(
    capture_state: State<CaptureProcess>,
    broadcaster_state: State<BroadcasterProcess>,
    windows_receiver_state: State<WindowsReceiverProcess>,
    midi_capture_state: State<MidiCaptureProcess>,
) -> Result<String, String> {
    PIPELINE_RUNNING.store(false, Ordering::SeqCst);

    // notify image gen processes that pipeline has stopped
    {
        let socket = UdpSocket::bind("0.0.0.0:0").ok();
        if let Some(sock) = socket {
            fn build_osc(address: &str, value: i32) -> Vec<u8> {
                use rosc::{OscMessage, OscPacket, OscType};
                rosc::encoder::encode(&OscPacket::Message(OscMessage {
                    addr: address.to_string(),
                    args: vec![OscType::Int(value)],
                })).unwrap_or_default()
            }
            let msg = build_osc("/musinfo/pipeline_running", 0);
            let _ = sock.send_to(&msg, "127.0.0.1:9001");
            let _ = sock.send_to(&msg, "127.0.0.1:9002");
            println!("[Tauri] pipeline_running -> 0 sent to image gen processes");
        }
    }

    // Notify TouchDesigner to reset OSC state
    {
        let socket = UdpSocket::bind("0.0.0.0:0").ok();
        if let Some(sock) = socket {
            fn build_osc_reset(address: &str, value: i32) -> Vec<u8> {
                use rosc::{OscMessage, OscPacket, OscType};
                rosc::encoder::encode(&OscPacket::Message(OscMessage {
                    addr: address.to_string(),
                    args: vec![OscType::Int(value)],
                })).unwrap_or_default()
            }
            let _ = sock.send_to(&build_osc_reset("/musinfo/reset", 1), "127.0.0.1:9099");
            let _ = sock.send_to(&build_osc_reset("/musinfo/reset", 0), "127.0.0.1:9099");
            println!("[Tauri] /musinfo/reset pulse sent to TouchDesigner on port 9099");
        }
    }
    

    // Disable image gen when pipeline stops
    {
        let socket = UdpSocket::bind("0.0.0.0:0").ok();
        if let Some(sock) = socket {
            fn build_osc_img(address: &str, value: i32) -> Vec<u8> {
                use rosc::{OscMessage, OscPacket, OscType};
                rosc::encoder::encode(&OscPacket::Message(OscMessage {
                    addr: address.to_string(),
                    args: vec![OscType::Int(value)],
                })).unwrap_or_default()
            }
            let msg = build_osc_img("/musinfo/image_gen_enabled", 0);
            let _ = sock.send_to(&msg, "127.0.0.1:9001");
            let _ = sock.send_to(&msg, "127.0.0.1:9002");
            println!("[Tauri] image_gen_enabled -> 0 sent to image gen processes");
        }
    }
    let root = project_root_windows()?;

    // Kill capture first — stops audio flowing into broadcaster
    if let Some(mut child) = capture_state.0.lock().unwrap().take() {
        let _ = child.kill();
        println!("[Tauri] capture.py stopped.");
    }

    // Kill midi_capture
    if let Some(mut child) = midi_capture_state.0.lock().unwrap().take() {
        let _ = child.kill();
        println!("[Tauri] midi_capture.py stopped.");
    }

    // Write stop sentinel — gives broadcaster a moment to flush/save state
    let sentinel = root.join("backend/broadcaster.stop");
    if let Err(e) = fs::write(&sentinel, b"stop") {
        eprintln!("[Tauri] Failed to write stop sentinel: {}", e);
    } else {
        println!("[Tauri] Stop sentinel written — waiting for broadcaster to flush...");
        std::thread::sleep(std::time::Duration::from_millis(1500));
    }

    // Kill broadcaster
    if let Some(mut child) = broadcaster_state.0.lock().unwrap().take() {
        let _ = child.kill();
        println!("[Tauri] broadcaster.py stopped.");
    }

    // Kill windows_receiver last — it may still be processing the final frames
    if let Some(mut child) = windows_receiver_state.0.lock().unwrap().take() {
        let _ = child.kill();
        println!("[Tauri] windows_receiver.py stopped.");
    }

    // WSL receivers stay alive — models remain loaded for next start.
    println!("[Tauri] Pipeline stopped. WSL receivers remain warm.");

    Ok("Pipeline stopped".to_string())
}

// ─── OSC LISTENER ─────────────────────────────────────────────────────────────

fn start_osc_listener(app_handle: AppHandle) {
    thread::spawn(move || {
        let socket = UdpSocket::bind("0.0.0.0:9000")
            .expect("[OSC] Failed to bind UDP socket on port 9000");
        println!("[OSC] Listening for OSC messages on port 9000...");

        let mut buf = [0u8; 1024];
        loop {
            match socket.recv_from(&mut buf) {
                Ok((size, addr)) => {
                    if OSC_DEBUG {
                        println!("[OSC] Packet from {} ({} bytes)", addr, size);
                    }
                    match decode_udp(&buf[..size]) {
                        Ok((_, OscPacket::Message(msg))) => {
                            if OSC_DEBUG {
                                println!("[OSC] {}: {:?}", msg.addr, msg.args);
                            }
                            let payload = msg
                                .args
                                .first()
                                .map(|a| match a {
                                    rosc::OscType::String(s) => s.clone(),
                                    rosc::OscType::Float(f) => f.to_string(),
                                    rosc::OscType::Double(d) => d.to_string(),
                                    rosc::OscType::Int(i) => i.to_string(),
                                    _ => String::new(),
                                })
                                .unwrap_or_default();

                            let osc_data = serde_json::json!({
                                "address": msg.addr,
                                "payload": payload
                            });

                            app_handle
                                .emit("osc-message", osc_data)
                                .unwrap_or_else(|e| eprintln!("[OSC] emit error: {}", e));
                        }
                        Ok(_) => {}
                        Err(e) => eprintln!("[OSC] Decode error: {}", e),
                    }
                }
                Err(e) => eprintln!("[OSC] Socket error: {}", e),
            }
        }
    });
}

// ─── SESSIONS ─────────────────────────────────────────────────────────────────

#[tauri::command]
async fn save_session(app: AppHandle) -> Result<String, String> {
    use tauri_plugin_dialog::DialogExt;

    let sessions_dir = sessions_path()?;
    if !sessions_dir.exists() {
        fs::create_dir_all(&sessions_dir)
            .map_err(|e| format!("Failed to create sessions dir: {}", e))?;
    }

    let src = instruments_path()?;
    let contents = fs::read_to_string(&src)
        .map_err(|e| format!("Failed to read instruments.json: {}", e))?;

    let default_name = next_session_name(&sessions_dir);

    let path = app
        .dialog()
        .file()
        .set_title("Save Session")
        .add_filter("JSON", &["json"])
        .set_directory(&sessions_dir)
        .set_file_name(format!("{}.json", default_name))
        .blocking_save_file();

    let Some(path) = path else {
        return Ok("cancelled".to_string());
    };

    let path = path
        .into_path()
        .map_err(|e| format!("Invalid path: {}", e))?;

    fs::write(&path, contents).map_err(|e| format!("Failed to write session file: {}", e))?;

    menu::rebuild_menu(&app)?;
    Ok("saved".to_string())
}

fn next_session_name(sessions_dir: &Path) -> String {
    let mut i = 1;
    loop {
        let candidate = format!("session{}.json", i);
        if !sessions_dir.join(&candidate).exists() {
            return format!("session{}", i);
        }
        i += 1;
    }
}

#[tauri::command]
async fn load_session(app: AppHandle, name: String) -> Result<Option<Value>, String> {
    let sessions_dir = sessions_path()?;
    let path = sessions_dir.join(format!("{}.json", name));

    let contents = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read session file: {}", e))?;
    let config: serde_json::Map<String, Value> = serde_json::from_str(&contents)
        .map_err(|e| format!("Invalid session file: {}", e))?;

    if !config.contains_key("instruments") {
        return Err("File does not look like a MUSINFO session".to_string());
    }

    let dest = instruments_path()?;
    write_config(&dest, &config)?;

    drop(config);
    let reconciled = reconcile_devices(app)?;
    Ok(Some(reconciled))
}

#[tauri::command]
fn list_sessions() -> Result<Vec<String>, String> {
    let sessions_dir = sessions_path()?;
    if !sessions_dir.exists() {
        return Ok(vec![]);
    }

    let mut names = vec![];
    for entry in
        fs::read_dir(&sessions_dir).map_err(|e| format!("Failed to read sessions dir: {}", e))?
    {
        let entry = entry.map_err(|e| format!("Failed to read entry: {}", e))?;
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("json") {
            if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                names.push(stem.to_string());
            }
        }
    }

    names.sort();
    Ok(names)
}

// ─── APP ENTRY POINT ──────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        // Pipeline tier — killed/restarted freely
        .manage(CaptureProcess(Mutex::new(None)))
        .manage(MidiCaptureProcess(Mutex::new(None)))
        .manage(BroadcasterProcess(Mutex::new(None)))
        .manage(WindowsReceiverProcess(Mutex::new(None)))
        // Persistent tier — survive stop/start, killed only on exit
        .manage(WslProcess(Mutex::new(None)))
        .manage(WslHeavyProcess(Mutex::new(None)))
        // image generation processes
        .manage(PromptGeneratorProcess(Mutex::new(None)))  
        .manage(ImageGenProcess(Mutex::new(None)))          
        // Test processes
        .manage(TestProcess(Mutex::new(None)))
        .manage(MidiTestProcess(Mutex::new(None)))
        .manage(AudioDeviceCache(Mutex::new(None)))
        .setup(|app| {
            let menu = menu::build_menu(&app.handle())?;
            app.set_menu(menu)?;

            start_osc_listener(app.handle().clone());

            let wsl_state       = app.state::<WslProcess>();
            let wsl_heavy_state = app.state::<WslHeavyProcess>();
            let prompt_gen      = app.state::<PromptGeneratorProcess>();
            let image_gen       = app.state::<ImageGenProcess>();

            if let Err(e) = spawn_persistent_processes(&wsl_state, &wsl_heavy_state, &prompt_gen, &image_gen) {
                eprintln!("[Tauri] Warning: failed to spawn persistent processes: {}", e);
            }
            
            send_instrument_config_osc();


            // Pre-warm the audio device cache in a background thread.
            // The Python+ASIO spawn (~500ms, causes one audio glitch) happens here,
            // before the UI renders, so get_audio_devices calls from AudioDevicesConfig
            // always hit the cache instantly.
            let app_handle = app.handle().clone();
            thread::spawn(move || {
                println!("[Tauri] Pre-warming audio device cache...");
                let devices = fetch_audio_devices_python();
                println!("[Tauri] Audio device cache ready ({} entries)", devices.len());
                let cache = app_handle.state::<AudioDeviceCache>();
                *cache.0.lock().unwrap() = Some(devices);
            });
        
            Ok(())
        })
        .on_menu_event(menu::handle_menu_event)
        // Kill persistent processes when the main window closes
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let app = window.app_handle();
                let wsl = app.state::<WslProcess>();
                let wsl_heavy = app.state::<WslHeavyProcess>();
                let prompt_gen = app.state::<PromptGeneratorProcess>();
                let image_gen  = app.state::<ImageGenProcess>();
                kill_persistent_processes(&wsl, &wsl_heavy, &prompt_gen, &image_gen);
                println!("[Tauri] App closing — persistent processes killed.");
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_audio_devices,
            get_midi_devices,
            start_pipeline,
            stop_pipeline,
            test_device_audio,
            stop_device_test,
            test_midi_input,
            stop_midi_test,
            save_instrument,
            delete_instrument,
            reconcile_devices,
            save_session,
            load_session,
            list_sessions,
            save_performance_config,
            toggle_image_generation,  
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}