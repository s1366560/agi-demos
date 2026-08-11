use std::path::{Path, PathBuf};

use super::{
    broker::{self, AtomicFileUpdate},
    inspect_manifest, manifest, InstallResult, InstalledManifest, ManifestState,
    NativeMessagingManifest, UninstallResult, MANIFEST_FILE_NAME,
};

#[cfg(windows)]
use super::{ManifestStatus, RegistrationAction};

#[derive(Clone, Copy, Debug)]
pub(super) struct RegistryTarget {
    pub(super) browser: &'static str,
    pub(super) key: &'static str,
}

const REGISTRY_TARGETS: [RegistryTarget; 4] = [
    RegistryTarget {
        browser: "Google Chrome",
        key: r"Software\Google\Chrome\NativeMessagingHosts\com.memstack.browserbridge",
    },
    RegistryTarget {
        browser: "Microsoft Edge",
        key: r"Software\Microsoft\Edge\NativeMessagingHosts\com.memstack.browserbridge",
    },
    RegistryTarget {
        browser: "Chromium",
        key: r"Software\Chromium\NativeMessagingHosts\com.memstack.browserbridge",
    },
    RegistryTarget {
        browser: "Brave",
        key: r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.memstack.browserbridge",
    },
];

pub(super) trait RegistryStore {
    fn read(&self, key: &str) -> Result<Option<String>, String>;
    fn write(&mut self, key: &str, value: &str) -> Result<(), String>;
    fn delete(&mut self, key: &str) -> Result<(), String>;
}

pub(super) fn registry_targets() -> &'static [RegistryTarget] {
    &REGISTRY_TARGETS
}

pub(super) fn install_with_store<S: RegistryStore>(
    store: &mut S,
    targets: &[RegistryTarget],
    source: &Path,
    root: &Path,
    version: &str,
) -> Result<InstallResult, String> {
    let broker_install = broker::install_versioned_broker(source, root, version)?;
    let expected = manifest(broker_install.broker_path());
    let serialized = serde_json::to_vec_pretty(&expected).map_err(|error| {
        format!("failed to serialize Windows native messaging manifest: {error}")
    })?;
    let manifest_path = root.join(MANIFEST_FILE_NAME);
    let manifest_update =
        match AtomicFileUpdate::replace(&manifest_path, &serialized, "windows-manifest") {
            Ok(update) => update,
            Err(error) => {
                let rollback = broker_install.rollback();
                return Err(with_rollback(error, rollback));
            }
        };
    match install_registry_values(store, targets, &manifest_path, &expected) {
        Ok(result) => {
            manifest_update.commit();
            broker_install.commit();
            Ok(result)
        }
        Err(error) => {
            let manifest_rollback = manifest_update.rollback();
            let broker_rollback = broker_install.rollback();
            Err(with_rollbacks(error, [manifest_rollback, broker_rollback]))
        }
    }
}

pub(super) fn uninstall_with_store<S: RegistryStore>(
    store: &mut S,
    targets: &[RegistryTarget],
) -> Result<UninstallResult, String> {
    let ownership_contract = manifest(Path::new("/owned/current-sidecar"));
    let mut owned = Vec::new();
    for target in targets {
        let Some(value) = store.read(target.key)? else {
            continue;
        };
        let path = PathBuf::from(&value);
        if !path.is_absolute() {
            return Err(format!(
                "native messaging registry collision for {} at {}",
                target.browser, target.key
            ));
        }
        let inspection = inspect_manifest(&path, &ownership_contract);
        match inspection.state {
            ManifestState::Valid | ManifestState::OwnedStale => {
                owned.push((*target, value));
            }
            ManifestState::Missing | ManifestState::Collision | ManifestState::Invalid => {
                return Err(format!(
                    "native messaging registry collision for {} at {}",
                    target.browser, target.key
                ));
            }
        }
    }

    let mut removed = Vec::new();
    let mut committed: Vec<(RegistryTarget, String)> = Vec::new();
    for (target, original) in owned {
        if let Err(error) = store.delete(target.key) {
            let rollback = rollback_values(store, &committed);
            return Err(with_rollback(
                format!(
                    "failed to remove native messaging registry value for {}: {error}",
                    target.browser
                ),
                rollback,
            ));
        }
        committed.push((target, original));
        removed.push(target.key.to_string());
    }
    Ok(UninstallResult { removed })
}

fn install_registry_values<S: RegistryStore>(
    store: &mut S,
    targets: &[RegistryTarget],
    manifest_path: &Path,
    expected: &NativeMessagingManifest,
) -> Result<InstallResult, String> {
    let manifest_value = manifest_path.to_string_lossy().into_owned();
    let mut originals = Vec::new();
    for target in targets {
        let original = store.read(target.key)?;
        if let Some(value) = &original {
            let path = PathBuf::from(value);
            if !path.is_absolute() {
                return Err(format!(
                    "native messaging registry collision for {} at {}",
                    target.browser, target.key
                ));
            }
            let inspection = inspect_manifest(&path, expected);
            if !matches!(
                inspection.state,
                ManifestState::Valid | ManifestState::OwnedStale
            ) {
                return Err(format!(
                    "native messaging registry collision for {} at {}",
                    target.browser, target.key
                ));
            }
        }
        originals.push((*target, original));
    }

    let mut committed = Vec::new();
    for (target, original) in &originals {
        if original.as_deref() == Some(manifest_value.as_str()) {
            continue;
        }
        if let Err(error) = store.write(target.key, &manifest_value) {
            let rollback = rollback_optional_values(store, &committed);
            return Err(with_rollback(
                format!(
                    "failed to register native messaging host for {}: {error}",
                    target.browser
                ),
                rollback,
            ));
        }
        committed.push((*target, original.clone()));
    }
    Ok(InstallResult {
        installed: targets
            .iter()
            .map(|target| InstalledManifest {
                browser: target.browser.to_string(),
                manifest_path: manifest_path.to_path_buf(),
            })
            .collect(),
        skipped: Vec::new(),
    })
}

