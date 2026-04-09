// lib.rs updated using Claude (sonnet 4.6)
// https://claude.ai/share/52e2944c-e51f-4af7-897c-736ca8b8c08e

use rosc::decoder::decode_udp;
use rosc::OscPacket;
use serde_json::Value;
use std::net::UdpSocket;
use std::path::Path;
use std::process::Command;
use std::thread;
use tauri::{AppHandle, Emitter}; // no Manager since we're only sending events

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

/// Sends a command to the WSL backend to start the audio capture process.
#[tauri::command]
fn start_capture() -> Result<String, String> {
    let script_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("Could not resolve project root")?
        .join("backend/windows/capture.py");

    let output = Command::new("python")
        .arg(&script_path)
        .output()
        .map_err(|e| format!("Failed to spawn capture.py: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

/// Spawns a background thread that listens for incoming OSC messages from WSL.
/// When a message arrives, it emits a Tauri event that the frontend can subscribe to.
fn start_osc_listener(app_handle: AppHandle) {
    // spawns a trhead : move takes ownership of app_handle
    thread::spawn(move || {
        // opens a UDP sucket on port 9000. 0.0.0.0 means listen on all network interfaces
        let socket =
            UdpSocket::bind("0.0.0.0:9000").expect("[OSC] Failed to bind UDP socket on port 9000");

        println!("[OSC] Listening for OSC messages on port 9000...");

        // fixed-sixe buffer to hold incoming UDP packets. OSC messages should fit within this size
        let mut buf = [0u8; 1024];

        loop {
            // waits until a udp packet arrives
            match socket.recv_from(&mut buf) {
                Ok((size, addr)) => {
                    println!("[OSC] Packet received from {}", addr);
                    // passes only the relevant slice of the buffer
                    match decode_udp(&buf[..size]) {
                        // type of OSC packet : -> message or bundle
                        Ok((_, OscPacket::Message(msg))) => {
                            println!("[OSC] Address: {}, Args: {:?}", msg.addr, msg.args);

                            // extract the string we're passing
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

                            //
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
        .setup(|app| {
            start_osc_listener(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_audio_devices, start_capture])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
