//! # agistack-parity — the strangler parity hard-gate (F3)
//!
//! When a capability is strangled from Python to Rust, the frontend must not be
//! able to tell the difference: the Rust response has to carry the **same JSON
//! keys, the same value types, and the same scalar formatting** as the FastAPI /
//! pydantic response it replaces. This crate is the reusable assertion that
//! encodes that contract, so every wave from P2 onward flips a route only after
//! its response passes the gate (plan.md §14.2 F3, §15.1 F3+).
//!
//! ## What "parity" means here
//!
//! JSON objects are *unordered*, so key order is intentionally **not** compared —
//! a consumer deserializes into a map either way. What is compared:
//!
//!   - **Object key sets** — recursively; a missing or extra key is a mismatch.
//!   - **Array length + element order** — arrays *are* ordered.
//!   - **Scalar type + exact rendering** — `"2023-01-01T00:00:00Z"` is not
//!     `"2023-01-01T00:00:00+00:00"`; `1` is not `1.0`; `"A"` is not `"a"`.
//!     This is what catches the real strangler hazards (ISO-8601 `Z` vs offset,
//!     UUID casing, integer-vs-float drift).
//!
//! ## Matcher tokens (for dynamic fields)
//!
//! Real responses carry dynamic ids and timestamps, so a golden fixture cannot
//! pin them literally. A golden **string** of the form `<token>` asserts the
//! actual value's *format* instead of its exact value:
//!
//! | token        | passes when the actual value is …            |
//! |--------------|----------------------------------------------|
//! | `<any>`      | anything (including null)                     |
//! | `<string>`   | a JSON string                                |
//! | `<int>`      | a JSON integer                               |
//! | `<number>`   | any JSON number                              |
//! | `<bool>`     | a JSON boolean                               |
//! | `<null>`     | JSON null                                    |
//! | `<uuid>`     | a canonical lower-case UUID string           |
//! | `<iso8601>`  | an ISO-8601 UTC string ending in `Z`         |
//! | `<ms_sk>`    | an `ms_sk_` + 64-hex API key string          |
//! | `<token?>`   | the above **or** JSON null (e.g. `<iso8601?>`)|
//!
//! A trailing `?` *inside* the brackets makes any token also accept `null` — exactly the shape of
//! pydantic `Optional[...]` fields such as `updated_at`.
//!
//! ## Golden provenance
//!
//! The goldens shipped alongside the strangled endpoints are **derived from the
//! Python schemas** (`application/schemas/*.py`, `routers/*.py`) — the documented
//! wire contract — not captured from a live Python process (both backends are not
//! run side-by-side in this environment). Capturing goldens from a live Python
//! OpenAPI response is the natural next step once the two run in parallel; the
//! harness is identical either way.

use serde_json::Value;
use std::fmt;

/// One structural difference between a golden contract and an actual response.
/// `path` is a JSON-pointer-ish dotted/indexed location (e.g. `tenants[0].slug`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Mismatch {
    /// A key present in the golden is absent from the actual response.
    MissingKey { path: String },
    /// A key present in the actual response is not in the golden contract.
    ExtraKey { path: String },
    /// The JSON kinds differ (object vs array vs string vs number vs …).
    TypeMismatch {
        path: String,
        expected: String,
        actual: String,
    },
    /// Same kind, different value (scalar inequality, incl. string formatting).
    ValueMismatch {
        path: String,
        expected: String,
        actual: String,
    },
    /// Arrays of differing length.
    ArrayLen {
        path: String,
        expected: usize,
        actual: usize,
    },
    /// A `<matcher>` token was not satisfied by the actual value.
    Matcher {
        path: String,
        token: String,
        actual: String,
    },
    /// A `<matcher>` token was not recognised (typo in a golden).
    UnknownMatcher { path: String, token: String },
}

impl fmt::Display for Mismatch {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Mismatch::MissingKey { path } => write!(f, "{path}: missing key (in golden, absent in response)"),
            Mismatch::ExtraKey { path } => write!(f, "{path}: unexpected key (in response, absent in golden)"),
            Mismatch::TypeMismatch { path, expected, actual } => {
                write!(f, "{path}: type mismatch — golden {expected}, response {actual}")
            }
            Mismatch::ValueMismatch { path, expected, actual } => {
                write!(f, "{path}: value mismatch — golden {expected}, response {actual}")
            }
            Mismatch::ArrayLen { path, expected, actual } => {
                write!(f, "{path}: array length — golden {expected}, response {actual}")
            }
            Mismatch::Matcher { path, token, actual } => {
                write!(f, "{path}: value {actual} does not satisfy matcher <{token}>")
            }
            Mismatch::UnknownMatcher { path, token } => {
                write!(f, "{path}: unknown matcher token <{token}>")
            }
        }
    }
}

