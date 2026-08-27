//! Protocol-v2 admission authority for Desktop sidecar business-route lifetimes.

use std::{
    pin::Pin,
    sync::Arc,
    task::{Context as TaskContext, Poll},
};

use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use http_body::{Body as HttpBody, Frame, SizeHint};
use serde::Serialize;

use super::{
    platform_plugin_authority_v2::{
        ActivePlatformPluginGenerationDescriptorV2, ActivePlatformPluginGenerationLeaseV2,
        PlatformPluginGenerationAcquireV2Error,
    },
    LocalRuntimeState,
};

#[derive(Clone)]
pub(super) struct PlatformPluginRouteAdmissionV2 {
    state: Arc<LocalRuntimeState>,
    required: bool,
}

impl PlatformPluginRouteAdmissionV2 {
    pub(super) fn required(state: Arc<LocalRuntimeState>) -> Self {
        Self {
            state,
            required: true,
        }
    }

    #[cfg(test)]
    pub(super) fn optional_for_unit_tests(state: Arc<LocalRuntimeState>) -> Self {
        Self {
            state,
            required: false,
        }
    }
}

pub(super) async fn require_generation_v2(
    State(admission): State<PlatformPluginRouteAdmissionV2>,
    mut request: Request,
    next: Next,
) -> Response {
    let lease = match admission
        .state
        .platform_plugin_authority_v2
        .acquire_generation()
    {
        Ok(lease) => lease,
        Err(_error) if !admission.required => return next.run(request).await,
        Err(error) => return GenerationAdmissionRejectionV2::from(error).into_response(),
    };
    // Reading the typed contribution here makes the generated contract the production
    // authority for admitting the existing Axum route set.
    let _route_contribution = lease.http_routes();
    let lease = Arc::new(lease);
    request.extensions_mut().insert(Arc::clone(&lease));
    let response = next.run(request).await;
    let (parts, body) = response.into_parts();
    Response::from_parts(
        parts,
        Body::new(PlatformPluginGenerationLeaseBodyV2::new(body, lease)),
    )
}

struct PlatformPluginGenerationLeaseBodyV2<B> {
    inner: Pin<Box<B>>,
    lease: Option<Arc<ActivePlatformPluginGenerationLeaseV2>>,
}

impl<B> PlatformPluginGenerationLeaseBodyV2<B> {
    fn new(inner: B, lease: Arc<ActivePlatformPluginGenerationLeaseV2>) -> Self {
        Self {
            inner: Box::pin(inner),
            lease: Some(lease),
        }
    }
}

impl<B> HttpBody for PlatformPluginGenerationLeaseBodyV2<B>
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
            this.lease.take();
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
    message: &'static str,
    generation: Option<ActivePlatformPluginGenerationDescriptorV2>,
}

impl From<PlatformPluginGenerationAcquireV2Error> for GenerationAdmissionRejectionV2 {
    fn from(error: PlatformPluginGenerationAcquireV2Error) -> Self {
        Self {
            code: error.reason().code(),
            message: error.reason().message(),
            generation: error.descriptor().cloned(),
        }
    }
}

#[derive(Serialize)]
struct GenerationAdmissionErrorEnvelopeV2 {
    error: GenerationAdmissionErrorBodyV2,
}

#[derive(Serialize)]
struct GenerationAdmissionErrorBodyV2 {
    code: &'static str,
    message: &'static str,
    target: &'static str,
    generation: Option<ActivePlatformPluginGenerationDescriptorV2>,
}

impl IntoResponse for GenerationAdmissionRejectionV2 {
    fn into_response(self) -> Response {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(GenerationAdmissionErrorEnvelopeV2 {
                error: GenerationAdmissionErrorBodyV2 {
                    code: self.code,
                    message: self.message,
                    target: "desktop-sidecar",
                    generation: self.generation,
                },
            }),
        )
            .into_response()
    }
}
