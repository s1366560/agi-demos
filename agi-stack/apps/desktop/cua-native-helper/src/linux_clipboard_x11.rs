//! X11 selection ownership and multi-format transfers, including the native INCR protocol.
use crate::backend::{NativeError, Result};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use x11rb::{
    connection::Connection,
    protocol::{
        xfixes::{ConnectionExt as _, SelectionEvent, SelectionEventMask},
        xproto::*,
        Event,
    },
    rust_connection::RustConnection,
    wrapper::ConnectionExt as _,
};
const LIMIT: usize = 8 * 1024 * 1024;
const CHUNK: usize = 64 * 1024;
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct Data {
    pub target: u32,
    pub type_: u32,
    pub format: u8,
    pub bytes: Vec<u8>,
}
struct Atoms {
    clipboard: u32,
    targets: u32,
    property: u32,
    incr: u32,
}
pub struct X11 {
    setter: Arc<RustConnection>,
    window: u32,
    atoms: Arc<Atoms>,
    data: Arc<Mutex<Vec<Data>>>,
    gate: Arc<Mutex<()>>,
    receipt: Arc<Mutex<Receipt>>,
}
#[derive(Default)]
struct Receipt {
    writer: u32,
    last_owner: u32,
    closed_owned: bool,
    saw_writer: bool,
    invalidated: bool,
}
impl Receipt {
    fn observed(&mut self, event: &x11rb::protocol::xfixes::SelectionNotifyEvent) {
        if event.subtype == SelectionEvent::SET_SELECTION_OWNER {
            // Once ownership passed away or this writer closed, reusing its numeric
            // XID cannot re-arm this generation. Only a trusted pre-write prepare can.
            if self.closed_owned || (self.saw_writer && event.owner != self.writer) {
                self.invalidated = true;
            }
            self.saw_writer |= event.owner == self.writer && !self.invalidated;
            self.closed_owned = false;
            self.last_owner = event.owner;
        } else if matches!(
            event.subtype,
            SelectionEvent::SELECTION_WINDOW_DESTROY | SelectionEvent::SELECTION_CLIENT_CLOSE
        ) {
            self.closed_owned = self.writer != 0
                && !self.invalidated
                && (self.last_owner == self.writer || self.closed_owned)
                && event.owner == 0;
            self.last_owner = event.owner;
        }
    }
}
fn error() -> NativeError {
    NativeError::new(
        "clipboard_unavailable",
        "native X11 selection transfer failed",
    )
}
fn atom(connection: &RustConnection, name: &str) -> Result<u32> {
    connection
        .intern_atom(false, name.as_bytes())
        .map_err(|_| error())?
        .reply()
        .map(|reply| reply.atom)
        .map_err(|_| error())
}
fn window(connection: &RustConnection, screen: usize) -> Result<u32> {
    let window = connection.generate_id().map_err(|_| error())?;
    connection
        .create_window(
            x11rb::COPY_DEPTH_FROM_PARENT,
            window,
            connection.setup().roots[screen].root,
            0,
            0,
            1,
            1,
            0,
            WindowClass::INPUT_ONLY,
            0,
            &CreateWindowAux::new().event_mask(EventMask::PROPERTY_CHANGE),
        )
        .map_err(|_| error())?
        .check()
        .map_err(|_| error())?;
    Ok(window)
}
impl X11 {
    pub fn new() -> Result<Self> {
        let (connection, screen) = x11rb::connect(None).map_err(|_| error())?;
        let window = window(&connection, screen)?;
        let atoms = Arc::new(Atoms {
            clipboard: atom(&connection, "CLIPBOARD")?,
            targets: atom(&connection, "TARGETS")?,
            property: atom(&connection, "MEMSTACK_CUA_CLIPBOARD")?,
            incr: atom(&connection, "INCR")?,
        });
        let data = Arc::new(Mutex::new(Vec::new()));
        let connection = Arc::new(connection);
        let serve = connection.clone();
        let values = data.clone();
        let native = atoms.clone();
        let gate = Arc::new(Mutex::new(()));
        let receipt = Arc::new(Mutex::new(Receipt::default()));
        let event_gate = gate.clone();
        let event_receipt = receipt.clone();
        std::thread::Builder::new()
            .name("memstack-cua-x11-clipboard".into())
            .spawn(move || serve_events(serve, window, native, values, event_gate, event_receipt))
            .map_err(|_| error())?;
        Ok(Self {
            setter: connection,
            window,
            atoms,
            data,
            gate,
            receipt,
        })
    }
    pub fn owner(&self) -> Result<u32> {
        self.setter
            .get_selection_owner(self.atoms.clipboard)
            .map_err(|_| error())?
            .reply()
            .map(|r| r.owner)
            .map_err(|_| error())
    }
    pub fn ours(&self) -> Result<bool> {
        Ok(self.owner()? == self.window)
    }
    pub fn target(&self, name: &str) -> Result<u32> {
        atom(&self.setter, name)
    }
    pub fn name(&self, target: u32) -> Result<String> {
        self.setter
            .get_atom_name(target)
            .map_err(|_| error())?
            .reply()
            .map_err(|_| error())
            .and_then(|r| String::from_utf8(r.name).map_err(|_| error()))
    }
    pub fn snapshot(&self) -> Result<(u32, Vec<Data>)> {
        let owner = self.owner()?;
        if owner == 0 {
            return Ok((owner, Vec::new()));
        }
        if owner == self.window {
            return self
                .data
                .lock()
                .map(|d| (owner, d.clone()))
                .map_err(|_| error());
        }
        let (connection, screen) = x11rb::connect(None).map_err(|_| error())?;
        let getter = window(&connection, screen)?;
        let targets = read(&connection, getter, &self.atoms, self.atoms.targets)?;
        if targets.format != 32 {
            return Err(error());
        }
        if targets.bytes.len() / 4 > 64 {
            return Err(NativeError::new(
                "clipboard_too_large",
                "too many native clipboard formats",
            ));
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        let mut result = Vec::new();
        let mut count = 0;
        for bytes in targets.bytes.chunks_exact(4) {
            if Instant::now() >= deadline {
                return Err(error());
            }
            let target = u32::from_ne_bytes(bytes.try_into().unwrap());
            let name = self.name(target)?;
            if ["TARGETS", "TIMESTAMP", "MULTIPLE", "SAVE_TARGETS"].contains(&name.as_str()) {
                continue;
            }
            let data = read(&connection, getter, &self.atoms, target)?;
            count += data.bytes.len();
            if count > LIMIT {
                return Err(NativeError::new(
                    "clipboard_too_large",
                    "native clipboard snapshot exceeds budget",
                ));
            }
            result.push(data);
        }
        if self.owner()? != owner {
            return Err(NativeError::new(
                "clipboard_changed",
                "native selection changed while preserving it",
            ));
        }
        Ok((owner, result))
    }
    #[cfg(debug_assertions)]
    pub fn test_grab(&self) -> Result<()> {
        self.setter
            .grab_server()
            .map_err(|_| error())?
            .check()
            .map_err(|_| error())
    }
    pub fn owned_id(&self) -> u32 {
        self.window
    }
    pub fn watch_writer(&self, writer: u32) -> Result<()> {
        let _gate = self.gate.lock().map_err(|_| error())?;
        let version = self
            .setter
            .xfixes_query_version(2, 0)
            .map_err(|_| error())?
            .reply()
            .map_err(|_| error())?;
        if version.major_version < 1 {
            return Err(error());
        }
        self.setter
            .xfixes_select_selection_input(
                self.window,
                self.atoms.clipboard,
                SelectionEventMask::SET_SELECTION_OWNER
                    | SelectionEventMask::SELECTION_WINDOW_DESTROY
                    | SelectionEventMask::SELECTION_CLIENT_CLOSE,
            )
            .map_err(|_| error())?
            .check()
            .map_err(|_| error())?;
        self.arm_writer_locked(writer)
    }
    pub fn arm_writer(&self, writer: u32) -> Result<()> {
        let _gate = self.gate.lock().map_err(|_| error())?;
        self.arm_writer_locked(writer)
    }
    fn arm_writer_locked(&self, writer: u32) -> Result<()> {
        let owner = self.owner()?;
        let mut receipt = self.receipt.lock().map_err(|_| error())?;
        while let Some(event) = self.setter.poll_for_event().map_err(|_| error())? {
            if let Event::XfixesSelectionNotify(event) = event {
                receipt.observed(&event);
            }
        }
        // Preserve an already-proven close if the caller died during its prepare.
        if !receipt.closed_owned {
            *receipt = Receipt {
                writer,
                last_owner: owner,
                saw_writer: owner == writer,
                ..Default::default()
            };
        }
        Ok(())
    }
    pub fn restore_closed_writer(&self, data: Vec<Data>) -> Result<bool> {
        self.install_checked(data, 0, true)
    }
    pub fn install(&self, data: Vec<Data>, expected_owner: u32) -> Result<()> {
        self.install_checked(data, expected_owner, false)
            .map(|_| ())
    }
    fn install_checked(
        &self,
        data: Vec<Data>,
        expected_owner: u32,
        require_closed: bool,
    ) -> Result<bool> {
        let _gate = self.gate.lock().map_err(|_| error())?;
        self.setter
            .grab_server()
            .map_err(|_| error())?
            .check()
            .map_err(|_| error())?;
        let result = (|| {
            let owner = self.owner()?;
            // GetSelectionOwner is a server barrier. Under the same gate, process
            // every earlier native event before deciding whether the lost owner
            // was this exact writer rather than a user copy or explicit clear.
            if require_closed {
                while let Some(event) = self.setter.poll_for_event().map_err(|_| error())? {
                    if let Event::XfixesSelectionNotify(event) = event {
                        self.receipt.lock().map_err(|_| error())?.observed(&event);
                    }
                }
            }
            if require_closed
                && (owner != 0 || !self.receipt.lock().map_err(|_| error())?.closed_owned)
            {
                return Ok(false);
            }
            if owner != expected_owner {
                return Err(NativeError::new(
                    "clipboard_changed",
                    "native selection changed before writing",
                ));
            }
            let next_owner = if data.is_empty() { 0 } else { self.window };
            *self.data.lock().map_err(|_| error())? = data;
            self.setter
                .set_selection_owner(next_owner, self.atoms.clipboard, x11rb::CURRENT_TIME)
                .map_err(|_| error())?
                .check()
                .map_err(|_| error())?;
            if self.owner()? != next_owner {
                return Err(error());
            }
            Ok(true)
        })();
        let _ = self.setter.ungrab_server();
        let _ = self.setter.flush();
        result
    }
}
fn read(connection: &RustConnection, window: u32, atoms: &Atoms, target: u32) -> Result<Data> {
    connection
        .convert_selection(
            window,
            atoms.clipboard,
            target,
            atoms.property,
            x11rb::CURRENT_TIME,
        )
        .map_err(|_| error())?;
    connection.flush().map_err(|_| error())?;
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if Instant::now() >= deadline {
            return Err(error());
        }
        match connection.poll_for_event().map_err(|_| error())? {
            Some(Event::SelectionNotify(event)) => {
                if event.property == 0 {
                    return Err(NativeError::new(
                        "clipboard_format_unsupported",
                        "selection cannot preserve this native target",
                    ));
                }
                break;
            }
            _ => std::thread::sleep(Duration::from_millis(2)),
        }
    }
    let mut reply = connection
        .get_property(
            false,
            window,
            atoms.property,
            AtomEnum::ANY,
            0,
            (LIMIT / 4) as u32,
        )
        .map_err(|_| error())?
        .reply()
        .map_err(|_| error())?;
    if reply.bytes_after > 0 {
        return Err(NativeError::new(
            "clipboard_too_large",
            "native target exceeds snapshot budget",
        ));
    }
    if reply.type_ != atoms.incr {
        return Ok(Data {
            target,
            type_: reply.type_,
            format: reply.format,
            bytes: reply.value,
        });
    }
    connection
        .delete_property(window, atoms.property)
        .map_err(|_| error())?;
    connection.flush().map_err(|_| error())?;
    let mut value = Vec::new();
    let mut format = 0;
    let mut type_ = 0;
    loop {
        if Instant::now() >= deadline {
            return Err(error());
        }
        match connection.poll_for_event().map_err(|_| error())? {
            Some(Event::PropertyNotify(event))
                if event.atom == atoms.property && event.state == Property::NEW_VALUE =>
            {
                reply = connection
                    .get_property(
                        true,
                        window,
                        atoms.property,
                        AtomEnum::ANY,
                        0,
                        (LIMIT / 4) as u32,
                    )
                    .map_err(|_| error())?
                    .reply()
                    .map_err(|_| error())?;
                if reply.value.is_empty() {
                    break;
                }
                format = reply.format;
                type_ = reply.type_;
                if reply.bytes_after > 0 || value.len() + reply.value.len() > LIMIT {
                    return Err(NativeError::new(
                        "clipboard_too_large",
                        "incremental native target exceeds budget",
                    ));
                }
                value.extend(reply.value);
                connection.flush().map_err(|_| error())?;
            }
            _ => std::thread::sleep(Duration::from_millis(2)),
        }
    }
    Ok(Data {
        target,
        type_,
        format,
        bytes: value,
    })
}
fn serve_events(
    connection: Arc<RustConnection>,
    window: u32,
    atoms: Arc<Atoms>,
    data: Arc<Mutex<Vec<Data>>>,
    gate: Arc<Mutex<()>>,
    receipt: Arc<Mutex<Receipt>>,
) {
    let mut transfers: BTreeMap<(u32, u32), (Data, usize, Instant)> = BTreeMap::new();
    loop {
        let Ok(_gate) = gate.lock() else { break };
        let event = match connection.poll_for_event() {
            Ok(Some(event)) => event,
            Ok(None) => {
                drop(_gate);
                std::thread::sleep(Duration::from_millis(2));
                continue;
            }
            Err(_) => break,
        };
        transfers.retain(|_, (_, _, deadline)| Instant::now() < *deadline);
        match event {
            Event::XfixesSelectionNotify(event) => {
                if let Ok(mut receipt) = receipt.lock() {
                    receipt.observed(&event);
                }
            }
            Event::SelectionRequest(event)
                if event.owner == window && event.selection == atoms.clipboard =>
            {
                let property = if event.property == 0 {
                    event.target
                } else {
                    event.property
                };
                let mut accepted = false;
                if event.target == atoms.targets {
                    let mut targets = data
                        .lock()
                        .map(|d| d.iter().map(|d| d.target).collect::<Vec<_>>())
                        .unwrap_or_default();
                    targets.push(atoms.targets);
                    accepted = connection
                        .change_property32(
                            PropMode::REPLACE,
                            event.requestor,
                            property,
                            AtomEnum::ATOM,
                            &targets,
                        )
                        .is_ok();
                } else if let Some(value) = data
                    .lock()
                    .ok()
                    .and_then(|data| data.iter().find(|d| d.target == event.target).cloned())
                {
                    if value.bytes.len() > CHUNK && transfers.len() < 8 {
                        let _ = connection.change_window_attributes(
                            event.requestor,
                            &ChangeWindowAttributesAux::new()
                                .event_mask(EventMask::PROPERTY_CHANGE),
                        );
                        accepted = connection
                            .change_property32(
                                PropMode::REPLACE,
                                event.requestor,
                                property,
                                atoms.incr,
                                &[value.bytes.len() as u32],
                            )
                            .is_ok();
                        if accepted {
                            transfers.insert(
                                (event.requestor, property),
                                (value, 0, Instant::now() + Duration::from_secs(3)),
                            );
                        }
                    } else if value.bytes.len() <= CHUNK {
                        accepted = property_write(
                            &connection,
                            event.requestor,
                            property,
                            &value,
                            &value.bytes,
                        )
                        .is_ok();
                    }
                }
                let notify = SelectionNotifyEvent {
                    response_type: SELECTION_NOTIFY_EVENT,
                    sequence: 0,
                    time: event.time,
                    requestor: event.requestor,
                    selection: event.selection,
                    target: event.target,
                    property: if accepted { property } else { 0 },
                };
                let _ = connection.send_event(false, event.requestor, EventMask::NO_EVENT, notify);
                let _ = connection.flush();
            }
            Event::PropertyNotify(event) if event.state == Property::DELETE => {
                if let Some((value, offset, _)) = transfers.get_mut(&(event.window, event.atom)) {
                    let end = (*offset + CHUNK).min(value.bytes.len());
                    let _ = property_write(
                        &connection,
                        event.window,
                        event.atom,
                        value,
                        &value.bytes[*offset..end],
                    );
                    let _ = connection.flush();
                    if *offset == value.bytes.len() {
                        transfers.remove(&(event.window, event.atom));
                    } else {
                        *offset = end;
                    }
                }
            }
            _ => {}
        }
    }
}
fn property_write(
    connection: &RustConnection,
    window: u32,
    property: u32,
    data: &Data,
    bytes: &[u8],
) -> Result<()> {
    if !matches!(data.format, 8 | 16 | 32) || bytes.len() % (data.format as usize / 8) != 0 {
        return Err(error());
    }
    connection
        .change_property(
            PropMode::REPLACE,
            window,
            property,
            data.type_,
            data.format,
            (bytes.len() * 8 / data.format as usize) as u32,
            bytes,
        )
        .map_err(|_| error())?
        .check()
        .map_err(|_| error())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn event(kind: SelectionEvent, owner: u32) -> x11rb::protocol::xfixes::SelectionNotifyEvent {
        x11rb::protocol::xfixes::SelectionNotifyEvent {
            subtype: kind,
            owner,
            ..Default::default()
        }
    }
    #[test]
    fn only_exact_native_writer_close_proves_owned_loss() {
        let mut receipt = Receipt {
            writer: 12,
            last_owner: 7,
            closed_owned: false,
            ..Default::default()
        };
        receipt.observed(&event(SelectionEvent::SET_SELECTION_OWNER, 12));
        receipt.observed(&event(SelectionEvent::SELECTION_CLIENT_CLOSE, 0));
        assert!(receipt.closed_owned);
        receipt.observed(&event(SelectionEvent::SELECTION_WINDOW_DESTROY, 0));
        assert!(receipt.closed_owned);
    }
    #[test]
    fn user_copy_and_explicit_clear_invalidate_owned_close_receipt() {
        let mut receipt = Receipt {
            writer: 12,
            last_owner: 12,
            closed_owned: false,
            saw_writer: true,
            ..Default::default()
        };
        receipt.observed(&event(SelectionEvent::SELECTION_CLIENT_CLOSE, 0));
        assert!(receipt.closed_owned);
        receipt.observed(&event(SelectionEvent::SET_SELECTION_OWNER, 0));
        assert!(!receipt.closed_owned);
        receipt.observed(&event(SelectionEvent::SET_SELECTION_OWNER, 31));
        receipt.observed(&event(SelectionEvent::SELECTION_CLIENT_CLOSE, 0));
        assert!(!receipt.closed_owned);
    }
    #[test]
    fn unknown_native_owner_close_never_proves_our_write() {
        let mut receipt = Receipt {
            writer: 12,
            last_owner: 31,
            closed_owned: false,
            ..Default::default()
        };
        receipt.observed(&event(SelectionEvent::SELECTION_CLIENT_CLOSE, 0));
        assert!(!receipt.closed_owned);
        let mut unknown = Receipt::default();
        unknown.observed(&event(SelectionEvent::SELECTION_CLIENT_CLOSE, 0));
        assert!(!unknown.closed_owned);
    }
    #[test]
    fn a_reused_native_xid_does_not_rearm_an_invalidated_generation() {
        let mut receipt = Receipt {
            writer: 12,
            last_owner: 12,
            saw_writer: true,
            ..Default::default()
        };
        receipt.observed(&event(SelectionEvent::SET_SELECTION_OWNER, 31));
        receipt.observed(&event(SelectionEvent::SET_SELECTION_OWNER, 12));
        receipt.observed(&event(SelectionEvent::SELECTION_CLIENT_CLOSE, 0));
        assert!(!receipt.closed_owned);
        let mut closed = Receipt {
            writer: 12,
            last_owner: 12,
            saw_writer: true,
            ..Default::default()
        };
        closed.observed(&event(SelectionEvent::SELECTION_CLIENT_CLOSE, 0));
        assert!(closed.closed_owned);
        closed.observed(&event(SelectionEvent::SET_SELECTION_OWNER, 12));
        closed.observed(&event(SelectionEvent::SELECTION_CLIENT_CLOSE, 0));
        assert!(!closed.closed_owned);
    }
}
