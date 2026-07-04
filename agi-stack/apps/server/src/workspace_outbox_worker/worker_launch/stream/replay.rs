use super::*;

pub(super) fn worker_stream_event_time_us(event: &Value) -> Option<i64> {
    event
        .get("event_time_us")
        .and_then(Value::as_i64)
        .or_else(|| {
            event
                .get("event_time_us")
                .and_then(Value::as_u64)
                .and_then(|value| i64::try_from(value).ok())
        })
}
