use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use super::{ProjectActivityRecord, ProjectMemberRecord, ProjectReadRecord, ProjectStatsRecord};

pub(super) const PROJECT_COUNT_SQL: &str = "\
    SELECT count(*) \
    FROM projects p \
    JOIN user_projects access ON access.project_id = p.id \
    WHERE access.user_id = $1 \
      AND ($2::text IS NULL OR p.tenant_id = $2) \
      AND ($3::text = '' OR p.id ILIKE $4 OR p.name ILIKE $4 \
           OR p.description ILIKE $4 OR p.owner_id ILIKE $4) \
      AND ($5::text <> 'public' OR p.is_public = true) \
      AND ($5::text <> 'private' OR p.is_public = false) \
      AND ($6::text IS NULL OR p.owner_id = $6)";

pub(super) const PROJECT_OWNER_IDS_SQL: &str = "\
    SELECT DISTINCT p.owner_id \
    FROM projects p \
    JOIN user_projects access ON access.project_id = p.id \
    WHERE access.user_id = $1 \
      AND ($2::text IS NULL OR p.tenant_id = $2) \
      AND ($3::text = '' OR p.id ILIKE $4 OR p.name ILIKE $4 \
           OR p.description ILIKE $4 OR p.owner_id ILIKE $4) \
      AND ($5::text <> 'public' OR p.is_public = true) \
      AND ($5::text <> 'private' OR p.is_public = false) \
    ORDER BY p.owner_id";

pub(super) const PROJECT_LIST_SQL: &str = "\
    SELECT \
    p.id, p.tenant_id, p.name, p.description, p.owner_id, \
    COALESCE((SELECT array_agg(up.user_id ORDER BY up.user_id) \
              FROM user_projects up WHERE up.project_id = p.id), ARRAY[]::text[]) AS member_ids, \
    COALESCE(p.memory_rules, '{}'::json) AS memory_rules, \
    COALESCE(p.graph_config, '{}'::json) AS graph_config, \
    p.graph_store_id, p.retrieval_store_id, \
    COALESCE(p.sandbox_type, 'cloud') AS sandbox_type, \
    COALESCE(p.sandbox_config, '{}'::json) AS sandbox_config, \
    COALESCE(p.is_public, false) AS is_public, \
    COALESCE(p.agent_conversation_mode, 'single_agent') AS agent_conversation_mode, \
    p.created_at, p.updated_at, \
    COALESCE((SELECT count(*) FROM memories m WHERE m.project_id = p.id), 0)::bigint AS memory_count, \
    COALESCE((SELECT sum(length(m.content)) FROM memories m WHERE m.project_id = p.id), 0)::bigint AS storage_used, \
    COALESCE((SELECT count(*) FROM user_projects up WHERE up.project_id = p.id), 0)::bigint AS member_count, \
    (SELECT max(m.created_at) FROM memories m WHERE m.project_id = p.id) AS last_memory_at \
    FROM projects p \
    JOIN user_projects access ON access.project_id = p.id \
    WHERE access.user_id = $1 \
      AND ($2::text IS NULL OR p.tenant_id = $2) \
      AND ($3::text = '' OR p.id ILIKE $4 OR p.name ILIKE $4 \
           OR p.description ILIKE $4 OR p.owner_id ILIKE $4) \
      AND ($5::text <> 'public' OR p.is_public = true) \
      AND ($5::text <> 'private' OR p.is_public = false) \
      AND ($6::text IS NULL OR p.owner_id = $6) \
    ORDER BY CASE WHEN p.name IN ('Default project', '默认项目') THEN 0 ELSE 1 END ASC, \
             p.created_at DESC, p.id ASC \
    OFFSET $7 LIMIT $8";

pub(super) const PROJECT_GET_SQL: &str = "\
    SELECT \
    p.id, p.tenant_id, p.name, p.description, p.owner_id, \
    COALESCE((SELECT array_agg(up.user_id ORDER BY up.user_id) \
              FROM user_projects up WHERE up.project_id = p.id), ARRAY[]::text[]) AS member_ids, \
    COALESCE(p.memory_rules, '{}'::json) AS memory_rules, \
    COALESCE(p.graph_config, '{}'::json) AS graph_config, \
    p.graph_store_id, p.retrieval_store_id, \
    COALESCE(p.sandbox_type, 'cloud') AS sandbox_type, \
    COALESCE(p.sandbox_config, '{}'::json) AS sandbox_config, \
    COALESCE(p.is_public, false) AS is_public, \
    COALESCE(p.agent_conversation_mode, 'single_agent') AS agent_conversation_mode, \
    p.created_at, p.updated_at, \
    COALESCE((SELECT count(*) FROM memories m WHERE m.project_id = p.id), 0)::bigint AS memory_count, \
    COALESCE((SELECT sum(length(m.content)) FROM memories m WHERE m.project_id = p.id), 0)::bigint AS storage_used, \
    COALESCE((SELECT count(*) FROM user_projects up WHERE up.project_id = p.id), 0)::bigint AS member_count, \
    (SELECT max(m.created_at) FROM memories m WHERE m.project_id = p.id) AS last_memory_at \
    FROM projects p \
    WHERE p.id = $1";

