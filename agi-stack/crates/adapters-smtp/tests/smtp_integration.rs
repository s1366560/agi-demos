//! Live conformance test for the F10 `EmailSender` SMTP adapter.
//!
//! Gated on a reachable SMTP relay + mailpit HTTP API (defaults: SMTP
//! `localhost:1025`, API `http://localhost:8025`; override with
//! `AGISTACK_SMTP_PORT` / `AGISTACK_MAILPIT_URL`). When nothing is listening the
//! test prints `[skip]` and returns, so an offline `cargo test --workspace` stays
//! green — the same environment-gated pattern as the Docker (F9) and Postgres
//! (F1) integration tests.
//!
//! When a sink is present it proves the real path end to end: build a MIME
//! message, deliver it over SMTP via `lettre`, then read it back out of the
//! mailpit inbox over HTTP and assert the delivered envelope + both body parts
//! match — and that the in-memory `EmailSender` oracle recorded exactly the same
//! envelope (behavioural parity between the two tiers).

use std::time::{Duration, SystemTime, UNIX_EPOCH};

use agistack_adapters_mem::InMemoryEmailSender;
use agistack_adapters_smtp::SmtpEmailSender;
use agistack_core::ports::{EmailMessage, EmailSender};

const SMTP_HOST: &str = "localhost";

fn smtp_port() -> u16 {
    std::env::var("AGISTACK_SMTP_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(1025)
}

fn api_base() -> String {
    std::env::var("AGISTACK_MAILPIT_URL").unwrap_or_else(|_| "http://localhost:8025".into())
}

#[tokio::test(flavor = "multi_thread")]
async fn sends_through_real_smtp_and_arrives_in_mailpit() {
    let client = reqwest::Client::new();
    let base = api_base();
    let list_url = format!("{base}/api/v1/messages");

    // Gate: is a mailpit sink reachable? If not, skip (offline stays green).
    match client.get(&list_url).send().await {
        Ok(r) if r.status().is_success() => {}
        _ => {
            eprintln!("[skip] mailpit API not reachable at {base}; skipping F10 live test");
            return;
        }
    }

    // Start from an empty inbox so our poll can't match a stale message.
    let _ = client.delete(&list_url).send().await;

    // Unique subject so we can find exactly our message in the inbox.
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let subject = format!("agistack F10 invite {nanos}");

    let msg = EmailMessage {
        from: "MemStack <no-reply@memstack.ai>".into(),
        to: vec!["alice@example.com".into()],
        subject: subject.clone(),
        body_text: "You have been invited to the project. Join the project.".into(),
        body_html: Some("<p>You have been invited. <b>Join the project.</b></p>".into()),
    };

    // Behavioural oracle: the in-memory tier records exactly the envelope a real
    // SMTP send transmits.
    let oracle = InMemoryEmailSender::new();
    oracle.send(&msg).await.unwrap();
    assert_eq!(oracle.sent().unwrap()[0], msg);

    // Real delivery over SMTP.
    let sender = SmtpEmailSender::plaintext(SMTP_HOST, smtp_port());
    sender
        .send(&msg)
        .await
        .expect("SMTP send should be accepted (250)");

    // Poll the inbox until our uniquely-subjected message shows up.
    let mut found: Option<serde_json::Value> = None;
    for _ in 0..20 {
        let list: serde_json::Value = client
            .get(&list_url)
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        if let Some(arr) = list["messages"].as_array() {
            if let Some(m) = arr
                .iter()
                .find(|m| m["Subject"] == serde_json::json!(subject))
            {
                found = Some(m.clone());
                break;
            }
        }
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
    let m = found.expect("the sent message should arrive in mailpit");

    // Envelope conformance: subject, recipient, sender as delivered by the relay.
    assert_eq!(m["Subject"], serde_json::json!(subject));
    let to_addr = m["To"][0]["Address"].as_str().expect("To address");
    assert_eq!(to_addr, "alice@example.com");
    let from_addr = m["From"]["Address"].as_str().expect("From address");
    assert_eq!(from_addr, "no-reply@memstack.ai");

    // Body conformance: fetch the full message and assert both alternative parts
    // carried through.
    let id = m["ID"].as_str().expect("message id");
    let full: serde_json::Value = client
        .get(format!("{base}/api/v1/message/{id}"))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert!(full["Text"]
        .as_str()
        .unwrap_or_default()
        .contains("Join the project"));
    assert!(full["HTML"]
        .as_str()
        .unwrap_or_default()
        .contains("Join the project"));

    // Cross-tier behavioural parity: what mailpit actually received matches what
    // the in-memory oracle recorded.
    let sent = oracle.sent().unwrap();
    assert_eq!(sent[0].to[0], to_addr);
    assert_eq!(sent[0].subject, subject);

    // Hermetic: leave the inbox as we found it.
    let _ = client.delete(&list_url).send().await;
}
