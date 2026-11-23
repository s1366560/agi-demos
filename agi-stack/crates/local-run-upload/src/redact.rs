//! Path and secret redaction shared by the queue and the cloud payload.

use serde_json::Value;

pub const LOCAL_ROOT_TOKEN: &str = "<local-root>";
pub const REDACTED_TOKEN: &str = "<redacted>";

pub fn redact_with_root(value: &str, local_root: &str) -> String {
    let replaced = replace_root(value, local_root);
    if contains_secret_like_text(&replaced) {
        return REDACTED_TOKEN.to_string();
    }
    rewrite_absolute_paths(&replaced)
}

pub fn redact_uploaded_json(value: &Value, local_root: &str) -> Value {
    redact_value(value, local_root, 0)
}

pub fn contains_secret_like_text(value: &str) -> bool {
    let patterns = [
        r"(?i)\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"(?i)\bGHP_[A-Z0-9]{20,}\b",
        r"(?i)\bGH(?:S|U|O|P)_[A-Z0-9]{20,}\b",
        r"(?i)\bGITHUB_PAT_[A-Z0-9_]{20,}\b",
        r"(?i)\bBEARER\s+[A-Z0-9._-]{16,}\b",
        r"(?i)\bSK-PROJ-[A-Z0-9_-]{16,}\b",
        r"(?i)\bSK-[A-Z0-9]{16,}\b",
        r"(?i)\bSK(?:_LIVE|_TEST)?_[A-Z0-9_]{16,}\b",
        r"(?i)\bMS_SK_[A-F0-9]{16,}\b",
        r"(?i)\bXOX[BAPRS]_[A-Z0-9_]{10,}\b",
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    ];
    patterns.iter().any(|pattern| regex_search(pattern, value))
}

fn redact_value(value: &Value, local_root: &str, depth: usize) -> Value {
    if depth > 32 {
        return Value::String(REDACTED_TOKEN.to_string());
    }
    match value {
        Value::String(text) => Value::String(redact_with_root(text, local_root)),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| redact_value(item, local_root, depth + 1))
                .collect(),
        ),
        Value::Object(map) => {
            let mut redacted = serde_json::Map::new();
            for (key, item) in map {
                let safe_key = redact_with_root(key, local_root);
                redacted.insert(safe_key, redact_value(item, local_root, depth + 1));
            }
            Value::Object(redacted)
        }
        other => other.clone(),
    }
}

fn replace_root(value: &str, local_root: &str) -> String {
    let root = local_root.trim().trim_end_matches(['/', '\\']);
    if root.is_empty() {
        return value.to_string();
    }
    let forward = root.replace('\\', "/");
    let mut output = value.replace(root, LOCAL_ROOT_TOKEN);
    if forward != root {
        output = output.replace(&forward, LOCAL_ROOT_TOKEN);
    }
    output
}

fn rewrite_absolute_paths(value: &str) -> String {
    let mut held = Vec::new();
    let mut parked = String::new();
    let chars: Vec<char> = value.chars().collect();
    let mut index = 0;
    while index < chars.len() {
        if chars[index..].starts_with(&['<', 'l', 'o', 'c', 'a', 'l', '-', 'r', 'o', 'o', 't', '>'])
        {
            let start = index;
            index += "<local-root>".chars().count();
            while index < chars.len() && chars[index] == '/' {
                let segment_start = index;
                index += 1;
                while index < chars.len() && !chars[index].is_whitespace() && chars[index] != '<' {
                    index += 1;
                }
                if index == segment_start + 1 {
                    break;
                }
            }
            held.push(chars[start..index].iter().collect::<String>());
            parked.push('\u{0000}');
            parked.push_str(&held.len().saturating_sub(1).to_string());
            parked.push('\u{0000}');
            continue;
        }
        parked.push(chars[index]);
        index += 1;
    }
    let rewritten = rewrite_raw_paths(&parked);
    let mut restored = rewritten;
    for (offset, token) in held.iter().enumerate() {
        restored = restored.replace(&format!("\u{0000}{offset}\u{0000}"), token);
    }
    restored
}

fn rewrite_raw_paths(value: &str) -> String {
    let mut output = String::new();
    let chars: Vec<char> = value.chars().collect();
    let mut index = 0;
    while index < chars.len() {
        let absolute = is_absolute_at(&chars, index);
        if absolute {
            let start = index;
            index += 1;
            while index < chars.len()
                && !chars[index].is_whitespace()
                && chars[index] != '"'
                && chars[index] != '\''
            {
                index += 1;
            }
            let path: String = chars[start..index].iter().collect();
            output.push_str(LOCAL_ROOT_TOKEN);
            output.push('/');
            output.push_str(path_basename(&path));
            continue;
        }
        output.push(chars[index]);
        index += 1;
    }
    output
}

