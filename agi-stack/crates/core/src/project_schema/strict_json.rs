//! Reject duplicate keys, including inside opaque schema definitions.

use serde::de::{Error, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::{Map, Number, Value};
use std::fmt;

pub(super) struct StrictJson(pub Value);

impl<'de> Deserialize<'de> for StrictJson {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct JsonVisitor;
        impl<'de> Visitor<'de> for JsonVisitor {
            type Value = StrictJson;

            fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
                formatter.write_str("JSON with unique object keys")
            }

            fn visit_bool<E: Error>(self, value: bool) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::Bool(value)))
            }

            fn visit_i64<E: Error>(self, value: i64) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::Number(value.into())))
            }

            fn visit_u64<E: Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::Number(value.into())))
            }

            fn visit_f64<E: Error>(self, value: f64) -> Result<Self::Value, E> {
                Number::from_f64(value)
                    .map(|number| StrictJson(Value::Number(number)))
                    .ok_or_else(|| E::custom("nonfinite number"))
            }

            fn visit_str<E: Error>(self, value: &str) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::String(value.to_owned())))
            }

            fn visit_string<E: Error>(self, value: String) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::String(value)))
            }

            fn visit_unit<E: Error>(self) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::Null))
            }

            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Self::Value, A::Error> {
                let mut result = Vec::new();
                while let Some(value) = seq.next_element::<StrictJson>()? {
                    result.push(value.0);
                }
                Ok(StrictJson(Value::Array(result)))
            }

            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut result = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if result.contains_key(&key) {
                        return Err(A::Error::custom("duplicate object key"));
                    }
                    result.insert(key, map.next_value::<StrictJson>()?.0);
                }
                Ok(StrictJson(Value::Object(result)))
            }
        }
        deserializer.deserialize_any(JsonVisitor)
    }
}
