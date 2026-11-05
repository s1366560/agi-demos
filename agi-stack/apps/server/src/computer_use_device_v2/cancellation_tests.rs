use super::*;
use futures_util::{SinkExt, StreamExt};

pub(super) async fn pg_fixture() -> Option<sqlx::PgPool> {
    let Ok(url) = std::env::var("AGISTACK_TEST_DATABASE_URL") else {
        return None;
    };
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .max_lifetime(None)
        .idle_timeout(None)
        .connect(&url)
        .await
        .unwrap();
    for statement in [
        "CREATE TEMP TABLE users (id text PRIMARY KEY, is_active boolean)",
        "CREATE TEMP TABLE projects (id text PRIMARY KEY, tenant_id text)",
        "CREATE TEMP TABLE conversations (id text PRIMARY KEY, user_id text, tenant_id text, project_id text)",
        "CREATE TEMP TABLE user_projects (user_id text, project_id text)",
        "CREATE TEMP TABLE user_tenants (user_id text, tenant_id text)",
        "CREATE TEMP TABLE agent_run_authorities (LIKE public.agent_run_authorities INCLUDING DEFAULTS)",
        "CREATE TEMP TABLE hitl_requests (LIKE public.hitl_requests INCLUDING DEFAULTS INCLUDING INDEXES)",
        "INSERT INTO users VALUES ('dev-user',true),('other-user',true)",
        "INSERT INTO projects VALUES ('dev-project','dev-tenant'),('other-project','other-tenant')",
        "INSERT INTO user_projects VALUES ('dev-user','dev-project'),('other-user','dev-project')",
        "INSERT INTO user_tenants VALUES ('dev-user','dev-tenant'),('other-user','dev-tenant')",
    ] {
        sqlx::query(statement).execute(&pool).await.unwrap();
    }
    Some(pool)
}

async fn insert_run(pool: &sqlx::PgPool, conversation: &str, id: &str) {
    sqlx::query("INSERT INTO agent_run_authorities (id,tenant_id,project_id,conversation_id,run_kind,idempotency_key,message_id,request_message,status,revision,permission_profile,authorization_snapshot) VALUES ($1,'dev-tenant','dev-project',$2,'chat',$1,$1,'Neutral fixture','running',3,'read_only','{}')")
        .bind(id).bind(conversation).execute(pool).await.unwrap();
}

async fn receive_reply(
    socket: &mut tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
) -> Value {
    tokio::time::timeout(std::time::Duration::from_secs(3), async {
        loop {
            let message = socket.next().await.unwrap().unwrap();
            if message.is_text() {
                let value: Value = serde_json::from_str(message.to_text().unwrap()).unwrap();
                if (value["type"] == "ack" && value["action"] == "stop_session")
                    || value["type"] == "error"
                {
                    return value;
                }
            }
        }
    })
    .await
    .unwrap()
}

#[tokio::test]
async fn orphan_chat_stop_uses_postgres_authority_without_an_executor_or_device() {
    let Some(pool) = pg_fixture().await else {
        return;
    };
    let mut app = crate::prod_api::unit::test_state();
    let conversation = app
        .agent_conversations
        .create_conversation(
            "dev-user",
            serde_json::from_value(
                json!({"project_id":"dev-project","title":"Owned stop fixture"}),
            )
            .unwrap(),
        )
        .await
        .unwrap();
    let conversation_id = serde_json::to_value(conversation).unwrap()["id"]
        .as_str()
        .unwrap()
        .to_owned();
    sqlx::query("INSERT INTO conversations VALUES ($1,'dev-user','dev-tenant','dev-project')")
        .bind(&conversation_id)
        .execute(&pool)
        .await
        .unwrap();
    insert_run(&pool, &conversation_id, "orphan").await;
    insert_run(&pool, &conversation_id, "foreign-tenant").await;
    sqlx::query(
        "UPDATE agent_run_authorities SET tenant_id='other-tenant' WHERE id='foreign-tenant'",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO hitl_requests (id,request_type,conversation_id,tenant_id,project_id,user_id,question,status,expires_at,request_metadata) VALUES ('pending','permission',$1,'dev-tenant','dev-project','dev-user','Neutral fixture','pending',NOW()+INTERVAL '1 hour','{\"native_computer_use\":{\"run_id\":\"orphan\"}}')")
        .bind(&conversation_id).execute(&pool).await.unwrap();
    app.computer_use_devices = Broker::new(
        Arc::new(authority::PgAuthority {
            pool: Some(pool.clone()),
            workspace: app.workspace_authority.clone(),
        }),
        Arc::new(InMemoryObjectStore::new()),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let router = axum::Router::new()
        .route("/api/v1/agent/ws", get(crate::agent_ws::agent_ws))
        .with_state(app);
    let server = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    let (mut socket, _) = tokio_tungstenite::connect_async(format!(
        "ws://{address}/api/v1/agent/ws?token=ms_sk_fixture"
    ))
    .await
    .unwrap();
    let stop = json!({"type":"stop_session","conversation_id":conversation_id}).to_string();
    socket
        .send(tokio_tungstenite::tungstenite::Message::Text(stop.clone()))
        .await
        .unwrap();
    let reply = receive_reply(&mut socket).await;
    assert_eq!(reply["type"], "ack", "{reply}");
    assert_eq!(reply["action"], "stop_session");
    let row: (String,i32,bool) = sqlx::query_as("SELECT status,revision,completed_at IS NOT NULL FROM agent_run_authorities WHERE id='orphan'").fetch_one(&pool).await.unwrap();
    assert_eq!(row, ("cancelled".into(), 4, true));
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM hitl_requests WHERE id='pending'")
            .fetch_one(&pool)
            .await
            .unwrap(),
        "cancelled"
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT status FROM agent_run_authorities WHERE id='foreign-tenant'"
        )
        .fetch_one(&pool)
        .await
        .unwrap(),
        "running"
    );
    socket
        .send(tokio_tungstenite::tungstenite::Message::Text(stop))
        .await
        .unwrap();
    assert_eq!(
        receive_reply(&mut socket).await["data"]["code"],
        "SESSION_NOT_RUNNING"
    );
    socket.close(None).await.unwrap();
    server.abort();
    pool.close().await;
}

