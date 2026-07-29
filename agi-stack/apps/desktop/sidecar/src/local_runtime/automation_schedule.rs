use std::str::FromStr;

use chrono::{DateTime, Duration, Utc};
use chrono_tz::Tz;
use croner::Cron;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct AutomationScheduleProjection {
    pub(super) availability: &'static str,
    pub(super) reason_code: Option<&'static str>,
    pub(super) fingerprint: String,
    pub(super) next_fire_at: Option<DateTime<Utc>>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum AutomationScheduleProjectionError {
    Invalid,
    Overflow,
}

pub(super) fn project_job_schedule(
    job: &Value,
    observed_at: DateTime<Utc>,
) -> Result<AutomationScheduleProjection, AutomationScheduleProjectionError> {
    let enabled = job
        .get("enabled")
        .and_then(Value::as_bool)
        .ok_or(AutomationScheduleProjectionError::Invalid)?;
    let schedule = job
        .get("schedule")
        .and_then(Value::as_object)
        .ok_or(AutomationScheduleProjectionError::Invalid)?;
    let schedule_kind = schedule
        .get("kind")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(AutomationScheduleProjectionError::Invalid)?;
    let schedule_config = schedule
        .get("config")
        .ok_or(AutomationScheduleProjectionError::Invalid)?;
    let timezone = job.get("timezone").and_then(Value::as_str).unwrap_or("UTC");
    let stagger_seconds = job
        .get("stagger_seconds")
        .and_then(Value::as_i64)
        .unwrap_or_default();
    let created_at = job
        .get("created_at")
        .and_then(Value::as_str)
        .ok_or(AutomationScheduleProjectionError::Invalid)
        .and_then(parse_utc)?;
    let fingerprint = schedule_fingerprint(
        enabled,
        schedule_kind,
        schedule_config,
        timezone,
        stagger_seconds,
    )?;
    if !enabled {
        return Ok(AutomationScheduleProjection {
            availability: "not_applicable",
            reason_code: Some("local_automation_schedule_disabled"),
            fingerprint,
            next_fire_at: None,
        });
    }
    if stagger_seconds < 0 {
        return Err(AutomationScheduleProjectionError::Invalid);
    }

    let next_fire_at = match schedule_kind {
        "at" => {
            let run_at = required_string(schedule_config, "run_at")
                .or_else(|_| required_string(schedule_config, "target_time"))?;
            let fire_at = add_seconds(parse_utc(run_at)?, stagger_seconds)?;
            (fire_at > observed_at).then_some(fire_at)
        }
        "every" => {
            let interval = schedule_config
                .get("interval_seconds")
                .and_then(Value::as_i64)
                .filter(|value| *value > 0)
                .ok_or(AutomationScheduleProjectionError::Invalid)?;
            let anchor = schedule_config
                .get("anchor_at")
                .and_then(Value::as_str)
                .map(parse_utc)
                .transpose()?
                .unwrap_or(created_at);
            Some(next_interval_fire(
                add_seconds(anchor, stagger_seconds)?,
                interval,
                observed_at,
            )?)
        }
        "cron" => {
            let expression = required_string(schedule_config, "expr")
                .or_else(|_| required_string(schedule_config, "expression"))?;
            let configured_timezone = schedule_config
                .get("timezone")
                .and_then(Value::as_str)
                .unwrap_or(timezone);
            let timezone = Tz::from_str(configured_timezone)
                .map_err(|_| AutomationScheduleProjectionError::Invalid)?;
            let cron = Cron::from_str(expression)
                .map_err(|_| AutomationScheduleProjectionError::Invalid)?;
            let search_at = add_seconds(observed_at, -stagger_seconds)?;
            let next = cron
                .find_next_occurrence(&search_at.with_timezone(&timezone), false)
                .map_err(|_| AutomationScheduleProjectionError::Invalid)?
                .with_timezone(&Utc);
            Some(add_seconds(next, stagger_seconds)?)
        }
        _ => return Err(AutomationScheduleProjectionError::Invalid),
    };
    Ok(AutomationScheduleProjection {
        availability: if next_fire_at.is_some() {
            "active"
        } else {
            "exhausted"
        },
        reason_code: None,
        fingerprint,
        next_fire_at,
    })
}

fn next_interval_fire(
    anchor: DateTime<Utc>,
    interval_seconds: i64,
    observed_at: DateTime<Utc>,
) -> Result<DateTime<Utc>, AutomationScheduleProjectionError> {
    if anchor > observed_at {
        return Ok(anchor);
    }
    let elapsed_seconds = observed_at.signed_duration_since(anchor).num_seconds();
    let steps = elapsed_seconds
        .checked_div(interval_seconds)
        .and_then(|value| value.checked_add(1))
        .ok_or(AutomationScheduleProjectionError::Overflow)?;
    let delta_seconds = interval_seconds
        .checked_mul(steps)
        .ok_or(AutomationScheduleProjectionError::Overflow)?;
    add_seconds(anchor, delta_seconds)
}

fn schedule_fingerprint(
    enabled: bool,
    schedule_kind: &str,
    schedule_config: &Value,
    timezone: &str,
    stagger_seconds: i64,
) -> Result<String, AutomationScheduleProjectionError> {
    let encoded = serde_json::to_vec(&json!({
        "enabled": enabled,
        "schedule_config": schedule_config,
        "schedule_type": schedule_kind,
        "stagger_seconds": stagger_seconds,
        "timezone": timezone,
    }))
    .map_err(|_| AutomationScheduleProjectionError::Invalid)?;
    Ok(format!("{:x}", Sha256::digest(encoded)))
}

fn required_string<'a>(
    value: &'a Value,
    field: &str,
) -> Result<&'a str, AutomationScheduleProjectionError> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(AutomationScheduleProjectionError::Invalid)
}

