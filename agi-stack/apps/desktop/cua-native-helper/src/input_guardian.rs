//! Independent resource owner and passive input mirror supervising the injection worker.
use crate::{
    backend::{NativeError, Result},
    input_watchdog::{read_frame, write_frame, Driver, Ownership, Request, Response, Watchdog},
};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    time::{Duration, Instant},
};
#[cfg(target_os = "linux")]
type Native = crate::linux_watchdog::Native;
#[cfg(target_os = "windows")]
type Native = crate::windows_watchdog::Native;
#[cfg(target_os = "linux")]
type Clipboard = crate::linux_clipboard::Clipboard;
#[cfg(target_os = "windows")]
type Clipboard = crate::windows_clipboard::Clipboard;
fn unsupported() -> NativeError {
    NativeError::unsupported("native resource guardian")
}
async fn available(clipboard: &Clipboard) -> bool {
    #[cfg(target_os = "linux")]
    {
        clipboard.available().await
    }
    #[cfg(target_os = "windows")]
    {
        clipboard.available()
    }
}
pub(crate) struct Root {
    path: PathBuf,
    identity: (u64, u64),
    retained: bool,
}
impl Root {
    fn create() -> Result<Self> {
        let path = std::env::temp_dir().join(format!(
            "memstack-cua-owned-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        #[cfg(target_os = "linux")]
        {
            use std::os::unix::fs::DirBuilderExt;
            std::fs::DirBuilder::new()
                .mode(0o700)
                .create(&path)
                .map_err(|_| unsupported())?;
        }
        #[cfg(target_os = "windows")]
        crate::windows::private_root(&path)?;
        let identity = Self::identity(&path)?;
        Ok(Self {
            path,
            identity,
            retained: false,
        })
    }
    pub(crate) fn identity(path: &std::path::Path) -> Result<(u64, u64)> {
        let metadata = std::fs::symlink_metadata(path).map_err(|_| unsupported())?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err(unsupported());
        }
        #[cfg(target_os = "linux")]
        {
            use std::os::unix::fs::MetadataExt;
            Ok((metadata.dev(), metadata.ino()))
        }
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::{fs::OpenOptionsExt, io::AsRawHandle};
            use windows::Win32::Foundation::{FILETIME, HANDLE};
            #[repr(C)]
            struct Info {
                attributes: u32,
                created: FILETIME,
                accessed: FILETIME,
                written: FILETIME,
                volume: u32,
                size_high: u32,
                size_low: u32,
                links: u32,
                index_high: u32,
                index_low: u32,
            }
            #[link(name = "kernel32")]
            unsafe extern "system" {
                fn GetFileInformationByHandle(file: HANDLE, info: *mut Info) -> i32;
            }
            let file = std::fs::OpenOptions::new()
                .access_mode(0x80)
                .share_mode(7)
                .custom_flags(0x02000000 | 0x00200000)
                .open(path)
                .map_err(|_| unsupported())?;
            let mut info: Info = unsafe { std::mem::zeroed() };
            if unsafe { GetFileInformationByHandle(HANDLE(file.as_raw_handle()), &mut info) } == 0 {
                return Err(unsupported());
            }
            Ok((
                info.volume as u64,
                (info.index_high as u64) << 32 | info.index_low as u64,
            ))
        }
    }
    pub(crate) fn remove_owned(path: &std::path::Path, identity: (u64, u64)) {
        if Self::identity(path).ok() == Some(identity) {
            let _ = std::fs::remove_dir_all(path);
        }
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        if !self.retained {
            Self::remove_owned(&self.path, self.identity);
        }
    }
}
fn reply(
    output: &mut std::io::Stdout,
    request: &Request,
    result: Result<Value>,
    owner: &Ownership,
) -> Result<()> {
    let response = Response {
        id: request.id,
        ok: result.is_ok(),
        kind: result
            .as_ref()
            .err()
            .map(|e| e.kind.clone())
            .unwrap_or_default(),
        body: result.unwrap_or(Value::Null),
        owned: owner.own.iter().copied().collect(),
    };
    write_frame(output, &response).map_err(|_| unsupported())
}
pub async fn run() -> Result<()> {
    let parent = crate::parent_process::Parent::current()?;
    let init: Request = read_frame(&mut std::io::stdin()).map_err(|_| unsupported())?;
    if init.op != "init" || init.marker == 0 {
        return Err(unsupported());
    }
    #[cfg(target_os = "linux")]
    let wayland = std::env::var_os("WAYLAND_DISPLAY").is_some();
    #[cfg(target_os = "windows")]
    let wayland = false;
    #[cfg(target_os = "linux")]
    let clipboard = Clipboard::new(wayland);
    #[cfg(target_os = "windows")]
    let clipboard = Clipboard::default();
    let worker = if wayland {
        None
    } else {
        Watchdog::start_mode_native(
            "--input-worker",
            init.marker,
            json!({"clipboard_owner_window":clipboard.owner_window()}),
        )
        .ok()
    };
    let mut mirror = if worker.is_some() {
        Native::new(init.marker).ok()
    } else {
        None
    };
    if let Some(driver) = mirror.as_mut() {
        driver.guard_releases(false);
    }
    let (send, receive) = std::sync::mpsc::channel::<Request>();
    std::thread::spawn(move || {
        let mut input = std::io::stdin();
        while let Ok(request) = read_frame(&mut input) {
            if send.send(request).is_err() {
                break;
            }
        }
    });
    let mut output = std::io::stdout();
    let mut owner = Ownership::default();
    reply(
        &mut output,
        &init,
        Ok(
            json!({"input_available":worker.as_ref().is_some_and(Watchdog::available)&&mirror.as_ref().is_some_and(Driver::available)}),
        ),
        &owner,
    )?;
    let mut roots = BTreeMap::<String, Root>::new();
    let mut lease = None;
    let mut fallback_input_lease = None;
    let mut last = Instant::now();
    let mut stopped = false;
    let mut cleanup_started = false;
    let mut mirror_cleanup = false;
    let mut releasing = false;
    loop {
        if let Some(driver) = mirror.as_mut() {
            match driver.events() {
                Ok(events) => {
                    for event in events {
                        if !event.owned {
                            owner.physical(event.item, event.source, event.down);
                        }
                    }
                }
                Err(_) => {
                    stopped = true;
                    mirror = None;
                }
            }
        }
        let worker_alive = worker.as_ref().is_some_and(Watchdog::alive);
        if worker.is_some() && !worker_alive {
            stopped = true;
            mirror_cleanup = true;
        }
        if !mirror_cleanup {
            if let Some(worker) = &worker {
                owner.own = worker.owned().into_iter().collect();
            }
        }
        let request = receive.recv_timeout(Duration::from_millis(5));
        match request {
            Ok(request) => {
                last = Instant::now();
                let result = if stopped || request.marker != init.marker {
                    Err(unsupported())
                } else {
                    (async {
                        match request.op.as_str() {
                            "heartbeat" => Ok(Value::Null),
                            #[cfg(all(target_os="linux",debug_assertions))]
                            "clipboard_grab_fixture" => {clipboard.test_grab()?;Ok(Value::Null)},
                            "private_root" => {
                                let purpose = request.body["purpose"]
                                    .as_str()
                                    .filter(|p| p.len() <= 256 && !p.is_empty())
                                    .ok_or_else(unsupported)?;
                                if !roots.contains_key(purpose) {
                                    roots.insert(purpose.into(), Root::create()?);
                                }
                                Ok(json!({"path":roots[purpose].path,"identity":roots[purpose].identity}))
                            }
                            "remove_root" => {
                                if let Some(purpose) = request.body["purpose"].as_str() {
                                    roots.remove(purpose);
                                }
                                Ok(Value::Null)
                            }
                            "retain_root" => {
                                let path = request.body["path"].as_str().ok_or_else(unsupported)?;
                                let root = roots.values_mut().find(|root| root.path == std::path::Path::new(path)).ok_or_else(unsupported)?;
                                if Root::identity(&root.path)? != root.identity { return Err(unsupported()); }
                                root.retained = true;
                                Ok(json!({"path":root.path,"retained":true}))
                            }
                            "clipboard_status" => {
                                let backup_ready=worker.as_ref().is_some_and(Watchdog::alive);
                                let recovery=if wayland {
                                    json!({"state":"unavailable","reason":"Wayland data-control has no verified cross-process selection-generation receipt; guardian loss leaves restoration unknown"})
                                } else if !backup_ready {
                                    json!({"state":"unavailable","reason":"native clipboard backup worker is unavailable"})
                                } else {
                                    #[cfg(target_os="linux")]
                                    let value=json!({"state":"available","backend":"xfixes_exact_writer_close","unknown_owner":"leave_unchanged"});
                                    #[cfg(target_os="windows")]
                                    let value=json!({"state":"available","backend":"committed_native_marker_sequence_owner","uncommitted_write":"unknown","reason":"a writer killed before its commit receipt cannot be proven; leave the clipboard unchanged"});
                                    value
                                };
                                Ok(json!({"available":available(&clipboard).await && (wayland||backup_ready),"crash_recovery":recovery}))
                            }
                            "clipboard_read" => {
                                clipboard
                                    .read(crate::backend::required(&request.body, "session_id")?)
                                    .await
                            }
                            "clipboard_write" => {
                                clipboard
                                    .write_guarded(
                                        crate::backend::required(&request.body, "session_id")?,
                                        &request.body,
                                        worker.as_ref(),
                                    )
                                    .await
                            }
                            "clipboard_release" => {
                                clipboard
                                    .release(
                                        crate::backend::required(&request.body, "session_id")?,
                                        request.body["handle"].as_str(),
                                    )
                                    .await
                            }
                            "acquire" => {
                                if releasing && !owner.own.is_empty() {
                                    Err(NativeError::new(
                                        "desktop_busy",
                                        "native input cleanup remains pending",
                                    ))
                                } else {
                                    if lease.is_none() {
                                        lease = Some(crate::device_lease::DeviceLease::acquire()?);
                                    }
                                    if let Some(worker) = &worker {
                                        worker.acquire()?;
                                } else if fallback_input_lease.is_none() {
                                    fallback_input_lease=Some(crate::device_lease::DeviceLease::input()?);
                                    }
                                    releasing = false;
                                    Ok(Value::Null)
                                }
                            }
                            "release" => {
                                releasing = true;
                                if let Some(worker) = &worker {
                                    worker.release()?;
                                }
                                Ok(Value::Null)
                            }
                            "hold" | "tap" if lease.is_some() && !releasing => {
                                let item = request.item.ok_or_else(unsupported)?;
                                let worker = worker
                                    .as_ref()
                                    .filter(|w| w.available())
                                    .ok_or_else(unsupported)?;
                                if mirror.as_ref().is_none_or(|m| !m.available()) {
                                    Err(unsupported())
                                } else {
                                    if request.down || request.op == "tap" {
                                        owner.claim(item)?;
                                    }
                                    let result = worker.forward(&request.op, item, request.down);
                                    if worker.alive() {
                                        owner.own = worker.owned().into_iter().collect();
                                    } else {
                                        stopped = true;
                                        mirror_cleanup = true;
                                    }
                                    result
                                }
                            }
                            _ => Err(unsupported()),
                        }
                    })
                    .await
                };
                if reply(&mut output, &request, result, &owner).is_err() {
                    stopped = true;
                }
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                if !stopped {
                    for _ in 0..40 {
                        if !parent.alive() {
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(5));
                    }
                }
                stopped = true;
            }
            Err(_) => {}
        }
        if last.elapsed() > Duration::from_secs(5) {
            stopped = true;
        }
        if stopped && !cleanup_started {
            // Kill the exact native image before final release: a suspended parent must
            // never resume an already acknowledged native operation after losing its lease.
            parent.terminate();
            cleanup_started = true;
            let _ = clipboard.restore_all().await;
            roots.clear();
            if let Some(worker) = &worker {
                if worker.alive() {
                    let _ = worker.release();
                } else {
                    mirror_cleanup = true;
                }
            }
        }
        if mirror_cleanup {
            owner.stop();
            if let Some(driver) = mirror.as_mut() {
                driver.guard_releases(true);
                for item in owner.ready() {
                    if driver.inject(item, false).is_ok() {
                        owner.released(item);
                    }
                }
            }
        } else if let Some(worker) = &worker {
            owner.own = worker.owned().into_iter().collect();
        }
        if (releasing || stopped) && owner.own.is_empty() {
            lease.take();
            fallback_input_lease.take();
            releasing = false;
        }
        if stopped && owner.own.is_empty() && !clipboard.retains_selection() {
            break;
        }
        if stopped {
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    Ok(())
}
