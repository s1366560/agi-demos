//! Static HTTP contribution ownership and declared argument sources.
//!
//! Callers pass Axum's matched route template, never an untrusted URL prefix.
//! Scope fields are declarations of handler inputs; their values still require
//! persisted ancestry resolution and actor authorization before admission.

mod knowledge;
mod skills;
mod tenant;

#[cfg(test)]
mod tests;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct ScopeParameterV2 {
    pub field: &'static str,
    pub parameter: &'static str,
    pub empty_is_absent: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct ResourceScopeV2 {
    pub kind: &'static str,
    pub parameter: &'static str,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct PayloadFieldOwnerV2 {
    pub field: &'static str,
    pub feature_id: &'static str,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum BodyScopeFormatV2 {
    Json,
    Multipart,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct FeatureOperationOwnerV2 {
    pub feature_ids: &'static [&'static str],
    pub resources: &'static [ResourceScopeV2],
    pub project_aggregate: bool,
    pub support_tenant_aggregate: bool,
    pub path_parameters: &'static [ScopeParameterV2],
    pub query_parameters: &'static [ScopeParameterV2],
    pub body_parameters: &'static [ScopeParameterV2],
    pub body_format: BodyScopeFormatV2,
    pub payload_field_owners: &'static [PayloadFieldOwnerV2],
}

const TENANT: &[ScopeParameterV2] = &[parameter("tenant_id", "tenant_id")];
const PROJECT: &[ScopeParameterV2] = &[parameter("project_id", "project_id")];
const TENANT_PROJECT: &[ScopeParameterV2] = &[
    parameter("tenant_id", "tenant_id"),
    parameter("project_id", "project_id"),
];

const fn parameter(field: &'static str, parameter: &'static str) -> ScopeParameterV2 {
    ScopeParameterV2 {
        field,
        parameter,
        empty_is_absent: false,
    }
}

const fn resource(kind: &'static str, parameter: &'static str) -> ResourceScopeV2 {
    ResourceScopeV2 { kind, parameter }
}

const fn declared(feature_ids: &'static [&'static str]) -> FeatureOperationOwnerV2 {
    FeatureOperationOwnerV2 {
        feature_ids,
        resources: &[],
        project_aggregate: false,
        support_tenant_aggregate: false,
        path_parameters: &[],
        query_parameters: &[],
        body_parameters: &[],
        body_format: BodyScopeFormatV2::Json,
        payload_field_owners: &[],
    }
}

impl FeatureOperationOwnerV2 {
    const fn path(mut self, parameters: &'static [ScopeParameterV2]) -> Self {
        self.path_parameters = parameters;
        self
    }

    const fn query(mut self, parameters: &'static [ScopeParameterV2]) -> Self {
        self.query_parameters = parameters;
        self
    }

    const fn body(mut self, parameters: &'static [ScopeParameterV2]) -> Self {
        self.body_parameters = parameters;
        self
    }

    const fn resources(mut self, resources: &'static [ResourceScopeV2]) -> Self {
        self.resources = resources;
        self
    }

    const fn aggregate(mut self) -> Self {
        self.project_aggregate = true;
        self
    }

    const fn multipart(mut self) -> Self {
        self.body_format = BodyScopeFormatV2::Multipart;
        self
    }
}

/// Return declared ownership for one exact method and mounted route template.
/// Bootstrap, replay and running-execution recovery endpoints remain unowned.
pub(crate) fn owner(method: &str, route: &str) -> Option<FeatureOperationOwnerV2> {
    // Axum invokes the GET handler for HEAD, then removes the response body.
    let method = match method {
        "HEAD" => "GET",
        method => method,
    };
    knowledge::owner(method, route)
        .or_else(|| skills::owner(method, route))
        .or_else(|| tenant::owner(method, route))
}
