//! Installed XDG DesktopAppInfo identities. GIO parses Exec argv and launches without a shell.
use crate::backend::{App, NativeError, Result};
use gio::{glib, prelude::*};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn invalid() -> NativeError {
    NativeError::new(
        "app_not_found",
        "select an exact installed desktop ID from list_apps",
    )
}
fn info_app(info: &gio::DesktopAppInfo) -> Result<App> {
    let id = info.id().ok_or_else(invalid)?;
    let executable = info.executable();
    let path = if executable.is_absolute() {
        executable
    } else {
        glib::find_program_in_path(executable).ok_or_else(invalid)?
    };
    let command = info.commandline().ok_or_else(invalid)?;
    // GLib's argv parser performs quote removal, never variable or command substitution.
    let argv = glib::shell_parse_argv(command).map_err(|_| invalid())?;
    if argv.is_empty() {
        return Err(invalid());
    }
    let file = info
        .filename()
        .ok_or_else(invalid)?
        .canonicalize()
        .map_err(|_| invalid())?;
    let mut app = App::new(
        format!("desktop:{id}"),
        info.display_name().into(),
        None,
        Some(path.to_string_lossy().into_owned()),
    );
    if app.identity_digest.is_empty() {
        return Err(invalid());
    }
    let mut identity = Sha256::new();
    identity.update(app.id.as_bytes());
    identity.update(app.identity_digest.as_bytes());
    identity.update(file.as_os_str().as_encoded_bytes());
    identity.update(std::fs::read(file).map_err(|_| invalid())?);
    app.identity_digest = format!("{:x}", identity.finalize());
    app.installed_id = Some(app.id.clone());
    Ok(app)
}
pub fn installed() -> Vec<App> {
    gio::AppInfo::all()
        .into_iter()
        .filter_map(|app| app.downcast::<gio::DesktopAppInfo>().ok())
        .filter(|info| !info.is_hidden())
        .filter_map(|info| info_app(&info).ok())
        .collect()
}
pub fn resolve(identifier: &str) -> Result<App> {
    let id = identifier.strip_prefix("desktop:").ok_or_else(invalid)?;
    if !gio::AppInfo::all()
        .iter()
        .any(|info| info.id().is_some_and(|native| native == id))
    {
        return Err(invalid());
    }
    let info = gio::DesktopAppInfo::new(id).ok_or_else(invalid)?;
    if info.is_hidden() {
        return Err(invalid());
    }
    info_app(&info)
}
pub fn start(app: &App) -> Result<Value> {
    let id = app.id.strip_prefix("desktop:").ok_or_else(invalid)?;
    // Native lookup rejects model-supplied paths and unregistered desktop files.
    let info = gio::DesktopAppInfo::new(id).ok_or_else(invalid)?;
    let current = info_app(&info)?;
    if current.id != app.id || current.identity_digest != app.identity_digest {
        return Err(NativeError::new(
            "application_identity_changed",
            "installed desktop entry or executable changed",
        ));
    }
    let mut pids = Vec::new();
    let null = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open("/dev/null")
        .map_err(|_| invalid())?;
    let mut callback = |_: &gio::DesktopAppInfo, pid: glib::Pid| {
        if pid.0 > 0 {
            pids.push(pid.0 as u32);
        }
    };
    info.launch_uris_as_manager_with_fds(
        &[],
        None::<&gio::AppLaunchContext>,
        glib::SpawnFlags::SEARCH_PATH,
        None,
        Some(&mut callback),
        Some(&null),
        Some(&null),
        Some(&null),
    )
    .map_err(|_| NativeError::new("app_launch_failed", "native DesktopAppInfo launch failed"))?;
    Ok(
        json!({"ok":true,"installed_app":app.id,"installed_identity_digest":app.identity_digest,"process_ids":pids,"fresh_observation_required":true}),
    )
}

#[cfg(test)]
mod tests {
    #[test]
    fn native_exec_parser_does_not_expand_commands_or_variables() {
        let parsed =
            gio::glib::shell_parse_argv("/usr/bin/app '$(echo hidden)' '$TOKEN' ';'").unwrap();
        assert_eq!(parsed[1], std::ffi::OsStr::new("$(echo hidden)"));
        assert_eq!(parsed[2], std::ffi::OsStr::new("$TOKEN"));
        assert!(super::start(&crate::backend::App::new(
            "/tmp/arbitrary".into(),
            "Unregistered".into(),
            None,
            Some("/usr/bin/true".into())
        ))
        .is_err());
    }
}

/// Associate only the complete native literal command line; field-code launches remain unassociated.
pub fn matches_running(installed: &App, running: &App) -> bool {
    let Some(pid) = running.process_id else {
        return false;
    };
    let Some(id) = installed.id.strip_prefix("desktop:") else {
        return false;
    };
    if installed.app_path.is_none() || installed.app_path != running.app_path {
        return false;
    }
    let Some(info) = gio::DesktopAppInfo::new(id) else {
        return false;
    };
    if !info_app(&info).is_ok_and(|current| current.identity_digest == installed.identity_digest) {
        return false;
    }
    let Some(command) = info.commandline() else {
        return false;
    };
    let Ok(argv) = glib::shell_parse_argv(command) else {
        return false;
    };
    // GIO owns field expansion. Without a launched PID receipt, an expanded command is unknown.
    if argv
        .iter()
        .any(|argument| argument.as_encoded_bytes().contains(&b'%'))
    {
        return false;
    }
    let Ok(command) = std::fs::read(format!("/proc/{pid}/cmdline")) else {
        return false;
    };
    if command.len() > 65536 {
        return false;
    }
    let native = command
        .strip_suffix(&[0])
        .unwrap_or(&command)
        .split(|byte| *byte == 0)
        .collect::<Vec<_>>();
    native.len() == argv.len()
        && native
            .iter()
            .skip(1)
            .zip(argv.iter().skip(1))
            .all(|(native, argument)| *native == argument.as_encoded_bytes())
}
