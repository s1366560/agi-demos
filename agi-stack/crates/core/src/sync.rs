//! Local-first sync reconcile — the Phase 4 data-plane convergence algorithm
//! (`05-roadmap.md` §1 Phase 4, `08-control-data-plane-separation.md` §7).
//!
//! This is the *payload* counterpart to the config control/data-plane split:
//! where [`crate::ports::ChangeLog`] captures local mutations, this module is
//! what makes two replicas that mutated **offline** converge to the same state
//! after they reconnect — with no central lock and no global transaction, i.e.
//! **eventual consistency as a feature, not a defect** (08 §7).
//!
//! Model: a set of **LWW-registers** keyed by `(entity, entity_id)`. Each local
//! write is a [`SyncRecord`] tagged with its originating `replica_id` and a
//! per-replica monotonic `seq`, so peers can (a) ship only what the other lacks
//! via a [`VersionVector`] delta, and (b) deterministically resolve conflicts.
//!
//! Convergence guarantee: the winner for a key is the maximum under the total
//! order `(version, at_ms, replica_id, seq)`. Because `(replica_id, seq)` is
//! globally unique, no two distinct records ever tie, so the order is *total* —
//! which makes [`Replica::merge`] **commutative, associative, and idempotent**
//! (the CRDT LWW-register laws). Reconcile order therefore cannot change the
//! outcome.
//!
//! Portability: pure data + `BTreeMap`; no tokio, no `std::time` (timestamps
//! arrive in [`ChangeEvent::at_ms`], filled by the host's injected
//! [`crate::ports::Clock`]). Compiles unchanged to `wasm32`, iOS and Android.

use std::collections::BTreeMap;

use crate::ports::ChangeEvent;

/// A [`ChangeEvent`] tagged with its origin replica and a per-replica monotonic
/// sequence number. `(replica_id, seq)` is the globally-unique identity used for
/// dedupe, version-vector deltas, and the final convergence tiebreak.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncRecord {
    pub replica_id: String,
    pub seq: u64,
    pub event: ChangeEvent,
}

/// Per-replica high-water mark: `replica_id -> highest seq observed`. Two
/// replicas exchange these to compute exactly which records the other is
/// missing (delta-sync), instead of shipping the whole log every time.
pub type VersionVector = BTreeMap<String, u64>;

fn key(event: &ChangeEvent) -> (String, String) {
    (event.entity.clone(), event.entity_id.clone())
}

/// Total order over records for the same key: `true` iff `a` should win over
/// `b`. Order: higher `version`, then later `at_ms`, then higher `replica_id`,
/// then higher `seq`. The last two make the order total (no ties between
/// distinct records) which is what guarantees deterministic convergence.
fn wins(a: &SyncRecord, b: &SyncRecord) -> bool {
    (
        a.event.version,
        a.event.at_ms,
        a.replica_id.as_str(),
        a.seq,
    ) > (
        b.event.version,
        b.event.at_ms,
        b.replica_id.as_str(),
        b.seq,
    )
}

/// One node's local-first state: a deduped record log plus the version vector of
/// what it has observed. Materialize the conflict-resolved snapshot with
/// [`Replica::view`].
#[derive(Debug, Clone)]
pub struct Replica {
    id: String,
    /// Keyed by `(replica_id, seq)` so re-delivery is automatically deduped and
    /// iteration is deterministic.
    log: BTreeMap<(String, u64), SyncRecord>,
    vv: VersionVector,
    next_seq: u64,
}

