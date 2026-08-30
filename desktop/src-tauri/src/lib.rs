mod commands;
mod config;
mod error;
mod import;
mod keychain;
mod qualtrics;
mod scheduler;
mod state;

use tauri::menu::{
    AboutMetadata, MenuBuilder, MenuItem, SubmenuBuilder, HELP_SUBMENU_ID, WINDOW_SUBMENU_ID,
};
use tauri::{Emitter, Manager};

use crate::state::AppState;

/// Native menu → webview. App.svelte opens What's new and runs a non-silent check.
const CHECK_UPDATES_EVENT: &str = "updates://check";
const CHECK_UPDATES_ID: &str = "check-for-updates";

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // A corrupt or unreadable config must not block startup: fall back to empty
            // so the user can still reach the UI and fix it.
            let cfg = match config::store::load(app.handle()) {
                Ok(cfg) => cfg,
                Err(e) => {
                    eprintln!("QualSched: could not load config ({e}); starting empty");
                    config::AppConfig::default()
                }
            };
            app.manage(AppState::new(cfg));
            // Menu is extra chrome: a failure here must not block the rest of the app.
            if let Err(e) = install_app_menu(app.handle()) {
                eprintln!("QualSched: could not install application menu ({e})");
            }
            Ok(())
        })
        .on_menu_event(|app, event| {
            if event.id() == CHECK_UPDATES_ID {
                let _ = app.emit(CHECK_UPDATES_EVENT, ());
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::config_cmds::get_app_config,
            commands::config_cmds::save_account,
            commands::config_cmds::delete_account,
            commands::config_cmds::save_project,
            commands::config_cmds::delete_project,
            commands::config_cmds::forget_survey_copies,
            commands::config_cmds::set_account_token,
            commands::config_cmds::has_account_token,
            commands::config_cmds::clear_account_token,
            commands::config_cmds::test_account,
            commands::lookup_cmds::list_surveys,
            commands::lookup_cmds::list_directories,
            commands::lookup_cmds::list_libraries,
            commands::lookup_cmds::list_mailing_lists,
            commands::lookup_cmds::list_messages,
            commands::lookup_cmds::get_message_text,
            commands::contact_cmds::get_contacts,
            commands::contact_cmds::create_contact,
            commands::contact_cmds::update_contact,
            commands::contact_cmds::delete_contact,
            commands::contact_cmds::apply_embedded_defaults,
            commands::schedule_cmds::preview_schedule,
            commands::schedule_cmds::execute_schedule,
            commands::distribution_cmds::list_distributions,
            commands::distribution_cmds::delete_distributions,
            commands::distribution_cmds::delete_unsent_for_contact,
            commands::import_cmds::preview_legacy_import,
            commands::import_cmds::confirm_legacy_import,
            commands::export_cmds::export_project_config,
            commands::update_cmds::check_for_update,
        ])
        .run(tauri::generate_context!())
        .expect("error while running QualSched");
}

/// Native menu rather than tauri-plugin-updater: Windows installers are still
/// unsigned, so there is no updater pubkey / latest.json to sign against. The
/// item just asks the webview to open What's new and hit GitHub.
///
/// Built to match Tauri's `Menu::default` (File/Edit/Window/Help) so we do not
/// strip the usual predefined items, plus "Check for Updates…" in the standard
/// place: the QualSched menu on macOS, Help on Windows and Linux.
fn about_metadata(app: &tauri::AppHandle) -> AboutMetadata<'_> {
    AboutMetadata {
        name: Some("QualSched".into()),
        version: Some(app.package_info().version.to_string()),
        ..Default::default()
    }
}

fn install_app_menu(app: &tauri::AppHandle) -> tauri::Result<()> {
    let check = MenuItem::with_id(
        app,
        CHECK_UPDATES_ID,
        "Check for Updates…",
        true,
        None::<&str>,
    )?;

    #[cfg(target_os = "macos")]
    let app_menu = SubmenuBuilder::new(app, "QualSched")
        .about(Some(about_metadata(app)))
        .separator()
        .item(&check)
        .separator()
        .services()
        .separator()
        .hide()
        .hide_others()
        .separator()
        .quit()
        .build()?;

    // Tauri's default omits File on Linux; include it so Windows/Linux are not
    // left with only Edit when we replace the empty-menu-bar case. Quit stays
    // on the QualSched menu on macOS (standard), so File there is just Close.
    #[cfg(target_os = "macos")]
    let file = SubmenuBuilder::new(app, "File").close_window().build()?;

    #[cfg(not(target_os = "macos"))]
    let file = SubmenuBuilder::new(app, "File")
        .close_window()
        .quit()
        .build()?;

    let edit = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;

    #[cfg(target_os = "macos")]
    let view = SubmenuBuilder::new(app, "View").fullscreen().build()?;

    let window = SubmenuBuilder::with_id(app, WINDOW_SUBMENU_ID, "Window")
        .minimize()
        .maximize()
        .separator()
        .close_window()
        .build()?;

    #[cfg(target_os = "macos")]
    let help = SubmenuBuilder::with_id(app, HELP_SUBMENU_ID, "Help").build()?;

    #[cfg(not(target_os = "macos"))]
    let help = SubmenuBuilder::with_id(app, HELP_SUBMENU_ID, "Help")
        .item(&check)
        .separator()
        .about(Some(about_metadata(app)))
        .build()?;

    #[cfg(target_os = "macos")]
    let menu = MenuBuilder::new(app)
        .item(&app_menu)
        .item(&file)
        .item(&edit)
        .item(&view)
        .item(&window)
        .item(&help)
        .build()?;

    #[cfg(not(target_os = "macos"))]
    let menu = MenuBuilder::new(app)
        .item(&file)
        .item(&edit)
        .item(&window)
        .item(&help)
        .build()?;

    app.set_menu(menu)?;
    Ok(())
}
