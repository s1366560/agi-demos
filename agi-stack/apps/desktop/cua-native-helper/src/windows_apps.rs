//! Exact AppsFolder inventory and native launch. No model command line or path is accepted.
use crate::backend::{App, NativeError, Result};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use windows::{
    Data::Xml::Dom::{XmlDocument, XmlElement},
    Management::Deployment::PackageManager,
    Win32::{
        Foundation::*,
        System::{Com::*, Threading::*},
        UI::{
            Shell::{PropertiesSystem::PSGetPropertyKeyFromName, *},
            WindowsAndMessaging::SW_SHOWNORMAL,
        },
    },
    core::{HSTRING, Interface, PCWSTR, PWSTR, w},
};

struct Installed {
    app: App,
    item: IShellItem,
    aumid: String,
    packaged: bool,
}
fn failure() -> NativeError {
    NativeError::new(
        "app_launch_unavailable",
        "native installed application inventory or launch is unavailable",
    )
}
fn owned_string(value: PWSTR) -> Option<String> {
    if value.is_null() {
        return None;
    }
    let result = unsafe { value.to_string().ok() };
    unsafe {
        CoTaskMemFree(Some(value.0.cast()));
    }
    result.filter(|v| !v.is_empty())
}
fn property(item: &IShellItem2, name: &str) -> Option<String> {
    let wide: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
    let mut key = PROPERTYKEY::default();
    unsafe {
        PSGetPropertyKeyFromName(PCWSTR(wide.as_ptr()), &mut key).ok()?;
        owned_string(item.GetString(&key).ok()?)
    }
}
fn package_executable(aumid: &str) -> Option<(PathBuf, String)> {
    let (family, app_id) = aumid.split_once('!')?;
    let manager = PackageManager::new().ok()?;
    let packages = manager
        .FindPackagesByUserSecurityIdPackageFamilyName(&HSTRING::new(), &HSTRING::from(family))
        .ok()?;
    for package in packages {
        let root = PathBuf::from(package.InstalledLocation().ok()?.Path().ok()?.to_string());
        let manifest = std::fs::read_to_string(root.join("AppxManifest.xml")).ok()?;
        if manifest.len() > 8 * 1024 * 1024 {
            return None;
        }
        let document = XmlDocument::new().ok()?;
        document.LoadXml(&HSTRING::from(&manifest)).ok()?;
        let applications = document
            .GetElementsByTagName(&HSTRING::from("Application"))
            .ok()?;
        for index in 0..applications.Length().ok()? {
            let element: XmlElement = applications.Item(index).ok()?.cast().ok()?;
            if element.GetAttribute(&HSTRING::from("Id")).ok()?.to_string() == app_id {
                let executable = element
                    .GetAttribute(&HSTRING::from("Executable"))
                    .ok()?
                    .to_string();
                let path = root.join(executable).canonicalize().ok()?;
                if !path.starts_with(root.canonicalize().ok()?) {
                    return None;
                }
                let identity = format!("{}\n{}", package.Id().ok()?.FullName().ok()?, manifest);
                return Some((path, identity));
            }
        }
    }
    None
}
fn entries(identifier: Option<&str>) -> Result<Vec<Installed>> {
    let folder: IShellItem =
        unsafe { SHGetKnownFolderItem(&FOLDERID_AppsFolder, KF_FLAG_DEFAULT, None) }
            .map_err(|_| failure())?;
    let enumeration: IEnumShellItems =
        unsafe { folder.BindToHandler(None, &BHID_EnumItems) }.map_err(|_| failure())?;
    let mut result = Vec::new();
    for _ in 0..4096 {
        let mut item = [None];
        let mut count = 0;
        if unsafe { enumeration.Next(&mut item, Some(&mut count)) }.is_err() || count == 0 {
            break;
        }
        let Some(item) = item[0].take() else {
            break;
        };
        let Some(parsing) = unsafe { item.GetDisplayName(SIGDN_DESKTOPABSOLUTEPARSING) }
            .ok()
            .and_then(owned_string)
        else {
            continue;
        };
        if identifier.is_some_and(|id| id != format!("shell:{parsing}")) {
            continue;
        }
        let Ok(properties) = item.cast::<IShellItem2>() else {
            continue;
        };
        let aumid = property(&properties, "System.AppUserModel.ID").unwrap_or_default();
        let package = package_executable(&aumid);
        let target = property(&properties, "System.Link.TargetParsingPath");
        let (path, package_identity, packaged) = match package {
            Some((path, identity)) => (path, identity, true),
            None => {
                let Some(path) = target
                    .as_ref()
                    .map(Path::new)
                    .filter(|path| path.is_absolute() && path.is_file())
                else {
                    continue;
                };
                (path.to_owned(), String::new(), false)
            }
        };
        let name = unsafe { item.GetDisplayName(SIGDN_NORMALDISPLAY) }
            .ok()
            .and_then(owned_string)
            .unwrap_or_else(|| parsing.clone());
        let mut app = App::new(
            format!("shell:{parsing}"),
            name,
            None,
            Some(path.to_string_lossy().into_owned()),
        );
        if app.identity_digest.is_empty() {
            continue;
        }
        let mut digest = Sha256::new();
        for field in [
            &app.id,
            &app.identity_digest,
            &aumid,
            &package_identity,
            &property(&properties, "System.Link.Arguments").unwrap_or_default(),
        ] {
            digest.update(field.as_bytes());
            digest.update([0]);
        }
        app.identity_digest = format!("{:x}", digest.finalize());
        app.installed_id = Some(app.id.clone());
        app.native_registration_id = (!aumid.is_empty()).then(|| aumid.clone());
        result.push(Installed {
            app,
            item,
            aumid,
            packaged,
        });
    }
    Ok(result)
}
pub fn icon(app: &App) -> Result<image::RgbaImage> {
    let mut items = entries(Some(&app.id))?;
    if items.len() != 1 {
        return Err(failure());
    }
    let entry = items.remove(0);
    if entry.app.identity_digest != app.identity_digest {
        return Err(NativeError::new(
            "app_icon_identity_changed",
            "the registered shell application changed",
        ));
    }
    crate::windows_app_icon::from_item(&entry.item)
}
pub fn installed() -> Result<Vec<App>> {
    entries(None).map(|items| items.into_iter().map(|item| item.app).collect())
}
pub fn resolve(identifier: &str) -> Result<Vec<App>> {
    entries(Some(identifier)).map(|items| items.into_iter().map(|item| item.app).collect())
}
pub fn start(approved: &App) -> Result<Value> {
    let installed = entries(Some(&approved.id))?
        .into_iter()
        .find(|item| item.app.id == approved.id)
        .ok_or_else(|| {
            NativeError::new(
                "app_not_found",
                "select an exact installed AppsFolder ID from list_apps",
            )
        })?;
    if installed.app.identity_digest != approved.identity_digest {
        return Err(NativeError::new(
            "application_identity_changed",
            "installed application code or native launch metadata changed",
        ));
    }
    let pid = unsafe {
        if installed.packaged {
            let activation: IApplicationActivationManager =
                CoCreateInstance(&ApplicationActivationManager, None, CLSCTX_LOCAL_SERVER)
                    .map_err(|_| failure())?;
            let aumid: Vec<u16> = installed.aumid.encode_utf16().chain(Some(0)).collect();
            activation
                .ActivateApplication(PCWSTR(aumid.as_ptr()), PCWSTR::null(), AO_NONE)
                .map_err(|_| failure())?
        } else {
            let pidl = SHGetIDListFromObject(&installed.item).map_err(|_| failure())?;
            let mut execution = SHELLEXECUTEINFOW {
                cbSize: std::mem::size_of::<SHELLEXECUTEINFOW>() as u32,
                fMask: SEE_MASK_IDLIST | SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC,
                lpVerb: w!("open"),
                lpIDList: pidl.cast(),
                nShow: SW_SHOWNORMAL.0,
                ..Default::default()
            };
            let launched = ShellExecuteExW(&mut execution);
            CoTaskMemFree(Some(pidl.cast()));
            launched.map_err(|_| failure())?;
            if execution.hProcess.is_invalid() {
                return Ok(
                    json!({"ok":true,"installed_app":approved.id,"state":"launched_process_not_yet_observable","fresh_observation_required":true}),
                );
            }
            let pid = GetProcessId(execution.hProcess);
            let _ = CloseHandle(execution.hProcess);
            pid
        }
    };
    let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }
        .map_err(|_| failure())?;
    let mut path = [0u16; 32768];
    let mut count = path.len() as u32;
    let queried = unsafe {
        QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            PWSTR(path.as_mut_ptr()),
            &mut count,
        )
    };
    unsafe {
        let _ = CloseHandle(handle);
    }
    queried.map_err(|_| failure())?;
    let activated = App::new(
        format!("pid:{pid}"),
        approved.display_name.clone(),
        Some(pid),
        Some(String::from_utf16_lossy(&path[..count as usize])),
    );
    Ok(
        json!({"ok":true,"app":activated.id,"process_id":pid,"activated_app":activated,"installed_app":approved.id,"installed_identity_digest":approved.identity_digest,"fresh_observation_required":true}),
    )
}

#[cfg(test)]
mod tests {
    #[test]
    fn shell_launch_uses_idlist_without_model_command_parameters() {
        use windows::Win32::UI::Shell::*;
        let request = SHELLEXECUTEINFOW {
            fMask: SEE_MASK_IDLIST | SEE_MASK_NOCLOSEPROCESS,
            ..Default::default()
        };
        assert!(request.lpFile.is_null());
        assert!(request.lpParameters.is_null());
        assert_eq!(request.fMask & SEE_MASK_IDLIST, SEE_MASK_IDLIST);
    }
}
