//! `agistack-adapters-smtp`: the server-tier [`EmailSender`] over `lettre`.
//!
//! This is **F10** of the Python -> Rust strangler migration
//! (`10-production-migration.md` §3): the transactional-email capability the P2
//! invitation flow and P7-G4 notifications depend on. It mirrors the Python SMTP
//! path (`smtp_config`, notification services) — build a MIME message, hand it to
//! an SMTP relay, succeed on the MTA's `250`.
//!
//! `lettre` drags in an async SMTP client (tokio + a TLS stack), so — exactly
//! like `adapters-postgres` / `adapters-http-llm` / `adapters-docker` — this crate
//! is kept OUT of the core/wasm path (ADR-0001). The core only ever sees
//! `dyn EmailSender`; the browser/device tier never sends SMTP.
//!
//! ## Agent First
//! Nothing here is a *judgment*: composing a MIME envelope and delivering it over
//! SMTP is a deterministic protocol operation, explicitly outside the
//! agent-decision boundary.

use async_trait::async_trait;
use lettre::message::header::ContentType;
use lettre::message::{Mailbox, MultiPart};
use lettre::transport::smtp::authentication::Credentials;
use lettre::{AsyncSmtpTransport, AsyncTransport, Message, Tokio1Executor};

use agistack_core::ports::{CoreError, CoreResult, EmailMessage, EmailSender};

/// Sends [`EmailMessage`]s through an SMTP relay.
///
/// Construct with [`SmtpEmailSender::plaintext`] for a local relay / sidecar MTA
/// (no encryption — the common in-cluster and test case, e.g. mailpit) or
/// [`SmtpEmailSender::relay`] for an authenticated TLS submission endpoint.
pub struct SmtpEmailSender {
    transport: AsyncSmtpTransport<Tokio1Executor>,
    default_from: Option<Mailbox>,
}

impl SmtpEmailSender {
    /// Unencrypted transport to `host:port`. Suitable for a trusted local relay
    /// (in-cluster MTA, sidecar, or a mailpit/mailhog sink in tests). Production
    /// submission over the public internet should use [`Self::relay`] instead.
    pub fn plaintext(host: &str, port: u16) -> Self {
        let transport = AsyncSmtpTransport::<Tokio1Executor>::builder_dangerous(host)
            .port(port)
            .build();
        Self { transport, default_from: None }
    }

    /// Authenticated TLS submission relay (implicit TLS / STARTTLS negotiated by
    /// `lettre`), the shape a production `smtp_config` uses.
    pub fn relay(host: &str, username: String, password: String) -> CoreResult<Self> {
        let transport = AsyncSmtpTransport::<Tokio1Executor>::relay(host)
            .map_err(|e| CoreError::Email(e.to_string()))?
            .credentials(Credentials::new(username, password))
            .build();
        Ok(Self { transport, default_from: None })
    }

    /// Set a fallback `From` used when an [`EmailMessage::from`] is empty (mirrors
    /// a configured `MAIL_FROM`). Returns `Self` for builder-style use.
    pub fn with_default_from(mut self, from: &str) -> CoreResult<Self> {
        self.default_from =
            Some(from.parse::<Mailbox>().map_err(|e| CoreError::Email(format!("default from: {e}")))?);
        Ok(self)
    }

    fn build_message(&self, msg: &EmailMessage) -> CoreResult<Message> {
        let from: Mailbox = if msg.from.trim().is_empty() {
            self.default_from
                .clone()
                .ok_or_else(|| CoreError::Email("no from address and no default".into()))?
        } else {
            msg.from.parse().map_err(|e| CoreError::Email(format!("from: {e}")))?
        };

        if msg.to.is_empty() {
            return Err(CoreError::Email("no recipients".into()));
        }

        let mut builder = Message::builder().from(from).subject(msg.subject.clone());
        for to in &msg.to {
            let mbox: Mailbox = to.parse().map_err(|e| CoreError::Email(format!("to {to}: {e}")))?;
            builder = builder.to(mbox);
        }

        let email = match &msg.body_html {
            Some(html) => builder
                .multipart(MultiPart::alternative_plain_html(msg.body_text.clone(), html.clone())),
            None => builder.header(ContentType::TEXT_PLAIN).body(msg.body_text.clone()),
        }
        .map_err(|e| CoreError::Email(e.to_string()))?;

        Ok(email)
    }
}

#[async_trait]
impl EmailSender for SmtpEmailSender {
    async fn send(&self, message: &EmailMessage) -> CoreResult<()> {
        let email = self.build_message(message)?;
        self.transport.send(email).await.map_err(|e| CoreError::Email(e.to_string()))?;
        Ok(())
    }
}
