//! Clipboard snapshots retain every native MIME target and restore only while still owned.
use crate::{
    backend::{required, NativeError, Result},
    linux_clipboard_x11::{Data, X11},
};
use serde_json::{json, Value};
use std::{
    io::Read,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tokio::sync::Mutex;
const LIMIT: usize = 8 * 1024 * 1024;
enum Saved {
    X11(u32, Vec<Data>),
    Wayland(String, Vec<(String, Vec<u8>)>),
}
struct Snapshot {
    owner: String,
    handle: String,
    previous: Saved,
    written: bool,
    offer: Option<Arc<AtomicBool>>,
}
pub struct Clipboard {
    native: Option<Arc<X11>>,
    wayland: bool,
    state: Mutex<Option<Snapshot>>,
    restored_offer: std::sync::Mutex<Option<Arc<AtomicBool>>>,
}
impl Clipboard {
    pub async fn restore_all(&self) -> Result<()> {
        let owner = self
            .state
            .lock()
            .await
            .as_ref()
            .map(|snapshot| snapshot.owner.clone());
        if let Some(owner) = owner {
            self.release(&owner, None).await?;
        }
        Ok(())
    }
    pub fn retains_selection(&self) -> bool {
        if self.wayland {
            return self.restored_offer.lock().ok().is_some_and(|offer| {
                offer
                    .as_ref()
                    .is_some_and(|offer| offer.load(Ordering::Acquire))
            });
        }
        self.native
            .as_ref()
            .is_some_and(|native| native.ours().unwrap_or(false))
    }
    pub fn new(wayland: bool) -> Self {
        Self {
            native: if wayland {
                None
            } else {
                X11::new().ok().map(Arc::new)
            },
            wayland,
            state: Mutex::new(None),
            restored_offer: std::sync::Mutex::new(None),
        }
    }
    pub async fn available(&self) -> bool {
        if self.wayland {
            tokio::task::spawn_blocking(|| {
                let Ok(seat) = crate::linux_clipboard_seat::exact_seat() else {
                    return false;
                };
                wl_clipboard_rs::paste::get_mime_types(
                    wl_clipboard_rs::paste::ClipboardType::Regular,
                    wl_clipboard_rs::paste::Seat::Specific(&seat),
                )
                .map(|_| true)
                .or_else(|error| match error {
                    wl_clipboard_rs::paste::Error::ClipboardEmpty => Ok(true),
                    other => Err(other),
                })
                .unwrap_or(false)
            })
            .await
            .unwrap_or(false)
        } else {
            self.native.is_some()
        }
    }
    async fn snapshot(&self) -> Result<Saved> {
        if self.wayland {
            tokio::task::spawn_blocking(wayland_snapshot)
                .await
                .map_err(|_| unavailable())?
                .map(|(seat, data)| Saved::Wayland(seat, data))
        } else {
            let native = self.native.clone().ok_or_else(unavailable)?;
            tokio::task::spawn_blocking(move || native.snapshot())
                .await
                .map_err(|_| unavailable())?
                .map(|(owner, data)| Saved::X11(owner, data))
        }
    }
    async fn ours(&self, snapshot: &Snapshot) -> Result<bool> {
        if self.wayland {
            Ok(snapshot
                .offer
                .as_ref()
                .is_some_and(|offer| offer.load(Ordering::Acquire)))
        } else {
            self.native.as_ref().ok_or_else(unavailable)?.ours()
        }
    }
    async fn install(
        &self,
        saved: Saved,
        expected_owner: Option<u32>,
    ) -> Result<Option<Arc<AtomicBool>>> {
        match saved {
            Saved::X11(_, data) => {
                self.native
                    .as_ref()
                    .ok_or_else(unavailable)?
                    .install(data, expected_owner.ok_or_else(unavailable)?)?;
                Ok(None)
            }
            Saved::Wayland(seat, data) => wayland_install(seat, data).await.map(Some),
        }
    }
    pub async fn read(&self, id: &str) -> Result<Value> {
        let mut state = self.state.lock().await;
        if state.as_ref().is_some_and(|snapshot| snapshot.owner != id) {
            return Err(NativeError::new(
                "clipboard_busy",
                "another session owns this clipboard snapshot",
            ));
        }
        let saved = self.snapshot().await?;
        let (text, formats) = self.describe(&saved)?;
        if state.is_none() {
            *state = Some(Snapshot {
                owner: id.into(),
                handle: uuid::Uuid::new_v4().to_string(),
                previous: saved,
                written: false,
                offer: None,
            });
        }
        Ok(
            json!({"handle":state.as_ref().unwrap().handle,"text":text,"formats":formats,"restore_lifetime":"native_selection_owner"}),
        )
    }
    fn describe(&self, saved: &Saved) -> Result<(Option<String>, Vec<String>)> {
        let values = match saved {
            Saved::Wayland(_, data) => data.clone(),
            Saved::X11(_, data) => {
                let native = self.native.as_ref().ok_or_else(unavailable)?;
                data.iter()
                    .map(|data| Ok((native.name(data.target)?, data.bytes.clone())))
                    .collect::<Result<Vec<_>>>()?
            }
        };
        let text = ["text/plain;charset=utf-8", "UTF8_STRING", "text/plain"]
            .into_iter()
            .find_map(|mime| {
                values
                    .iter()
                    .find(|(name, _)| name == mime)
                    .and_then(|(_, bytes)| String::from_utf8(bytes.clone()).ok())
            });
        Ok((text, values.into_iter().map(|(name, _)| name).collect()))
    }
    #[cfg(debug_assertions)]
    pub fn test_grab(&self) -> Result<()> {
        self.native.as_ref().ok_or_else(unavailable)?.test_grab()
    }
    pub fn owner_window(&self) -> usize {
        self.native
            .as_ref()
            .map(|native| native.owned_id() as usize)
            .unwrap_or(0)
    }
    pub async fn write_guarded(
        &self,
        id: &str,
        request: &Value,
        backup: Option<&crate::input_watchdog::Watchdog>,
    ) -> Result<Value> {
        let text = required(request, "text")?;
        if text.len() > LIMIT {
            return Err(NativeError::new(
                "clipboard_too_large",
                "clipboard content exceeds budget",
            ));
        }
        let format = request["format"].as_str().unwrap_or("text");
        if !matches!(format, "text" | "md" | "html") {
            return Err(NativeError::new(
                "invalid_params",
                "invalid clipboard format",
            ));
        }
        let mut state = self.state.lock().await;
        if state.as_ref().is_some_and(|snapshot| snapshot.owner != id) {
            return Err(NativeError::new(
                "clipboard_busy",
                "another session owns the native clipboard",
            ));
        }
        if state.is_none() {
            *state = Some(Snapshot {
                owner: id.into(),
                handle: uuid::Uuid::new_v4().to_string(),
                previous: self.snapshot().await?,
                written: false,
                offer: None,
            });
        }
        let snapshot = state.as_mut().unwrap();
        if !snapshot.written {
            snapshot.previous = self.snapshot().await?;
        }
        if snapshot.written && !self.ours(snapshot).await? {
            return Err(NativeError::new(
                "clipboard_changed",
                "the user replaced the clipboard",
            ));
        }
        let mut mimes = vec!["text/plain;charset=utf-8".to_owned(), "text/plain".into()];
        if format == "html" {
            mimes.push("text/html".into());
        }
        if format == "md" {
            mimes.push("text/markdown".into());
        }
        let data = if self.wayland {
            let Saved::Wayland(seat, _) = &snapshot.previous else {
                return Err(unavailable());
            };
            Saved::Wayland(
                seat.clone(),
                mimes
                    .into_iter()
                    .map(|mime| (mime, text.as_bytes().to_vec()))
                    .collect(),
            )
        } else {
            mimes.push("UTF8_STRING".into());
            let native = self.native.as_ref().ok_or_else(unavailable)?;
            Saved::X11(
                0,
                mimes
                    .into_iter()
                    .map(|mime| {
                        let target = native.target(&mime)?;
                        Ok(Data {
                            target,
                            type_: target,
                            format: 8,
                            bytes: text.as_bytes().to_vec(),
                        })
                    })
                    .collect::<Result<Vec<_>>>()?,
            )
        };
        let expected_owner = match &snapshot.previous {
            Saved::X11(owner, _) => Some(if snapshot.written {
                self.native.as_ref().ok_or_else(unavailable)?.owned_id()
            } else {
                *owner
            }),
            Saved::Wayland(_, _) => None,
        };
        if let Saved::X11(_, previous) = &snapshot.previous {
            let backup = backup.ok_or_else(unavailable)?;
            let meta = previous
                .iter()
                .map(|data| {
                    json!({"target":data.target,"type_":data.type_,
                "format":data.format,"size":data.bytes.len()})
                })
                .collect::<Vec<_>>();
            backup.call(
                "clipboard_backup_prepare",
                json!({"phase":"begin",
                "generation":snapshot.handle,"writer":self.owner_window(),"formats":meta}),
            )?;
            for (index, data) in previous.iter().enumerate() {
                for bytes in data.bytes.chunks(256 * 1024) {
                    backup.call(
                        "clipboard_backup_prepare",
                        json!({"phase":"chunk","index":index,"bytes":bytes}),
                    )?;
                }
            }
            backup.call("clipboard_backup_prepare", json!({"phase":"complete"}))?;
        }
        snapshot.offer = self.install(data, expected_owner).await?;
        snapshot.written = true;
        Ok(json!({"handle":snapshot.handle,"format":format,"ok":true}))
    }
    pub async fn release(&self, id: &str, handle: Option<&str>) -> Result<Value> {
        let mut state = self.state.lock().await;
        let Some(snapshot) = state.as_ref() else {
            return Ok(json!({"restored":false}));
        };
        if snapshot.owner != id || handle.is_some_and(|handle| handle != snapshot.handle) {
            return Err(NativeError::new(
                "clipboard_owner_mismatch",
                "clipboard snapshot belongs to another session",
            ));
        }
        let restore = snapshot.written && self.ours(snapshot).await?;
        let snapshot = state.take().unwrap();
        let written = snapshot.written;
        if restore {
            let expected = self.native.as_ref().map(|native| native.owned_id());
            let offer = self.install(snapshot.previous, expected).await?;
            *self.restored_offer.lock().map_err(|_| unavailable())? = offer;
        }
        let mut result = json!({"restored":restore,"restore_lifetime":"native_selection_owner"});
        if self.wayland && written && !restore {
            result["restoration_state"] = json!("unknown");
            result["reason"] = json!(
                "the original Wayland selection source is lost and its generation cannot be verified; leave the clipboard unchanged"
            );
        }
        Ok(result)
    }
}
fn unavailable() -> NativeError {
    NativeError::new(
        "capability_unsupported",
        "native clipboard selection protocol is unavailable",
    )
}
fn wayland_snapshot() -> Result<(String, Vec<(String, Vec<u8>)>)> {
    use wl_clipboard_rs::paste::{get_contents, get_mime_types, ClipboardType, MimeType, Seat};
    let seat = crate::linux_clipboard_seat::exact_seat()?;
    let types = match get_mime_types(ClipboardType::Regular, Seat::Specific(&seat)) {
        Ok(types) => types,
        Err(wl_clipboard_rs::paste::Error::ClipboardEmpty) => return Ok((seat, Vec::new())),
        Err(_) => return Err(unavailable()),
    };
    if types.len() > 64 {
        return Err(NativeError::new(
            "clipboard_too_large",
            "too many native clipboard formats",
        ));
    }
    let mut result = Vec::new();
    let mut count = 0;
    for mime in &types {
        let (mut pipe, _) = get_contents(
            ClipboardType::Regular,
            Seat::Specific(&seat),
            MimeType::Specific(mime),
        )
        .map_err(|_| unavailable())?;
        use std::os::fd::AsRawFd;
        let fd = pipe.as_raw_fd();
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
            return Err(unavailable());
        }
        let mut bytes = Vec::new();
        let deadline = Instant::now() + Duration::from_secs(3);
        let mut buffer = [0; 65536];
        loop {
            if Instant::now() >= deadline {
                return Err(NativeError::new(
                    "clipboard_timeout",
                    "native selection producer did not finish",
                ));
            }
            match pipe.read(&mut buffer) {
                Ok(0) => break,
                Ok(n) => {
                    bytes.extend(&buffer[..n]);
                    if count + bytes.len() > LIMIT {
                        return Err(NativeError::new(
                            "clipboard_too_large",
                            "native selection exceeds budget",
                        ));
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(2))
                }
                Err(_) => return Err(unavailable()),
            }
        }
        count += bytes.len();
        if count > LIMIT {
            return Err(NativeError::new(
                "clipboard_too_large",
                "native clipboard snapshot exceeds budget",
            ));
        }
        result.push((mime.clone(), bytes));
    }
    let final_types =
        get_mime_types(ClipboardType::Regular, Seat::Specific(&seat)).map_err(|_| unavailable())?;
    if final_types != types {
        return Err(NativeError::new(
            "clipboard_changed",
            "native formats changed while preserving the clipboard",
        ));
    }
    Ok((seat, result))
}
async fn wayland_install(seat: String, data: Vec<(String, Vec<u8>)>) -> Result<Arc<AtomicBool>> {
    use wl_clipboard_rs::copy::{MimeSource, MimeType, Options, Source};
    let active = Arc::new(AtomicBool::new(false));
    if data.is_empty() {
        tokio::task::spawn_blocking(move || {
            wl_clipboard_rs::copy::clear(
                wl_clipboard_rs::copy::ClipboardType::Regular,
                wl_clipboard_rs::copy::Seat::Specific(seat),
            )
        })
        .await
        .map_err(|_| unavailable())?
        .map_err(|_| unavailable())?;
        return Ok(active);
    }
    let flag = active.clone();
    let (ready, sent) = tokio::sync::oneshot::channel();
    std::thread::Builder::new()
        .name("memstack-cua-wayland-clipboard".into())
        .spawn(move || {
            let mut options = Options::new();
            options.foreground(true);
            options.seat(wl_clipboard_rs::copy::Seat::Specific(seat));
            let prepared = options.prepare_copy_multi(
                data.into_iter()
                    .map(|(mime, bytes)| MimeSource {
                        source: Source::Bytes(bytes.into()),
                        mime_type: MimeType::Specific(mime),
                    })
                    .collect(),
            );
            match prepared {
                Ok(offer) => {
                    flag.store(true, Ordering::Release);
                    let _ = ready.send(Ok(()));
                    let _ = offer.serve();
                    flag.store(false, Ordering::Release);
                }
                Err(_) => {
                    let _ = ready.send(Err(unavailable()));
                }
            }
        })
        .map_err(|_| unavailable())?;
    tokio::time::timeout(Duration::from_secs(5), sent)
        .await
        .map_err(|_| unavailable())?
        .map_err(|_| unavailable())??;
    Ok(active)
}

