use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use async_trait::async_trait;
use serde_json::json;

use agistack_adapters_redis::{DeviceGrant, RedisDeviceGrantStore};
use agistack_adapters_secrets::{try_generate_device_user_code, try_generate_urlsafe_token};

use super::{
    DeviceCodeView, DeviceTokenView, IdentityError, DEVICE_CODE_INTERVAL_SECS,
    DEVICE_CODE_TTL_SECS, DEVICE_USER_CODE_ALLOC_ATTEMPTS,
};

/// Server-only ephemeral grant store for CLI device-code login. It intentionally
/// lives outside `core`: Redis TTL grants are a transport/auth concern, not a
/// portable domain port.
#[async_trait]
pub trait DeviceGrantStore: Send + Sync {
    async fn user_code_exists(&self, user_code: &str) -> Result<bool, String>;
    async fn create_pending(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        ttl_seconds: u64,
    ) -> Result<(), String>;
    async fn device_code_for_user_code(&self, user_code: &str) -> Result<Option<String>, String>;
    async fn get(&self, device_code: &str) -> Result<Option<DeviceGrant>, String>;
    async fn compare_and_set(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: &DeviceGrant,
    ) -> Result<bool, String>;
    async fn compare_and_set_and_delete_index(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: &DeviceGrant,
    ) -> Result<bool, String>;
    async fn compare_and_delete_pair(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
    ) -> Result<bool, String>;
}

pub type SharedDeviceGrantStore = Arc<dyn DeviceGrantStore>;

#[async_trait]
impl DeviceGrantStore for RedisDeviceGrantStore {
    async fn user_code_exists(&self, user_code: &str) -> Result<bool, String> {
        RedisDeviceGrantStore::user_code_exists(self, user_code)
            .await
            .map_err(|e| e.to_string())
    }

    async fn create_pending(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        ttl_seconds: u64,
    ) -> Result<(), String> {
        RedisDeviceGrantStore::create_pending(self, device_code, grant, ttl_seconds)
            .await
            .map_err(|e| e.to_string())
    }

    async fn device_code_for_user_code(&self, user_code: &str) -> Result<Option<String>, String> {
        RedisDeviceGrantStore::device_code_for_user_code(self, user_code)
            .await
            .map_err(|e| e.to_string())
    }

    async fn get(&self, device_code: &str) -> Result<Option<DeviceGrant>, String> {
        RedisDeviceGrantStore::get(self, device_code)
            .await
            .map_err(|e| e.to_string())
    }

    async fn compare_and_set(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: &DeviceGrant,
    ) -> Result<bool, String> {
        RedisDeviceGrantStore::compare_and_set(self, device_code, expected, replacement)
            .await
            .map_err(|e| e.to_string())
    }

    async fn compare_and_set_and_delete_index(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: &DeviceGrant,
    ) -> Result<bool, String> {
        RedisDeviceGrantStore::compare_and_set_and_delete_index(
            self,
            device_code,
            expected,
            replacement,
        )
        .await
        .map_err(|e| e.to_string())
    }

    async fn compare_and_delete_pair(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
    ) -> Result<bool, String> {
        RedisDeviceGrantStore::compare_and_delete_pair(self, device_code, expected)
            .await
            .map_err(|e| e.to_string())
    }
}

#[derive(Default)]
pub struct InMemoryDeviceGrantStore {
    inner: Mutex<InMemoryDeviceGrantState>,
}

#[derive(Default)]
struct InMemoryDeviceGrantState {
    device: HashMap<String, InMemoryDeviceGrantEntry>,
    user_code: HashMap<String, String>,
}

#[derive(Clone)]
struct InMemoryDeviceGrantEntry {
    grant: DeviceGrant,
    expires_at_ms: i64,
}

impl InMemoryDeviceGrantStore {
    pub fn new() -> Self {
        Self::default()
    }

    fn purge_expired(state: &mut InMemoryDeviceGrantState, now_ms: i64) {
        let expired: Vec<(String, String)> = state
            .device
            .iter()
            .filter(|(_, entry)| entry.expires_at_ms <= now_ms)
            .map(|(device_code, entry)| (device_code.clone(), entry.grant.user_code.clone()))
            .collect();
        for (device_code, user_code) in expired {
            state.device.remove(&device_code);
            state.user_code.remove(&user_code);
        }
    }
}

