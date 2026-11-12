//! Native UIA control-view snapshots and exact, explicitly selected pattern operations.
use crate::backend::{required, NativeError, Observation, Result};
use serde_json::{json, Value};
use windows::{
    core::BSTR,
    Win32::{
        Foundation::HWND,
        System::{
            Com::{CoCreateInstance, CLSCTX_INPROC_SERVER},
            Ole::*,
        },
        UI::Accessibility::*,
    },
};

fn error() -> NativeError {
    NativeError::new(
        "uia_unavailable",
        "native UI Automation provider rejected the operation",
    )
}
fn automation() -> Result<IUIAutomation> {
    unsafe { CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER) }.map_err(|_| error())
}
pub fn available() -> bool {
    automation().is_ok()
}
fn hwnd(id: &str) -> Result<HWND> {
    let address = id
        .strip_prefix("hwnd:0x")
        .and_then(|value| usize::from_str_radix(value, 16).ok())
        .ok_or_else(|| NativeError::new("invalid_params", "exact HWND is required"))?;
    Ok(HWND(address as *mut std::ffi::c_void))
}
fn runtime(element: &IUIAutomationElement) -> Result<Vec<i32>> {
    // SAFETY: RuntimeId is an owned one-dimensional SAFEARRAY of native i32 values.
    unsafe {
        let array = element.GetRuntimeId().map_err(|_| error())?;
        if array.is_null() {
            return Err(NativeError::new(
                "stale_element",
                "UIA RuntimeId is unavailable",
            ));
        }
        let result = (|| {
            if SafeArrayGetDim(array) != 1 || SafeArrayGetElemsize(array) != 4 {
                return Err(error());
            }
            let start = SafeArrayGetLBound(array, 1).map_err(|_| error())?;
            let end = SafeArrayGetUBound(array, 1).map_err(|_| error())?;
            let count = end
                .checked_sub(start)
                .and_then(|n| n.checked_add(1))
                .filter(|n| (1..=128).contains(n))
                .ok_or_else(error)?;
            let mut data = std::ptr::null_mut();
            SafeArrayAccessData(array, &mut data).map_err(|_| error())?;
            let ids = std::slice::from_raw_parts(data as *const i32, count as usize).to_vec();
            let _ = SafeArrayUnaccessData(array);
            Ok(ids)
        })();
        let _ = SafeArrayDestroy(array);
        result
    }
}
fn describe(element: &IUIAutomationElement, index: usize, path: &[usize]) -> Result<Value> {
    unsafe {
        let bounds = element.CurrentBoundingRectangle().map_err(|_| error())?;
        let password = element
            .CurrentIsPassword()
            .map(|value| value.as_bool())
            .unwrap_or(true);
        let mut actions = Vec::new();
        if element
            .GetCurrentPatternAs::<IUIAutomationInvokePattern>(UIA_InvokePatternId)
            .is_ok()
        {
            actions.push("invoke");
        }
        if element
            .GetCurrentPatternAs::<IUIAutomationSelectionItemPattern>(UIA_SelectionItemPatternId)
            .is_ok()
        {
            actions.push("select");
        }
        if element
            .GetCurrentPatternAs::<IUIAutomationExpandCollapsePattern>(UIA_ExpandCollapsePatternId)
            .is_ok()
        {
            actions.extend(["expand", "collapse"]);
        }
        if element
            .GetCurrentPatternAs::<IUIAutomationTogglePattern>(UIA_TogglePatternId)
            .is_ok()
        {
            actions.push("toggle");
        }
        let value = element
            .GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId)
            .ok();
        if value.is_some() {
            actions.push("set_value");
        }
        if element
            .GetCurrentPatternAs::<IUIAutomationTextPattern>(UIA_TextPatternId)
            .is_ok()
        {
            actions.push("select_text");
        }
        if element
            .CurrentIsKeyboardFocusable()
            .map(|v| v.as_bool())
            .unwrap_or(false)
        {
            actions.push("focus");
        }
        Ok(
            json!({"element_index":index,"path":path,"runtime_id":runtime(element)?,"name":element.CurrentName().ok().map(|v|v.to_string()),
            "role":element.CurrentLocalizedControlType().ok().map(|v|v.to_string()),"control_type":element.CurrentControlType().ok().map(|v|v.0),
            "actions":actions,"password":password,"value":if password{None}else{value.and_then(|p|p.CurrentValue().ok()).map(|v|v.to_string().chars().take(16384).collect::<String>())},
            "bounds":{"x":bounds.left,"y":bounds.top,"width":bounds.right-bounds.left,"height":bounds.bottom-bounds.top}}),
        )
    }
}
pub fn snapshot(id: &str) -> Result<Value> {
    let automation = automation()?;
    let root = unsafe { automation.ElementFromHandle(hwnd(id)?) }.map_err(|_| error())?;
    let walker = unsafe { automation.ControlViewWalker() }.map_err(|_| error())?;
    let mut queue = std::collections::VecDeque::from([(root, Vec::new())]);
    let mut elements = Vec::new();
    while let Some((element, path)) = queue.pop_front() {
        if elements.len() >= 4096 {
            break;
        }
        elements.push(describe(&element, elements.len(), &path)?);
        if path.len() >= 64 {
            continue;
        }
        if let Ok(mut child) = unsafe { walker.GetFirstChildElement(&element) } {
            for ordinal in 0..4096 {
                if queue.len() + elements.len() >= 4096 {
                    break;
                }
                let mut child_path = path.clone();
                child_path.push(ordinal);
                queue.push_back((child.clone(), child_path));
                match unsafe { walker.GetNextSiblingElement(&child) } {
                    Ok(next) => child = next,
                    Err(_) => break,
                }
            }
        }
    }
    Ok(json!({"elements":elements,"window_id":id,"truncated":elements.len()>=4096}))
}
pub fn resolve(observation: &Observation, index: u64) -> Result<IUIAutomationElement> {
    let expected = observation.native["elements"]
        .as_array()
        .and_then(|items| {
            items
                .iter()
                .find(|item| item["element_index"].as_u64() == Some(index))
        })
        .ok_or_else(|| NativeError::new("stale_element", "element is absent from this snapshot"))?;
    let automation = automation()?;
    let mut element = unsafe { automation.ElementFromHandle(hwnd(&observation.window.window_id)?) }
        .map_err(|_| error())?;
    let walker = unsafe { automation.ControlViewWalker() }.map_err(|_| error())?;
    for ordinal in expected["path"].as_array().ok_or_else(error)? {
        let ordinal = ordinal.as_u64().filter(|n| *n < 4096).ok_or_else(error)?;
        let mut child = unsafe { walker.GetFirstChildElement(&element) }.map_err(|_| error())?;
        for _ in 0..ordinal {
            child = unsafe { walker.GetNextSiblingElement(&child) }.map_err(|_| error())?;
        }
        element = child;
    }
    if json!(runtime(&element)?) != expected["runtime_id"] {
        return Err(NativeError::new(
            "stale_element",
            "the native UIA element changed since observation",
        ));
    }
    Ok(element)
}
pub fn action(observation: &Observation, request: &Value) -> Result<()> {
    let index = request["element_index"]
        .as_u64()
        .ok_or_else(|| NativeError::new("invalid_params", "observed element_index is required"))?;
    let element = resolve(observation, index)?;
    let kind = required(request, "kind")?;
    let selected = if kind == "secondary_action" {
        required(request, "action")?
    } else {
        kind
    };
    // No inferred default action or physical fallback: the agent selected an exact exposed pattern.
    unsafe {
        let result = match selected {
            "set_value" => {
                let pattern = element
                    .GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId)
                    .map_err(|_| error())?;
                if pattern.CurrentIsReadOnly().map_err(|_| error())?.as_bool() {
                    return Err(NativeError::new(
                        "element_read_only",
                        "UIA element is read only",
                    ));
                }
                pattern.SetValue(&BSTR::from(required(request, "value")?))
            }
            "invoke" => element
                .GetCurrentPatternAs::<IUIAutomationInvokePattern>(UIA_InvokePatternId)
                .map_err(|_| error())?
                .Invoke(),
            "select" => element
                .GetCurrentPatternAs::<IUIAutomationSelectionItemPattern>(
                    UIA_SelectionItemPatternId,
                )
                .map_err(|_| error())?
                .Select(),
            "expand" => element
                .GetCurrentPatternAs::<IUIAutomationExpandCollapsePattern>(
                    UIA_ExpandCollapsePatternId,
                )
                .map_err(|_| error())?
                .Expand(),
            "collapse" => element
                .GetCurrentPatternAs::<IUIAutomationExpandCollapsePattern>(
                    UIA_ExpandCollapsePatternId,
                )
                .map_err(|_| error())?
                .Collapse(),
            "toggle" => element
                .GetCurrentPatternAs::<IUIAutomationTogglePattern>(UIA_TogglePatternId)
                .map_err(|_| error())?
                .Toggle(),
            "focus" => element.SetFocus(),
            "select_text" => {
                return select_text(&element, request);
            }
            _ => {
                return Err(NativeError::new(
                    "invalid_params",
                    "select an exact exposed native UIA action",
                ));
            }
        };
        result.map_err(|_| error())
    }
}
fn select_text(element: &IUIAutomationElement, request: &Value) -> Result<()> {
    unsafe {
        let text = required(request, "text")?;
        let pattern = element
            .GetCurrentPatternAs::<IUIAutomationTextPattern>(UIA_TextPatternId)
            .map_err(|_| error())?;
        let document = pattern.DocumentRange().map_err(|_| error())?;
        let needle = format!(
            "{}{}{}",
            request["prefix"].as_str().unwrap_or(""),
            text,
            request["suffix"].as_str().unwrap_or("")
        );
        let range = document
            .FindText(&BSTR::from(needle.as_str()), false, false)
            .map_err(|_| NativeError::new("text_not_found", "exact text was not found"))?;
        if range.GetText(-1).map_err(|_| error())?.to_string() != needle {
            return Err(NativeError::new(
                "text_not_found",
                "UIA returned a different text match",
            ));
        }
        // Reject repeated matches so the agent must provide an exact disambiguating context.
        let remaining = range.Clone().map_err(|_| error())?;
        remaining
            .MoveEndpointByRange(
                TextPatternRangeEndpoint_Start,
                &range,
                TextPatternRangeEndpoint_End,
            )
            .map_err(|_| error())?;
        remaining
            .MoveEndpointByRange(
                TextPatternRangeEndpoint_End,
                &document,
                TextPatternRangeEndpoint_End,
            )
            .map_err(|_| error())?;
        if remaining
            .FindText(&BSTR::from(needle.as_str()), false, false)
            .is_ok()
        {
            return Err(NativeError::new(
                "ambiguous_text",
                "provide exact prefix/suffix for repeated text",
            ));
        }
        let prefix = request["prefix"]
            .as_str()
            .unwrap_or("")
            .encode_utf16()
            .count();
        let suffix = request["suffix"]
            .as_str()
            .unwrap_or("")
            .encode_utf16()
            .count();
        range
            .MoveEndpointByUnit(
                TextPatternRangeEndpoint_Start,
                TextUnit_Character,
                prefix as i32,
            )
            .map_err(|_| error())?;
        range
            .MoveEndpointByUnit(
                TextPatternRangeEndpoint_End,
                TextUnit_Character,
                -(suffix as i32),
            )
            .map_err(|_| error())?;
        match request["cursor"].as_str().unwrap_or("select") {
            "before" => range
                .MoveEndpointByRange(
                    TextPatternRangeEndpoint_End,
                    &range,
                    TextPatternRangeEndpoint_Start,
                )
                .map_err(|_| error())?,
            "after" => range
                .MoveEndpointByRange(
                    TextPatternRangeEndpoint_Start,
                    &range,
                    TextPatternRangeEndpoint_End,
                )
                .map_err(|_| error())?,
            "select" => {}
            _ => return Err(NativeError::new("invalid_params", "invalid text cursor")),
        }
        range.Select().map_err(|_| error())
    }
}

/// Only provider-declared WindowPattern and UIA control type; no class/title inference.
pub fn window_metadata(id: &str) -> (Option<bool>, Option<String>) {
    let Ok(window) = hwnd(id) else {
        return (None, None);
    };
    let Ok(automation) = automation() else {
        return (None, None);
    };
    unsafe {
        let Ok(element) = automation.ElementFromHandle(window) else {
            return (None, None);
        };
        let modal = element
            .GetCurrentPatternAs::<IUIAutomationWindowPattern>(UIA_WindowPatternId)
            .ok()
            .and_then(|pattern| pattern.CurrentIsModal().ok())
            .map(|value| value.as_bool());
        let kind = element
            .CurrentControlType()
            .ok()
            .map(|kind| format!("uia:{}", kind.0));
        (modal, kind)
    }
}
