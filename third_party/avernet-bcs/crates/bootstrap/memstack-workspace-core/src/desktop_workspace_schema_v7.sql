INSERT OR IGNORE INTO workspace_autonomy_bootstrap_outbox (
    bootstrap_id,
    tenant_id,
    project_id,
    workspace_id,
    actor_id,
    objective_title,
    objective_description,
    created_at_ms
)
SELECT
    'autonomy-bootstrap-recovery:' || profile.workspace_id,
    profile.tenant_id,
    profile.project_id,
    profile.workspace_id,
    COALESCE(
        (
            SELECT member.user_id
            FROM workspace_members member
            WHERE member.tenant_id = profile.tenant_id
              AND member.project_id = profile.project_id
              AND member.workspace_id = profile.workspace_id
              AND member.role IN ('owner', 'admin', 'editor')
            ORDER BY CASE member.role
                WHEN 'owner' THEN 0
                WHEN 'admin' THEN 1
                ELSE 2
            END,
            member.created_at ASC,
            member.member_id ASC
            LIMIT 1
        ),
        profile.created_by
    ),
    CASE
        WHEN length(trim(profile.name)) > 0 THEN profile.name
        ELSE 'Autonomous workspace ' || profile.workspace_id
    END,
    profile.description,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000
FROM workspace_profiles profile
WHERE profile.deleted_at IS NULL
  AND (
      json_extract(profile.metadata_json, '$.collaboration_mode') = 'autonomous'
      OR json_extract(profile.metadata_json, '$.agent_conversation_mode') = 'autonomous'
      OR json_extract(
          profile.metadata_json,
          '$.legacy_desktop.collaboration_mode'
      ) = 'autonomous'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM workspace_tasks root
      WHERE root.tenant_id = profile.tenant_id
        AND root.project_id = profile.project_id
        AND root.workspace_id = profile.workspace_id
        AND json_extract(root.metadata_json, '$.task_role') = 'goal_root'
  );
