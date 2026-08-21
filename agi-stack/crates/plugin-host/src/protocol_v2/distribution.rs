//! Strict control-plane distribution parsing for protocol v2 data planes.

use serde::{
    ser::{SerializeStruct, Serializer},
    Deserialize, Serialize,
};
use serde_json::Value;

use super::{
    parse_profile_snapshot_v2, ControlPlaneEnvelopeV2, PluginProtocolV2Error, ProfileSnapshotV2,
    PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL_V2,
};

/// Immutable identity for one published plugin generation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PluginGenerationDescriptorV2 {
    pub profile_id: String,
    pub generation: u64,
    pub digest: String,
}

/// A complete, validated v2 control-plane distribution.
#[derive(Clone, Debug, PartialEq)]
pub struct ControlPlaneDistributionV2 {
    pub schema_version: u64,
    pub descriptor: PluginGenerationDescriptorV2,
    pub snapshot: ProfileSnapshotV2,
    pub envelope: ControlPlaneEnvelopeV2,
    snapshot_wire: Value,
}

impl Serialize for ControlPlaneDistributionV2 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("ControlPlaneDistributionV2", 4)?;
        state.serialize_field("schema_version", &self.schema_version)?;
        state.serialize_field("descriptor", &self.descriptor)?;
        state.serialize_field("snapshot", &self.snapshot_wire)?;
        state.serialize_field("envelope", &self.envelope)?;
        state.end()
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DistributionWireV2 {
    schema_version: u64,
    descriptor: PluginGenerationDescriptorV2,
    snapshot: Value,
    envelope: ControlPlaneEnvelopeV2,
}

/// Parse and validate a complete distribution before any target projection.
///
/// # Errors
///
/// Returns [`PluginProtocolV2Error`] for incompatible schemas, malformed snapshots,
/// digest mismatches, or inconsistent descriptor/envelope metadata.
pub fn parse_control_plane_distribution_v2(
    raw: &str,
) -> Result<ControlPlaneDistributionV2, PluginProtocolV2Error> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| PluginProtocolV2Error::InvalidJson(error.to_string()))?;
    if value.get("schema_version").and_then(Value::as_u64) != Some(2) {
        return Err(PluginProtocolV2Error::IncompatibleSchemaVersion);
    }
    let wire: DistributionWireV2 = serde_json::from_value(value)
        .map_err(|error| PluginProtocolV2Error::InvalidShape(error.to_string()))?;
    let snapshot_raw = serde_json::to_string(&wire.snapshot)
        .map_err(|error| PluginProtocolV2Error::InvalidShape(error.to_string()))?;
    let snapshot = parse_profile_snapshot_v2(&snapshot_raw)?;

    let expected_descriptor = PluginGenerationDescriptorV2 {
        profile_id: snapshot.profile_id.clone(),
        generation: snapshot.generation,
        digest: snapshot.digest.clone(),
    };
    if wire.descriptor != expected_descriptor {
        return Err(PluginProtocolV2Error::DistributionMismatch(
            "descriptor does not match snapshot".into(),
        ));
    }
    if wire.envelope.version == 0 {
        return Err(PluginProtocolV2Error::DistributionMismatch(
            "envelope version must be positive".into(),
        ));
    }
    if wire.envelope.nonce.is_empty() {
        return Err(PluginProtocolV2Error::DistributionMismatch(
            "envelope nonce must be non-empty".into(),
        ));
    }
    if wire.envelope.snapshot_digest != snapshot.digest {
        return Err(PluginProtocolV2Error::DistributionMismatch(
            "envelope digest does not match snapshot".into(),
        ));
    }
    if wire.envelope.type_url != PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL_V2 {
        return Err(PluginProtocolV2Error::DistributionMismatch(
            "envelope type_url is incompatible".into(),
        ));
    }

    Ok(ControlPlaneDistributionV2 {
        schema_version: wire.schema_version,
        descriptor: wire.descriptor,
        snapshot,
        envelope: wire.envelope,
        snapshot_wire: wire.snapshot,
    })
}