#[tokio::test]
async fn orphan_unsupported_human_request_cannot_silently_leave_a_native_run_parked() {
    let (broker, _, _) = fixture();
    let mut app = crate::prod_api::unit::test_state();
    app.computer_use_devices = broker.clone();
    let bound = BoundRun {
        owner: owner(),
        run: run(),
        tools: Arc::new(app.registry.clone()),
        broker,
        parked: false,
    };
    let mut state =
        agistack_core::SessionState::new("engine-session", "Neutral fixture", Some("project"));
    state.status = agistack_core::SessionStatus::AwaitingInput;
    state.pending_hitl = Some(agistack_core::HitlRequest::new(
        "generic-request",
        agistack_core::HitlKind::Permission,
        "Neutral fixture",
    ));
    struct Observer;
    #[async_trait]
    impl agistack_core::agent::ReActObserver for Observer {}
    let result = park(
        &app,
        bound,
        app.engine.clone(),
        Arc::new(Observer),
        &state,
        "conversation",
        Some("message"),
    )
    .await;
    assert!(
        result.is_err(),
        "unsupported suspension must produce a terminal error"
    );
    assert!(app.computer_use_devices.pending.lock().unwrap().is_empty());
}

#[tokio::test]
async fn orphan_stop_rejects_foreign_owner_revoked_membership_and_rolls_back_failed_cleanup() {
    let Some(pool) = pg_fixture().await else {
        return;
    };
    sqlx::query("INSERT INTO conversations VALUES ('owned','dev-user','dev-tenant','dev-project')")
        .execute(&pool)
        .await
        .unwrap();
    insert_run(&pool, "owned", "orphan").await;
    let pg = authority::PgAuthority {
        pool: Some(pool.clone()),
        workspace: Arc::new(crate::workspace_authority::UnavailableWorkspaceAuthority),
    };
    assert!(pg
        .cancel_chat("other-user", "owned")
        .await
        .unwrap()
        .is_empty());
    assert!(pg
        .cancel_chat("dev-user", "missing")
        .await
        .unwrap()
        .is_empty());
    sqlx::query("DELETE FROM pg_temp.user_projects WHERE user_id='dev-user'")
        .execute(&pool)
        .await
        .unwrap();
    assert!(pg
        .cancel_chat("dev-user", "owned")
        .await
        .unwrap()
        .is_empty());
    sqlx::query("INSERT INTO pg_temp.user_projects VALUES ('dev-user','dev-project')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("ALTER TABLE pg_temp.hitl_requests DROP COLUMN request_metadata")
        .execute(&pool)
        .await
        .unwrap();
    assert!(pg.cancel_chat("dev-user", "owned").await.is_err());
    assert_eq!(
        sqlx::query_as::<_, (String, i32)>(
            "SELECT status,revision FROM agent_run_authorities WHERE id='orphan'"
        )
        .fetch_one(&pool)
        .await
        .unwrap(),
        ("running".into(), 3)
    );
    pool.close().await;
}

#[tokio::test]
async fn orphan_park_failure_writes_exact_failed_chat_revision() {
    let Some(pool) = pg_fixture().await else {
        return;
    };
    sqlx::query("INSERT INTO conversations VALUES ('owned','dev-user','dev-tenant','dev-project')")
        .execute(&pool)
        .await
        .unwrap();
    insert_run(&pool, "owned", "orphan").await;
    let mut app = crate::prod_api::unit::test_state();
    app.computer_use_devices = Broker::new(
        Arc::new(authority::PgAuthority {
            pool: Some(pool.clone()),
            workspace: app.workspace_authority.clone(),
        }),
        Arc::new(InMemoryObjectStore::new()),
    );
    let mut chat = run();
    chat.run_id = "orphan".into();
    chat.run_kind = "chat".into();
    let bound = BoundRun {
        owner: Owner {
            user_id: "dev-user".into(),
            tenant_id: "dev-tenant".into(),
            project_id: "dev-project".into(),
        },
        run: chat,
        tools: Arc::new(app.registry.clone()),
        broker: app.computer_use_devices.clone(),
        parked: false,
    };
    let mut state =
        agistack_core::SessionState::new("engine-session", "Neutral fixture", Some("dev-project"));
    state.status = agistack_core::SessionStatus::AwaitingInput;
    state.pending_hitl = Some(agistack_core::HitlRequest::new(
        "generic",
        agistack_core::HitlKind::Clarification,
        "Neutral fixture",
    ));
    struct Observer;
    #[async_trait]
    impl agistack_core::agent::ReActObserver for Observer {}
    assert!(park(
        &app,
        bound,
        app.engine.clone(),
        Arc::new(Observer),
        &state,
        "owned",
        Some("message")
    )
    .await
    .is_err());
    assert_eq!(
        sqlx::query_as::<_, (String, i32, String)>(
            "SELECT status,revision,error FROM agent_run_authorities WHERE id='orphan'"
        )
        .fetch_one(&pool)
        .await
        .unwrap(),
        (
            "failed".into(),
            4,
            "computer_use_human_request_not_parked".into()
        )
    );
    pool.close().await;
}

#[tokio::test]
async fn orphan_cancel_revokes_exact_run_requests_and_keeps_other_connections_registered() {
    let Some(pool) = pg_fixture().await else {
        return;
    };
    sqlx::query("INSERT INTO conversations VALUES ('owned','dev-user','dev-tenant','dev-project')")
        .execute(&pool)
        .await
        .unwrap();
    insert_run(&pool, "owned", "orphan").await;
    let (mut broker, _, mut receive) = fixture();
    let own = Owner {
        user_id: "dev-user".into(),
        tenant_id: "dev-tenant".into(),
        project_id: "dev-project".into(),
    };
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .owner = own.clone();
    let mut ids = vec![];
    for (conversation, run_id) in [("owned", "orphan"), ("other-conversation", "other-run")] {
        let mut parent = run();
        parent.run_id = run_id.into();
        parent.run_kind = "chat".into();
        let cloned = broker.clone();
        let owner = own.clone();
        let call = tokio::spawn(async move {
            cloned
                .request(
                    &owner,
                    conversation,
                    &parent,
                    &context(1, "computer_get_app_state"),
                    "{}",
                )
                .await
        });
        let id = receive.recv().await.unwrap()["request_id"]
            .as_str()
            .unwrap()
            .to_owned();
        broker.claim(&id, "dev-user", "device").unwrap();
        broker
            .receive_result("connection", &id, "{}".into(), false, vec![])
            .unwrap();
        call.await.unwrap().unwrap();
        ids.push(id);
    }
    let mut other = broker.devices.lock().unwrap()["connection"].clone();
    other.connection_id = "other-connection".into();
    other.device_id = "other-device".into();
    broker
        .devices
        .lock()
        .unwrap()
        .insert("other-connection".into(), other);
    let mut app = crate::prod_api::unit::test_state();
    broker.authority = Some(Arc::new(authority::PgAuthority {
        pool: Some(pool.clone()),
        workspace: app.workspace_authority.clone(),
    }));
    app.computer_use_devices = broker.clone();
    assert!(cancel_owned_chat(&app, "dev-user", "owned").await.unwrap());
    assert!(broker.requests.lock().unwrap()[&ids[0]].cancelled);
    assert!(!broker.requests.lock().unwrap()[&ids[1]].cancelled);
    assert_eq!(broker.devices.lock().unwrap().len(), 2);
    assert!(broker
        .resume_authority(&ids[0], "dev-user", "device", "engine-session")
        .await
        .is_err());
    assert!(!cancel_owned_chat(&app, "dev-user", "owned").await.unwrap());
    pool.close().await;
}
