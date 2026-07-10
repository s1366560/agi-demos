use axum::http::HeaderValue;
use base64::{engine::general_purpose, Engine as _};
use sha2::{Digest, Sha256};

use super::*;

const MIN_RUNTIME_AUTH_SECRET_BYTES: usize = 32;
const HMAC_SHA256_BLOCK_BYTES: usize = 64;
const RUNTIME_AUTH_CONTEXT: &[u8] = b"memstack-sandbox-runtime-v1";

#[derive(Clone, PartialEq, Eq)]
pub(super) struct SandboxRuntimeToken(String);

impl SandboxRuntimeToken {
    pub(super) fn expose(&self) -> &str {
        &self.0
    }

    #[cfg(test)]
    pub(super) fn from_exposed(value: &str) -> Self {
        Self(value.to_string())
    }
}

impl std::fmt::Debug for SandboxRuntimeToken {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("[redacted]")
    }
}

#[derive(Clone)]
pub(super) struct SandboxRuntimeAuth {
    secret: Vec<u8>,
}

impl SandboxRuntimeAuth {
    pub(super) fn try_new(secret: impl AsRef<str>) -> Result<Self, &'static str> {
        let secret = secret.as_ref().as_bytes();
        if secret.len() < MIN_RUNTIME_AUTH_SECRET_BYTES {
            return Err("sandbox runtime auth secret must be at least 32 bytes");
        }
        Ok(Self {
            secret: secret.to_vec(),
        })
    }

    pub(super) fn token_for(&self, project_id: &str, tenant_id: &str) -> SandboxRuntimeToken {
        let mut message =
            Vec::with_capacity(RUNTIME_AUTH_CONTEXT.len() + project_id.len() + tenant_id.len() + 2);
        message.extend_from_slice(RUNTIME_AUTH_CONTEXT);
        message.push(0);
        message.extend_from_slice(project_id.as_bytes());
        message.push(0);
        message.extend_from_slice(tenant_id.as_bytes());
        SandboxRuntimeToken(
            general_purpose::URL_SAFE_NO_PAD.encode(hmac_sha256(&self.secret, &message)),
        )
    }
}

impl std::fmt::Debug for SandboxRuntimeAuth {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("[redacted]")
    }
}

fn hmac_sha256(key: &[u8], message: &[u8]) -> [u8; 32] {
    let normalized_key = if key.len() > HMAC_SHA256_BLOCK_BYTES {
        Sha256::digest(key).to_vec()
    } else {
        key.to_vec()
    };
    let mut inner_pad = [0x36_u8; HMAC_SHA256_BLOCK_BYTES];
    let mut outer_pad = [0x5c_u8; HMAC_SHA256_BLOCK_BYTES];
    for (index, byte) in normalized_key.iter().enumerate() {
        inner_pad[index] ^= byte;
        outer_pad[index] ^= byte;
    }

    let mut inner = Sha256::new();
    inner.update(inner_pad);
    inner.update(message);
    let inner_digest = inner.finalize();

    let mut outer = Sha256::new();
    outer.update(outer_pad);
    outer.update(inner_digest);
    outer.finalize().into()
}

pub(super) fn sandbox_basic_auth_header(
    token: &SandboxRuntimeToken,
) -> SandboxApiResult<HeaderValue> {
    let credentials = general_purpose::STANDARD.encode(format!("sandbox:{}", token.expose()));
    HeaderValue::from_str(&format!("Basic {credentials}"))
        .map_err(|_| SandboxApiError::internal("invalid sandbox runtime credential"))
}

pub(super) fn sandbox_bearer_auth_header(
    token: &SandboxRuntimeToken,
) -> SandboxApiResult<HeaderValue> {
    HeaderValue::from_str(&format!("Bearer {}", token.expose()))
        .map_err(|_| SandboxApiError::internal("invalid sandbox runtime credential"))
}
