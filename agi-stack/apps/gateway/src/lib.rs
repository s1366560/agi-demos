//! The **strangler-fig gateway** (plan.md Section 14.1) — the single front door
//! that lets the Rust rewrite replace the Python backend one capability at a
//! time, with zero frontend changes and instant rollback.
//!
//! ```text
//!  client ──▶ gateway ──▶ /api/v1/memories|episodes|recall  ──▶ agistack-server (Rust)
//!                     └──▶ everything else                    ──▶ Python backend (legacy)
//! ```
//!
//! A capability is "strangled" by moving its path prefix into
//! [`STRANGLED_PREFIXES`]. Because both backends speak the same `/api/v1`
//! contract, same `ms_sk_` bearer auth, and same JSON shapes (guaranteed by the
//! P1 parity work), the client cannot tell which backend served a request — the
//! essence of the strangler pattern. Rollback = move the prefix back.
//!
//! The gateway is a dumb, deterministic reverse proxy: **routing is pure path
//! prefix matching** (no semantics), and it forwards method/headers/body
//! verbatim — including `Authorization`, so bearer auth passes through unchanged.
//! WebSocket paths are also proxied without interpreting application messages.

use std::sync::Arc;

use axum::{
    body::Body,
    extract::{
        ws::{CloseFrame as AxumCloseFrame, Message as AxumWsMessage, WebSocket, WebSocketUpgrade},
        State,
    },
    http::{HeaderMap, HeaderName, Method, Request, Response, StatusCode, Uri},
    response::IntoResponse,
};
use futures_util::{SinkExt, StreamExt};
use tokio::net::TcpStream;
use tokio_tungstenite::{
    connect_async,
    tungstenite::{
        client::IntoClientRequest,
        handshake::client::Request as WsClientRequest,
        protocol::{
            frame::{
                coding::CloseCode as TungsteniteCloseCode, CloseFrame as TungsteniteCloseFrame,
            },
            Message as TungsteniteMessage,
        },
    },
    MaybeTlsStream, WebSocketStream,
};

/// Path prefixes already served by the Rust server. Everything else falls
/// through to the Python upstream. Add a prefix here to strangle a capability;
/// remove it to roll back.
pub const STRANGLED_PREFIXES: &[&str] = &[
    "/api/v1/memories",
    "/api/v1/episodes",
    "/api/v1/recall",
    // P2 login vertical (surgical — coarse prefix match, so only fully-covered
    // paths are listed). `/auth/token` and `/auth/oauth/*` are complete in Rust;
    // other `/auth/*` siblings (force-change-password, me, ...) stay in Python.
    "/api/v1/auth/token",
    "/api/v1/auth/oauth",
];

/// Method-scoped strangler rules for resources where the Rust backend only owns
/// read-side routes. This prevents a coarse `/api/v1/tenants` prefix from
/// accidentally capturing sibling endpoints such as `/tenants/{id}/members` or
/// write operations that still belong to Python.
pub const STRANGLED_METHOD_RULES: &[MethodRule] = &[
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "PATCH",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "invitations",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "invitations",
            excluded: &[],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "invitations",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "policies"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "policies"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "policies", "check"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "approval-requests"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "approval-requests", "*", "resolve"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "decision-records"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "decision-records", "*"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildExcept(&["sandboxes"]),
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildExcept(&["sandboxes"]),
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildExcept(&["sandboxes"]),
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "stats",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "PATCH",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &["sandboxes"],
        },
    },
    // P5 sandbox HTTP control-plane flip. These are deliberately method-scoped
    // and exclude the reserved `/projects/sandboxes/*` sibling namespace so the
    // data-plane proxy and unported collection siblings can be rolled back by
    // deleting only this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/projects/sandboxes",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "sandbox",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "sandbox",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "sandbox",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "health"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "stats"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "sync"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "execute"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "proxy-auth-cookie"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "restart"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "desktop"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "desktop"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "terminal"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "terminal"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "http-services"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "http-services"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "http-services", "*", "preview-session"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "http-services", "*"],
            excluded: &["sandboxes"],
        },
    },
    // P5 sandbox path data-plane flip. These remain exact method/tail rules:
    // no coarse `/projects/{id}/sandbox` prefix, and no preview-host wildcard.
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailPrefixExcept {
            tail_prefix: &["sandbox", "desktop", "proxy"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "*",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailPrefixExcept {
            tail_prefix: &["sandbox", "http-services", "*", "proxy"],
            excluded: &["sandboxes"],
        },
    },
    // P5 skill store/versioning flip. Only database-backed CRUD, content,
    // status, versions, and rollback are in Rust; filesystem/system import,
    // export, package, clone/publish, and evolution siblings remain Python.
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills/system/list",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildExcept(&["system"]),
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildExcept(&["system"]),
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildExcept(&["system"]),
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "content",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "content",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "PATCH",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "status",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "versions",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "versions",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "rollback",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/agent/ws",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/shared",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/auth/device/code",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/auth/device/approve",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/auth/device/token",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/invitations",
        match_kind: MethodMatchKind::FixedChildWithGrandchild { child: "verify" },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/invitations",
        match_kind: MethodMatchKind::FixedChildWithGrandchild { child: "accept" },
    },
];

