CREATE TABLE IF NOT EXISTS knowledge_project_schema_heads (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, schema_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
    deleted INTEGER NOT NULL CHECK(deleted IN (0,1)),
    document_json TEXT NOT NULL CHECK(json_valid(document_json)),
    PRIMARY KEY(tenant_id,project_id),
    CHECK(json_extract(document_json,'$.tenant_id') IS tenant_id),
    CHECK(json_extract(document_json,'$.project_id') IS project_id),
    CHECK(json_extract(document_json,'$.schema_id') IS schema_id),
    CHECK(json_extract(document_json,'$.revision') IS revision),
    CHECK(json_extract(document_json,'$.deleted') IS deleted)
);
CREATE TABLE IF NOT EXISTS knowledge_project_schema_changes (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, schema_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
    actor_id TEXT NOT NULL CHECK(length(actor_id)>0),
    change_id TEXT NOT NULL CHECK(length(change_id)=36),
    expected_revision INTEGER NOT NULL CHECK(expected_revision=revision-1),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)),
    PRIMARY KEY(tenant_id,project_id,revision),
    UNIQUE(tenant_id,project_id,actor_id,change_id),
    CHECK(json_extract(request_json,'$.tenant_id') IS tenant_id),
    CHECK(json_extract(request_json,'$.project_id') IS project_id),
    CHECK(json_extract(request_json,'$.actor_id') IS actor_id),
    CHECK(json_extract(request_json,'$.change_id') IS change_id),
    CHECK(json_extract(request_json,'$.expected_revision') IS expected_revision),
    CHECK(json_extract(request_json,'$.command') IS CASE WHEN revision=1 THEN 'bootstrap' ELSE 'replace' END),
    CHECK(json_extract(receipt_json,'$.format_version') IS 1),
    CHECK(json_extract(receipt_json,'$.actor_id') IS actor_id),
    CHECK(json_extract(receipt_json,'$.change_id') IS change_id),
    CHECK(json_extract(receipt_json,'$.sequence') IS revision),
    CHECK(json_type(receipt_json,'$.document') IS 'object'),
    CHECK(json_extract(receipt_json,'$.document.tenant_id') IS tenant_id),
    CHECK(json_extract(receipt_json,'$.document.project_id') IS project_id),
    CHECK(json_extract(receipt_json,'$.document.schema_id') IS schema_id),
    CHECK(json_extract(receipt_json,'$.document.revision') IS revision),
    CHECK(json_type(receipt_json,'$.document.deleted') IN ('true','false'))
);
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_change_guard
BEFORE INSERT ON knowledge_project_schema_changes BEGIN
    SELECT CASE WHEN NEW.revision != COALESCE((SELECT revision FROM knowledge_project_schema_heads
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id),0)+1
        THEN RAISE(ABORT,'project schema journal revision conflict') END;
    SELECT CASE WHEN EXISTS(SELECT 1 FROM knowledge_project_schema_heads
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
        AND (schema_id!=NEW.schema_id OR deleted=1))
        THEN RAISE(ABORT,'project schema identity is terminal or changed') END;
    SELECT CASE WHEN NEW.revision=1 AND
        (json_extract(NEW.receipt_json,'$.document.deleted') IS NOT 0
        OR json_array_length(NEW.receipt_json,'$.document.tombstones') IS NOT 0)
        THEN RAISE(ABORT,'project schema bootstrap must be live without tombstones') END;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_change_append
AFTER INSERT ON knowledge_project_schema_changes BEGIN
    INSERT INTO knowledge_project_schema_heads(tenant_id,project_id,schema_id,revision,deleted,document_json)
    VALUES(NEW.tenant_id,NEW.project_id,NEW.schema_id,NEW.revision,
        json_extract(NEW.receipt_json,'$.document.deleted'),json_extract(NEW.receipt_json,'$.document'))
    ON CONFLICT(tenant_id,project_id) DO UPDATE SET
        schema_id=excluded.schema_id,revision=excluded.revision,deleted=excluded.deleted,
        document_json=excluded.document_json;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_head_insert_guard
BEFORE INSERT ON knowledge_project_schema_heads BEGIN
    -- Also fence INSERT OR REPLACE, whose implicit delete does not necessarily
    -- run deletion triggers when SQLite recursive_triggers is disabled.
    SELECT CASE WHEN EXISTS(SELECT 1 FROM knowledge_project_schema_heads
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
        AND (schema_id!=NEW.schema_id OR deleted=1 OR NEW.revision!=revision+1))
        THEN RAISE(ABORT,'project schema head insert revision or identity conflict') END;
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM knowledge_project_schema_changes
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND revision=NEW.revision
        AND schema_id=NEW.schema_id AND json_extract(receipt_json,'$.document')=NEW.document_json)
        THEN RAISE(ABORT,'project schema head requires its journal receipt') END;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_head_update_guard
BEFORE UPDATE ON knowledge_project_schema_heads BEGIN
    SELECT CASE WHEN NEW.tenant_id!=OLD.tenant_id OR NEW.project_id!=OLD.project_id
        OR NEW.schema_id!=OLD.schema_id OR OLD.deleted=1 OR NEW.revision!=OLD.revision+1
        THEN RAISE(ABORT,'project schema head revision or identity conflict') END;
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM knowledge_project_schema_changes
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND revision=NEW.revision
        AND schema_id=NEW.schema_id AND json_extract(receipt_json,'$.document')=NEW.document_json)
        THEN RAISE(ABORT,'project schema head requires its journal receipt') END;
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_change_immutable
BEFORE UPDATE ON knowledge_project_schema_changes BEGIN
    SELECT RAISE(ABORT,'project schema journal is immutable');
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_change_no_delete
BEFORE DELETE ON knowledge_project_schema_changes BEGIN
    SELECT RAISE(ABORT,'project schema journal cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS knowledge_project_schema_head_no_delete
BEFORE DELETE ON knowledge_project_schema_heads BEGIN
    SELECT RAISE(ABORT,'project schema head must retain terminal identity');
END;
