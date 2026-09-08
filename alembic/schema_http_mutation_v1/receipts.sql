-- Responses are rendered from actual admitted rows after materialization. No
-- timestamp prediction, mutable-row replay, or caller-provided response payload.
CREATE FUNCTION project_schema_http_response(tenant_value text, project_value text, schema_value text,
    actor_value text, change_value text) RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE
    base project_schema_receipts%ROWTYPE;
    change project_schema_changes%ROWTYPE;
    request_value jsonb;
    original_value jsonb;
    operation_value text;
    target_value text;
    body_value text;
    status_value integer := 200;
BEGIN
    SELECT * INTO STRICT base FROM project_schema_receipts WHERE tenant_id=tenant_value
        AND project_id=project_value AND schema_id=schema_value AND actor_id=actor_value AND change_id=change_value;
    SELECT * INTO STRICT change FROM project_schema_changes WHERE tenant_id=tenant_value
        AND project_id=project_value AND schema_id=schema_value AND actor_id=actor_value AND change_id=change_value;
    request_value := base.request_json::jsonb;
    original_value := (request_value->>'http_mutation')::jsonb;
    operation_value := original_value->>'operation';
    target_value := coalesce(original_value->>'target_id',request_value->>'http_created_id');
    IF operation_value IN ('delete_entity_type','delete_edge_type','delete_edge_map') THEN
        status_value := 204; body_value := '';
    ELSIF operation_value IN ('create_entity_type','update_entity_type') THEN
        SELECT jsonb_build_object('id',id,'project_id',project_id,'name',name,'description',description,
            'schema',schema::jsonb,'status',status,'source',source,'created_at',created_at,'updated_at',updated_at)::text
            INTO body_value FROM entity_types WHERE project_id=project_value AND id=target_value;
    ELSIF operation_value IN ('create_edge_type','update_edge_type') THEN
        SELECT jsonb_build_object('id',id,'project_id',project_id,'name',name,'description',description,
            'schema',schema::jsonb,'status',status,'source',source,'created_at',created_at,'updated_at',updated_at)::text
            INTO body_value FROM edge_types WHERE project_id=project_value AND id=target_value;
    ELSIF operation_value='create_edge_map' THEN
        SELECT jsonb_build_object('id',id,'project_id',project_id,'source_type',source_type,
            'target_type',target_type,'edge_type',edge_type,'status',status,'source',source,'created_at',created_at)::text
            INTO body_value FROM edge_type_maps WHERE project_id=project_value AND id=target_value;
    END IF;
    PERFORM project_schema_assert(body_value IS NOT NULL, 'project_schema_http_response_missing');
    RETURN jsonb_build_object('status',status_value,'body',body_value,'headers',jsonb_build_object(
        'X-Project-Schema-Id',schema_value,'X-Project-Schema-Revision',change.revision::text,
        'X-Project-Schema-Change-Id',change_value))::text;
END
$$;

CREATE FUNCTION project_schema_guard_http_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    base project_schema_receipts%ROWTYPE;
    change project_schema_changes%ROWTYPE;
BEGIN
    PERFORM project_schema_assert(TG_OP='INSERT', 'project_schema_history_immutable');
    SELECT * INTO base FROM project_schema_receipts WHERE tenant_id=NEW.tenant_id
        AND project_id=NEW.project_id AND schema_id=NEW.schema_id AND actor_id=NEW.actor_id AND change_id=NEW.change_id;
    SELECT * INTO change FROM project_schema_changes WHERE tenant_id=NEW.tenant_id
        AND project_id=NEW.project_id AND schema_id=NEW.schema_id AND actor_id=NEW.actor_id AND change_id=NEW.change_id
        AND transaction_id=txid_current();
    PERFORM project_schema_assert(FOUND AND NEW.original_request_json=base.request_json::jsonb->>'http_mutation'
        AND NEW.response_json=project_schema_http_response(NEW.tenant_id,NEW.project_id,NEW.schema_id,
            NEW.actor_id,NEW.change_id), 'project_schema_http_receipt_not_admitted');
    RETURN NEW;
END
$$;

CREATE FUNCTION project_schema_finalize_http(tenant_value text, project_value text, schema_value text,
    actor_value text, change_value text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE base project_schema_receipts%ROWTYPE;
BEGIN
    SELECT * INTO STRICT base FROM project_schema_receipts WHERE tenant_id=tenant_value
        AND project_id=project_value AND schema_id=schema_value AND actor_id=actor_value AND change_id=change_value;
    INSERT INTO project_schema_http_receipts(tenant_id,project_id,schema_id,actor_id,change_id,
        original_request_json,response_json)
    VALUES(tenant_value,project_value,schema_value,actor_value,change_value,
        base.request_json::jsonb->>'http_mutation',
        project_schema_http_response(tenant_value,project_value,schema_value,actor_value,change_value));
END
$$;

CREATE FUNCTION project_schema_check_http_commit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    project_value text := CASE WHEN TG_OP='DELETE' THEN OLD.project_id ELSE NEW.project_id END;
    change project_schema_changes%ROWTYPE;
    base project_schema_receipts%ROWTYPE;
    receipt project_schema_http_receipts%ROWTYPE;
BEGIN
    SELECT c.* INTO change FROM project_schema_changes c JOIN projects p ON p.id=c.project_id
        AND p.tenant_id=c.tenant_id WHERE c.project_id=project_value AND c.transaction_id=txid_current();
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT * INTO STRICT base FROM project_schema_receipts WHERE tenant_id=change.tenant_id
        AND project_id=change.project_id AND schema_id=change.schema_id AND actor_id=change.actor_id AND change_id=change.change_id;
    IF NOT (base.request_json::jsonb ? 'http_mutation') THEN RETURN NULL; END IF;
    SELECT * INTO receipt FROM project_schema_http_receipts WHERE tenant_id=change.tenant_id
        AND project_id=change.project_id AND schema_id=change.schema_id AND actor_id=change.actor_id AND change_id=change.change_id;
    PERFORM project_schema_assert(FOUND AND receipt.original_request_json=base.request_json::jsonb->>'http_mutation'
        AND receipt.response_json=project_schema_http_response(change.tenant_id,change.project_id,
            change.schema_id,change.actor_id,change.change_id), 'project_schema_http_commit_receipt_mismatch');
    RETURN NULL;
END
$$;
