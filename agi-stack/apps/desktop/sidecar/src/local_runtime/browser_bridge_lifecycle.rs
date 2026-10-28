//! A stopped bridge generation cannot retain upgraded sockets or authority.
use super::{BridgeNotification, BrowserBridgeServer};
use serde_json::json;
use std::sync::atomic::Ordering;

impl BrowserBridgeServer {
    pub(super) fn is_stopped(&self) -> bool {
        *self.shutdown.borrow()
    }

    pub(super) fn stop(&self) {
        let sessions = {
            let mut sessions = self.backends.lock().expect("browser bridge backends");
            self.shutdown.send_replace(true);
            sessions
                .drain()
                .map(|(_, session)| session)
                .collect::<Vec<_>>()
        };
        for session in sessions {
            session.closed.store(true, Ordering::SeqCst);
            session.notify_closed.notify_one();
            session.fail_waiters("browser bridge stopped");
            let _ = self.notifications.send(BridgeNotification {
                method: "onBrowserDisconnected".into(),
                params: json!({ "backend": session.browser_id }),
            });
        }
    }
}
