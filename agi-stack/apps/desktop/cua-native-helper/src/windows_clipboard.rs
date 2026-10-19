//! Session-owned Win32 clipboard snapshots. Preserve all transferable global-memory formats.
use crate::{
    backend::{required, NativeError, Result},
    input_watchdog::Watchdog,
};
use serde_json::{json, Value};
use tokio::sync::Mutex;
use windows::{
    core::w,
    Win32::{
        Foundation::{HANDLE, HGLOBAL, HWND},
        System::{DataExchange::*, Memory::*},
        UI::WindowsAndMessaging::{CreateWindowExW, DestroyWindow, HWND_MESSAGE},
    },
};
const UNICODE: u32 = 13;
const LIMIT: usize = 8 * 1024 * 1024;
const CHUNK: usize = 256 * 1024;
struct Snapshot {
    owner: String,
    handle: String,
    previous: Vec<(u32, Vec<u8>)>,
    sequence: u32,
    written: bool,
    marker: Option<uuid::Uuid>,
}
pub struct Clipboard {
    state: Mutex<Option<Snapshot>>,
    hwnd: usize,
}
impl Default for Clipboard {
    fn default() -> Self {
        // A message-only window provides the clipboard owner required by SetClipboardData.
        let hwnd = unsafe {
            CreateWindowExW(
                Default::default(),
                w!("STATIC"),
                w!("Memstack CUA Clipboard"),
                Default::default(),
                0,
                0,
                0,
                0,
                Some(HWND_MESSAGE),
                None,
                None,
                None,
            )
        }
        .map(|window| window.0 as usize)
        .unwrap_or(0);
        Self {
            state: Mutex::new(None),
            hwnd,
        }
    }
}
impl Drop for Clipboard {
    fn drop(&mut self) {
        if self.hwnd != 0 {
            unsafe {
                let _ = DestroyWindow(HWND(self.hwnd as *mut std::ffi::c_void));
            }
        }
    }
}

