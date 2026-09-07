//! Main-owned renderer deliveries. Credentials never cross the control response boundary.
use std::{collections::HashMap, sync::Mutex, time::Duration};

use agistack_plugin_host::protocol_v2::ApplyStatusV2;
use agistack_plugin_host::{
    parse_control_plane_distribution_v2, ControlPlaneDistributionV2, SnapshotApplyReceiptV2,
};
use futures_util::StreamExt;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use url::Url;
use uuid::Uuid;
use zeroize::Zeroizing;

use crate::{
    local_runtime::PlatformPluginAuthorityModeV2,
    plugin_data_plane_credential_v2::{
        validate_base_url_v2, PluginDataPlaneCredentialBrokerV2, PluginDataPlaneCredentialRecordV2,
        DESKTOP_RENDERER_DATA_PLANE_ID_V2,
    },
};

type Selection = (PlatformPluginAuthorityModeV2, u64);
const MAX_OWNERS: usize = 32;
const MAX_BYTES: usize = 4 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RendererOwnerV2 {
    pub owner_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RendererReceiptSubmissionV2 {
    pub owner_id: String,
    pub delivery_token: String,
    pub receipt: SnapshotApplyReceiptV2,
}

#[derive(Clone)]
struct Delivery {
    token: String,
    selection: Selection,
    configuration: String,
    epoch: Uuid,
    distribution: ControlPlaneDistributionV2,
    receipt: Option<SnapshotApplyReceiptV2>,
    posted: bool,
}

struct Deliveries {
    epoch: Uuid,
    owners: HashMap<String, Delivery>,
    requests: HashMap<String, Uuid>,
}

pub(super) struct DesktopRendererReceiptServiceV2 {
    broker: PluginDataPlaneCredentialBrokerV2,
    client: reqwest::Client,
    deliveries: Mutex<Deliveries>,
}

impl DesktopRendererReceiptServiceV2 {
    pub fn new(broker: PluginDataPlaneCredentialBrokerV2) -> Result<Self, String> {
        Ok(Self {
            broker,
            client: reqwest::Client::builder()
                .timeout(Duration::from_secs(10))
                .redirect(reqwest::redirect::Policy::none())
                .build()
                .map_err(|_| "renderer_transport_unavailable")?,
            deliveries: Mutex::new(Deliveries {
                epoch: Uuid::new_v4(),
                owners: HashMap::new(),
                requests: HashMap::new(),
            }),
        })
    }

    pub fn invalidate(&self) -> Result<(), String> {
        let mut state = self
            .deliveries
            .lock()
            .map_err(|_| "renderer_delivery_unavailable")?;
        state.epoch = Uuid::new_v4();
        state.owners.clear();
        state.requests.clear();
        Ok(())
    }

    pub fn retire_owner(&self, owner: &str) -> Result<(), String> {
        validate_owner(owner)?;
        let mut state = self
            .deliveries
            .lock()
            .map_err(|_| "renderer_delivery_unavailable")?;
        state.owners.remove(owner);
        state.requests.remove(owner);
        Ok(())
    }

    pub async fn fetch(
        &self,
        owner: &str,
        selection: impl Fn() -> Result<Selection, String>,
    ) -> Result<Option<Value>, String> {
        validate_owner(owner)?;
        let expected = selection()?;
        if expected.0 != PlatformPluginAuthorityModeV2::Cloud {
            return Err("renderer_cloud_not_selected".into());
        }
        let record = self
            .broker
            .load()
            .map_err(|error| error.to_string())?
            .ok_or("renderer_credential_required")?;
        let base = normalized_base(&record)?;
        let configuration = configuration(&record)?;
        let request_id = Uuid::new_v4();
        let epoch = {
            let mut state = self
                .deliveries
                .lock()
                .map_err(|_| "renderer_delivery_unavailable")?;
            if !state.requests.contains_key(owner) && state.requests.len() >= MAX_OWNERS {
                return Err("renderer_owner_capacity".into());
            }
            state.requests.insert(owner.to_owned(), request_id);
            state.epoch
        };
        let response = self
            .client
            .get(endpoint(&base, "distribution"))
            .bearer_auth(&record.credential)
            .send()
            .await
            .map_err(|_| "renderer_distribution_transport_failed")?;
        if response.status().as_u16() == 404 {
            self.require_current(expected, &configuration, epoch, &selection)?;
            let mut state = self
                .deliveries
                .lock()
                .map_err(|_| "renderer_delivery_unavailable")?;
            if state.requests.get(owner) != Some(&request_id) {
                return Err("renderer_delivery_superseded".into());
            }
            state.owners.remove(owner);
            return Ok(None);
        }
        if !response.status().is_success() {
            return Err(format!(
                "renderer_distribution_http_{}",
                response.status().as_u16()
            ));
        }
        if response
            .content_length()
            .is_some_and(|size| size > MAX_BYTES as u64)
        {
            return Err("renderer_distribution_too_large".into());
        }
        let mut bytes = Vec::new();
        let mut stream = response.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|_| "renderer_distribution_transport_failed")?;
            if bytes.len().saturating_add(chunk.len()) > MAX_BYTES {
                return Err("renderer_distribution_too_large".into());
            }
            bytes.extend_from_slice(&chunk);
        }
        let raw = std::str::from_utf8(&bytes).map_err(|_| "renderer_distribution_invalid")?;
        let distribution = parse_control_plane_distribution_v2(raw)
            .map_err(|_| "renderer_distribution_invalid")?;
        self.require_current(expected, &configuration, epoch, &selection)?;
        let authority_id = format!(
            "sha256:{:x}",
            Sha256::digest(format!("{}:{}", base, expected.1))
        );
        let mut state = self
            .deliveries
            .lock()
            .map_err(|_| "renderer_delivery_unavailable")?;
        if state.epoch != epoch || state.requests.get(owner) != Some(&request_id) {
            return Err("renderer_delivery_superseded".into());
        }
        if !state.owners.contains_key(owner) && state.owners.len() >= MAX_OWNERS {
            return Err("renderer_owner_capacity".into());
        }
        let existing = state.owners.get(owner).filter(|item| {
            item.selection == expected
                && item.configuration == configuration
                && item.epoch == epoch
                && item.distribution == distribution
        });
        let token = existing
            .map(|item| item.token.clone())
            .unwrap_or_else(|| Uuid::new_v4().to_string());
        if existing.is_none() {
            state.owners.insert(
                owner.to_owned(),
                Delivery {
                    token: token.clone(),
                    selection: expected,
                    configuration,
                    epoch,
                    distribution: distribution.clone(),
                    receipt: None,
                    posted: false,
                },
            );
        }
        Ok(Some(
            json!({"source":"cloud", "distribution": distribution, "delivery_token": token, "authority_id": authority_id}),
        ))
    }

    fn require_current(
        &self,
        expected: Selection,
        expected_configuration: &str,
        epoch: Uuid,
        selection: &impl Fn() -> Result<Selection, String>,
    ) -> Result<PluginDataPlaneCredentialRecordV2, String> {
        if selection()? != expected || expected.0 != PlatformPluginAuthorityModeV2::Cloud {
            return Err("renderer_delivery_superseded".into());
        }
        let record = self
            .broker
            .load()
            .map_err(|error| error.to_string())?
            .ok_or("renderer_credential_required")?;
        if configuration(&record)? != expected_configuration
            || self
                .deliveries
                .lock()
                .map_err(|_| "renderer_delivery_unavailable")?
                .epoch
                != epoch
        {
            return Err("renderer_delivery_superseded".into());
        }
        Ok(record)
    }

    pub async fn submit(
        &self,
        request: RendererReceiptSubmissionV2,
        selection: impl Fn() -> Result<Selection, String>,
    ) -> Result<(), String> {
        validate_owner(&request.owner_id)?;
        let delivery = self
            .deliveries
            .lock()
            .map_err(|_| "renderer_delivery_unavailable")?
            .owners
            .get(&request.owner_id)
            .filter(|item| item.token == request.delivery_token)
            .cloned()
            .ok_or("renderer_delivery_unknown")?;
        validate_receipt(&delivery.distribution, &request.receipt)?;
        let record = self.require_current(
            delivery.selection,
            &delivery.configuration,
            delivery.epoch,
            &selection,
        )?;
        if !record.ack_participation {
            return Err("renderer_ack_disabled".into());
        }
        {
            let mut state = self
                .deliveries
                .lock()
                .map_err(|_| "renderer_delivery_unavailable")?;
            let current = state
                .owners
                .get_mut(&request.owner_id)
                .filter(|item| item.token == request.delivery_token)
                .ok_or("renderer_delivery_unknown")?;
            if current
                .receipt
                .as_ref()
                .is_some_and(|prior| prior != &request.receipt)
            {
                return Err("renderer_receipt_conflict".into());
            }
            if current.posted {
                return Ok(());
            }
            current.receipt = Some(request.receipt.clone());
        }
        let base = normalized_base(&record)?;
        let response = self.client.post(endpoint(&base, "data-plane-state")).bearer_auth(&record.credential).json(&json!({"schema_version":2,"data_plane_id":DESKTOP_RENDERER_DATA_PLANE_ID_V2,"nonce":delivery.distribution.envelope.nonce,"receipt":request.receipt})).send().await.map_err(|_| "renderer_receipt_transport_failed")?;
        if !response.status().is_success() {
            return Err(format!(
                "renderer_receipt_http_{}",
                response.status().as_u16()
            ));
        }
        self.require_current(
            delivery.selection,
            &delivery.configuration,
            delivery.epoch,
            &selection,
        )?;
        let mut state = self
            .deliveries
            .lock()
            .map_err(|_| "renderer_delivery_unavailable")?;
        let current = state
            .owners
            .get_mut(&request.owner_id)
            .filter(|item| item.token == request.delivery_token)
            .ok_or("renderer_delivery_unknown")?;
        current.posted = true;
        Ok(())
    }
}

