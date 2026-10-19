//! Shell icon-only metadata for native inventory entries and frozen executable identities.
use crate::backend::{App, NativeError, Result};
use image::RgbaImage;
use std::path::Path;
use windows::{
    core::{Interface, PCWSTR},
    Win32::{Foundation::SIZE, Graphics::Gdi::*, UI::Shell::*},
};
fn unavailable() -> NativeError {
    NativeError::new(
        "app_icon_unavailable",
        "the native shell cannot provide a bounded application icon",
    )
}
struct Bitmap(HBITMAP);
impl Drop for Bitmap {
    fn drop(&mut self) {
        unsafe {
            let _ = DeleteObject(self.0.into());
        }
    }
}
struct Dc(HDC);
impl Drop for Dc {
    fn drop(&mut self) {
        unsafe {
            let _ = DeleteDC(self.0);
        }
    }
}
pub fn from_item(item: &IShellItem) -> Result<RgbaImage> {
    let factory: IShellItemImageFactory = item.cast().map_err(|_| unavailable())?;
    let bitmap = Bitmap(
        unsafe {
            factory.GetImage(
                SIZE { cx: 64, cy: 64 },
                SIIGBF_ICONONLY | SIIGBF_BIGGERSIZEOK,
            )
        }
        .map_err(|_| unavailable())?,
    );
    let mut native = BITMAP::default();
    if unsafe {
        GetObjectW(
            bitmap.0.into(),
            std::mem::size_of::<BITMAP>() as i32,
            Some((&mut native as *mut BITMAP).cast()),
        )
    } == 0
        || native.bmWidth <= 0
        || native.bmHeight <= 0
        || native.bmWidth > 1024
        || native.bmHeight > 1024
    {
        return Err(unavailable());
    }
    let width = native.bmWidth as u32;
    let height = native.bmHeight as u32;
    let mut info = BITMAPINFO {
        bmiHeader: BITMAPINFOHEADER {
            biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: native.bmWidth,
            biHeight: -native.bmHeight,
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB.0,
            ..Default::default()
        },
        ..Default::default()
    };
    let dc = Dc(unsafe { CreateCompatibleDC(None) });
    if dc.0.is_invalid() {
        return Err(unavailable());
    }
    let mut pixels = vec![0u8; width as usize * height as usize * 4];
    if unsafe {
        GetDIBits(
            dc.0,
            bitmap.0,
            0,
            height,
            Some(pixels.as_mut_ptr().cast()),
            &mut info,
            DIB_RGB_COLORS,
        )
    } != height as i32
    {
        return Err(unavailable());
    }
    bgra(width, height, pixels)
}
fn bgra(width: u32, height: u32, mut bytes: Vec<u8>) -> Result<RgbaImage> {
    if width == 0
        || height == 0
        || width > 1024
        || height > 1024
        || bytes.len() != width as usize * height as usize * 4
    {
        return Err(unavailable());
    }
    for pixel in bytes.chunks_exact_mut(4) {
        pixel.swap(0, 2);
        // Shell bitmap alpha is premultiplied; PNG uses straight alpha.
        if pixel[3] != 0 && pixel[3] != 255 {
            for index in 0..3 {
                pixel[index] = ((pixel[index] as u32 * 255 + pixel[3] as u32 / 2) / pixel[3] as u32)
                    .min(255) as u8;
            }
        }
    }
    RgbaImage::from_raw(width, height, bytes).ok_or_else(unavailable)
}
pub fn icon(app: &App, root: &Path) -> Result<serde_json::Value> {
    let image = if app.installed_id.is_some() {
        crate::windows_apps::icon(app)?
    } else {
        if app.process_id.is_none() || !app.id.starts_with("pid:") {
            return Err(unavailable());
        }
        let path = app.app_path.as_ref().ok_or_else(unavailable)?;
        let current = App::new(
            app.id.clone(),
            app.display_name.clone(),
            app.process_id,
            Some(path.clone()),
        );
        if current.identity_digest.is_empty() || current.identity_digest != app.identity_digest {
            return Err(NativeError::new(
                "app_icon_identity_changed",
                "the frozen native executable changed",
            ));
        }
        let wide = path.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
        let item: IShellItem = unsafe { SHCreateItemFromParsingName(PCWSTR(wide.as_ptr()), None) }
            .map_err(|_| unavailable())?;
        from_item(&item)?
    };
    crate::app_icon::write_png(root, image)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_shell_bitmap_codec_keeps_channels_and_unpremultiplies_alpha() {
        let image = bgra(1, 1, vec![16, 32, 64, 128]).unwrap();
        assert_eq!(image.get_pixel(0, 0).0, [128, 64, 32, 128]);
        assert!(bgra(1, 1, vec![0, 0, 0]).is_err());
        assert!(bgra(0, 1, vec![]).is_err());
    }
}
