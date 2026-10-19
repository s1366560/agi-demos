//! Authenticate first, resolve declared input fields, then admit a new operation.

use std::collections::BTreeMap;

use axum::{
    body::{to_bytes, Body},
    extract::{FromRequest, FromRequestParts, MatchedPath, Multipart, Path, State},
    http::Request,
    middleware::Next,
    response::{IntoResponse, Response},
};
use serde_json::Value;

use crate::{
    auth::Identity,
    feature_operation_owners_v2::{
        self, BodyScopeFormatV2, FeatureOperationOwnerV2, ScopeParameterV2,
    },
    feature_operation_v2::{FeatureAdmissionErrorV2, FeatureOperationAdmissionV2},
    AppState,
};

const MAX_SCOPE_BODY_BYTES: usize = 2 * 1024 * 1024;

pub(crate) async fn guard(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    guard_with_admission(&state.feature_operations, request, next).await
}

pub(crate) async fn guard_with_admission(
    admission: &FeatureOperationAdmissionV2,
    request: Request<Body>,
    next: Next,
) -> Response {
    let Some(route) = request.extensions().get::<MatchedPath>() else {
        return next.run(request).await;
    };
    let Some(owner) = feature_operation_owners_v2::owner(request.method().as_str(), route.as_str())
    else {
        return next.run(request).await;
    };
    match prepare(admission, request, owner).await {
        Ok(request) => next.run(request).await,
        Err(error) => error.into_response(),
    }
}

async fn prepare(
    admission: &FeatureOperationAdmissionV2,
    request: Request<Body>,
    owner: FeatureOperationOwnerV2,
) -> Result<Request<Body>, FeatureAdmissionErrorV2> {
    let identity = request
        .extensions()
        .get::<Identity>()
        .cloned()
        .ok_or_else(FeatureAdmissionErrorV2::forbidden)?;
    let (mut parts, body) = request.into_parts();
    let mut arguments = BTreeMap::new();
    if !owner.path_parameters.is_empty() {
        let Path(path) = Path::<BTreeMap<String, String>>::from_request_parts(&mut parts, &())
            .await
            .map_err(|_| FeatureAdmissionErrorV2::invalid())?;
        for field in owner.path_parameters {
            if let Some(value) = path.get(field.field) {
                insert(&mut arguments, field, value)?;
            }
        }
    }
    for (key, value) in
        url::form_urlencoded::parse(parts.uri.query().unwrap_or_default().as_bytes())
    {
        if let Some(field) = owner
            .query_parameters
            .iter()
            .find(|field| field.field == key)
        {
            insert(&mut arguments, field, &value)?;
        }
    }
    let mut features = owner.feature_ids.to_vec();
    let body = if owner.body_parameters.is_empty() && owner.payload_field_owners.is_empty() {
        body
    } else {
        let bytes = to_bytes(body, MAX_SCOPE_BODY_BYTES)
            .await
            .map_err(|_| FeatureAdmissionErrorV2::invalid())?;
        match owner.body_format {
            BodyScopeFormatV2::Json => {
                let value: Value = serde_json::from_slice(&bytes)
                    .map_err(|_| FeatureAdmissionErrorV2::invalid())?;
                for field in owner.body_parameters {
                    if let Some(value) = value.get(field.field).filter(|value| !value.is_null()) {
                        insert(
                            &mut arguments,
                            field,
                            value
                                .as_str()
                                .ok_or_else(FeatureAdmissionErrorV2::invalid)?,
                        )?;
                    }
                }
                for field in owner.payload_field_owners {
                    if value.get(field.field).is_some() {
                        features.push(field.feature_id);
                    }
                }
            }
            BodyScopeFormatV2::Multipart => {
                let mut parsed = Request::new(Body::from(bytes.clone()));
                *parsed.headers_mut() = parts.headers.clone();
                let mut multipart = Multipart::from_request(parsed, &())
                    .await
                    .map_err(|_| FeatureAdmissionErrorV2::invalid())?;
                while let Some(field) = multipart
                    .next_field()
                    .await
                    .map_err(|_| FeatureAdmissionErrorV2::invalid())?
                {
                    if let Some(parameter) = owner
                        .body_parameters
                        .iter()
                        .find(|parameter| Some(parameter.field) == field.name())
                    {
                        let value = field
                            .text()
                            .await
                            .map_err(|_| FeatureAdmissionErrorV2::invalid())?;
                        insert(&mut arguments, parameter, &value)?;
                    }
                }
            }
        }
        Body::from(bytes)
    };
    admission
        .admit(&identity.user_id, &owner, &arguments, &features)
        .await?;
    Ok(Request::from_parts(parts, body))
}

fn insert(
    arguments: &mut BTreeMap<String, String>,
    field: &ScopeParameterV2,
    value: &str,
) -> Result<(), FeatureAdmissionErrorV2> {
    if value.is_empty() && field.empty_is_absent {
        return Ok(());
    }
    if value.is_empty()
        || arguments
            .get(field.parameter)
            .is_some_and(|previous| previous != value)
    {
        return Err(FeatureAdmissionErrorV2::scope_mismatch());
    }
    arguments.insert(field.parameter.into(), value.into());
    Ok(())
}
