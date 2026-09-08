//! Production collection schemas: tenants/projects plus total/page/page_size.
//! Complete bounded paging prevents truncated or mixed-tenant selection lists.
use std::collections::BTreeSet;

use super::*;
use crate::local_runtime::knowledge_authority_v2::contracts::{SyncCloudProject, SyncCloudTenant};

const PAGE_SIZE: u64 = 100;
const MAX_ITEMS: u64 = 10_000;

impl TrustedCloudConnection {
    pub(in crate::local_runtime::knowledge_authority_v2) async fn tenants(
        &self,
        check_local: &(dyn Fn() -> Result<(), KnowledgeAuthorityErrorV2> + Sync),
    ) -> Result<Vec<SyncCloudTenant>, KnowledgeAuthorityErrorV2> {
        let values = self.catalog("tenants", None, check_local).await?;
        values
            .into_iter()
            .map(|value| {
                Ok(SyncCloudTenant {
                    id: identifier_field(&value, "id")?,
                    name: name_field(&value)?,
                })
            })
            .collect()
    }

    pub(in crate::local_runtime::knowledge_authority_v2) async fn projects(
        &self,
        tenant: &str,
        check_local: &(dyn Fn() -> Result<(), KnowledgeAuthorityErrorV2> + Sync),
    ) -> Result<Vec<SyncCloudProject>, KnowledgeAuthorityErrorV2> {
        if !valid_identifier(tenant) {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        // A project filter is not evidence of tenant membership. Re-read the
        // authenticated membership-backed tenant catalogue before using it.
        if !self
            .tenants(check_local)
            .await?
            .iter()
            .any(|item| item.id == tenant)
        {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        let values = self.catalog("projects", Some(tenant), check_local).await?;
        values
            .into_iter()
            .map(|value| {
                let tenant_id = identifier_field(&value, "tenant_id")?;
                if tenant_id != tenant {
                    return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
                }
                Ok(SyncCloudProject {
                    id: identifier_field(&value, "id")?,
                    tenant_id,
                    name: name_field(&value)?,
                })
            })
            .collect()
    }

    async fn catalog(
        &self,
        collection: &str,
        tenant: Option<&str>,
        check_local: &(dyn Fn() -> Result<(), KnowledgeAuthorityErrorV2> + Sync),
    ) -> Result<Vec<Value>, KnowledgeAuthorityErrorV2> {
        let mut items = Vec::new();
        let mut identifiers = BTreeSet::new();
        let mut expected_total = None;
        for page in 1..=MAX_ITEMS / PAGE_SIZE {
            check_local()?;
            let mut url = self.url(&format!("{collection}/"));
            url.query_pairs_mut()
                .append_pair("page", &page.to_string())
                .append_pair("page_size", &PAGE_SIZE.to_string());
            if let Some(tenant) = tenant {
                url.query_pairs_mut().append_pair("tenant_id", tenant);
            }
            let response = self.get(url, None).await?;
            check_local()?;
            let total = response["total"]
                .as_u64()
                .filter(|total| *total <= MAX_ITEMS)
                .ok_or(KnowledgeAuthorityErrorV2::RemoteRejected)?;
            if response["page"].as_u64() != Some(page)
                || response["page_size"].as_u64() != Some(PAGE_SIZE)
                || expected_total.is_some_and(|expected| expected != total)
            {
                return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
            }
            expected_total = Some(total);
            let rows = response[collection]
                .as_array()
                .ok_or(KnowledgeAuthorityErrorV2::RemoteRejected)?;
            let expected_count = total.saturating_sub(items.len() as u64).min(PAGE_SIZE) as usize;
            if rows.len() != expected_count {
                return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
            }
            for item in rows {
                let id = identifier_field(item, "id")?;
                if !identifiers.insert(id) {
                    return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
                }
                if tenant.is_some_and(|tenant| item["tenant_id"].as_str() != Some(tenant)) {
                    return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
                }
                name_field(item)?;
                items.push(item.clone());
            }
            if items.len() as u64 == total {
                return Ok(items);
            }
        }
        Err(KnowledgeAuthorityErrorV2::RemoteRejected)
    }

    pub(in crate::local_runtime::knowledge_authority_v2) async fn verify_project(
        &self,
        tenant: &str,
        project: &str,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        if !valid_identifier(tenant) {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        let mut url = self.project_url(project, &[])?;
        url.query_pairs_mut().append_pair("tenant_id", tenant);
        let result = self.get(url, None).await?;
        if result["id"].as_str() != Some(project) || result["tenant_id"].as_str() != Some(tenant) {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        Ok(())
    }
}

fn identifier_field(value: &Value, name: &str) -> Result<String, KnowledgeAuthorityErrorV2> {
    value[name]
        .as_str()
        .filter(|value| valid_identifier(value))
        .map(str::to_owned)
        .ok_or(KnowledgeAuthorityErrorV2::RemoteRejected)
}
fn name_field(value: &Value) -> Result<String, KnowledgeAuthorityErrorV2> {
    value["name"]
        .as_str()
        .filter(|value| value.chars().count() <= 4096)
        .map(str::to_owned)
        .ok_or(KnowledgeAuthorityErrorV2::RemoteRejected)
}