#[async_trait]
impl DeviceGrantStore for InMemoryDeviceGrantStore {
    async fn user_code_exists(&self, user_code: &str) -> Result<bool, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        Ok(state.user_code.contains_key(user_code))
    }

    async fn create_pending(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        ttl_seconds: u64,
    ) -> Result<(), String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        state
            .user_code
            .insert(grant.user_code.clone(), device_code.to_string());
        state.device.insert(
            device_code.to_string(),
            InMemoryDeviceGrantEntry {
                grant: grant.clone(),
                expires_at_ms: now_ms + (ttl_seconds as i64 * 1000),
            },
        );
        Ok(())
    }

    async fn device_code_for_user_code(&self, user_code: &str) -> Result<Option<String>, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        Ok(state.user_code.get(user_code).cloned())
    }

    async fn get(&self, device_code: &str) -> Result<Option<DeviceGrant>, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        Ok(state
            .device
            .get(device_code)
            .map(|entry| entry.grant.clone()))
    }

    async fn compare_and_set(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: &DeviceGrant,
    ) -> Result<bool, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        let Some(entry) = state.device.get_mut(device_code) else {
            return Ok(false);
        };
        if entry.grant != *expected {
            return Ok(false);
        }
        if expected.user_code != replacement.user_code {
            return Err("device grant CAS cannot change user code".to_string());
        }
        entry.grant = replacement.clone();
        Ok(true)
    }

    async fn compare_and_set_and_delete_index(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: &DeviceGrant,
    ) -> Result<bool, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        let Some(entry) = state.device.get_mut(device_code) else {
            return Ok(false);
        };
        if entry.grant != *expected {
            return Ok(false);
        }
        if expected.user_code != replacement.user_code {
            return Err("device grant CAS cannot change user code".to_string());
        }
        entry.grant = replacement.clone();
        if state.user_code.get(&expected.user_code).map(String::as_str) == Some(device_code) {
            state.user_code.remove(&expected.user_code);
        }
        Ok(true)
    }

    async fn compare_and_delete_pair(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
    ) -> Result<bool, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        let Some(entry) = state.device.get(device_code) else {
            return Ok(false);
        };
        if entry.grant != *expected {
            return Ok(false);
        }
        state.device.remove(device_code);
        if state.user_code.get(&expected.user_code).map(String::as_str) == Some(device_code) {
            state.user_code.remove(&expected.user_code);
        }
        Ok(true)
    }
}

pub(super) fn normalize_device_user_code(user_code: &str) -> String {
    user_code.trim().to_uppercase()
}

pub(super) async fn create_device_code_with_store(
    store: &dyn DeviceGrantStore,
) -> Result<DeviceCodeView, IdentityError> {
    for _ in 0..DEVICE_USER_CODE_ALLOC_ATTEMPTS {
        let user_code = try_generate_device_user_code().map_err(IdentityError::internal)?;
        if store
            .user_code_exists(&user_code)
            .await
            .map_err(IdentityError::internal)?
        {
            continue;
        }

        let device_code = try_generate_urlsafe_token(32).map_err(IdentityError::internal)?;
        let grant = DeviceGrant::pending(user_code.clone());
        store
            .create_pending(&device_code, &grant, DEVICE_CODE_TTL_SECS)
            .await
            .map_err(IdentityError::internal)?;

        return Ok(DeviceCodeView {
            device_code,
            user_code: user_code.clone(),
            verification_uri: "/device".to_string(),
            verification_uri_complete: format!("/device?user_code={user_code}"),
            expires_in: DEVICE_CODE_TTL_SECS,
            interval: DEVICE_CODE_INTERVAL_SECS,
        });
    }

    Err(IdentityError::service_unavailable(
        "Could not allocate user code",
    ))
}

pub(super) async fn poll_device_token_from_store(
    store: &dyn DeviceGrantStore,
    device_code: &str,
) -> Result<DeviceTokenView, IdentityError> {
    let device_code = device_code.trim();
    if device_code.is_empty() {
        return Err(IdentityError::bad_request("device_code required"));
    }
    let grant = store
        .get(device_code)
        .await
        .map_err(IdentityError::internal)?
        .ok_or_else(|| IdentityError::gone("expired_token"))?;

    match grant.status.as_str() {
        "pending" => Err(IdentityError::precondition_required(json!({
            "error": "authorization_pending",
            "interval": DEVICE_CODE_INTERVAL_SECS,
        }))),
        "approved" => {
            let access_token = grant
                .access_token
                .clone()
                .ok_or_else(|| IdentityError::internal("approved but no token stored"))?;
            let consumed = DeviceGrant {
                status: "consumed".to_string(),
                ..grant.clone()
            };
            let consumed_grant = store
                .compare_and_set_and_delete_index(device_code, &grant, &consumed)
                .await
                .map_err(IdentityError::internal)?;
            if !consumed_grant {
                return Err(IdentityError::gone("expired_token"));
            }
            Ok(DeviceTokenView {
                access_token,
                token_type: "bearer".to_string(),
            })
        }
        "consumed" => Err(IdentityError::gone("expired_token")),
        _ => Err(IdentityError::gone("device code was not approved")),
    }
}
