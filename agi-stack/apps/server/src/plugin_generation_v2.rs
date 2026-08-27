//! Protocol-v2 admission authority for Rust server request lifetimes.

use std::{
    pin::Pin,
    sync::{Arc, Mutex},
    task::{Context as TaskContext, Poll},
};

use agistack_plugin_host::{
    DataPlaneTargetV2, GenerationLeaseV2, GenerationManagerV2, RuntimeV2Error,
    RustServerHttpRouteContributionV2, ScopeKindV2, ScopeV2, TargetHostDescriptorV2,
    RUST_SERVER_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2, RUST_SERVER_HOST_SERVICE_V2,
    RUST_SERVER_HTTP_ROUTES_SERVICE_V2, RUST_SERVER_HTTP_ROUTE_STRATEGY_V2,
};
use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    middleware::{self, Next},
    response::{IntoResponse, Response},
    Json, Router,
};
use http_body::{Body as HttpBody, Frame, SizeHint};
use serde::Serialize;
use tokio::sync::{oneshot, Notify};

pub(crate) const RUST_SERVER_GENERATION_STRATEGY_V2: &str = "generated-catalog-bootstrap";
const RUST_SERVER_TARGET_V2: &str = "rust-server";
const RUST_SERVER_HOST_SERVICE_VERSION_V2: &str = "1.0.0";
const RUST_SERVER_HTTP_ROUTES_SERVICE_VERSION_V2: &str = "1.0.0";

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct RustServerRequestGenerationV2 {
    pub(crate) profile_id: String,
    pub(crate) generation: u64,
    pub(crate) digest: String,
    pub(crate) target: DataPlaneTargetV2,
    pub(crate) strategy: String,
    pub(crate) route_contribution_id: String,
    pub(crate) route_strategy: String,
}

#[derive(Default)]
struct AdmissionStateV2 {
    accepting: bool,
    in_flight: usize,
    release_error: Option<RuntimeV2Error>,
}

struct AdmissionInnerV2 {
    manager: Arc<GenerationManagerV2>,
    state: Mutex<AdmissionStateV2>,
    drained: Notify,
}

#[derive(Clone)]
pub(crate) struct RustServerGenerationAdmissionV2 {
    inner: Arc<AdmissionInnerV2>,
}

impl RustServerGenerationAdmissionV2 {
    #[must_use]
    pub(crate) fn new(manager: Arc<GenerationManagerV2>) -> Self {
        Self {
            inner: Arc::new(AdmissionInnerV2 {
                manager,
                state: Mutex::new(AdmissionStateV2 {
                    accepting: true,
                    ..AdmissionStateV2::default()
                }),
                drained: Notify::new(),
            }),
        }
    }

    pub(crate) fn bind(&self, router: Router) -> Router {
        router.layer(middleware::from_fn_with_state(
            self.clone(),
            require_generation_v2,
        ))
    }

    #[cfg(test)]
    #[must_use]
    pub(crate) fn manager(&self) -> &GenerationManagerV2 {
        &self.inner.manager
    }

    pub(crate) async fn shutdown(&self) -> Result<(), RuntimeV2Error> {
        self.stop();
        let drain_result = self.drain().await;
        self.inner.manager.close().await;
        drain_result
    }

    fn stop(&self) {
        let mut state = lock(&self.inner.state);
        state.accepting = false;
        let drained = state.in_flight == 0;
        drop(state);
        if drained {
            self.inner.drained.notify_one();
        }
    }

    async fn drain(&self) -> Result<(), RuntimeV2Error> {
        loop {
            let notified = self.inner.drained.notified();
            let drained_result = {
                let mut state = lock(&self.inner.state);
                (state.in_flight == 0).then(|| state.release_error.take().map_or(Ok(()), Err))
            };
            if let Some(result) = drained_result {
                return result;
            }
            notified.await;
        }
    }

