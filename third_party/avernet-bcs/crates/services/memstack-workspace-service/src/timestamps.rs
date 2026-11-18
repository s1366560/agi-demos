use time::{OffsetDateTime, UtcOffset, macros::format_description};

pub(crate) fn response_micros(value: OffsetDateTime) -> String {
    value
        .to_offset(UtcOffset::UTC)
        .format(format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ))
        .expect("UTC timestamp has all format components")
}

pub(crate) fn storage_micros(value: OffsetDateTime) -> String {
    value
        .to_offset(UtcOffset::UTC)
        .format(format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]+00:00"
        ))
        .expect("UTC timestamp has all format components")
}

pub(crate) fn response_millis(value: OffsetDateTime) -> String {
    value
        .to_offset(UtcOffset::UTC)
        .format(format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:3]Z"
        ))
        .expect("UTC timestamp has all format components")
}

pub(crate) fn unix_millis(value: OffsetDateTime) -> i64 {
    value.unix_timestamp_nanos().div_euclid(1_000_000) as i64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preserves_timestamp_wire_formats_and_pre_epoch_rounding() {
        let before_epoch = OffsetDateTime::from_unix_timestamp_nanos(-1).unwrap();
        assert_eq!(unix_millis(before_epoch), -1);
        assert_eq!(
            storage_micros(before_epoch),
            "1969-12-31T23:59:59.999999+00:00"
        );
        assert_eq!(response_micros(before_epoch), "1969-12-31T23:59:59.999999Z");
        assert_eq!(response_millis(before_epoch), "1969-12-31T23:59:59.999Z");
    }
}
