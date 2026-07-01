//! The **control-plane** side of the control-flow / data-flow split.
//!
//! This is the agi-stack distillation of two industrial control planes:
//!   - **Kubernetes**: the API server is the single source of truth (SSOT); the
//!     desired state (`spec`) is authoritative and every write gets a new
//!     monotonic `resourceVersion`. Data planes reconcile *toward* it.
//!   - **Istio / Envoy xDS**: config travels as a versioned `DiscoveryResponse`
//!     (`version_info`, `nonce`, `type_url`, `resources`); the data plane replies
//!     with an ACK or a NACK (`envoyproxy/envoy:api/envoy/service/discovery/v3/
//!     discovery.proto`, `envoyproxy/envoy:api/xds_protocol.rst`).
//!
//! Portability invariant (sustains ADR-0001/0003): this module is **pure data +
//! arithmetic** — no tokio, no `std::time`, no transport. The transport that
//! actually carries a [`ConfigSnapshot`] to a data plane (server gRPC/WebSocket,
//! device HTTP long-poll, or an in-process channel) lives *outside* the core, so
//! the protocol values compile to every target the core does. Separating the
//! protocol (here) from its transport is itself the control/data-plane split
//! applied to our own code.
//!
//! Agent First: bumping the version and minting a nonce are protocol/arithmetic
//! facts and stay deterministic here. *What policy to publish* (which tenant gets
//! which tools) is a semantic, control-plane decision made upstream by an agent /
//! policy engine — it is never encoded in this module.

use crate::manifest::ToolDecl;

/// The `type_url` identifying a tool-registry config stream. Istio uses fully
/// qualified protobuf type URLs (e.g.
/// `type.googleapis.com/envoy.config.cluster.v3.Cluster`); here one stable string
/// names the resource type a snapshot carries, so a data plane can reject a
/// snapshot of the wrong type (the xDS type-check step).
pub const TOOL_REGISTRY_TYPE_URL: &str = "agi-stack/tool-registry/v1";

/// An xDS-style **config snapshot** — the unit the control plane pushes to a data
/// plane. Mirrors Envoy's `DiscoveryResponse`
/// (`envoyproxy/envoy:api/envoy/service/discovery/v3/discovery.proto`):
///
/// - `type_url`  — which resource type this carries (xDS `type_url`).
/// - `version`   — monotonic config version (xDS `version_info`; K8s
///   `resourceVersion`). Lets the data plane detect staleness and idempotent
///   re-pushes.
/// - `nonce`     — per-push identifier the data plane echoes back in its ACK/NACK
///   so the control plane can correlate the response (xDS `nonce`).
/// - `resources` — the **full desired set** (state-of-the-world, SotW). A
///   delta/incremental-xDS variant would carry only changed/removed names; that
///   is noted as future work in `08-control-data-plane-separation.md`.
#[derive(Debug, Clone)]
pub struct ConfigSnapshot {
    pub type_url: String,
    pub version: u64,
    pub nonce: String,
    pub resources: Vec<ToolDecl>,
}

/// The data plane's response to a snapshot — xDS **ACK/NACK** semantics
/// (`envoyproxy/envoy:api/xds_protocol.rst`, "ACK/NACK and resource type instance
/// version"):
///
/// - [`Ack`](Self::Ack) — the snapshot was accepted and applied; echoes the
///   accepted `version` + `nonce`.
/// - [`Nack`](Self::Nack) — the snapshot was rejected; echoes the `nonce`, reports
///   an `error`, and the data plane keeps its **last good** config rather than
///   applying the rejected update. A bad push therefore cannot brick a data plane.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConfigAck {
    Ack {
        version: u64,
        nonce: String,
    },
    Nack {
        version: u64,
        nonce: String,
        error: String,
    },
}

impl ConfigAck {
    pub fn is_ack(&self) -> bool {
        matches!(self, ConfigAck::Ack { .. })
    }

    pub fn is_nack(&self) -> bool {
        matches!(self, ConfigAck::Nack { .. })
    }

    /// The `version` this response refers to (whether ACK or NACK).
    pub fn version(&self) -> u64 {
        match self {
            ConfigAck::Ack { version, .. } | ConfigAck::Nack { version, .. } => *version,
        }
    }

    /// The error message if this is a NACK.
    pub fn error(&self) -> Option<&str> {
        match self {
            ConfigAck::Nack { error, .. } => Some(error),
            ConfigAck::Ack { .. } => None,
        }
    }
}

/// The authoritative **control plane**: holds desired state and emits versioned
/// snapshots. [`publish`](Self::publish) is the only way to change desired state,
/// and it bumps the version monotonically — mirroring how every Kubernetes write
/// gets a fresh `resourceVersion` and every xDS config change a fresh
/// `version_info`.
///
/// The control plane is the SSOT: the desired set it holds — not any data plane's
/// local view — is authoritative. A data plane that has drifted, missed a push,
/// or just reconnected is brought back into line by reconciling against a snapshot
/// from here (see [`crate::reconcile`]).
pub struct ControlPlane {
    version: u64,
    nonce_seq: u64,
    desired: Vec<ToolDecl>,
}

impl Default for ControlPlane {
    fn default() -> Self {
        Self::new()
    }
}

impl ControlPlane {
    pub fn new() -> Self {
        Self {
            version: 0,
            nonce_seq: 0,
            desired: Vec::new(),
        }
    }

    /// Publish a new **desired** tool set. Bumps the config version monotonically,
    /// stores it as the new SSOT, and returns the snapshot to distribute.
    pub fn publish(&mut self, tools: Vec<ToolDecl>) -> ConfigSnapshot {
        self.version += 1;
        self.desired = tools;
        self.snapshot()
    }

    /// Re-emit the **current** desired state as a fresh snapshot (new nonce, same
    /// version). This is the **reconnect / full-resend** path: when a data plane
    /// reconnects it receives the whole state-of-the-world again — exactly like an
    /// Envoy re-subscribing to istiod, or a Kong data plane reconnecting and
    /// pulling a full config (ADR-0006). Idempotent at the data plane: if it is
    /// already converged, reconciling this snapshot is a no-op ACK.
    pub fn snapshot(&mut self) -> ConfigSnapshot {
        self.nonce_seq += 1;
        ConfigSnapshot {
            type_url: TOOL_REGISTRY_TYPE_URL.to_string(),
            version: self.version,
            nonce: format!("nonce-{}-{}", self.version, self.nonce_seq),
            resources: self.desired.clone(),
        }
    }

    /// The current authoritative config version.
    pub fn version(&self) -> u64 {
        self.version
    }

    /// The current desired set (read-only view of the SSOT).
    pub fn desired(&self) -> &[ToolDecl] {
        &self.desired
    }
}
