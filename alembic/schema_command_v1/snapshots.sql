-- Relational reconstruction only. There is no mutable current JSON authority.
CREATE FUNCTION project_schema_build_document(
    project_value text, schema_value text, revision_value bigint, deleted_value boolean,
    legacy boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
    result jsonb;
    tenant_value text;
    definition json;
BEGIN
    SELECT tenant_id INTO STRICT tenant_value FROM projects WHERE id = project_value;
    FOR definition IN
        SELECT schema FROM entity_types WHERE project_id = project_value
        UNION ALL SELECT schema FROM edge_types WHERE project_id = project_value
    LOOP
        PERFORM project_schema_definition(definition);
    END LOOP;
    SELECT jsonb_build_object(
        'format_version',1,'tenant_id',tenant_value,'project_id',project_value,
        'schema_id',schema_value,'revision',revision_value,'deleted',deleted_value,
        'entity_types',coalesce((SELECT jsonb_agg(jsonb_build_object(
            'id',id,'name',name,'description',coalesce(description,''),'schema',project_schema_portable_json(schema),
            'status',status,'source',source) ORDER BY id)
            FROM entity_types WHERE project_id = project_value),'[]'::jsonb),
        'edge_types',coalesce((SELECT jsonb_agg(jsonb_build_object(
            'id',id,'name',name,'description',coalesce(description,''),'schema',project_schema_portable_json(schema),
            'status',status,'source',source) ORDER BY id)
            FROM edge_types WHERE project_id = project_value),'[]'::jsonb),
        'mappings',coalesce((SELECT jsonb_agg(jsonb_build_object(
            'id',m.id,'status',m.status,'source',m.source,
            'source_type_id',CASE WHEN legacy THEN
                (SELECT id FROM entity_types WHERE project_id=project_value AND name=m.source_type)
                ELSE m.source_type_id END,
            'target_type_id',CASE WHEN legacy THEN
                (SELECT id FROM entity_types WHERE project_id=project_value AND name=m.target_type)
                ELSE m.target_type_id END,
            'edge_type_id',CASE WHEN legacy THEN
                (SELECT id FROM edge_types WHERE project_id=project_value AND name=m.edge_type)
                ELSE m.edge_type_id END) ORDER BY m.id)
            FROM edge_type_maps m WHERE m.project_id=project_value),'[]'::jsonb),
        'tombstones',CASE WHEN legacy THEN '[]'::jsonb ELSE coalesce((
            SELECT jsonb_agg(jsonb_build_object('id',member_id,'kind',kind,
                'deleted_revision',deleted_revision) ORDER BY member_id)
            FROM project_schema_tombstones WHERE project_id=project_value AND schema_id=schema_value
        ),'[]'::jsonb) END
    ) INTO result;
    RETURN result;
END
$$;

CREATE FUNCTION project_schema_current_document(project_value text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE head project_schema_heads%ROWTYPE;
BEGIN
    SELECT * INTO head FROM project_schema_heads WHERE project_id=project_value AND mode='active';
    IF NOT FOUND THEN RETURN NULL; END IF;
    RETURN project_schema_build_document(project_value,head.schema_id,head.revision,head.deleted);
END
$$;

CREATE FUNCTION project_schema_members(value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(jsonb_object_agg(member->>'id',kind),'{}'::jsonb) FROM (
        SELECT v AS member,'entity_type' AS kind FROM jsonb_array_elements(value->'entity_types') AS e(v)
        UNION ALL SELECT v,'edge_type' FROM jsonb_array_elements(value->'edge_types') AS e(v)
        UNION ALL SELECT v,'mapping' FROM jsonb_array_elements(value->'mappings') AS e(v)
    ) members
$$;

CREATE FUNCTION project_schema_successor(before_value jsonb, after_value jsonb) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    old_live jsonb := project_schema_members(before_value);
    new_live jsonb := project_schema_members(after_value);
    old_dead jsonb;
    new_dead jsonb;
    item record;
    revision_value integer := (after_value->>'revision')::integer;
BEGIN
    PERFORM project_schema_assert(before_value->>'deleted' = 'false'
        AND before_value->>'tenant_id' = after_value->>'tenant_id'
        AND before_value->>'project_id' = after_value->>'project_id'
        AND before_value->>'schema_id' = after_value->>'schema_id'
        AND (before_value->>'revision')::bigint + 1 = revision_value,
        'project_schema_transition_invalid');
    SELECT coalesce(jsonb_object_agg(v->>'id',v),'{}'::jsonb) INTO old_dead
        FROM jsonb_array_elements(before_value->'tombstones') AS e(v);
    SELECT coalesce(jsonb_object_agg(v->>'id',v),'{}'::jsonb) INTO new_dead
        FROM jsonb_array_elements(after_value->'tombstones') AS e(v);
    FOR item IN SELECT key,val FROM jsonb_each(old_dead) AS e(key,val) LOOP
        PERFORM project_schema_assert(new_dead->item.key = item.val, 'project_schema_tombstone_immutable');
    END LOOP;
    FOR item IN SELECT key,val FROM jsonb_each(new_live) AS e(key,val) LOOP
        PERFORM project_schema_assert(NOT old_dead ? item.key
            AND (NOT old_live ? item.key OR old_live->item.key = item.val),
            'project_schema_member_identity_immutable');
    END LOOP;
    FOR item IN SELECT key,val FROM jsonb_each(old_live) AS e(key,val) LOOP
        IF NOT new_live ? item.key THEN
            PERFORM project_schema_assert(new_dead->item.key = jsonb_build_object(
                'id',item.key,'kind',item.val,'deleted_revision',revision_value),
                'project_schema_tombstone_required');
        END IF;
    END LOOP;
    FOR item IN SELECT key,val FROM jsonb_each(new_dead) AS e(key,val) LOOP
        PERFORM project_schema_assert(old_dead ? item.key OR (
            old_live ? item.key AND NOT new_live ? item.key
            AND item.val->'kind' = old_live->item.key
            AND (item.val->>'deleted_revision')::integer = revision_value),
            'project_schema_tombstone_invalid');
    END LOOP;
END
$$;