struct Open;
impl Open {
    fn new(hwnd: usize) -> Result<Self> {
        if hwnd == 0 {
            return Err(NativeError::new(
                "clipboard_unavailable",
                "native clipboard owner window is unavailable",
            ));
        }
        unsafe { OpenClipboard(Some(HWND(hwnd as *mut std::ffi::c_void))) }.map_err(|_| {
            NativeError::new(
                "clipboard_busy",
                "native clipboard is owned by another application",
            )
        })?;
        Ok(Self)
    }
}
fn unavailable() -> NativeError {
    NativeError::new(
        "clipboard_unavailable",
        "native clipboard recovery is unavailable",
    )
}
fn malformed_backup() -> NativeError {
    NativeError::new("invalid_params", "invalid private native clipboard backup")
}
fn current_owner() -> usize {
    #[link(name = "user32")]
    unsafe extern "system" {
        #[link_name = "GetClipboardOwner"]
        fn owner() -> HWND;
    }
    // SAFETY: GetClipboardOwner takes no arguments and NULL is a valid no-owner result.
    unsafe { owner().0 as usize }
}
fn marker_format() -> Result<u32> {
    // SAFETY: the static, terminated UTF-16 format name remains valid for the call.
    let format = unsafe { RegisterClipboardFormatW(w!("Memstack CUA Cleanup Receipt v1")) };
    if format == 0 {
        Err(unavailable())
    } else {
        Ok(format)
    }
}
unsafe fn native_value(format: u32) -> Result<Vec<u8>> {
    // SAFETY: callers hold OpenClipboard; only transferable HGLOBAL formats reach this function.
    let data = unsafe { GetClipboardData(format) }.map_err(|_| unavailable())?;
    let global = HGLOBAL(data.0);
    // SAFETY: the native clipboard supplied this global-memory handle.
    let size = unsafe { GlobalSize(global) };
    if size == 0 || size > LIMIT {
        return Err(unavailable());
    }
    // SAFETY: the HGLOBAL remains owned by the open clipboard until it is unlocked below.
    let pointer = unsafe { GlobalLock(global) };
    if pointer.is_null() {
        return Err(unavailable());
    }
    // SAFETY: GlobalSize bounds the readable locked allocation, and the copy owns its bytes.
    let value = unsafe { std::slice::from_raw_parts(pointer as *const u8, size) }.to_vec();
    // SAFETY: this balances the successful GlobalLock above.
    unsafe {
        let _ = GlobalUnlock(global);
    }
    Ok(value)
}
impl Drop for Open {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseClipboard();
        }
    }
}
unsafe fn content() -> Result<Vec<(u32, Vec<u8>)>> {
    let mut values = Vec::new();
    let mut format = 0;
    let mut bytes = 0usize;
    loop {
        format = unsafe { EnumClipboardFormats(format) };
        if format == 0 {
            break;
        }
        // Bitmap/metafile/palette handles cannot be preserved as arbitrary global-memory bytes.
        if matches!(format, 2 | 3 | 9 | 14 | 0x80..=0x8e) {
            return Err(NativeError::new(
                "clipboard_format_unsupported",
                "clipboard contains a non-transferable native object",
            ));
        }
        let data = unsafe { GetClipboardData(format) }.map_err(|_| {
            NativeError::new(
                "clipboard_unavailable",
                "cannot preserve native clipboard format",
            )
        })?;
        let global = HGLOBAL(data.0);
        let size = unsafe { GlobalSize(global) };
        bytes = bytes
            .checked_add(size)
            .filter(|n| *n <= LIMIT)
            .ok_or_else(|| {
                NativeError::new("clipboard_too_large", "clipboard exceeds snapshot budget")
            })?;
        if size == 0 {
            return Err(NativeError::new(
                "clipboard_format_unsupported",
                "clipboard format cannot be copied safely",
            ));
        }
        let pointer = unsafe { GlobalLock(global) };
        if pointer.is_null() {
            return Err(NativeError::new(
                "clipboard_unavailable",
                "clipboard memory is unavailable",
            ));
        }
        let value = unsafe { std::slice::from_raw_parts(pointer as *const u8, size) }.to_vec();
        unsafe {
            let _ = GlobalUnlock(global);
        }
        values.push((format, value));
    }
    Ok(values)
}
struct Allocation(Option<HGLOBAL>);
impl Drop for Allocation {
    fn drop(&mut self) {
        if let Some(global) = self.0 {
            // SAFETY: this handle has not transferred to the clipboard service.
            unsafe {
                let _ = windows::Win32::Foundation::GlobalFree(Some(global));
            }
        }
    }
}
unsafe fn install(values: &[(u32, Vec<u8>)]) -> Result<()> {
    let mut allocated = Vec::with_capacity(values.len());
    let mut total = 0usize;
    for (format, bytes) in values {
        total = total
            .checked_add(bytes.len())
            .filter(|size| *size <= LIMIT)
            .ok_or_else(|| {
                NativeError::new(
                    "clipboard_too_large",
                    "clipboard exceeds native allocation budget",
                )
            })?;
        // SAFETY: all requested lengths are bounded; RAII retains ownership until SetClipboardData.
        let global = unsafe { GlobalAlloc(GMEM_MOVEABLE, bytes.len()) }.map_err(|_| {
            NativeError::new("clipboard_unavailable", "cannot allocate clipboard memory")
        })?;
        let allocation = Allocation(Some(global));
        // SAFETY: the allocation above is valid and stays owned through this copy.
        let pointer = unsafe { GlobalLock(global) };
        if pointer.is_null() {
            return Err(NativeError::new(
                "clipboard_unavailable",
                "cannot access clipboard memory",
            ));
        }
        // SAFETY: GlobalAlloc requested bytes.len() writable bytes and the source owns that length.
        unsafe {
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), pointer.cast(), bytes.len());
            let _ = GlobalUnlock(global);
        }
        allocated.push((*format, allocation));
    }
    // SAFETY: caller holds OpenClipboard; allocation failures above leave its old content intact.
    unsafe { EmptyClipboard() }.map_err(|_| {
        NativeError::new("clipboard_unavailable", "cannot replace native clipboard")
    })?;
    for (format, allocation) in &mut allocated {
        let global = allocation.0.ok_or_else(unavailable)?;
        // SAFETY: this open clipboard takes ownership only when SetClipboardData succeeds.
        if unsafe { SetClipboardData(*format, Some(HANDLE(global.0))) }.is_err() {
            return Err(NativeError::new(
                "clipboard_unavailable",
                "clipboard write rejected",
            ));
        }
        allocation.0 = None;
    }
    Ok(())
}
fn text(values: &[(u32, Vec<u8>)]) -> String {
    let Some((_, bytes)) = values.iter().find(|(format, _)| *format == UNICODE) else {
        return String::new();
    };
    let units = bytes
        .chunks_exact(2)
        .map(|b| u16::from_le_bytes([b[0], b[1]]))
        .take_while(|unit| *unit != 0)
        .collect::<Vec<_>>();
    String::from_utf16_lossy(&units)
}
impl Clipboard {
    pub fn owner_window(&self) -> usize {
        self.hwnd
    }
    fn owns(&self, snapshot: &Snapshot) -> Result<bool> {
        if current_owner() != self.hwnd
            || snapshot.sequence != unsafe { GetClipboardSequenceNumber() }
        {
            return Ok(false);
        }
        let Some(marker) = snapshot.marker else {
            return Ok(false);
        };
        let format = marker_format()?;
        // SAFETY: write/release callers retain the native OpenClipboard guard.
        Ok(unsafe { native_value(format) }.is_ok_and(|bytes| bytes == marker.as_bytes()))
    }
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
        false
    }
    pub fn available(&self) -> bool {
        self.hwnd != 0
    }
    pub async fn read(&self, id: &str) -> Result<Value> {
        let mut state = self.state.lock().await;
        let _open = Open::new(self.hwnd)?;
        if state.as_ref().is_some_and(|s| s.owner != id) {
            return Err(NativeError::new(
                "clipboard_busy",
                "another session owns the clipboard snapshot",
            ));
        }
        let values = unsafe { content()? };
        let current = text(&values);
        if state.is_none() {
            *state = Some(Snapshot {
                owner: id.into(),
                handle: uuid::Uuid::new_v4().to_string(),
                previous: values,
                sequence: unsafe { GetClipboardSequenceNumber() },
                written: false,
                marker: None,
            });
        }
        Ok(json!({"handle":state.as_ref().unwrap().handle,"text":current,"format":"text"}))
    }
    pub async fn write_guarded(
        &self,
        id: &str,
        request: &Value,
        backup: Option<&Watchdog>,
    ) -> Result<Value> {
        let backup = backup.ok_or_else(|| NativeError::unsupported("native clipboard backup"))?;
        let source = required(request, "text")?;
        if source.len() > LIMIT {
            return Err(NativeError::new(
                "clipboard_too_large",
                "clipboard text exceeds budget",
            ));
        }
        let format = request["format"].as_str().unwrap_or("text");
        let mut values = match format {
            "text" | "md" => vec![(
                UNICODE,
                source
                    .encode_utf16()
                    .chain([0])
                    .flat_map(u16::to_le_bytes)
                    .collect::<Vec<_>>(),
            )],
            "html" => {
                let html = html_payload(source);
                let native = unsafe { RegisterClipboardFormatW(w!("HTML Format")) };
                if native == 0 {
                    return Err(NativeError::new(
                        "clipboard_unavailable",
                        "HTML clipboard format unavailable",
                    ));
                }
                vec![
                    (native, html),
                    (
                        UNICODE,
                        source
                            .encode_utf16()
                            .chain([0])
                            .flat_map(u16::to_le_bytes)
                            .collect::<Vec<_>>(),
                    ),
                ]
            }
            _ => {
                return Err(NativeError::new(
                    "invalid_params",
                    "invalid clipboard format",
                ));
            }
        };
        let mut state = self.state.lock().await;
        let _open = Open::new(self.hwnd)?;
        if state.as_ref().is_some_and(|s| s.owner != id) {
            return Err(NativeError::new(
                "clipboard_busy",
                "another session owns the clipboard snapshot",
            ));
        }
        if state.is_none() {
            *state = Some(Snapshot {
                owner: id.into(),
                handle: uuid::Uuid::new_v4().to_string(),
                previous: unsafe { content()? },
                sequence: unsafe { GetClipboardSequenceNumber() },
                written: false,
                marker: None,
            });
        }
        let snapshot = state.as_mut().unwrap();
        if !snapshot.written {
            snapshot.previous = unsafe { content()? };
            snapshot.sequence = unsafe { GetClipboardSequenceNumber() };
        }
        if snapshot.written && !self.owns(snapshot)? {
            return Err(NativeError::new(
                "clipboard_changed",
                "user replaced the clipboard snapshot",
            ));
        }
        let generation = uuid::Uuid::new_v4();
        prepare_backup(backup, generation, self.hwnd, &snapshot.previous)?;
        values.insert(0, (marker_format()?, generation.as_bytes().to_vec()));
        if let Err(error) = unsafe { install(&values) } {
            let _ = unsafe { install(&snapshot.previous) };
            return Err(error);
        }
        snapshot.sequence = unsafe { GetClipboardSequenceNumber() };
        snapshot.written = true;
        snapshot.marker = Some(generation);
        if current_owner() != self.hwnd {
            return Err(unavailable());
        }
        if let Err(error) = backup.call(
            "clipboard_backup_commit",
            json!({"generation":generation.to_string(),"sequence":snapshot.sequence,"owner_window":self.hwnd}),
        ) {
            // The native lock still excludes user copies. Undo an unacknowledged write
            // while the original baseline remains available in this process.
            if unsafe { install(&snapshot.previous) }.is_ok() {
                snapshot.written = false;
                snapshot.marker = None;
                snapshot.sequence = unsafe { GetClipboardSequenceNumber() };
            }
            return Err(error);
        }
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
                "clipboard handle is not owned by this session",
            ));
        }
        let _open = Open::new(self.hwnd)?;
        let restore = snapshot.written && self.owns(snapshot)?;
        if restore {
            unsafe { install(&snapshot.previous)? };
        }
        *state = None;
        Ok(json!({"restored":restore}))
    }
}
fn prepare_backup(
    backup: &Watchdog,
    generation: uuid::Uuid,
    owner_window: usize,
    values: &[(u32, Vec<u8>)],
) -> Result<()> {
    let generation = generation.to_string();
    backup.call(
        "clipboard_backup_prepare",
        json!({"phase":"begin","generation":generation,"owner_window":owner_window,
            "formats":values.iter().map(|(format,bytes)|json!({"format":format,"length":bytes.len()})).collect::<Vec<_>>() }),
    )?;
    for (index, (_, bytes)) in values.iter().enumerate() {
        for (chunk, data) in bytes.chunks(CHUNK).enumerate() {
            backup.call(
                "clipboard_backup_prepare",
                json!({"phase":"chunk","generation":generation,"index":index,
                    "offset":chunk*CHUNK,"bytes":data}),
            )?;
        }
    }
    backup.call(
        "clipboard_backup_prepare",
        json!({"phase":"complete","generation":generation}),
    )?;
    Ok(())
}
struct Prepared {
    generation: uuid::Uuid,
    values: Vec<(u32, Vec<u8>)>,
    lengths: Vec<usize>,
    complete: bool,
}
impl Prepared {
    fn begin(body: &Value, writer: usize) -> Result<Self> {
        if integer(body, "owner_window")? != writer || writer == 0 {
            return Err(malformed_backup());
        }
        let formats = body["formats"].as_array().ok_or_else(malformed_backup)?;
        if formats.len() > 64 {
            return Err(malformed_backup());
        }
        let mut values = Vec::with_capacity(formats.len());
        let mut lengths = Vec::with_capacity(formats.len());
        let mut total = 0usize;
        let mut seen = std::collections::BTreeSet::new();
        for entry in formats {
            let format =
                u32::try_from(integer(entry, "format")?).map_err(|_| malformed_backup())?;
            let length = integer(entry, "length")?;
            total = total.checked_add(length).ok_or_else(malformed_backup)?;
            if format == 0
                || matches!(format, 2 | 3 | 9 | 14 | 0x80..=0x8e)
                || !seen.insert(format)
                || length == 0
                || total > LIMIT
            {
                return Err(malformed_backup());
            }
            values.push((format, Vec::new()));
            lengths.push(length);
        }
        Ok(Self {
            generation: generation(body)?,
            values,
            lengths,
            complete: false,
        })
    }
    fn append(&mut self, body: &Value) -> Result<()> {
        if self.complete || generation(body)? != self.generation {
            return Err(malformed_backup());
        }
        let index = integer(body, "index")?;
        let offset = integer(body, "offset")?;
        let incoming = body["bytes"].as_array().ok_or_else(malformed_backup)?;
        let expected = *self.lengths.get(index).ok_or_else(malformed_backup)?;
        let (_, bytes) = self.values.get_mut(index).ok_or_else(malformed_backup)?;
        if incoming.is_empty()
            || incoming.len() > CHUNK
            || offset != bytes.len()
            || offset
                .checked_add(incoming.len())
                .is_none_or(|end| end > expected)
        {
            return Err(malformed_backup());
        }
        let chunk: Vec<u8> =
            serde_json::from_value(body["bytes"].clone()).map_err(|_| malformed_backup())?;
        bytes.extend(chunk);
        Ok(())
    }
    fn finish(&mut self, body: &Value) -> Result<()> {
        if generation(body)? != self.generation
            || self
                .values
                .iter()
                .zip(&self.lengths)
                .any(|((_, data), length)| data.len() != *length)
        {
            return Err(malformed_backup());
        }
        self.complete = true;
        Ok(())
    }
}
fn integer(body: &Value, field: &str) -> Result<usize> {
    usize::try_from(body[field].as_u64().ok_or_else(malformed_backup)?)
        .map_err(|_| malformed_backup())
}
fn generation(body: &Value) -> Result<uuid::Uuid> {
    uuid::Uuid::parse_str(required(body, "generation")?).map_err(|_| malformed_backup())
}
struct Committed {
    prepared: Prepared,
    sequence: u32,
    owner: usize,
}
impl Committed {
    fn owner_matches(&self, sequence: u32, owner: usize) -> bool {
        self.sequence == sequence && (owner == self.owner || owner == 0)
    }
    fn matches(&self, sequence: u32, owner: usize, marker: &[u8]) -> bool {
        self.owner_matches(sequence, owner) && marker == self.prepared.generation.as_bytes()
    }
}
/// In-memory backup on a separately pinned native child. Never restore a prepare-only write.
pub struct Backup {
    clipboard: Clipboard,
    writer: usize,
    format: u32,
    staging: Option<Prepared>,
    committed: Option<Committed>,
}
impl Backup {
    pub fn new(init: &Value) -> Result<Self> {
        let writer = integer(init, "clipboard_owner_window")?;
        let clipboard = Clipboard::default();
        if writer == 0 || !clipboard.available() {
            return Err(unavailable());
        }
        Ok(Self {
            clipboard,
            writer,
            format: marker_format()?,
            staging: None,
            committed: None,
        })
    }
    pub fn prepare(&mut self, body: &Value) -> Result<()> {
        match required(body, "phase")? {
            "begin" => self.staging = Some(Prepared::begin(body, self.writer)?),
            "chunk" => self
                .staging
                .as_mut()
                .ok_or_else(malformed_backup)?
                .append(body)?,
            "complete" => self
                .staging
                .as_mut()
                .ok_or_else(malformed_backup)?
                .finish(body)?,
            _ => return Err(malformed_backup()),
        }
        Ok(())
    }
    pub fn commit(&mut self, body: &Value) -> Result<()> {
        let prepared = self.staging.as_ref().ok_or_else(malformed_backup)?;
        let owner = integer(body, "owner_window")?;
        let sequence = u32::try_from(integer(body, "sequence")?).map_err(|_| malformed_backup())?;
        if !prepared.complete || prepared.generation != generation(body)? || owner != self.writer {
            return Err(malformed_backup());
        }
        let prepared = self.staging.take().ok_or_else(malformed_backup)?;
        self.committed = Some(Committed {
            prepared,
            sequence,
            owner,
        });
        Ok(())
    }
    /// Caller must first confirm the pinned guardian process has exited.
    pub fn restore(&mut self) -> Result<bool> {
        let Some(receipt) = self.committed.as_ref() else {
            return Ok(false);
        };
        let _open = Open::new(self.clipboard.hwnd)?;
        // SAFETY: this native counter takes no arguments and is read under OpenClipboard.
        let sequence = unsafe { GetClipboardSequenceNumber() };
        let owner = current_owner();
        if !receipt.owner_matches(sequence, owner) {
            self.committed = None;
            self.staging = None;
            return Ok(false);
        }
        // SAFETY: the native clipboard lock bounds both checks and the following installation.
        let marker = unsafe { native_value(self.format) };
        if !marker.is_ok_and(|bytes| receipt.matches(sequence, owner, &bytes)) {
            self.committed = None;
            self.staging = None;
            return Ok(false);
        }
        // SAFETY: every preserved format was validated as transferable global memory;
        // the same Open guard excludes a user copy between the ownership check and write.
        unsafe {
            install(&receipt.prepared.values)?;
        }
        self.committed = None;
        self.staging = None;
        Ok(true)
    }
    pub fn retains_selection(&self) -> bool {
        false
    }
}
fn html_payload(fragment: &str) -> Vec<u8> {
    let wrapper =
        format!("<html><body><!--StartFragment-->{fragment}<!--EndFragment--></body></html>");
    let blank = "Version:0.9\r\nStartHTML:0000000000\r\nEndHTML:0000000000\r\nStartFragment:0000000000\r\nEndFragment:0000000000\r\n";
    let start = blank.len();
    let begin = start + wrapper.find("<!--StartFragment-->").unwrap() + 20;
    let end = begin + fragment.len();
    let header = format!(
        "Version:0.9\r\nStartHTML:{start:010}\r\nEndHTML:{:010}\r\nStartFragment:{begin:010}\r\nEndFragment:{end:010}\r\n",
        start + wrapper.len()
    );
    format!("{header}{wrapper}\0").into_bytes()
}
#[cfg(test)]
mod tests {
    use super::*;

