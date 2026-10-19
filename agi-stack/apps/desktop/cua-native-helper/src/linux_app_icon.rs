//! Exact PID/XID EWMH icons. Native app paths are never image-file inputs.
use crate::backend::{NativeError, Rect, Result};
use image::{Rgba, RgbaImage};
use x11rb::protocol::xproto::{AtomEnum, ConnectionExt as _};
fn unavailable() -> NativeError {
    NativeError::new(
        "app_icon_unavailable",
        "the exact native window does not expose a supported application icon",
    )
}
pub fn window(pid: Option<u32>, bounds: Rect) -> Result<RgbaImage> {
    let pid = pid.filter(|pid| *pid > 0).ok_or_else(unavailable)?;
    let selected = crate::linux_x11::resolve(Some(pid), bounds)?;
    let xid = selected
        .window_id
        .strip_prefix("0x")
        .and_then(|id| u32::from_str_radix(id, 16).ok())
        .or_else(|| selected.window_id.parse::<u32>().ok())
        .ok_or_else(unavailable)?;
    let (connection, _) = x11rb::connect(None).map_err(|_| unavailable())?;
    let atom = |name: &[u8]| {
        connection
            .intern_atom(true, name)
            .map_err(|_| unavailable())?
            .reply()
            .map(|r| r.atom)
            .map_err(|_| unavailable())
    };
    let pid_atom = atom(b"_NET_WM_PID")?;
    let actual = connection
        .get_property(false, xid, pid_atom, AtomEnum::CARDINAL, 0, 1)
        .map_err(|_| unavailable())?
        .reply()
        .map_err(|_| unavailable())?
        .value32()
        .and_then(|mut values| values.next());
    if actual != Some(pid) {
        return Err(NativeError::new(
            "app_icon_identity_changed",
            "the native icon window no longer belongs to the resolved process",
        ));
    }
    let icon_atom = atom(b"_NET_WM_ICON")?;
    let reply = connection
        .get_property(
            false,
            xid,
            icon_atom,
            AtomEnum::CARDINAL,
            0,
            1024 * 1024 + 2,
        )
        .map_err(|_| unavailable())?
        .reply()
        .map_err(|_| unavailable())?;
    if reply.bytes_after != 0 || reply.format != 32 {
        return Err(unavailable());
    }
    let values = reply.value32().ok_or_else(unavailable)?.collect::<Vec<_>>();
    decode(&values)
}
fn decode(values: &[u32]) -> Result<RgbaImage> {
    let mut offset = 0usize;
    let mut selected = None;
    while offset < values.len() {
        let width = *values.get(offset).ok_or_else(unavailable)?;
        let height = *values.get(offset + 1).ok_or_else(unavailable)?;
        let count = (width as usize)
            .checked_mul(height as usize)
            .ok_or_else(unavailable)?;
        let end = offset
            .checked_add(2)
            .and_then(|start| start.checked_add(count))
            .filter(|end| *end <= values.len())
            .ok_or_else(unavailable)?;
        if width == 0 || height == 0 {
            return Err(unavailable());
        }
        if width <= 1024 && height <= 1024 {
            let rank = if width >= 64 && height >= 64 {
                (0, count)
            } else {
                (1, usize::MAX - count)
            };
            if selected.as_ref().is_none_or(|(old, _, _, _)| rank < *old) {
                selected = Some((rank, width, height, &values[offset + 2..end]));
            }
        }
        offset = end;
    }
    let (_, width, height, pixels) = selected.ok_or_else(unavailable)?;
    let mut image = RgbaImage::new(width, height);
    for (pixel, argb) in image.pixels_mut().zip(pixels) {
        *pixel = Rgba([
            (argb >> 16) as u8,
            (argb >> 8) as u8,
            *argb as u8,
            (argb >> 24) as u8,
        ]);
    }
    Ok(image)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_argb_codec_retains_color_alpha_and_dimension_selection() {
        let mut data = vec![1, 1, 0x80112233];
        data.extend([64, 64]);
        data.extend(std::iter::repeat_n(0xffabcdef, 64 * 64));
        data.extend([128, 128]);
        data.extend(std::iter::repeat_n(0xffffffff, 128 * 128));
        let image = decode(&data).unwrap();
        assert_eq!(image.dimensions(), (64, 64));
        assert_eq!(image.get_pixel(0, 0).0, [0xab, 0xcd, 0xef, 0xff]);
        assert_eq!(
            decode(&[1, 1, 0x80112233]).unwrap().get_pixel(0, 0).0,
            [0x11, 0x22, 0x33, 0x80]
        );
    }
    #[test]
    fn malformed_native_icon_payload_fails_without_partial_decode() {
        for data in [
            vec![],
            vec![1],
            vec![0, 1],
            vec![64, 64, 1],
            vec![u32::MAX, u32::MAX],
        ] {
            assert!(decode(&data).is_err());
        }
    }
}

