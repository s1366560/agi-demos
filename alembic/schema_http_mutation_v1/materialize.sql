-- Frozen structural interpretation of the eight existing HTTP mutation shapes.
CREATE FUNCTION project_schema_http_materialize(previous_value jsonb, request_value jsonb, created_value text)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    operation_value text := request_value->>'operation';
    collection_value text;
    kind_value text;
    create_value boolean;
    delete_value boolean;
    fields_value jsonb := request_value->'fields';
    target_value text := request_value->>'target_id';
    member_value jsonb;
    document_value jsonb := previous_value;
    members_value jsonb;
    permitted text[];
    required text[];
    reference record;
    reference_id text;
    matches integer;
    field_value record;
BEGIN
    PERFORM project_schema_assert(jsonb_typeof(request_value)='object'
        AND request_value ?& ARRAY['command','operation','tenant_id','project_id','actor_id',
            'target_id','fields','expected_revision','change_id']
        AND NOT EXISTS (SELECT 1 FROM jsonb_object_keys(request_value) AS item(key)
            WHERE key <> ALL(ARRAY['command','operation','tenant_id','project_id','actor_id',
                'target_id','fields','expected_revision','change_id']))
        AND request_value->>'command'='http_mutation'
        AND project_schema_uuid(request_value->>'change_id')
        AND project_schema_text(request_value->'actor_id',512), 'project_schema_mutation_invalid');
    PERFORM project_schema_assert(request_value->>'tenant_id'=previous_value->>'tenant_id'
        AND request_value->>'project_id'=previous_value->>'project_id', 'project_schema_scope_mismatch');
    PERFORM project_schema_assert(request_value->>'expected_revision'=previous_value->>'revision'
        AND (previous_value->>'revision')::bigint < 2147483647, 'project_schema_revision_conflict');
    PERFORM project_schema_assert(previous_value->>'deleted'='false', 'project_schema_deleted');
    IF operation_value IN ('create_entity_type','update_entity_type','delete_entity_type') THEN
        collection_value := 'entity_types'; kind_value := 'entity_type';
    ELSIF operation_value IN ('create_edge_type','update_edge_type','delete_edge_type') THEN
        collection_value := 'edge_types'; kind_value := 'edge_type';
    ELSE
        PERFORM project_schema_assert(operation_value IN ('create_edge_map','delete_edge_map'),
            'project_schema_mutation_invalid');
        collection_value := 'mappings'; kind_value := 'mapping';
    END IF;
    create_value := operation_value IN ('create_entity_type','create_edge_type','create_edge_map');
    delete_value := operation_value IN ('delete_entity_type','delete_edge_type','delete_edge_map');
    permitted := CASE WHEN delete_value THEN ARRAY[]::text[]
        WHEN collection_value='mappings' THEN ARRAY['source_type','target_type','edge_type','status','source']
        WHEN create_value THEN ARRAY['name','description','schema','status','source']
        ELSE ARRAY['description','schema'] END;
    required := CASE WHEN NOT create_value THEN ARRAY[]::text[]
        WHEN collection_value='mappings' THEN ARRAY['source_type','target_type','edge_type']
        ELSE ARRAY['name'] END;
    PERFORM project_schema_assert(jsonb_typeof(fields_value)='object'
        AND fields_value ?& required AND NOT EXISTS (SELECT 1 FROM jsonb_object_keys(fields_value) AS item(key)
            WHERE key <> ALL(permitted)), 'project_schema_mutation_invalid');
    members_value := previous_value->collection_value;
    IF create_value THEN
        PERFORM project_schema_assert(request_value->'target_id'='null'::jsonb
            AND project_schema_uuid(created_value), 'project_schema_mutation_invalid');
        member_value := jsonb_build_object('id',created_value,
            'status',coalesce(fields_value->'status','"ENABLED"'::jsonb),
            'source',coalesce(fields_value->'source','"user"'::jsonb));
        IF collection_value='mappings' THEN
            FOR reference IN SELECT * FROM (VALUES
                ('source_type','entity_types','source_type_id'),
                ('target_type','entity_types','target_type_id'),
                ('edge_type','edge_types','edge_type_id')) AS refs(name,collection,key)
            LOOP
                SELECT count(*),min(item->>'id') INTO matches,reference_id
                    FROM jsonb_array_elements(previous_value->reference.collection) AS items(item)
                    WHERE item->'name'=fields_value->reference.name;
                PERFORM project_schema_assert(matches=1, 'project_schema_mapping_reference_not_found');
                member_value := member_value || jsonb_build_object(reference.key,reference_id);
            END LOOP;
            PERFORM project_schema_assert(NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(members_value) AS items(item)
                WHERE item->'source_type_id'=member_value->'source_type_id'
                    AND item->'target_type_id'=member_value->'target_type_id'
                    AND item->'edge_type_id'=member_value->'edge_type_id'), 'project_schema_mapping_conflict');
        ELSE
            PERFORM project_schema_assert(NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(members_value) AS items(item)
                WHERE item->'name'=fields_value->'name'), 'project_schema_' || kind_value || '_conflict');
            member_value := member_value || jsonb_build_object('name',fields_value->'name',
                'description',coalesce(nullif(fields_value->'description','null'::jsonb),'""'::jsonb),
                'schema',coalesce(fields_value->'schema','{}'::jsonb));
        END IF;
        members_value := members_value || jsonb_build_array(member_value);
    ELSE
        PERFORM project_schema_assert(project_schema_uuid(target_value) AND created_value IS NULL,
            'project_schema_mutation_invalid');
        SELECT item INTO member_value FROM jsonb_array_elements(members_value) AS items(item)
            WHERE item->>'id'=target_value;
        PERFORM project_schema_assert(FOUND, 'project_schema_' || kind_value || '_not_found');
        IF delete_value THEN
            PERFORM project_schema_assert(collection_value='mappings' OR NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(previous_value->'mappings') AS items(item)
                WHERE target_value IN (item->>'source_type_id',item->>'target_type_id',item->>'edge_type_id')),
                'project_schema_type_referenced');
            document_value := jsonb_set(document_value,'{tombstones}',(document_value->'tombstones') ||
                jsonb_build_array(jsonb_build_object('id',target_value,'kind',kind_value,
                    'deleted_revision',(previous_value->>'revision')::bigint+1)));
            SELECT coalesce(jsonb_agg(item),'[]'::jsonb) INTO members_value
                FROM jsonb_array_elements(members_value) AS items(item) WHERE item->>'id'<>target_value;
        ELSE
            FOR field_value IN SELECT key,value FROM jsonb_each(fields_value) WHERE value <> 'null'::jsonb LOOP
                member_value := jsonb_set(member_value,ARRAY[field_value.key],field_value.value);
            END LOOP;
            SELECT jsonb_agg(CASE WHEN item->>'id'=target_value THEN member_value ELSE item END)
                INTO members_value FROM jsonb_array_elements(members_value) AS items(item);
        END IF;
    END IF;
    document_value := jsonb_set(jsonb_set(document_value,ARRAY[collection_value],members_value),'{revision}',
        to_jsonb((previous_value->>'revision')::bigint+1));
    FOREACH collection_value IN ARRAY ARRAY['entity_types','edge_types','mappings','tombstones'] LOOP
        SELECT coalesce(jsonb_agg(item ORDER BY item->>'id'),'[]'::jsonb) INTO members_value
            FROM jsonb_array_elements(document_value->collection_value) AS items(item);
        document_value := jsonb_set(document_value,ARRAY[collection_value],members_value);
    END LOOP;
    PERFORM project_schema_document(document_value);
    PERFORM project_schema_successor(previous_value,document_value);
    RETURN document_value;
