use std::path::Path;
use tauri::{
    menu::{Menu, MenuBuilder, MenuItemBuilder, SubmenuBuilder},
    AppHandle, Emitter, Manager,
};
use tauri_plugin_opener::OpenerExt;

// Menu IDs
const SAVE_SESSION: &str = "save-session";
const LOAD_SESSION: &str = "load-session";
const HELP: &str = "help";
const ABOUT: &str = "about";

// Build menu
pub fn build_menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let save = MenuItemBuilder::new("Save Session")
        .id(SAVE_SESSION)
        .accelerator("CmdOrCtrl+S")
        .build(app)?;

    let load = MenuItemBuilder::new("Load Session")
        .id(LOAD_SESSION)
        .accelerator("CmdOrCtrl+O")
        .build(app)?;

    // File dropdown
    let file = SubmenuBuilder::new(app, "File")
        .item(&save)
        .item(&load)
        .build()?;

    let help = MenuItemBuilder::new("Help").id(HELP).build(app)?;

    let about = MenuItemBuilder::new("About").id(ABOUT).build(app)?;

    MenuBuilder::new(app)
        .item(&file)
        .item(&help)
        .item(&about)
        .build()
}

// Menu event handler
pub fn handle_menu_event(app: &AppHandle, event: tauri::menu::MenuEvent) {
    match event.id().as_ref() {
        SAVE_SESSION => {
            app.emit("menu-save-session", ()).unwrap_or_else(|e| {
                eprintln!("[menu] Failed to emit menu-save-session: {}", e);
            });
        }

        LOAD_SESSION => {
            app.emit("menu-load-session", ()).unwrap_or_else(|e| {
                eprintln!("[menu] Failed to emit menu-load-session: {}", e);
            });
        }

        HELP => {
            let docs_path = docs_url("index.html");
            open_url(app, &docs_path);
        }

        ABOUT => {
            let docs_path = docs_url("about.html");
            open_url(app, &docs_path);
        }

        other => {
            eprintln!("[menu] Unknown menu event: {}", other);
        }
    }
}

// Helpers

/// Builds a file:/// URL pointing into the docs/ folder at project root.
/// Uses CARGO_MANIFEST_DIR (src-tauri/) → parent → project root.
fn docs_url(filename: &str) -> String {
    let project_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("Could not resolve project root");

    let path = project_root
        .join("docs")
        .join(filename)
        .to_string_lossy()
        // Windows paths need forward slashes in file URIs
        .replace('\\', "/");

    format!("file:///{}", path)
}

// Opens a URL in the system default browser via tauri-plugin-opener.
fn open_url(app: &AppHandle, url: &str) {
    if let Err(e) = app.opener().open_url(url, None::<&str>) {
        eprintln!("[menu] Failed to open {}: {}", url, e);
    }
}
