//! Pagination freezes the upper identity, but deliberately reads live job states.
use super::*;
use agistack_core::knowledge::diagnostics::{DiagnosticPage, DiagnosticRequest};
use serde::{Deserialize, Serialize};
const MAX_WIRE_INTEGER: u64 = 9_007_199_254_740_991;
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Cursor {
    binding: String,
    pub upper: u64,
    pub after: u64,
}
impl Cursor {
    pub fn read(request: &DiagnosticRequest, binding: String, upper: u64) -> KnowledgeResult<Self> {
        if !(1..=100).contains(&request.limit) || upper > MAX_WIRE_INTEGER {
            return Err(KnowledgeError::InvalidInput);
        }
        let cursor = match &request.cursor {
            Some(value) if value.len() <= 8192 => {
                serde_json::from_str::<Self>(value).map_err(|_| KnowledgeError::InvalidInput)?
            }
            Some(_) => return Err(KnowledgeError::InvalidInput),
            None => Self {
                binding: binding.clone(),
                upper,
                after: 0,
            },
        };
        if cursor.binding != binding || cursor.after > cursor.upper || cursor.upper > upper {
            return Err(KnowledgeError::Conflict);
        }
        Ok(cursor)
    }
    pub fn page<T>(
        mut self,
        mut items: Vec<T>,
        limit: usize,
        key: impl Fn(&T) -> u64,
    ) -> KnowledgeResult<DiagnosticPage<T>> {
        let more = items.len() > limit;
        items.truncate(limit);
        let next_cursor = if more {
            self.after = items.last().map(key).ok_or(KnowledgeError::Conflict)?;
            Some(serde_json::to_string(&self).map_err(storage)?)
        } else {
            None
        };
        Ok(DiagnosticPage { items, next_cursor })
    }
}
