//! Agent event model — the runtime-agnostic taxonomy + wire envelope shared by
//! the SessionProcessor (emits), the `EventStream` port (F5, transports opaque
//! JSON), and the WS event bridge (F7, delivers). This is the Rust port of the
//! Python single-source-of-truth `src/domain/events/{types,envelope}.py`.
//!
//! Pure data + pure functions: no I/O, no `uuid`/`rand`/clock — the `event_id`
//! and `timestamp` are **injected** by the caller (server uses uuid + a real
//! clock; device/tests inject deterministic values), mirroring the hexagonal
//! id/time discipline in [`crate::util`] and ADR-0001. Compiles to `wasm32`.

mod all;
mod envelope;
mod kind;
mod wire;

#[cfg(test)]
mod tests;

pub use envelope::EventEnvelope;
pub use kind::{AgentEventType, EventCategory};

use crate::util::fnv1a;

/// Deterministic, `wasm32`-clean `evt_`-prefixed event id derived from a seed via
/// FNV-1a — matches the Python `evt_` + 12-hex shape without pulling `uuid`.
/// Callers needing globally-unique random ids inject them instead (server: uuid
/// v4), consistent with the injected-id discipline in [`crate::util`].
pub fn derive_event_id(seed: &str) -> String {
    format!("evt_{:012x}", fnv1a(seed) & 0x0000_ffff_ffff_ffff)
}