END
$$;

CREATE FUNCTION project_schema_guard_http_head() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    intent jsonb := nullif(current_setting('memstack.project_schema_intent',true),'')::jsonb;
    request_value jsonb;
    original_value jsonb;
    previous_value jsonb;
BEGIN
    request_value := (intent->>'request_json')::jsonb;
    IF NOT coalesce(request_value ? 'http_mutation',false) THEN RETURN NEW; END IF;
    PERFORM project_schema_assert(TG_OP='UPDATE' AND OLD.mode='active', 'project_schema_active_required');
    original_value := (request_value->>'http_mutation')::jsonb;
    PERFORM project_schema_assert(original_value->>'actor_id'=request_value->>'actor_id'
        AND original_value->>'change_id'=request_value->>'change_id'
        AND original_value->>'expected_revision'=request_value->>'expected_revision',
        'project_schema_request_mismatch');
    SELECT snapshot::jsonb INTO STRICT previous_value FROM project_schema_changes
        WHERE tenant_id=OLD.tenant_id AND project_id=OLD.project_id AND schema_id=OLD.schema_id
        AND revision=OLD.revision;
    PERFORM project_schema_assert(project_schema_http_materialize(previous_value,original_value,
        request_value->>'http_created_id')=intent->'document', 'project_schema_request_mismatch');
    RETURN NEW;
END
$$;
