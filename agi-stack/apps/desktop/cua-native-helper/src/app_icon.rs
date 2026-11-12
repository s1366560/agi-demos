//! UI-only application icons, encoded as owned bounded PNG files.
use crate::backend::{NativeError, Result};
use image::{imageops::FilterType, ImageFormat, RgbaImage};
use serde_json::{json, Value};
use std::{
    io::{BufWriter, Write},
    path::Path,
};
pub fn write_png(root: &Path, source: RgbaImage) -> Result<Value> {
    let width = source.width();
    let height = source.height();
    if width == 0 || height == 0 || width > 1024 || height > 1024 {
        return Err(NativeError::new(
            "app_icon_unavailable",
            "native icon raster dimensions are unsupported",
        ));
    }
    let image = image::imageops::resize(&source, 64, 64, FilterType::Lanczos3);
    let path = root.join(format!("app-icon-{}.png", uuid::Uuid::new_v4()));
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options
        .open(&path)
        .map_err(|_| NativeError::new("artifact_unavailable", "cannot create owned icon"))?;
    let mut writer = BufWriter::new(file);
    image
        .write_to(&mut writer, ImageFormat::Png)
        .and_then(|_| writer.flush().map_err(image::ImageError::IoError))
        .map_err(|_| NativeError::new("app_icon_unavailable", "native icon PNG encoding failed"))?;
    let url = url::Url::from_file_path(&path)
        .map_err(|_| NativeError::new("artifact_unavailable", "invalid owned icon URL"))?;
    Ok(json!({"url":url.as_str(),"mime_type":"image/png","width":64,"height":64,"kind":"app_icon"}))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_app_icon_is_owned_png_with_actual_fixed_dimensions() {
        let root = tempfile::tempdir().unwrap();
        let source = image::RgbaImage::from_pixel(32, 16, image::Rgba([24, 80, 210, 255]));
        let value = write_png(root.path(), source).unwrap();
        assert_eq!(value["kind"], "app_icon");
        assert_eq!(value["mime_type"], "image/png");
        assert_eq!(value["width"], 64);
        assert_eq!(value["height"], 64);
        let path = url::Url::parse(value["url"].as_str().unwrap())
            .unwrap()
            .to_file_path()
            .unwrap();
        assert!(path.starts_with(root.path()));
        assert_eq!(image::image_dimensions(&path).unwrap(), (64, 64));
    }
    #[test]
    fn native_app_icon_rejects_empty_or_excessive_native_raster() {
        let root = tempfile::tempdir().unwrap();
        assert!(write_png(root.path(), image::RgbaImage::new(0, 0)).is_err());
        assert!(write_png(root.path(), image::RgbaImage::new(1025, 1)).is_err());
    }
}