impl Replica {
    pub fn new(id: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            log: BTreeMap::new(),
            vv: VersionVector::new(),
            next_seq: 1,
        }
    }

    pub fn id(&self) -> &str {
        &self.id
    }

    /// Record a local (possibly offline) mutation. Assigns this replica's next
    /// `seq` and advances its own version-vector entry.
    pub fn apply_local(&mut self, event: ChangeEvent) -> SyncRecord {
        let seq = self.next_seq;
        self.next_seq += 1;
        let record = SyncRecord {
            replica_id: self.id.clone(),
            seq,
            event,
        };
        self.log.insert((self.id.clone(), seq), record.clone());
        self.bump_vv(&self.id.clone(), seq);
        record
    }

    /// Records this replica holds that a peer described by `their_vv` has not yet
    /// seen — the minimal delta to send on reconnect.
    pub fn delta_since(&self, their_vv: &VersionVector) -> Vec<SyncRecord> {
        self.log
            .values()
            .filter(|r| r.seq > their_vv.get(&r.replica_id).copied().unwrap_or(0))
            .cloned()
            .collect()
    }

    /// Merge foreign records. Idempotent (dedup by `(replica_id, seq)`) and
    /// commutative (order-independent), so applying the same delta twice — or in
    /// any order — yields the same state.
    pub fn merge(&mut self, incoming: &[SyncRecord]) {
        for r in incoming {
            self.bump_vv(&r.replica_id, r.seq);
            self.log
                .entry((r.replica_id.clone(), r.seq))
                .or_insert_with(|| r.clone());
        }
    }

    /// The conflict-resolved snapshot: `(entity, entity_id) -> winning event`.
    pub fn view(&self) -> BTreeMap<(String, String), ChangeEvent> {
        let mut winners: BTreeMap<(String, String), SyncRecord> = BTreeMap::new();
        for r in self.log.values() {
            winners
                .entry(key(&r.event))
                .and_modify(|cur| {
                    if wins(r, cur) {
                        *cur = r.clone();
                    }
                })
                .or_insert_with(|| r.clone());
        }
        winners
            .into_iter()
            .map(|(k, r)| (k, r.event))
            .collect()
    }

    pub fn version_vector(&self) -> &VersionVector {
        &self.vv
    }

    fn bump_vv(&mut self, replica_id: &str, seq: u64) {
        let entry = self.vv.entry(replica_id.to_string()).or_insert(0);
        if seq > *entry {
            *entry = seq;
        }
    }
}

