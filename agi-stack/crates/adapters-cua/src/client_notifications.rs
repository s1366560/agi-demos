//! Lossy input updates are isolated from loss-intolerant lifecycle receipts.
use super::*;

impl Connection {
    pub(super) async fn notification(
        &self,
        value: &Value,
        native_status: &broadcast::Sender<crate::CuaNativeStatus>,
    ) -> bool {
        if value["jsonrpc"] == "2.0" && value["method"] == "native_input_telemetry" {
            // Presentation is lossy and never blocks or invalidates lifecycle receipts.
            if let Ok(event) =
                serde_json::from_value::<crate::CuaInputTelemetry>(value["params"].clone())
            {
                let active = self
                    .sessions
                    .lock()
                    .await
                    .get(&event.context.session_id)
                    .is_some_and(|(context, _)| context == &event.context);
                let generations = self.generations.lock().await;
                let current = generations
                    .get(&event.context.session_id)
                    .is_some_and(|generation| generation == &event.input_generation);
                if event.valid() && active && current {
                    let mut sequences = self.input_sequences.lock().await;
                    let fresh = sequences.get(&event.context.session_id).is_none_or(
                        |(generation, sequence)| {
                            generation != &event.input_generation || event.sequence > *sequence
                        },
                    );
                    if fresh {
                        sequences.insert(
                            event.context.session_id.clone(),
                            (event.input_generation.clone(), event.sequence),
                        );
                        self.input_telemetry.send_modify(|latest| {
                            latest.insert(event.context.session_id.clone(), event);
                        });
                    }
                }
            }
            return true;
        }
        let event = value
            .get("params")
            .cloned()
            .and_then(|params| serde_json::from_value::<crate::CuaNativeStatus>(params).ok());
        let valid = if let Some(event) = event.as_ref() {
            let active = self
                .sessions
                .lock()
                .await
                .get(&event.context.session_id)
                .is_some_and(|(context, _)| context == &event.context);
            let closed = !active
                && self
                    .closed_sessions
                    .lock()
                    .await
                    .get(&event.context.session_id)
                    .is_some_and(|(context, _)| context == &event.context);
            value["jsonrpc"] == "2.0"
                && value["method"] == "native_status"
                && event.valid()
                && (active || closed)
        } else {
            false
        };
        if !valid {
            return false;
        }
        if let Some(event) = event {
            let _ = native_status.send(event);
        }
        true
    }
}
