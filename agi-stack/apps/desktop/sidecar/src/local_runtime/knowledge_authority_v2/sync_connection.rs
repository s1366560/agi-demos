//! Scoped native connection/discovery and explicit verified target binding.
//! Local workspace authority remains separate from the cloud vault identity.
use agistack_core::knowledge::sync::push::KnowledgeSyncTarget;
use agistack_core::knowledge::sync::KnowledgeSyncLink;
use serde_json::{json, Value};

use super::contracts::{
    SyncCloudEnrollment, SyncCloudGeneration, SyncEnrollmentRequest, SyncTargetRequest,
};
use super::trusted_cloud_connection::TrustedCloudConnection;
use super::*;
use crate::local_runtime::LocalRuntimeState;
use crate::trusted_session::{
    TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRuntimeMode,
};

impl KnowledgeOperationV2 {
    fn check_sync_context(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        write: bool,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        self.authority.require_sync_release()?;
        processing_context::with_read_current_checked(
            self,
            state,
            auth,
            write,
            |_| Ok(()),
            |clock| clock().map(|_| ()),
        )
    }

    async fn observe_connection(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        expected: &str,
        write: bool,
    ) -> Result<TrustedCloudConnection, KnowledgeAuthorityErrorV2> {
        self.check_sync_context(state, auth, write)?;
        let connection = TrustedCloudConnection::open(&broker(state)?).await?;
        self.check_sync_context(state, auth, write)?;
        connection.require_observation(&self.authority.sync_connection_nonce, expected)?;
        Ok(connection)
    }

    pub(super) async fn sync_connection(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
    ) -> Result<Value, KnowledgeAuthorityErrorV2> {
        self.check_sync_context(state, auth, false)?;
        let Some(broker) = state.platform_plugin_authority_v2.trusted_sessions() else {
            return Ok(json!({"connection":null}));
        };
        let snapshot = broker
            .snapshot()
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        if !snapshot.record.is_some_and(|record| {
            record.runtime_mode == TrustedSessionRuntimeMode::Cloud
                && record.credential_kind == TrustedSessionCredentialKind::CloudBearer
        }) {
            self.check_sync_context(state, auth, false)?;
            return Ok(json!({"connection":null}));
        }
        let connection = TrustedCloudConnection::open(&broker).await?;
        self.check_sync_context(state, auth, false)?;
        connection.with_current_session(|| {
            Ok(json!({"connection":connection.projection(&self.authority.sync_connection_nonce)}))
        })
    }

    pub(super) async fn sync_tenants(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        expected: &str,
    ) -> Result<Value, KnowledgeAuthorityErrorV2> {
        let connection = self
            .observe_connection(state, auth, expected, false)
            .await?;
        let items = connection
            .tenants(&|| self.check_sync_context(state, auth, false))
            .await?;
        self.check_sync_context(state, auth, false)?;
        connection.with_current_session(|| Ok(json!({"connection":connection.projection(&self.authority.sync_connection_nonce),"items":items})))
    }

    pub(super) async fn sync_projects(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        expected: &str,
        tenant: &str,
    ) -> Result<Value, KnowledgeAuthorityErrorV2> {
        let connection = self
            .observe_connection(state, auth, expected, false)
            .await?;
        let items = connection
            .projects(tenant, &|| self.check_sync_context(state, auth, false))
            .await?;
        self.check_sync_context(state, auth, false)?;
        connection.with_current_session(|| Ok(json!({"connection":connection.projection(&self.authority.sync_connection_nonce),"tenant_id":tenant,"items":items})))
    }

    async fn observe_enrollment(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        request: &SyncEnrollmentRequest,
        expected_generation: Option<&SyncCloudGeneration>,
        write: bool,
    ) -> Result<(TrustedCloudConnection, SyncCloudEnrollment), KnowledgeAuthorityErrorV2> {
        let connection = self
            .observe_connection(state, auth, &request.expected_connection_revision, write)
            .await?;
        connection
            .verify_project(&request.tenant_id, &request.project_id)
            .await?;
        self.check_sync_context(state, auth, write)?;
        let enrollment = connection
            .enrollment(&request.tenant_id, &request.project_id, expected_generation)
            .await?;
        self.check_sync_context(state, auth, write)?;
        self.authority.require_sync_cloud_profile(
            &enrollment.generation.descriptor.profile_id,
            enrollment.generation.descriptor.generation,
            &enrollment.generation.descriptor.digest,
        )?;
        Ok((connection, enrollment))
    }

