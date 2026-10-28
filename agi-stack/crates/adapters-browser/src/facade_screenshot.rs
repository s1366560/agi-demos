//! Annotated viewport capture; annotations never modify the page DOM.
use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, tool_err};
use agistack_core::ports::CoreResult;
use base64::{Engine as _, engine::general_purpose::STANDARD};
use image::{ImageFormat, Rgba};
use serde_json::{Value, json};

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn element_screenshot(
        &self,
        backend: Backend,
        tab: u64,
        args: &[Value],
        input: &Value,
    ) -> CoreResult<Value> {
        let options = args
            .first()
            .ok_or_else(|| tool_err("element screenshot requires a point"))?;
        let coordinate = |key: &str| {
            options[key]
                .as_f64()
                .filter(|value| value.is_finite() && *value >= 0.0)
                .ok_or_else(|| tool_err("element screenshot point must be finite and nonnegative"))
        };
        let (x, y) = (coordinate("x")?, coordinate("y")?);
        let elements = self
            .facade_evaluate(
                backend,
                tab,
                crate::facade::dom_expression("playwright.elementInfo", &json!(args))?,
            )
            .await?;
        let screenshot = self.screenshot(input).await?;
        let bytes = STANDARD
            .decode(
                screenshot["dataBase64"]
                    .as_str()
                    .ok_or_else(|| tool_err("screenshot missing"))?,
            )
            .map_err(|_| tool_err("screenshot encoding invalid"))?;
        if bytes.len() > 16 * 1024 * 1024 {
            return Err(tool_err("screenshot too large"));
        }
        let mut reader = image::ImageReader::new(std::io::Cursor::new(bytes))
            .with_guessed_format()
            .map_err(|_| tool_err("screenshot format invalid"))?;
        let mut limits = image::Limits::default();
        limits.max_image_width = Some(8192);
        limits.max_image_height = Some(8192);
        limits.max_alloc = Some(128 * 1024 * 1024);
        reader.limits(limits);
        let mut pixels = reader
            .decode()
            .map_err(|_| tool_err("screenshot decoding failed"))?
            .into_rgba8();
        let width = screenshot["width"]
            .as_f64()
            .filter(|v| *v > 0.0)
            .ok_or_else(|| tool_err("viewport width invalid"))?;
        let height = screenshot["height"]
            .as_f64()
            .filter(|v| *v > 0.0)
            .ok_or_else(|| tool_err("viewport height invalid"))?;
        if x >= width || y >= height {
            return Err(tool_err("element screenshot point outside viewport"));
        }
        let (sx, sy) = (
            pixels.width() as f64 / width,
            pixels.height() as f64 / height,
        );
        let (pw, ph) = (pixels.width() as i32, pixels.height() as i32);
        let mut put = |px: i32, py: i32, color: Rgba<u8>| {
            if px >= 0 && py >= 0 && px < pw && py < ph {
                pixels.put_pixel(px as u32, py as u32, color);
            }
        };
        for element in elements.as_array().into_iter().flatten() {
            let rect = &element["boundingBox"];
            let (left, top) = (
                (rect["x"].as_f64().unwrap_or(0.0) * sx).round() as i32,
                (rect["y"].as_f64().unwrap_or(0.0) * sy).round() as i32,
            );
            let right = (left + (rect["width"].as_f64().unwrap_or(0.0) * sx).round() as i32)
                .clamp(0, pw - 1);
            let bottom = (top + (rect["height"].as_f64().unwrap_or(0.0) * sy).round() as i32)
                .clamp(0, ph - 1);
            let (left, top) = (left.clamp(0, pw - 1), top.clamp(0, ph - 1));
            for offset in 0..2 {
                for px in left..=right {
                    put(px, top + offset, Rgba([0, 110, 255, 255]));
                    put(px, bottom - offset, Rgba([0, 110, 255, 255]));
                }
                for py in top..=bottom {
                    put(left + offset, py, Rgba([0, 110, 255, 255]));
                    put(right - offset, py, Rgba([0, 110, 255, 255]));
                }
            }
        }
        let (x, y) = ((x * sx).round() as i32, (y * sy).round() as i32);
        for delta in -7..=7 {
            put(x + delta, y, Rgba([255, 40, 40, 255]));
            put(x, y + delta, Rgba([255, 40, 40, 255]));
        }
        let mut bytes = std::io::Cursor::new(Vec::new());
        image::DynamicImage::ImageRgba8(pixels)
            .write_to(&mut bytes, ImageFormat::Png)
            .map_err(|_| tool_err("annotated screenshot encoding failed"))?;
        Ok(
            json!({"mimeType":"image/png","dataBase64":STANDARD.encode(bytes.into_inner()),"width":pw,"height":ph}),
        )
    }
}