/// Independent native owner-event observer and a pre-write acknowledged baseline.
/// No guardian X11 connection survives its death; any server grab closes with it.
pub struct Backup {
    native: Arc<X11>,
    writer: u32,
    previous: Option<Vec<Data>>,
    pending: Option<(Vec<Data>, Vec<usize>)>,
}
impl Backup {
    pub fn new(init: &Value) -> Result<Self> {
        let writer = init["clipboard_owner_window"]
            .as_u64()
            .and_then(|id| u32::try_from(id).ok())
            .filter(|id| *id != 0)
            .ok_or_else(unavailable)?;
        let native = Arc::new(X11::new()?);
        native.watch_writer(writer)?;
        Ok(Self {
            native,
            writer,
            previous: None,
            pending: None,
        })
    }
    pub fn prepare(&mut self, body: &Value) -> Result<()> {
        match body["phase"].as_str() {
            Some("begin") => {
                if body["writer"].as_u64() != Some(self.writer as u64)
                    || body["generation"].as_str().is_none()
                {
                    return Err(unavailable());
                }
                let meta = body["formats"]
                    .as_array()
                    .filter(|formats| formats.len() <= 64)
                    .ok_or_else(unavailable)?;
                let mut data = Vec::new();
                let mut sizes = Vec::new();
                let mut total = 0usize;
                for format in meta {
                    let value = |name: &str| {
                        format[name]
                            .as_u64()
                            .and_then(|value| u32::try_from(value).ok())
                            .ok_or_else(unavailable)
                    };
                    let size = value("size")? as usize;
                    total = total
                        .checked_add(size)
                        .filter(|total| *total <= LIMIT)
                        .ok_or_else(unavailable)?;
                    let unit = value("format")?;
                    if !matches!(unit, 8 | 16 | 32) || size % (unit as usize / 8) != 0 {
                        return Err(unavailable());
                    }
                    data.push(Data {
                        target: value("target")?,
                        type_: value("type_")?,
                        format: unit as u8,
                        bytes: Vec::new(),
                    });
                    sizes.push(size);
                }
                self.native.arm_writer(self.writer)?;
                self.pending = Some((data, sizes));
            }
            Some("chunk") => {
                let index = body["index"]
                    .as_u64()
                    .and_then(|index| usize::try_from(index).ok())
                    .ok_or_else(unavailable)?;
                let bytes: Vec<u8> =
                    serde_json::from_value(body["bytes"].clone()).map_err(|_| unavailable())?;
                let (data, sizes) = self.pending.as_mut().ok_or_else(unavailable)?;
                let entry = data.get_mut(index).ok_or_else(unavailable)?;
                if bytes.len() > 256 * 1024
                    || entry
                        .bytes
                        .len()
                        .checked_add(bytes.len())
                        .is_none_or(|len| len > sizes[index])
                {
                    return Err(unavailable());
                }
                entry.bytes.extend(bytes);
            }
            Some("complete") => {
                let (data, sizes) = self.pending.take().ok_or_else(unavailable)?;
                if data
                    .iter()
                    .zip(sizes)
                    .any(|(entry, size)| entry.bytes.len() != size)
                {
                    return Err(unavailable());
                }
                self.previous = Some(data);
            }
            _ => return Err(unavailable()),
        }
        Ok(())
    }
    pub fn commit(&mut self, _: &Value) -> Result<()> {
        Ok(())
    }
    pub fn restore(&mut self) -> Result<bool> {
        let Some(previous) = self.previous.as_ref() else {
            return Ok(false);
        };
        let restored = self.native.restore_closed_writer(previous.clone())?;
        self.previous = None;
        Ok(restored)
    }
    pub fn retains_selection(&self) -> bool {
        self.native.ours().unwrap_or(false)
    }
}
