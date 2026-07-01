//! [`Clock`] adapters. The split here is the whole reason `Clock` is a port: a
//! fixed clock works everywhere (incl. wasm), while the real system clock uses
//! `std::time`, which **panics** on `wasm32-unknown-unknown` and is therefore
//! gated off that target (ADR-0001).

use agistack_core::ports::Clock;

/// A constant clock — deterministic for tests and usable on every platform.
pub struct FixedClock(pub i64);

impl Clock for FixedClock {
    fn now_ms(&self) -> i64 {
        self.0
    }
}

/// Wall-clock time from `std::time`. Native targets only: `SystemTime` is
/// unavailable on `wasm32-unknown-unknown`. On the web the host injects a
/// `performance.now()`-backed clock instead.
#[cfg(not(target_arch = "wasm32"))]
pub struct SystemClock;

#[cfg(not(target_arch = "wasm32"))]
impl Clock for SystemClock {
    fn now_ms(&self) -> i64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0)
    }
}
