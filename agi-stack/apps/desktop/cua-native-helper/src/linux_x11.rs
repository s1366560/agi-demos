//! Exact native PID and window/frame geometry correlation; no title or app-name matching.
use crate::backend::{NativeError, Rect, Result};
pub fn matches(
    window: &sky_cua_linux::x11::windowing::X11WindowInfo,
    pid: Option<u32>,
    expected: Rect,
) -> bool {
    if window.app.pid != pid {
        return false;
    }
    let Some(bounds) = window.bounds.as_ref() else {
        return false;
    };
    let client = Rect {
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
    };
    if client == expected {
        return true;
    }
    let Ok(output) = std::process::Command::new("xprop")
        .args(["-id", &window.window_id, "_NET_FRAME_EXTENTS"])
        .output()
    else {
        return false;
    };
    if !output.status.success() {
        return false;
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let Some((_, values)) = text.trim().split_once('=') else {
        return false;
    };
    let extents = values
        .split(',')
        .map(|n| n.trim().parse::<u32>())
        .collect::<std::result::Result<Vec<_>, _>>();
    let Ok(extents) = extents else { return false };
    if extents.len() != 4 {
        return false;
    }
    Rect {
        x: client.x - extents[0] as f64,
        y: client.y - extents[2] as f64,
        width: client.width + extents[0] as f64 + extents[1] as f64,
        height: client.height + extents[2] as f64 + extents[3] as f64,
    } == expected
}
pub fn activate(pid: Option<u32>, expected: Rect) -> Result<()> {
    let window = resolve(pid, expected)?;
    sky_cua_linux::x11::input_xtest::window_activate(&window.window_id).map_err(NativeError::from)
}
pub fn resolve(
    pid: Option<u32>,
    expected: Rect,
) -> Result<sky_cua_linux::x11::windowing::X11WindowInfo> {
    let windows = sky_cua_linux::x11::windowing::discover_windows().map_err(NativeError::from)?;
    let mut candidates = windows
        .into_iter()
        .filter(|window| matches(window, pid, expected));
    let window = candidates.next().ok_or_else(|| {
        NativeError::new(
            "window_required",
            "native PID/window/frame identity is unavailable",
        )
    })?;
    if candidates.next().is_some() {
        return Err(NativeError::new(
            "window_required",
            "native PID/window/frame identity is ambiguous",
        ));
    }
    Ok(window)
}