/// Bidirectional reconcile: each side ships only the delta the other lacks, then
/// merges. After this returns both replicas have identical [`Replica::view`]s
/// (eventual consistency). Pure and synchronous — the transport lives outside
/// the core (direct call, channel, or HTTP in an adapter).
pub fn reconcile(a: &mut Replica, b: &mut Replica) {
    let to_b = a.delta_since(b.version_vector());
    let to_a = b.delta_since(a.version_vector());
    b.merge(&to_b);
    a.merge(&to_a);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ev(entity: &str, id: &str, op: &str, version: u32, at_ms: i64) -> ChangeEvent {
        ChangeEvent {
            entity: entity.into(),
            entity_id: id.into(),
            op: op.into(),
            version,
            at_ms,
        }
    }

    #[test]
    fn offline_divergence_then_reconnect_converges() {
        let mut a = Replica::new("A");
        let mut b = Replica::new("B");

        // Both start from a shared baseline write (as if synced once before).
        let base = ev("memory", "m1", "create", 1, 100);
        let r = a.apply_local(base.clone());
        b.merge(&[r]);

        // Go offline: each edits different entities.
        a.apply_local(ev("memory", "m2", "create", 1, 200));
        b.apply_local(ev("memory", "m3", "create", 1, 210));

        // Reconnect.
        reconcile(&mut a, &mut b);

        assert_eq!(a.view(), b.view(), "replicas must converge");
        assert_eq!(a.view().len(), 3, "all three memories present on both sides");
    }

    #[test]
    fn conflicting_write_resolved_by_lww_version_then_time() {
        let mut a = Replica::new("A");
        let mut b = Replica::new("B");

        // Same key m1 edited on both sides while offline.
        a.apply_local(ev("memory", "m1", "update", 2, 300)); // higher version
        b.apply_local(ev("memory", "m1", "update", 1, 999)); // later time, lower version

        reconcile(&mut a, &mut b);

        let win = &a.view()[&("memory".to_string(), "m1".to_string())];
        assert_eq!(win.version, 2, "higher version wins regardless of at_ms");
        assert_eq!(a.view(), b.view());

        // Tie on version -> later at_ms wins.
        let mut c = Replica::new("C");
        let mut d = Replica::new("D");
        c.apply_local(ev("memory", "x", "update", 5, 100));
        d.apply_local(ev("memory", "x", "update", 5, 400));
        reconcile(&mut c, &mut d);
        assert_eq!(c.view()[&("memory".into(), "x".into())].at_ms, 400);
        assert_eq!(c.view(), d.view());
    }

    #[test]
    fn merge_is_commutative_regardless_of_order() {
        let mk = || {
            let mut a = Replica::new("A");
            let mut b = Replica::new("B");
            a.apply_local(ev("memory", "m1", "update", 3, 10));
            b.apply_local(ev("memory", "m1", "update", 2, 99));
            b.apply_local(ev("memory", "m2", "create", 1, 50));
            (a, b)
        };

        // Order 1: a<-b then b<-a (via reconcile).
        let (mut a1, mut b1) = mk();
        reconcile(&mut a1, &mut b1);

        // Order 2: manual reverse delta application.
        let (mut a2, mut b2) = mk();
        let to_a = b2.delta_since(a2.version_vector());
        let to_b = a2.delta_since(b2.version_vector());
        a2.merge(&to_a);
        b2.merge(&to_b);

        assert_eq!(a1.view(), a2.view(), "merge order must not matter");
        assert_eq!(a1.view(), b1.view());
        assert_eq!(a2.view(), b2.view());
    }

    #[test]
    fn reconcile_is_idempotent_no_churn() {
        let mut a = Replica::new("A");
        let mut b = Replica::new("B");
        a.apply_local(ev("memory", "m1", "create", 1, 1));
        b.apply_local(ev("memory", "m2", "create", 1, 2));

        reconcile(&mut a, &mut b);
        let a_after = a.view();
        let log_len = a.log.len();

        // Reconnect again with nothing new — must be a no-op delta.
        assert!(a.delta_since(b.version_vector()).is_empty());
        assert!(b.delta_since(a.version_vector()).is_empty());
        reconcile(&mut a, &mut b);
        assert_eq!(a.view(), a_after, "second reconcile changes nothing");
        assert_eq!(a.log.len(), log_len, "no duplicate records");
    }

    #[test]
    fn version_vector_ships_only_missing_records() {
        let mut a = Replica::new("A");
        let mut b = Replica::new("B");
        a.apply_local(ev("memory", "m1", "create", 1, 1));
        reconcile(&mut a, &mut b); // b now knows A:1

        a.apply_local(ev("memory", "m2", "create", 1, 2)); // A:2 only

        let delta = a.delta_since(b.version_vector());
        assert_eq!(delta.len(), 1, "only the unseen A:2 is shipped");
        assert_eq!(delta[0].seq, 2);
    }

    #[test]
    fn three_replicas_converge_via_pairwise_gossip() {
        let mut a = Replica::new("A");
        let mut b = Replica::new("B");
        let mut c = Replica::new("C");
        a.apply_local(ev("memory", "m1", "update", 1, 10));
        b.apply_local(ev("memory", "m1", "update", 2, 20)); // conflicts with A
        c.apply_local(ev("memory", "m2", "create", 1, 30));

        // Gossip pairwise in a ring; one extra round to fully propagate.
        reconcile(&mut a, &mut b);
        reconcile(&mut b, &mut c);
        reconcile(&mut a, &mut c);
        reconcile(&mut a, &mut b);

        assert_eq!(a.view(), b.view());
        assert_eq!(b.view(), c.view());
        // m1 resolved to B's higher version everywhere.
        assert_eq!(a.view()[&("memory".into(), "m1".into())].version, 2);
    }
}
