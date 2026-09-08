use super::{
    ProjectSchemaError, RawDocument, MAX_DOCUMENT_BYTES, MAX_MEMBERS, MAX_REVISION,
    MAX_SAFE_NUMBER, MAX_SCHEMA_DEPTH, MAX_SCHEMA_NODES, MAX_SCHEMA_TEXT_BYTES,
};
use serde_json::Value;
use std::collections::BTreeSet;

fn require(condition: bool) -> Result<(), ProjectSchemaError> {
    if condition {
        Ok(())
    } else {
        Err(ProjectSchemaError::InvalidDocument)
    }
}

fn uuid(value: &str) -> Result<(), ProjectSchemaError> {
    require(
        value.len() == 36
            && value != "00000000-0000-0000-0000-000000000000"
            && value.bytes().enumerate().all(|(i, b)| {
                if [8, 13, 18, 23].contains(&i) {
                    b == b'-'
                } else {
                    b.is_ascii_digit() || (b'a'..=b'f').contains(&b)
                }
            }),
    )
}

fn text(value: &str, max: usize, nonempty: bool) -> Result<(), ProjectSchemaError> {
    require((!nonempty || !value.is_empty()) && value.len() <= max && !value.contains('\0'))
}

pub(super) fn validate(value: &RawDocument) -> Result<(), ProjectSchemaError> {
    require(value.format_version == 1 && (1..=MAX_REVISION).contains(&value.revision))?;
    for id in [&value.tenant_id, &value.project_id] {
        text(id, 512, true)?;
        require(id.trim_matches([' ', '\t', '\r', '\n']) == id)?;
    }
    uuid(&value.schema_id)?;
    let live_count = value.entity_types.len() + value.edge_types.len() + value.mappings.len();
    require(live_count + value.tombstones.len() <= MAX_MEMBERS)?;
    require(!value.deleted || live_count == 0)?;
    let mut ids = BTreeSet::from([value.schema_id.as_str()]);
    for member in value.entity_types.iter().chain(&value.edge_types) {
        uuid(&member.id)?;
        require(ids.insert(&member.id))?;
        text(&member.name, 512, true)?;
        text(&member.description, 4_096, false)?;
        text(&member.source, 128, true)?;
        require(member.schema.is_object())?;
        visit_schema(&member.schema, 0, &mut 0, &mut 0)?;
    }
    let entities: BTreeSet<_> = value.entity_types.iter().map(|m| m.id.as_str()).collect();
    let edges: BTreeSet<_> = value.edge_types.iter().map(|m| m.id.as_str()).collect();
    for member in &value.mappings {
        uuid(&member.id)?;
        require(ids.insert(&member.id))?;
        text(&member.source, 128, true)?;
        for (id, allowed) in [
            (&member.source_type_id, &entities),
            (&member.target_type_id, &entities),
            (&member.edge_type_id, &edges),
        ] {
            uuid(id)?;
            require(allowed.contains(id.as_str()))?;
        }
    }
    for item in &value.tombstones {
        uuid(&item.id)?;
        require(ids.insert(&item.id))?;
        require((1..=value.revision).contains(&item.deleted_revision))?;
    }
    let json = serde_json::to_value(value).map_err(|_| ProjectSchemaError::InvalidDocument)?;
    require(document_weight(&json) <= MAX_DOCUMENT_BYTES)
}

fn visit_schema(
    value: &Value,
    depth: usize,
    nodes: &mut usize,
    text_bytes: &mut usize,
) -> Result<(), ProjectSchemaError> {
    *nodes += 1;
    require(*nodes <= MAX_SCHEMA_NODES && depth <= MAX_SCHEMA_DEPTH)?;
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                require(!key.contains('\0'))?;
                *text_bytes += key.len();
                visit_schema(child, depth + 1, nodes, text_bytes)?;
            }
        }
        Value::Array(items) => {
            for child in items {
                visit_schema(child, depth + 1, nodes, text_bytes)?;
            }
        }
        Value::String(text) => {
            require(!text.contains('\0'))?;
            *text_bytes += text.len();
        }
        Value::Number(number) => {
            require(
                number
                    .as_f64()
                    .is_some_and(|n| n.is_finite() && n.abs() <= MAX_SAFE_NUMBER),
            )?;
        }
        Value::Bool(_) | Value::Null => {}
    }
    require(*text_bytes <= MAX_SCHEMA_TEXT_BYTES)
}

fn string_weight(text: &str) -> usize {
    2 + text
        .bytes()
        .map(|byte| match byte {
            8 | 9 | 10 | 12 | 13 | 34 | 92 => 2,
            0..=31 => 6,
            _ => 1,
        })
        .sum::<usize>()
}

fn document_weight(value: &Value) -> usize {
    match value {
        Value::Object(map) => {
            2 + map.len().saturating_sub(1)
                + map
                    .iter()
                    .map(|(key, child)| string_weight(key) + 1 + document_weight(child))
                    .sum::<usize>()
        }
        Value::Array(items) => {
            2 + items.len().saturating_sub(1) + items.iter().map(document_weight).sum::<usize>()
        }
        Value::String(text) => string_weight(text),
        Value::Number(_) => 32,
        Value::Bool(false) => 5,
        Value::Bool(true) | Value::Null => 4,
    }
}