    fn begin(token: uuid::Uuid, formats: Value) -> Value {
        json!({"phase":"begin","generation":token.to_string(),"owner_window":7,"formats":formats})
    }
    #[test]
    fn backup_rejects_partial_out_of_order_and_cross_generation_chunks() {
        let token = uuid::Uuid::new_v4();
        let mut value =
            Prepared::begin(&begin(token, json!([{"format":13,"length":2}])), 7).unwrap();
        let mut chunk = json!({"generation":token.to_string(),"index":0,"offset":1,"bytes":[1,2]});
        assert!(value.append(&chunk).is_err());
        let complete = json!({"generation":token.to_string()});
        assert!(value.finish(&complete).is_err());
        chunk["offset"] = json!(0);
        chunk["bytes"] = json!([256, 2]);
        assert!(value.append(&chunk).is_err());
        chunk["bytes"] = json!([1, 2]);
        chunk["generation"] = json!(uuid::Uuid::new_v4().to_string());
        assert!(value.append(&chunk).is_err());
        chunk["generation"] = json!(token.to_string());
        value.append(&chunk).unwrap();
        assert!(value.append(&chunk).is_err());
        value.finish(&complete).unwrap();
        assert!(value.append(&chunk).is_err());
        assert_eq!(value.values, vec![(13, vec![1, 2])]);
    }
    #[test]
    fn backup_rejects_duplicate_nontransferable_and_oversized_formats() {
        let token = uuid::Uuid::new_v4();
        for formats in [
            json!([{"format":13,"length":1},{"format":13,"length":1}]),
            json!([{"format":2,"length":1}]),
            json!([{"format":13,"length":LIMIT+1}]),
        ] {
            assert!(Prepared::begin(&begin(token, formats), 7).is_err());
        }
        assert!(Prepared::begin(&begin(token, json!([])), 8).is_err());
    }
    #[test]
    fn native_receipt_requires_exact_sequence_owner_and_marker() {
        let token = uuid::Uuid::new_v4();
        let receipt = Committed {
            prepared: Prepared::begin(&begin(token, json!([])), 7).unwrap(),
            sequence: 42,
            owner: 7,
        };
        assert!(receipt.matches(42, 7, token.as_bytes()));
        assert!(receipt.matches(42, 0, token.as_bytes()));
        assert!(!receipt.matches(43, 7, token.as_bytes()));
        assert!(!receipt.matches(42, 8, token.as_bytes()));
        assert!(!receipt.matches(42, 7, uuid::Uuid::new_v4().as_bytes()));
    }
    #[test]
    fn uncommitted_prepare_preserves_prior_committed_receipt() {
        let mut backup = Backup {
            clipboard: Clipboard {
                state: Mutex::new(None),
                hwnd: 0,
            },
            writer: 7,
            format: 0,
            staging: None,
            committed: None,
        };
        let token = uuid::Uuid::new_v4();
        backup.prepare(&begin(token, json!([]))).unwrap();
        assert!(!backup.restore().unwrap());
        let receipt = json!({"generation":token.to_string(),"sequence":1,"owner_window":7});
        assert!(backup.commit(&receipt).is_err());
        backup
            .prepare(&json!({"phase":"complete","generation":token.to_string()}))
            .unwrap();
        backup.commit(&receipt).unwrap();
        backup
            .prepare(&begin(uuid::Uuid::new_v4(), json!([])))
            .unwrap();
        assert_eq!(
            backup.committed.as_ref().unwrap().prepared.generation,
            token
        );
    }
    #[test]
    fn html_offsets_measure_utf8_bytes() {
        let value = super::html_payload("中文");
        let source = std::str::from_utf8(&value).unwrap();
        let offset = |key: &str| {
            source
                .lines()
                .find_map(|line| line.strip_prefix(key))
                .unwrap()
                .parse::<usize>()
                .unwrap()
        };
        assert_eq!(
            &value[offset("StartFragment:")..offset("EndFragment:")],
            "中文".as_bytes()
        );
    }
}
