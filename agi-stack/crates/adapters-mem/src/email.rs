//! In-memory [`EmailSender`] — the test/device tier of the transactional-email
//! port (F10). Records every [`EmailMessage`] it is asked to send instead of
//! touching the network, so it backs unit tests and the wasm build and serves as
//! the behavioural oracle for the `lettre`/SMTP adapter.
//!
//! Email delivery is an I/O side effect (not a value store), so the equivalence
//! the SMTP integration test asserts is **behavioural** — the fake captures
//! exactly the `from`/`to`/`subject`/body a real SMTP send transmits, which the
//! live mailpit inbox then confirms — not byte parity.

use std::sync::Mutex;

use async_trait::async_trait;

use agistack_core::ports::{CoreError, CoreResult, EmailMessage, EmailSender};

/// Process-local email sink: appends each sent [`EmailMessage`] to a `Vec` the
/// test can inspect. Never fails (mirrors a healthy MTA accepting the envelope).
#[derive(Default)]
pub struct InMemoryEmailSender {
    sent: Mutex<Vec<EmailMessage>>,
}

impl InMemoryEmailSender {
    /// A fresh sink with no recorded messages.
    pub fn new() -> Self {
        Self::default()
    }

    /// Snapshot of every message sent so far, in send order.
    pub fn sent(&self) -> CoreResult<Vec<EmailMessage>> {
        Ok(self.sent.lock().map_err(|_| poisoned())?.clone())
    }

    /// Number of messages sent so far.
    pub fn count(&self) -> CoreResult<usize> {
        Ok(self.sent.lock().map_err(|_| poisoned())?.len())
    }
}

fn poisoned() -> CoreError {
    CoreError::Email("poisoned email sink lock".into())
}

#[async_trait]
impl EmailSender for InMemoryEmailSender {
    async fn send(&self, message: &EmailMessage) -> CoreResult<()> {
        self.sent
            .lock()
            .map_err(|_| poisoned())?
            .push(message.clone());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    static PANIC_HOOK_LOCK: Mutex<()> = Mutex::new(());

    fn msg() -> EmailMessage {
        EmailMessage {
            from: "MemStack <no-reply@memstack.ai>".into(),
            to: vec!["alice@example.com".into()],
            subject: "You're invited".into(),
            body_text: "Join the project".into(),
            body_html: Some("<p>Join the project</p>".into()),
        }
    }

    #[test]
    fn records_sent_messages_in_order() {
        let sender = InMemoryEmailSender::new();
        assert_eq!(sender.count().unwrap(), 0);

        block_on(sender.send(&msg())).unwrap();
        let mut second = msg();
        second.subject = "Reminder".into();
        block_on(sender.send(&second)).unwrap();

        let sent = sender.sent().unwrap();
        assert_eq!(sent.len(), 2);
        assert_eq!(sent[0].subject, "You're invited");
        assert_eq!(sent[0].to, vec!["alice@example.com".to_string()]);
        assert_eq!(sent[1].subject, "Reminder");
    }

    #[test]
    fn captures_full_envelope_and_bodies() {
        let sender = InMemoryEmailSender::new();
        block_on(sender.send(&msg())).unwrap();
        let sent = sender.sent().unwrap();
        assert_eq!(sent[0].from, "MemStack <no-reply@memstack.ai>");
        assert_eq!(sent[0].body_text, "Join the project");
        assert_eq!(
            sent[0].body_html.as_deref(),
            Some("<p>Join the project</p>")
        );
    }

    #[test]
    fn poisoned_lock_returns_email_error() {
        let sender = InMemoryEmailSender::new();
        let _panic_hook_guard = PANIC_HOOK_LOCK.lock().unwrap();
        let old_hook = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = sender.sent.lock().unwrap();
            panic!("poison email sink mutex");
        }));
        std::panic::set_hook(old_hook);
        assert!(result.is_err());

        let err = block_on(sender.send(&msg())).unwrap_err();
        assert!(matches!(
            err,
            CoreError::Email(message) if message == "poisoned email sink lock"
        ));
    }
}
