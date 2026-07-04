use std::cmp::Reverse;
use std::collections::{HashMap, HashSet};
use std::sync::Mutex;

use async_trait::async_trait;
use chrono::Utc;

use agistack_adapters_postgres::TenantSkillConfigRecord;
use agistack_adapters_secrets::generate_uuid_v4;

use super::views::{
    OverrideSkillPayload, SystemSkillPayload, TenantSkillConfigListView, TenantSkillConfigView,
    TenantSkillStatusView,
};
use super::{
    present, skill_status_view, validate_system_skill_name, TenantSkillConfigApiError,
    TenantSkillConfigService,
};

#[derive(Default)]
pub(crate) struct DevTenantSkillConfigService {
    tenant_id: String,
    configs: Mutex<HashMap<String, TenantSkillConfigRecord>>,
    override_skills: Mutex<HashSet<String>>,
}

impl DevTenantSkillConfigService {
    pub(crate) fn new(tenant_id: impl Into<String>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            configs: Mutex::new(HashMap::new()),
            override_skills: Mutex::new(HashSet::new()),
        }
    }

    #[cfg(test)]
    pub(super) fn with_override_skill(
        self,
        skill_id: impl Into<String>,
    ) -> Result<Self, TenantSkillConfigApiError> {
        self.override_skills
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .insert(skill_id.into());
        Ok(self)
    }

    fn resolve_tenant(&self, tenant_id: Option<&str>) -> String {
        present(tenant_id)
            .map(ToString::to_string)
            .unwrap_or_else(|| self.tenant_id.clone())
    }

    fn find_config(
        &self,
        tenant_id: &str,
        system_skill_name: &str,
    ) -> Result<Option<TenantSkillConfigRecord>, TenantSkillConfigApiError> {
        Ok(self
            .configs
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .values()
            .find(|config| {
                config.tenant_id == tenant_id && config.system_skill_name == system_skill_name
            })
            .cloned())
    }

    fn write_config(
        &self,
        record: TenantSkillConfigRecord,
    ) -> Result<TenantSkillConfigRecord, TenantSkillConfigApiError> {
        self.configs
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .insert(record.id.clone(), record.clone());
        Ok(record)
    }
}

#[async_trait]
impl TenantSkillConfigService for DevTenantSkillConfigService {
    async fn list_configs(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<TenantSkillConfigListView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let mut configs: Vec<_> = self
            .configs
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .values()
            .filter(|config| config.tenant_id == tenant_id)
            .cloned()
            .collect();
        configs.sort_by_key(|config| Reverse(config.created_at));
        let total = configs.len() as i64;
        Ok(TenantSkillConfigListView {
            configs: configs
                .into_iter()
                .map(TenantSkillConfigView::from)
                .collect(),
            total,
        })
    }

    async fn get_config(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(system_skill_name)?;
        let config = self
            .find_config(&tenant_id, system_skill_name)?
            .ok_or_else(|| TenantSkillConfigApiError::not_found("Skill configuration not found"))?;
        Ok(config.into())
    }

    async fn disable_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillPayload,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let now = Utc::now();
        let record = match self.find_config(&tenant_id, system_skill_name)? {
            Some(mut record) => {
                record.action = "disable".to_string();
                record.override_skill_id = None;
                record.updated_at = Some(now);
                record
            }
            None => TenantSkillConfigRecord {
                id: generate_uuid_v4(),
                tenant_id,
                system_skill_name: system_skill_name.to_string(),
                action: "disable".to_string(),
                override_skill_id: None,
                created_at: now,
                updated_at: Some(now),
            },
        };
        Ok(self.write_config(record)?.into())
    }

    async fn override_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: OverrideSkillPayload,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let override_skill_id = validate_system_skill_name(&body.override_skill_id)?;
        if !self
            .override_skills
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .contains(override_skill_id)
        {
            return Err(TenantSkillConfigApiError::not_found(
                "Override skill not found",
            ));
        }
        let now = Utc::now();
        let record = match self.find_config(&tenant_id, system_skill_name)? {
            Some(mut record) => {
                record.action = "override".to_string();
                record.override_skill_id = Some(override_skill_id.to_string());
                record.updated_at = Some(now);
                record
            }
            None => TenantSkillConfigRecord {
                id: generate_uuid_v4(),
                tenant_id,
                system_skill_name: system_skill_name.to_string(),
                action: "override".to_string(),
                override_skill_id: Some(override_skill_id.to_string()),
                created_at: now,
                updated_at: Some(now),
            },
        };
        Ok(self.write_config(record)?.into())
    }

    async fn enable_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillPayload,
    ) -> Result<(), TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let mut configs = self
            .configs
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?;
        let id = configs
            .values()
            .find(|config| {
                config.tenant_id == tenant_id && config.system_skill_name == system_skill_name
            })
            .map(|config| config.id.clone())
            .ok_or_else(|| TenantSkillConfigApiError::not_found("Skill configuration not found"))?;
        configs.remove(&id);
        Ok(())
    }

    async fn delete_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<(), TenantSkillConfigApiError> {
        self.enable_skill(
            user_id,
            tenant_id,
            SystemSkillPayload {
                system_skill_name: system_skill_name.to_string(),
            },
        )
        .await
    }

    async fn skill_status(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<TenantSkillStatusView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(system_skill_name)?;
        let config = self.find_config(&tenant_id, system_skill_name)?;
        Ok(skill_status_view(system_skill_name, config))
    }
}