/// Shape of a method-aware strangler rule.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MethodRule {
    pub method: &'static str,
    pub path: &'static str,
    pub match_kind: MethodMatchKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MethodMatchKind {
    /// Match exactly `path` plus an optional trailing slash.
    Exact,
    /// Match exactly one non-empty path segment under `path`.
    SingleChild,
    /// Match exactly one child segment except reserved Python-owned siblings.
    SingleChildExcept(&'static [&'static str]),
    /// Match `path/{child}/{suffix}` except reserved Python-owned child names.
    SingleChildWithSuffixExcept {
        suffix: &'static str,
        excluded: &'static [&'static str],
    },
    /// Match `path/{child}/{suffix}/{grandchild}`, excluding reserved child names.
    SingleChildWithSuffixAndGrandchildExcept {
        suffix: &'static str,
        excluded: &'static [&'static str],
    },
    /// Match `path/{child}/{tail...}`; `*` tail entries match exactly one
    /// non-empty segment. Excludes reserved Python-owned child names.
    SingleChildWithTailExcept {
        tail: &'static [&'static str],
        excluded: &'static [&'static str],
    },
    /// Match `path/{child}/{tail_prefix...}` and any non-empty remainder.
    /// `*` tail entries match exactly one non-empty segment.
    SingleChildWithTailPrefixExcept {
        tail_prefix: &'static [&'static str],
        excluded: &'static [&'static str],
    },
    /// Match `path/{child}/{grandchild}` for public token-style resources.
    FixedChildWithGrandchild { child: &'static str },
}

/// Max proxied body size (request or response) — 25 MiB, generous for JSON
/// payloads while bounding memory. Larger streaming bodies (e.g. agent token
/// streams, P3) will need a streaming path; not required for P1.
const MAX_BODY_BYTES: usize = 25 * 1024 * 1024;
const PREVIEW_HOST_SUFFIX_ENV: &str = "WORKSPACE_HTTP_PREVIEW_HOST_SUFFIX";

/// Where the two backends live. Both are plain base URLs (no trailing slash),
/// e.g. `http://127.0.0.1:8088` (Rust) and `http://127.0.0.1:8000` (Python).
#[derive(Clone, Debug)]
pub struct Upstreams {
    pub rust: String,
    pub python: String,
}

/// True when `path` belongs to an already-strangled capability and should be
/// routed to the Rust server. Pure prefix match — deterministic, no judgment.
pub fn is_strangled(path: &str) -> bool {
    STRANGLED_PREFIXES.iter().any(|p| {
        // Match the prefix exactly or as a path segment boundary so
        // `/api/v1/memories` and `/api/v1/memories/123` match but a hypothetical
        // `/api/v1/memories_admin` does not.
        path == *p || path.starts_with(&format!("{p}/"))
    })
}

/// True when a request is served by Rust, considering both legacy path-prefix
/// ownership and method-aware read-side ownership.
pub fn is_strangled_request(method: &Method, path: &str) -> bool {
    is_strangled(path)
        || STRANGLED_METHOD_RULES
            .iter()
            .any(|rule| method_matches(rule, method, path))
}

fn method_matches(rule: &MethodRule, method: &Method, path: &str) -> bool {
    (rule.method == "*" || method.as_str() == rule.method)
        && match rule.match_kind {
            MethodMatchKind::Exact => path == rule.path || path == format!("{}/", rule.path),
            MethodMatchKind::SingleChild => single_child_path(rule.path, path),
            MethodMatchKind::SingleChildExcept(excluded) => single_child_segment(rule.path, path)
                .map(|segment| !excluded.contains(&segment))
                .unwrap_or(false),
            MethodMatchKind::SingleChildWithSuffixExcept { suffix, excluded } => {
                single_child_with_suffix(rule.path, path, suffix)
                    .map(|segment| !excluded.contains(&segment))
                    .unwrap_or(false)
            }
            MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept { suffix, excluded } => {
                single_child_with_suffix_and_grandchild(rule.path, path, suffix)
                    .map(|segment| !excluded.contains(&segment))
                    .unwrap_or(false)
            }
            MethodMatchKind::SingleChildWithTailExcept { tail, excluded } => {
                single_child_with_tail(rule.path, path, tail)
                    .map(|segment| !excluded.contains(&segment))
                    .unwrap_or(false)
            }
            MethodMatchKind::SingleChildWithTailPrefixExcept {
                tail_prefix,
                excluded,
            } => single_child_with_tail_prefix(rule.path, path, tail_prefix)
                .map(|segment| !excluded.contains(&segment))
                .unwrap_or(false),
            MethodMatchKind::FixedChildWithGrandchild { child } => {
                fixed_child_with_grandchild(rule.path, path, child)
            }
        }
}

fn single_child_path(base: &str, path: &str) -> bool {
    single_child_segment(base, path).is_some()
}

fn single_child_segment<'a>(base: &str, path: &'a str) -> Option<&'a str> {
    let rest = path.strip_prefix(&format!("{base}/"))?;
    if !rest.is_empty() && !rest.contains('/') {
        Some(rest)
    } else {
        None
    }
}

