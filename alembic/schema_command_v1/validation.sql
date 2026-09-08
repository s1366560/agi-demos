-- Frozen migration support. Structural checks only; definitions are never executed.
CREATE FUNCTION project_schema_assert(ok boolean, code text) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF ok IS DISTINCT FROM true THEN
        RAISE EXCEPTION USING MESSAGE = code, ERRCODE = '23514';
    END IF;
END
$$;

CREATE FUNCTION project_schema_uuid(value text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN value IS NOT NULL AND value::uuid::text = value
        AND value <> '00000000-0000-0000-0000-000000000000';
EXCEPTION WHEN invalid_text_representation THEN RETURN false;
END
$$;

CREATE FUNCTION project_schema_text(value jsonb, maximum integer, nonempty boolean DEFAULT true)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_typeof(value) = 'string' AND octet_length(value #>> '{}') <= maximum
        AND (NOT nonempty OR length(value #>> '{}') > 0)
$$;

-- [node count, key/value UTF-8 bytes, portable serialization weight]. JSON (not
-- JSONB) traversal retains duplicate keys so legacy lexical defects fail closed.
CREATE FUNCTION project_schema_json_metrics(value json, depth integer DEFAULT 0)
RETURNS integer[] LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    kind text := json_typeof(value);
    child record;
    metrics integer[];
    nodes integer := 1;
    strings integer := 0;
    weight integer := 0;
    children integer := 0;
BEGIN
    PERFORM project_schema_assert(depth <= 32, 'project_schema_definition_invalid');
    IF kind = 'object' THEN
        PERFORM project_schema_assert(
            NOT EXISTS (SELECT key FROM json_each(value) GROUP BY key HAVING count(*) > 1),
            'project_schema_definition_invalid');
        weight := 2;
        FOR child IN SELECT key, val FROM json_each(value) AS entry(key, val) LOOP
            metrics := project_schema_json_metrics(child.val, depth + 1);
            nodes := nodes + metrics[1];
            strings := strings + octet_length(child.key) + metrics[2];
            weight := weight + octet_length(to_json(child.key)::text) + 1 + metrics[3];
            children := children + 1;
        END LOOP;
    ELSIF kind = 'array' THEN
        weight := 2;
        FOR child IN SELECT val FROM json_array_elements(value) AS entry(val) LOOP
            metrics := project_schema_json_metrics(child.val, depth + 1);
            nodes := nodes + metrics[1];
            strings := strings + metrics[2];
            weight := weight + metrics[3];
            children := children + 1;
        END LOOP;
    ELSIF kind = 'string' THEN
        strings := octet_length(value #>> '{}');
        weight := octet_length(to_json(value #>> '{}')::text);
    ELSIF kind = 'number' THEN
        PERFORM project_schema_assert(abs(value::text::numeric) <= 9007199254740991,
            'project_schema_definition_invalid');
        weight := 32;
    ELSE
        PERFORM project_schema_assert(kind IN ('null', 'boolean'), 'project_schema_definition_invalid');
        weight := length(value::text);
    END IF;
    RETURN ARRAY[nodes, strings, weight + greatest(children - 1, 0)];
END
$$;

CREATE FUNCTION project_schema_definition(value json) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE metrics integer[];
BEGIN
    PERFORM project_schema_assert(json_typeof(value) = 'object', 'project_schema_definition_invalid');
    -- Starting at 16 gives this individual opaque definition the v1 depth limit 16.
    metrics := project_schema_json_metrics(value, 16);
    PERFORM project_schema_assert(metrics[1] <= 1024 AND metrics[2] <= 16384,
        'project_schema_definition_invalid');
END
$$;

-- Python/Rust document parsers use finite binary64 numbers. Project raw legacy
-- decimals through that same representation without rewriting their stored JSON.
CREATE FUNCTION project_schema_portable_json(value json) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET extra_float_digits = 3 AS $$
DECLARE
    kind text := json_typeof(value);
    result jsonb;
BEGIN
    IF kind='object' THEN
        SELECT coalesce(jsonb_object_agg(key,project_schema_portable_json(val)),'{}'::jsonb)
            INTO result FROM json_each(value) AS e(key,val);
    ELSIF kind='array' THEN
        SELECT coalesce(jsonb_agg(project_schema_portable_json(val) ORDER BY ordinal),'[]'::jsonb)
            INTO result FROM json_array_elements(value) WITH ORDINALITY AS e(val,ordinal);
    ELSIF kind='number' THEN
        BEGIN
            result := (value::text::double precision)::text::jsonb;
        EXCEPTION WHEN numeric_value_out_of_range THEN
            -- PostgreSQL reports a zero-rounded subnormal as an error; binary64
            -- JSON parsers return zero. Finite overflow was already rejected.
            PERFORM project_schema_assert(abs(value::text::numeric)<1e-300,
                'project_schema_definition_invalid');
            result := '0'::jsonb;
        END;
    ELSE
        result := value::jsonb;
    END IF;
    RETURN result;
END
$$;

CREATE FUNCTION project_schema_document(value jsonb) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    member jsonb;
    field text;
    member_id text;
    seen jsonb := '{}'::jsonb;
    metrics integer[];
    revision_value integer;
BEGIN
    PERFORM project_schema_assert(jsonb_typeof(value) = 'object'
        AND (SELECT count(*) FROM jsonb_object_keys(value)) = 10
        AND value ?& ARRAY['format_version','tenant_id','project_id','schema_id','revision',
            'deleted','entity_types','edge_types','mappings','tombstones'], 'project_schema_document_invalid');
    PERFORM project_schema_assert(value->>'format_version' = '1'
        AND jsonb_typeof(value->'format_version') = 'number'
        AND jsonb_typeof(value->'revision') = 'number'
        AND jsonb_typeof(value->'deleted') = 'boolean'
        AND project_schema_uuid(value->>'schema_id'), 'project_schema_document_invalid');
    revision_value := (value->>'revision')::integer;
    PERFORM project_schema_assert(revision_value BETWEEN 1 AND 2147483647,
        'project_schema_document_invalid');
    FOREACH field IN ARRAY ARRAY['tenant_id', 'project_id'] LOOP
        PERFORM project_schema_assert(project_schema_text(value->field, 512)
            AND value->>field = btrim(value->>field, E' \t\r\n'), 'project_schema_document_invalid');
    END LOOP;
    FOREACH field IN ARRAY ARRAY['entity_types','edge_types','mappings','tombstones'] LOOP
        PERFORM project_schema_assert(jsonb_typeof(value->field) = 'array', 'project_schema_document_invalid');
    END LOOP;
    PERFORM project_schema_assert(jsonb_array_length(value->'entity_types')
        + jsonb_array_length(value->'edge_types') + jsonb_array_length(value->'mappings')
        + jsonb_array_length(value->'tombstones') <= 1024, 'project_schema_document_invalid');
    seen := jsonb_build_object(value->>'schema_id', 'document');
    FOREACH field IN ARRAY ARRAY['entity_types','edge_types','mappings','tombstones'] LOOP
        FOR member IN SELECT val FROM jsonb_array_elements(value->field) AS entry(val) LOOP
            member_id := member->>'id';
            PERFORM project_schema_assert(jsonb_typeof(member) = 'object'
                AND project_schema_uuid(member_id) AND NOT seen ? member_id, 'project_schema_document_invalid');
            seen := seen || jsonb_build_object(member_id, field);
            IF field IN ('entity_types','edge_types') THEN
                PERFORM project_schema_assert((SELECT count(*) FROM jsonb_object_keys(member)) = 6
                    AND member ?& ARRAY['id','name','description','schema','status','source']
                    AND project_schema_text(member->'name',512)
                    AND project_schema_text(member->'description',4096,false), 'project_schema_document_invalid');
                PERFORM project_schema_definition((member->'schema')::json);
            ELSIF field = 'mappings' THEN
                PERFORM project_schema_assert((SELECT count(*) FROM jsonb_object_keys(member)) = 6
                    AND member ?& ARRAY['id','source_type_id','target_type_id','edge_type_id','status','source']
                    AND EXISTS (SELECT 1 FROM jsonb_array_elements(value->'entity_types') AS e(v)
                        WHERE v->>'id' = member->>'source_type_id')
                    AND EXISTS (SELECT 1 FROM jsonb_array_elements(value->'entity_types') AS e(v)
                        WHERE v->>'id' = member->>'target_type_id')
                    AND EXISTS (SELECT 1 FROM jsonb_array_elements(value->'edge_types') AS e(v)
                        WHERE v->>'id' = member->>'edge_type_id'), 'project_schema_document_invalid');
            ELSE
                PERFORM project_schema_assert((SELECT count(*) FROM jsonb_object_keys(member)) = 3
                    AND member ?& ARRAY['id','kind','deleted_revision']
                    AND member->>'kind' IN ('entity_type','edge_type','mapping')
                    AND jsonb_typeof(member->'deleted_revision') = 'number'
                    AND (member->>'deleted_revision')::integer BETWEEN 1 AND revision_value,
                    'project_schema_document_invalid');
            END IF;
            IF field <> 'tombstones' THEN
                PERFORM project_schema_assert(member->>'status' IN ('ENABLED','DISABLED')
                    AND project_schema_text(member->'source',128), 'project_schema_document_invalid');
            END IF;
        END LOOP;
    END LOOP;
    PERFORM project_schema_assert(value->>'deleted' <> 'true' OR (
        jsonb_array_length(value->'entity_types') = 0 AND jsonb_array_length(value->'edge_types') = 0
        AND jsonb_array_length(value->'mappings') = 0), 'project_schema_document_invalid');
    metrics := project_schema_json_metrics(value::json);
    PERFORM project_schema_assert(metrics[3] <= 1048576, 'project_schema_document_invalid');
END
$$;
