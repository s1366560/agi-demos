use std::collections::BTreeMap;

use agistack_adapters_postgres::ChannelWebhookSecretRecord;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

pub(crate) type FeishuWebhookHeaders = BTreeMap<String, String>;

#[derive(Debug, Clone, Copy)]
pub(crate) struct FeishuWebhookSecrets<'a> {
    pub(crate) verification_token: Option<&'a str>,
    pub(crate) encrypt_key: Option<&'a str>,
}

impl<'a> From<&'a ChannelWebhookSecretRecord> for FeishuWebhookSecrets<'a> {
    fn from(record: &'a ChannelWebhookSecretRecord) -> Self {
        Self {
            verification_token: record.verification_token.as_deref(),
            encrypt_key: record.encrypt_key.as_deref(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum FeishuWebhookVerification {
    UrlChallenge { challenge: String },
    Event,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum FeishuWebhookVerificationError {
    InvalidJsonObject,
    NotConfigured,
    InvalidToken,
    MissingSignatureHeaders,
    InvalidSignature,
}

pub(crate) fn verify_feishu_webhook_request(
    secrets: FeishuWebhookSecrets<'_>,
    headers: &FeishuWebhookHeaders,
    raw_body: &[u8],
    body: &Value,
) -> Result<FeishuWebhookVerification, FeishuWebhookVerificationError> {
    let Value::Object(object) = body else {
        return Err(FeishuWebhookVerificationError::InvalidJsonObject);
    };
    if secrets.verification_token.is_none() && secrets.encrypt_key.is_none() {
        return Err(FeishuWebhookVerificationError::NotConfigured);
    }

    if let Some(expected_token) = secrets.verification_token {
        let received = extract_feishu_verification_token(object).unwrap_or_default();
        if !constant_time_eq(received.as_bytes(), expected_token.as_bytes()) {
            return Err(FeishuWebhookVerificationError::InvalidToken);
        }
        if let Some(challenge) = feishu_challenge(object) {
            return Ok(FeishuWebhookVerification::UrlChallenge {
                challenge: challenge.to_string(),
            });
        }
    }

    if let Some(encrypt_key) = secrets.encrypt_key {
        verify_feishu_signature(headers, raw_body, encrypt_key)?;
    }

    Ok(FeishuWebhookVerification::Event)
}

pub(crate) fn feishu_webhook_idempotency_key(
    headers: &FeishuWebhookHeaders,
    raw_body: &[u8],
    body: &Value,
) -> String {
    if let Some(value) = first_string_path(
        body,
        &[
            &["event_id"],
            &["uuid"],
            &["header", "event_id"],
            &["event", "header", "event_id"],
            &["event", "message", "message_id"],
        ],
    ) {
        return value.to_string();
    }
    for name in ["X-Lark-Request-Id", "X-Request-Id"] {
        if let Some(value) = header_value(headers, name) {
            return value.to_string();
        }
    }
    format!("sha256:{}", sha256_hex(&[raw_body]))
}

fn verify_feishu_signature(
    headers: &FeishuWebhookHeaders,
    raw_body: &[u8],
    encrypt_key: &str,
) -> Result<(), FeishuWebhookVerificationError> {
    let Some(timestamp) = header_value(headers, "X-Lark-Request-Timestamp") else {
        return Err(FeishuWebhookVerificationError::MissingSignatureHeaders);
    };
    let Some(nonce) = header_value(headers, "X-Lark-Request-Nonce") else {
        return Err(FeishuWebhookVerificationError::MissingSignatureHeaders);
    };
    let Some(signature) = header_value(headers, "X-Lark-Signature") else {
        return Err(FeishuWebhookVerificationError::MissingSignatureHeaders);
    };
    let expected = sha256_hex(&[
        timestamp.as_bytes(),
        nonce.as_bytes(),
        encrypt_key.as_bytes(),
        raw_body,
    ]);
    if constant_time_eq(expected.as_bytes(), signature.as_bytes()) {
        Ok(())
    } else {
        Err(FeishuWebhookVerificationError::InvalidSignature)
    }
}

fn extract_feishu_verification_token(body: &Map<String, Value>) -> Option<&str> {
    object_field(body, "header")
        .and_then(|header| string_field(header, "token"))
        .or_else(|| {
            object_field(body, "event")
                .and_then(|event| object_field(event, "header"))
                .and_then(|header| string_field(header, "token"))
        })
        .or_else(|| string_field(body, "token"))
}

fn feishu_challenge(body: &Map<String, Value>) -> Option<&str> {
    string_field(body, "challenge")
}

fn header_value<'a>(headers: &'a FeishuWebhookHeaders, name: &str) -> Option<&'a str> {
    headers
        .iter()
        .find(|(key, _)| key.eq_ignore_ascii_case(name))
        .map(|(_, value)| value.as_str())
        .filter(|value| !value.is_empty())
}

fn first_string_path<'a>(body: &'a Value, paths: &[&[&str]]) -> Option<&'a str> {
    paths.iter().find_map(|path| string_path(body, path))
}

