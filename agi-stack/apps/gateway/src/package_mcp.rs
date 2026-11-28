//! Compose the project's signed tools at the trusted gateway, before the sandbox boundary.
use std::collections::{HashMap, HashSet};
use std::time::Duration;

use axum::http::{header, HeaderMap, HeaderValue};
use futures_util::{
    future::{AbortHandle, Abortable},
    StreamExt,
};
use reqwest::{Client, Response, Url};
use serde_json::{json, Value};
use tokio::task::JoinSet;

#[derive(Clone)]
pub(super) struct Authority {
    endpoint: Url,
    bearer: HeaderValue,
    client: Client,
}

impl Authority {
    pub(super) fn for_project(
        project: &str,
        headers: &HeaderMap,
        python: &str,
        client: Client,
    ) -> Option<Self> {
        // A sandbox cookie, a project id, and a sandbox service token are never cloud authority.
        let bearer = if let Some(header) = headers.get(header::AUTHORIZATION) {
            header.clone()
        } else {
            let protocol = headers.get(header::SEC_WEBSOCKET_PROTOCOL)?.to_str().ok()?;
            let mut fields = protocol.split(',').map(str::trim);
            fields.find(|field| *field == "memstack.auth")?;
            let token = fields.next()?;
            HeaderValue::from_str(&format!("Bearer {token}")).ok()?
        };
        let mut endpoint = Url::parse(python).ok()?;
        endpoint.path_segments_mut().ok()?.pop_if_empty().extend([
            "api",
            "v1",
            "platform-plugins",
            "v2",
            "optional-business",
            "sandbox-mcp",
            "projects",
            project,
            "tools",
        ]);
        Some(Self {
            endpoint,
            bearer,
            client,
        })
    }

    async fn tools(&self) -> Option<Vec<Value>> {
        let response = self
            .client
            .get(self.endpoint.clone())
            .header(header::AUTHORIZATION, &self.bearer)
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .ok()?
            .error_for_status()
            .ok()?;
        let mut result = bounded_json(response).await?;
        let Value::Array(tools) = result.get_mut("tools")?.take() else {
            return None;
        };
        Some(tools)
    }

    pub(super) async fn invoke(&self, id: Value, params: Value) -> Value {
        let invoke = async {
            let arguments = params
                .get("arguments")
                .cloned()
                .unwrap_or_else(|| json!({}));
            let body = json!({"name": params.get("name")?, "arguments": arguments});
            let response = self
                .client
                .post(self.endpoint.clone())
                .header(header::AUTHORIZATION, &self.bearer)
                .timeout(Duration::from_secs(45))
                .json(&body)
                .send()
                .await
                .ok()?
                .error_for_status()
                .ok()?;
            bounded_json(response).await
        };
        match invoke.await {
            Some(result) => json!({"jsonrpc":"2.0","id":id,"result":result}),
            None => {
                json!({"jsonrpc":"2.0","id":id,"error":{"code":-32001,"message":"Project package tool unavailable"}})
            }
        }
    }
}

async fn bounded_json(response: Response) -> Option<Value> {
    let mut body = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.ok()?;
        if chunk.len() > (4 * 1024 * 1024_usize).saturating_sub(body.len()) {
            return None;
        }
        body.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&body).ok()
}

fn rpc_key(value: &Value) -> Option<String> {
    if value.is_string() || value.is_i64() || value.is_u64() {
        Some(value.to_string())
    } else {
        None
    }
}

fn package_alias(name: &str) -> bool {
    let Some((plugin, rest)) = name.strip_prefix("pkg_").and_then(|n| n.split_once('_')) else {
        return false;
    };
    let Some((label, release)) = rest.rsplit_once('_') else {
        return false;
    };
    plugin.len() == 12
        && release.len() == 24
        && plugin
            .bytes()
            .chain(release.bytes())
            .all(|c| c.is_ascii_hexdigit())
        && (1..=20).contains(&label.len())
        && label
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
}

pub(super) struct Session {
    pub(super) authority: Authority,
    // Only enrich the matching first-page tools/list response and only route handles
    // advertised on this authenticated connection. Upstream tool names keep precedence.
    listings: HashMap<String, bool>,
    aliases: HashSet<String>,
    native_aliases: HashSet<String>,
}

impl Session {
    pub(super) fn new(authority: Authority) -> Self {
        Self {
            authority,
            listings: HashMap::new(),
            aliases: HashSet::new(),
            native_aliases: HashSet::new(),
        }
    }

