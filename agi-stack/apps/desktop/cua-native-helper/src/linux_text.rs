//! AT-SPI text ranges use Unicode scalar offsets and require an exact unambiguous match.
use crate::backend::{required, NativeError, Result};
use atspi::proxy::{accessible::ObjectRefExt, proxy_ext::ProxyExt};
use serde_json::Value;
fn range(content: &str, text: &str, prefix: &str, suffix: &str) -> Result<(i32, i32)> {
    let needle = format!("{prefix}{text}{suffix}");
    let mut matches = content.match_indices(&needle);
    let (offset, _) = matches
        .next()
        .ok_or_else(|| NativeError::new("text_not_found", "exact text was not found"))?;
    if matches.next().is_some() {
        return Err(NativeError::new(
            "ambiguous_text",
            "provide prefix/suffix for repeated text",
        ));
    }
    let start = content[..offset].chars().count() + prefix.chars().count();
    let end = start + text.chars().count();
    Ok((
        i32::try_from(start)
            .map_err(|_| NativeError::new("text_too_large", "text range exceeds native limit"))?,
        i32::try_from(end)
            .map_err(|_| NativeError::new("text_too_large", "text range exceeds native limit"))?,
    ))
}
pub async fn select(reference: &str, request: &Value) -> Result<()> {
    let split = reference
        .find(":/")
        .ok_or_else(|| NativeError::new("stale_element", "invalid native object reference"))?;
    let name = zbus::names::UniqueName::try_from(reference[..split].to_owned())
        .map_err(|_| NativeError::new("stale_element", "invalid native object owner"))?;
    let path = zbus::zvariant::ObjectPath::try_from(reference[split + 1..].to_owned())
        .map_err(|_| NativeError::new("stale_element", "invalid native object path"))?;
    let connection = sky_cua_linux::atspi::connect().await.map_err(|_| {
        NativeError::new("accessibility_unavailable", "AT-SPI connection unavailable")
    })?;
    let object = atspi::ObjectRef::new_owned(name, path);
    let accessible = object
        .as_accessible_proxy(connection.connection())
        .await
        .map_err(|_| NativeError::new("stale_element", "native text element disappeared"))?;
    let proxies = accessible.proxies().await.map_err(|_| {
        NativeError::new(
            "accessibility_unavailable",
            "native text interfaces unavailable",
        )
    })?;
    let proxy = proxies
        .text()
        .await
        .map_err(|_| NativeError::unsupported("AT-SPI Text interface"))?;
    let count = proxy
        .character_count()
        .await
        .map_err(|_| NativeError::new("text_unavailable", "cannot determine native text length"))?;
    if !(0..=1048576).contains(&count) {
        return Err(NativeError::new(
            "text_too_large",
            "native text exceeds the selection budget",
        ));
    }
    let content = proxy
        .get_text(0, count)
        .await
        .map_err(|_| NativeError::new("text_unavailable", "cannot read native text"))?;
    let (start, end) = range(
        &content,
        required(request, "text")?,
        request["prefix"].as_str().unwrap_or(""),
        request["suffix"].as_str().unwrap_or(""),
    )?;
    let selected = match request["cursor"].as_str().unwrap_or("select") {
        "before" => proxy.set_caret_offset(start).await,
        "after" => proxy.set_caret_offset(end).await,
        "select" => proxy.add_selection(start, end).await,
        _ => return Err(NativeError::new("invalid_params", "invalid text cursor")),
    }
    .map_err(|_| NativeError::new("text_selection_failed", "native text selection rejected"))?;
    if !selected {
        return Err(NativeError::new(
            "text_selection_failed",
            "native text provider did not select the range",
        ));
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    #[test]
    fn native_ranges_count_unicode_scalars() {
        assert_eq!(
            super::range("a中🙂text!", "text", "🙂", "!").unwrap(),
            (3, 7)
        );
        assert!(super::range("text text", "text", "", "").is_err());
        assert!(super::range("ABC", "abc", "", "").is_err());
    }
}