fn string_path<'a>(body: &'a Value, path: &[&str]) -> Option<&'a str> {
    let mut current = body;
    for key in path {
        current = current.get(*key)?;
    }
    current.as_str().filter(|value| !value.is_empty())
}

fn object_field<'a>(source: &'a Map<String, Value>, key: &str) -> Option<&'a Map<String, Value>> {
    source.get(key).and_then(Value::as_object)
}

fn string_field<'a>(source: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    source
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
}

fn sha256_hex(parts: &[&[u8]]) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update(part);
    }
    let digest = hasher.finalize();
    let mut out = String::with_capacity(digest.len() * 2);
    for byte in digest {
        out.push(hex_nibble(byte >> 4));
        out.push(hex_nibble(byte & 0x0f));
    }
    out
}

fn hex_nibble(nibble: u8) -> char {
    match nibble {
        0..=9 => char::from(b'0' + nibble),
        _ => char::from(b'a' + (nibble - 10)),
    }
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut diff = 0_u8;
    for (a, b) in left.iter().zip(right.iter()) {
        diff |= a ^ b;
    }
    diff == 0
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn signature(timestamp: &str, nonce: &str, encrypt_key: &str, raw_body: &[u8]) -> String {
        sha256_hex(&[
            timestamp.as_bytes(),
            nonce.as_bytes(),
            encrypt_key.as_bytes(),
            raw_body,
        ])
    }

    #[test]
    fn feishu_url_challenge_accepts_valid_token_without_signature() {
        let body = json!({
            "type": "url_verification",
            "token": "verify-token",
            "challenge": "challenge-value"
        });
        let result = verify_feishu_webhook_request(
            FeishuWebhookSecrets {
                verification_token: Some("verify-token"),
                encrypt_key: Some("encrypt-secret"),
            },
            &FeishuWebhookHeaders::new(),
            br#"{"token":"verify-token"}"#,
            &body,
        )
        .expect("valid challenge is accepted");

        assert_eq!(
            result,
            FeishuWebhookVerification::UrlChallenge {
                challenge: "challenge-value".to_string()
            }
        );
    }

    #[test]
    fn feishu_event_accepts_nested_token_and_signature() {
        let raw = br#"{"event":{"header":{"token":"verify-token","event_id":"evt-1"}}}"#;
        let mut headers = FeishuWebhookHeaders::new();
        headers.insert(
            "x-lark-request-timestamp".to_string(),
            "1700000000".to_string(),
        );
        headers.insert("x-lark-request-nonce".to_string(), "nonce".to_string());
        headers.insert(
            "x-lark-signature".to_string(),
            signature("1700000000", "nonce", "encrypt-secret", raw),
        );
        let body = json!({
            "event": {
                "header": {
                    "token": "verify-token",
                    "event_id": "evt-1"
                }
            }
        });

        let result = verify_feishu_webhook_request(
            FeishuWebhookSecrets {
                verification_token: Some("verify-token"),
                encrypt_key: Some("encrypt-secret"),
            },
            &headers,
            raw,
            &body,
        )
        .expect("valid event is accepted");

        assert_eq!(result, FeishuWebhookVerification::Event);
        assert_eq!(
            feishu_webhook_idempotency_key(&headers, raw, &body),
            "evt-1"
        );
    }

    #[test]
    fn feishu_event_rejects_invalid_signature() {
        let raw = br#"{"event":{"message":{"message_id":"mid-1"}}}"#;
        let mut headers = FeishuWebhookHeaders::new();
        headers.insert(
            "X-Lark-Request-Timestamp".to_string(),
            "1700000000".to_string(),
        );
        headers.insert("X-Lark-Request-Nonce".to_string(), "nonce".to_string());
        headers.insert("X-Lark-Signature".to_string(), "bad".to_string());

        let error = verify_feishu_webhook_request(
            FeishuWebhookSecrets {
                verification_token: None,
                encrypt_key: Some("encrypt-secret"),
            },
            &headers,
            raw,
            &json!({"event": {"message": {"message_id": "mid-1"}}}),
        )
        .expect_err("invalid signature is rejected");

        assert_eq!(error, FeishuWebhookVerificationError::InvalidSignature);
    }

    #[test]
    fn feishu_event_rejects_missing_configured_token() {
        let error = verify_feishu_webhook_request(
            FeishuWebhookSecrets {
                verification_token: Some("verify-token"),
                encrypt_key: None,
            },
            &FeishuWebhookHeaders::new(),
            br#"{"event":{}}"#,
            &json!({"event": {}}),
        )
        .expect_err("missing token is rejected");

        assert_eq!(error, FeishuWebhookVerificationError::InvalidToken);
    }
}