/// The outcome of comparing an actual response against a golden contract.
#[derive(Debug, Clone, Default)]
pub struct ParityReport {
    pub mismatches: Vec<Mismatch>,
}

impl ParityReport {
    /// True when the response is shape- and format-compatible with the golden.
    pub fn is_match(&self) -> bool {
        self.mismatches.is_empty()
    }
}

impl fmt::Display for ParityReport {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.is_match() {
            return write!(f, "parity OK");
        }
        writeln!(f, "parity FAILED ({} mismatch(es)):", self.mismatches.len())?;
        for m in &self.mismatches {
            writeln!(f, "  - {m}")?;
        }
        Ok(())
    }
}

/// Compare an `actual` response value against a `golden` contract value and
/// collect every difference. See the crate docs for the parity rules.
pub fn compare(golden: &Value, actual: &Value) -> ParityReport {
    let mut mismatches = Vec::new();
    walk("$", golden, actual, &mut mismatches);
    ParityReport { mismatches }
}

/// Compare and **panic** with a readable report on any mismatch. Intended for
/// `#[test]` use next to a strangled endpoint's response type.
pub fn assert_parity(golden: &Value, actual: &Value) {
    let report = compare(golden, actual);
    assert!(report.is_match(), "{report}");
}

fn kind(v: &Value) -> &'static str {
    match v {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

fn walk(path: &str, golden: &Value, actual: &Value, out: &mut Vec<Mismatch>) {
    // A golden string of the form `<token>` asserts a *format*, not a literal.
    if let Value::String(s) = golden {
        if let Some(token) = matcher_token(s) {
            check_matcher(path, token, actual, out);
            return;
        }
    }

    match (golden, actual) {
        (Value::Object(g), Value::Object(a)) => {
            for (k, gv) in g {
                let child = format!("{path}.{k}");
                match a.get(k) {
                    Some(av) => walk(&child, gv, av, out),
                    None => out.push(Mismatch::MissingKey { path: child }),
                }
            }
            for k in a.keys() {
                if !g.contains_key(k) {
                    out.push(Mismatch::ExtraKey { path: format!("{path}.{k}") });
                }
            }
        }
        (Value::Array(g), Value::Array(a)) => {
            if g.len() != a.len() {
                out.push(Mismatch::ArrayLen {
                    path: path.to_string(),
                    expected: g.len(),
                    actual: a.len(),
                });
                // Still compare the overlapping prefix for actionable detail.
            }
            for (i, (gv, av)) in g.iter().zip(a.iter()).enumerate() {
                walk(&format!("{path}[{i}]"), gv, av, out);
            }
        }
        (Value::Object(_), _) | (Value::Array(_), _) => out.push(Mismatch::TypeMismatch {
            path: path.to_string(),
            expected: kind(golden).to_string(),
            actual: kind(actual).to_string(),
        }),
        _ => {
            // Scalars: exact equality (this is where formatting parity bites).
            if kind(golden) != kind(actual) {
                out.push(Mismatch::TypeMismatch {
                    path: path.to_string(),
                    expected: kind(golden).to_string(),
                    actual: kind(actual).to_string(),
                });
            } else if golden != actual {
                out.push(Mismatch::ValueMismatch {
                    path: path.to_string(),
                    expected: golden.to_string(),
                    actual: actual.to_string(),
                });
            }
        }
    }
}

/// If `s` is exactly `<...>`, return the inner token, else `None`.
fn matcher_token(s: &str) -> Option<&str> {
    let bytes = s.as_bytes();
    if bytes.len() >= 2 && bytes[0] == b'<' && bytes[bytes.len() - 1] == b'>' {
        Some(&s[1..s.len() - 1])
    } else {
        None
    }
}

fn check_matcher(path: &str, token: &str, actual: &Value, out: &mut Vec<Mismatch>) {
    let (base, optional) = match token.strip_suffix('?') {
        Some(b) => (b, true),
        None => (token, false),
    };

    if actual.is_null() {
        // `<token?>`, `<any>` and `<null>` tolerate null; everything else rejects it.
        if optional || base == "any" || base == "null" {
            return;
        }
        out.push(Mismatch::Matcher {
            path: path.to_string(),
            token: token.to_string(),
            actual: "null".to_string(),
        });
        return;
    }

    let ok = match base {
        "any" => true,
        "null" => false, // non-null actual against <null>
        "string" => actual.is_string(),
        "int" => actual.is_i64() || actual.is_u64(),
        "number" => actual.is_number(),
        "bool" => actual.is_boolean(),
        "uuid" => actual.as_str().map(is_canonical_uuid).unwrap_or(false),
        "iso8601" => actual.as_str().map(is_iso8601_utc_z).unwrap_or(false),
        "ms_sk" => actual.as_str().map(is_ms_sk_key).unwrap_or(false),
        _ => {
            out.push(Mismatch::UnknownMatcher {
                path: path.to_string(),
                token: token.to_string(),
            });
            return;
        }
    };

    if !ok {
        out.push(Mismatch::Matcher {
            path: path.to_string(),
            token: token.to_string(),
            actual: actual.to_string(),
        });
    }
}

// ---- format validators (also public for direct assertions) ----------------

/// A canonical lower-case UUID: `8-4-4-4-12` lower-hex with hyphens.
pub fn is_canonical_uuid(s: &str) -> bool {
    let b = s.as_bytes();
    if b.len() != 36 {
        return false;
    }
    for (i, &c) in b.iter().enumerate() {
        match i {
            8 | 13 | 18 | 23 => {
                if c != b'-' {
                    return false;
                }
            }
            _ => {
                if !c.is_ascii_digit() && !(b'a'..=b'f').contains(&c) {
                    return false;
                }
            }
        }
    }
    true
}

/// An ISO-8601 UTC timestamp rendered with a trailing `Z` (the pydantic default
/// for `datetime(timezone.utc)` via FastAPI's json encoder), optionally with a
/// fractional-second part: `YYYY-MM-DDTHH:MM:SS[.fff]Z`. A `+00:00` offset form
/// is intentionally rejected — that divergence is a real strangler hazard.
pub fn is_iso8601_utc_z(s: &str) -> bool {
    let Some(body) = s.strip_suffix('Z') else {
        return false;
    };
    let Some((date, time)) = body.split_once('T') else {
        return false;
    };
    // date == YYYY-MM-DD
    let d = date.as_bytes();
    if d.len() != 10 || d[4] != b'-' || d[7] != b'-' {
        return false;
    }
    if !all_digits(&date[0..4]) || !all_digits(&date[5..7]) || !all_digits(&date[8..10]) {
        return false;
    }
    // time == HH:MM:SS or HH:MM:SS.fraction
    let (hms, frac) = match time.split_once('.') {
        Some((h, f)) => (h, Some(f)),
        None => (time, None),
    };
    let t = hms.as_bytes();
    if t.len() != 8 || t[2] != b':' || t[5] != b':' {
        return false;
    }
    if !all_digits(&hms[0..2]) || !all_digits(&hms[3..5]) || !all_digits(&hms[6..8]) {
        return false;
    }
    match frac {
        Some(f) => !f.is_empty() && all_digits(f),
        None => true,
    }
}

/// An `ms_sk_` API key: the `ms_sk_` prefix followed by exactly 64 lower-hex
/// characters (the shape `adapters-secrets` mints, mirroring Python's format).
pub fn is_ms_sk_key(s: &str) -> bool {
    let Some(rest) = s.strip_prefix("ms_sk_") else {
        return false;
    };
    rest.len() == 64 && rest.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

/// The FastAPI `HTTPException` error envelope: a JSON object carrying a `detail`
/// field. Rust handlers must render errors this way so the frontend's existing
/// error handling keeps working across a strangler flip.
pub fn is_error_envelope(v: &Value) -> bool {
    v.as_object().map(|o| o.contains_key("detail")).unwrap_or(false)
}

/// True when `v` is `{"detail": <expected>}` (exact detail string).
pub fn error_envelope_is(v: &Value, expected_detail: &str) -> bool {
    v.get("detail").and_then(Value::as_str) == Some(expected_detail)
}

fn all_digits(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn identical_objects_match_regardless_of_key_order() {
        let golden = json!({ "a": 1, "b": "x" });
        let actual = json!({ "b": "x", "a": 1 });
        assert!(compare(&golden, &actual).is_match());
    }

    #[test]
    fn missing_and_extra_keys_are_reported() {
        let golden = json!({ "a": 1, "b": 2 });
        let actual = json!({ "a": 1, "c": 3 });
        let r = compare(&golden, &actual);
        assert!(!r.is_match());
        assert!(r.mismatches.iter().any(|m| matches!(m, Mismatch::MissingKey { path } if path == "$.b")));
        assert!(r.mismatches.iter().any(|m| matches!(m, Mismatch::ExtraKey { path } if path == "$.c")));
    }

    #[test]
    fn type_and_value_mismatches_are_reported() {
        let golden = json!({ "n": 1, "s": "A" });
        let actual = json!({ "n": "1", "s": "a" });
        let r = compare(&golden, &actual);
        assert!(r.mismatches.iter().any(|m| matches!(m, Mismatch::TypeMismatch { path, .. } if path == "$.n")));
        assert!(r.mismatches.iter().any(|m| matches!(m, Mismatch::ValueMismatch { path, .. } if path == "$.s")));
    }

    #[test]
    fn integer_is_not_float() {
        // A classic strangler drift: pydantic emits ints, a Rust f64 would not.
        let golden = json!({ "page_size": 20 });
        let actual = json!({ "page_size": 20.0 });
        assert!(!compare(&golden, &actual).is_match());
    }

    #[test]
    fn array_order_and_length_matter() {
        assert!(compare(&json!([1, 2, 3]), &json!([1, 2, 3])).is_match());
        assert!(!compare(&json!([1, 2, 3]), &json!([3, 2, 1])).is_match());
        let short = compare(&json!([1, 2, 3]), &json!([1, 2]));
        assert!(short.mismatches.iter().any(|m| matches!(m, Mismatch::ArrayLen { expected: 3, actual: 2, .. })));
    }

    #[test]
    fn nested_path_is_reported() {
        let golden = json!({ "tenants": [{ "slug": "acme" }] });
        let actual = json!({ "tenants": [{ "slug": "other" }] });
        let r = compare(&golden, &actual);
        assert!(r.mismatches.iter().any(|m| matches!(m, Mismatch::ValueMismatch { path, .. } if path == "$.tenants[0].slug")));
    }

    #[test]
    fn matcher_uuid_iso_ms_sk() {
        let golden = json!({ "id": "<uuid>", "at": "<iso8601>", "key": "<ms_sk>" });
        let actual = json!({
            "id": "1b4e28ba-2fa1-11d2-883f-0016d3cca427",
            "at": "2023-11-14T22:13:20Z",
            "key": "ms_sk_0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        });
        assert_parity(&golden, &actual);
    }

    #[test]
    fn matcher_rejects_wrong_format() {
        // +00:00 offset must fail the ISO-8601-Z matcher.
        let g = json!({ "at": "<iso8601>" });
        assert!(!compare(&g, &json!({ "at": "2023-11-14T22:13:20+00:00" })).is_match());
        // upper-case UUID fails the canonical-lowercase matcher.
        let g2 = json!({ "id": "<uuid>" });
        assert!(!compare(&g2, &json!({ "id": "1B4E28BA-2FA1-11D2-883F-0016D3CCA427" })).is_match());
    }

    #[test]
    fn optional_matcher_accepts_null_and_value() {
        let g = json!({ "updated_at": "<iso8601?>" });
        assert!(compare(&g, &json!({ "updated_at": null })).is_match());
        assert!(compare(&g, &json!({ "updated_at": "2023-11-14T22:13:20Z" })).is_match());
        // A non-null wrong format still fails.
        assert!(!compare(&g, &json!({ "updated_at": "nope" })).is_match());
    }

    #[test]
    fn required_matcher_rejects_null() {
        let g = json!({ "id": "<uuid>" });
        assert!(!compare(&g, &json!({ "id": null })).is_match());
    }

    #[test]
    fn unknown_matcher_token_fails_loudly() {
        let g = json!({ "x": "<wat>" });
        let r = compare(&g, &json!({ "x": "anything" }));
        assert!(r.mismatches.iter().any(|m| matches!(m, Mismatch::UnknownMatcher { .. })));
    }

    #[test]
    fn iso8601_validator_accepts_fractional_and_rejects_offset() {
        assert!(is_iso8601_utc_z("2023-11-14T22:13:20Z"));
        assert!(is_iso8601_utc_z("2023-11-14T22:13:20.123Z"));
        assert!(!is_iso8601_utc_z("2023-11-14T22:13:20+00:00"));
        assert!(!is_iso8601_utc_z("2023-11-14 22:13:20Z"));
        assert!(!is_iso8601_utc_z("not-a-date"));
    }

    #[test]
    fn uuid_and_ms_sk_validators() {
        assert!(is_canonical_uuid("1b4e28ba-2fa1-11d2-883f-0016d3cca427"));
        assert!(!is_canonical_uuid("1b4e28ba2fa111d2883f0016d3cca427"));
        assert!(!is_canonical_uuid("ZZZZ28ba-2fa1-11d2-883f-0016d3cca427"));
        assert!(is_ms_sk_key("ms_sk_0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"));
        assert!(!is_ms_sk_key("ms_sk_short"));
        assert!(!is_ms_sk_key("jwt.header.payload"));
    }

    #[test]
    fn error_envelope_helpers() {
        assert!(is_error_envelope(&json!({ "detail": "Incorrect username or password" })));
        assert!(!is_error_envelope(&json!({ "error": "nope" })));
        assert!(error_envelope_is(&json!({ "detail": "x" }), "x"));
        assert!(!error_envelope_is(&json!({ "detail": "x" }), "y"));
    }
}
