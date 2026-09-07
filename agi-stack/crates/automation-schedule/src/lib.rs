//! Civil-time cron policy shared by both automation runtimes.

use chrono::{DateTime, TimeZone, Utc};
use chrono_tz::Tz;
use croner::Cron;

/// A cron expression cannot produce a strictly advancing calendar candidate.
#[derive(Clone, Copy, Debug, PartialEq, Eq, thiserror::Error)]
pub enum CronProjectionError {
    #[error("cron schedule has no valid future candidate")]
    Invalid,
}

/// Returns the first scheduled instant strictly after `observed_at`.
/// Missing civil times are skipped; repeated civil times use their first instant.
///
/// # Errors
/// Returns an error when the cron search fails or does not advance.
pub fn next_cron_fire(
    cron: &Cron,
    timezone: Tz,
    observed_at: DateTime<Utc>,
) -> Result<DateTime<Utc>, CronProjectionError> {
    // Search civil calendar values without the library's gap snapping policy.
    // Resolve each value once: gaps are absent, folds use their earliest instant.
    let mut civil_cursor = observed_at.with_timezone(&timezone).naive_local().and_utc();
    loop {
        let candidate = cron
            .find_next_occurrence(&civil_cursor, false)
            .map_err(|_| CronProjectionError::Invalid)?;
        if candidate <= civil_cursor {
            return Err(CronProjectionError::Invalid);
        }
        civil_cursor = candidate;
        if let Some(instant) = timezone
            .from_local_datetime(&candidate.naive_utc())
            .earliest()
        {
            if instant.with_timezone(&Utc) > observed_at {
                return Ok(instant.with_timezone(&Utc));
            }
        }
    }
}
