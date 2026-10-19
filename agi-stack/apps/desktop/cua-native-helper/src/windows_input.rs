//! Explicit SendInput primitives. Held keys belong to the global session input lease.
use crate::backend::{check_cancel, NativeError, Result};
use crate::input_watchdog::{Item, Watchdog};
use std::{
    collections::BTreeSet,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    },
    time::Duration,
};
use tokio::sync::Mutex;
use windows::Win32::UI::{Input::KeyboardAndMouse::*, WindowsAndMessaging::SetCursorPos};

static MARKER: AtomicUsize = AtomicUsize::new(0);
pub struct Input {
    held: Mutex<BTreeSet<u16>>,
    button: Mutex<bool>,
    watchdog: Option<Watchdog>,
    device_lease: std::sync::Mutex<Option<crate::device_lease::DeviceLease>>,
}
impl Default for Input {
    fn default() -> Self {
        let watchdog = Watchdog::start().ok();
        let marker = watchdog
            .as_ref()
            .map(|watchdog| watchdog.marker())
            .unwrap_or_else(|| uuid::Uuid::new_v4().as_u128() as usize | 1);
        MARKER.store(marker, Ordering::Release);
        Self {
            held: Mutex::new(BTreeSet::new()),
            button: Mutex::new(false),
            watchdog,
            device_lease: std::sync::Mutex::new(None),
        }
    }
}
fn send(input: &[INPUT]) -> Result<()> {
    let mut input = input.to_vec();
    for event in &mut input {
        if event.r#type == INPUT_KEYBOARD {
            event.Anonymous.ki.dwExtraInfo = MARKER.load(Ordering::Acquire);
        } else if event.r#type == INPUT_MOUSE {
            event.Anonymous.mi.dwExtraInfo = MARKER.load(Ordering::Acquire);
        }
    }
    // SAFETY: all INPUT unions are initialized for their declared type.
    if unsafe { SendInput(&input, std::mem::size_of::<INPUT>() as i32) } != input.len() as u32 {
        return Err(NativeError::new(
            "input_permission_required",
            "Windows rejected native input; target integrity or desktop permission changed",
        ));
    }
    Ok(())
}
fn key_input(code: u16, up: bool) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: VIRTUAL_KEY(code),
                dwFlags: if up {
                    KEYEVENTF_KEYUP
                } else {
                    KEYBD_EVENT_FLAGS(0)
                },
                ..Default::default()
            },
        },
    }
}
pub fn chord(name: &str) -> Result<Vec<u16>> {
    name.split('+')
        .map(|part| {
            let code = match part.to_ascii_lowercase().as_str() {
                "ctrl" | "control" => VK_CONTROL.0,
                "alt" | "option" => VK_MENU.0,
                "shift" => VK_SHIFT.0,
                "win" | "super" | "meta" => VK_LWIN.0,
                "enter" | "return" => VK_RETURN.0,
                "tab" => VK_TAB.0,
                "escape" | "esc" => VK_ESCAPE.0,
                "backspace" => VK_BACK.0,
                "delete" => VK_DELETE.0,
                "space" => VK_SPACE.0,
                "left" => VK_LEFT.0,
                "right" => VK_RIGHT.0,
                "up" => VK_UP.0,
                "down" => VK_DOWN.0,
                "home" => VK_HOME.0,
                "end" => VK_END.0,
                "pageup" => VK_PRIOR.0,
                "pagedown" => VK_NEXT.0,
                other if other.len() == 1 && other.as_bytes()[0].is_ascii_alphanumeric() => {
                    other.as_bytes()[0].to_ascii_uppercase() as u16
                }
                other if other.starts_with('f') => other[1..]
                    .parse::<u16>()
                    .ok()
                    .filter(|n| (1..=24).contains(n))
                    .map(|n| VK_F1.0 + n - 1)
                    .ok_or_else(|| NativeError::new("invalid_params", "unsupported native key"))?,
                _ => return Err(NativeError::new("invalid_params", "unsupported native key")),
            };
            Ok(code)
        })
        .collect()
}
impl Input {
    pub fn guardian(&self) -> Result<&Watchdog> {
        self.watchdog
            .as_ref()
            .filter(|guard| guard.alive())
            .ok_or_else(|| NativeError::unsupported("resource guardian"))
    }
    pub fn acquire(&self) -> Result<()> {
        if let Some(watchdog) = self.watchdog.as_ref().filter(|watchdog| watchdog.alive()) {
            return watchdog.acquire();
        }
        let mut lease = self
            .device_lease
            .lock()
            .map_err(|_| NativeError::unsupported("device lease"))?;
        if lease.is_none() {
            *lease = Some(crate::device_lease::DeviceLease::acquire()?);
        }
        Ok(())
    }
    pub async fn hold(&self, name: &str, down: bool) -> Result<()> {
        if !self.held_input_available() {
            return Err(NativeError::unsupported("input watchdog"));
        }
        let keys = chord(name)?;
        let mut held = self.held.lock().await;
        if down {
            let mut added = Vec::new();
            let result = (|| {
                for code in &keys {
                    if held.contains(code) {
                        continue;
                    }
                    // Do not take ownership of a key already held by the user.
                    if unsafe { GetAsyncKeyState(*code as i32) } < 0 {
                        return Err(NativeError::new(
                            "input_busy",
                            "native key is already held by the user",
                        ));
                    }
                    self.watchdog
                        .as_ref()
                        .filter(|watchdog| watchdog.available())
                        .ok_or_else(|| NativeError::unsupported("input watchdog"))?
                        .hold(Item::Key(*code), true)?;
                    held.insert(*code);
                    added.push(*code);
                }
                Ok(())
            })();
            if result.is_err() {
                for code in added.into_iter().rev() {
                    if let Some(watchdog) = &self.watchdog {
                        let _ = watchdog.hold(Item::Key(code), false);
                    }
                    held.remove(&code);
                }
            }
            result?;
        } else {
            for code in keys.into_iter().rev() {
                if held.remove(&code) {
                    self.watchdog
                        .as_ref()
                        .ok_or_else(|| NativeError::unsupported("input watchdog"))?
                        .hold(Item::Key(code), false)?;
                }
            }
        }
        Ok(())
    }
    pub async fn press(&self, name: &str) -> Result<()> {
        if !self.held_input_available() {
            let keys = chord(name)?;
            if keys
                .iter()
                .any(|code| unsafe { GetAsyncKeyState(*code as i32) } < 0)
            {
                return Err(NativeError::new("input_busy", "native key is already held"));
            }
            let mut input = keys
                .iter()
                .map(|code| key_input(*code, false))
                .collect::<Vec<_>>();
            input.extend(keys.iter().rev().map(|code| key_input(*code, true)));
            return send(&input);
        }
        let existing = self.held.lock().await.clone();
        let result = self.hold(name, true).await;
        let mut held = self.held.lock().await;
        let added = held.difference(&existing).copied().collect::<Vec<_>>();
        for code in added.into_iter().rev() {
            held.remove(&code);
            if let Some(watchdog) = &self.watchdog {
                let _ = watchdog.hold(Item::Key(code), false);
            }
        }
        result
    }
    pub fn scalar(character: char) -> Result<()> {
        let mut buffer = [0; 2];
        for unit in character.encode_utf16(&mut buffer).iter().copied() {
            send(&[
                INPUT {
                    r#type: INPUT_KEYBOARD,
                    Anonymous: INPUT_0 {
                        ki: KEYBDINPUT {
                            wScan: unit,
                            dwFlags: KEYEVENTF_UNICODE,
                            ..Default::default()
                        },
                    },
                },
                INPUT {
                    r#type: INPUT_KEYBOARD,
                    Anonymous: INPUT_0 {
                        ki: KEYBDINPUT {
                            wScan: unit,
                            dwFlags: KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                            ..Default::default()
                        },
                    },
                },
            ])?;
        }
        Ok(())
    }
    pub fn move_to(x: f64, y: f64) -> Result<()> {
        if !x.is_finite()
            || !y.is_finite()
            || x < i32::MIN as f64
            || x > i32::MAX as f64
            || y < i32::MIN as f64
            || y > i32::MAX as f64
        {
            return Err(NativeError::new(
                "invalid_params",
                "invalid native coordinates",
            ));
        }
        unsafe { SetCursorPos(x.round() as i32, y.round() as i32) }.map_err(|_| {
            NativeError::new(
                "input_permission_required",
                "Windows rejected pointer movement",
            )
        })
    }
    fn mouse(flags: MOUSE_EVENT_FLAGS, data: u32) -> Result<()> {
        send(&[INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dwFlags: flags,
                    mouseData: data,
                    ..Default::default()
                },
            },
        }])
    }
    pub fn click(&self, button: &str) -> Result<()> {
        let (down, up) = match button {
            "left" => (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            "right" => (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
            "middle" => (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
            _ => return Err(NativeError::new("invalid_params", "invalid mouse button")),
        };
        let code = match button {
            "left" => 1,
            "right" => 2,
            "middle" => 3,
            _ => 0,
        };
        if let Some(watchdog) = self
            .watchdog
            .as_ref()
            .filter(|watchdog| watchdog.available())
        {
            return watchdog.tap(Item::Button(code));
        }
        let input = [down, up].map(|flags| INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dwFlags: flags,
                    ..Default::default()
                },
            },
        });
        send(&input)
    }
    pub fn scroll(direction: &str, pages: f64) -> Result<()> {
        if !pages.is_finite() || !(0.1..=100.0).contains(&pages) {
            return Err(NativeError::new("invalid_params", "invalid scroll pages"));
        }
        let (flags, sign) = match direction {
            "up" => (MOUSEEVENTF_WHEEL, 1),
            "down" => (MOUSEEVENTF_WHEEL, -1),
            "right" => (MOUSEEVENTF_HWHEEL, 1),
            "left" => (MOUSEEVENTF_HWHEEL, -1),
            _ => {
                return Err(NativeError::new(
                    "invalid_params",
                    "invalid scroll direction",
                ));
            }
        };
        Self::mouse(flags, ((pages * 120.0).round() as i32 * sign) as u32)
    }
    pub async fn drag_step(&self, x: f64, y: f64, phase: &str) -> Result<()> {
        Self::move_to(x, y)?;
        let mut button = self.button.lock().await;
        match phase {
            "begin" => {
                if *button {
                    return Err(NativeError::new("input_busy", "drag already active"));
                }
                self.watchdog
                    .as_ref()
                    .filter(|watchdog| watchdog.available())
                    .ok_or_else(|| NativeError::unsupported("input watchdog"))?
                    .hold(Item::Button(1), true)?;
                *button = true;
            }
            "move" => {
                if !*button {
                    return Err(NativeError::new(
                        "invalid_params",
                        "begin a drag before moving",
                    ));
                }
            }
            "end" => {
                if *button {
                    self.watchdog
                        .as_ref()
                        .ok_or_else(|| NativeError::unsupported("input watchdog"))?
                        .hold(Item::Button(1), false)?;
                    *button = false;
                }
            }
            _ => return Err(NativeError::new("invalid_params", "invalid drag phase")),
        }
        Ok(())
    }
    pub async fn drag(
        &self,
        from: (f64, f64),
        to: (f64, f64),
        cancel: Arc<AtomicBool>,
    ) -> Result<()> {
        self.drag_step(from.0, from.1, "begin").await?;
        let result = async {
            for step in 1..=24 {
                check_cancel(&cancel)?;
                let t = step as f64 / 24.0;
                Self::move_to(from.0 + (to.0 - from.0) * t, from.1 + (to.1 - from.1) * t)?;
                tokio::time::sleep(Duration::from_millis(8)).await;
            }
            Ok(())
        }
        .await;
        self.release().await;
        result
    }
    pub fn held_input_available(&self) -> bool {
        self.watchdog
            .as_ref()
            .is_some_and(|watchdog| watchdog.available())
    }
    pub async fn release(&self) {
        self.held.lock().await.clear();
        *self.button.lock().await = false;
        if let Some(watchdog) = &self.watchdog {
            let _ = watchdog.release();
        }
        if let Ok(mut lease) = self.device_lease.lock() {
            lease.take();
        }
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn native_key_codec_is_exact() {
        assert_eq!(
            super::chord("Ctrl+Shift+A").unwrap(),
            vec![0x11, 0x10, 0x41]
        );
        assert_eq!(super::chord("F24").unwrap(), vec![0x87]);
        assert!(super::chord("unknown").is_err());
    }
}
