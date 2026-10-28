//! Prioritized control output with bounded, coalesced input telemetry.
use serde_json::Value;
use std::{collections::BTreeMap, time::Duration};
use tokio::{
    io::{AsyncWrite, AsyncWriteExt},
    sync::{mpsc, watch},
};

pub(super) async fn run<W: AsyncWrite + Unpin>(
    mut output: W,
    mut controls: mpsc::Receiver<Value>,
    input: watch::Receiver<BTreeMap<String, Value>>,
) -> Result<(), String> {
    let mut sent = BTreeMap::new();
    let mut tick = tokio::time::interval(Duration::from_millis(16));
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        let value = tokio::select! {
            biased;
            value = controls.recv() => match value { Some(value) => value, None => return Ok(()) },
            _ = tick.tick() => {
                let latest = input.borrow().clone();
                sent.retain(|id, _| latest.contains_key(id));
                let Some((id, event)) = latest.iter().find(|(id, event)| {
                    sent.get(*id) != Some(&(event["input_generation"].clone(), event["sequence"].clone()))
                }) else { continue; };
                sent.insert(id.clone(), (event["input_generation"].clone(), event["sequence"].clone()));
                serde_json::json!({"type":"computer_use_input","input":event})
            }
        };
        let mut bytes = serde_json::to_vec(&value).map_err(|error| error.to_string())?;
        bytes.push(b'\n');
        // A partial frame cannot be skipped safely. Terminate this transport on timeout;
        // its owner releases all native resources before allowing a replacement.
        tokio::time::timeout(Duration::from_millis(250), async {
            output.write_all(&bytes).await?;
            output.flush().await
        })
        .await
        .map_err(|_| "sidecar control output timed out".to_owned())?
        .map_err(|error| format!("sidecar control output failed: {error}"))?;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncBufReadExt, BufReader};

    #[tokio::test]
    async fn control_receipts_precede_latest_input_and_a_slow_reader_is_bounded() {
        let (writer, reader) = tokio::io::duplex(4096);
        let (controls, rx) = mpsc::channel(4);
        let (input, input_rx) = watch::channel(BTreeMap::new());
        input.send_replace(BTreeMap::from([(
            "session".into(),
            serde_json::json!({"input_generation":"g","sequence":99}),
        )]));
        controls
            .send(serde_json::json!({"type":"response","id":"stop"}))
            .await
            .unwrap();
        let task = tokio::spawn(run(writer, rx, input_rx));
        let mut reader = BufReader::new(reader).lines();
        let first: Value =
            serde_json::from_str(&reader.next_line().await.unwrap().unwrap()).unwrap();
        assert_eq!(first["id"], "stop");
        let second: Value =
            serde_json::from_str(&reader.next_line().await.unwrap().unwrap()).unwrap();
        assert_eq!(second["input"]["sequence"], 99);
        drop(controls);
        task.await.unwrap().unwrap();
        let (writer, _unread) = tokio::io::duplex(1);
        let (controls, rx) = mpsc::channel(1);
        let (_, input_rx) = watch::channel(BTreeMap::new());
        controls
            .send(serde_json::json!({"type":"response"}))
            .await
            .unwrap();
        let error = tokio::time::timeout(Duration::from_secs(1), run(writer, rx, input_rx))
            .await
            .unwrap()
            .unwrap_err();
        assert_eq!(error, "sidecar control output timed out");
    }
}