    fn admit(
        &self,
    ) -> Result<
        (RustServerRequestGenerationV2, GenerationReleaseGuardV2),
        GenerationAdmissionRejectionV2,
    > {
        let (lease, descriptor_result) = {
            let mut state = lock(&self.inner.state);
            if !state.accepting {
                return Err(GenerationAdmissionRejectionV2::new(
                    "generation_admission_stopped",
                    "protocol-v2 generation admission is stopped",
                ));
            }
            let next_in_flight = state.in_flight.checked_add(1).ok_or_else(|| {
                GenerationAdmissionRejectionV2::new(
                    "generation_admission_capacity_exhausted",
                    "protocol-v2 generation admission capacity is exhausted",
                )
            })?;
            let lease = self
                .inner
                .manager
                .acquire()
                .map_err(GenerationAdmissionRejectionV2::runtime)?;
            let descriptor_result = request_descriptor_v2(&lease);
            state.in_flight = next_in_flight;
            (lease, descriptor_result)
        };

        let guard = self.spawn_release_owner(lease);
        match descriptor_result {
            Ok(descriptor) => Ok((descriptor, guard)),
            Err(error) => {
                drop(guard);
                Err(error)
            }
        }
    }

    fn spawn_release_owner(&self, lease: GenerationLeaseV2) -> GenerationReleaseGuardV2 {
        let (release_tx, release_rx) = oneshot::channel();
        let inner = Arc::clone(&self.inner);
        tokio::spawn(async move {
            let _ = release_rx.await;
            let release_result = lease.release().await;
            let mut state = lock(&inner.state);
            if let Err(error) = release_result {
                state.release_error.get_or_insert(error);
            }
            if state.in_flight == 0 {
                state
                    .release_error
                    .get_or_insert(RuntimeV2Error::LeaseUnderflow);
            } else {
                state.in_flight -= 1;
            }
            let drained = state.in_flight == 0;
            drop(state);
            if drained {
                inner.drained.notify_one();
            }
        });
        GenerationReleaseGuardV2 {
            release_tx: Some(release_tx),
        }
    }

    #[cfg(test)]
    fn in_flight_for_test(&self) -> usize {
        lock(&self.inner.state).in_flight
    }
}

fn request_descriptor_v2(
    lease: &GenerationLeaseV2,
) -> Result<RustServerRequestGenerationV2, GenerationAdmissionRejectionV2> {
    let generation = lease
        .generation()
        .map_err(GenerationAdmissionRejectionV2::runtime)?;
    let root_scope = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    let descriptor = generation
        .resolve_versioned::<TargetHostDescriptorV2>(
            RUST_SERVER_HOST_SERVICE_V2,
            RUST_SERVER_HOST_SERVICE_VERSION_V2,
            &root_scope,
            None,
        )
        .map_err(GenerationAdmissionRejectionV2::runtime)?;
    if descriptor.target != RUST_SERVER_TARGET_V2 {
        return Err(GenerationAdmissionRejectionV2::new(
            "invalid_rust_server_generation_target",
            "protocol-v2 generation does not target the Rust server",
        ));
    }
    if descriptor.strategy != RUST_SERVER_GENERATION_STRATEGY_V2 {
        return Err(GenerationAdmissionRejectionV2::new(
            "invalid_rust_server_generation_strategy",
            "protocol-v2 generation uses an incompatible Rust server strategy",
        ));
    }
    let routes = generation
        .resolve_versioned::<RustServerHttpRouteContributionV2>(
            RUST_SERVER_HTTP_ROUTES_SERVICE_V2,
            RUST_SERVER_HTTP_ROUTES_SERVICE_VERSION_V2,
            &root_scope,
            None,
        )
        .map_err(GenerationAdmissionRejectionV2::runtime)?;
    if routes.contribution_id != RUST_SERVER_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2 {
        return Err(GenerationAdmissionRejectionV2::new(
            "invalid_rust_server_route_contribution",
            "protocol-v2 generation declares an unknown Rust server route contribution",
        ));
    }
    if routes.strategy != RUST_SERVER_HTTP_ROUTE_STRATEGY_V2 {
        return Err(GenerationAdmissionRejectionV2::new(
            "invalid_rust_server_route_strategy",
            "protocol-v2 generation uses an incompatible Rust server route strategy",
        ));
    }
    Ok(RustServerRequestGenerationV2 {
        profile_id: generation.snapshot.profile_id.clone(),
        generation: generation.snapshot.generation,
        digest: generation.snapshot.digest.clone(),
        target: DataPlaneTargetV2::RustServer,
        strategy: descriptor.strategy.clone(),
        route_contribution_id: routes.contribution_id.clone(),
        route_strategy: routes.strategy.clone(),
    })
}

