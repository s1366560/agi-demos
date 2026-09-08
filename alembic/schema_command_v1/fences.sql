CREATE FUNCTION project_schema_guard_row() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    project_value text;
    member_value text;
    head project_schema_heads%ROWTYPE;
    change project_schema_changes%ROWTYPE;
    scope_row record;
BEGIN
    project_value := CASE WHEN TG_OP='DELETE' THEN OLD.project_id ELSE NEW.project_id END;
    member_value := CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
    IF TG_OP='UPDATE' AND NEW.project_id IS DISTINCT FROM OLD.project_id THEN
        FOR scope_row IN SELECT id FROM projects WHERE id IN (OLD.project_id,NEW.project_id)
            ORDER BY id FOR UPDATE LOOP
            PERFORM project_schema_assert(NOT EXISTS (SELECT 1 FROM project_schema_heads
                WHERE project_id=scope_row.id AND mode='active'), 'project_schema_scope_immutable');
        END LOOP;
    ELSE
        -- Even legacy writers acquire this lock. Bootstrap uses the same project
        -- lock before scanning, so stale pre-activation writes cannot commit later.
        PERFORM 1 FROM projects WHERE id=project_value FOR UPDATE;
    END IF;
    SELECT * INTO head FROM project_schema_heads WHERE project_id=project_value;
    IF NOT FOUND OR head.mode='legacy' THEN
        IF TG_TABLE_NAME='edge_type_maps' AND TG_OP <> 'DELETE' THEN
            PERFORM project_schema_assert(NEW.source_type_id IS NULL AND NEW.target_type_id IS NULL
                AND NEW.edge_type_id IS NULL, 'project_schema_inactive_references');
        END IF;
        RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP='UPDATE' THEN
        PERFORM project_schema_assert((NEW.id,NEW.project_id) IS NOT DISTINCT FROM (OLD.id,OLD.project_id),
            'project_schema_member_identity_immutable');
    END IF;
    SELECT * INTO change FROM project_schema_changes
        WHERE project_id=project_value AND tenant_id=head.tenant_id AND schema_id=head.schema_id
        AND revision=head.revision AND sequence=head.sequence AND transaction_id=txid_current();
    PERFORM project_schema_assert(FOUND, 'project_schema_command_required');
    IF TG_TABLE_NAME='edge_type_maps' AND TG_OP <> 'DELETE' THEN
        PERFORM project_schema_assert(NEW.source_type_id IS NOT NULL AND NEW.target_type_id IS NOT NULL
            AND NEW.edge_type_id IS NOT NULL, 'project_schema_mapping_ids_required');
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END
$$;

CREATE FUNCTION project_schema_guard_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Only the nested head trigger appends accepted journal/receipt rows. A raw
    -- INSERT, COPY, UPDATE, DELETE, or forged GUC does not create admitted history.
    PERFORM project_schema_assert(TG_OP='INSERT' AND pg_trigger_depth()=2,
        'project_schema_history_immutable');
    RETURN NEW;
END
$$;

CREATE FUNCTION project_schema_guard_tombstone() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE change project_schema_changes%ROWTYPE;
BEGIN
    PERFORM project_schema_assert(TG_OP='INSERT', 'project_schema_tombstone_immutable');
    PERFORM 1 FROM projects WHERE id=NEW.project_id AND tenant_id=NEW.tenant_id FOR UPDATE;
    SELECT * INTO change FROM project_schema_changes
        WHERE schema_id=NEW.schema_id AND project_id=NEW.project_id AND tenant_id=NEW.tenant_id
        AND revision=NEW.deleted_revision AND transaction_id=txid_current();
    PERFORM project_schema_assert(FOUND AND change.snapshot::jsonb->'tombstones' @> jsonb_build_array(
        jsonb_build_object('id',NEW.member_id,'kind',NEW.kind,'deleted_revision',NEW.deleted_revision)),
        'project_schema_tombstone_not_admitted');
    RETURN NEW;
END
$$;

CREATE FUNCTION project_schema_guard_project() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' OR (NEW.id,NEW.tenant_id) IS DISTINCT FROM (OLD.id,OLD.tenant_id) THEN
        PERFORM project_schema_assert(NOT EXISTS (
            SELECT 1 FROM project_schema_heads WHERE project_id=OLD.id AND mode='active'),
            'project_schema_scope_immutable');
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END
$$;

CREATE FUNCTION project_schema_guard_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING MESSAGE='project_schema_truncate_forbidden', ERRCODE='23514';
END
$$;

CREATE FUNCTION project_schema_check_commit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    project_value text;
    head project_schema_heads%ROWTYPE;
    change project_schema_changes%ROWTYPE;
    receipt project_schema_receipts%ROWTYPE;
    actual jsonb;
BEGIN
    project_value := CASE WHEN TG_OP='DELETE' THEN OLD.project_id ELSE NEW.project_id END;
    SELECT * INTO head FROM project_schema_heads WHERE project_id=project_value;
    IF NOT FOUND OR head.mode <> 'active' THEN RETURN NULL; END IF;
    PERFORM project_schema_assert((SELECT count(*) FROM project_schema_changes
        WHERE project_id=project_value AND transaction_id=txid_current())=1,
        'project_schema_commit_journal_required');
    SELECT * INTO STRICT change FROM project_schema_changes
        WHERE project_id=project_value AND transaction_id=txid_current();
    PERFORM project_schema_assert((change.tenant_id,change.schema_id,change.revision,change.sequence)
        IS NOT DISTINCT FROM (head.tenant_id,head.schema_id,head.revision,head.sequence),
        'project_schema_commit_head_mismatch');
    SELECT * INTO STRICT receipt FROM project_schema_receipts
        WHERE tenant_id=change.tenant_id AND project_id=change.project_id AND schema_id=change.schema_id
        AND actor_id=change.actor_id AND change_id=change.change_id;
    PERFORM project_schema_assert(receipt.receipt_json::jsonb=jsonb_build_object(
        'schema_id',change.schema_id,'revision',change.revision,'sequence',change.sequence,
        'change_id',change.change_id,'document',change.snapshot::jsonb),
        'project_schema_commit_receipt_mismatch');
    actual := project_schema_current_document(project_value);
    PERFORM project_schema_document(actual);
    PERFORM project_schema_assert(actual=change.snapshot::jsonb, 'project_schema_commit_document_mismatch');
    PERFORM project_schema_assert(NOT EXISTS (
        SELECT 1 FROM edge_type_maps m
        LEFT JOIN entity_types s ON s.project_id=m.project_id AND s.id=m.source_type_id
        LEFT JOIN entity_types t ON t.project_id=m.project_id AND t.id=m.target_type_id
        LEFT JOIN edge_types e ON e.project_id=m.project_id AND e.id=m.edge_type_id
        WHERE m.project_id=project_value AND (
            m.source_type IS DISTINCT FROM s.name OR m.target_type IS DISTINCT FROM t.name
            OR m.edge_type IS DISTINCT FROM e.name)), 'project_schema_mapping_name_mismatch');
    RETURN NULL;
END
$$;
