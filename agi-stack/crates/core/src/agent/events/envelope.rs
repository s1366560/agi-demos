use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use super::{AgentEventType, EventCategory};

/// Standard wire envelope wrapping every domain event — the Rust port of Python
/// `EventEnvelope`. Field set, defaults, and `to_value` key order match
/// `envelope.py::to_dict`, so a Rust producer and the Python/frontend consumer
/// serialize identically. `correlation_id`/`causation_id` serialize as JSON
/// `null` when absent (no `skip_serializing_if`) to preserve shape parity.
///
/// `event_id`/`timestamp` are injected (see module docs) rather than generated
/// ambiently, keeping the type pure and `wasm32`-clean.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventEnvelope {
    pub schema_version: String,
    pub event_id: String,
    pub event_type: String,
    pub timestamp: String,
    pub source: String,
    pub correlation_id: Option<String>,
    pub causation_id: Option<String>,
    pub payload: Value,
    pub metadata: Value,
}

impl EventEnvelope {
    /// Default schema version (Python `EventEnvelope.schema_version`).
    pub const SCHEMA_VERSION: &'static str = "1.0";
    /// Default source system (Python `EventEnvelope.source`).
    pub const SOURCE: &'static str = "memstack";

    /// Primary factory: wrap a typed domain event into an envelope. Mirrors
    /// Python `EventEnvelope.wrap`, except `event_id`/`timestamp` are injected.
    pub fn wrap(
        event_type: AgentEventType,
        payload: Value,
        event_id: impl Into<String>,
        timestamp: impl Into<String>,
    ) -> Self {
        Self {
            schema_version: Self::SCHEMA_VERSION.to_string(),
            event_id: event_id.into(),
            event_type: event_type.as_str().to_string(),
            timestamp: timestamp.into(),
            source: Self::SOURCE.to_string(),
            correlation_id: None,
            causation_id: None,
            payload,
            metadata: Value::Object(Map::new()),
        }
    }

    /// The typed event kind, if `event_type` is a known wire string.
    pub fn typed(&self) -> Option<AgentEventType> {
        AgentEventType::from_wire(&self.event_type)
    }

    /// Category grouping via the typed event kind (defaults to `Agent` for any
    /// known-but-unmapped type; `None` only for an unrecognized wire string).
    pub fn category(&self) -> Option<EventCategory> {
        self.typed().map(|t| t.category())
    }

    /// Set correlation (and optional causation) ids, mirroring Python
    /// `with_correlation`.
    pub fn with_correlation(
        mut self,
        correlation_id: impl Into<String>,
        causation_id: Option<String>,
    ) -> Self {
        self.correlation_id = Some(correlation_id.into());
        if causation_id.is_some() {
            self.causation_id = causation_id;
        }
        self
    }

    /// Insert a single metadata key, mirroring Python `with_metadata`.
    pub fn with_metadata(mut self, key: impl Into<String>, value: Value) -> Self {
        if !self.metadata.is_object() {
            self.metadata = Value::Object(Map::new());
        }
        if let Some(obj) = self.metadata.as_object_mut() {
            obj.insert(key.into(), value);
        }
        self
    }

    /// Derive a child envelope: the child inherits this envelope's
    /// `correlation_id`, takes this envelope's `event_id` as its `causation_id`,
    /// and merges parent metadata under child overrides. Mirrors Python
    /// `create_child_envelope`.
    pub fn child(
        &self,
        event_type: AgentEventType,
        payload: Value,
        event_id: impl Into<String>,
        timestamp: impl Into<String>,
    ) -> Self {
        let mut metadata = self.metadata.clone();
        if !metadata.is_object() {
            metadata = Value::Object(Map::new());
        }
        Self {
            schema_version: Self::SCHEMA_VERSION.to_string(),
            event_id: event_id.into(),
            event_type: event_type.as_str().to_string(),
            timestamp: timestamp.into(),
            source: Self::SOURCE.to_string(),
            correlation_id: self.correlation_id.clone(),
            causation_id: Some(self.event_id.clone()),
            payload,
            metadata,
        }
    }

    /// Serialize to a `serde_json::Value` (the normalized wire form the F5
    /// `EventStream` transports as opaque JSON and the F7 bridge delivers).
    pub fn to_value(&self) -> Value {
        serde_json::to_value(self).unwrap_or(Value::Null)
    }

    /// Serialize to a JSON string (Python `to_json`).
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).unwrap_or_else(|_| "{}".to_string())
    }

    /// Parse an envelope from a JSON string (Python `from_json`).
    pub fn from_json(s: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(s)
    }
}
