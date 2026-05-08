use std::path::Path;
use tauri::{
    menu::{Menu, MenuBuilder, MenuItemBuilder, SubmenuBuilder},
    AppHandle, Emitter,
};
use tauri_plugin_opener::OpenerExt;

// Menu Ids

const SAVE_SESSION: &str = "save-session";
const HELP: &str = "help";
const ABOUT: &str = "about";
pub const LOAD_SESSION_PREFIX: &str = "load-session:";

// Build Menu Handlers

pub fn build_menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let file = build_file_submenu(app)?;

    let help = MenuItemBuilder::new("Help").id(HELP).build(app)?;

    let about = MenuItemBuilder::new("About").id(ABOUT).build(app)?;

    MenuBuilder::new(app)
        .item(&file)
        .item(&help)
        .item(&about)
        .build()
}

// Builds the File submenu, reading current sessions from disk.
// Called on startup and after every save.
fn build_file_submenu(app: &AppHandle) -> tauri::Result<tauri::menu::Submenu<tauri::Wry>> {
    let save = MenuItemBuilder::new("Save Session")
        .id(SAVE_SESSION)
        .accelerator("CmdOrCtrl+S")
        .build(app)?;

    // read sessions from disk
    let sessions = list_sessions_from_disk();

    // build the Load Session submenu
    let mut load_builder = SubmenuBuilder::new(app, "Load Session");

    if sessions.is_empty() {
        let empty = MenuItemBuilder::new("No sessions saved")
            .enabled(false)
            .build(app)?;
        load_builder = load_builder.item(&empty);
    } else {
        for name in &sessions {
            let item = MenuItemBuilder::new(name)
                .id(format!("{}{}", LOAD_SESSION_PREFIX, name))
                .build(app)?;
            load_builder = load_builder.item(&item);
        }
    }

    let load = load_builder.build()?;

    SubmenuBuilder::new(app, "File")
        .item(&save)
        .item(&load)
        .build()
}

// Rebuild

// Called after a session is saved to refresh the Load Session submenu.
pub fn rebuild_menu(app: &AppHandle) -> Result<(), String> {
    let menu = build_menu(app).map_err(|e| format!("Failed to rebuild menu: {}", e))?;
    app.set_menu(menu)
        .map_err(|e| format!("Failed to set menu: {}", e))?;
    Ok(())
}

// Event Handlers

pub fn handle_menu_event(app: &AppHandle, event: tauri::menu::MenuEvent) {
    let id = event.id().as_ref();

    // load-session:name pattern
    if let Some(name) = id.strip_prefix(LOAD_SESSION_PREFIX) {
        app.emit("menu-load-session", name.to_string())
            .unwrap_or_else(|e| {
                eprintln!("[menu] Failed to emit menu-load-session: {}", e);
            });
        return;
    }

    match id {
        SAVE_SESSION => {
            app.emit("menu-save-session", ()).unwrap_or_else(|e| {
                eprintln!("[menu] Failed to emit menu-save-session: {}", e);
            });
        }

        HELP => open_url(app, &docs_url("index.html")),
        ABOUT => open_url(app, &docs_url("about.html")),

        other => eprintln!("[menu] Unknown menu event: {}", other),
    }
}

// Helpers

fn list_sessions_from_disk() -> Vec<String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("Could not resolve project root");

    let sessions_dir = root.join("sessions");

    if !sessions_dir.exists() {
        return vec![];
    }

    let mut names = vec![];
    if let Ok(entries) = std::fs::read_dir(&sessions_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("json") {
                if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                    names.push(stem.to_string());
                }
            }
        }
    }

    names.sort();
    names
}

fn docs_url(filename: &str) -> String {
    let project_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("Could not resolve project root");

    let path = project_root
        .join("docs")
        .join(filename)
        .to_string_lossy()
        .replace('\\', "/");

    format!("file:///{}", path)
}

fn open_url(app: &AppHandle, url: &str) {
    if let Err(e) = app.opener().open_url(url, None::<&str>) {
        eprintln!("[menu] Failed to open {}: {}", url, e);
    }
}
