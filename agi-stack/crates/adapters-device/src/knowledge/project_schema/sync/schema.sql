-- Accepted mappings and immutable prepared intent; never a second schema journal/link.
CREATE TABLE IF NOT EXISTS knowledge_project_schema_sync_cursors (
    sync_key TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, authority TEXT NOT NULL,
    remote_tenant_id TEXT NOT NULL, remote_project_id TEXT NOT NULL, remote_actor_id TEXT NOT NULL,
    schema_id TEXT NOT NULL,
    anchor_id TEXT, epoch INTEGER NOT NULL DEFAULT 0 CHECK(epoch >= 0),
    native_after INTEGER NOT NULL DEFAULT 0 CHECK(native_after BETWEEN 0 AND 2147483647),
    cloud_after INTEGER NOT NULL DEFAULT 0 CHECK(cloud_after BETWEEN 0 AND 2147483647),
    UNIQUE(tenant_id,project_id,authority,remote_tenant_id,remote_project_id,remote_actor_id,schema_id),
    CHECK((anchor_id IS NULL AND epoch=0 AND native_after=0 AND cloud_after=0) OR anchor_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS knowledge_project_schema_prepared (
    step_id TEXT PRIMARY KEY, sync_key TEXT NOT NULL, initialization_id TEXT NOT NULL,
    local_actor_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('native_bootstrap','native_replace','cloud_replace')),
    expected_anchor_id TEXT, expected_epoch INTEGER NOT NULL CHECK(expected_epoch >= 0),
    source_receipt TEXT NOT NULL, destination_base TEXT,
    destination_change_id TEXT NOT NULL, request_json TEXT NOT NULL,
    completed_anchor_id TEXT,
    FOREIGN KEY(sync_key) REFERENCES knowledge_project_schema_sync_cursors(sync_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS knowledge_project_schema_one_pending
ON knowledge_project_schema_prepared(sync_key) WHERE completed_anchor_id IS NULL;
CREATE TABLE IF NOT EXISTS knowledge_project_schema_sync_anchors (
    anchor_id TEXT PRIMARY KEY, sync_key TEXT NOT NULL, producing_step_id TEXT NOT NULL UNIQUE,
    predecessor_anchor_id TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('source_seed','destination_seed','pair')),
    native_receipt TEXT, cloud_receipt TEXT NOT NULL,
    native_revision INTEGER NOT NULL CHECK(native_revision BETWEEN 0 AND 2147483647),
    cloud_revision INTEGER NOT NULL CHECK(cloud_revision BETWEEN 1 AND 2147483647),
    imported_side TEXT NOT NULL CHECK(imported_side IN ('native','cloud','neither')),
    CHECK((kind='pair' AND native_receipt IS NOT NULL AND native_revision>0)
       OR (kind IN ('source_seed','destination_seed') AND native_receipt IS NULL AND native_revision=0 AND cloud_revision=1)),
    FOREIGN KEY(sync_key) REFERENCES knowledge_project_schema_sync_cursors(sync_key),
    FOREIGN KEY(producing_step_id) REFERENCES knowledge_project_schema_prepared(step_id)
);
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_sync_cursor_insert BEFORE INSERT ON knowledge_project_schema_sync_cursors
BEGIN
 SELECT CASE WHEN NEW.anchor_id IS NOT NULL OR NOT EXISTS(
  SELECT 1 FROM knowledge_sync_links l JOIN knowledge_sync_targets t
   ON t.tenant_id=l.tenant_id AND t.project_id=l.project_id
  WHERE l.tenant_id=NEW.tenant_id AND l.project_id=NEW.project_id AND t.authority=NEW.authority
   AND l.remote_tenant_id=NEW.remote_tenant_id AND l.remote_project_id=NEW.remote_project_id
   AND l.remote_actor_id=NEW.remote_actor_id
 ) THEN RAISE(ABORT,'invalid schema sync cursor binding') END;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_sync_cursor_update BEFORE UPDATE ON knowledge_project_schema_sync_cursors
BEGIN
 SELECT CASE WHEN NEW.sync_key!=OLD.sync_key OR NEW.tenant_id!=OLD.tenant_id OR NEW.project_id!=OLD.project_id
  OR NEW.authority!=OLD.authority OR NEW.remote_tenant_id!=OLD.remote_tenant_id
  OR NEW.remote_project_id!=OLD.remote_project_id OR NEW.remote_actor_id!=OLD.remote_actor_id
  OR NEW.schema_id!=OLD.schema_id OR NEW.epoch!=OLD.epoch+1 OR NOT EXISTS(
   SELECT 1 FROM knowledge_project_schema_sync_anchors a WHERE a.anchor_id=NEW.anchor_id AND a.sync_key=OLD.sync_key
    AND a.predecessor_anchor_id IS OLD.anchor_id
    AND NEW.native_after=CASE WHEN a.kind='pair' THEN a.native_revision ELSE 0 END
    AND NEW.cloud_after=CASE WHEN a.kind='source_seed' THEN 0 ELSE a.cloud_revision END
  ) THEN RAISE(ABORT,'invalid schema sync cursor transition') END;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_sync_cursor_no_delete BEFORE DELETE ON knowledge_project_schema_sync_cursors
BEGIN SELECT RAISE(ABORT,'schema sync cursor cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_prepared_insert BEFORE INSERT ON knowledge_project_schema_prepared
BEGIN
 SELECT CASE WHEN NEW.completed_anchor_id IS NOT NULL OR NOT EXISTS(
  SELECT 1 FROM knowledge_project_schema_sync_cursors c WHERE c.sync_key=NEW.sync_key
   AND c.anchor_id IS NEW.expected_anchor_id AND c.epoch=NEW.expected_epoch
 ) THEN RAISE(ABORT,'invalid prepared schema cursor') END;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_prepared_update BEFORE UPDATE ON knowledge_project_schema_prepared
BEGIN
 SELECT CASE WHEN NEW.step_id!=OLD.step_id OR NEW.sync_key!=OLD.sync_key
  OR NEW.initialization_id!=OLD.initialization_id OR NEW.local_actor_id!=OLD.local_actor_id
  OR NEW.kind!=OLD.kind OR NEW.expected_anchor_id IS NOT OLD.expected_anchor_id
  OR NEW.expected_epoch!=OLD.expected_epoch OR NEW.source_receipt!=OLD.source_receipt
  OR NEW.destination_base IS NOT OLD.destination_base OR NEW.destination_change_id!=OLD.destination_change_id
  OR NEW.request_json!=OLD.request_json OR OLD.completed_anchor_id IS NOT NULL OR NOT EXISTS(
   SELECT 1 FROM knowledge_project_schema_sync_anchors a WHERE a.anchor_id=NEW.completed_anchor_id
    AND a.producing_step_id=OLD.step_id AND a.sync_key=OLD.sync_key
  ) THEN RAISE(ABORT,'prepared schema intent is immutable') END;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_prepared_no_delete BEFORE DELETE ON knowledge_project_schema_prepared
BEGIN SELECT RAISE(ABORT,'prepared schema intent cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_anchor_insert BEFORE INSERT ON knowledge_project_schema_sync_anchors
BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM knowledge_project_schema_prepared p JOIN knowledge_project_schema_sync_cursors c ON c.sync_key=p.sync_key
  WHERE p.step_id=NEW.producing_step_id AND p.sync_key=NEW.sync_key AND p.completed_anchor_id IS NULL
   AND p.expected_anchor_id IS NEW.predecessor_anchor_id AND c.anchor_id IS NEW.predecessor_anchor_id
   AND c.epoch=p.expected_epoch
 ) OR (NEW.predecessor_anchor_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM knowledge_project_schema_sync_anchors a WHERE a.anchor_id=NEW.predecessor_anchor_id AND a.sync_key=NEW.sync_key
 )) THEN RAISE(ABORT,'invalid schema acceptance mapping') END;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_anchor_no_update BEFORE UPDATE ON knowledge_project_schema_sync_anchors
BEGIN SELECT RAISE(ABORT,'schema acceptance mapping is immutable'); END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_anchor_no_delete BEFORE DELETE ON knowledge_project_schema_sync_anchors
BEGIN SELECT RAISE(ABORT,'schema acceptance mapping cannot be deleted'); END;
