//! Private, independent input owner. It survives the main helper to release injected holds.
use crate::backend::{NativeError, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::{Read, Write},
    process::{ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum Item {
    Key(u16),
    Button(u16),
}
#[derive(Serialize, Deserialize)]
pub(crate) struct Request {
    pub id: u64,
    pub op: String,
    pub marker: usize,
    pub item: Option<Item>,
    pub down: bool,
    #[serde(default)]
    pub body: serde_json::Value,
}
#[derive(Serialize, Deserialize)]
pub(crate) struct Response {
    pub id: u64,
    pub ok: bool,
    pub kind: String,
    #[serde(default)]
    pub body: serde_json::Value,
    #[serde(default)]
    pub owned: Vec<Item>,
}
fn unsupported() -> NativeError {
    NativeError::new(
        "capability_unsupported",
        "native input watchdog or physical-source tracking is unavailable",
    )
}
pub(crate) fn read_frame<R: Read, T: serde::de::DeserializeOwned>(
    reader: &mut R,
) -> std::io::Result<T> {
    let mut header = [0; 4];
    reader.read_exact(&mut header)?;
    let length = u32::from_le_bytes(header) as usize;
    if length > 8 * 1024 * 1024 {
        return Err(std::io::ErrorKind::InvalidData.into());
    }
    let mut bytes = vec![0; length];
    reader.read_exact(&mut bytes)?;
    serde_json::from_slice(&bytes).map_err(|_| std::io::ErrorKind::InvalidData.into())
}
pub(crate) fn write_frame<W: Write, T: Serialize>(
    writer: &mut W,
    value: &T,
) -> std::io::Result<()> {
    let bytes = serde_json::to_vec(value).map_err(|_| std::io::ErrorKind::InvalidData)?;
    if bytes.len() > 8 * 1024 * 1024 {
        return Err(std::io::ErrorKind::InvalidData.into());
    }
    writer.write_all(&(bytes.len() as u32).to_le_bytes())?;
    writer.write_all(&bytes)?;
    writer.flush()
}
struct Control {
    input: Option<ChildStdin>,
    replies: std::sync::mpsc::Receiver<Response>,
    next: u64,
    last: serde_json::Value,
    owned: Vec<Item>,
}
struct Inner {
    control: Mutex<Control>,
    alive: AtomicBool,
    input: AtomicBool,
    marker: usize,
    roots: Mutex<std::collections::BTreeMap<std::path::PathBuf, (u64, u64)>>,
}
impl Inner {
    fn request(
        &self,
        op: &str,
        item: Option<Item>,
        down: bool,
        body: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let mut control = self.control.lock().map_err(|_| unsupported())?;
        let id = control.next;
        control.next = control.next.wrapping_add(1);
        let request = Request {
            id,
            op: op.into(),
            marker: self.marker,
            item,
            down,
            body,
        };
        let result = (|| {
            write_frame(control.input.as_mut().ok_or_else(unsupported)?, &request)
                .map_err(|_| unsupported())?;
            let response = control
                .replies
                .recv_timeout(Duration::from_secs(2))
                .map_err(|_| unsupported())?;
            if response.id != id {
                return Err(unsupported());
            }
            control.owned = response.owned;
            control.last = response.body.clone();
            if op == "private_root" && response.ok {
                if let (Some(path), Some(device), Some(inode)) = (
                    response.body["path"].as_str(),
                    response.body["identity"][0].as_u64(),
                    response.body["identity"][1].as_u64(),
                ) {
                    self.roots
                        .lock()
                        .map_err(|_| unsupported())?
                        .insert(path.into(), (device, inode));
                }
            }
            if op == "retain_root" && response.ok {
                if let Some(path) = response.body["path"].as_str() {
                    self.roots
                        .lock()
                        .map_err(|_| unsupported())?
                        .remove(std::path::Path::new(path));
                }
            }
            if !response.ok {
                return Err(NativeError::new(
                    &response.kind,
                    "native input claim was rejected",
                ));
            }
            Ok(response.body)
        })();
        if result
            .as_ref()
            .is_err_and(|error| error.kind == "capability_unsupported")
        {
            self.alive.store(false, Ordering::Release);
            control.input.take();
        }
        result
    }
}
#[derive(Clone)]
pub struct Watchdog {
    inner: Arc<Inner>,
}
impl Watchdog {
    pub fn start() -> Result<Self> {
        let marker = uuid::Uuid::new_v4().as_u128() as usize | 1;
        Self::start_mode("--input-watchdog", marker)
    }
    pub(crate) fn start_mode(mode: &str, marker: usize) -> Result<Self> {
        Self::start_mode_native(mode, marker, serde_json::Value::Null)
    }
    pub(crate) fn start_mode_native(
        mode: &str,
        marker: usize,
        body: serde_json::Value,
    ) -> Result<Self> {
        let mut command = Command::new(std::env::current_exe().map_err(|_| unsupported())?);
        command
            .arg(mode)
            .env_clear()
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        for key in [
            "DISPLAY",
            "XAUTHORITY",
            "WAYLAND_DISPLAY",
            "XDG_RUNTIME_DIR",
            "SYSTEMROOT",
            "WINDIR",
        ] {
            if let Some(value) = std::env::var_os(key) {
                command.env(key, value);
            }
        }
        let mut child = command.spawn().map_err(|_| unsupported())?;
        let input = child.stdin.take().ok_or_else(unsupported)?;
        let mut output = child.stdout.take().ok_or_else(unsupported)?;
        let (sender, replies) = std::sync::mpsc::channel();
        let inner = Arc::new(Inner {
            control: Mutex::new(Control {
                input: Some(input),
                replies,
                next: 0,
                last: serde_json::Value::Null,
                owned: Vec::new(),
            }),
            alive: AtomicBool::new(true),
            input: AtomicBool::new(false),
            marker,
            roots: Mutex::new(Default::default()),
        });
        let monitored = Arc::downgrade(&inner);
        #[cfg(any(target_os = "linux", target_os = "windows"))]
        let guardian_mode = mode == "--input-watchdog";
        std::thread::spawn(move || {
            while let Ok(response) = read_frame(&mut output) {
                if sender.send(response).is_err() {
                    break;
                }
            }
            if let Some(inner) = monitored.upgrade() {
                inner.alive.store(false, Ordering::Release);
                #[cfg(any(target_os = "linux", target_os = "windows"))]
                if guardian_mode {
                    // The injection worker survives this guardian and releases via EOF.
                    // Fence this helper immediately; its audio handles close on exit.
                    if let Ok(roots) = inner.roots.lock() {
                        for (path, identity) in roots.iter() {
                            crate::input_guardian::Root::remove_owned(path, *identity);
                        }
                    }
                    std::process::exit(70);
                }
            }
            let _ = child.wait();
        });
        let initialized = inner.request("init", None, false, body)?;
        inner.input.store(
            initialized["input_available"].as_bool().unwrap_or(true),
            Ordering::Release,
        );
        let weak = Arc::downgrade(&inner);
        std::thread::spawn(move || loop {
            std::thread::sleep(Duration::from_millis(250));
            let Some(inner) = weak.upgrade() else {
                break;
            };
            if inner
                .request("heartbeat", None, false, serde_json::Value::Null)
                .is_err()
            {
                break;
            }
        });
        Ok(Self { inner })
    }
    pub fn available(&self) -> bool {
        self.alive() && self.inner.input.load(Ordering::Acquire)
    }
    pub fn alive(&self) -> bool {
        self.inner.alive.load(Ordering::Acquire)
    }
    #[cfg(target_os = "windows")]
    pub fn marker(&self) -> usize {
        self.inner.marker
    }
    pub fn hold(&self, item: Item, down: bool) -> Result<()> {
        self.inner
            .request("hold", Some(item), down, serde_json::Value::Null)
            .map(|_| ())
    }
    #[cfg(target_os = "windows")]
    pub fn tap(&self, item: Item) -> Result<()> {
        self.inner
            .request("tap", Some(item), false, serde_json::Value::Null)
            .map(|_| ())
    }
    pub fn release(&self) -> Result<()> {
        self.inner
            .request("release", None, false, serde_json::Value::Null)
            .map(|_| ())
    }
    pub fn acquire(&self) -> Result<()> {
        self.inner
            .request("acquire", None, false, serde_json::Value::Null)
            .map(|_| ())
    }
    pub fn call(&self, op: &str, body: serde_json::Value) -> Result<serde_json::Value> {
        self.inner.request(op, None, false, body)
    }
    pub(crate) fn forward(&self, op: &str, item: Item, down: bool) -> Result<serde_json::Value> {
        self.inner
            .request(op, Some(item), down, serde_json::Value::Null)
    }
    pub fn owned(&self) -> Vec<Item> {
        self.inner
            .control
            .lock()
            .map(|control| control.owned.clone())
            .unwrap_or_default()
    }
    pub fn private_root(&self, purpose: &str) -> Result<std::path::PathBuf> {
        let value = self.call("private_root", serde_json::json!({"purpose":purpose}))?;
        value["path"]
            .as_str()
            .map(std::path::PathBuf::from)
            .ok_or_else(unsupported)
    }
    pub fn clipboard(
        &self,
        id: &str,
        method: &str,
        params: &serde_json::Value,
    ) -> Result<serde_json::Value> {
        let mut body = params.clone();
        if !body.is_object() {
            body = serde_json::json!({});
        }
        body["session_id"] = serde_json::json!(id);
        self.call(method, body)
    }
    pub fn clipboard_crash_recovery(&self) -> serde_json::Value {
        self.call("clipboard_status",serde_json::Value::Null).ok()
            .and_then(|value|value.get("crash_recovery").cloned())
            .unwrap_or_else(||serde_json::json!({"state":"unavailable","reason":"native resource guardian is unavailable"}))
    }
    pub fn clipboard_available(&self) -> bool {
        self.call("clipboard_status", serde_json::Value::Null)
            .ok()
            .is_some_and(|value| value["available"] == true)
    }
}

#[derive(Default)]
pub struct Ownership {
    pub own: BTreeSet<Item>,
    pending: BTreeSet<Item>,
    physical: BTreeMap<Item, BTreeSet<u64>>,
}
impl Ownership {
    pub fn physical(&mut self, item: Item, source: u64, down: bool) {
        if down {
            self.physical.entry(item).or_default().insert(source);
        } else if let Some(sources) = self.physical.get_mut(&item) {
            sources.remove(&source);
            if sources.is_empty() {
                self.physical.remove(&item);
            }
        }
    }
    pub fn claim(&mut self, item: Item) -> Result<bool> {
        if self.physical.contains_key(&item) {
            return Err(NativeError::new(
                "input_busy",
                "the user already holds this native input",
            ));
        }
        self.pending.remove(&item);
        Ok(self.own.insert(item))
    }
    pub fn observed_owned(&mut self, item: Item, down: bool) {
        if down {
            self.own.insert(item);
        } else {
            self.own.remove(&item);
            self.pending.remove(&item);
        }
    }
    pub fn release_item(&mut self, item: Item) {
        if self.own.contains(&item) {
            self.pending.insert(item);
        }
    }
    pub fn stop(&mut self) {
        self.pending.extend(&self.own);
    }
    pub fn ready(&self) -> Vec<Item> {
        self.pending
            .iter()
            .filter(|item| !self.physical.contains_key(item))
            .copied()
            .collect()
    }
    pub fn released(&mut self, item: Item) {
        self.own.remove(&item);
        self.pending.remove(&item);
    }
}
pub struct Event {
    pub item: Item,
    pub source: u64,
    pub down: bool,
    pub owned: bool,
}
pub trait Driver {
    fn events(&mut self) -> Result<Vec<Event>>;
    fn inject(&mut self, item: Item, down: bool) -> Result<()>;
    fn available(&self) -> bool;
    fn guard_releases(&mut self, _: bool) {}
}
#[cfg(any(target_os = "windows", target_os = "linux"))]
pub fn worker() -> Result<()> {
    let parent = crate::parent_process::Parent::current()?;
    let init: Request = read_frame(&mut std::io::stdin()).map_err(|_| unsupported())?;
    if init.op != "init" || init.marker == 0 {
        return Err(unsupported());
    }
    #[cfg(target_os = "linux")]
    let mut clipboard = crate::linux_clipboard::Backup::new(&init.body)?;
    #[cfg(target_os = "windows")]
    let mut clipboard = crate::windows_clipboard::Backup::new(&init.body)?;
    #[cfg(target_os = "linux")]
    let mut driver = crate::linux_watchdog::Native::new(init.marker)?;
    #[cfg(target_os = "windows")]
    let mut driver = crate::windows_watchdog::Native::new(init.marker)?;
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
    write_frame(
        &mut output,
        &Response {
            id: init.id,
            ok: true,
            kind: String::new(),
            body: serde_json::json!({"input_available":true}),
            owned: Vec::new(),
        },
    )
    .map_err(|_| unsupported())?;
    let mut owner = Ownership::default();
    let mut lease = None;
    let mut releasing = false;
    let mut stopped = false;
    let mut last = Instant::now();
    let mut resources_restored = false;
    loop {
        for event in match driver.events() {
            Ok(events) => events,
            Err(error) => {
                owner.stop();
                return Err(error);
            }
        } {
            if event.owned {
                if event.source == u64::MAX {
                    owner.release_item(event.item);
                } else {
                    owner.observed_owned(event.item, event.down);
                }
            } else {
                owner.physical(event.item, event.source, event.down);
            }
        }
        match receive.recv_timeout(Duration::from_millis(5)) {
            Ok(request) => {
                last = Instant::now();
                let result = if request.marker != init.marker || stopped || !driver.available() {
                    Err(unsupported())
                } else {
                    (|| match request.op.as_str() {
                        "heartbeat" => Ok(()),
                        "clipboard_backup_prepare" => clipboard.prepare(&request.body),
                        "clipboard_backup_commit" => clipboard.commit(&request.body),
                        "acquire" => {
                            if releasing && !owner.own.is_empty() {
                                Err(NativeError::new(
                                    "desktop_busy",
                                    "owned input release is pending",
                                ))
                            } else if lease.is_none() {
                                lease = Some(crate::device_lease::DeviceLease::input()?);
                                releasing = false;
                                Ok(())
                            } else {
                                Ok(())
                            }
                        }
                        "release" => {
                            owner.stop();
                            releasing = true;
                            Ok(())
                        }
                        "hold" if lease.is_some() && !releasing => {
                            if let Some(item) = request.item {
                                if request.down {
                                    match owner.claim(item) {
                                        Ok(true) => driver.inject(item, true),
                                        Ok(false) => Ok(()),
                                        Err(error) => Err(error),
                                    }
                                } else {
                                    owner.release_item(item);
                                    Ok(())
                                }
                            } else {
                                Err(unsupported())
                            }
                        }
                        "tap" if lease.is_some() && !releasing => {
                            if let Some(item) = request.item {
                                if owner.own.contains(&item) {
                                    Err(NativeError::new(
                                        "input_busy",
                                        "release the owned input before tapping",
                                    ))
                                } else {
                                    match owner.claim(item) {
                                        Ok(true) => {
                                            let result = driver.inject(item, true);
                                            owner.release_item(item);
                                            result
                                        }
                                        Ok(false) => Err(unsupported()),
                                        Err(error) => Err(error),
                                    }
                                }
                            } else {
                                Err(unsupported())
                            }
                        }
                        _ => Err(unsupported()),
                    })()
                };
                for item in owner.ready() {
                    match driver.inject(item, false) {
                        Ok(()) => owner.released(item),
                        Err(error) if error.kind == "input_deferred" => {}
                        Err(_) => {
                            stopped = true;
                            owner.stop();
                        }
                    }
                }
                let response = Response {
                    id: request.id,
                    ok: result.is_ok(),
                    kind: result.err().map(|error| error.kind).unwrap_or_default(),
                    body: serde_json::Value::Null,
                    owned: owner.own.iter().copied().collect(),
                };
                let _ = write_frame(&mut output, &response);
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                stopped = true;
                owner.stop();
                std::thread::sleep(Duration::from_millis(5));
            }
            Err(_) => {}
        }
        if Instant::now().duration_since(last) > Duration::from_secs(5) {
            stopped = true;
            owner.stop();
        }
        for item in owner.ready() {
            match driver.inject(item, false) {
                Ok(()) => owner.released(item),
                Err(error) if error.kind == "input_deferred" => {}
                Err(_) => {
                    stopped = true;
                    owner.stop();
                }
            }
        }
        if releasing && owner.own.is_empty() {
            lease.take();
            releasing = false;
        }
        if stopped && !resources_restored {
            // EOF may precede the normal guardian exit by a few instructions.
            // Pinning the real parent prevents restoring while any old writer can resume.
            for _ in 0..40 {
                if !parent.alive() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(5));
            }
            parent.terminate();
            if !parent.alive() {
                if clipboard.restore().is_ok() {
                    resources_restored = true;
                }
            }
        }
        if stopped && owner.own.is_empty() {
            lease.take();
            if resources_restored && !clipboard.retains_selection() {
                break;
            }
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn physical_same_key_defers_only_our_release() {
        let item = Item::Key(42);
        let mut state = Ownership::default();
        assert!(state.claim(item).unwrap());
        state.physical(item, 7, true);
        state.stop();
        assert!(state.ready().is_empty());
        state.physical(item, 8, true);
        state.physical(item, 7, false);
        assert!(state.ready().is_empty());
        state.physical(item, 8, false);
        assert_eq!(state.ready(), vec![item]);
        state.released(item);
        assert!(state.own.is_empty());
    }
    #[test]
    fn already_physical_input_cannot_be_claimed() {
        let mut state = Ownership::default();
        let item = Item::Button(1);
        state.physical(item, 2, true);
        assert!(state.claim(item).is_err());
        assert!(state.own.is_empty());
    }
}
