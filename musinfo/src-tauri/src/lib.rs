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
use tauri::{AppHandle, Emitter, State};

// holds the test audio state
struct TestProcess(Mutex<Option<Child>>);

// holds the test midi state
struct MidiTestProcess(Mutex<Option<Child>>);

// holds the capture.py process handle so stop_pipeline can kill it
struct CaptureProcess(Mutex<Option<Child>>);

// holds the wsl_receiver.py process handle so stop_pipeline can kill it
struct WslProcess(Mutex<Option<Child>>);

// holds the broadcaster.py process handle so stop_pipeline can kill it
struct BroadcasterProcess(Mutex<Option<Child>>);

// holds the windows_receiver.py process handle so stop_pipeline can kill it
struct WindowsReceiverProcess(Mutex<Option<Child>>);

// HELPER FUNCTIONS

// Resolves the path to instruments.json relative to the project root.
fn instruments_path() -> Result<std::path::PathBuf, String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?;
    Ok(root.join("backend/config/instruments.json"))
}

// Reads and parses instruments.json into a mutable JSON map.
fn read_config(path: &Path) -> Result<serde_json::Map<String, Value>, String> {
    let raw = fs::read_to_string(path).map_err(|e| format!("Failed to read: {}", e))?;
    serde_json::from_str(&raw).map_err(|e| format!("Failed to parse: {}", e))
}

// Serializes the config map and writes it back to disk with pretty formatting.
fn write_config(path: &Path, config: &serde_json::Map<String, Value>) -> Result<(), String> {
    let out =
        serde_json::to_string_pretty(config).map_err(|e| format!("Serialize error: {}", e))?;
    fs::write(path, out).map_err(|e| format!("Write error: {}", e))
}

// INSTRUMENTS

//  Save instrument configuration to instruments.json.
#[tauri::command]
fn save_instrument(_app: AppHandle, instrument: Value) -> Result<String, String> {
    // resolve path to instruments.json relative to the project root
    let project_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?;

    let config_path = project_root.join("backend/config/instruments.json");

    // read existing file
    let raw = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read instruments.json: {}", e))?;

    let mut config: serde_json::Map<String, Value> = serde_json::from_str(&raw)
        .map_err(|e| format!("Failed to parse instruments.json: {}", e))?;

    // extract name from instrument, use it as the key
    let name = instrument["name"]
        .as_str()
        .ok_or("Instrument has no name")?
        .to_string();

    // build the entry without the name field (name is the key, not a field)
    let mut entry = instrument.clone();
    if let Some(obj) = entry.as_object_mut() {
        obj.remove("name");
    }

    // insert into instruments map
    let instruments = config
        .get_mut("instruments")
        .and_then(|v| v.as_object_mut())
        .ok_or("instruments.json has no 'instruments' key")?;

    instruments.insert(name, entry);

    // write back with pretty formatting
    let output =
        serde_json::to_string_pretty(&config).map_err(|e| format!("Failed to serialize: {}", e))?;

    fs::write(&config_path, output)
        .map_err(|e| format!("Failed to write instruments.json: {}", e))?;

    Ok("Instrument saved".to_string())
}

// Removes an instrument entry by key
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
    Ok("Instrument deleted".to_string())
}

// AUDIO DEVICES

