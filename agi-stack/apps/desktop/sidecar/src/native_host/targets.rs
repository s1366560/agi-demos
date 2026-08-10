use std::{ffi::OsStr, path::PathBuf};

use super::{browser_bridge, ManifestTarget, MANIFEST_DIR_OVERRIDE_ENV};

pub(super) fn manifest_targets_from_override(
    value: Option<&OsStr>,
) -> Result<Vec<ManifestTarget>, String> {
    let Some(value) = value else {
        return Ok(platform_manifest_targets());
    };
    let hosts_dir = PathBuf::from(value);
    if !hosts_dir.is_absolute() {
        return Err(format!(
            "{MANIFEST_DIR_OVERRIDE_ENV} must be an absolute path"
        ));
    }
    Ok(vec![ManifestTarget {
        browser: "QA Chromium",
        hosts_dir,
    }])
}

pub(super) fn manifest_targets() -> Result<Vec<ManifestTarget>, String> {
    manifest_targets_from_override(std::env::var_os(MANIFEST_DIR_OVERRIDE_ENV).as_deref())
}

#[cfg(target_os = "macos")]
fn platform_manifest_targets() -> Vec<ManifestTarget> {
    let Ok(home) = browser_bridge::home_dir() else {
        return Vec::new();
    };
    let base = home.join("Library/Application Support");
    [
        ("Google Chrome", base.join("Google/Chrome")),
        ("Chromium", base.join("Chromium")),
        ("Microsoft Edge", base.join("Microsoft Edge")),
        ("Brave", base.join("BraveSoftware/Brave-Browser")),
    ]
    .into_iter()
    .map(|(browser, profile_dir)| ManifestTarget {
        browser,
        hosts_dir: profile_dir.join("NativeMessagingHosts"),
    })
    .collect()
}

#[cfg(target_os = "linux")]
fn platform_manifest_targets() -> Vec<ManifestTarget> {
    let Ok(home) = browser_bridge::home_dir() else {
        return Vec::new();
    };
    let base = home.join(".config");
    [
        ("Google Chrome", base.join("google-chrome")),
        ("Chromium", base.join("chromium")),
        ("Microsoft Edge", base.join("microsoft-edge")),
        ("Brave", base.join("BraveSoftware/Brave-Browser")),
    ]
    .into_iter()
    .map(|(browser, profile_dir)| ManifestTarget {
        browser,
        hosts_dir: profile_dir.join("NativeMessagingHosts"),
    })
    .collect()
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn platform_manifest_targets() -> Vec<ManifestTarget> {
    Vec::new()
}
