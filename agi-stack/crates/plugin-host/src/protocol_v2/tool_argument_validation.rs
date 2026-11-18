//! Schema work runs outside the native executor's nested tool/future stack.

use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};

use serde_json::Value;

use super::RuntimeV2Error;

#[derive(Clone, Default)]
pub(super) struct ToolArgumentValidator {
    // Scoped to the policy generation. Argument values are never cached.
    schemas: Arc<Mutex<BTreeMap<String, Arc<jsonschema::Validator>>>>,
}

impl ToolArgumentValidator {
    pub(super) async fn is_valid(
        &self,
        schema: Option<&Value>,
        arguments: &Value,
    ) -> Result<bool, RuntimeV2Error> {
        let Some(schema) = schema else {
            return Ok(arguments.is_object());
        };
        #[cfg(target_arch = "wasm32")]
        {
            self.validate_schema(schema, arguments)
        }
        #[cfg(not(target_arch = "wasm32"))]
        {
            let validator = self.clone();
            let schema = schema.clone();
            let arguments = arguments.clone();
            let (send, receive) = futures::channel::oneshot::channel();
            worker()?
                .try_send(Box::new(move || {
                    if !send.is_canceled() {
                        let _ = send.send(validator.validate_schema(&schema, &arguments));
                    }
                }))
                .map_err(|_| invalid("tool schema validation is unavailable"))?;
            receive
                .await
                .map_err(|_| invalid("tool schema validation is unavailable"))?
        }
    }

    fn validate_schema(&self, schema: &Value, arguments: &Value) -> Result<bool, RuntimeV2Error> {
        let key = schema.to_string();
        let validator = {
            let mut schemas = self
                .schemas
                .lock()
                .map_err(|_| invalid("tool schema validation is unavailable"))?;
            if let Some(validator) = schemas.get(&key) {
                validator.clone()
            } else {
                let validator = Arc::new(
                    jsonschema::draft202012::new(schema)
                        .map_err(|_| invalid("invalid tool input schema"))?,
                );
                // A generation may declare many dynamic tools; cap retained
                // compiled schemas without ever skipping their validation.
                if schemas.len() < 256 {
                    schemas.insert(key, validator.clone());
                }
                validator
            }
        };
        Ok(arguments.is_object() && validator.is_valid(arguments))
    }
}

fn invalid(message: &str) -> RuntimeV2Error {
    RuntimeV2Error::Module(message.into())
}

#[cfg(not(target_arch = "wasm32"))]
type ValidationJob = Box<dyn FnOnce() + Send>;

#[cfg(not(target_arch = "wasm32"))]
fn worker() -> Result<&'static std::sync::mpsc::SyncSender<ValidationJob>, RuntimeV2Error> {
    use std::sync::{mpsc, OnceLock};
    static WORKER: OnceLock<Result<mpsc::SyncSender<ValidationJob>, ()>> = OnceLock::new();
    WORKER
        .get_or_init(|| {
            let (send, receive) = mpsc::sync_channel::<ValidationJob>(64);
            std::thread::Builder::new()
                .name("tool-schema-validation".into())
                .spawn(move || {
                    for job in receive {
                        // An unexpected validator panic closes that job's response but
                        // must not strand other requests or expose their private data.
                        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(job));
                    }
                })
                .map_err(|_| ())?;
            Ok(send)
        })
        .as_ref()
        .map_err(|_| invalid("tool schema validation is unavailable"))
}

#[cfg(all(test, not(target_arch = "wasm32")))]
mod tests {
    use super::ToolArgumentValidator;
    use futures::executor::block_on;
    use serde_json::json;

    #[test]
    fn unavailable_validator_is_a_hard_error_even_for_invalid_arguments() {
        let validator = ToolArgumentValidator::default();
        let schemas = validator.schemas.clone();
        let poison = std::thread::spawn(move || {
            let _guard = schemas.lock().unwrap();
            panic!("simulate an interrupted schema cache update");
        });
        assert!(poison.join().is_err());
        let schema = json!({"type":"object","required":["path"]});
        assert!(block_on(validator.is_valid(Some(&schema), &json!({}))).is_err());
    }
}
