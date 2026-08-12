ALTER TABLE bcs_messages ADD COLUMN workspace_id TEXT;
ALTER TABLE bcs_messages ADD COLUMN mentions_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE bcs_messages ADD COLUMN parent_message_id TEXT;
ALTER TABLE bcs_messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE bcs_messages ADD COLUMN source_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_messages_workspace_created
    ON bcs_messages(env, workspace_id, created_at, message_id);
