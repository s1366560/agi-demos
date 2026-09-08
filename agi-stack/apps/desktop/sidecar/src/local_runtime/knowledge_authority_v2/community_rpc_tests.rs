use super::*;
use crate::local_runtime::{
    local_router, local_router_with_generation_required, workspace_core_bridge,
};
use axum::{
    body::{to_bytes, Body},
    extract::Path,
    http::{Request, StatusCode},
    routing::get,
};
use tower::ServiceExt;

async fn rpc(f: &CommunityFixture, write: bool, operation: Value) -> (StatusCode, Value) {
    let scope = operation_scope(&f.base.auth, &f.base.operation._lease);
    let body = if write {
        json!({"scope":scope,"command":operation})
    } else {
        json!({"scope":scope,"query":operation})
    };
    let path = if write {
        "/api/v1/knowledge/processing-command"
    } else {
        "/api/v1/knowledge/processing-query"
    };
    let response = local_router_with_generation_required(f.base.state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header("authorization", format!("Bearer {TOKEN}"))
                .header("x-agistack-launch", TOKEN)
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024)
        .await
        .unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

#[tokio::test]
async fn build_commands_are_idempotent_and_selection_is_revision_fenced() {
    let f = CommunityFixture::new().await;
    let create = json!({"operation":"create_community_build","idempotency_key":"rpc-create","min_community_size":2});
    let (status, first) = rpc(&f, true, create.clone()).await;
    assert_eq!(status, StatusCode::OK, "{first}");
    assert_eq!(rpc(&f, true, create).await.1, first);
    assert_eq!(rpc(&f,true,json!({"operation":"create_community_build","idempotency_key":"rpc-create","min_community_size":3})).await.0,StatusCode::CONFLICT);
    let build = &first["result"]["build"]["build_id"];
    let select = json!({"operation":"select_community_build","build_id":build,"expected_selection_revision":0});
    let (status, selected) = rpc(&f, true, select.clone()).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(selected["result"]["selection"]["revision"], 1);
    assert_eq!(rpc(&f, true, select).await.0, StatusCode::CONFLICT);
    let (status,activation)=rpc(&f,true,json!({"operation":"activate_community_build","build_id":build,"expected_selection_revision":1})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(activation["result"]["activated"], false);
    let (status, page) = rpc(
        &f,
        false,
        json!({"operation":"community_build","build_id":build,"offset":0,"limit":1}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(page["result"]["page"]["items"].as_array().unwrap().len(), 1);
    assert_eq!(page["result"]["page"]["status"]["state"], "pending");
}

#[tokio::test]
async fn community_queries_are_scoped_and_writer_commands_reject_viewers() {
    let f = CommunityFixture::new().await;
    let (status, active) = rpc(&f, false, json!({"operation":"community_active"})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(active["result"]["selection"]["revision"], 0);
    assert!(active["result"]["current_status"].is_null());
    assert_eq!(
        rpc(
            &f,
            false,
            json!({"operation":"community_build","build_id":f.input.build_id,"offset":0,"limit":0})
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let (status, missing) = rpc(
        &f,
        false,
        json!({"operation":"community_build","build_id":"foreign-build","offset":0,"limit":1}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(missing["result"]["page"].is_null());
    f.base
        .state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_tenant_memberships SET role='viewer'")
        .unwrap();
    assert_eq!(
        rpc(&f, false, json!({"operation":"community_active"}))
            .await
            .0,
        StatusCode::OK
    );
    assert_eq!(rpc(&f,true,json!({"operation":"create_community_build","idempotency_key":"viewer","min_community_size":2})).await.0,StatusCode::FORBIDDEN);
}

struct CoreEndpoint(tokio::task::JoinHandle<()>);
#[tokio::test]
async fn unselected_build_receipt_is_recoverable_through_history() {
    let f = CommunityFixture::new().await;
    let (status, receipt) = rpc(&f, true, json!({"operation":"create_community_build","idempotency_key":"lost-response","min_community_size":2})).await;
    assert_eq!(status, StatusCode::OK);
    let (status, history) = rpc(&f, false, json!({"operation":"community_builds","offset":0,"limit":20})).await;
    assert_eq!(status, StatusCode::OK, "{history}");
    assert!(history["result"]["page"]["items"].as_array().unwrap().contains(&receipt["result"]["build"]));
    let (_, active) = rpc(&f, false, json!({"operation":"community_active"})).await;
    assert_eq!(active["result"]["selection"]["revision"], 0);
    assert_eq!(rpc(&f, false, json!({"operation":"community_builds","offset":0,"limit":101})).await.0, StatusCode::UNPROCESSABLE_ENTITY);
}
impl Drop for CoreEndpoint {
    fn drop(&mut self) {
        self.0.abort();
    }
}

async fn install_provider(f: &CommunityFixture, endpoint: &CommunityEndpoint) -> CoreEndpoint {
    let configured=local_router(f.base.state.clone()).oneshot(Request::builder().method("PUT")
        .uri("/api/v1/llm-providers/local-runtime").header("authorization",format!("Bearer {TOKEN}"))
        .header("x-agistack-launch",TOKEN).header("content-type","application/json")
        .body(Body::from(json!({"provider_type":"openai_compatible","base_url":endpoint.base,"auth_method":"none","llm_model":"fixture-model","allowed_models":["fixture-model"],"is_active":true,"expected_revision":0}).to_string())).unwrap()).await.unwrap();
    assert_eq!(configured.status(), StatusCode::OK);
    let app=Router::new().route("/api/v1/tenants/:tenant/projects/:project/workspaces/:workspace",get(|Path((tenant,project,workspace)):Path<(String,String,String)>|async move {Json(json!({"id":workspace,"tenant_id":tenant,"project_id":project}))}))
        .route("/api/v1/tenants/:tenant/projects/:project/workspaces/:workspace/agent-policy",get(|Path((tenant,project,workspace)):Path<(String,String,String)>|async move {Json(json!({"workspace_id":workspace,"tenant_id":tenant,"project_id":project,"roles":{"default":{"provider_id":"local-runtime","model_id":"fixture-model"},"fast":null,"coding":null,"vision":null},"fallbacks":[]}))}));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}/", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    workspace_core_bridge::install_authority(
        &f.base.state,
        base,
        "fixture-service".into(),
        "fixture-registry".into(),
        "fixture-webhook".into(),
        "fixture-event".into(),
    )
    .unwrap();
    CoreEndpoint(task)
}

#[tokio::test]
async fn public_community_worker_uses_provider_and_only_explicit_activation_publishes() {
    let f = Arc::new(CommunityFixture::new().await);
    let endpoint = CommunityEndpoint::new(&f, f.output(true)).await;
    let _core = install_provider(&f, &endpoint).await;
    let copy = f.clone();
    let run = tokio::spawn(async move {
        rpc(&copy,true,json!({"operation":"process_community_one","build_id":copy.input.build_id,"workspace_id":"explicit-workspace"})).await
    });
    endpoint.wait().await;
    endpoint.release.notify_one();
    let (status, response) = run.await.unwrap();
    assert_eq!(status, StatusCode::OK, "{response}");
    assert_eq!(response["result"]["receipt"]["status"], "applied");
    assert!(response["result"]["receipt"].get("invocation").is_none());
    let (_, active) = rpc(&f, false, json!({"operation":"community_active"})).await;
    assert!(active["result"]["current_status"].is_null());
    assert_eq!(rpc(&f,true,json!({"operation":"select_community_build","build_id":f.input.build_id,"expected_selection_revision":0})).await.0,StatusCode::OK);
    let (_,activated)=rpc(&f,true,json!({"operation":"activate_community_build","build_id":f.input.build_id,"expected_selection_revision":1})).await;
    assert_eq!(activated["result"]["activated"], true);
    let (_, active) = rpc(&f, false, json!({"operation":"community_active"})).await;
    assert_eq!(active["result"]["current_status"]["ready_count"], 1);
    let (_, page) = rpc(
        &f,
        false,
        json!({"operation":"community_build","build_id":f.input.build_id,"offset":0,"limit":20}),
    )
    .await;
    assert_eq!(
        page["result"]["page"]["items"][0]["result"]["submission"]["decision"]["name"],
        "Cedar maintenance"
    );
    let (_,audit)=rpc(&f,false,json!({"operation":"community_audit","build_id":f.input.build_id,"candidate_id":f.input.candidate.membership_digest,"attempt":1})).await;
    assert_eq!(audit["result"]["audit"]["provider_id"], "local-runtime");
    assert_eq!(rpc(&f,true,json!({"operation":"create_community_build","idempotency_key":"unselected-history","min_community_size":2})).await.0,StatusCode::OK);
    let (status,history)=rpc(&f,false,json!({"operation":"community_builds","offset":0,"limit":20})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(history["result"]["page"]["total"], 2);
    if let Ok(path) = std::env::var("AGISTACK_COMMUNITY_RPC_FIXTURE") {
        let fixture = json!({"scope":operation_scope(&f.base.auth,&f.base.operation._lease),
        "query_cases":[
            {"query":{"operation":"community_active"},"response":active},
            {"query":{"operation":"community_build","build_id":f.input.build_id,"offset":0,"limit":20},"response":page},
            {"query":{"operation":"community_audit","build_id":f.input.build_id,"candidate_id":f.input.candidate.membership_digest,"attempt":1},"response":audit},
            {"query":{"operation":"community_builds","offset":0,"limit":20},"response":history}
        ],"command_cases":[
            {"command":{"operation":"process_community_one","build_id":f.input.build_id,"workspace_id":"explicit-workspace"},"response":response}
        ]});
        std::fs::write(path, serde_json::to_vec(&fixture).unwrap()).unwrap();
    }
    let mut memory = f
        .base
        .operation
        .get(&f.base.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.content = "changed source".into();
    f.base
        .repo()
        .update(&f.base.operation.scope, memory, 1)
        .await
        .unwrap();
    let (_, active) = rpc(&f, false, json!({"operation":"community_active"})).await;
    assert!(active["result"]["current_status"].is_null());
    assert_eq!(active["result"]["stale_build_id"], f.input.build_id);
}
