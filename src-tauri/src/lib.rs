mod commands;
mod config;
mod error;
mod import;
mod keychain;
mod qualtrics;
mod scheduler;
mod state;

use tauri::Manager;

use crate::state::AppState;

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
            Ok(())
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
