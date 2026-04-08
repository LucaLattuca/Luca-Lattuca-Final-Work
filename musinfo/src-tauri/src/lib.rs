use std::process::Command;

/// Runs a Python script to query all available audio devices on the system.
#[tauri::command]
fn get_audio_devices() -> Vec<serde_json::Value> {
    let output = std::process::Command::new("python")
        .args([
            "-c",
            r#"
import json, sounddevice as sd
devices = sd.query_devices()
host_apis = sd.query_hostapis()
result = []
for i, d in enumerate(devices):
    api_name = host_apis[d["hostapi"]]["name"]

    # Only include input devices and those using Windows WASAPI (Windows Audio Session API)
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
        .unwrap();

    let stdout = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str(stdout.trim()).unwrap_or_default()
}

// sends a command to the backend to start the audio capture process
#[tauri::command]
fn start_capture() -> Result<String, String> {
    let script_path = "../backend/windows/capture.py";

    let output = Command::new("python")
        .arg(script_path)
        .output()
        .map_err(|e| format!("Failed to spawn capture.py: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![get_audio_devices, start_capture])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
