//! Local-first sync over the in-memory adapter tier (Wave H, `p4-sync`).
//!
//! Proves the Phase-4 convergence story end to end on real ports: two devices
//! mutate state **offline**, each stamping `at_ms` via the [`Clock`] port and
//! capturing every mutation through the [`ChangeLog`] out-port
//! (`InMemoryChangeLog`); on reconnect the core [`reconcile`] merges them to an
//! identical, conflict-resolved view (eventual consistency, no central lock).

use agistack_adapters_mem::{FixedClock, InMemoryChangeLog};
use agistack_core::ports::{ChangeEvent, ChangeLog, Clock};
use agistack_core::sync::{reconcile, Replica};

/// A device = a sync replica + its local change-capture log + a clock.
struct Device {
    replica: Replica,
    changelog: InMemoryChangeLog,
    clock: FixedClock,
}

impl Device {
    fn new(id: &str, now_ms: i64) -> Self {
        Self {
            replica: Replica::new(id),
            changelog: InMemoryChangeLog::new(),
            clock: FixedClock(now_ms),
        }
    }

    /// Apply a local (offline) write: stamp time from the Clock port, capture it
    /// through the ChangeLog out-port, and fold it into the sync replica.
    async fn write(&mut self, entity: &str, id: &str, op: &str, version: u32) {
        let event = ChangeEvent {
            entity: entity.into(),
            entity_id: id.into(),
            op: op.into(),
            version,
            at_ms: self.clock.now_ms(),
        };
        self.changelog.record(event.clone()).await.unwrap();
        self.replica.apply_local(event);
    }
}

#[test]
fn two_devices_offline_then_resync_converge() {
    futures::executor::block_on(async {
        // Device B's clock is later, to exercise LWW time tiebreaks.
        let mut phone = Device::new("phone", 1_000);
        let mut laptop = Device::new("laptop", 2_000);

        // Shared baseline created on the phone, synced once.
        phone.write("memory", "m1", "create", 1).await;
        reconcile(&mut phone.replica, &mut laptop.replica);
        assert_eq!(phone.replica.view(), laptop.replica.view());

        // Go offline: divergent edits, including a conflict on m1.
        phone.write("memory", "m2", "create", 1).await;
        phone.write("memory", "m1", "update", 2).await; // higher version
        laptop.write("memory", "m3", "create", 1).await;
        laptop.write("memory", "m1", "update", 1).await; // later time, lower version

        // Each ChangeLog captured exactly its own local mutations (capture seam).
        assert_eq!(phone.changelog.events().unwrap().len(), 3); // m1.create, m2, m1.update
        assert_eq!(laptop.changelog.events().unwrap().len(), 2); // m3, m1.update

        // Reconnect -> converge.
        reconcile(&mut phone.replica, &mut laptop.replica);

        let pv = phone.replica.view();
        let lv = laptop.replica.view();
        assert_eq!(pv, lv, "devices converge to identical state");
        assert_eq!(pv.len(), 3, "m1, m2, m3 all present");
        // Conflict on m1 resolved to the higher version (phone's v2).
        assert_eq!(pv[&("memory".into(), "m1".into())].version, 2);
    });
}

#[test]
fn resync_after_convergence_is_a_noop() {
    futures::executor::block_on(async {
        let mut a = Device::new("a", 10);
        let mut b = Device::new("b", 20);
        a.write("entity", "e1", "create", 1).await;
        b.write("entity", "e2", "create", 1).await;
        reconcile(&mut a.replica, &mut b.replica);
        let snapshot = a.replica.view();

        // Nothing new happened -> the next reconnect ships no deltas.
        assert!(a.replica.delta_since(b.replica.version_vector()).is_empty());
        reconcile(&mut a.replica, &mut b.replica);
        assert_eq!(a.replica.view(), snapshot, "no churn on a quiet resync");
    });
}
