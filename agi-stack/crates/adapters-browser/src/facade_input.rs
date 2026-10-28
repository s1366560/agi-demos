use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, tool_err};
use agistack_core::ports::CoreResult;
use serde_json::{Value, json};
use std::sync::Arc;

/// Cancellation may drop an input future between down and up. Release through
/// the same backend even after the originating request has been cancelled.
struct InputRelease<E: BridgeEndpoint> {
    endpoint: Arc<E>,
    backend: Backend,
    tab: u64,
    method: &'static str,
    params: Option<Value>,
    session: Option<String>,
    registration: Option<crate::input_visibility::ReleaseRegistration>,
}
impl<E: BridgeEndpoint> InputRelease<E> {
    fn new(
        host: &BrowserToolHost<E>,
        backend: Backend,
        tab: u64,
        method: &'static str,
        params: Value,
    ) -> Self {
        let registration = host.register_input_release(backend, tab,
            json!({"tabId":tab,"method":method,"params":params}));
        Self {
            registration,
            endpoint: host.endpoint.clone(),
            backend,
            tab,
            method,
            params: Some(params),
            session: None,
        }
    }
    fn disarm(&mut self) {
        self.params = None;
        if let Some(registration) = &self.registration { registration.disarm(); }
    }
    fn set_session(&mut self, session: Option<&str>) {
        self.session = session.map(str::to_owned);
        if let (Some(registration), Some(session)) = (&self.registration, session) {
            registration.set_session(session);
        }
    }
}
impl<E: BridgeEndpoint> Drop for InputRelease<E> {
    fn drop(&mut self) {
        if self.registration.is_some() { return; }
        let Some(params) = self.params.take() else {
            return;
        };
        let Ok(runtime) = tokio::runtime::Handle::try_current() else {
            return;
        };
        let endpoint = self.endpoint.clone();
        let backend = self.backend;
        let mut args = json!({"tabId":self.tab,"method":self.method,"params":params});
        if let Some(session) = &self.session {
            args["sessionId"] = json!(session);
        }
        runtime.spawn(async move {
            let _ = endpoint.request_on(&backend.wire_name(), "executeCdp", args).await;
        });
    }
}

fn modifiers(keys: impl IntoIterator<Item = impl AsRef<str>>) -> CoreResult<u64> {
    keys.into_iter()
        .try_fold(0, |mask, key| match key.as_ref().to_lowercase().as_str() {
            "alt" | "option" => Ok(mask | 1),
            "ctrl" | "control" => Ok(mask | 2),
            "meta" | "super" | "cmd" | "command" => Ok(mask | 4),
            "shift" => Ok(mask | 8),
            _ => Err(tool_err("invalid key modifier")),
        })
}

