use std::sync::Mutex;

use async_trait::async_trait;

use super::{
    WorkspaceAuthority, WorkspaceAuthorityError, WorkspaceAuthorityProfile, WorkspaceAuthorityScope,
};

pub(crate) struct FixedWorkspaceAuthority {
    pub(crate) profile: Option<WorkspaceAuthorityProfile>,
    pub(crate) available: bool,
    pub(crate) users: Vec<String>,
    pub(crate) requests: Mutex<Vec<(String, String, Option<String>)>>,
}

impl FixedWorkspaceAuthority {
    pub(crate) fn new(profile: Option<WorkspaceAuthorityProfile>, users: &[&str]) -> Self {
        Self {
            profile,
            available: true,
            users: users.iter().map(|user| (*user).to_string()).collect(),
            requests: Mutex::new(Vec::new()),
        }
    }
}

#[async_trait]
impl WorkspaceAuthority for FixedWorkspaceAuthority {
    async fn authorize(
        &self,
        user_id: &str,
        workspace_id: &str,
    ) -> Result<Option<WorkspaceAuthorityScope>, WorkspaceAuthorityError> {
        self.read_profile(user_id, workspace_id, None)
            .await
            .map(|profile| profile.map(|profile| profile.scope))
    }

    async fn read_profile(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: Option<&str>,
    ) -> Result<Option<WorkspaceAuthorityProfile>, WorkspaceAuthorityError> {
        self.requests.lock().unwrap().push((
            user_id.to_string(),
            workspace_id.to_string(),
            task_id.map(str::to_string),
        ));
        if !self.available {
            return Err(WorkspaceAuthorityError::Unavailable);
        }
        if !self.users.iter().any(|user| user == user_id) {
            return Ok(None);
        }
        Ok(self.profile.clone())
    }
}
