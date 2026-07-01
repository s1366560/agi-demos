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

use agistack_core::ports::{CoreResult, EmailMessage, EmailSender};

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
    pub fn sent(&self) -> Vec<EmailMessage> {
        self.sent.lock().expect("email sink mutex").clone()
    }

    /// Number of messages sent so far.
    pub fn count(&self) -> usize {
        self.sent.lock().expect("email sink mutex").len()
    }
}

#[async_trait]
impl EmailSender for InMemoryEmailSender {
    async fn send(&self, message: &EmailMessage) -> CoreResult<()> {
        self.sent.lock().expect("email sink mutex").push(message.clone());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

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
        assert_eq!(sender.count(), 0);

        block_on(sender.send(&msg())).unwrap();
        let mut second = msg();
        second.subject = "Reminder".into();
        block_on(sender.send(&second)).unwrap();

        let sent = sender.sent();
        assert_eq!(sent.len(), 2);
        assert_eq!(sent[0].subject, "You're invited");
        assert_eq!(sent[0].to, vec!["alice@example.com".to_string()]);
        assert_eq!(sent[1].subject, "Reminder");
    }

    #[test]
    fn captures_full_envelope_and_bodies() {
        let sender = InMemoryEmailSender::new();
        block_on(sender.send(&msg())).unwrap();
        let sent = sender.sent();
        assert_eq!(sent[0].from, "MemStack <no-reply@memstack.ai>");
        assert_eq!(sent[0].body_text, "Join the project");
        assert_eq!(sent[0].body_html.as_deref(), Some("<p>Join the project</p>"));
    }
}