fn rollback_optional_values<S: RegistryStore>(
    store: &mut S,
    committed: &[(RegistryTarget, Option<String>)],
) -> Result<(), String> {
    let mut errors = Vec::new();
    for (target, original) in committed.iter().rev() {
        let result = match original {
            Some(value) => store.write(target.key, value),
            None => store.delete(target.key),
        };
        if let Err(error) = result {
            errors.push(format!("{}: {error}", target.browser));
        }
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("; "))
    }
}

fn rollback_values<S: RegistryStore>(
    store: &mut S,
    committed: &[(RegistryTarget, String)],
) -> Result<(), String> {
    let mut errors = Vec::new();
    for (target, value) in committed.iter().rev() {
        if let Err(error) = store.write(target.key, value) {
            errors.push(format!("{}: {error}", target.browser));
        }
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("; "))
    }
}

fn with_rollback(error: String, rollback: Result<(), String>) -> String {
    match rollback {
        Ok(()) => error,
        Err(rollback) => format!("{error}; rollback failed: {rollback}"),
    }
}

fn with_rollbacks<const N: usize>(error: String, rollbacks: [Result<(), String>; N]) -> String {
    let failures = rollbacks
        .into_iter()
        .filter_map(Result::err)
        .collect::<Vec<_>>();
    if failures.is_empty() {
        error
    } else {
        format!("{error}; rollback failed: {}", failures.join("; "))
    }
}

#[cfg(windows)]
struct SystemRegistry;

#[cfg(windows)]
impl RegistryStore for SystemRegistry {
    fn read(&self, key: &str) -> Result<Option<String>, String> {
        use std::io::ErrorKind;

        use winreg::{enums::KEY_READ, RegKey};

        let current_user = RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
        let key = match current_user.open_subkey_with_flags(key, KEY_READ) {
            Ok(key) => key,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(format!("failed to open HKCU registry key: {error}")),
        };
        key.get_value("")
            .map(Some)
            .map_err(|error| format!("failed to read HKCU registry value: {error}"))
    }

    fn write(&mut self, key: &str, value: &str) -> Result<(), String> {
        use winreg::{enums::KEY_WRITE, RegKey};

        let current_user = RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
        let (key, _) = current_user
            .create_subkey_with_flags(key, KEY_WRITE)
            .map_err(|error| format!("failed to create HKCU registry key: {error}"))?;
        key.set_value("", &value)
            .map_err(|error| format!("failed to write HKCU registry value: {error}"))
    }

    fn delete(&mut self, key: &str) -> Result<(), String> {
        use std::io::ErrorKind;

        use winreg::{enums::KEY_WRITE, RegKey};

        let current_user = RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
        let key = match current_user.open_subkey_with_flags(key, KEY_WRITE) {
            Ok(key) => key,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
            Err(error) => return Err(format!("failed to open HKCU registry key: {error}")),
        };
        match key.delete_value("") {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
            Err(error) => Err(format!("failed to delete HKCU registry value: {error}")),
        }
    }
}

#[cfg(windows)]
pub(super) fn install() -> Result<InstallResult, String> {
    let source = std::env::current_exe()
        .map_err(|error| format!("failed to resolve browser broker executable: {error}"))?;
    let source = source.canonicalize().unwrap_or(source);
    install_with_store(
        &mut SystemRegistry,
        registry_targets(),
        &source,
        &broker::broker_root()?,
        env!("CARGO_PKG_VERSION"),
    )
}

#[cfg(windows)]
pub(super) fn uninstall() -> Result<UninstallResult, String> {
    uninstall_with_store(&mut SystemRegistry, registry_targets())
}

#[cfg(windows)]
pub(super) fn statuses() -> Vec<ManifestStatus> {
    let store = SystemRegistry;
    let root = match broker::broker_root() {
        Ok(root) => root,
        Err(error) => {
            return vec![ManifestStatus {
                browser: "Windows Native Messaging".to_string(),
                path: PathBuf::new(),
                registration_location: "HKCU".to_string(),
                present: false,
                state: ManifestState::Invalid,
                reason_code: "registration_target_invalid",
                allowed_actions: Vec::new(),
                broker_digest: None,
                error: Some(error),
            }];
        }
    };
    let expected_path = broker::current_broker_path(&root).unwrap_or_default();
    let expected = manifest(&expected_path);
    registry_targets()
        .iter()
        .map(|target| match store.read(target.key) {
            Ok(Some(value)) => {
                let path = PathBuf::from(value);
                let inspection = inspect_manifest(&path, &expected);
                ManifestStatus::from_inspection(
                    target.browser.to_string(),
                    path,
                    format!("HKCU\\{}", target.key),
                    inspection,
                )
            }
            Ok(None) => ManifestStatus {
                browser: target.browser.to_string(),
                path: PathBuf::from(target.key),
                registration_location: format!("HKCU\\{}", target.key),
                present: false,
                state: ManifestState::Missing,
                reason_code: "registration_missing",
                allowed_actions: vec![RegistrationAction::Install],
                broker_digest: None,
                error: None,
            },
            Err(error) => ManifestStatus {
                browser: target.browser.to_string(),
                path: PathBuf::from(target.key),
                registration_location: format!("HKCU\\{}", target.key),
                present: false,
                state: ManifestState::Invalid,
                reason_code: "registration_read_failed",
                allowed_actions: Vec::new(),
                broker_digest: None,
                error: Some(error),
            },
        })
        .collect()
}
