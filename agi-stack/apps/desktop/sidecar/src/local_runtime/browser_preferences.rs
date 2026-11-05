//! Browser preferences survive a new application process; execution identities do not.
use super::browser_bridge::BrowserBridgeConfig;
use crate::private_file_permissions::set_private_file_permissions;
use serde::{Deserialize, Serialize};
use std::{
    fs,
    fs::OpenOptions,
    io::{Read, Write},
    path::{Path, PathBuf},
};

const FILE: &str = "browser-preferences-v1.json";
const MAX_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Stored {
    version: u8,
    browser_bridge: BrowserBridgeConfig,
}

fn durable_preferences(config: &BrowserBridgeConfig) -> BrowserBridgeConfig {
    BrowserBridgeConfig {
        enabled: false,
        full_cdp_access_enabled: false,
        ..config.clone()
    }
}

pub(super) fn load(root: &Path) -> Result<BrowserBridgeConfig, String> {
    let path = root.join(FILE);
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = match options.open(&path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Default::default()),
        Err(_) => return Err("browser_preferences_read_failed".into()),
    };
    let metadata = file
        .metadata()
        .map_err(|_| "browser_preferences_read_failed")?;
    if !metadata.is_file() || metadata.len() > MAX_BYTES {
        return Err("browser_preferences_invalid".into());
    }
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "browser_preferences_read_failed")?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err("browser_preferences_invalid".into());
    }
    let stored: Stored =
        serde_json::from_slice(&bytes).map_err(|_| "browser_preferences_invalid")?;
    if stored.version != 1 {
        return Err("browser_preferences_version_unsupported".into());
    }
    stored.browser_bridge.validate()?;
    // A fresh app restores preferences, not an earlier process's active access.
    Ok(durable_preferences(&stored.browser_bridge))
}

pub(super) struct Prepared {
    temporary: PathBuf,
    destination: PathBuf,
    owns_temporary: bool,
}

impl Prepared {
    pub(super) fn new(root: &Path, config: &BrowserBridgeConfig) -> Result<Self, String> {
        config.validate()?;
        let mut prepared = Self {
            temporary: root.join(format!(".browser-preferences-{}.tmp", uuid::Uuid::new_v4())),
            destination: root.join(FILE),
            owns_temporary: false,
        };
        let bytes = serde_json::to_vec(&Stored {
            version: 1,
            browser_bridge: durable_preferences(config),
        })
        .map_err(|_| "browser_preferences_encode_failed")?;
        if bytes.len() as u64 > MAX_BYTES {
            return Err("browser_preferences_too_large".into());
        }
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options
            .open(&prepared.temporary)
            .map_err(|_| "browser_preferences_write_failed")?;
        prepared.owns_temporary = true;
        set_private_file_permissions(&prepared.temporary)
            .map_err(|_| "browser_preferences_write_failed")?;
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| "browser_preferences_write_failed")?;
        Ok(prepared)
    }
    pub(super) fn commit(self) -> Result<(), String> {
        fs::rename(&self.temporary, &self.destination)
            .map_err(|_| "browser_preferences_write_failed".into())
    }
}
impl Drop for Prepared {
    fn drop(&mut self) {
        if self.owns_temporary {
            let _ = fs::remove_file(&self.temporary);
        }
    }
}

#[cfg(test)]
#[path = "browser_preferences_tests.rs"]
mod tests;