fn single_child_with_suffix<'a>(base: &str, path: &'a str, suffix: &str) -> Option<&'a str> {
    let rest = path.strip_prefix(&format!("{base}/"))?;
    let mut parts = rest.split('/');
    let child = parts.next()?;
    let actual_suffix = parts.next()?;
    if child.is_empty() || actual_suffix != suffix || parts.next().is_some() {
        None
    } else {
        Some(child)
    }
}

fn single_child_with_suffix_and_grandchild<'a>(
    base: &str,
    path: &'a str,
    suffix: &str,
) -> Option<&'a str> {
    let rest = path.strip_prefix(&format!("{base}/"))?;
    let mut parts = rest.split('/');
    let child = parts.next()?;
    let actual_suffix = parts.next()?;
    let grandchild = parts.next()?;
    if child.is_empty()
        || actual_suffix != suffix
        || grandchild.is_empty()
        || parts.next().is_some()
    {
        None
    } else {
        Some(child)
    }
}

fn single_child_with_tail<'a>(
    base: &str,
    path: &'a str,
    tail: &'static [&'static str],
) -> Option<&'a str> {
    let rest = path.strip_prefix(&format!("{base}/"))?;
    let mut parts = rest.split('/');
    let child = parts.next()?;
    if child.is_empty() {
        return None;
    }

    for expected in tail {
        let actual = parts.next()?;
        if actual.is_empty() || (*expected != "*" && actual != *expected) {
            return None;
        }
    }

    if parts.next().is_some() {
        None
    } else {
        Some(child)
    }
}

fn single_child_with_tail_prefix<'a>(
    base: &str,
    path: &'a str,
    tail_prefix: &'static [&'static str],
) -> Option<&'a str> {
    let rest = path.strip_prefix(&format!("{base}/"))?;
    let mut parts = rest.split('/');
    let child = parts.next()?;
    if child.is_empty() {
        return None;
    }

    for expected in tail_prefix {
        let actual = parts.next()?;
        if actual.is_empty() || (*expected != "*" && actual != *expected) {
            return None;
        }
    }

    if parts.any(str::is_empty) {
        None
    } else {
        Some(child)
    }
}

fn fixed_child_with_grandchild(base: &str, path: &str, child: &str) -> bool {
    let Some(rest) = path.strip_prefix(&format!("{base}/")) else {
        return false;
    };
    let mut parts = rest.split('/');
    let actual_child = parts.next();
    let grandchild = parts.next();
    actual_child == Some(child)
        && grandchild
            .map(|segment| !segment.is_empty())
            .unwrap_or(false)
        && parts.next().is_none()
}

/// Pick the upstream base URL for a request path.
pub fn upstream_for<'a>(path: &str, upstreams: &'a Upstreams) -> &'a str {
    if is_strangled(path) {
        &upstreams.rust
    } else {
        &upstreams.python
    }
}

/// Pick the upstream base URL for a full request. New code should prefer this
/// over [`upstream_for`] because some strangled resources are method-scoped.
pub fn upstream_for_request<'a>(method: &Method, path: &str, upstreams: &'a Upstreams) -> &'a str {
    if is_strangled_request(method, path) {
        &upstreams.rust
    } else {
        &upstreams.python
    }
}

/// Pick the upstream for a full request including structural host-based routes.
/// Preview hosts have no stable `/api/v1` prefix; their capability boundary is
/// the DNS shape `{service}.{project}.{WORKSPACE_HTTP_PREVIEW_HOST_SUFFIX}`.
pub fn upstream_for_request_with_headers<'a>(
    method: &Method,
    path: &str,
    headers: &HeaderMap,
    upstreams: &'a Upstreams,
) -> &'a str {
    if is_preview_host_headers(headers) {
        &upstreams.rust
    } else {
        upstream_for_request(method, path, upstreams)
    }
}

pub fn is_preview_host(host_header: &str) -> bool {
    let suffix = preview_host_suffix_hostname();
    is_preview_host_for_suffix(host_header, &suffix)
}

fn is_preview_host_headers(headers: &HeaderMap) -> bool {
    headers
        .get("host")
        .and_then(|value| value.to_str().ok())
        .map(is_preview_host)
        .unwrap_or(false)
}

fn preview_host_suffix_hostname() -> String {
    let raw = std::env::var(PREVIEW_HOST_SUFFIX_ENV)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "preview.localhost:8000".to_string());
    host_header_hostname(&raw).unwrap_or_else(|| "preview.localhost".to_string())
}

fn is_preview_host_for_suffix(host_header: &str, suffix_hostname: &str) -> bool {
    let Some(hostname) = host_header_hostname(host_header) else {
        return false;
    };
    let suffix = suffix_hostname
        .trim()
        .trim_matches('.')
        .to_ascii_lowercase();
    if suffix.is_empty() {
        return false;
    }

    let expected_tail = format!(".{suffix}");
    if !hostname.ends_with(&expected_tail) {
        return false;
    }
    let prefix = &hostname[..hostname.len() - expected_tail.len()];
    let mut labels = prefix.split('.');
    let service_label = labels.next();
    let project_id = labels.next();
    labels.next().is_none()
        && service_label.map(is_preview_host_label).unwrap_or(false)
        && project_id.map(is_preview_host_label).unwrap_or(false)
}