async fn require_generation_v2(
    State(admission): State<RustServerGenerationAdmissionV2>,
    mut request: Request,
    next: Next,
) -> Response {
    let (descriptor, guard) = match admission.admit() {
        Ok(admission) => admission,
        Err(error) => return error.into_response(),
    };
    request.extensions_mut().insert(descriptor);
    let response = next.run(request).await;
    let (parts, body) = response.into_parts();
    Response::from_parts(parts, Body::new(GenerationLeaseBodyV2::new(body, guard)))
}

struct GenerationReleaseGuardV2 {
    release_tx: Option<oneshot::Sender<()>>,
}

impl Drop for GenerationReleaseGuardV2 {
    fn drop(&mut self) {
        if let Some(release_tx) = self.release_tx.take() {
            let _ = release_tx.send(());
        }
    }
}

struct GenerationLeaseBodyV2<B> {
    inner: Pin<Box<B>>,
    guard: Option<GenerationReleaseGuardV2>,
}

impl<B> GenerationLeaseBodyV2<B> {
    fn new(inner: B, guard: GenerationReleaseGuardV2) -> Self {
        Self {
            inner: Box::pin(inner),
            guard: Some(guard),
        }
    }
}

impl<B> HttpBody for GenerationLeaseBodyV2<B>
where
    B: HttpBody,
{
    type Data = B::Data;
    type Error = B::Error;

    fn poll_frame(
        self: Pin<&mut Self>,
        context: &mut TaskContext<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        let this = self.get_mut();
        let frame = this.inner.as_mut().poll_frame(context);
        if matches!(&frame, Poll::Ready(None) | Poll::Ready(Some(Err(_)))) {
            this.guard.take();
        }
        frame
    }

    fn is_end_stream(&self) -> bool {
        self.inner.is_end_stream()
    }

    fn size_hint(&self) -> SizeHint {
        self.inner.size_hint()
    }
}

struct GenerationAdmissionRejectionV2 {
    code: &'static str,
    message: String,
}

impl GenerationAdmissionRejectionV2 {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    fn runtime(error: RuntimeV2Error) -> Self {
        Self::new(error.code(), error.to_string())
    }
}

#[derive(Serialize)]
struct GenerationAdmissionErrorEnvelopeV2 {
    error: GenerationAdmissionErrorBodyV2,
}

#[derive(Serialize)]
struct GenerationAdmissionErrorBodyV2 {
    code: &'static str,
    message: String,
}

