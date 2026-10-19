//! Capture an exact native window pixmap, including pixels hidden by another application.
use crate::backend::{NativeError, Rect, Result};
use image::{Rgba, RgbaImage};
use std::{collections::BTreeSet, path::Path};
use x11rb::{
    connection::Connection,
    protocol::{
        composite::{ConnectionExt as _, Redirect},
        xproto::{ConnectionExt as _, ImageFormat, ImageOrder, VisualClass},
    },
};
fn unavailable() -> NativeError {
    NativeError::new(
        "capture_unavailable",
        "exact X11 window capture requires XComposite and a supported native visual",
    )
}
fn geometry(
    connection: &x11rb::rust_connection::RustConnection,
    root: u32,
    id: u32,
) -> Result<Rect> {
    let geometry = connection
        .get_geometry(id)
        .map_err(|_| unavailable())?
        .reply()
        .map_err(|_| unavailable())?;
    let position = connection
        .translate_coordinates(id, root, 0, 0)
        .map_err(|_| unavailable())?
        .reply()
        .map_err(|_| unavailable())?;
    Ok(Rect {
        x: position.dst_x as f64,
        y: position.dst_y as f64,
        width: geometry.width as f64,
        height: geometry.height as f64,
    })
}
pub fn available() -> bool {
    let Ok((connection, _)) = x11rb::connect(None) else {
        return false;
    };
    connection
        .composite_query_version(0, 4)
        .ok()
        .and_then(|reply| reply.reply().ok())
        .is_some_and(|version| version.major_version > 0 || version.minor_version >= 2)
}
pub struct Capture {
    connection: x11rb::rust_connection::RustConnection,
    screen: usize,
    redirected: BTreeSet<u32>,
}
impl Capture {
    pub fn new() -> Result<Self> {
        let (connection, screen) = x11rb::connect(None).map_err(|_| unavailable())?;
        Ok(Self {
            connection,
            screen,
            redirected: BTreeSet::new(),
        })
    }
    pub fn capture(&mut self, pid: Option<u32>, expected: Rect, output: &Path) -> Result<u32> {
        let selected = crate::linux_x11::resolve(pid, expected)?;
        let client = selected
            .window_id
            .strip_prefix("0x")
            .and_then(|id| u32::from_str_radix(id, 16).ok())
            .or_else(|| selected.window_id.parse::<u32>().ok())
            .ok_or_else(unavailable)?;
        let connection = &self.connection;
        let screen = self.screen;
        let version = connection
            .composite_query_version(0, 4)
            .map_err(|_| unavailable())?
            .reply()
            .map_err(|_| unavailable())?;
        if version.major_version == 0 && version.minor_version < 2 {
            return Err(unavailable());
        }
        let root = connection.setup().roots[screen].root;
        let atom = connection
            .intern_atom(true, b"_NET_WM_PID")
            .map_err(|_| unavailable())?
            .reply()
            .map_err(|_| unavailable())?
            .atom;
        let actual_pid = connection
            .get_property(
                false,
                client,
                atom,
                x11rb::protocol::xproto::AtomEnum::CARDINAL,
                0,
                1,
            )
            .map_err(|_| unavailable())?
            .reply()
            .map_err(|_| unavailable())?
            .value32()
            .and_then(|mut values| values.next());
        if pid.is_none() || actual_pid != pid {
            return Err(NativeError::new(
                "capture_identity_mismatch",
                "native XID no longer belongs to the approved process",
            ));
        }
        let mut target = client;
        for _ in 0..8 {
            if geometry(&connection, root, target)? == expected {
                break;
            }
            let parent = connection
                .query_tree(target)
                .map_err(|_| unavailable())?
                .reply()
                .map_err(|_| unavailable())?
                .parent;
            if parent == root || parent == 0 {
                return Err(NativeError::new(
                    "capture_geometry_unavailable",
                    "native XID and AT-SPI frame do not agree",
                ));
            }
            target = parent;
        }
        if geometry(&connection, root, target)? != expected {
            return Err(unavailable());
        }
        let attributes = connection
            .get_window_attributes(target)
            .map_err(|_| unavailable())?
            .reply()
            .map_err(|_| unavailable())?;
        let visual = connection.setup().roots[screen]
            .allowed_depths
            .iter()
            .flat_map(|depth| &depth.visuals)
            .find(|visual| {
                visual.visual_id == attributes.visual && visual.class == VisualClass::TRUE_COLOR
            })
            .ok_or_else(unavailable)?;
        if !self.redirected.contains(&target) {
            connection
                .composite_redirect_window(target, Redirect::AUTOMATIC)
                .map_err(|_| unavailable())?
                .check()
                .map_err(|_| unavailable())?;
            self.redirected.insert(target);
            // The server exposes the newly redirected surface. Keep this connection alive
            // so subsequent captures retain pixels even while another app obscures it.
            std::thread::sleep(std::time::Duration::from_millis(40));
        }
        let pixmap = connection.generate_id().map_err(|_| unavailable())?;
        let result = (|| {
            connection
                .composite_name_window_pixmap(target, pixmap)
                .map_err(|_| unavailable())?
                .check()
                .map_err(|_| unavailable())?;
            let native = connection
                .get_geometry(pixmap)
                .map_err(|_| unavailable())?
                .reply()
                .map_err(|_| unavailable())?;
            if native.width == 0
                || native.height == 0
                || native.width as u64 * native.height as u64 > 32_000_000
            {
                return Err(unavailable());
            }
            let format = connection
                .setup()
                .pixmap_formats
                .iter()
                .find(|format| format.depth == native.depth)
                .ok_or_else(unavailable)?;
            if !matches!(format.bits_per_pixel, 16 | 24 | 32) || format.scanline_pad == 0 {
                return Err(unavailable());
            }
            let frame = connection
                .get_image(
                    ImageFormat::Z_PIXMAP,
                    pixmap,
                    0,
                    0,
                    native.width,
                    native.height,
                    u32::MAX,
                )
                .map_err(|_| unavailable())?
                .reply()
                .map_err(|_| unavailable())?;
            let bytes = format.bits_per_pixel as usize / 8;
            let stride = (native.width as usize * format.bits_per_pixel as usize)
                .div_ceil(format.scanline_pad as usize)
                * (format.scanline_pad as usize / 8);
            if frame.data.len() < stride * native.height as usize {
                return Err(unavailable());
            }
            let channel = |pixel: u32, mask: u32| -> Result<u8> {
                if mask == 0 {
                    return Err(unavailable());
                }
                let maximum = mask >> mask.trailing_zeros();
                Ok((((pixel & mask) >> mask.trailing_zeros()) as u64 * 255 / maximum as u64) as u8)
            };
            let mut image = RgbaImage::new(native.width as u32, native.height as u32);
            for (y, row) in frame
                .data
                .chunks_exact(stride)
                .take(native.height as usize)
                .enumerate()
            {
                for (x, value) in row
                    .chunks_exact(bytes)
                    .take(native.width as usize)
                    .enumerate()
                {
                    let pixel = if connection.setup().image_byte_order == ImageOrder::LSB_FIRST {
                        value.iter().enumerate().fold(0, |pixel, (shift, byte)| {
                            pixel | (*byte as u32) << (shift * 8)
                        })
                    } else {
                        value
                            .iter()
                            .fold(0, |pixel, byte| (pixel << 8) | *byte as u32)
                    };
                    image.put_pixel(
                        x as u32,
                        y as u32,
                        Rgba([
                            channel(pixel, visual.red_mask)?,
                            channel(pixel, visual.green_mask)?,
                            channel(pixel, visual.blue_mask)?,
                            255,
                        ]),
                    );
                }
            }
            if geometry(&connection, root, target)? != expected {
                return Err(NativeError::new(
                    "capture_geometry_changed",
                    "native window moved during capture",
                ));
            }
            image.save(output).map_err(|_| {
                NativeError::new("capture_failed", "cannot save exact native window pixels")
            })?;
            Ok(target)
        })();
        let _ = connection.free_pixmap(pixmap);
        let _ = connection.flush();
        result
    }
}
impl Drop for Capture {
    fn drop(&mut self) {
        for target in &self.redirected {
            let _ = self
                .connection
                .composite_unredirect_window(*target, Redirect::AUTOMATIC);
        }
        let _ = self.connection.flush();
    }
}