fn parse_utc(value: &str) -> Result<DateTime<Utc>, AutomationScheduleProjectionError> {
    DateTime::parse_from_rfc3339(value)
        .map(|value| value.with_timezone(&Utc))
        .map_err(|_| AutomationScheduleProjectionError::Invalid)
}

fn add_seconds(
    value: DateTime<Utc>,
    seconds: i64,
) -> Result<DateTime<Utc>, AutomationScheduleProjectionError> {
    value
        .checked_add_signed(Duration::seconds(seconds))
        .ok_or(AutomationScheduleProjectionError::Overflow)
}

#[cfg(test)]
mod tests {
    use chrono::{DateTime, Utc};
    use serde_json::{json, Value};

    use super::{project_job_schedule, AutomationScheduleProjectionError};

    #[test]
    fn cron_projection_honors_timezone_offset_across_dst() {
        let job = automation_job(
            json!({
                "kind": "cron",
                "config": { "expression": "0 9 * * *" }
            }),
            "America/New_York",
        );
        let observed_at = utc("2026-03-07T15:00:00Z");

        let projection = project_job_schedule(&job, observed_at).expect("cron projection");

        assert_eq!(projection.next_fire_at, Some(utc("2026-03-08T13:00:00Z")));
    }

    #[test]
    fn interval_projection_moves_past_an_exact_boundary() {
        let job = automation_job(
            json!({
                "kind": "every",
                "config": {
                    "interval_seconds": 60,
                    "anchor_at": "2026-04-01T10:00:00Z"
                }
            }),
            "UTC",
        );

        let projection =
            project_job_schedule(&job, utc("2026-04-01T10:01:00Z")).expect("interval projection");

        assert_eq!(projection.next_fire_at, Some(utc("2026-04-01T10:02:00Z")));
    }

    #[test]
    fn cron_projection_rejects_unknown_timezone() {
        let job = automation_job(
            json!({
                "kind": "cron",
                "config": { "expression": "0 9 * * *" }
            }),
            "Mars/Olympus",
        );

        assert_eq!(
            project_job_schedule(&job, utc("2026-04-01T10:00:00Z")),
            Err(AutomationScheduleProjectionError::Invalid)
        );
    }

    fn automation_job(schedule: Value, timezone: &str) -> Value {
        json!({
            "enabled": true,
            "schedule": schedule,
            "timezone": timezone,
            "stagger_seconds": 0,
            "created_at": "2026-03-01T00:00:00Z",
        })
    }

    fn utc(value: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(value)
            .expect("UTC fixture")
            .with_timezone(&Utc)
    }
}
