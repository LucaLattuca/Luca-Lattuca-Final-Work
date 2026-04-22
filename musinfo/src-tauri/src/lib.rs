use rosc::decoder::decode_udp;
use rosc::OscPacket;
use serde_json::Value;
use std::fs::File;
use std::net::UdpSocket;
use std::path::Path;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use tauri::{AppHandle, Emitter, State};

// Holds the capture.py process handle so stop_capture can kill it later
struct CaptureProcess(Mutex<Option<Child>>);
// start wsl process
struct WslProcess(Mutex<Option<Child>>);

/// Runs a Python script to query all available audio devices on the system.
#[tauri::command]
fn get_audio_devices() -> Vec<Value> {
    let output = match Command::new("python")
        .args([
            "-c",
            r#"
import json, sounddevice as sd
devices = sd.query_devices()
host_apis = sd.query_hostapis()
result = []
for i, d in enumerate(devices):
    api_name = host_apis[d["hostapi"]]["name"]
    if d["max_input_channels"] == 0:
        continue
    if api_name != "Windows WASAPI":
        continue
    result.append({
        "index": i,
        "name": d["name"],
        "host_api": host_apis[d["hostapi"]]["name"],
        "max_input_channels": d["max_input_channels"],
        "max_output_channels": d["max_output_channels"],
        "default_sample_rate": d["default_samplerate"],
    })
print(json.dumps(result))
"#,
        ])
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

/// Spawns capture.py as a background process and stores the handle.
/// Uses .spawn() instead of .output() so it returns immediately.
#[tauri::command]
fn start_capture(
    capture_state: State<CaptureProcess>,
    wsl_state: State<WslProcess>,
) -> Result<String, String> {
    // --- 1. Build paths ---
    let project_root_windows = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?;

    // Convert Windows path → WSL path (C:\foo\bar → /mnt/c/foo/bar)
    let project_root_wsl = project_root_windows
        .to_string_lossy()
        .replace("C:\\", "/mnt/c/")
        .replace("\\", "/")
        .to_lowercase();

    let wsl_script = format!("{}/backend/wsl/receiver.py", project_root_wsl);
    let bash_cmd = format!(
        "source {}/backend/wsl/.venv/bin/activate && python3 {}",
        project_root_wsl, wsl_script
    );

    println!("[Tauri] WSL script: {}", wsl_script);

    // --- 3. Spawn receiver.py inside WSL (Ubuntu) ---
    let wsl_child = Command::new("wsl")
        .args(["-d", "Ubuntu", "/bin/bash", "-c", &bash_cmd])
        .stdout(log_file.try_clone().unwrap())
        .stderr(log_file)
        .spawn()
        .map_err(|e| format!("Failed to spawn receiver.py in WSL: {}", e))?;

    *wsl_state.0.lock().unwrap() = Some(wsl_child);
    println!("[Tauri] receiver.py spawned in WSL.");

    // Give receiver.py time to bind its socket before capture.py connects
    std::thread::sleep(std::time::Duration::from_millis(1500));

    // --- 4. Spawn capture.py on Windows ---
    let capture_script = project_root_windows.join("backend/windows/capture.py");
    let child = Command::new("python")
        .arg(&capture_script)
        .spawn()
        .map_err(|e| format!("Failed to spawn capture.py: {}", e))?;

    *capture_state.0.lock().unwrap() = Some(child);
    println!("[Tauri] capture.py spawned.");

    Ok("Capture started".to_string())
}

/// Kills the running capture.py process.
#[tauri::command]
fn stop_capture(
    capture_state: State<CaptureProcess>,
    wsl_state: State<WslProcess>,
) -> Result<String, String> {
    if let Some(mut child) = capture_state.0.lock().unwrap().take() {
        child
            .kill()
            .map_err(|e| format!("Failed to kill capture.py: {}", e))?;
        println!("[Tauri] capture.py stopped.");
    }

    if let Some(mut child) = wsl_state.0.lock().unwrap().take() {
        child
            .kill()
            .map_err(|e| format!("Failed to kill receiver.py: {}", e))?;
        println!("[Tauri] receiver.py stopped.");
    }

    Ok("Capture stopped".to_string())
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
        .manage(WslProcess(Mutex::new(None))) // ← add this
        .setup(|app| {
            start_osc_listener(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_audio_devices,
            start_capture,
            stop_capture
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
