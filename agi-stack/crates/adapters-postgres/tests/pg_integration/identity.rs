use super::support::*;

/// P2 login vertical: prove the store-level round-trip against the shared schema.
/// 1. `find_auth_by_email` returns the Python-shaped auth record.
/// 2. `insert_api_key` (mint on login) writes a key that `find_by_raw_key` then
///    resolves — this exercises the exact SHA-256 digest parity the two sides
///    share (mint hashes the plaintext; auth hashes the presented raw key).
/// 3. `PgTenantRepository` scopes tenant reads by membership (count/list/get with
///    404-then-403 ordering).
#[tokio::test]
async fn login_and_tenant_reads_roundtrip_against_shared_schema() {
    let Some(pool) = pool_or_skip("login_and_tenant_reads_roundtrip_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    ensure_tenant_delete_tables(&pool).await;

    // Clean any prior run for a deterministic assertion set.
    for sql in [
        "DELETE FROM tenant_delete_audit_children WHERE id = 'tenant_audit_child'",
        "DELETE FROM tenant_delete_audit_entries \
         WHERE id = 'tenant_audit_entry' OR tenant_id = 't_p2_delete'",
        "DELETE FROM tenant_delete_loose_notes WHERE tenant_id = 't_p2_delete'",
        "DELETE FROM project_delete_audit_children WHERE id = 'tenant_project_audit_child'",
        "DELETE FROM project_delete_audit_entries \
         WHERE id = 'tenant_project_audit_entry' OR project_id = 'p_p2_delete'",
        "DELETE FROM messages WHERE id = 'msg_tenant_delete' OR conversation_id = 'c_tenant_delete'",
        "DELETE FROM conversations \
         WHERE id = 'c_tenant_delete' OR project_id = 'p_p2_delete' OR tenant_id = 't_p2_delete'",
        "DELETE FROM workspaces \
         WHERE id = 'w_tenant_delete' OR project_id = 'p_p2_delete' OR tenant_id = 't_p2_delete'",
        "DELETE FROM user_projects WHERE project_id = 'p_p2_delete'",
        "DELETE FROM projects WHERE id = 'p_p2_delete' OR tenant_id = 't_p2_delete'",
        "DELETE FROM user_tenants WHERE user_id IN ('u_p2', 'u_p2_target') \
         OR tenant_id IN ('t_p2_created', 't_p2_member', 't_p2_other', 't_p2_delete')",
        "DELETE FROM api_keys WHERE user_id = 'u_p2'",
        "DELETE FROM tenants WHERE id IN ('t_p2_created', 't_p2_member', 't_p2_other', 't_p2_delete')",
        "DELETE FROM users WHERE id IN ('u_p2', 'u_p2_target')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    // A user with a Python-stored bcrypt hash (the real `userpassword` vector).
    let stored_hash = "$2b$12$7zqrguT7EVNDjaBFQ03ITe6Q5Y1YiOL6Vu45Q6rjaLF3VfNYU/VD6";
    sqlx::query(
        "INSERT INTO users (id, email, full_name, hashed_password, is_active, is_superuser, \
         must_change_password) VALUES ('u_p2', 'p2@memstack.ai', 'P2 User', $1, true, false, false)",
    )
    .bind(stored_hash)
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO users (id, email, full_name, is_active, is_superuser) \
         VALUES ('u_p2_target', 'target-p2@memstack.ai', 'P2 Target', true, false)",
    )
    .execute(&pool)
    .await
    .unwrap();

    let users = PgUserStore::new(pool.clone());

    // (1) Auth lookup returns the shaped record.
    let rec = users
        .find_auth_by_email("p2@memstack.ai")
        .await
        .unwrap()
        .expect("user found");
    assert_eq!(rec.id, "u_p2");
    assert_eq!(rec.hashed_password, stored_hash);
    assert!(rec.is_active);
    assert!(!rec.is_superuser);
    assert!(users
        .find_auth_by_email("missing@x")
        .await
        .unwrap()
        .is_none());

    // (2) Mint a key exactly as login does, then resolve it via the auth store.
    let raw_key = "ms_sk_p2_login_session_key_0000000000000000000000000000000000000000";
    users
        .insert_api_key(
            "k_p2",
            raw_key,
            "Login Session p2@memstack.ai",
            "u_p2",
            None,
            &["read".to_string(), "write".to_string()],
        )
        .await
        .unwrap();
    let keys = PgApiKeyStore::new(pool.clone());
    let resolved = keys
        .find_by_raw_key(raw_key)
        .await
        .unwrap()
        .expect("minted key resolves");
    assert_eq!(resolved.user_id, "u_p2");
    assert!(resolved.is_usable_at(1_700_000_000_000));

    // (3) Tenant membership scoping.
    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) \
         VALUES ('t_p2_member', 'Member Tenant', 'member-tenant', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) \
         VALUES ('t_p2_other', 'Other Tenant', 'other-tenant', 'u_other')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_p2', 'u_p2', 't_p2_member', 'admin')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let tenants = PgTenantRepository::new(pool.clone());
    assert_eq!(tenants.count_for_user("u_p2", None).await.unwrap(), 1);
    let page = tenants.list_for_user("u_p2", None, 0, 20).await.unwrap();
    assert_eq!(page.len(), 1);
    assert_eq!(page[0].id, "t_p2_member");
    assert_eq!(page[0].slug, "member-tenant");

    // Found (member), by id and by slug.
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_p2_member").await.unwrap(),
        TenantLookup::Found(t) if t.id == "t_p2_member"
    ));
    assert!(matches!(
        tenants.get_for_user("u_p2", "member-tenant").await.unwrap(),
        TenantLookup::Found(_)
    ));
    // Exists but no membership -> Forbidden (403), not NotFound.
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_p2_other").await.unwrap(),
        TenantLookup::Forbidden
    ));
    // Does not exist -> NotFound (404).
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_nope").await.unwrap(),
        TenantLookup::NotFound
    ));

    // (4) Tenant create/update and member mutations match Python-owned tables.
    let created = tenants
        .create_tenant(
            "t_p2_created",
            "ut_p2_created_owner",
            "u_p2",
            "Acme Corporation",
            Some("Created by Rust"),
            &json!({"admin": true, "create_projects": true, "manage_users": true}),
        )
        .await
        .unwrap();
    assert_eq!(created.slug, "acme-corporation");
    assert_eq!(created.owner_id, "u_p2");
    assert_eq!(created.plan, "free");
    assert_eq!(created.max_projects, 10);
    assert_eq!(created.max_users, 5);

    let owner_membership: (String, serde_json::Value) = sqlx::query_as(
        "SELECT role, permissions FROM user_tenants \
         WHERE tenant_id = 't_p2_created' AND user_id = 'u_p2'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(owner_membership.0, "owner");
    assert_eq!(owner_membership.1["manage_users"], true);

    let updated = tenants
        .update_owned_tenant(
            "u_p2",
            "t_p2_created",
            &TenantUpdatePatch {
                name: Some("Acme Updated".into()),
                description: Some(None),
                plan: Some("enterprise".into()),
                max_projects: Some(20),
                max_users: Some(50),
                max_storage: Some(2_147_483_648),
            },
        )
        .await
        .unwrap()
        .expect("owned tenant update");
    assert_eq!(updated.name, "Acme Updated");
    assert_eq!(updated.slug, "acme-corporation");
    assert_eq!(updated.description, None);
    assert_eq!(updated.plan, "enterprise");
    assert!(tenants
        .update_owned_tenant("u_p2_target", "t_p2_created", &TenantUpdatePatch::default())
        .await
        .unwrap()
        .is_none());

    assert!(tenants.tenant_exists("t_p2_created").await.unwrap());
    assert!(tenants
        .user_owns_tenant("u_p2", "t_p2_created")
        .await
        .unwrap());
    assert!(!tenants
        .user_owns_tenant("u_p2_target", "t_p2_created")
        .await
        .unwrap());
    assert!(tenants.user_exists("u_p2_target").await.unwrap());
    assert!(tenants
        .tenant_member_role("t_p2_created", "u_p2_target")
        .await
        .unwrap()
        .is_none());

    tenants
        .add_tenant_member(
            "ut_p2_created_target",
            "t_p2_created",
            "u_p2_target",
            "editor",
            &json!({"read": true, "write": true}),
        )
        .await
        .unwrap();
    assert_eq!(
        tenants
            .tenant_member_role("t_p2_created", "u_p2_target")
            .await
            .unwrap()
            .expect("tenant membership")
            .role,
        "editor"
    );
    assert!(tenants
        .update_tenant_member(
            "t_p2_created",
            "u_p2_target",
            "owner",
            &json!({"read": true, "write": true}),
        )
        .await
        .unwrap());
    let member_after_update: (String, serde_json::Value) = sqlx::query_as(
        "SELECT role, permissions FROM user_tenants \
         WHERE tenant_id = 't_p2_created' AND user_id = 'u_p2_target'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(member_after_update.0, "owner");
    assert_eq!(member_after_update.1["write"], true);

    assert!(tenants
        .remove_tenant_member("t_p2_created", "u_p2_target")
        .await
        .unwrap());
    assert!(!tenants
        .remove_tenant_member("t_p2_created", "u_p2_target")
        .await
        .unwrap());

    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) \
         VALUES ('t_p2_delete', 'Delete Tenant', 'delete-tenant', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
         VALUES ('ut_p2_delete_owner', 'u_p2', 't_p2_delete', 'owner', '{\"manage_users\": true}'::json)",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_p2_delete', 't_p2_delete', 'Tenant Delete Project', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
         VALUES ('up_p2_delete_owner', 'u_p2', 'p_p2_delete', 'owner', '{\"admin\": true}'::json)",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO conversations (id, project_id, tenant_id, user_id, title) \
         VALUES ('c_tenant_delete', 'p_p2_delete', 't_p2_delete', 'u_p2', 'Tenant delete conversation')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO messages (id, conversation_id, content) \
         VALUES ('msg_tenant_delete', 'c_tenant_delete', 'delete me')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO workspaces (id, tenant_id, project_id, name, created_by) \
         VALUES ('w_tenant_delete', 't_p2_delete', 'p_p2_delete', 'Delete workspace', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO project_delete_audit_entries (id, project_id) \
         VALUES ('tenant_project_audit_entry', 'p_p2_delete')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO project_delete_audit_children (id, entry_id) \
         VALUES ('tenant_project_audit_child', 'tenant_project_audit_entry')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenant_delete_audit_entries (id, tenant_id) \
         VALUES ('tenant_audit_entry', 't_p2_delete')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenant_delete_audit_children (id, entry_id) \
         VALUES ('tenant_audit_child', 'tenant_audit_entry')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenant_delete_loose_notes (id, tenant_id, note) \
         VALUES ('tenant_loose_note', 't_p2_delete', 'no physical FK')",
    )
    .execute(&pool)
    .await
    .unwrap();

    assert!(!tenants
        .delete_owned_tenant("u_p2_target", "t_p2_delete")
        .await
        .unwrap());
    assert!(tenants
        .delete_owned_tenant("u_p2", "t_p2_delete")
        .await
        .unwrap());
    assert!(!tenants.tenant_exists("t_p2_delete").await.unwrap());
    for (table, predicate) in [
        ("user_tenants", "tenant_id = 't_p2_delete'"),
        ("projects", "id = 'p_p2_delete'"),
        ("user_projects", "project_id = 'p_p2_delete'"),
        ("conversations", "id = 'c_tenant_delete'"),
        ("messages", "id = 'msg_tenant_delete'"),
        ("workspaces", "id = 'w_tenant_delete'"),
        (
            "project_delete_audit_entries",
            "id = 'tenant_project_audit_entry'",
        ),
        (
            "project_delete_audit_children",
            "id = 'tenant_project_audit_child'",
        ),
        ("tenant_delete_audit_entries", "id = 'tenant_audit_entry'"),
        ("tenant_delete_audit_children", "id = 'tenant_audit_child'"),
        ("tenant_delete_loose_notes", "id = 'tenant_loose_note'"),
    ] {
        let sql = format!("SELECT count(*) FROM {table} WHERE {predicate}");
        let (count,): (i64,) = sqlx::query_as(&sql).fetch_one(&pool).await.unwrap();
        assert_eq!(count, 0, "{table} still has rows matching {predicate}");
    }
}