fn host_header_hostname(value: &str) -> Option<String> {
    let value = value.trim();
    if value.is_empty() {
        return None;
    }
    let value = value
        .strip_prefix("http://")
        .or_else(|| value.strip_prefix("https://"))
        .unwrap_or(value);
    let authority = value.split('/').next().unwrap_or(value).trim();
    let host = if let Some(rest) = authority.strip_prefix('[') {
        rest.split_once(']').map(|(host, _)| host).unwrap_or(rest)
    } else {
        authority.split(':').next().unwrap_or(authority)
    };
    let host = host.trim_matches('.').to_ascii_lowercase();
    if host.is_empty() {
        None
    } else {
        Some(host)
    }
}

fn is_preview_host_label(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 63
        && value
            .chars()
            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '-')
}

pub fn strangled_rule_summary() -> String {
    let method_rules = STRANGLED_METHOD_RULES
        .iter()
        .map(|r| format!("{} {} ({:?})", r.method, r.path, r.match_kind))
        .collect::<Vec<_>>()
        .join(", ");
    if method_rules.is_empty() {
        STRANGLED_PREFIXES.join(", ")
    } else {
        format!(
            "prefixes=[{}]; method_rules=[{}]",
            STRANGLED_PREFIXES.join(", "),
            method_rules
        )
    }
}

/// Shared gateway state: a reusable HTTP client + the upstream addresses.
#[derive(Clone)]
pub struct GatewayState {
    pub client: reqwest::Client,
    pub upstreams: Arc<Upstreams>,
}

impl GatewayState {
    pub fn new(upstreams: Upstreams) -> Self {
        let client = reqwest::Client::builder()
            // Do not follow redirects: a 307 from a backend must reach the client
            // unchanged (mirrors FastAPI trailing-slash semantics end to end).
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .expect("build reqwest client");
        Self {
            client,
            upstreams: Arc::new(upstreams),
        }
    }
}

/// Hop-by-hop headers (RFC 7230 §6.1) plus framing headers we must not copy
/// verbatim, since the proxied body is re-framed by the client/server.
fn is_hop_by_hop(name: &HeaderName) -> bool {
    matches!(
        name.as_str(),
        "connection"
            | "keep-alive"
            | "proxy-authenticate"
            | "proxy-authorization"
            | "te"
            | "trailer"
            | "transfer-encoding"
            | "upgrade"
            | "content-length"
            | "host"
    )
}

/// Copy end-to-end headers from `src` into `dst`, dropping hop-by-hop/framing
/// headers. `Authorization` is end-to-end, so bearer tokens pass through.
fn copy_end_to_end_headers(src: &HeaderMap, dst: &mut HeaderMap) {
    for (name, value) in src.iter() {
        if !is_hop_by_hop(name) {
            dst.append(name.clone(), value.clone());
        }
    }
}

fn websocket_url(upstream: &str, path_and_query: &str) -> String {
    let base = upstream.trim_end_matches('/');
    let ws_base = if let Some(rest) = base.strip_prefix("http://") {
        format!("ws://{rest}")
    } else if let Some(rest) = base.strip_prefix("https://") {
        format!("wss://{rest}")
    } else {
        base.to_string()
    };
    format!("{ws_base}{path_and_query}")
}

fn copy_websocket_forward_headers(src: &HeaderMap, dst: &mut HeaderMap) {
    for name in [
        HeaderName::from_static("authorization"),
        HeaderName::from_static("cookie"),
        HeaderName::from_static("sec-websocket-protocol"),
        HeaderName::from_static("x-request-id"),
        HeaderName::from_static("x-correlation-id"),
        HeaderName::from_static("x-forwarded-for"),
        HeaderName::from_static("x-real-ip"),
    ] {
        if let Some(value) = src.get(&name) {
            dst.insert(name, value.clone());
        }
    }
}

fn preserve_host_header(src: &HeaderMap, dst: &mut HeaderMap) {
    if let Some(value) = src.get(HeaderName::from_static("host")) {
        dst.insert(HeaderName::from_static("host"), value.clone());
    }
}

fn build_upstream_ws_request(
    url: &str,
    headers: &HeaderMap,
    preserve_host: bool,
) -> Result<WsClientRequest, String> {
    let mut request = url
        .into_client_request()
        .map_err(|err| format!("invalid upstream websocket request: {err}"))?;
    copy_websocket_forward_headers(headers, request.headers_mut());
    if preserve_host {
        preserve_host_header(headers, request.headers_mut());
    }
    Ok(request)
}

type UpstreamWs = WebSocketStream<MaybeTlsStream<TcpStream>>;
const WEBSOCKET_SUBPROTOCOLS: [&str; 2] = ["memstack.auth", "binary"];

/// Proxy the single strangled WebSocket endpoint. The gateway connects to the
/// Rust upstream before accepting the client upgrade, so upstream failures can
/// still surface as a normal FastAPI-shaped 502 response.
pub async fn websocket_proxy(
    State(state): State<GatewayState>,
    headers: HeaderMap,
    uri: Uri,
    ws: WebSocketUpgrade,
) -> Response<Body> {
    websocket_proxy_to_upstream(&state.upstreams.rust, headers, uri, ws, false).await
}