fn finite(value: &Value, field: &str) -> CoreResult<f64> {
    value
        .get(field)
        .and_then(Value::as_f64)
        .filter(|number| number.is_finite())
        .ok_or_else(|| tool_err(format!("input requires finite {field}")))
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn facade_mouse_click(
        &self,
        backend: Backend,
        tab: u64,
        session: Option<&str>,
        point: &Value,
        options: &Value,
        double: bool,
    ) -> CoreResult<Value> {
        let (x, y) = (finite(point, "x")?, finite(point, "y")?);
        let button = options
            .get("button")
            .and_then(Value::as_str)
            .unwrap_or("left");
        if !matches!(button, "left" | "right" | "middle") {
            return Err(tool_err("invalid mouse button"));
        }
        let modifiers = modifiers(
            options
                .get("modifiers")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .map(|value| value.as_str().unwrap_or("invalid")),
        )?;
        self.execute_cdp_session(
            backend,
            tab,
            session,
            "Input.dispatchMouseEvent",
            json!({"type":"mouseMoved","x":x,"y":y,"modifiers":modifiers}),
        )
        .await?;
        for count in 1..=if double { 2 } else { 1 } {
            let release = json!({"type":"mouseReleased","x":x,"y":y,"button":button,"clickCount":count,"modifiers":modifiers});
            let mut guard = InputRelease::new(
                self,
                backend,
                tab,
                "Input.dispatchMouseEvent",
                release.clone(),
            );
            guard.set_session(session);
            self.execute_cdp_session(backend,tab,session,"Input.dispatchMouseEvent",json!({"type":"mousePressed","x":x,"y":y,"button":button,"clickCount":count,"modifiers":modifiers})).await?;
            self.execute_cdp_session(backend, tab, session, "Input.dispatchMouseEvent", release)
                .await?;
            guard.disarm();
        }
        Ok(Value::Null)
    }

    pub(crate) async fn facade_type_characters(
        &self,
        backend: Backend,
        tab: u64,
        text: &str,
    ) -> CoreResult<Value> {
        self.with_input_visibility(backend, tab, self.facade_type_characters_prepared(backend, tab, text)).await
    }

    async fn facade_type_characters_prepared(
        &self, backend: Backend, tab: u64, text: &str,
    ) -> CoreResult<Value> {
        for character in text.chars() {
            let text = character.to_string();
            let key = match character {
                '\n' | '\r' => "Enter",
                '\t' => "Tab",
                _ => &text,
            };
            let release = json!({"type":"keyUp","key":key});
            let mut guard = InputRelease::new(
                self,
                backend,
                tab,
                "Input.dispatchKeyEvent",
                release.clone(),
            );
            self.execute_cdp(backend,tab,"Input.dispatchKeyEvent",json!({"type":"keyDown","key":key,"text":if key=="Enter" {"\r"} else if key=="Tab" {""} else {&text}})).await?;
            self.execute_cdp(backend, tab, "Input.dispatchKeyEvent", release)
                .await?;
            guard.disarm();
        }
        Ok(Value::Null)
    }

    pub(crate) async fn facade_input(
        &self,
        backend: Backend,
        tab: u64,
        operation: &str,
        args: &[Value],
    ) -> CoreResult<Value> {
        self.with_input_visibility(backend, tab, self.facade_input_prepared(backend, tab, operation, args)).await
    }

    async fn facade_input_prepared(
        &self, backend: Backend, tab: u64, operation: &str, args: &[Value],
    ) -> CoreResult<Value> {
        let first = args.first().cloned().unwrap_or(Value::Null);
        match operation {
            "ax.click" | "cua.click" | "cua.double_click" | "cua.move" => {
                let (x, y) = self.facade_point(backend, tab, &first).await?;
                if operation == "cua.move" {
                    return self
                        .execute_cdp(
                            backend,
                            tab,
                            "Input.dispatchMouseEvent",
                            json!({"type":"mouseMoved","x":x,"y":y}),
                        )
                        .await;
                }
                let options = if first.is_number() {
                    args.get(1).unwrap_or(&Value::Null)
                } else {
                    &first
                };
                let button = options
                    .get("mouseButton")
                    .and_then(Value::as_str)
                    .unwrap_or(match options.get("button").and_then(Value::as_u64) {
                        Some(2) => "middle",
                        Some(3) => "right",
                        _ => "left",
                    });
                if !["left", "right", "middle", "back", "forward"].contains(&button) {
                    return Err(tool_err("invalid mouse button"));
                }
                let count = if operation == "cua.double_click" {
                    2
                } else {
                    options
                        .get("clickCount")
                        .and_then(Value::as_u64)
                        .unwrap_or(1)
                };
                if !(1..=3).contains(&count) {
                    return Err(tool_err("click count must be from 1 to 3"));
                }
                let milliseconds = options
                    .get("duration_ms")
                    .and_then(Value::as_u64)
                    .unwrap_or_else(|| {
                        (options
                            .get("duration")
                            .and_then(Value::as_f64)
                            .unwrap_or(0.0)
                            * 1000.0) as u64
                    });
                if milliseconds > 30_000 {
                    return Err(tool_err("click duration exceeds 30000 milliseconds"));
                }
                let modifiers = modifiers(
                    options
                        .get("key")
                        .and_then(Value::as_str)
                        .into_iter()
                        .flat_map(|key| key.split('+')),
                )?;
                for ordinal in 1..=count {
                    let release = json!({"type":"mouseReleased","x":x,"y":y,"button":button,"clickCount":ordinal,"modifiers":modifiers});
                    let mut guard = InputRelease::new(
                        self,
                        backend,
                        tab,
                        "Input.dispatchMouseEvent",
                        release.clone(),
                    );
                    self.execute_cdp(backend, tab, "Input.dispatchMouseEvent", json!({"type":"mousePressed","x":x,"y":y,"button":button,"clickCount":ordinal,"modifiers":modifiers})).await?;
                    if milliseconds > 0 {
                        tokio::time::sleep(std::time::Duration::from_millis(milliseconds)).await;
                    }
                    self.execute_cdp(backend, tab, "Input.dispatchMouseEvent", release)
                        .await?;
                    guard.disarm();
                }
                Ok(Value::Null)
            }
            "ax.drag" | "cua.drag" => {
                let path = if operation == "ax.drag" {
                    args.to_vec()
                } else {
                    first["path"]
                        .as_array()
                        .cloned()
                        .ok_or_else(|| tool_err("drag requires path"))?
                };
                if path.len() < 2 || path.len() > 1000 {
                    return Err(tool_err("drag requires between 2 and 1000 points"));
                }
                let points = path
                    .iter()
                    .map(|value| Ok((finite(value, "x")?, finite(value, "y")?)))
                    .collect::<CoreResult<Vec<_>>>()?;
                let (x, y) = points[0];
                let mut guard = InputRelease::new(
                    self,
                    backend,
                    tab,
                    "Input.dispatchMouseEvent",
                    json!({"type":"mouseReleased","x":x,"y":y,"button":"left","clickCount":1}),
                );
                self.execute_cdp(
                    backend,
                    tab,
                    "Input.dispatchMouseEvent",
                    json!({"type":"mousePressed","x":x,"y":y,"button":"left","clickCount":1}),
                )
                .await?;
                for &(x, y) in &points[1..] {
                    self.execute_cdp(
                        backend,
                        tab,
                        "Input.dispatchMouseEvent",
                        json!({"type":"mouseMoved","x":x,"y":y,"button":"left","buttons":1}),
                    )
                    .await?;
                }
                let (x, y) = points[points.len() - 1];
                let result = self
                    .execute_cdp(
                        backend,
                        tab,
                        "Input.dispatchMouseEvent",
                        json!({"type":"mouseReleased","x":x,"y":y,"button":"left","clickCount":1}),
                    )
                    .await?;
                guard.disarm();
                Ok(result)
            }
            "ax.scroll" | "cua.scroll" => {
                let (x, y) = self.facade_point(backend, tab, &first).await?;
                let (dx, dy) = if operation == "cua.scroll" {
                    (finite(&first, "scrollX")?, finite(&first, "scrollY")?)
                } else {
                    let direction = first
                        .get("direction")
                        .or_else(|| args.get(1))
                        .and_then(Value::as_str)
                        .unwrap_or("down");
                    let pages = first
                        .get("pages")
                        .or_else(|| args.get(2))
                        .and_then(Value::as_f64)
                        .unwrap_or(1.0);
                    if !pages.is_finite() || pages <= 0.0 {
                        return Err(tool_err("pages must be positive"));
                    }
                    match direction {
                        "up" => (0.0, -600.0 * pages),
                        "down" => (0.0, 600.0 * pages),
                        "left" => (-600.0 * pages, 0.0),
                        "right" => (600.0 * pages, 0.0),
                        _ => return Err(tool_err("invalid scroll direction")),
                    }
                };
                self.execute_cdp(
                    backend,
                    tab,
                    "Input.dispatchMouseEvent",
                    json!({"type":"mouseWheel","x":x,"y":y,"deltaX":dx,"deltaY":dy}),
                )
                .await
            }
            "cua.type" | "ax.typeText" | "ax.paste" => {
                let text = if operation == "cua.type" {
                    first.get("text")
                } else {
                    self.facade_focus(backend, tab, &first).await?;
                    args.get(1)
                }
                .and_then(Value::as_str)
                .ok_or_else(|| tool_err("type requires text"))?;
                self.execute_cdp(backend, tab, "Input.insertText", json!({"text":text}))
                    .await
            }
            "ax.pressKey" | "cua.keypress" => {
                let chord = if operation == "ax.pressKey" {
                    self.facade_focus(backend, tab, &first).await?;
                    args.get(1).and_then(Value::as_str).map(str::to_owned)
                } else {
                    first.get("keys").and_then(Value::as_array).map(|keys| {
                        keys.iter()
                            .filter_map(Value::as_str)
                            .collect::<Vec<_>>()
                            .join("+")
                    })
                }
                .ok_or_else(|| tool_err("key press requires a chord"))?;
                let mut parts = chord.split('+').collect::<Vec<_>>();
                let key = parts
                    .pop()
                    .filter(|key| !key.is_empty())
                    .ok_or_else(|| tool_err("empty key chord"))?;
                let modifiers = modifiers(parts)?;
                let (key, code, virtual_code) = match key {
                    "Return" | "Enter" => ("Enter", "Enter", 13),
                    "Tab" => ("Tab", "Tab", 9),
                    "Escape" | "Esc" => ("Escape", "Escape", 27),
                    "Backspace" => ("Backspace", "Backspace", 8),
                    "Delete" => ("Delete", "Delete", 46),
                    "Up" | "ArrowUp" => ("ArrowUp", "ArrowUp", 38),
                    "Down" | "ArrowDown" => ("ArrowDown", "ArrowDown", 40),
                    "Left" | "ArrowLeft" => ("ArrowLeft", "ArrowLeft", 37),
                    "Right" | "ArrowRight" => ("ArrowRight", "ArrowRight", 39),
                    other => (other, "", 0),
                };
                let virtual_code = if key.len() == 1 && key.is_ascii() {
                    key.as_bytes()[0].to_ascii_uppercase() as u32
                } else {
                    virtual_code
                };
                let code = if key.len() == 1 && key.as_bytes()[0].is_ascii_alphabetic() {
                    format!("Key{}", key.to_ascii_uppercase())
                } else {
                    code.to_string()
                };
                let release = json!({"type":"keyUp","key":key,"code":code,"windowsVirtualKeyCode":virtual_code,"modifiers":modifiers});
                let mut guard = InputRelease::new(
                    self,
                    backend,
                    tab,
                    "Input.dispatchKeyEvent",
                    release.clone(),
                );
                self.execute_cdp(backend, tab, "Input.dispatchKeyEvent", json!({"type":"keyDown","key":key,"code":code,"windowsVirtualKeyCode":virtual_code,"modifiers":modifiers,"text":if modifiers & 7 == 0 && key.chars().count()==1 {key}else{""}})).await?;
                let milliseconds = args
                    .get(2)
                    .and_then(|options| options.get("duration_ms"))
                    .and_then(Value::as_u64)
                    .unwrap_or(0)
                    .min(30000);
                if milliseconds > 0 {
                    tokio::time::sleep(std::time::Duration::from_millis(milliseconds)).await;
                }
                let result = self
                    .execute_cdp(backend, tab, "Input.dispatchKeyEvent", release)
                    .await?;
                guard.disarm();
                Ok(result)
            }
            _ => Err(tool_err("unsupported browser input operation")),
        }
    }

    async fn facade_focus(&self, backend: Backend, tab: u64, value: &Value) -> CoreResult<()> {
        if value.is_null() {
            return Ok(());
        }
        let index = value
            .as_u64()
            .ok_or_else(|| tool_err("focus requires an element index or null"))?;
        self.facade_evaluate(backend, tab, format!("(() => {{ const e=globalThis.__memstackFacadeRefs?.[{index}]; if(!e || !e.isConnected) throw Error('stale accessibility index'); e.focus(); if(document.activeElement!==e && !e.shadowRoot?.activeElement) throw Error('element cannot receive focus'); }})()")).await?;
        Ok(())
    }

    async fn facade_point(
        &self,
        backend: Backend,
        tab: u64,
        value: &Value,
    ) -> CoreResult<(f64, f64)> {
        if value.get("x").is_some() {
            return Ok((finite(value, "x")?, finite(value, "y")?));
        }
        let index = value
            .as_u64()
            .or_else(|| value.get("element_index").and_then(Value::as_u64))
            .ok_or_else(|| tool_err("input requires an element index or point"))?;
        let point = self.facade_evaluate(backend, tab, format!("(() => {{ const e=globalThis.__memstackFacadeRefs?.[{index}]; if(!e || !e.isConnected) throw Error('stale accessibility index'); e.scrollIntoView({{block:'center',inline:'center'}}); const r=e.getBoundingClientRect(); if(!r.width||!r.height) throw Error('element is not visible'); return {{x:r.x+r.width/2,y:r.y+r.height/2}}; }})()")).await?;
        Ok((finite(&point, "x")?, finite(&point, "y")?))
    }
}