#[tokio::test]
async fn invitations_roundtrip_against_shared_schema() {
    let Some(pool) = pool_or_skip("invitations_roundtrip_against_shared_schema").await else {
        return;
    };
    ensure_identity_tables(&pool).await;
    ensure_invitation_tables(&pool).await;

    for cleanup in [
        "DELETE FROM user_tenants WHERE user_id IN ('u_inv_owner', 'u_inv_member', 'u_inv_accept')",
        "DELETE FROM invitations WHERE tenant_id IN ('t_inv', 't_inv_other') OR id IN ('inv_one', 'inv_two')",
        "DELETE FROM tenants WHERE id IN ('t_inv', 't_inv_other')",
        "DELETE FROM users WHERE id IN ('u_inv_owner', 'u_inv_member', 'u_inv_accept')",
    ] {
        sqlx::query(cleanup).execute(&pool).await.unwrap();
    }

    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES \
         ('u_inv_owner', 'owner-inv@example.test', false), \
         ('u_inv_member', 'member-inv@example.test', false), \
         ('u_inv_accept', 'accept-inv@example.test', false)",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) VALUES \
         ('t_inv', 'Invitation Tenant', 'invitation-tenant', 'u_inv_owner'), \
         ('t_inv_other', 'Other Invitation Tenant', 'other-invitation-tenant', 'u_inv_owner')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) VALUES \
         ('ut_inv_owner', 'u_inv_owner', 't_inv', 'owner'), \
         ('ut_inv_member', 'u_inv_member', 't_inv', 'member')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgInvitationRepository::new(pool.clone());
    assert_eq!(
        repo.tenant_admin_status("u_inv_owner", "t_inv")
            .await
            .unwrap(),
        TenantAdminStatus::Authorized
    );
    assert_eq!(
        repo.tenant_admin_status("u_inv_member", "t_inv")
            .await
            .unwrap(),
        TenantAdminStatus::NotAdmin
    );
    assert_eq!(
        repo.tenant_admin_status("u_inv_owner", "missing")
            .await
            .unwrap(),
        TenantAdminStatus::TenantNotFound
    );

    let created_at = sqlx::types::chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap();
    let expires_at = sqlx::types::chrono::DateTime::from_timestamp(1_700_604_800, 0).unwrap();
    let invitation = InvitationRecord {
        id: "inv_one".into(),
        tenant_id: "t_inv".into(),
        email: "invitee@example.test".into(),
        role: "member".into(),
        token: "inv-token-one".into(),
        status: "pending".into(),
        invited_by: "u_inv_owner".into(),
        accepted_by: None,
        expires_at,
        created_at,
        deleted_at: None,
    };
    repo.create(&invitation).await.unwrap();

    assert!(repo
        .find_pending_by_email_and_tenant(" INVITEE@EXAMPLE.TEST ", "t_inv")
        .await
        .unwrap()
        .is_some());
    assert_eq!(repo.count_pending_by_tenant("t_inv").await.unwrap(), 1);
    let listed = repo.list_pending_by_tenant("t_inv", 50, 0).await.unwrap();
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].id, "inv_one");
    assert_eq!(
        repo.find_by_token("inv-token-one")
            .await
            .unwrap()
            .expect("token lookup")
            .email,
        "invitee@example.test"
    );

    repo.update_status("inv_one", "accepted", Some("u_inv_accept"))
        .await
        .unwrap();
    let accepted = repo.find_by_id("inv_one").await.unwrap().unwrap();
    assert_eq!(accepted.status, "accepted");
    assert_eq!(accepted.accepted_by.as_deref(), Some("u_inv_accept"));
    repo.ensure_user_tenant_membership("ut_inv_accept", "u_inv_accept", "t_inv", "member")
        .await
        .unwrap();
    let membership = sqlx::query_as::<_, (String,)>(
        "SELECT role FROM user_tenants WHERE user_id = 'u_inv_accept' AND tenant_id = 't_inv'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(membership.0, "member");

    let mut cancel = invitation.clone();
    cancel.id = "inv_two".into();
    cancel.token = "inv-token-two".into();
    cancel.status = "pending".into();
    cancel.accepted_by = None;
    repo.create(&cancel).await.unwrap();
    repo.soft_delete("inv_two", created_at).await.unwrap();
    let cancelled = repo.find_by_id("inv_two").await.unwrap().unwrap();
    assert_eq!(cancelled.status, "cancelled");
    assert!(cancelled.deleted_at.is_some());
}