impl IntoResponse for GenerationAdmissionRejectionV2 {
    fn into_response(self) -> Response {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(GenerationAdmissionErrorEnvelopeV2 {
                error: GenerationAdmissionErrorBodyV2 {
                    code: self.code,
                    message: self.message,
                },
            }),
        )
            .into_response()
    }
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use std::{
        collections::BTreeMap,
        convert::Infallible,
        sync::{
            atomic::{AtomicBool, Ordering},
            Arc,
        },
        time::Duration,
    };

    use agistack_plugin_host::{
        parse_profile_snapshot_v2, rust_server_host_definition_v2,
        rust_server_http_routes_definition_v2, ContextV2, DataPlaneTargetV2, GenerationManagerV2,
        LoaderV2, PluginDefinitionV2, PluginModuleRuntimeV2, RuntimeGenerationV2, RuntimeV2Error,
        RustServerHttpRouteContributionV2, TargetHostDescriptorV2,
        RUST_SERVER_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2, RUST_SERVER_HOST_MODULE_REF_V2,
        RUST_SERVER_HOST_SERVICE_V2, RUST_SERVER_HTTP_ROUTES_MODULE_REF_V2,
        RUST_SERVER_HTTP_ROUTES_SERVICE_V2, RUST_SERVER_HTTP_ROUTE_STRATEGY_V2,
    };
    use async_trait::async_trait;
    use axum::{
        body::{to_bytes, Body, Bytes},
        extract::Request,
        http::{header::HeaderName, HeaderValue, StatusCode},
        response::{IntoResponse, Response},
        routing::get,
        Extension, Json, Router,
    };
    use futures_util::{stream, StreamExt};
    use serde_json::{json, Value};
    use tower::ServiceExt;

    use super::{
        RustServerGenerationAdmissionV2, RustServerRequestGenerationV2,
        RUST_SERVER_GENERATION_STRATEGY_V2,
    };

    const SNAPSHOT: &str =
        include_str!("../../../../shared/profiles/memstack-default-bootstrap.v2.json");
    const DIGEST_HEADER: HeaderName = HeaderName::from_static("x-test-generation-digest");

    #[derive(Clone)]
    enum TestHostValueV2 {
        Descriptor(TargetHostDescriptorV2),
        WrongType,
    }

    struct TestHostModuleV2 {
        value: TestHostValueV2,
    }

    #[derive(Clone)]
    enum TestRouteValueV2 {
        Descriptor(RustServerHttpRouteContributionV2),
        WrongType,
    }

    struct TestRouteModuleV2 {
        value: TestRouteValueV2,
    }

    #[async_trait]
    impl PluginModuleRuntimeV2 for TestHostModuleV2 {
        async fn apply(
            &self,
            context: &mut ContextV2,
            _config: &BTreeMap<String, Value>,
        ) -> Result<(), RuntimeV2Error> {
            match &self.value {
                TestHostValueV2::Descriptor(descriptor) => {
                    context.provide(RUST_SERVER_HOST_SERVICE_V2, descriptor.clone())?;
                }
                TestHostValueV2::WrongType => {
                    context.provide(RUST_SERVER_HOST_SERVICE_V2, 7_u64)?;
                }
            }
            Ok(())
        }
    }

    #[async_trait]
    impl PluginModuleRuntimeV2 for TestRouteModuleV2 {
        async fn apply(
            &self,
            context: &mut ContextV2,
            _config: &BTreeMap<String, Value>,
        ) -> Result<(), RuntimeV2Error> {
            match &self.value {
                TestRouteValueV2::Descriptor(descriptor) => {
                    context.provide(RUST_SERVER_HTTP_ROUTES_SERVICE_V2, descriptor.clone())?;
                }
                TestRouteValueV2::WrongType => {
                    context.provide(RUST_SERVER_HTTP_ROUTES_SERVICE_V2, 7_u64)?;
                }
            }
            Ok(())
        }
    }

    fn test_definition(value: TestHostValueV2) -> PluginDefinitionV2 {
        let mut definition = rust_server_host_definition_v2();
        definition.module = Arc::new(TestHostModuleV2 { value });
        definition
    }

    fn test_route_definition(value: TestRouteValueV2) -> PluginDefinitionV2 {
        let mut definition = rust_server_http_routes_definition_v2();
        definition.module = Arc::new(TestRouteModuleV2 { value });
        definition
    }

    async fn stage_generation_with(
        host_definition: Option<PluginDefinitionV2>,
        route_definition: Option<PluginDefinitionV2>,
        profile_id: &str,
        generation: u64,
        digest: &str,
    ) -> Arc<RuntimeGenerationV2> {
        let mut snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("snapshot must parse");
        snapshot.profile_id = profile_id.to_owned();
        snapshot.generation = generation;
        snapshot.digest = digest.to_owned();
        if host_definition.is_none() {
            snapshot.entries.retain(|entry| {
                entry.module_ref != RUST_SERVER_HOST_MODULE_REF_V2
                    && entry.module_ref != RUST_SERVER_HTTP_ROUTES_MODULE_REF_V2
            });
        } else if route_definition.is_none() {
            snapshot
                .entries
                .retain(|entry| entry.module_ref != RUST_SERVER_HTTP_ROUTES_MODULE_REF_V2);
        }
        LoaderV2::for_target(
            DataPlaneTargetV2::RustServer,
            host_definition.into_iter().chain(route_definition),
        )
        .stage(snapshot)
        .await
        .expect("test generation must stage")
    }

    async fn stage_generation(
        host_definition: Option<PluginDefinitionV2>,
        profile_id: &str,
        generation: u64,
        digest: &str,
    ) -> Arc<RuntimeGenerationV2> {
        stage_generation_with(
            host_definition,
            Some(rust_server_http_routes_definition_v2()),
            profile_id,
            generation,
            digest,
        )
        .await
    }

    async fn admission_with(
        generation: Option<Arc<RuntimeGenerationV2>>,
    ) -> RustServerGenerationAdmissionV2 {
        let manager = Arc::new(GenerationManagerV2::new());
        if let Some(generation) = generation {
            manager.publish(generation).await;
        }
        RustServerGenerationAdmissionV2::new(manager)
    }

    fn request(path: &str) -> Request {
        Request::builder()
            .uri(path)
            .body(Body::empty())
            .expect("request must build")
    }

    async fn descriptor_probe(
        Extension(descriptor): Extension<RustServerRequestGenerationV2>,
    ) -> Json<RustServerRequestGenerationV2> {
        Json(descriptor)
    }

    async fn streaming_probe(
        Extension(descriptor): Extension<RustServerRequestGenerationV2>,
    ) -> Response {
        let body = stream::once(async {
            Ok::<Bytes, Infallible>(Bytes::from_static(b"generation-stream"))
        })
        .chain(stream::pending());
        let mut response = Body::from_stream(body).into_response();
        response.headers_mut().insert(
            DIGEST_HEADER,
            HeaderValue::from_str(&descriptor.digest).expect("digest header must be valid"),
        );
        response
    }

    async fn wait_for_in_flight(admission: &RustServerGenerationAdmissionV2, expected: usize) {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                if admission.in_flight_for_test() == expected {
                    return;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("in-flight lease count must converge");
    }

    async fn rejection_code(response: Response) -> String {
        let status = response.status();
        let body = to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("rejection body must be readable");
        let value: Value = serde_json::from_slice(&body).expect("rejection must be JSON");
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
        value["error"]["code"]
            .as_str()
            .expect("rejection code must be present")
            .to_owned()
    }

    #[tokio::test]
    async fn request_receives_exact_generation_and_host_descriptor() {
        let generation = stage_generation(
            Some(rust_server_host_definition_v2()),
            "server-profile",
            41,
            "sha256:server-generation-41",
        )
        .await;
        let admission = admission_with(Some(generation)).await;
        let app = admission.bind(Router::new().route("/probe", get(descriptor_probe)));

        let response = app.oneshot(request("/probe")).await.expect("request");
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("descriptor body");
        assert_eq!(
            serde_json::from_slice::<Value>(&body).expect("descriptor JSON"),
            json!({
                "profile_id": "server-profile",
                "generation": 41,
                "digest": "sha256:server-generation-41",
                "target": "rust-server",
                "strategy": RUST_SERVER_GENERATION_STRATEGY_V2,
                "route_contribution_id": RUST_SERVER_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2,
                "route_strategy": RUST_SERVER_HTTP_ROUTE_STRATEGY_V2,
            })
        );
        wait_for_in_flight(&admission, 0).await;
        admission.shutdown().await.expect("shutdown must drain");
    }

    #[tokio::test]
    async fn unavailable_or_invalid_generation_rejects_before_handler() {
        let cases = [
            (None, "generation_unavailable"),
            (
                Some(stage_generation(None, "missing-host", 1, "sha256:missing-host").await),
                "missing_service",
            ),
            (
                Some(
                    stage_generation(
                        Some(test_definition(TestHostValueV2::WrongType)),
                        "wrong-type",
                        2,
                        "sha256:wrong-type",
                    )
                    .await,
                ),
                "service_type_mismatch",
            ),
            (
                Some(
                    stage_generation(
                        Some(test_definition(TestHostValueV2::Descriptor(
                            TargetHostDescriptorV2 {
                                target: "desktop-sidecar".to_owned(),
                                strategy: RUST_SERVER_GENERATION_STRATEGY_V2.to_owned(),
                            },
                        ))),
                        "wrong-target",
                        3,
                        "sha256:wrong-target",
                    )
                    .await,
                ),
                "invalid_rust_server_generation_target",
            ),
            (
                Some(
                    stage_generation(
                        Some(test_definition(TestHostValueV2::Descriptor(
                            TargetHostDescriptorV2 {
                                target: "rust-server".to_owned(),
                                strategy: "static-router".to_owned(),
                            },
                        ))),
                        "wrong-strategy",
                        4,
                        "sha256:wrong-strategy",
                    )
                    .await,
                ),
                "invalid_rust_server_generation_strategy",
            ),
            (
                Some(
                    stage_generation_with(
                        Some(rust_server_host_definition_v2()),
                        None,
                        "missing-routes",
                        5,
                        "sha256:missing-routes",
                    )
                    .await,
                ),
                "missing_service",
            ),
            (
                Some(
                    stage_generation_with(
                        Some(rust_server_host_definition_v2()),
                        Some(test_route_definition(TestRouteValueV2::WrongType)),
                        "wrong-route-type",
                        6,
                        "sha256:wrong-route-type",
                    )
                    .await,
                ),
                "service_type_mismatch",
            ),
            (
                Some(
                    stage_generation_with(
                        Some(rust_server_host_definition_v2()),
                        Some(test_route_definition(TestRouteValueV2::Descriptor(
                            RustServerHttpRouteContributionV2 {
                                contribution_id: "unknown-routes".to_owned(),
                                strategy: RUST_SERVER_HTTP_ROUTE_STRATEGY_V2.to_owned(),
                            },
                        ))),
                        "wrong-route-contribution",
                        7,
                        "sha256:wrong-route-contribution",
                    )
                    .await,
                ),
                "invalid_rust_server_route_contribution",
            ),
            (
                Some(
                    stage_generation_with(
                        Some(rust_server_host_definition_v2()),
                        Some(test_route_definition(TestRouteValueV2::Descriptor(
                            RustServerHttpRouteContributionV2 {
                                contribution_id: RUST_SERVER_DEFAULT_HTTP_ROUTE_CONTRIBUTION_ID_V2
                                    .to_owned(),
                                strategy: "static-router".to_owned(),
                            },
                        ))),
                        "wrong-route-strategy",
                        8,
                        "sha256:wrong-route-strategy",
                    )
                    .await,
                ),
                "invalid_rust_server_route_strategy",
            ),
        ];

        for (generation, expected_code) in cases {
            let called = Arc::new(AtomicBool::new(false));
            let handler_called = Arc::clone(&called);
            let admission = admission_with(generation).await;
            let app = admission.bind(Router::new().route(
                "/probe",
                get(move || {
                    let handler_called = Arc::clone(&handler_called);
                    async move {
                        handler_called.store(true, Ordering::SeqCst);
                        StatusCode::NO_CONTENT
                    }
                }),
            ));

            let response = app.oneshot(request("/probe")).await.expect("request");
            assert_eq!(rejection_code(response).await, expected_code);
            assert!(!called.load(Ordering::SeqCst));
            admission.shutdown().await.expect("shutdown must drain");
        }
    }

    #[tokio::test]
    async fn streaming_response_pins_old_generation_until_body_drop() {
        let old = stage_generation(
            Some(rust_server_host_definition_v2()),
            "server-profile",
            10,
            "sha256:old-generation",
        )
        .await;
        let manager = Arc::new(GenerationManagerV2::new());
        manager.publish(old).await;
        let admission = RustServerGenerationAdmissionV2::new(Arc::clone(&manager));
        let app = admission.bind(Router::new().route("/stream", get(streaming_probe)));

        let old_response = app
            .clone()
            .oneshot(request("/stream"))
            .await
            .expect("old request");
        assert_eq!(
            old_response.headers()[DIGEST_HEADER],
            "sha256:old-generation"
        );
        wait_for_in_flight(&admission, 1).await;

        let new = stage_generation(
            Some(rust_server_host_definition_v2()),
            "server-profile",
            11,
            "sha256:new-generation",
        )
        .await;
        manager.publish(new).await;
        let new_response = app.oneshot(request("/stream")).await.expect("new request");
        assert_eq!(
            new_response.headers()[DIGEST_HEADER],
            "sha256:new-generation"
        );
        wait_for_in_flight(&admission, 2).await;

        drop(new_response);
        wait_for_in_flight(&admission, 1).await;
        drop(old_response);
        wait_for_in_flight(&admission, 0).await;
        admission.shutdown().await.expect("shutdown must drain");
    }

    #[tokio::test]
    async fn canceled_handler_releases_lease_and_shutdown_rejects_new_requests() {
        let generation = stage_generation(
            Some(rust_server_host_definition_v2()),
            "server-profile",
            20,
            "sha256:canceled-handler",
        )
        .await;
        let admission = admission_with(Some(generation)).await;
        let app = admission.bind(Router::new().route(
            "/pending",
            get(|| async {
                std::future::pending::<()>().await;
                StatusCode::NO_CONTENT
            }),
        ));
        let task_app = app.clone();
        let request_task = tokio::spawn(async move {
            task_app
                .oneshot(request("/pending"))
                .await
                .expect("pending request")
        });
        wait_for_in_flight(&admission, 1).await;

        request_task.abort();
        let _ = request_task.await;
        tokio::time::timeout(Duration::from_secs(2), admission.shutdown())
            .await
            .expect("shutdown must not hang")
            .expect("shutdown must drain");

        let response = app
            .oneshot(request("/pending"))
            .await
            .expect("stopped request");
        assert_eq!(
            rejection_code(response).await,
            "generation_admission_stopped"
        );
    }
}
