//! Stable read-only generation snapshots for synchronous status presentation.
use std::{collections::BTreeMap, sync::Mutex};

#[derive(Default)]
pub(super) struct Bindings(Mutex<BTreeMap<String, (String, String)>>);

impl Bindings {
    pub(super) fn current(&self, session: &str) -> Option<String> {
        self.0
            .lock()
            .ok()?
            .get(session)
            .map(|(_, generation)| generation.clone())
    }
    pub(super) fn set(&self, connection: &str, session: &str, generation: &str) {
        self.0
            .lock()
            .expect("native input bindings")
            .insert(session.into(), (connection.into(), generation.into()));
    }
    pub(super) fn remove_session(&self, connection: &str, session: &str) {
        let mut bindings = self.0.lock().expect("native input bindings");
        if bindings
            .get(session)
            .is_some_and(|(owner, _)| owner == connection)
        {
            bindings.remove(session);
        }
    }
    pub(super) fn remove_connection(&self, connection: &str) -> BTreeMap<String, String> {
        let mut bindings = self.0.lock().expect("native input bindings");
        let removed = bindings
            .iter()
            .filter(|(_, (owner, _))| owner == connection)
            .map(|(session, (_, generation))| (session.clone(), generation.clone()))
            .collect();
        bindings.retain(|_, (owner, _)| owner != connection);
        removed
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn retiring_an_old_helper_cannot_clear_a_replacement_binding() {
        let bindings = Bindings::default();
        bindings.set("old-helper", "session", "first-generation");
        bindings.set("new-helper", "session", "second-generation");
        assert!(bindings.remove_connection("old-helper").is_empty());
        bindings.remove_session("old-helper", "session");
        assert_eq!(
            bindings.current("session").as_deref(),
            Some("second-generation")
        );
        let removed = bindings.remove_connection("new-helper");
        assert_eq!(removed["session"], "second-generation");
        assert!(bindings.current("session").is_none());
    }
}