    fn request(&mut self, text: &str) -> Option<(Value, Value)> {
        let request: Value = serde_json::from_str(text).ok()?;
        if request.get("jsonrpc")?.as_str()? != "2.0" {
            return None;
        }
        let id = request.get("id")?;
        let key = rpc_key(id)?;
        let method = request.get("method")?.as_str()?;
        if method == "tools/list" && self.listings.len() < 128 {
            self.listings
                .insert(key, request.pointer("/params/cursor").is_none());
        }
        if method == "tools/call" {
            let name = request.pointer("/params/name")?.as_str()?;
            if package_alias(name) && !self.native_aliases.contains(name) {
                return Some((id.clone(), request.get("params")?.clone()));
            }
        }
        None
    }

    pub(super) async fn response(&mut self, text: &str) -> Option<String> {
        if self.listings.is_empty() {
            return None;
        }
        let mut reply: Value = serde_json::from_str(text).ok()?;
        if reply.get("method").is_some() {
            return None;
        }
        let first_page = self.listings.remove(&rpc_key(reply.get("id")?)?)?;
        let original = reply.pointer_mut("/result/tools")?.as_array_mut()?;
        let previous = original.len();
        original.retain(|tool| {
            tool["name"]
                .as_str()
                .is_none_or(|name| !self.aliases.contains(name))
        });
        let removed = previous != original.len();
        let native_handles = original
            .iter()
            .filter_map(|t| t["name"].as_str())
            .filter(|name| package_alias(name))
            .take(4096_usize.saturating_sub(self.native_aliases.len()));
        self.native_aliases
            .extend(native_handles.map(str::to_owned));
        if !first_page {
            return removed.then(|| reply.to_string());
        }
        let discovered = self.authority.tools().await.unwrap_or_default();
        // Keep the previous handles private to the package authority after a release change.
        // They will fail its authorization check until the caller discovers the new release.
        for tool in discovered {
            let Some(name) = tool["name"].as_str() else {
                continue;
            };
            if !self.native_aliases.contains(name)
                && (self.aliases.contains(name) || self.aliases.len() < 4096)
            {
                self.aliases.insert(name.to_owned());
                original.push(tool);
            }
        }
        (removed || previous != original.len()).then(|| reply.to_string())
    }
}

fn cancellation(text: &str) -> Option<String> {
    let message: Value = serde_json::from_str(text).ok()?;
    if message.get("jsonrpc")?.as_str()? != "2.0"
        || message.get("method")?.as_str()? != "notifications/cancelled"
    {
        return None;
    }
    rpc_key(message.pointer("/params/requestId")?)
}

pub(super) enum Dispatch {
    Forward,
    Accepted,
    Error(String),
}

#[derive(Default)]
pub(super) struct Calls {
    jobs: JoinSet<(String, Option<Value>)>,
    cancellations: HashMap<String, AbortHandle>,
}

impl Calls {
    pub(super) fn is_empty(&self) -> bool {
        self.jobs.is_empty()
    }

    pub(super) fn receive(&mut self, session: &mut Session, text: &str) -> Dispatch {
        if let Some((id, params)) = session.request(text) {
            if !params["name"]
                .as_str()
                .is_some_and(|name| session.aliases.contains(name))
            {
                let error = json!({"jsonrpc":"2.0","id":id,"error":{"code":-32602,
                    "message":"Project tool was not advertised on this connection"}});
                return Dispatch::Error(error.to_string());
            }
            let key = id.to_string();
            if self.cancellations.len() >= 32 || self.cancellations.contains_key(&key) {
                let error = json!({"jsonrpc":"2.0","id":id,"error":{"code":-32002,
                    "message":"Project call already active or capacity exceeded"}});
                return Dispatch::Error(error.to_string());
            }
            let (handle, cancel) = AbortHandle::new_pair();
            self.cancellations.insert(key.clone(), handle);
            let host = session.authority.clone();
            self.jobs.spawn(async move {
                (
                    key,
                    Abortable::new(host.invoke(id, params), cancel).await.ok(),
                )
            });
            return Dispatch::Accepted;
        }
        if !self.cancellations.is_empty() {
            if let Some(handle) = cancellation(text).and_then(|key| self.cancellations.get(&key)) {
                handle.abort();
                return Dispatch::Accepted;
            }
        }
        Dispatch::Forward
    }

    pub(super) async fn next(&mut self) -> Option<String> {
        let (key, result) = self.jobs.join_next().await?.ok()?;
        self.cancellations.remove(&key);
        result.map(|value| value.to_string())
    }
}