async fn websocket_proxy_to_upstream(
    upstream: &str,
    headers: HeaderMap,
    uri: Uri,
    ws: WebSocketUpgrade,
    preserve_host: bool,
) -> Response<Body> {
    let path_and_query = uri.path_and_query().map(|pq| pq.as_str()).unwrap_or("/");
    let upstream_url = websocket_url(upstream, path_and_query);
    let request = match build_upstream_ws_request(&upstream_url, &headers, preserve_host) {
        Ok(request) => request,
        Err(err) => return error_response(StatusCode::BAD_GATEWAY, &err),
    };
    let upstream = match connect_async(request).await {
        Ok((stream, _response)) => stream,
        Err(err) => {
            return error_response(
                StatusCode::BAD_GATEWAY,
                &format!("upstream websocket failed: {err}"),
            )
        }
    };

    ws.protocols(WEBSOCKET_SUBPROTOCOLS)
        .on_upgrade(move |socket| pump_websockets(socket, upstream))
        .into_response()
}

async fn pump_websockets(mut client: WebSocket, mut upstream: UpstreamWs) {
    loop {
        tokio::select! {
            incoming = client.recv() => {
                let Some(Ok(message)) = incoming else {
                    let _ = upstream.close(None).await;
                    break;
                };
                let should_close = matches!(message, AxumWsMessage::Close(_));
                if upstream.send(axum_to_tungstenite(message)).await.is_err() {
                    break;
                }
                if should_close {
                    break;
                }
            }
            incoming = upstream.next() => {
                let Some(Ok(message)) = incoming else {
                    let _ = client.send(AxumWsMessage::Close(None)).await;
                    break;
                };
                let should_close = matches!(message, TungsteniteMessage::Close(_));
                if let Some(message) = tungstenite_to_axum(message) {
                    if client.send(message).await.is_err() {
                        break;
                    }
                }
                if should_close {
                    break;
                }
            }
        }
    }
}

fn axum_to_tungstenite(message: AxumWsMessage) -> TungsteniteMessage {
    match message {
        AxumWsMessage::Text(text) => TungsteniteMessage::Text(text),
        AxumWsMessage::Binary(binary) => TungsteniteMessage::Binary(binary),
        AxumWsMessage::Ping(ping) => TungsteniteMessage::Ping(ping),
        AxumWsMessage::Pong(pong) => TungsteniteMessage::Pong(pong),
        AxumWsMessage::Close(Some(close)) => {
            TungsteniteMessage::Close(Some(TungsteniteCloseFrame {
                code: TungsteniteCloseCode::from(close.code),
                reason: close.reason,
            }))
        }
        AxumWsMessage::Close(None) => TungsteniteMessage::Close(None),
    }
}

fn tungstenite_to_axum(message: TungsteniteMessage) -> Option<AxumWsMessage> {
    match message {
        TungsteniteMessage::Text(text) => Some(AxumWsMessage::Text(text)),
        TungsteniteMessage::Binary(binary) => Some(AxumWsMessage::Binary(binary)),
        TungsteniteMessage::Ping(ping) => Some(AxumWsMessage::Ping(ping)),
        TungsteniteMessage::Pong(pong) => Some(AxumWsMessage::Pong(pong)),
        TungsteniteMessage::Close(Some(close)) => {
            Some(AxumWsMessage::Close(Some(AxumCloseFrame {
                code: close.code.into(),
                reason: close.reason,
            })))
        }
        TungsteniteMessage::Close(None) => Some(AxumWsMessage::Close(None)),
        TungsteniteMessage::Frame(_) => None,
    }
}

/// The catch-all proxy handler: forward any request to the upstream chosen by
/// its path, preserving method, end-to-end headers (incl. `Authorization`), and
/// body, then relay the upstream's status/headers/body back to the client.
pub async fn proxy(State(state): State<GatewayState>, req: Request<Body>) -> Response<Body> {
    let (parts, body) = req.into_parts();
    let path = parts.uri.path().to_string();
    let path_and_query = parts
        .uri
        .path_and_query()
        .map(|pq| pq.as_str())
        .unwrap_or("/");

    let preview_host = is_preview_host_headers(&parts.headers);
    let upstream =
        upstream_for_request_with_headers(&parts.method, &path, &parts.headers, &state.upstreams);
    let url = format!("{upstream}{path_and_query}");

    let body_bytes = match axum::body::to_bytes(body, MAX_BODY_BYTES).await {
        Ok(bytes) => bytes,
        Err(_) => return error_response(StatusCode::PAYLOAD_TOO_LARGE, "request body too large"),
    };

    // Build the upstream request: same method + end-to-end headers + body.
    let mut forward_headers = HeaderMap::new();
    copy_end_to_end_headers(&parts.headers, &mut forward_headers);
    if preview_host {
        preserve_host_header(&parts.headers, &mut forward_headers);
    }

    let upstream_response = state
        .client
        .request(parts.method.clone(), &url)
        .headers(forward_headers)
        .body(body_bytes)
        .send()
        .await;

    let resp = match upstream_response {
        Ok(resp) => resp,
        Err(err) => {
            // Upstream unreachable / transport error -> 502, like a real gateway.
            return error_response(
                StatusCode::BAD_GATEWAY,
                &format!("upstream request failed: {err}"),
            );
        }
    };

    let status = resp.status();
    let mut response_headers = HeaderMap::new();
    copy_end_to_end_headers(resp.headers(), &mut response_headers);

    let resp_bytes = match resp.bytes().await {
        Ok(bytes) => bytes,
        Err(err) => {
            return error_response(
                StatusCode::BAD_GATEWAY,
                &format!("reading upstream response failed: {err}"),
            )
        }
    };

    let mut out = Response::new(Body::from(resp_bytes));
    *out.status_mut() = status;
    *out.headers_mut() = response_headers;
    out
}

