mod rules;

#[cfg(test)]
mod tests;

use std::sync::OnceLock;

use axum::http::{HeaderMap, Method};

pub use rules::{STRANGLED_METHOD_RULES, STRANGLED_PREFIXES};

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
        path == *p
            || path
                .strip_prefix(*p)
                .is_some_and(|rest| rest.starts_with('/'))
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
            MethodMatchKind::Exact => {
                path == rule.path || path.strip_prefix(rule.path) == Some("/")
            }
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

/// Strip `base` plus its `/` segment boundary from `path`, allocation-free.
fn strip_base_segment<'a>(base: &str, path: &'a str) -> Option<&'a str> {
    path.strip_prefix(base)?.strip_prefix('/')
}

fn single_child_segment<'a>(base: &str, path: &'a str) -> Option<&'a str> {
    let rest = strip_base_segment(base, path)?;
    if !rest.is_empty() && !rest.contains('/') {
        Some(rest)
    } else {
        None
    }
}

fn single_child_with_suffix<'a>(base: &str, path: &'a str, suffix: &str) -> Option<&'a str> {
    let rest = strip_base_segment(base, path)?;
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
    let rest = strip_base_segment(base, path)?;
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
    let rest = strip_base_segment(base, path)?;
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
    let rest = strip_base_segment(base, path)?;
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
    let Some(rest) = strip_base_segment(base, path) else {
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
    upstream_for_request_with_preview(method, path, is_preview_host_headers(headers), upstreams)
}

/// Same as [`upstream_for_request_with_headers`] but takes the preview-host
/// verdict precomputed, so a handler that already checked the `Host` header
/// does not pay for a second check.
pub fn upstream_for_request_with_preview<'a>(
    method: &Method,
    path: &str,
    preview_host: bool,
    upstreams: &'a Upstreams,
) -> &'a str {
    if preview_host {
        &upstreams.rust
    } else {
        upstream_for_request(method, path, upstreams)
    }
}

pub fn is_preview_host(host_header: &str) -> bool {
    is_preview_host_for_suffix(host_header, preview_host_suffix_hostname())
}

pub(super) fn is_preview_host_headers(headers: &HeaderMap) -> bool {
    headers
        .get("host")
        .and_then(|value| value.to_str().ok())
        .map(is_preview_host)
        .unwrap_or(false)
}

/// The preview-host suffix is process configuration: read and normalize the
/// environment once instead of on every request.
fn preview_host_suffix_hostname() -> &'static str {
    static SUFFIX: OnceLock<String> = OnceLock::new();
    SUFFIX.get_or_init(|| {
        let raw = std::env::var(PREVIEW_HOST_SUFFIX_ENV)
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "preview.localhost:8000".to_string());
        host_header_hostname(&raw).unwrap_or_else(|| "preview.localhost".to_string())
    })
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
