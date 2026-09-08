//! Test-only JSON-lines probe used by the Python/Rust differential suite.

use agistack_core::project_schema::{ProjectSchemaDocument, ProjectSchemaError};
use serde_json::{json, Value};
use std::io::{self, BufRead};

fn evaluate(case: &Value) -> Result<Value, ProjectSchemaError> {
    let document = &case["document"];
    let raw = document
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| document.to_string());
    let parsed = ProjectSchemaDocument::from_json(&raw)?;
    if let Some(previous) = case.get("previous") {
        let previous = if previous.is_null() {
            None
        } else {
            Some(ProjectSchemaDocument::from_json(&previous.to_string())?)
        };
        let expected = case["expected_revision"]
            .as_u64()
            .and_then(|number| u32::try_from(number).ok())
            .ok_or(ProjectSchemaError::RevisionConflict)?;
        parsed.validate_successor(previous.as_ref(), expected)?;
    }
    Ok(parsed.to_value())
}

fn main() {
    for line in io::stdin().lock().lines() {
        let case: Value =
            serde_json::from_str(&line.expect("probe input line")).expect("probe case");
        let result = match evaluate(&case) {
            Ok(document) => json!({"valid":true,"document":document}),
            Err(error) => json!({"valid":false,"code":error.to_string()}),
        };
        println!("{result}");
    }
}
