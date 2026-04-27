"""sanitize invalid every cron jobs

Revision ID: n2b3c4d5e6f7
Revises: m9f0a1b2c3d4
Create Date: 2026-04-27 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "m9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Disable and sanitize malformed recurring cron schedules."""
    op.execute(
        """
        WITH candidate AS (
            SELECT
                id,
                schedule_config,
                NULLIF(schedule_config->>'interval_seconds', '') AS interval_raw,
                NULLIF(schedule_config->>'hours', '') AS hours_raw,
                NULLIF(schedule_config->>'minutes', '') AS minutes_raw,
                NULLIF(schedule_config->>'seconds', '') AS seconds_raw
            FROM cron_jobs
            WHERE schedule_type = 'every'
        ),
        classified AS (
            SELECT
                id,
                schedule_config,
                interval_raw,
                (
                    (hours_raw IS NOT NULL AND hours_raw !~ '^-?[0-9]+$')
                    OR (minutes_raw IS NOT NULL AND minutes_raw !~ '^-?[0-9]+$')
                    OR (seconds_raw IS NOT NULL AND seconds_raw !~ '^-?[0-9]+$')
                ) AS has_bad_hms,
                (
                    CASE
                        WHEN hours_raw ~ '^-?[0-9]+$' THEN hours_raw::integer
                        ELSE 0
                    END * 3600
                    + CASE
                        WHEN minutes_raw ~ '^-?[0-9]+$' THEN minutes_raw::integer
                        ELSE 0
                    END * 60
                    + CASE
                        WHEN seconds_raw ~ '^-?[0-9]+$' THEN seconds_raw::integer
                        ELSE 0
                    END
                ) AS hms_seconds
            FROM candidate
        ),
        invalid AS (
            SELECT id, schedule_config
            FROM classified
            WHERE
                (
                    interval_raw IS NOT NULL
                    AND (
                        interval_raw !~ '^-?[0-9]+$'
                        OR CASE
                            WHEN interval_raw ~ '^-?[0-9]+$' THEN interval_raw::integer <= 0
                            ELSE false
                        END
                    )
                )
                OR (
                    interval_raw IS NULL
                    AND (has_bad_hms OR hms_seconds <= 0)
                )
        )
        UPDATE cron_jobs AS job
        SET
            enabled = false,
            schedule_config = '{"interval_seconds": 300}'::json,
            state = (
                COALESCE(job.state, '{}'::json)::jsonb
                || jsonb_build_object(
                    'disabled_reason', 'invalid_every_schedule_sanitized',
                    'invalid_schedule_config', invalid.schedule_config,
                    'sanitized_at', now()::text
                )
            )::json,
            updated_at = now()
        FROM invalid
        WHERE job.id = invalid.id
        """
    )


def downgrade() -> None:
    """No-op: the original invalid schedule cannot be safely re-enabled."""
