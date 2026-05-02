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
fn save_instrument(app: AppHandle, instrument: Value) -> Result<String, String> {
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
    if api_name != "Windows WASAPI":
        continue

    name_lower = d["name"].lower()
    is_virtual = any(k in name_lower for k in VIRTUAL_KEYWORDS)

    if "{device_type}" == "virtual" and not is_virtual:
        continue
    if "{device_type}" == "audio" and is_virtual:
        continue
    
    # one entry per input channel
    for ch in range(d["max_input_channels"]):
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

    let output = match Command::new("python").args(["-c", &python_script]).output() {
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
import json, rtmidi
m = rtmidi.MidiIn()
ports = m.get_ports()
result = [{"index": i, "name": p} for i, p in enumerate(ports)]
print(json.dumps(result))
"#,
        ])
        .output()
    {
        Ok(o) => o,
        Err(e) => {
            eprintln!("[get_midi_devices] Failed to spawn python: {}", e);
            return vec![];
        }
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str(stdout.trim()).unwrap_or_default()
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

// spawns the full audio pipeline in order: wsl_receiver → windows_receiver → broadcaster → capture
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
        .stdout(Stdio::null())
        .stderr(Stdio::null())
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
        .stdout(Stdio::null())
        .stderr(Stdio::null())
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
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to spawn broadcaster.py: {}", e))?;

    *broadcaster_state.0.lock().unwrap() = Some(broadcaster_child);
    println!("[Tauri] broadcaster.py spawned.");

    std::thread::sleep(std::time::Duration::from_millis(500));

    // --- 4. Spawn capture.py on Windows ---
    let capture_script = project_root_windows.join("backend/windows/capture.py");

    println!("[Tauri] Spawning capture.py...");

    let capture_child = Command::new("python")
        .arg(&capture_script)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to spawn capture.py: {}", e))?;

    *capture_state.0.lock().unwrap() = Some(capture_child);
    println!("[Tauri] capture.py spawned.");

    Ok("Pipeline started".to_string())
}

// kills all pipeline processes in reverse order: capture → broadcaster → windows_receiver → wsl_receiver
#[tauri::command]
fn stop_pipeline(
    capture_state: State<CaptureProcess>,
    wsl_state: State<WslProcess>,
    broadcaster_state: State<BroadcasterProcess>,
    windows_receiver_state: State<WindowsReceiverProcess>,
) -> Result<String, String> {
    // if capture.py is running, kill it
    if let Some(mut child) = capture_state.0.lock().unwrap().take() {
        child
            .kill()
            .map_err(|e| format!("Failed to kill capture.py: {}", e))?;
        println!("[Tauri] capture.py stopped.");
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
                    println!("[OSC] Packet received from {}", addr);

                    match decode_udp(&buf[..size]) {
                        Ok((_, OscPacket::Message(msg))) => {
                            println!("[OSC] Address: {}, Args: {:?}", msg.addr, msg.args);

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
                                .unwrap_or_else(|| msg.addr.clone());

                            app_handle
                                .emit("osc-message", payload)
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(CaptureProcess(Mutex::new(None)))
        .manage(TestProcess(Mutex::new(None)))
        .manage(WslProcess(Mutex::new(None)))
        .manage(WindowsReceiverProcess(Mutex::new(None)))
        .manage(BroadcasterProcess(Mutex::new(None)))
        .setup(|app| {
            start_osc_listener(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_audio_devices,
            get_midi_devices,
            start_pipeline,
            stop_pipeline,
            test_device_audio,
            stop_device_test,
            save_instrument,
            delete_instrument
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
