use super::super::sync_transport::{CloudResolutionResponse, VerifiedCloudTransport};
use super::super::*;
use crate::trusted_session::TrustedSessionBroker;
use agistack_core::knowledge::sync::{cloud_resolution::*, KnowledgeSyncRepository};

pub(in crate::local_runtime::knowledge_authority_v2) enum CloudResolutionDispatch {
    Resolved(KnowledgeCloudResolutionOutcome),
    Stale(String),
}

impl KnowledgeOperationV2 {
    async fn resolution_transport(
        &self,
        broker: &TrustedSessionBroker,
    ) -> Result<(Arc<SqliteKnowledgeRepository>, VerifiedCloudTransport), KnowledgeAuthorityErrorV2>
    {
        let repository = self.authority.repository()?;
        let link = repository
            .sync_status(&self.scope)
            .await?
            .link
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        let transport = VerifiedCloudTransport::connect(broker, link).await?;
        Ok((repository, transport))
    }
    async fn dispatch_cloud_resolution(
        &self,
        repository: &SqliteKnowledgeRepository,
        transport: &VerifiedCloudTransport,
        record: KnowledgeCloudResolutionRecord,
    ) -> Result<CloudResolutionDispatch, KnowledgeAuthorityErrorV2> {
        transport.ensure_current()?;
        if record.rejection.is_some() {
            return Ok(CloudResolutionDispatch::Stale(record.resolution_id));
        }
        if let Some(receipt) = record.receipt {
            return Ok(CloudResolutionDispatch::Resolved(
                KnowledgeCloudResolutionOutcome {
                    resolution_id: record.resolution_id,
                    receipt,
                    pending_reconciliation: record.reconciliation.is_none(),
                    replayed: true,
                },
            ));
        }
        match transport.resolve_cloud(&record).await? {
            CloudResolutionResponse::Success(response) => transport.with_current_session(|| {
                Ok(CloudResolutionDispatch::Resolved(
                    repository.accept_cloud_resolution_receipt_durable(
                        &self.scope,
                        &transport.target,
                        &self.actor_id,
                        &record.resolution_id,
                        response,
                    )?,
                ))
            }),
            CloudResolutionResponse::Stale(response) => {
                transport.with_current_session(|| {
                    Ok(repository.reject_cloud_resolution_stale_durable(
                        &self.scope,
                        &transport.target,
                        &self.actor_id,
                        &record.resolution_id,
                        response,
                    )?)
                })?;
                Ok(CloudResolutionDispatch::Stale(record.resolution_id))
            }
        }
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn resolve_cloud_conflict(
        &self,
        broker: &TrustedSessionBroker,
        key: &str,
        command: KnowledgeCloudResolutionCommand,
    ) -> Result<CloudResolutionDispatch, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        command.validate()?;
        let (repository, transport) = self.resolution_transport(broker).await?;
        let previous = transport.with_current_session(|| {
            Ok(repository.cloud_resolution_by_key_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                key,
            )?)
        })?;
        let record = if previous.is_some() {
            // The durable prepare port compares the original command before
            // replaying; it intentionally ignores the absent fresh snapshot.
            transport.with_current_session(|| {
                Ok(repository.prepare_cloud_resolution_durable(
                    &self.scope,
                    &transport.target,
                    &self.actor_id,
                    key,
                    command,
                    Value::Null,
                )?)
            })?
        } else {
            let saved = transport.with_current_session(|| {
                Ok(repository.cloud_conflict_snapshot_durable(
                    &self.scope,
                    &transport.target,
                    command.local_sequence,
                )?)
            })?;
            if saved["id"] != command.conflict_id || saved["memory_id"] != command.memory_id {
                return Err(KnowledgeError::Conflict.into());
            }
            let id = saved["id"]
                .as_str()
                .ok_or(KnowledgeAuthorityErrorV2::RemoteRejected)?;
            let verified = transport.conflict_snapshot(id).await?;
            transport.with_current_session(|| {
                Ok(repository.prepare_cloud_resolution_durable(
                    &self.scope,
                    &transport.target,
                    &self.actor_id,
                    key,
                    command,
                    verified,
                )?)
            })?
        };
        self.dispatch_cloud_resolution(&repository, &transport, record)
            .await
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn resume_cloud_resolution(
        &self,
        broker: &TrustedSessionBroker,
        id: &str,
    ) -> Result<CloudResolutionDispatch, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let (repository, transport) = self.resolution_transport(broker).await?;
        let record = transport.with_current_session(|| {
            Ok(repository.cloud_resolution_record_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                id,
            )?)
        })?;
        self.dispatch_cloud_resolution(&repository, &transport, record)
            .await
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn reconcile_cloud_resolution(
        &self,
        broker: &TrustedSessionBroker,
        id: &str,
        command: KnowledgeCloudReconciliationCommand,
    ) -> Result<KnowledgeCloudResolutionOutcome, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let (repository, transport) = self.resolution_transport(broker).await?;
        transport.with_current_session(|| {
            Ok(repository.reconcile_cloud_resolution_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                id,
                command,
            )?)
        })
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn cloud_conflict_context(
        &self,
        broker: &TrustedSessionBroker,
        sequence: u64,
    ) -> Result<KnowledgeCloudResolutionContext, KnowledgeAuthorityErrorV2> {
        let (repository, transport) = self.resolution_transport(broker).await?;
        let saved = transport.with_current_session(|| {
            Ok(repository.cloud_conflict_snapshot_durable(
                &self.scope,
                &transport.target,
                sequence,
            )?)
        })?;
        let verified = transport
            .conflict_snapshot(
                saved["id"]
                    .as_str()
                    .ok_or(KnowledgeAuthorityErrorV2::RemoteRejected)?,
            )
            .await?;
        transport.with_current_session(|| {
            Ok(repository.cloud_conflict_context_durable(
                &self.scope,
                &transport.target,
                sequence,
                verified,
            )?)
        })
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn cloud_resolution_record(
        &self,
        broker: &TrustedSessionBroker,
        id: &str,
    ) -> Result<KnowledgeCloudResolutionRecord, KnowledgeAuthorityErrorV2> {
        let (repository, transport) = self.resolution_transport(broker).await?;
        transport.with_current_session(|| {
            Ok(repository.cloud_resolution_record_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                id,
            )?)
        })
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn cloud_resolution_records(
        &self,
        broker: &TrustedSessionBroker,
        limit: usize,
    ) -> Result<Vec<KnowledgeCloudResolutionRecord>, KnowledgeAuthorityErrorV2> {
        let (repository, transport) = self.resolution_transport(broker).await?;
        transport.with_current_session(|| {
            Ok(repository.cloud_resolution_records_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                limit,
            )?)
        })
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn cloud_resolution_by_key(
        &self,
        broker: &TrustedSessionBroker,
        key: &str,
    ) -> Result<Option<KnowledgeCloudResolutionRecord>, KnowledgeAuthorityErrorV2> {
        let (repository, transport) = self.resolution_transport(broker).await?;
        transport.with_current_session(|| {
            Ok(repository.cloud_resolution_by_key_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                key,
            )?)
        })
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn pending_cloud_resolutions(
        &self,
        broker: &TrustedSessionBroker,
        before_resolution_id: Option<&str>,
        limit: usize,
    ) -> Result<KnowledgeCloudResolutionPage, KnowledgeAuthorityErrorV2> {
        let (repository, transport) = self.resolution_transport(broker).await?;
        transport.with_current_session(|| {
            Ok(repository.pending_cloud_resolutions_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                before_resolution_id,
                limit,
            )?)
        })
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn cloud_reconciliation_context(
        &self,
        broker: &TrustedSessionBroker,
        id: &str,
    ) -> Result<KnowledgeCloudResolutionContext, KnowledgeAuthorityErrorV2> {
        let (repository, transport) = self.resolution_transport(broker).await?;
        transport.with_current_session(|| {
            Ok(repository.cloud_reconciliation_context_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                id,
            )?)
        })
    }
}