pub(super) const PROJECT_DASHBOARD_STATS_SQL: &str = "\
    SELECT \
    COALESCE((SELECT count(*) FROM memories m WHERE m.project_id = $1), 0)::bigint AS memory_count, \
    COALESCE((SELECT sum(length(m.content)) FROM memories m WHERE m.project_id = $1), 0)::bigint AS storage_used, \
    COALESCE((SELECT count(*) FROM user_projects up WHERE up.project_id = $1), 0)::bigint AS member_count, \
    COALESCE((SELECT count(*) FROM conversations c WHERE c.project_id = $1), 0)::bigint AS conversation_count";

pub(super) const PROJECT_RECENT_ACTIVITY_SQL: &str = "\
    SELECT m.id, COALESCE(NULLIF(u.full_name, ''), u.email) AS user_name, \
           COALESCE(NULLIF(m.title, ''), 'Untitled Memory') AS target, m.created_at \
    FROM memories m \
    JOIN users u ON u.id = m.author_id \
    WHERE m.project_id = $1 \
    ORDER BY m.created_at DESC, m.id ASC \
    LIMIT 5";

pub(super) const PROJECT_MEMBERS_SQL: &str = "\
    SELECT up.user_id, u.email, u.full_name, COALESCE(up.role, 'member') AS role, \
           COALESCE(up.permissions, '{}'::json) AS permissions, \
           COALESCE(up.created_at, now()) AS created_at \
    FROM user_projects up \
    JOIN users u ON up.user_id = u.id \
    WHERE up.project_id = $1 \
    ORDER BY up.created_at ASC NULLS LAST, up.user_id ASC";

pub(super) fn row_to_record(row: PgRow) -> Result<ProjectReadRecord, sqlx::Error> {
    let updated_at: Option<DateTime<Utc>> = row.try_get("updated_at")?;
    let last_memory_at: Option<DateTime<Utc>> = row.try_get("last_memory_at")?;
    let last_active = match (updated_at, last_memory_at) {
        (Some(a), Some(b)) => Some(if b > a { b } else { a }),
        (Some(a), None) => Some(a),
        (None, Some(b)) => Some(b),
        (None, None) => None,
    };

    Ok(ProjectReadRecord {
        id: row.try_get("id")?,
        tenant_id: row.try_get("tenant_id")?,
        name: row.try_get("name")?,
        description: row.try_get("description")?,
        owner_id: row.try_get("owner_id")?,
        member_ids: row.try_get("member_ids")?,
        memory_rules: row.try_get("memory_rules")?,
        graph_config: row.try_get("graph_config")?,
        graph_store_id: row.try_get("graph_store_id")?,
        retrieval_store_id: row.try_get("retrieval_store_id")?,
        sandbox_type: row.try_get("sandbox_type")?,
        sandbox_config: row.try_get("sandbox_config")?,
        is_public: row.try_get("is_public")?,
        agent_conversation_mode: row.try_get("agent_conversation_mode")?,
        created_at: row.try_get("created_at")?,
        updated_at,
        stats: ProjectStatsRecord {
            memory_count: row.try_get("memory_count")?,
            storage_used: row.try_get("storage_used")?,
            member_count: row.try_get("member_count")?,
            last_active,
        },
    })
}

pub(super) fn row_to_activity(row: PgRow) -> Result<ProjectActivityRecord, sqlx::Error> {
    Ok(ProjectActivityRecord {
        id: row.try_get("id")?,
        user: row.try_get("user_name")?,
        target: row.try_get("target")?,
        created_at: row.try_get("created_at")?,
    })
}

pub(super) fn row_to_member(row: PgRow) -> Result<ProjectMemberRecord, sqlx::Error> {
    Ok(ProjectMemberRecord {
        user_id: row.try_get("user_id")?,
        email: row.try_get("email")?,
        name: row.try_get("full_name")?,
        role: row.try_get("role")?,
        permissions: row.try_get("permissions")?,
        created_at: row.try_get("created_at")?,
    })
}