fn is_absolute_at(chars: &[char], index: usize) -> bool {
    let previous_ok = index == 0 || !chars[index - 1].is_ascii_alphanumeric();
    if !previous_ok {
        return false;
    }
    if chars[index] == '/' {
        return chars
            .get(index + 1)
            .is_some_and(|next| !next.is_whitespace());
    }
    chars.get(index + 1) == Some(&':')
        && chars.get(index + 2) == Some(&'\\')
        && chars[index].is_ascii_alphabetic()
}

fn path_basename(path: &str) -> &str {
    path.trim_end_matches(['/', '\\'])
        .rsplit(['/', '\\'])
        .next()
        .filter(|base| !base.is_empty() && *base != "." && *base != "..")
        .unwrap_or("redacted-path")
}

fn regex_search(pattern: &str, value: &str) -> bool {
    RegexSearch::new(pattern).is_some_and(|search| search.found(value))
}

struct RegexSearch {
    pattern: String,
}

impl RegexSearch {
    fn new(pattern: &str) -> Option<Self> {
        Some(Self {
            pattern: pattern.to_string(),
        })
    }

    fn found(&self, value: &str) -> bool {
        secret_patterns_match(&self.pattern, value)
    }
}

fn secret_patterns_match(pattern: &str, value: &str) -> bool {
    match pattern {
        r"(?i)\bSK-[A-Z0-9]{16,}\b" => has_sk_token(value),
        r"(?i)\bBEARER\s+[A-Z0-9._-]{16,}\b" => has_bearer(value),
        r"(?i)\bMS_SK_[A-F0-9]{16,}\b" => has_prefixed(value, &["ms_sk_", "MS_SK_"]),
        r"(?i)\b(?:AKIA|ASIA)[A-Z0-9]{16}\b" => has_aws(value),
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b" => has_jwt(value),
        _ => false,
    }
}

fn has_sk_token(value: &str) -> bool {
    value
        .split(|ch: char| !ch.is_ascii_alphanumeric() && ch != '-' && ch != '_')
        .any(|token| {
            let lower = token.to_ascii_lowercase();
            (lower.starts_with("sk-")
                || lower.starts_with("sk_live_")
                || lower.starts_with("sk_test_"))
                && token
                    .chars()
                    .skip(lower.find('-').map(|index| index + 1).unwrap_or(3))
                    .count()
                    >= 16
        })
}

fn has_bearer(value: &str) -> bool {
    let lower = value.to_ascii_lowercase();
    lower
        .split_whitespace()
        .collect::<Vec<_>>()
        .windows(2)
        .any(|pair| {
            pair[0] == "bearer"
                && pair[1]
                    .chars()
                    .filter(|ch| {
                        ch.is_ascii_alphanumeric() || *ch == '.' || *ch == '_' || *ch == '-'
                    })
                    .count()
                    >= 16
        })
}

fn has_prefixed(value: &str, prefixes: &[&str]) -> bool {
    value
        .split(|ch: char| !ch.is_ascii_alphanumeric() && ch != '_')
        .any(|token| {
            prefixes.iter().any(|prefix| {
                token.len() >= prefix.len() + 16
                    && token[..prefix.len()].eq_ignore_ascii_case(prefix)
            })
        })
}

fn has_aws(value: &str) -> bool {
    value
        .split(|ch: char| !ch.is_ascii_alphanumeric())
        .any(|token| {
            let upper = token.to_ascii_uppercase();
            (upper.starts_with("AKIA") || upper.starts_with("ASIA")) && upper.len() == 20
        })
}

fn has_jwt(value: &str) -> bool {
    value.split_whitespace().any(|token| {
        let parts: Vec<&str> = token
            .trim_matches(|ch: char| ch == '"' || ch == '\'' || ch == ',')
            .split('.')
            .collect();
        parts.len() == 3
            && parts[0].starts_with("eyJ")
            && parts.iter().all(|part| {
                part.len() >= 8
                    && part
                        .chars()
                        .all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '-')
            })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn root_replacement_keeps_the_relative_path_and_drops_secrets() {
        let root = "/Users/alice/src/agi-demos";
        let redacted = redact_with_root(&format!("{root}/src/main.ts"), root);
        assert_eq!(redacted, "<local-root>/src/main.ts");
        assert!(!redacted.contains("/Users/alice"));
        assert_eq!(
            redact_with_root("token sk-abcdefghijklmnopqrstuvwxyz", root),
            "<redacted>"
        );
        let preserved = redact_uploaded_json(
            &serde_json::json!({"path": "<local-root>/src/main.ts"}),
            root,
        );
        assert_eq!(preserved["path"], "<local-root>/src/main.ts");
    }
}
