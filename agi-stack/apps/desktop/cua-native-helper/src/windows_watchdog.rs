//! Low-level hooks distinguish physical input from this helper's unique SendInput marker.
use crate::{
    backend::{NativeError, Result},
    input_watchdog::{Driver, Event, Item},
};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::{Mutex, OnceLock},
};
use windows::{
    core::*,
    Win32::{
        Foundation::*,
        System::LibraryLoader::GetModuleHandleW,
        UI::{
            Input::{self, KeyboardAndMouse::*},
            WindowsAndMessaging::*,
        },
    },
};
fn unavailable() -> NativeError {
    NativeError::new(
        "capability_unsupported",
        "native low-level input ownership hooks are unavailable",
    )
}
struct State {
    marker: usize,
    events: Vec<Event>,
    physical: BTreeMap<Item, BTreeSet<u64>>,
    sources: BTreeMap<(usize, u16), u64>,
    next_source: u64,
    ready: bool,
    blocked: BTreeSet<Item>,
    guard_releases: bool,
}
static STATE: OnceLock<Mutex<State>> = OnceLock::new();
fn canonical(code: u16) -> u16 {
    match code {
        0xa0 | 0xa1 => 0x10,
        0xa2 | 0xa3 => 0x11,
        0xa4 | 0xa5 => 0x12,
        _ => code,
    }
}
fn record(item: Item, down: bool, injected: bool, marker: usize) -> bool {
    let Some(state) = STATE.get() else {
        return false;
    };
    let Ok(mut state) = state.lock() else {
        return false;
    };
    let own = injected && marker == state.marker;
    if own && !down && state.guard_releases && state.physical.contains_key(&item) {
        state.blocked.insert(item);
        state.events.push(Event {
            item,
            source: u64::MAX,
            down: false,
            owned: true,
        });
        return true;
    }
    if !injected {
        if down {
            state.physical.entry(item).or_default().insert(1);
        } else {
            if let Some(sources) = state.physical.get_mut(&item) {
                sources.remove(&1);
                if sources.is_empty() {
                    state.physical.remove(&item);
                }
            }
        }
    }
    if own || !injected {
        state.events.push(Event {
            item,
            source: 1,
            down,
            owned: own,
        });
    }
    false
}
unsafe extern "system" fn keyboard(code: i32, message: WPARAM, data: LPARAM) -> LRESULT {
    if code == HC_ACTION as i32 {
        // SAFETY: Windows supplies a KBDLLHOOKSTRUCT for HC_ACTION keyboard callbacks.
        let event = unsafe { &*(data.0 as *const KBDLLHOOKSTRUCT) };
        let down = message.0 as u32 == WM_KEYDOWN || message.0 as u32 == WM_SYSKEYDOWN;
        let up = message.0 as u32 == WM_KEYUP || message.0 as u32 == WM_SYSKEYUP;
        if (down || up)
            && record(
                Item::Key(canonical(event.vkCode as u16)),
                down,
                event.flags.0 & LLKHF_INJECTED.0 != 0,
                event.dwExtraInfo,
            )
        {
            return LRESULT(1);
        }
    }
    unsafe { CallNextHookEx(None, code, message, data) }
}
unsafe extern "system" fn mouse(code: i32, message: WPARAM, data: LPARAM) -> LRESULT {
    if code == HC_ACTION as i32 {
        // SAFETY: Windows supplies a MSLLHOOKSTRUCT for HC_ACTION mouse callbacks.
        let event = unsafe { &*(data.0 as *const MSLLHOOKSTRUCT) };
        let item = match message.0 as u32 {
            WM_LBUTTONDOWN => Some((1, true)),
            WM_LBUTTONUP => Some((1, false)),
            WM_RBUTTONDOWN => Some((2, true)),
            WM_RBUTTONUP => Some((2, false)),
            WM_MBUTTONDOWN => Some((3, true)),
            WM_MBUTTONUP => Some((3, false)),
            WM_XBUTTONDOWN => Some((3 + (event.mouseData >> 16) as u16, true)),
            WM_XBUTTONUP => Some((3 + (event.mouseData >> 16) as u16, false)),
            _ => None,
        };
        if let Some((button, down)) = item {
            if record(
                Item::Button(button),
                down,
                event.flags & 1 != 0,
                event.dwExtraInfo,
            ) {
                return LRESULT(1);
            }
        }
    }
    unsafe { CallNextHookEx(None, code, message, data) }
}
fn physical_source(item: Item, handle: usize, slot: u16, down: bool) {
    let Ok(mut state) = STATE.get().unwrap().lock() else {
        return;
    };
    if handle == 0 {
        state.ready = false;
        return;
    }
    let source = if let Some(source) = state.sources.get(&(handle, slot)) {
        *source
    } else {
        let source = state.next_source;
        state.next_source += 1;
        state.sources.insert((handle, slot), source);
        source
    };
    if down {
        if let Some(sources) = state.physical.get_mut(&item) {
            sources.remove(&1);
        }
        state.events.push(Event {
            item,
            source: 1,
            down: false,
            owned: false,
        });
        state.physical.entry(item).or_default().insert(source);
    } else if let Some(sources) = state.physical.get_mut(&item) {
        sources.remove(&source);
        if sources.is_empty() {
            state.physical.remove(&item);
        }
    }
    state.events.push(Event {
        item,
        source,
        down,
        owned: false,
    });
}
unsafe extern "system" fn raw_window(
    window: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    if message == WM_INPUT {
        let mut raw = Input::RAWINPUT::default();
        let mut size = std::mem::size_of::<Input::RAWINPUT>() as u32;
        let length = unsafe {
            Input::GetRawInputData(
                Input::HRAWINPUT(lparam.0 as *mut _),
                Input::RID_INPUT,
                Some((&mut raw as *mut Input::RAWINPUT).cast()),
                &mut size,
                std::mem::size_of::<Input::RAWINPUTHEADER>() as u32,
            )
        };
        if length != u32::MAX && length >= std::mem::size_of::<Input::RAWINPUTHEADER>() as u32 {
            let handle = raw.header.hDevice.0 as usize;
            if raw.header.dwType == Input::RIM_TYPEKEYBOARD.0 {
                let key = unsafe { raw.data.keyboard };
                physical_source(
                    Item::Key(canonical(key.VKey)),
                    handle,
                    key.MakeCode | (key.Flags & 6) << 8,
                    key.Flags & 1 == 0,
                );
            } else if raw.header.dwType == Input::RIM_TYPEMOUSE.0 {
                let mouse = unsafe { raw.data.mouse };
                let flags = unsafe { mouse.Anonymous.Anonymous.usButtonFlags };
                for (button, down, up) in [
                    (1, 1, 2),
                    (2, 4, 8),
                    (3, 16, 32),
                    (4, 64, 128),
                    (5, 256, 512),
                ] {
                    if flags & down != 0 {
                        physical_source(Item::Button(button), handle, button, true);
                    }
                    if flags & up != 0 {
                        physical_source(Item::Button(button), handle, button, false);
                    }
                }
            }
        }
    } else if message == WM_INPUT_DEVICE_CHANGE && wparam.0 == 2 {
        if let Ok(mut state) = STATE.get().unwrap().lock() {
            let removed = state
                .sources
                .iter()
                .filter(|((handle, _), _)| *handle == lparam.0 as usize)
                .map(|(_, source)| *source)
                .collect::<BTreeSet<_>>();
            let mut events = Vec::new();
            for (item, sources) in &mut state.physical {
                for source in &removed {
                    if sources.remove(source) {
                        events.push(Event {
                            item: *item,
                            source: *source,
                            down: false,
                            owned: false,
                        });
                    }
                }
            }
            state.physical.retain(|_, sources| !sources.is_empty());
            state
                .sources
                .retain(|(handle, _), _| *handle != lparam.0 as usize);
            state.events.extend(events);
        }
    }
    unsafe { DefWindowProcW(window, message, wparam, lparam) }
}
pub struct Native {
    keyboard: HHOOK,
    mouse: HHOOK,
    marker: usize,
    window: HWND,
}
impl Native {
    pub fn new(marker: usize) -> Result<Self> {
        STATE
            .set(Mutex::new(State {
                marker,
                events: Vec::new(),
                physical: BTreeMap::new(),
                sources: BTreeMap::new(),
                next_source: 2,
                ready: true,
                blocked: BTreeSet::new(),
                guard_releases: true,
            }))
            .map_err(|_| unavailable())?;
        let module = unsafe { GetModuleHandleW(None) }.map_err(|_| unavailable())?;
        let keyboard = unsafe {
            SetWindowsHookExW(WH_KEYBOARD_LL, Some(keyboard), Some(HINSTANCE(module.0)), 0)
        }
        .map_err(|_| unavailable())?;
        let mouse = match unsafe {
            SetWindowsHookExW(WH_MOUSE_LL, Some(mouse), Some(HINSTANCE(module.0)), 0)
        } {
            Ok(hook) => hook,
            Err(_) => {
                unsafe {
                    let _ = UnhookWindowsHookEx(keyboard);
                }
                return Err(unavailable());
            }
        };
        let class = WNDCLASSW {
            lpfnWndProc: Some(raw_window),
            hInstance: HINSTANCE(module.0),
            lpszClassName: w!("MemstackInputWatchdog"),
            ..Default::default()
        };
        if unsafe { RegisterClassW(&class) } == 0 {
            return Err(unavailable());
        }
        let window = unsafe {
            CreateWindowExW(
                WINDOW_EX_STYLE(0),
                w!("MemstackInputWatchdog"),
                w!(""),
                WINDOW_STYLE(0),
                0,
                0,
                0,
                0,
                Some(HWND_MESSAGE),
                None,
                Some(HINSTANCE(module.0)),
                None,
            )
        }
        .map_err(|_| unavailable())?;
        let devices = [
            Input::RAWINPUTDEVICE {
                usUsagePage: 1,
                usUsage: 6,
                dwFlags: Input::RIDEV_INPUTSINK | Input::RIDEV_DEVNOTIFY,
                hwndTarget: window,
            },
            Input::RAWINPUTDEVICE {
                usUsagePage: 1,
                usUsage: 2,
                dwFlags: Input::RIDEV_INPUTSINK | Input::RIDEV_DEVNOTIFY,
                hwndTarget: window,
            },
        ];
        unsafe {
            Input::RegisterRawInputDevices(
                &devices,
                std::mem::size_of::<Input::RAWINPUTDEVICE>() as u32,
            )
        }
        .map_err(|_| unavailable())?;
        // Start tracking from a neutral state. Unknown preexisting physical ownership cannot be claimed.
        if (1..=255).any(|code| unsafe { GetAsyncKeyState(code) } < 0) {
            return Err(unavailable());
        }
        Ok(Self {
            keyboard,
            mouse,
            marker,
            window,
        })
    }
    fn pump() {
        unsafe {
            let mut message = MSG::default();
            while PeekMessageW(&mut message, None, 0, 0, PM_REMOVE).as_bool() {
                let _ = TranslateMessage(&message);
                DispatchMessageW(&message);
            }
        }
    }
}
impl Driver for Native {
    fn guard_releases(&mut self, guard: bool) {
        if let Ok(mut state) = STATE.get().unwrap().lock() {
            state.guard_releases = guard;
        }
    }
    fn events(&mut self) -> Result<Vec<Event>> {
        Self::pump();
        Ok(std::mem::take(
            &mut STATE
                .get()
                .ok_or_else(unavailable)?
                .lock()
                .map_err(|_| unavailable())?
                .events,
        ))
    }
    fn inject(&mut self, item: Item, down: bool) -> Result<()> {
        let input = match item {
            Item::Key(code) => INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: VIRTUAL_KEY(code),
                        dwFlags: if down {
                            KEYBD_EVENT_FLAGS(0)
                        } else {
                            KEYEVENTF_KEYUP
                        },
                        dwExtraInfo: self.marker,
                        ..Default::default()
                    },
                },
            },
            Item::Button(button) => {
                let flags = match (button, down) {
                    (1, true) => MOUSEEVENTF_LEFTDOWN,
                    (1, false) => MOUSEEVENTF_LEFTUP,
                    (2, true) => MOUSEEVENTF_RIGHTDOWN,
                    (2, false) => MOUSEEVENTF_RIGHTUP,
                    (3, true) => MOUSEEVENTF_MIDDLEDOWN,
                    (3, false) => MOUSEEVENTF_MIDDLEUP,
                    _ => return Err(unavailable()),
                };
                INPUT {
                    r#type: INPUT_MOUSE,
                    Anonymous: INPUT_0 {
                        mi: MOUSEINPUT {
                            dwFlags: flags,
                            dwExtraInfo: self.marker,
                            ..Default::default()
                        },
                    },
                }
            }
        };
        if unsafe { SendInput(&[input], std::mem::size_of::<INPUT>() as i32) } != 1 {
            return Err(unavailable());
        }
        Self::pump();
        if STATE
            .get()
            .unwrap()
            .lock()
            .map_err(|_| unavailable())?
            .blocked
            .remove(&item)
        {
            return Err(NativeError::new(
                "input_deferred",
                "the user physically holds the same input",
            ));
        }
        Ok(())
    }
    fn available(&self) -> bool {
        !self.keyboard.is_invalid()
            && !self.mouse.is_invalid()
            && STATE
                .get()
                .is_some_and(|state| state.lock().is_ok_and(|state| state.ready))
    }
}
impl Drop for Native {
    fn drop(&mut self) {
        unsafe {
            let _ = UnhookWindowsHookEx(self.keyboard);
            let _ = UnhookWindowsHookEx(self.mouse);
            let _ = DestroyWindow(self.window);
        }
    }
}