// rematches device id with name and channel, since device_id can change
#[tauri::command]
fn reconcile_devices(_app: AppHandle) -> Result<Value, String> {
    let path = instruments_path()?;
    let mut config = read_config(&path)?;

    // strips Windows MME port suffix so "Digital Piano-2" matches "Digital Piano-1"
    fn strip_midi_suffix(name: &str) -> &str {
        if let Some(pos) = name.rfind('-') {
            let suffix = &name[pos + 1..];
            if !suffix.is_empty() && suffix.chars().all(|c| c.is_ascii_digit()) {
                return name[..pos].trim_end();
            }
        }
        name
    }

    // query live audio devices
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

    // query live MIDI devices
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

        // audio reconcile — exact match on name + channel + host_api
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

        // midi reconcile — fuzzy match on base name (strips trailing -N suffix)
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

// Runs a Python script to query all available audio devices on the system and filter them by type.
#[tauri::command]
fn get_audio_devices(device_type: String) -> Vec<Value> {
    let python_script = format!(
        r#"
import json, sounddevice as sd
devices = sd.query_devices()
host_apis = sd.query_hostapis()
result = []
VIRTUAL_KEYWORDS = ["vb", "virtual", "cable", "voicemeeter"]

for i, d in enumerate(devices):
    api_name = host_apis[d["hostapi"]]["name"]
    if d["max_input_channels"] == 0:
        continue
    if api_name not in ["Windows WASAPI", "Windows WDM-KS", "MME", "ASIO"]:
        continue

    name_lower = d["name"].lower()
    is_virtual = any(k in name_lower for k in VIRTUAL_KEYWORDS)

    # Filter by device type (unless "all")
    if "{device_type}" != "all":
        if "{device_type}" == "virtual" and not is_virtual:
            continue
        if "{device_type}" == "audio" and is_virtual:
            continue
    
    # Limit virtual devices to 4 channels, show all channels for real devices
    max_channels_to_show = 4 if is_virtual else d["max_input_channels"]

    # one entry per input channel
    for ch in range(min(max_channels_to_show, d["max_input_channels"])):
        result.append({{
            "device_index": i,
            "name": d["name"],
            "channel": ch,
            "host_api": api_name,
            "max_input_channels": d["max_input_channels"],
            "sample_rate": int(d["default_samplerate"]),
            "latency": round(d["default_low_input_latency"] * 1000, 2),
        }})
        
print(json.dumps(result))
"#
    );

    let output = match Command::new("python")
        .env("SD_ENABLE_ASIO", "1")
        .args(["-c", &python_script])
        .output()
    {
        Ok(o) => o,
        Err(e) => {
            eprintln!("[get_audio_devices] Failed to spawn python: {}", e);
            return vec![];
        }
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str(stdout.trim()).unwrap_or_default()
}

// Runs a Python script to query all available MIDI input devices on the system.
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

// TEST MIDI

// Spawns a Python script that listens to a MIDI input device and emits events.
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
                eprintln!("[test_midi_input stdout] {}", line); // ← add
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

// TEST AUDIO

#[tauri::command]
fn test_device_audio(
    device_id: usize,
    channel: usize,
    app: AppHandle,
    test_state: State<TestProcess>,
) -> Result<String, String> {
    // kill any existing test stream first
    if let Some(mut child) = test_state.0.lock().unwrap().take() {
        let _ = child.kill();
    }

    let script = format!(
        r#"
import sounddevice as sd
import numpy as np

# query the device's default sample rate
device_info = sd.query_devices({device_id}, 'input')
RATE = int(device_info['default_samplerate'])
CHUNK = int(RATE * 0.05) # 50ms buffer

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

    // take stdout before moving child into state
    let stdout = child.stdout.take().ok_or("No stdout")?;
    let stderr = child.stderr.take().ok_or("No stderr")?;
    *test_state.0.lock().unwrap() = Some(child);

    // log stderr in a separate thread so you can see Python errors
    thread::spawn(move || {
        let reader = std::io::BufReader::new(stderr);
        for line in std::io::BufRead::lines(reader) {
            if let Ok(line) = line {
                eprintln!("[test_device_audio stderr] {}", line);
            }
        }
    });

    // read stdout in background thread, emit each RMS value as an event
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

// AUDIO PIPELINE

// spawns the full audio pipeline in order: wsl_receiver -> windows_receiver -> broadcaster -> capture
#[tauri::command]
fn start_pipeline(
    capture_state: State<CaptureProcess>,
    wsl_state: State<WslProcess>,
    broadcaster_state: State<BroadcasterProcess>,
    windows_receiver_state: State<WindowsReceiverProcess>,
) -> Result<String, String> {
    let project_root_windows = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?;

    let project_root_wsl = project_root_windows
        .to_string_lossy()
        .replace("C:\\", "/mnt/c/")
        .replace("\\", "/")
        .to_lowercase();

    // --- 1. Spawn wsl_receiver.py inside WSL ---
    let wsl_script = format!("{}/backend/wsl/wsl_receiver.py", project_root_wsl);
    let bash_cmd = format!(
        "source {}/backend/wsl/.venv/bin/activate && python3 {}",
        project_root_wsl, wsl_script
    );

    println!("[Tauri] Spawning wsl_receiver.py...");

    let wsl_child = Command::new("wsl")
        .args(["-d", "Ubuntu", "/bin/bash", "-c", &bash_cmd])
        // REMOVED: .stdout(Stdio::null())
        // REMOVED: .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to spawn wsl_receiver.py: {}", e))?;

    *wsl_state.0.lock().unwrap() = Some(wsl_child);
    println!("[Tauri] wsl_receiver.py spawned.");

    std::thread::sleep(std::time::Duration::from_millis(1500));

    // --- 2. Spawn windows_receiver.py on Windows ---
    let windows_receiver_script = project_root_windows.join("backend/windows/windows_receiver.py");

    println!("[Tauri] Spawning windows_receiver.py...");

    let windows_receiver_child = Command::new("python")
        .arg(&windows_receiver_script)
        // REMOVED: .stdout(Stdio::null())
        // REMOVED: .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to spawn windows_receiver.py: {}", e))?;

    *windows_receiver_state.0.lock().unwrap() = Some(windows_receiver_child);
    println!("[Tauri] windows_receiver.py spawned.");

    std::thread::sleep(std::time::Duration::from_millis(500));

    // --- 3. Spawn broadcaster.py on Windows ---
    let broadcaster_script = project_root_windows.join("backend/windows/broadcaster.py");

    println!("[Tauri] Spawning broadcaster.py...");

    let broadcaster_child = Command::new("python")
        .arg(&broadcaster_script)
        // REMOVED: .stdout(Stdio::null())
        // REMOVED: .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to spawn broadcaster.py: {}", e))?;

    *broadcaster_state.0.lock().unwrap() = Some(broadcaster_child);
    println!("[Tauri] broadcaster.py spawned.");

    std::thread::sleep(std::time::Duration::from_millis(500));

    // --- 4. Spawn capture.py on Windows ---
    let capture_script = project_root_windows.join("backend/windows/capture.py");

    println!("[Tauri] Spawning capture.py...");

    let capture_child = Command::new("python")
        .env("SD_ENABLE_ASIO", "1")
        .arg(&capture_script)
        // REMOVED: .stdout(Stdio::null())
        // REMOVED: .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to spawn capture.py: {}", e))?;

    *capture_state.0.lock().unwrap() = Some(capture_child);
    println!("[Tauri] capture.py spawned.");

    Ok("Pipeline started".to_string())
}

// kills all pipeline processes in reverse order: capture -> broadcaster -> windows_receiver -> wsl_receiver
#[tauri::command]
fn stop_pipeline(
    capture_state: State<CaptureProcess>,
    wsl_state: State<WslProcess>,
    broadcaster_state: State<BroadcasterProcess>,
    windows_receiver_state: State<WindowsReceiverProcess>,
) -> Result<String, String> {
    let project_root_windows = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?;

    // if capture.py is running, kill it
    if let Some(mut child) = capture_state.0.lock().unwrap().take() {
        child
            .kill()
            .map_err(|e| format!("Failed to kill capture.py: {}", e))?;
        println!("[Tauri] capture.py stopped.");
    }

    let sentinel_path = project_root_windows
        .join("backend")
        .join("broadcaster.stop");

    if let Err(e) = fs::write(&sentinel_path, b"stop") {
        eprintln!("[Tauri] Failed to write stop sentinel: {}", e);
    } else {
        println!("[Tauri] Stop sentinel written — waiting for broadcaster to save...");
        std::thread::sleep(std::time::Duration::from_millis(1500)); // give it time to save
    }

    // if broadcaster.py is running, kill it
    if let Some(mut child) = broadcaster_state.0.lock().unwrap().take() {
        child
            .kill()
            .map_err(|e| format!("Failed to kill broadcaster.py: {}", e))?;
        println!("[Tauri] broadcaster.py stopped.");
    }

    // if windows_receiver.py is running, kill it
    if let Some(mut child) = windows_receiver_state.0.lock().unwrap().take() {
        child
            .kill()
            .map_err(|e| format!("Failed to kill windows_receiver.py: {}", e))?;
        println!("[Tauri] windows_receiver.py stopped.");
    }

    // if wsl_receiver.py is running, kill it
    if let Some(mut child) = wsl_state.0.lock().unwrap().take() {
        child
            .kill()
            .map_err(|e| format!("Failed to kill wsl_receiver.py: {}", e))?;
        println!("[Tauri] receiver.py stopped.");
    }

    Ok("Pipeline stopped".to_string())
}

/// Spawns a background thread that listens for incoming OSC messages from WSL.
/// When a message arrives, it emits a Tauri event that the frontend can subscribe to.
fn start_osc_listener(app_handle: AppHandle) {
    thread::spawn(move || {
        let socket =
            UdpSocket::bind("0.0.0.0:9000").expect("[OSC] Failed to bind UDP socket on port 9000");

        println!("[OSC] Listening for OSC messages on port 9000...");

        let mut buf = [0u8; 1024];

        loop {
            match socket.recv_from(&mut buf) {
                Ok((size, addr)) => {
                    println!("[OSC] Packet received from {} ({} bytes)", addr, size);

                    match decode_udp(&buf[..size]) {
                        Ok((_, OscPacket::Message(msg))) => {
                            println!("[OSC] Address: {}, Args: {:?}", msg.addr, msg.args);

                            // Extract the message payload
                            let payload = msg
                                .args
                                .first()
                                .and_then(|a| {
                                    if let rosc::OscType::String(s) = a {
                                        Some(s.clone())
                                    } else {
                                        None
                                    }
                                })
                                .unwrap_or_default();

                            // Send BOTH address and payload as JSON
                            let osc_data = serde_json::json!({
                                "address": msg.addr,
                                "payload": payload
                            });

                            app_handle
                                .emit("osc-message", osc_data)
                                .unwrap_or_else(|e| eprintln!("[OSC] Failed to emit event: {}", e));
                        }
                        Ok(_) => println!("[OSC] Received OSC bundle (ignored for now)"),
                        Err(e) => eprintln!("[OSC] Decode error: {}", e),
                    }
                }
                Err(e) => eprintln!("[OSC] Socket error: {}", e),
            }
        }
    });
}


#[tauri::command]
async fn save_session(app: AppHandle) -> Result<String, String> {
    use tauri_plugin_dialog::DialogExt;

    // read current instruments.json
    let src = instruments_path()?;
    let contents = fs::read_to_string(&src)
        .map_err(|e| format!("Failed to read instruments.json: {}", e))?;

    // open a native save dialog
    let path = app
        .dialog()
        .file()
        .set_title("Save Session")
        .add_filter("JSON", &["json"])
        .blocking_save_file();

    // user cancelled
    let Some(path) = path else {
        return Ok("cancelled".to_string());
    };

    fs::write(path.into_path().map_err(|e| format!("Invalid path: {}", e))?, contents)
    .map_err(|e| format!("Failed to write session file: {}", e))?;

    Ok("saved".to_string())
}


#[tauri::command]
async fn load_session(app: AppHandle) -> Result<Option<Value>, String> {
    use tauri_plugin_dialog::DialogExt;

    // open a native open dialog
    let path = app
        .dialog()
        .file()
        .set_title("Load Session")
        .add_filter("JSON", &["json"])
        .blocking_pick_file();

    // user cancelled — return None, React checks for this
    let Some(path) = path else {
        return Ok(None);
    };

    // read and validate the chosen file
    let contents = fs::read_to_string(path.into_path().map_err(|e| format!("Invalid path: {}", e))?)
    .map_err(|e| format!("Failed to read session file: {}", e))?;

    let config: serde_json::Map<String, Value> = serde_json::from_str(&contents)
        .map_err(|e| format!("Invalid session file: {}", e))?;

    // basic sanity check — must have an instruments key
    if !config.contains_key("instruments") {
        return Err("File does not look like a MUSINFO session".to_string());
    }

    // overwrite instruments.json with the loaded config
    let dest = instruments_path()?;
    write_config(&dest, &config)?;

    // run reconcile so device_ids are resolved for this machine
    // we call reconcile_devices logic directly rather than re-invoking
    drop(config); // reconcile reads from disk
    let reconciled = reconcile_devices(app)?;

    Ok(Some(reconciled))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(CaptureProcess(Mutex::new(None)))
        .manage(TestProcess(Mutex::new(None)))
        .manage(MidiTestProcess(Mutex::new(None)))
        .manage(WslProcess(Mutex::new(None)))
        .manage(WindowsReceiverProcess(Mutex::new(None)))
        .manage(BroadcasterProcess(Mutex::new(None)))
        .setup(|app| {
            // build and attach the native menu
            let menu = menu::build_menu(&app.handle())?;
            app.set_menu(menu)?;

            // start OSC listener
            start_osc_listener(app.handle().clone());

            Ok(())
        })
        .on_menu_event(menu::handle_menu_event)
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
