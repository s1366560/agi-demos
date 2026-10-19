//! EIS protocol driver adapted from sky-cua 9e4d9f0 (MIT; see THIRD_PARTY_NOTICES).
//! Only native capabilities, keymap codes and exact pointer coordinates are used.
use crate::backend::{NativeError, Result};
use reis::{
    ei,
    event::{DeviceCapability, EiEvent, EiEventConverter},
};
use std::{
    collections::{BTreeMap, BTreeSet},
    os::fd::{AsFd, OwnedFd},
    os::unix::net::UnixStream,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use xkbcommon::xkb;

#[derive(Default, Debug)]
pub struct Capabilities {
    pub keyboard: AtomicBool,
    pub pointer: AtomicBool,
}
#[derive(Clone, Debug)]
pub struct Eis {
    sender: std::sync::mpsc::Sender<Command>,
    pub capabilities: Arc<Capabilities>,
}
enum Action {
    Key(String, bool),
    Button(u32, bool),
    Move(f64, f64),
    Release,
}
struct Command {
    action: Action,
    reply: tokio::sync::oneshot::Sender<Result<()>>,
}
struct Keyboard {
    device: reis::event::Device,
    interface: ei::Keyboard,
    keycodes: BTreeMap<u32, u32>,
}
struct Pointer {
    device: reis::event::Device,
    absolute: ei::PointerAbsolute,
    button: ei::Button,
}
struct Worker {
    context: ei::Context,
    converter: EiEventConverter,
    connection: reis::event::Connection,
    keyboard: Option<Keyboard>,
    pointer: Option<Pointer>,
    held: BTreeSet<u32>,
    buttons: BTreeSet<u32>,
    emulating: std::collections::HashSet<ei::Device>,
    capabilities: Arc<Capabilities>,
    sequence: u32,
}
fn unavailable() -> NativeError {
    NativeError::new(
        "capability_unsupported",
        "the granted EIS session lacks the required native device capability",
    )
}
impl Eis {
    pub async fn start(fd: OwnedFd) -> Result<Self> {
        let (sender, receiver) = std::sync::mpsc::channel();
        let (ready, sent) = tokio::sync::oneshot::channel();
        let capabilities = Arc::new(Capabilities::default());
        let flags = capabilities.clone();
        std::thread::Builder::new()
            .name("memstack-cua-eis".into())
            .spawn(move || match Worker::new(fd, flags) {
                Ok(mut worker) => {
                    let _ = ready.send(Ok(()));
                    worker.run(receiver);
                }
                Err(error) => {
                    let _ = ready.send(Err(error));
                }
            })
            .map_err(|_| unavailable())?;
        tokio::time::timeout(Duration::from_secs(5), sent)
            .await
            .map_err(|_| unavailable())?
            .map_err(|_| unavailable())??;
        Ok(Self {
            sender,
            capabilities,
        })
    }
    async fn command(&self, action: Action) -> Result<()> {
        let (reply, result) = tokio::sync::oneshot::channel();
        self.sender
            .send(Command { action, reply })
            .map_err(|_| unavailable())?;
        tokio::time::timeout(Duration::from_secs(3), result)
            .await
            .map_err(|_| unavailable())?
            .map_err(|_| unavailable())?
    }
    pub async fn key(&self, name: &str, down: bool) -> Result<()> {
        self.command(Action::Key(name.into(), down)).await
    }
    pub async fn button(&self, button: u32, down: bool) -> Result<()> {
        self.command(Action::Button(button, down)).await
    }
    pub async fn move_to(&self, x: f64, y: f64) -> Result<()> {
        self.command(Action::Move(x, y)).await
    }
    pub async fn release(&self) -> Result<()> {
        self.command(Action::Release).await
    }
}
impl Worker {
    fn new(fd: OwnedFd, capabilities: Arc<Capabilities>) -> Result<Self> {
        let stream = UnixStream::from(fd);
        stream
            .set_read_timeout(Some(Duration::from_millis(250)))
            .map_err(|_| unavailable())?;
        stream
            .set_write_timeout(Some(Duration::from_secs(2)))
            .map_err(|_| unavailable())?;
        let context = ei::Context::new(stream).map_err(|_| unavailable())?;
        let handshake = reis::handshake::ei_handshake_blocking(
            &context,
            "memstack-cua-native-helper",
            ei::handshake::ContextType::Sender,
        )
        .map_err(|_| unavailable())?;
        let converter = EiEventConverter::new(&context, handshake);
        let connection = converter.connection().clone();
        let mut worker = Self {
            context,
            converter,
            connection,
            keyboard: None,
            pointer: None,
            held: BTreeSet::new(),
            buttons: BTreeSet::new(),
            emulating: Default::default(),
            capabilities,
            sequence: 1,
        };
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline && (worker.keyboard.is_none() || worker.pointer.is_none()) {
            worker.events()?;
            worker.read()?;
        }
        Ok(worker)
    }
    fn read(&mut self) -> Result<()> {
        match self.context.read() {
            Ok(_) => Ok(()),
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                Ok(())
            }
            Err(_) => Err(unavailable()),
        }
    }
    fn events(&mut self) -> Result<()> {
        while let Some(event) = self.context.pending_event() {
            let event = match event {
                reis::PendingRequestResult::Request(value) => value,
                reis::PendingRequestResult::InvalidObject(_) => continue,
                _ => return Err(unavailable()),
            };
            self.converter
                .handle_event(event)
                .map_err(|_| unavailable())?;
            while let Some(event) = self.converter.next_event() {
                match event {
                    EiEvent::SeatAdded(event) => {
                        event.seat.bind_capabilities(
                            DeviceCapability::Keyboard
                                | DeviceCapability::PointerAbsolute
                                | DeviceCapability::Button,
                        );
                        self.connection.flush().map_err(|_| unavailable())?;
                    }
                    EiEvent::DeviceResumed(event) => {
                        self.release()?;
                        if let Some(keyboard) = event.device.interface::<ei::Keyboard>() {
                            let keymap = event.device.keymap().ok_or_else(unavailable)?;
                            if keymap.type_ != ei::keyboard::KeymapType::Xkb {
                                return Err(unavailable());
                            }
                            let fd = keymap
                                .fd
                                .as_fd()
                                .try_clone_to_owned()
                                .map_err(|_| unavailable())?;
                            let context = xkb::Context::new(0);
                            let keymap = unsafe {
                                xkb::Keymap::new_from_fd(
                                    &context,
                                    fd,
                                    keymap.size as usize,
                                    xkb::KEYMAP_FORMAT_TEXT_V1,
                                    0,
                                )
                            }
                            .map_err(|_| unavailable())?
                            .ok_or_else(unavailable)?;
                            let mut keycodes = BTreeMap::new();
                            for raw in keymap.min_keycode().raw()..=keymap.max_keycode().raw() {
                                let Some(code) = raw.checked_sub(8) else {
                                    continue;
                                };
                                let key = xkb::Keycode::new(raw);
                                for layout in 0..keymap.num_layouts_for_key(key).max(1) {
                                    for sym in keymap.key_get_syms_by_level(key, layout, 0) {
                                        keycodes.entry(sym.raw()).or_insert(code);
                                    }
                                }
                            }
                            self.keyboard = Some(Keyboard {
                                device: event.device.clone(),
                                interface: keyboard,
                                keycodes,
                            });
                            self.capabilities.keyboard.store(true, Ordering::Release);
                        }
                        if let (Some(absolute), Some(button)) = (
                            event.device.interface::<ei::PointerAbsolute>(),
                            event.device.interface::<ei::Button>(),
                        ) {
                            self.pointer = Some(Pointer {
                                device: event.device,
                                absolute,
                                button,
                            });
                            self.capabilities.pointer.store(true, Ordering::Release);
                        }
                    }
                    EiEvent::DevicePaused(event) => self.removed(&event.device),
                    EiEvent::DeviceRemoved(event) => self.removed(&event.device),
                    EiEvent::DeviceStopEmulating(event) => self.removed(&event.device),
                    _ => {}
                }
            }
        }
        Ok(())
    }
    fn removed(&mut self, device: &reis::event::Device) {
        let _ = self.release();
        if self
            .keyboard
            .as_ref()
            .is_some_and(|keyboard| keyboard.device.device() == device.device())
        {
            self.keyboard = None;
            self.capabilities.keyboard.store(false, Ordering::Release);
        }
        if self
            .pointer
            .as_ref()
            .is_some_and(|pointer| pointer.device.device() == device.device())
        {
            self.pointer = None;
            self.capabilities.pointer.store(false, Ordering::Release);
        }
        self.emulating.remove(device.device());
    }
    fn emulate(&mut self, device: &reis::event::Device) -> Result<()> {
        if self.emulating.insert(device.device().clone()) {
            device
                .device()
                .start_emulating(self.connection.serial(), self.sequence);
            self.sequence = self.sequence.wrapping_add(1);
            self.connection.flush().map_err(|_| unavailable())?;
            std::thread::sleep(Duration::from_millis(20));
        }
        Ok(())
    }
    fn execute(&mut self, action: Action) -> Result<()> {
        match action {
            Action::Key(name, down) => {
                let sym = sky_cua_linux::portal::remote_desktop::keysym_for_key_name(&name)
                    .ok_or_else(|| {
                        NativeError::new("invalid_params", "unsupported native key name")
                    })? as u32;
                let keyboard = self.keyboard.as_ref().ok_or_else(unavailable)?;
                let code = *keyboard
                    .keycodes
                    .get(&sym)
                    .or_else(|| {
                        if name.len() == 1 {
                            keyboard
                                .keycodes
                                .get(&(name.as_bytes()[0].to_ascii_lowercase() as u32))
                        } else {
                            None
                        }
                    })
                    .ok_or_else(unavailable)?;
                let device = keyboard.device.clone();
                self.emulate(&device)?;
                let keyboard = self.keyboard.as_ref().ok_or_else(unavailable)?;
                if down {
                    if self.held.insert(code) {
                        keyboard.interface.key(code, ei::keyboard::KeyState::Press);
                    }
                } else if self.held.remove(&code) {
                    keyboard
                        .interface
                        .key(code, ei::keyboard::KeyState::Released);
                }
                device.device().frame(self.connection.serial(), micros());
            }
            Action::Button(button, down) => {
                let device = self
                    .pointer
                    .as_ref()
                    .ok_or_else(unavailable)?
                    .device
                    .clone();
                self.emulate(&device)?;
                let pointer = self.pointer.as_ref().ok_or_else(unavailable)?;
                if down {
                    if self.buttons.insert(button) {
                        pointer
                            .button
                            .button(button, ei::button::ButtonState::Press);
                    }
                } else if self.buttons.remove(&button) {
                    pointer
                        .button
                        .button(button, ei::button::ButtonState::Released);
                }
                device.device().frame(self.connection.serial(), micros());
            }
            Action::Move(x, y) => {
                let device = self
                    .pointer
                    .as_ref()
                    .ok_or_else(unavailable)?
                    .device
                    .clone();
                if !device.regions().iter().any(|r| {
                    x >= r.x as f64
                        && y >= r.y as f64
                        && x < r.x as f64 + r.width as f64
                        && y < r.y as f64 + r.height as f64
                }) {
                    return Err(NativeError::new(
                        "invalid_params",
                        "pointer is outside the granted EIS regions",
                    ));
                }
                self.emulate(&device)?;
                self.pointer
                    .as_ref()
                    .ok_or_else(unavailable)?
                    .absolute
                    .motion_absolute(x as f32, y as f32);
                device.device().frame(self.connection.serial(), micros());
            }
            Action::Release => self.release()?,
        }
        self.connection.flush().map_err(|_| unavailable())
    }
    fn release(&mut self) -> Result<()> {
        if let Some(keyboard) = &self.keyboard {
            for code in std::mem::take(&mut self.held) {
                keyboard
                    .interface
                    .key(code, ei::keyboard::KeyState::Released);
            }
            keyboard
                .device
                .device()
                .frame(self.connection.serial(), micros());
        }
        if let Some(pointer) = &self.pointer {
            for button in std::mem::take(&mut self.buttons) {
                pointer
                    .button
                    .button(button, ei::button::ButtonState::Released);
            }
            pointer
                .device
                .device()
                .frame(self.connection.serial(), micros());
        }
        self.connection.flush().map_err(|_| unavailable())
    }
    fn run(&mut self, receiver: std::sync::mpsc::Receiver<Command>) {
        loop {
            if self.events().is_err() {
                break;
            }
            match receiver.recv_timeout(Duration::from_millis(10)) {
                Ok(command) => {
                    let result = self.execute(command.action);
                    let _ = command.reply.send(result);
                }
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
                Err(_) => {
                    if self.read().is_err() {
                        break;
                    }
                }
            }
        }
        let _ = self.release();
        for device in &self.emulating {
            device.stop_emulating(self.connection.serial());
        }
        let _ = self.connection.flush();
        self.capabilities.keyboard.store(false, Ordering::Release);
        self.capabilities.pointer.store(false, Ordering::Release);
    }
}
fn micros() -> u64 {
    let mut time = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut time) } != 0 {
        return 0;
    }
    time.tv_sec as u64 * 1_000_000 + time.tv_nsec as u64 / 1_000
}

#[cfg(test)]
mod tests {
    #[tokio::test]
    async fn closed_native_eis_transport_never_reports_available() {
        let (client, server) = std::os::unix::net::UnixStream::pair().unwrap();
        drop(server);
        let result = super::Eis::start(client.into()).await;
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().kind, "capability_unsupported");
    }
    #[test]
    fn native_keysyms_are_exact_protocol_values() {
        assert_eq!(
            sky_cua_linux::portal::remote_desktop::keysym_for_key_name("Ctrl"),
            Some(0xffe3)
        );
        assert_eq!(
            sky_cua_linux::portal::remote_desktop::keysym_for_key_name("Shift"),
            Some(0xffe1)
        );
        assert!(
            sky_cua_linux::portal::remote_desktop::keysym_for_key_name("not-a-native-key")
                .is_none()
        );
    }
}