pub async fn fallback_proxy(
    State(state): State<GatewayState>,
    headers: HeaderMap,
    uri: Uri,
    ws: Option<WebSocketUpgrade>,
    req: Request<Body>,
) -> Response<Body> {
    if let Some(ws) = ws {
        if is_preview_host_headers(&headers) {
            return websocket_proxy_to_upstream(&state.upstreams.rust, headers, uri, ws, true)
                .await;
        }
    }
    proxy(State(state), req).await
}

/// A minimal JSON error envelope matching the `{"detail": ...}` shape the rest
/// of the stack uses.
fn error_response(status: StatusCode, detail: &str) -> Response<Body> {
    let body = format!("{{\"detail\":\"{}\"}}", detail.replace('"', "'"));
    let mut resp = Response::new(Body::from(body));
    *resp.status_mut() = status;
    resp.headers_mut().insert(
        axum::http::header::CONTENT_TYPE,
        axum::http::HeaderValue::from_static("application/json"),
    );
    resp
}

/// Build the gateway router: a single catch-all that proxies every method and
/// path. Callers `serve` this or drive it in tests.
pub fn app(state: GatewayState) -> axum::Router {
    use axum::routing::{any, get};
    axum::Router::new()
        .route("/api/v1/agent/ws", get(websocket_proxy))
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy/websockify",
            get(websocket_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal/proxy/ws",
            get(websocket_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/mcp/proxy",
            get(websocket_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws",
            get(websocket_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws/*path",
            get(websocket_proxy),
        )
        .fallback(any(fallback_proxy))
        .with_state(state)
}

#[cfg(test)]
mod unit {
    use super::*;

    fn ups() -> Upstreams {
        Upstreams {
            rust: "http://rust:8088".into(),
            python: "http://python:8000".into(),
        }
    }

    #[test]
    fn strangled_prefixes_route_to_rust() {
        let get = Method::GET;
        assert!(is_strangled("/api/v1/memories"));
        assert!(is_strangled("/api/v1/memories/"));
        assert!(is_strangled("/api/v1/memories/abc123"));
        assert!(is_strangled("/api/v1/episodes/"));
        assert!(is_strangled("/api/v1/recall/short"));
        // P2 login vertical.
        assert!(is_strangled("/api/v1/auth/token"));
        assert!(is_strangled("/api/v1/auth/oauth/google/callback"));
        assert!(is_strangled_request(&get, "/api/v1/tenants"));
        assert!(is_strangled_request(&get, "/api/v1/tenants/"));
        assert!(is_strangled_request(&get, "/api/v1/tenants/acme"));
        assert!(is_strangled_request(&Method::POST, "/api/v1/tenants"));
        assert!(is_strangled_request(&Method::PUT, "/api/v1/tenants/acme"));
        assert!(is_strangled_request(
            &Method::DELETE,
            "/api/v1/tenants/acme"
        ));
        assert!(is_strangled_request(&get, "/api/v1/projects"));
        assert!(is_strangled_request(&Method::POST, "/api/v1/projects"));
        assert!(is_strangled_request(&get, "/api/v1/projects/p1"));
        assert!(is_strangled_request(&Method::PUT, "/api/v1/projects/p1"));
        assert!(is_strangled_request(&Method::DELETE, "/api/v1/projects/p1"));
        assert!(is_strangled_request(
            &Method::POST,
            "/api/v1/tenants/acme/members"
        ));
        assert!(is_strangled_request(
            &Method::POST,
            "/api/v1/tenants/acme/members/u1"
        ));
        assert!(is_strangled_request(
            &Method::PATCH,
            "/api/v1/tenants/acme/members/u1"
        ));
        assert!(is_strangled_request(
            &Method::DELETE,
            "/api/v1/tenants/acme/members/u1"
        ));
        assert!(is_strangled_request(&get, "/api/v1/agent/ws"));
        assert!(is_strangled_request(&get, "/api/v1/shared/share_token"));
        for p in [
            "/api/v1/memories",
            "/api/v1/episodes/",
            "/api/v1/recall/short",
            "/api/v1/auth/token",
            "/api/v1/auth/oauth/github/callback",
        ] {
            assert_eq!(upstream_for(p, &ups()), "http://rust:8088");
        }
        for p in [
            "/api/v1/tenants",
            "/api/v1/tenants/",
            "/api/v1/tenants/acme",
            "/api/v1/shared/share_token",
        ] {
            assert_eq!(upstream_for_request(&get, p, &ups()), "http://rust:8088");
        }
    }

    #[test]
    fn everything_else_routes_to_python() {
        let get = Method::GET;
        let post = Method::POST;
        for p in [
            "/api/v1/projects",
            // Other `/auth/*` siblings remain in Python (surgical strangling).
            "/api/v1/auth/force-change-password",
            "/api/v1/auth/me",
            "/api/v1/auth/tokens", // not a segment boundary of `/auth/token`
            // Tenant reads are method-scoped; sibling routes stay in Python.
            "/api/v1/tenants/t1/members",
            "/api/v1/tenants/t1/stats",
            "/api/v1/agent/sessions",
            "/api/v1/memories_admin", // not a segment boundary -> not strangled
            "/health",
            "/",
        ] {
            assert!(!is_strangled(p), "{p} should not be strangled");
            assert_eq!(upstream_for(p, &ups()), "http://python:8000");
        }
        assert_eq!(
            upstream_for_request(&get, "/api/v1/tenants/t1/members", &ups()),
            "http://python:8000"
        );
        assert_eq!(
            upstream_for_request(&post, "/api/v1/tenants/t1/stats", &ups()),
            "http://python:8000"
        );
        assert_eq!(
            upstream_for_request(&post, "/api/v1/agent/ws", &ups()),
            "http://python:8000"
        );
        assert_eq!(
            upstream_for_request(&Method::DELETE, "/api/v1/projects/sandboxes", &ups()),
            "http://python:8000"
        );
        assert_eq!(
            upstream_for_request(&Method::PUT, "/api/v1/projects/sandboxes", &ups()),
            "http://python:8000"
        );
        assert_eq!(
            upstream_for_request(&get, "/api/v1/shared/share_token/extra", &ups()),
            "http://python:8000"
        );
        assert_eq!(
            upstream_for_request(&post, "/api/v1/shared/share_token", &ups()),
            "http://python:8000"
        );
    }

    #[test]
    fn p5_sandbox_http_control_plane_rules_are_exact() {
        for (method, path) in [
            (Method::GET, "/api/v1/projects/sandboxes"),
            (Method::GET, "/api/v1/projects/p1/sandbox"),
            (Method::POST, "/api/v1/projects/p1/sandbox"),
            (Method::DELETE, "/api/v1/projects/p1/sandbox"),
            (Method::GET, "/api/v1/projects/p1/sandbox/health"),
            (Method::GET, "/api/v1/projects/p1/sandbox/stats"),
            (Method::GET, "/api/v1/projects/p1/sandbox/sync"),
            (Method::POST, "/api/v1/projects/p1/sandbox/execute"),
            (
                Method::POST,
                "/api/v1/projects/p1/sandbox/proxy-auth-cookie",
            ),
            (Method::POST, "/api/v1/projects/p1/sandbox/restart"),
            (Method::POST, "/api/v1/projects/p1/sandbox/desktop"),
            (Method::DELETE, "/api/v1/projects/p1/sandbox/desktop"),
            (Method::POST, "/api/v1/projects/p1/sandbox/terminal"),
            (Method::DELETE, "/api/v1/projects/p1/sandbox/terminal"),
            (Method::GET, "/api/v1/projects/p1/sandbox/http-services"),
            (Method::POST, "/api/v1/projects/p1/sandbox/http-services"),
            (
                Method::POST,
                "/api/v1/projects/p1/sandbox/http-services/web/preview-session",
            ),
            (
                Method::DELETE,
                "/api/v1/projects/p1/sandbox/http-services/web",
            ),
            (Method::GET, "/api/v1/projects/p1/sandbox/desktop/proxy"),
            (
                Method::GET,
                "/api/v1/projects/p1/sandbox/desktop/proxy/app.js",
            ),
            (
                Method::GET,
                "/api/v1/projects/p1/sandbox/desktop/proxy/websockify",
            ),
            (
                Method::GET,
                "/api/v1/projects/p1/sandbox/http-services/web/proxy",
            ),
            (
                Method::POST,
                "/api/v1/projects/p1/sandbox/http-services/web/proxy",
            ),
            (
                Method::PUT,
                "/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data",
            ),
            (
                Method::PATCH,
                "/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data",
            ),
            (
                Method::DELETE,
                "/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data",
            ),
            (
                Method::OPTIONS,
                "/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data",
            ),
            (
                Method::GET,
                "/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/socket",
            ),
        ] {
            assert_eq!(
                upstream_for_request(&method, path, &ups()),
                "http://rust:8088",
                "{method} {path} should route to rust",
            );
        }

        for (method, path) in [
            (Method::POST, "/api/v1/projects/sandboxes"),
            (Method::GET, "/api/v1/projects/sandboxes/stats"),
            (Method::GET, "/api/v1/projects/sandboxes/members"),
            (Method::POST, "/api/v1/projects/sandboxes/members"),
            (Method::PUT, "/api/v1/projects/p1/sandbox"),
            (Method::GET, "/api/v1/projects/p1/sandbox/restart"),
            (
                Method::GET,
                "/api/v1/projects/p1/sandbox/http-services/web/preview-session",
            ),
            (
                Method::GET,
                "/api/v1/projects/sandboxes/sandbox/http-services/web/proxy",
            ),
            (Method::GET, "/api/v1/projects/p1/sandbox/terminal/proxy/ws"),
            (Method::GET, "/api/v1/projects/p1/sandbox/mcp/proxy"),
        ] {
            assert_eq!(
                upstream_for_request(&method, path, &ups()),
                "http://python:8000",
                "{method} {path} should remain on python",
            );
        }
    }

    #[test]
    fn p5_skill_store_rules_are_exact() {
        for (method, path) in [
            (Method::GET, "/api/v1/skills"),
            (Method::GET, "/api/v1/skills/"),
            (Method::POST, "/api/v1/skills"),
            (Method::POST, "/api/v1/skills/"),
            (Method::GET, "/api/v1/skills/system/list"),
            (Method::GET, "/api/v1/skills/skill-1"),
            (Method::PUT, "/api/v1/skills/skill-1"),
            (Method::DELETE, "/api/v1/skills/skill-1"),
            (Method::GET, "/api/v1/skills/skill-1/content"),
            (Method::PUT, "/api/v1/skills/skill-1/content"),
            (Method::PATCH, "/api/v1/skills/skill-1/status"),
            (Method::GET, "/api/v1/skills/skill-1/versions"),
            (Method::GET, "/api/v1/skills/skill-1/versions/2"),
            (Method::POST, "/api/v1/skills/skill-1/rollback"),
        ] {
            assert_eq!(
                upstream_for_request(&method, path, &ups()),
                "http://rust:8088",
                "{method} {path} should route to rust",
            );
        }

        for (method, path) in [
            (Method::PATCH, "/api/v1/skills"),
            (Method::DELETE, "/api/v1/skills"),
            (Method::POST, "/api/v1/skills/system/list"),
            (Method::GET, "/api/v1/skills/system"),
            (Method::GET, "/api/v1/skills/system/import"),
            (Method::GET, "/api/v1/skills/system/list/extra"),
            (Method::POST, "/api/v1/skills/skill-1/content"),
            (Method::PUT, "/api/v1/skills/skill-1/status"),
            (Method::POST, "/api/v1/skills/skill-1/versions"),
            (Method::GET, "/api/v1/skills/skill-1/versions/2/extra"),
            (Method::GET, "/api/v1/skills/skill-1/rollback"),
            (Method::POST, "/api/v1/skills/skill-1/publish"),
            (Method::POST, "/api/v1/skills/skill-1/clone"),
            (Method::GET, "/api/v1/skills/skill-1/files"),
        ] {
            assert_eq!(
                upstream_for_request(&method, path, &ups()),
                "http://python:8000",
                "{method} {path} should remain on python",
            );
        }
    }

    #[test]
    fn preview_hosts_are_host_scoped_and_route_to_rust() {
        assert!(is_preview_host_for_suffix(
            "web.p1.preview.localhost:8000",
            "preview.localhost"
        ));
        assert!(is_preview_host_for_suffix(
            "WEB.P1.PREVIEW.LOCALHOST",
            "preview.localhost"
        ));
        assert!(is_preview_host_for_suffix(
            "https://web.p1.preview.example.test",
            "preview.example.test"
        ));

        for host in [
            "",
            "preview.localhost:8000",
            "web.preview.localhost:8000",
            "web.p1.other.localhost:8000",
            "deep.web.p1.preview.localhost:8000",
            "web.p1.preview.localhost.evil.test",
        ] {
            assert!(
                !is_preview_host_for_suffix(host, "preview.localhost"),
                "{host} should not match preview host shape",
            );
        }

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("host"),
            axum::http::HeaderValue::from_static("web.p1.preview.localhost:8000"),
        );
        assert_eq!(
            upstream_for_request_with_headers(&Method::GET, "/docs", &headers, &ups()),
            "http://rust:8088"
        );

        headers.insert(
            HeaderName::from_static("host"),
            axum::http::HeaderValue::from_static("web.p1.other.localhost:8000"),
        );
        assert_eq!(
            upstream_for_request_with_headers(&Method::GET, "/docs", &headers, &ups()),
            "http://python:8000"
        );
    }

    #[test]
    fn authorization_is_end_to_end() {
        // The bearer token must survive proxying -> not hop-by-hop.
        assert!(!is_hop_by_hop(&HeaderName::from_static("authorization")));
        // Framing/hop-by-hop headers are dropped.
        assert!(is_hop_by_hop(&HeaderName::from_static("content-length")));
        assert!(is_hop_by_hop(&HeaderName::from_static("connection")));
        assert!(is_hop_by_hop(&HeaderName::from_static("transfer-encoding")));
    }

    #[test]
    fn websocket_url_converts_http_base_to_ws() {
        assert_eq!(
            websocket_url("http://rust:8088", "/api/v1/agent/ws?token=ms_sk_x"),
            "ws://rust:8088/api/v1/agent/ws?token=ms_sk_x"
        );
        assert_eq!(
            websocket_url("https://rust.example", "/api/v1/agent/ws"),
            "wss://rust.example/api/v1/agent/ws"
        );
    }
}
