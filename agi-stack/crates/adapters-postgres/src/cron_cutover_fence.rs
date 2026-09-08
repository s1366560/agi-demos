//! The persisted verification receipt is separate from operator-supplied observations.

/// Expand the same structural receipt fence in every scheduler admission transaction.
/// A future deployment verifier must establish these facts; this crate never manufactures them.
macro_rules! verified_cutover_sql {
    ($prefix:literal) => {
        concat!(
            " AND ",
            $prefix,
            "cutover_phase = 'verified' ",
            " AND ",
            $prefix,
            "cutover_revision > 0 ",
            " AND ",
            $prefix,
            "cutover_evidence->>'protocol' = 'cron-cutover-evidence.v1' ",
            " AND ",
            $prefix,
            "cutover_evidence->'verification'->>'protocol' = 'cron-deployment-verification.v1' ",
            " AND json_typeof(",
            $prefix,
            "cutover_evidence->'verification'->'cutover_revision') = 'number' ",
            " AND json_typeof(",
            $prefix,
            "cutover_evidence->'verification'->'deployment_id') = 'string' ",
            " AND json_typeof(",
            $prefix,
            "cutover_evidence->'verification'->'receipt_id') = 'string' ",
            " AND json_typeof(",
            $prefix,
            "cutover_evidence->'verification'->'verifier_id') = 'string' ",
            " AND json_typeof(",
            $prefix,
            "cutover_evidence->'verification'->'inventory_sha256') = 'string' ",
            " AND json_typeof(",
            $prefix,
            "cutover_evidence->'verification'->'evidence_sha256') = 'string' ",
            " AND ",
            $prefix,
            "cutover_evidence->'verification'->>'cutover_revision' = ",
            $prefix,
            "cutover_revision::text ",
            " AND NULLIF(",
            $prefix,
            "cutover_evidence->'verification'->>'deployment_id', '') = ",
            $prefix,
            "cutover_evidence->'manifest'->>'deployment_id' ",
            " AND length(",
            $prefix,
            "cutover_evidence->'verification'->>'receipt_id') > 0 ",
            " AND length(",
            $prefix,
            "cutover_evidence->'verification'->>'verifier_id') > 0 ",
            " AND ",
            $prefix,
            "cutover_evidence->'verification'->>'inventory_sha256' ~ '^[0-9a-f]{64}$' ",
            " AND ",
            $prefix,
            "cutover_evidence->'verification'->>'evidence_sha256' ~ '^[0-9a-f]{64}$' ",
        )
    };
}

pub(crate) use verified_cutover_sql;
