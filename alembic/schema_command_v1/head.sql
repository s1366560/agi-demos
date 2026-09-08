-- Admission binds one snapshot to one head step. Only the head trigger may append
-- accepted history; merely setting a transaction GUC never permits a bare row write.
CREATE FUNCTION project_schema_guard_head() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    tenant_value text;
    intent jsonb;
    document_value jsonb;
    expected_value bigint := 0;
    previous_value jsonb;
    request_value jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM project_schema_assert(OLD.mode = 'legacy', 'project_schema_history_immutable');
        RETURN OLD;
    END IF;
    SELECT tenant_id INTO STRICT tenant_value FROM projects WHERE id=NEW.project_id FOR UPDATE;
    PERFORM project_schema_assert(tenant_value=NEW.tenant_id, 'project_schema_scope_mismatch');
    IF TG_OP = 'UPDATE' THEN
        PERFORM project_schema_assert((NEW.project_id,NEW.tenant_id,NEW.created_at)
            IS NOT DISTINCT FROM (OLD.project_id,OLD.tenant_id,OLD.created_at),
            'project_schema_scope_immutable');
        IF OLD.mode = 'active' THEN
            PERFORM project_schema_assert(NEW.mode='active' AND NEW.schema_id=OLD.schema_id
                AND NOT OLD.deleted AND NEW.revision=OLD.revision+1
                AND NEW.sequence=OLD.sequence+1, 'project_schema_revision_conflict');
            expected_value := OLD.revision;
        END IF;
    END IF;
    IF NEW.mode='legacy' THEN RETURN NEW; END IF;
    PERFORM project_schema_assert(NEW.mode='active', 'project_schema_document_invalid');
    intent := nullif(current_setting('memstack.project_schema_intent',true),'')::jsonb;
    PERFORM project_schema_assert(intent IS NOT NULL
        AND intent->>'tenant_id'=NEW.tenant_id AND intent->>'project_id'=NEW.project_id
        AND intent->>'schema_id'=NEW.schema_id
        AND intent->>'expected_revision'=expected_value::text
        AND project_schema_text(intent->'actor_id',512)
        AND intent->>'actor_id'=btrim(intent->>'actor_id',E' \t\r\n')
        AND project_schema_uuid(intent->>'change_id'), 'project_schema_write_intent_required');
    PERFORM project_schema_assert(NOT EXISTS (SELECT 1 FROM project_schema_changes
        WHERE project_id=NEW.project_id AND transaction_id=txid_current()),
        'project_schema_one_command_per_transaction');
    document_value := intent->'document';
    PERFORM project_schema_document(document_value);
    PERFORM project_schema_assert(document_value->>'schema_id'=NEW.schema_id
        AND document_value->>'project_id'=NEW.project_id AND document_value->>'tenant_id'=NEW.tenant_id
        AND document_value->>'revision'=NEW.revision::text
        AND document_value->>'deleted'=NEW.deleted::text, 'project_schema_head_document_mismatch');
    request_value := (intent->>'request_json')::jsonb;
    PERFORM project_schema_assert(request_value->>'tenant_id'=NEW.tenant_id
        AND request_value->>'project_id'=NEW.project_id AND request_value->>'schema_id'=NEW.schema_id
        AND request_value->>'actor_id'=intent->>'actor_id'
        AND request_value->>'change_id'=intent->>'change_id'
        AND request_value->>'expected_revision'=expected_value::text,
        'project_schema_request_mismatch');
    IF expected_value=0 THEN
        PERFORM project_schema_assert(NEW.revision=1 AND NEW.sequence=1 AND NOT NEW.deleted
            AND intent->>'source_kind'='bootstrap' AND request_value->>'command'='bootstrap',
            'project_schema_bootstrap_invalid');
        PERFORM project_schema_assert(document_value=project_schema_build_document(
            NEW.project_id,NEW.schema_id,1,false,true), 'project_schema_bootstrap_preservation_required');
    ELSE
        PERFORM project_schema_assert(intent->>'source_kind'='mutation'
            AND request_value->>'command'='replace', 'project_schema_request_mismatch');
        PERFORM project_schema_document(request_value->'document');
        -- Array order is not identity; the command snapshot is sorted by member ID.
        PERFORM project_schema_assert(request_value->'document' @> document_value
            AND document_value @> (request_value->'document'), 'project_schema_request_mismatch');
        SELECT snapshot::jsonb INTO STRICT previous_value FROM project_schema_changes
            WHERE schema_id=NEW.schema_id AND revision=expected_value;
        PERFORM project_schema_successor(previous_value,document_value);
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION project_schema_append_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    intent jsonb;
    response_value jsonb;
BEGIN
    IF NEW.mode <> 'active' THEN RETURN NEW; END IF;
    intent := nullif(current_setting('memstack.project_schema_intent',true),'')::jsonb;
    INSERT INTO project_schema_changes(tenant_id,project_id,sequence,schema_id,revision,actor_id,
        change_id,source_kind,snapshot,transaction_id)
    VALUES(NEW.tenant_id,NEW.project_id,NEW.sequence,NEW.schema_id,NEW.revision,intent->>'actor_id',
        intent->>'change_id',intent->>'source_kind',(intent->'document')::json,txid_current());
    response_value := jsonb_build_object('schema_id',NEW.schema_id,'revision',NEW.revision,
        'sequence',NEW.sequence,'change_id',intent->>'change_id','document',intent->'document');
    INSERT INTO project_schema_receipts(tenant_id,project_id,schema_id,actor_id,change_id,
        request_json,receipt_json)
    VALUES(NEW.tenant_id,NEW.project_id,NEW.schema_id,intent->>'actor_id',intent->>'change_id',
        intent->>'request_json',response_value::text);
    RETURN NEW;
END
$$;