/// Resolve only native inventory icon metadata. File icons outside OS icon namespaces
/// and vector formats with external resource references are deliberately not decoded.
pub fn installed(app: &crate::backend::App, root: &std::path::Path) -> Result<serde_json::Value> {
    use gio::prelude::*;
    let info = if let Some(id) = app
        .installed_id
        .as_deref()
        .and_then(|id| id.strip_prefix("desktop:"))
    {
        let current = crate::linux_apps::resolve(&format!("desktop:{id}"))?;
        if current.identity_digest != app.identity_digest {
            return Err(NativeError::new(
                "app_icon_identity_changed",
                "the registered application identity changed",
            ));
        }
        gio::DesktopAppInfo::new(id).ok_or_else(unavailable)?
    } else {
        let path = app.app_path.as_ref().ok_or_else(unavailable)?;
        let mut matching = gio::AppInfo::all()
            .into_iter()
            .filter_map(|info| info.downcast::<gio::DesktopAppInfo>().ok())
            .filter(|info| {
                let executable = info.executable();
                let executable = if executable.is_absolute() {
                    Some(executable)
                } else {
                    gio::glib::find_program_in_path(executable)
                };
                executable
                    .and_then(|path| path.canonicalize().ok())
                    .is_some_and(|actual| actual.to_string_lossy() == *path)
            });
        let first = matching.next().ok_or_else(unavailable)?;
        let icon = first.icon().and_then(|icon| icon.to_string());
        if matching.any(|info| info.icon().and_then(|value| value.to_string()) != icon) {
            return Err(NativeError::new(
                "app_icon_unavailable",
                "multiple registered icons share this executable; select an exact native window",
            ));
        }
        first
    };
    let icon = info.icon().ok_or_else(unavailable)?;
    let roots = icon_roots();
    if let Ok(file) = icon.clone().downcast::<gio::FileIcon>() {
        let source = file.file().path().ok_or_else(unavailable)?;
        return crate::app_icon::write_png(root, read_owned_resource(&source, &roots)?);
    }
    let themed = icon
        .downcast::<gio::ThemedIcon>()
        .map_err(|_| unavailable())?;
    for name in themed.names() {
        if !single_component(&name) {
            continue;
        }
        for namespace in &roots {
            let mut pending = vec![namespace.clone()];
            let mut visited = 0usize;
            while let Some(directory) = pending.pop() {
                visited += 1;
                if visited > 8192 {
                    break;
                }
                let Ok(entries) = std::fs::read_dir(&directory) else {
                    continue;
                };
                let mut entries = entries.filter_map(|entry| entry.ok()).collect::<Vec<_>>();
                entries.sort_by_key(|entry| entry.file_name());
                for entry in entries {
                    let path = entry.path();
                    let Ok(kind) = entry.file_type() else {
                        continue;
                    };
                    if kind.is_dir()
                        && !kind.is_symlink()
                        && path.components().count() <= namespace.components().count() + 6
                    {
                        pending.push(path);
                        continue;
                    }
                    if ["png", "jpg", "webp"].iter().any(|extension| {
                        entry.file_name() == std::ffi::OsStr::new(&format!("{name}.{extension}"))
                    }) {
                        if let Ok(image) = read_owned_resource(&path, &roots) {
                            return crate::app_icon::write_png(root, image);
                        }
                    }
                }
            }
        }
    }
    Err(NativeError::new(
        "app_icon_unavailable",
        "the registered native icon has no bounded raster resource in an OS icon namespace",
    ))
}
fn icon_roots() -> Vec<std::path::PathBuf> {
    let mut data = vec![gio::glib::user_data_dir()];
    data.extend(gio::glib::system_data_dirs());
    data.into_iter()
        .flat_map(|path| [path.join("icons"), path.join("pixmaps")])
        .filter_map(|path| path.canonicalize().ok())
        .collect()
}
fn single_component(name: &str) -> bool {
    let mut parts = std::path::Path::new(name).components();
    matches!(parts.next(), Some(std::path::Component::Normal(_))) && parts.next().is_none()
}
fn read_owned_resource(
    source: &std::path::Path,
    roots: &[std::path::PathBuf],
) -> Result<RgbaImage> {
    let source = source.canonicalize().map_err(|_| unavailable())?;
    if !roots.iter().any(|root| source.starts_with(root)) {
        return Err(NativeError::new(
            "app_icon_unavailable",
            "the registered icon is outside OS icon namespaces",
        ));
    }
    let mut file = std::fs::File::open(&source).map_err(|_| unavailable())?;
    use std::io::Read;
    let mut bytes = Vec::new();
    std::io::Read::by_ref(&mut file)
        .take(2 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| unavailable())?;
    if bytes.len() > 2 * 1024 * 1024 {
        return Err(unavailable());
    }
    let mut reader = image::ImageReader::new(std::io::Cursor::new(bytes))
        .with_guessed_format()
        .map_err(|_| unavailable())?;
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(1024);
    limits.max_image_height = Some(1024);
    limits.max_alloc = Some(8 * 1024 * 1024);
    reader.limits(limits);
    reader
        .decode()
        .map(|image| image.to_rgba8())
        .map_err(|_| unavailable())
}

#[cfg(test)]
mod resource_tests {
    use super::*;
    #[test]
    fn native_icon_resource_namespace_rejects_paths_and_symlink_escape() {
        let temp = tempfile::tempdir().unwrap();
        let icons = temp.path().join("icons");
        std::fs::create_dir(&icons).unwrap();
        let secret = temp.path().join("outside.png");
        image::RgbaImage::from_pixel(1, 1, image::Rgba([1, 2, 3, 255]))
            .save(&secret)
            .unwrap();
        std::os::unix::fs::symlink(&secret, icons.join("escape.png")).unwrap();
        assert!(read_owned_resource(&secret, &[icons.clone()]).is_err());
        assert!(read_owned_resource(&icons.join("escape.png"), &[icons]).is_err());
        assert!(!single_component("../arbitrary"));
        assert!(!single_component("/tmp/arbitrary"));
        assert!(single_component("native-application-icon"));
    }
}
