//! P7 billing strangler slice.
//!
//! Rust owns tenant billing summary, invoice list, and exact plan upgrade.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Serialize;
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    BillingTenantRecord, BillingUsageRecord, InvoiceRecord, PgBillingRepository,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedBilling = Arc<dyn BillingService>;

const FREE_STORAGE_LIMIT: i64 = 10 * 1024 * 1024 * 1024;
const PRO_STORAGE_LIMIT: i64 = 100 * 1024 * 1024 * 1024;
const ENTERPRISE_STORAGE_LIMIT: i64 = 1024 * 1024 * 1024 * 1024;

#[async_trait]
pub(crate) trait BillingService: Send + Sync {
    async fn get_billing_info(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<BillingInfoResponse, BillingApiError>;

    async fn list_invoices(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<InvoiceListResponse, BillingApiError>;

    async fn upgrade_plan(
        &self,
        user_id: &str,
        tenant_id: &str,
        request: BillingUpgradeRequest,
    ) -> Result<BillingUpgradeResponse, BillingApiError>;
}

pub(crate) struct PgBillingService {
    repo: PgBillingRepository,
}

impl PgBillingService {
    pub(crate) fn new(repo: PgBillingRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl BillingService for PgBillingService {
    async fn get_billing_info(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<BillingInfoResponse, BillingApiError> {
        require_billing_admin_role(&self.repo, user_id, tenant_id).await?;
        let tenant = self
            .repo
            .billing_tenant(tenant_id)
            .await
            .map_err(BillingApiError::internal)?
            .ok_or_else(|| BillingApiError::not_found("Tenant not found"))?;
        let usage = self
            .repo
            .billing_usage(tenant_id)
            .await
            .map_err(BillingApiError::internal)?;
        let invoices = self
            .repo
            .list_recent_invoices(tenant_id, 12)
            .await
            .map_err(BillingApiError::internal)?;
        Ok(BillingInfoResponse::from_records(tenant, usage, invoices))
    }

    async fn list_invoices(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<InvoiceListResponse, BillingApiError> {
        require_billing_admin_role(&self.repo, user_id, tenant_id).await?;
        if !self
            .repo
            .tenant_exists(tenant_id)
            .await
            .map_err(BillingApiError::internal)?
        {
            return Err(BillingApiError::not_found("Tenant not found"));
        }
        let records = self
            .repo
            .list_invoices(tenant_id)
            .await
            .map_err(BillingApiError::internal)?;
        Ok(InvoiceListResponse::from_records(records))
    }

    async fn upgrade_plan(
        &self,
        user_id: &str,
        tenant_id: &str,
        request: BillingUpgradeRequest,
    ) -> Result<BillingUpgradeResponse, BillingApiError> {
        require_billing_owner_role(&self.repo, user_id, tenant_id).await?;
        let plan = normalize_billing_plan(request.plan.as_ref())?;
        let storage_limit = storage_limit_for_plan(&plan);
        let tenant = self
            .repo
            .update_tenant_plan(tenant_id, &plan, storage_limit)
            .await
            .map_err(BillingApiError::internal)?
            .ok_or_else(|| BillingApiError::not_found("Tenant not found"))?;
        Ok(BillingUpgradeResponse::from_tenant(tenant))
    }
}

pub(crate) struct DevBillingService {
    invoices: Vec<InvoiceRecord>,
}

impl DevBillingService {
    pub(crate) fn new(invoices: Vec<InvoiceRecord>) -> Self {
        Self { invoices }
    }
}

impl Default for DevBillingService {
    fn default() -> Self {
        Self::new(Vec::new())
    }
}

#[async_trait]
impl BillingService for DevBillingService {
    async fn get_billing_info(
        &self,
        _user_id: &str,
        tenant_id: &str,
    ) -> Result<BillingInfoResponse, BillingApiError> {
        let tenant = BillingTenantRecord {
            id: tenant_id.to_string(),
            name: format!("Tenant {tenant_id}"),
            plan: "free".to_string(),
            storage_limit: 10_737_418_240,
        };
        let usage = BillingUsageRecord {
            projects: 0,
            memories: 0,
            users: 0,
            storage: 0,
        };
        let mut invoices = self
            .invoices
            .iter()
            .filter(|invoice| invoice.tenant_id == tenant_id)
            .cloned()
            .collect::<Vec<_>>();
        invoices.sort_by(|left, right| {
            right
                .created_at
                .cmp(&left.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        invoices.truncate(12);
        Ok(BillingInfoResponse::from_records(tenant, usage, invoices))
    }

    async fn list_invoices(
        &self,
        _user_id: &str,
        tenant_id: &str,
    ) -> Result<InvoiceListResponse, BillingApiError> {
        let mut invoices = self
            .invoices
            .iter()
            .filter(|invoice| invoice.tenant_id == tenant_id)
            .cloned()
            .collect::<Vec<_>>();
        invoices.sort_by(|left, right| {
            right
                .created_at
                .cmp(&left.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(InvoiceListResponse::from_records(invoices))
    }

    async fn upgrade_plan(
        &self,
        _user_id: &str,
        tenant_id: &str,
        request: BillingUpgradeRequest,
    ) -> Result<BillingUpgradeResponse, BillingApiError> {
        let plan = normalize_billing_plan(request.plan.as_ref())?;
        Ok(BillingUpgradeResponse::from_tenant(BillingTenantRecord {
            id: tenant_id.to_string(),
            name: format!("Tenant {tenant_id}"),
            storage_limit: storage_limit_for_plan(&plan),
            plan,
        }))
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/tenants/:tenant_id/billing", get(get_billing_info))
        .route("/api/v1/tenants/:tenant_id/invoices", get(list_invoices))
        .route("/api/v1/tenants/:tenant_id/upgrade", post(upgrade_plan))
}

async fn get_billing_info(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
) -> Result<Json<BillingInfoResponse>, BillingApiError> {
    let response = app
        .billing
        .get_billing_info(&identity.user_id, &tenant_id)
        .await?;
    Ok(Json(response))
}

async fn list_invoices(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
) -> Result<Json<InvoiceListResponse>, BillingApiError> {
    let response = app
        .billing
        .list_invoices(&identity.user_id, &tenant_id)
        .await?;
    Ok(Json(response))
}

async fn upgrade_plan(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    body: Option<Json<Value>>,
) -> Result<Json<BillingUpgradeResponse>, BillingApiError> {
    let request = BillingUpgradeRequest {
        plan: match body {
            Some(Json(Value::Object(mut object))) => object.remove("plan"),
            Some(Json(Value::Null)) | None => None,
            Some(Json(_)) => return Err(BillingApiError::bad_request("Invalid billing plan")),
        },
    };
    let response = app
        .billing
        .upgrade_plan(&identity.user_id, &tenant_id, request)
        .await?;
    Ok(Json(response))
}

async fn require_billing_admin_role(
    repo: &PgBillingRepository,
    user_id: &str,
    tenant_id: &str,
) -> Result<(), BillingApiError> {
    let role = repo
        .tenant_member_role(user_id, tenant_id)
        .await
        .map_err(BillingApiError::internal)?;
    match role.as_deref() {
        Some("admin" | "owner") => Ok(()),
        _ => Err(BillingApiError::forbidden("Access denied")),
    }
}

async fn require_billing_owner_role(
    repo: &PgBillingRepository,
    user_id: &str,
    tenant_id: &str,
) -> Result<(), BillingApiError> {
    let role = repo
        .tenant_member_role(user_id, tenant_id)
        .await
        .map_err(BillingApiError::internal)?;
    match role.as_deref() {
        Some("owner") => Ok(()),
        _ => Err(BillingApiError::forbidden("Only owner can upgrade plan")),
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub(crate) struct BillingUpgradeRequest {
    plan: Option<Value>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InvoiceView {
    id: String,
    amount: i32,
    currency: String,
    status: String,
    period_start: String,
    period_end: String,
    created_at: String,
    paid_at: Option<String>,
    invoice_url: Option<String>,
}

impl From<InvoiceRecord> for InvoiceView {
    fn from(record: InvoiceRecord) -> Self {
        Self {
            id: record.id,
            amount: record.amount,
            currency: record.currency,
            status: record.status,
            period_start: iso8601(record.period_start),
            period_end: iso8601(record.period_end),
            created_at: iso8601(record.created_at),
            paid_at: record.paid_at.map(iso8601),
            invoice_url: record.invoice_url,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct BillingTenantView {
    id: String,
    name: String,
    plan: String,
    storage_limit: i64,
}

impl From<BillingTenantRecord> for BillingTenantView {
    fn from(record: BillingTenantRecord) -> Self {
        Self {
            id: record.id,
            name: record.name,
            plan: record.plan,
            storage_limit: record.storage_limit,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct BillingUsageView {
    projects: i64,
    memories: i64,
    users: i64,
    storage: i64,
}

impl From<BillingUsageRecord> for BillingUsageView {
    fn from(record: BillingUsageRecord) -> Self {
        Self {
            projects: record.projects,
            memories: record.memories,
            users: record.users,
            storage: record.storage,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct BillingInfoResponse {
    tenant: BillingTenantView,
    usage: BillingUsageView,
    invoices: Vec<InvoiceView>,
}

impl BillingInfoResponse {
    fn from_records(
        tenant: BillingTenantRecord,
        usage: BillingUsageRecord,
        invoices: Vec<InvoiceRecord>,
    ) -> Self {
        Self {
            tenant: BillingTenantView::from(tenant),
            usage: BillingUsageView::from(usage),
            invoices: invoices.into_iter().map(InvoiceView::from).collect(),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct BillingUpgradeResponse {
    message: String,
    tenant: BillingTenantView,
}

impl BillingUpgradeResponse {
    fn from_tenant(tenant: BillingTenantRecord) -> Self {
        Self {
            message: "Plan upgraded successfully".to_string(),
            tenant: BillingTenantView::from(tenant),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InvoiceListResponse {
    invoices: Vec<InvoiceView>,
}

impl InvoiceListResponse {
    fn from_records(records: Vec<InvoiceRecord>) -> Self {
        Self {
            invoices: records.into_iter().map(InvoiceView::from).collect(),
        }
    }
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn storage_limit_for_plan(plan: &str) -> i64 {
    match plan {
        "free" => FREE_STORAGE_LIMIT,
        "pro" => PRO_STORAGE_LIMIT,
        "enterprise" => ENTERPRISE_STORAGE_LIMIT,
        _ => PRO_STORAGE_LIMIT,
    }
}

fn normalize_billing_plan(plan: Option<&Value>) -> Result<String, BillingApiError> {
    let Some(plan) = plan else {
        return Ok("pro".to_string());
    };
    match plan {
        Value::Null | Value::Bool(false) => Ok("pro".to_string()),
        Value::String(value) if value.is_empty() => Ok("pro".to_string()),
        Value::String(value) if matches!(value.as_str(), "free" | "pro" | "enterprise") => {
            Ok(value.clone())
        }
        Value::Number(value) if value.as_i64() == Some(0) => Ok("pro".to_string()),
        Value::Array(values) if values.is_empty() => Ok("pro".to_string()),
        Value::Object(values) if values.is_empty() => Ok("pro".to_string()),
        _ => Err(BillingApiError::bad_request("Invalid billing plan")),
    }
}

#[derive(Debug)]
pub(crate) struct BillingApiError {
    status: StatusCode,
    detail: String,
}

impl BillingApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for BillingApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use serde_json::Value;

    fn invoice(
        id: &str,
        created_at: DateTime<Utc>,
        paid_at: Option<DateTime<Utc>>,
    ) -> InvoiceRecord {
        InvoiceRecord {
            id: id.to_string(),
            tenant_id: "tenant-1".to_string(),
            amount: 1999,
            currency: "USD".to_string(),
            status: "paid".to_string(),
            period_start: Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            period_end: Utc.with_ymd_and_hms(2026, 2, 1, 0, 0, 0).unwrap(),
            created_at,
            paid_at,
            invoice_url: Some("https://billing.example.test/invoices/invoice-1".to_string()),
        }
    }

    fn billing_tenant() -> BillingTenantRecord {
        BillingTenantRecord {
            id: "tenant-1".to_string(),
            name: "Tenant tenant-1".to_string(),
            plan: "pro".to_string(),
            storage_limit: 107_374_182_400,
        }
    }

    fn billing_usage() -> BillingUsageRecord {
        BillingUsageRecord {
            projects: 2,
            memories: 3,
            users: 2,
            storage: 0,
        }
    }

    #[test]
    fn billing_info_response_matches_python_shape() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/billing_info_response.json"))
                .expect("billing info golden must be valid JSON");
        let response = BillingInfoResponse::from_records(
            billing_tenant(),
            billing_usage(),
            vec![invoice(
                "invoice-1",
                Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap(),
                Some(Utc.with_ymd_and_hms(2026, 1, 6, 0, 0, 0).unwrap()),
            )],
        );

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn invoice_list_response_matches_python_shape() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/invoice_list_response.json"))
                .expect("invoice list golden must be valid JSON");
        let response = InvoiceListResponse::from_records(vec![invoice(
            "invoice-1",
            Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap(),
            Some(Utc.with_ymd_and_hms(2026, 1, 6, 0, 0, 0).unwrap()),
        )]);

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn billing_upgrade_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/billing_upgrade_response.json"
        ))
        .expect("billing upgrade golden must be valid JSON");
        let response = BillingUpgradeResponse::from_tenant(BillingTenantRecord {
            id: "tenant-1".to_string(),
            name: "Tenant tenant-1".to_string(),
            plan: "enterprise".to_string(),
            storage_limit: 1_099_511_627_776,
        });

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn billing_plan_normalization_matches_python_truthy_contract() {
        assert_eq!(
            normalize_billing_plan(None).expect("missing defaults"),
            "pro"
        );
        assert_eq!(
            normalize_billing_plan(Some(&json!(null))).expect("null defaults"),
            "pro"
        );
        assert_eq!(
            normalize_billing_plan(Some(&json!(false))).expect("false defaults"),
            "pro"
        );
        assert_eq!(
            normalize_billing_plan(Some(&json!(""))).expect("empty string defaults"),
            "pro"
        );
        assert_eq!(
            normalize_billing_plan(Some(&json!("enterprise"))).expect("enterprise accepted"),
            "enterprise"
        );
        assert!(normalize_billing_plan(Some(&json!(true))).is_err());
        assert!(normalize_billing_plan(Some(&json!("team"))).is_err());
    }

    #[tokio::test]
    async fn dev_billing_service_filters_and_orders_by_tenant() {
        let service = DevBillingService::new(vec![
            invoice(
                "invoice-old",
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
                None,
            ),
            invoice(
                "invoice-new",
                Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
                None,
            ),
            InvoiceRecord {
                tenant_id: "tenant-other".to_string(),
                ..invoice(
                    "invoice-other",
                    Utc.with_ymd_and_hms(2026, 1, 3, 0, 0, 0).unwrap(),
                    None,
                )
            },
        ]);

        let response = service
            .list_invoices("user-1", "tenant-1")
            .await
            .expect("dev service succeeds");

        assert_eq!(response.invoices.len(), 2);
        assert_eq!(response.invoices[0].id, "invoice-new");
        assert_eq!(response.invoices[1].id, "invoice-old");
    }

    #[tokio::test]
    async fn dev_billing_info_limits_recent_invoices() {
        let invoices = (0..14)
            .map(|idx| {
                invoice(
                    &format!("invoice-{idx:02}"),
                    Utc.with_ymd_and_hms(2026, 1, 1 + idx, 0, 0, 0)
                        .single()
                        .unwrap(),
                    None,
                )
            })
            .collect::<Vec<_>>();
        let service = DevBillingService::new(invoices);

        let response = service
            .get_billing_info("user-1", "tenant-1")
            .await
            .expect("dev billing info succeeds");

        assert_eq!(response.invoices.len(), 12);
        assert_eq!(response.invoices[0].id, "invoice-13");
        assert_eq!(response.invoices[11].id, "invoice-02");
    }
}