    pub(super) async fn sync_enrollment(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        request: &SyncEnrollmentRequest,
    ) -> Result<Value, KnowledgeAuthorityErrorV2> {
        let (connection, enrollment) = self
            .observe_enrollment(state, auth, request, None, false)
            .await?;
        connection.with_current_session(|| Ok(json!({"connection":connection.projection(&self.authority.sync_connection_nonce),"enrollment":enrollment})))
    }

    pub(super) async fn sync_enroll(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        request: &SyncTargetRequest,
    ) -> Result<Value, KnowledgeAuthorityErrorV2> {
        request.expected_generation.validate()?;
        let (connection, previous) = self
            .observe_enrollment(
                state,
                auth,
                &request.observation(),
                Some(&request.expected_generation),
                true,
            )
            .await?;
        let enrollment = if previous.enabled {
            previous
        } else {
            if !previous.can_enroll {
                return Err(KnowledgeAuthorityErrorV2::Forbidden);
            }
            self.check_sync_context(state, auth, true)?;
            connection
                .enroll(
                    &request.tenant_id,
                    &request.project_id,
                    &request.expected_generation,
                )
                .await?
        };
        self.check_sync_context(state, auth, true)?;
        connection.with_current_session(|| Ok(json!({"connection":connection.projection(&self.authority.sync_connection_nonce),"enrollment":enrollment})))
    }

    pub(super) async fn sync_bind(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        request: &SyncTargetRequest,
    ) -> Result<Value, KnowledgeAuthorityErrorV2> {
        request.expected_generation.validate()?;
        let (connection, enrollment) = self
            .observe_enrollment(
                state,
                auth,
                &request.observation(),
                Some(&request.expected_generation),
                true,
            )
            .await?;
        if !enrollment.enabled {
            return Err(KnowledgeAuthorityErrorV2::SyncNotEnrolled);
        }
        let target = KnowledgeSyncTarget {
            authority: connection.canonical_authority.clone(),
            link: KnowledgeSyncLink {
                remote_tenant_id: enrollment.tenant_id.clone(),
                remote_project_id: enrollment.project_id.clone(),
                remote_actor_id: connection.actor_id.clone(),
            },
        };
        let repository = self.authority.repository()?;
        // Lock order: local auth -> current generation -> cloud session ->
        // knowledge storage. Neither clock callback reacquires an outer lock.
        let status = processing_context::with_read_current_checked(
            self,
            state,
            auth,
            true,
            |_| Ok(()),
            |clock| {
                Ok(connection.with_current_session(|| {
                    Ok(repository.bind_verified_sync_target_durable(
                        &self.scope,
                        &target,
                        &|| {
                            clock()?;
                            connection
                                .ensure_deadline()
                                .map_err(|_| KnowledgeError::Conflict)
                        },
                    )?)
                }))
            },
        )??;
        Ok(
            json!({"connection":connection.projection(&self.authority.sync_connection_nonce),"enrollment":enrollment,"status":status,"association_state":"verified"}),
        )
    }
}

impl SyncTargetRequest {
    fn observation(&self) -> SyncEnrollmentRequest {
        SyncEnrollmentRequest {
            scope: self.scope.clone(),
            expected_connection_revision: self.expected_connection_revision.clone(),
            tenant_id: self.tenant_id.clone(),
            project_id: self.project_id.clone(),
        }
    }
}

fn broker(state: &LocalRuntimeState) -> Result<TrustedSessionBroker, KnowledgeAuthorityErrorV2> {
    state
        .platform_plugin_authority_v2
        .trusted_sessions()
        .ok_or(KnowledgeAuthorityErrorV2::TransportUnavailable)
}