fn validate_owner(owner: &str) -> Result<(), String> {
    if owner.is_empty() || owner.len() > 128 {
        return Err("renderer_owner_invalid".into());
    }
    Ok(())
}

fn normalized_base(record: &PluginDataPlaneCredentialRecordV2) -> Result<Url, String> {
    let mut base =
        validate_base_url_v2(&record.api_base_url).map_err(|_| "renderer_origin_invalid")?;
    let path = base.path().trim_end_matches('/');
    let path = if path.ends_with("/api/v1") {
        path.to_owned()
    } else {
        format!("{path}/api/v1")
    };
    base.set_path(&path);
    Ok(base)
}
fn endpoint(base: &Url, suffix: &str) -> Url {
    let mut url = base.clone();
    url.set_path(&format!("{}/platform-plugins/v2/{suffix}", base.path()));
    url
}
fn configuration(record: &PluginDataPlaneCredentialRecordV2) -> Result<String, String> {
    let bytes =
        Zeroizing::new(serde_json::to_vec(record).map_err(|_| "renderer_credential_invalid")?);
    Ok(format!("sha256:{:x}", Sha256::digest(bytes.as_slice())))
}
fn validate_receipt(
    distribution: &ControlPlaneDistributionV2,
    receipt: &SnapshotApplyReceiptV2,
) -> Result<(), String> {
    if receipt.requested_version != distribution.envelope.version
        || receipt.requested_digest != distribution.snapshot.digest
    {
        return Err("renderer_receipt_mismatch".into());
    }
    match receipt.status {
        ApplyStatusV2::Ack
            if receipt.applied_version == Some(receipt.requested_version)
                && receipt.applied_digest.as_ref() == Some(&receipt.requested_digest)
                && receipt.error_code.is_none()
                && receipt.error_message.is_none() =>
        {
            Ok(())
        }
        ApplyStatusV2::Nack
            if receipt
                .error_code
                .as_ref()
                .is_some_and(|value| !value.is_empty())
                && receipt
                    .error_message
                    .as_ref()
                    .is_some_and(|value| !value.is_empty())
                && receipt.applied_version.is_some() == receipt.applied_digest.is_some()
                && receipt.applied_version.is_none_or(|version| version > 0)
                && receipt.applied_digest.as_ref().is_none_or(|digest| {
                    digest.len() == 64
                        && digest
                            .bytes()
                            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                }) =>
        {
            Ok(())
        }
        _ => Err("renderer_receipt_invalid".into()),
    }
}

#[cfg(test)]
#[path = "renderer_receipt_service_v2_tests.rs"]
mod tests;
