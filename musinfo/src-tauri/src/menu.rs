use std::path::Path;
use tauri::{
    menu::{Menu, MenuBuilder, MenuItemBuilder, SubmenuBuilder},
    AppHandle, Emitter,
};
use tauri_plugin_opener::OpenerExt;

// ── Menu IDs ──────────────────────────────────────────────────────────────────

const SAVE_SESSION: &str = "save-session";
const HELP: &str = "help";
const ABOUT: &str = "about";
pub const LOAD_SESSION_PREFIX: &str = "load-session:";

// ── Build ─────────────────────────────────────────────────────────────────────

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

    let sessions = list_sessions_from_disk();
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

// ── Rebuild ───────────────────────────────────────────────────────────────────

// Called after a session is saved to refresh the Load Session submenu.
pub fn rebuild_menu(app: &AppHandle) -> Result<(), String> {
    let menu = build_menu(app).map_err(|e| format!("Failed to rebuild menu: {}", e))?;
    app.set_menu(menu)
        .map_err(|e| format!("Failed to set menu: {}", e))?;
    Ok(())
}

// ── Event Handlers ────────────────────────────────────────────────────────────

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
        HELP => open_doc_browser(app, "index.html"),
        ABOUT => open_doc_browser(app, "about.html"),
        other => eprintln!("[menu] Unknown menu event: {}", other),
    }
}

// ── Doc Browser ───────────────────────────────────────────────────────────────

// Opens a documentation page in the system browser.
//
// Chrome and Edge block fetch() across file:// origins, so markdown cannot be
// loaded at runtime from the browser. Rust reads both markdown files and writes
// temporary HTML files with the content already embedded as window.__DOC_CONTENT__.
// Both temp files are (re)generated on every open so that the Architecture ↔ About
// nav link continues to work.
fn open_doc_browser(app: &AppHandle, target: &str) {
    // CARGO_MANIFEST_DIR = musinfo/src-tauri
    //   .parent()  → musinfo
    //   .parent()  → repo root
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("[menu] could not resolve musinfo dir")
        .parent()
        .expect("[menu] could not resolve repo root");

    let docs_dir = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("[menu] could not resolve musinfo dir")
        .join("docs");

    // Generate both temp files so the nav link between the two pages works.
    let pages: [(&str, &str); 2] = [
        ("index.html", "ARCHITECTURE.md"),
        ("about.html", "README.md"),
    ];

    for (html_file, md_file) in &pages {
        let md = std::fs::read_to_string(root.join(md_file))
            .unwrap_or_else(|e| format!("# Could not read {}\n\n{}", md_file, e));

        let template = match std::fs::read_to_string(docs_dir.join(html_file)) {
            Ok(t) => t,
            Err(e) => {
                eprintln!("[menu] Failed to read template {}: {}", html_file, e);
                continue;
            }
        };

        let json = serde_json::to_string(&md).unwrap_or_else(|_| "\"\"".to_string());

        // Inject content before </head> and rewrite nav hrefs to the temp filenames.
        let script_tag = format!(
            "  <script>window.__DOC_CONTENT__ = {};</script>\n</head>",
            json
        );
        let output = template
            .replace("</head>", &script_tag)
            .replace("href=\"index.html\"", "href=\"_tmp_index.html\"")
            .replace("href=\"about.html\"", "href=\"_tmp_about.html\"");

        let tmp_path = docs_dir.join(format!("_tmp_{}", html_file));
        if let Err(e) = std::fs::write(&tmp_path, &output) {
            eprintln!("[menu] Failed to write {}: {}", tmp_path.display(), e);
        }
    }

    let tmp_path = docs_dir.join(format!("_tmp_{}", target));
    let url = format!("file:///{}", tmp_path.to_string_lossy().replace('\\', "/"));
    open_url(app, &url);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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

fn open_url(app: &AppHandle, url: &str) {
    if let Err(e) = app.opener().open_url(url, None::<&str>) {
        eprintln!("[menu] Failed to open {}: {}", url, e);
    }
}
