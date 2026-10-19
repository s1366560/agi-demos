//! XI2 raw source-device ownership and XTEST injection in an independent process.
use crate::{
    backend::{NativeError, Result},
    input_watchdog::{Driver, Event as InputEvent, Item},
};
use std::collections::{BTreeMap, BTreeSet};
use x11rb::{
    connection::Connection,
    protocol::{
        xinput::{ConnectionExt as _, DeviceType, EventMask, InputStateData, XIEventMask},
        xproto::{AtomEnum, ConnectionExt as _, CreateWindowAux, PropMode, WindowClass},
        xtest::ConnectionExt as _,
        Event,
    },
    rust_connection::RustConnection,
};
fn unavailable() -> NativeError {
    NativeError::new(
        "capability_unsupported",
        "XI2 source-device tracking and XTEST are required for held input",
    )
}
pub struct Native {
    connection: RustConnection,
    sources: BTreeMap<u16, bool>,
    physical: BTreeMap<u16, BTreeSet<Item>>,
    initial: Vec<InputEvent>,
    ready: bool,
}
impl Native {
    pub fn new(_: usize) -> Result<Self> {
        let (connection, screen) = x11rb::connect(None).map_err(|_| unavailable())?;
        connection
            .xinput_xi_query_version(2, 0)
            .map_err(|_| unavailable())?
            .reply()
            .map_err(|_| unavailable())?;
        connection
            .xtest_get_version(2, 2)
            .map_err(|_| unavailable())?
            .reply()
            .map_err(|_| unavailable())?;
        let root = connection.setup().roots[screen].root;
        // A private InputOnly resource also lets the X server report this connection's
        // exact process owner. Losing that connection is a real driver failure.
        let resource = connection.generate_id().map_err(|_| unavailable())?;
        connection
            .create_window(
                0,
                resource,
                root,
                0,
                0,
                1,
                1,
                0,
                WindowClass::INPUT_ONLY,
                0,
                &CreateWindowAux::new(),
            )
            .map_err(|_| unavailable())?
            .check()
            .map_err(|_| unavailable())?;
        let pid_atom = connection
            .intern_atom(false, b"_NET_WM_PID")
            .map_err(|_| unavailable())?
            .reply()
            .map_err(|_| unavailable())?
            .atom;
        use x11rb::wrapper::ConnectionExt as _;
        connection
            .change_property32(
                PropMode::REPLACE,
                resource,
                pid_atom,
                AtomEnum::CARDINAL,
                &[std::process::id()],
            )
            .map_err(|_| unavailable())?
            .check()
            .map_err(|_| unavailable())?;
        let masks = [
            EventMask {
                deviceid: 1,
                mask: vec![
                    XIEventMask::RAW_KEY_PRESS
                        | XIEventMask::RAW_KEY_RELEASE
                        | XIEventMask::RAW_BUTTON_PRESS
                        | XIEventMask::RAW_BUTTON_RELEASE,
                ],
            },
            EventMask {
                // XIHierarchy requires XIAllDevices, rather than XIAllMasterDevices.
                deviceid: 0,
                mask: vec![XIEventMask::HIERARCHY | XIEventMask::DEVICE_CHANGED],
            },
        ];
        connection
            .xinput_xi_select_events(root, &masks)
            .map_err(|_| unavailable())?
            .check()
            .map_err(|_| unavailable())?;
        let mut native = Self {
            connection,
            sources: BTreeMap::new(),
            physical: BTreeMap::new(),
            initial: Vec::new(),
            ready: true,
        };
        native.inventory(true)?;
        Ok(native)
    }
    fn inventory(&mut self, snapshot: bool) -> Result<()> {
        let devices = self
            .connection
            .xinput_xi_query_device(0u16)
            .map_err(|_| unavailable())?
            .reply()
            .map_err(|_| unavailable())?
            .infos;
        let mut sources = BTreeMap::new();
        let mut xtest_keyboard = 0;
        let mut xtest_pointer = 0;
        for device in devices {
            if !device.enabled
                || (device.type_ != DeviceType::SLAVE_KEYBOARD
                    && device.type_ != DeviceType::SLAVE_POINTER)
            {
                continue;
            }
            let xtest = (device.type_ == DeviceType::SLAVE_KEYBOARD
                && device.name == b"Virtual core XTEST keyboard")
                || (device.type_ == DeviceType::SLAVE_POINTER
                    && device.name == b"Virtual core XTEST pointer");
            if xtest {
                if device.type_ == DeviceType::SLAVE_KEYBOARD {
                    xtest_keyboard += 1;
                } else {
                    xtest_pointer += 1;
                }
            }
            sources.insert(device.deviceid, xtest);
            if snapshot && !xtest {
                let id = u8::try_from(device.deviceid).map_err(|_| unavailable())?;
                let states = self
                    .connection
                    .xinput_query_device_state(id)
                    .map_err(|_| unavailable())?
                    .reply()
                    .map_err(|_| unavailable())?
                    .classes;
                for state in states {
                    match state.data {
                        InputStateData::Key(state) => {
                            for code in 0..256 {
                                if state.keys[code / 8] & (1 << (code % 8)) != 0 {
                                    self.initial.push(InputEvent {
                                        item: Item::Key(code as u16),
                                        source: device.deviceid as u64,
                                        down: true,
                                        owned: false,
                                    });
                                    self.physical
                                        .entry(device.deviceid)
                                        .or_default()
                                        .insert(Item::Key(code as u16));
                                }
                            }
                        }
                        InputStateData::Button(state) => {
                            for code in 1..256 {
                                if state.buttons[code / 8] & (1 << (code % 8)) != 0 {
                                    self.initial.push(InputEvent {
                                        item: Item::Button(code as u16),
                                        source: device.deviceid as u64,
                                        down: true,
                                        owned: false,
                                    });
                                    self.physical
                                        .entry(device.deviceid)
                                        .or_default()
                                        .insert(Item::Button(code as u16));
                                }
                            }
                        }
                        _ => {}
                    }
                }
            }
        }
        for (source, items) in &self.physical {
            if !sources.contains_key(source) {
                self.initial.extend(items.iter().map(|item| InputEvent {
                    item: *item,
                    source: *source as u64,
                    down: false,
                    owned: false,
                }));
            }
        }
        self.physical
            .retain(|source, _| sources.contains_key(source));
        self.ready = xtest_keyboard == 1 && xtest_pointer == 1;
        self.sources = sources;
        if !self.ready {
            return Err(unavailable());
        }
        Ok(())
    }
    fn raw(&mut self, result: &mut Vec<InputEvent>, item: Item, source: u16, down: bool) {
        match self.sources.get(&source) {
            Some(true) => {}
            Some(false) => {
                if down {
                    self.physical.entry(source).or_default().insert(item);
                } else if let Some(items) = self.physical.get_mut(&source) {
                    items.remove(&item);
                }
                result.push(InputEvent {
                    item,
                    source: source as u64,
                    down,
                    owned: false,
                });
            }
            None => {
                self.ready = false;
                result.push(InputEvent {
                    item,
                    source: source as u64,
                    down,
                    owned: false,
                });
            }
        }
    }
}
impl Driver for Native {
    fn events(&mut self) -> Result<Vec<InputEvent>> {
        let mut result = std::mem::take(&mut self.initial);
        while let Some(event) = self
            .connection
            .poll_for_event()
            .map_err(|_| unavailable())?
        {
            match event {
                Event::XinputRawKeyPress(event) => self.raw(
                    &mut result,
                    Item::Key(event.detail as u16),
                    event.sourceid,
                    true,
                ),
                Event::XinputRawKeyRelease(event) => self.raw(
                    &mut result,
                    Item::Key(event.detail as u16),
                    event.sourceid,
                    false,
                ),
                Event::XinputRawButtonPress(event) => self.raw(
                    &mut result,
                    Item::Button(event.detail as u16),
                    event.sourceid,
                    true,
                ),
                Event::XinputRawButtonRelease(event) => self.raw(
                    &mut result,
                    Item::Button(event.detail as u16),
                    event.sourceid,
                    false,
                ),
                Event::XinputHierarchy(_) | Event::XinputDeviceChanged(_) => {
                    if self.inventory(false).is_err() {
                        self.ready = false;
                    }
                }
                _ => {}
            }
        }
        Ok(result)
    }
    fn inject(&mut self, item: Item, down: bool) -> Result<()> {
        let (kind, code) = match item {
            Item::Key(code) => (if down { 2 } else { 3 }, code),
            Item::Button(code) => (if down { 4 } else { 5 }, code),
        };
        let code = u8::try_from(code).map_err(|_| unavailable())?;
        self.connection
            .xtest_fake_input(kind, code, 0, 0, 0, 0, 0)
            .map_err(|_| unavailable())?
            .check()
            .map_err(|_| unavailable())?;
        self.connection.flush().map_err(|_| unavailable())?;
        Ok(())
    }
    fn available(&self) -> bool {
        self.ready
    }
}
pub fn keycode(name: &str) -> Result<u16> {
    let sym = sky_cua_linux::portal::remote_desktop::keysym_for_key_name(name)
        .ok_or_else(|| NativeError::new("invalid_params", "unknown native key"))?
        as u32;
    let (connection, _) = x11rb::connect(None).map_err(|_| unavailable())?;
    let setup = connection.setup();
    let first = setup.min_keycode;
    let count = setup.max_keycode - first + 1;
    let mapping = connection
        .get_keyboard_mapping(first, count)
        .map_err(|_| unavailable())?
        .reply()
        .map_err(|_| unavailable())?;
    mapping
        .keysyms
        .chunks(mapping.keysyms_per_keycode as usize)
        .position(|symbols| symbols.contains(&sym))
        .map(|index| first as u16 + index as u16)
        .ok_or_else(unavailable)
}
pub fn move_pointer(x: f64, y: f64) -> Result<()> {
    if !x.is_finite()
        || !y.is_finite()
        || x.round() < i16::MIN as f64
        || x.round() > i16::MAX as f64
        || y.round() < i16::MIN as f64
        || y.round() > i16::MAX as f64
    {
        return Err(NativeError::new(
            "invalid_params",
            "native X11 motion coordinates exceed protocol range",
        ));
    }
    let (connection, screen) = x11rb::connect(None).map_err(|_| unavailable())?;
    connection
        .xtest_fake_input(
            6,
            0,
            0,
            connection.setup().roots[screen].root,
            x.round() as i16,
            y.round() as i16,
            0,
        )
        .map_err(|_| unavailable())?
        .check()
        .map_err(|_| unavailable())?;
    Ok(())
}
