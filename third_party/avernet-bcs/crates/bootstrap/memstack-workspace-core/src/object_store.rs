//! Adapter from Avernet storage plugins to the Workspace ObjectStorePort.

use std::io;
use std::sync::Arc;

use async_trait::async_trait;
use bcs_storage_api::factory::{StorageBackendConfig, StoragePluginFactory};
use bcs_storage_api::{
    ByteStream, ByteStreamTrait, ClientUploadTarget, PresignGetOptions, StorageHandle,
    StoragePlugin, UploadHandle, UploadMode, UploadPrepareRequest,
};
use bcs_storage_baas::BaasStoragePluginFactory;
use bcs_storage_local::LocalStoragePluginFactory;
use bytes::{Bytes, BytesMut};
use futures::{Stream, StreamExt, TryStreamExt};
use memstack_workspace_service::{
    ObjectStageRequest, ObjectStoreError, ObjectStorePort, ReadyObjectReference,
    StagedObjectReference,
};

use bcs::{BcsConfig, resolve_env};

/// Build the Workspace object authority from the same storage configuration as BCS session files.
pub async fn build_workspace_object_store(
    config: &BcsConfig,
    desktop_vault: bool,
) -> Result<Arc<dyn ObjectStorePort>, ObjectStoreError> {
    let factory: Arc<dyn StoragePluginFactory> = match config.session_files.storage_backend.as_str()
    {
        "local" => Arc::new(LocalStoragePluginFactory),
        "baas" => Arc::new(BaasStoragePluginFactory),
        backend => {
            return Err(ObjectStoreError::Invalid(format!(
                "unsupported Workspace object backend: {backend}"
            )));
        }
    };
    let bcs_base_url = config
        .bcs_endpoint
        .clone()
        .unwrap_or_else(|| format!("http://{}:{}", config.bind, config.port));
    let backend = config
        .session_files
        .backend
        .iter()
        .map(|(key, value)| (key.clone(), toml_value_to_json(value)))
        .collect();
    let storage = factory
        .build(&StorageBackendConfig {
            env: resolve_env(),
            max_file_size: config.session_files.max_file_size,
            multipart_threshold: config.session_files.multipart_threshold,
            share_link_ttl: config.session_files.share_link_ttl,
            bcs_base_url,
            bots_base_dir: config.bots_base_dir.display().to_string(),
            backend,
        })
        .await
        .map_err(|error| ObjectStoreError::Unavailable(error.to_string()))?;
    Ok(Arc::new(StoragePluginObjectStorePort::new(
        storage,
        desktop_vault,
    )))
}

fn toml_value_to_json(value: &toml::Value) -> serde_json::Value {
    match value {
        toml::Value::String(value) => serde_json::Value::String(value.clone()),
        toml::Value::Integer(value) => serde_json::Value::Number((*value).into()),
        toml::Value::Float(value) => serde_json::Number::from_f64(*value)
            .map_or(serde_json::Value::Null, serde_json::Value::Number),
        toml::Value::Boolean(value) => serde_json::Value::Bool(*value),
        toml::Value::Datetime(value) => serde_json::Value::String(value.to_string()),
        toml::Value::Array(values) => {
            serde_json::Value::Array(values.iter().map(toml_value_to_json).collect())
        }
        toml::Value::Table(values) => serde_json::Value::Object(
            values
                .iter()
                .map(|(key, value)| (key.clone(), toml_value_to_json(value)))
                .collect(),
        ),
    }
}

/// Fail-closed default used by focused tests and incomplete deployments.
pub(crate) struct UnavailableObjectStorePort;

#[async_trait]
impl ObjectStorePort for UnavailableObjectStorePort {
    fn backend_name(&self) -> &str {
        "unavailable"
    }

    fn max_object_size(&self) -> u64 {
        0
    }

    async fn stage(
        &self,
        _request: &ObjectStageRequest,
        _body: ByteStream,
    ) -> Result<StagedObjectReference, ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "Workspace object store is not configured".to_string(),
        ))
    }

    async fn finalize(
        &self,
        _staged: &StagedObjectReference,
    ) -> Result<ReadyObjectReference, ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "Workspace object store is not configured".to_string(),
        ))
    }

    async fn abort(&self, _staged: &StagedObjectReference) -> Result<(), ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "Workspace object store is not configured".to_string(),
        ))
    }

    async fn open(&self, _object: &ReadyObjectReference) -> Result<ByteStream, ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "Workspace object store is not configured".to_string(),
        ))
    }

    async fn delete(&self, _object: &ReadyObjectReference) -> Result<(), ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "Workspace object store is not configured".to_string(),
        ))
    }

    async fn copy(
        &self,
        _source: &ReadyObjectReference,
        _request: &ObjectStageRequest,
    ) -> Result<ReadyObjectReference, ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "Workspace object store is not configured".to_string(),
        ))
    }
}

/// Cloud/Desktop adapter. `desktop_vault=true` redacts local filesystem details
/// from durable metadata and exposes an opaque `desktop-vault` reference.
pub struct StoragePluginObjectStorePort {
    storage: Arc<dyn StoragePlugin>,
    http: reqwest::Client,
    desktop_vault: bool,
}

impl StoragePluginObjectStorePort {
    #[must_use]
    pub fn new(storage: Arc<dyn StoragePlugin>, desktop_vault: bool) -> Self {
        Self {
            storage,
            http: reqwest::Client::new(),
            desktop_vault,
        }
    }

    fn upload_handle(staged: &StagedObjectReference) -> Result<UploadHandle, ObjectStoreError> {
        serde_json::from_value(staged.handle.clone())
            .map_err(|error| ObjectStoreError::Invalid(error.to_string()))
    }

    fn storage_handle(&self, object: &ReadyObjectReference) -> StorageHandle {
        StorageHandle {
            backend: self.storage.backend_name().to_string(),
            key: object.key.clone(),
            backend_handle: object.handle.clone(),
        }
    }

    async fn direct_upload(
        &self,
        target: ClientUploadTarget,
        mut body: ByteStream,
    ) -> Result<(), ObjectStoreError> {
        match target {
            ClientUploadTarget::ProxyViaBcs => Err(ObjectStoreError::Invalid(
                "proxy target must be streamed through the storage plugin".to_string(),
            )),
            ClientUploadTarget::Direct {
                mode: UploadMode::Single,
                url: Some(url),
                ..
            } => {
                let response = self
                    .http
                    .put(url)
                    .body(reqwest::Body::wrap_stream(body))
                    .send()
                    .await
                    .map_err(|error| ObjectStoreError::Unavailable(error.to_string()))?;
                if !response.status().is_success() {
                    return Err(ObjectStoreError::Unavailable(format!(
                        "direct object upload returned {}",
                        response.status()
                    )));
                }
                Ok(())
            }
            ClientUploadTarget::Direct {
                mode: UploadMode::Multipart,
                parts: Some(parts),
                part_size: Some(part_size),
                ..
            } => {
                let part_size = usize::try_from(part_size).map_err(|_| {
                    ObjectStoreError::Invalid(
                        "multipart part size exceeds platform size".to_string(),
                    )
                })?;
                if part_size == 0 {
                    return Err(ObjectStoreError::Invalid(
                        "multipart part size must be positive".to_string(),
                    ));
                }
                let mut pending = BytesMut::with_capacity(part_size);
                for part in parts {
                    while pending.len() < part_size {
                        let Some(chunk) = body.next().await else {
                            break;
                        };
                        pending.extend_from_slice(
                            &chunk.map_err(|error| {
                                ObjectStoreError::Unavailable(error.to_string())
                            })?,
                        );
                    }
                    if pending.is_empty() {
                        return Err(ObjectStoreError::Conflict(format!(
                            "multipart upload is missing part {}",
                            part.part_number
                        )));
                    }
                    let take = pending.len().min(part_size);
                    let chunk = pending.split_to(take).freeze();
                    let response = self
                        .http
                        .put(part.url)
                        .body(chunk)
                        .send()
                        .await
                        .map_err(|error| ObjectStoreError::Unavailable(error.to_string()))?;
                    if !response.status().is_success() {
                        return Err(ObjectStoreError::Unavailable(format!(
                            "direct multipart upload returned {}",
                            response.status()
                        )));
                    }
                }
                if !pending.is_empty() || body.next().await.is_some() {
                    return Err(ObjectStoreError::Conflict(
                        "multipart target does not cover the complete object".to_string(),
                    ));
                }
                Ok(())
            }
            ClientUploadTarget::Direct { .. } => Err(ObjectStoreError::Invalid(
                "direct upload target is incomplete".to_string(),
            )),
        }
    }
}

#[async_trait]
impl ObjectStorePort for StoragePluginObjectStorePort {
    fn backend_name(&self) -> &str {
        if self.desktop_vault {
            "desktop-vault"
        } else {
            self.storage.backend_name()
        }
    }

    fn max_object_size(&self) -> u64 {
        self.storage.capabilities().max_object_size
    }

    async fn stage(
        &self,
        request: &ObjectStageRequest,
        body: ByteStream,
    ) -> Result<StagedObjectReference, ObjectStoreError> {
        let prepared = self
            .storage
            .prepare_upload(
                UploadPrepareRequest {
                    key: request.key.clone(),
                    file_name: request.file_name.clone(),
                    mime_type: request.content_type.clone(),
                    size: request.size_bytes,
                    ttl_secs: 3_600,
                },
                None,
            )
            .await
            .map_err(map_storage_error)?;
        let result = match prepared.client_target.clone() {
            ClientUploadTarget::ProxyViaBcs => self
                .storage
                .stream_upload(&prepared.handle, None, body)
                .await
                .map_err(map_storage_error),
            target => self.direct_upload(target, body).await,
        };
        if let Err(error) = result {
            let _ = self.storage.abort_upload(&prepared.handle).await;
            return Err(error);
        }
        Ok(StagedObjectReference {
            backend: self.backend_name().to_string(),
            key: request.key.clone(),
            handle: serde_json::to_value(&prepared.handle)
                .map_err(|error| ObjectStoreError::Invalid(error.to_string()))?,
            size_bytes: request.size_bytes,
            checksum_sha256: request.checksum_sha256.clone(),
        })
    }

    async fn finalize(
        &self,
        staged: &StagedObjectReference,
    ) -> Result<ReadyObjectReference, ObjectStoreError> {
        let handle = Self::upload_handle(staged)?;
        let meta = self
            .storage
            .complete_upload(&handle)
            .await
            .map_err(map_storage_error)?;
        Ok(ReadyObjectReference {
            backend: self.backend_name().to_string(),
            key: staged.key.clone(),
            handle: if self.desktop_vault {
                serde_json::Value::Null
            } else {
                handle.backend_handle
            },
            size_bytes: if meta.size == 0 {
                staged.size_bytes
            } else {
                meta.size
            },
            checksum_sha256: meta.sha256.or_else(|| Some(staged.checksum_sha256.clone())),
        })
    }

    async fn abort(&self, staged: &StagedObjectReference) -> Result<(), ObjectStoreError> {
        self.storage
            .abort_upload(&Self::upload_handle(staged)?)
            .await
            .map_err(map_storage_error)
    }

    async fn open(&self, object: &ReadyObjectReference) -> Result<ByteStream, ObjectStoreError> {
        let handle = self.storage_handle(object);
        if self.storage.capabilities().supports_stream_get {
            return self
                .storage
                .get_stream(&handle)
                .await
                .map_err(map_storage_error);
        }
        let ticket = self
            .storage
            .presign_get(
                &handle,
                PresignGetOptions {
                    ttl_secs: 300,
                    show: false,
                },
                None,
            )
            .await
            .map_err(map_storage_error)?;
        let response = self
            .http
            .get(ticket.download_url)
            .send()
            .await
            .map_err(|error| ObjectStoreError::Unavailable(error.to_string()))?;
        if response.status() == reqwest::StatusCode::NOT_FOUND {
            return Err(ObjectStoreError::NotFound);
        }
        if !response.status().is_success() {
            return Err(ObjectStoreError::Unavailable(format!(
                "object download returned {}",
                response.status()
            )));
        }
        Ok(box_stream(
            response.bytes_stream().map_err(io::Error::other),
        ))
    }

    async fn delete(&self, object: &ReadyObjectReference) -> Result<(), ObjectStoreError> {
        self.storage
            .delete(&self.storage_handle(object))
            .await
            .map_err(map_storage_error)
    }

    async fn copy(
        &self,
        source: &ReadyObjectReference,
        request: &ObjectStageRequest,
    ) -> Result<ReadyObjectReference, ObjectStoreError> {
        let body = self.open(source).await?;
        let staged = self.stage(request, body).await?;
        match self.finalize(&staged).await {
            Ok(ready) => Ok(ready),
            Err(error) => {
                let _ = self.abort(&staged).await;
                Err(error)
            }
        }
    }
}

fn map_storage_error(error: bcs_storage_api::StorageError) -> ObjectStoreError {
    match error {
        bcs_storage_api::StorageError::InvalidInput(message) => ObjectStoreError::Invalid(message),
        bcs_storage_api::StorageError::NotFound => ObjectStoreError::NotFound,
        bcs_storage_api::StorageError::Conflict(message) => ObjectStoreError::Conflict(message),
        bcs_storage_api::StorageError::Unsupported(backend) => {
            ObjectStoreError::Unavailable(format!("unsupported by {backend}"))
        }
        bcs_storage_api::StorageError::Backend(error) => {
            ObjectStoreError::Unavailable(error.to_string())
        }
    }
}

fn box_stream<S>(stream: S) -> ByteStream
where
    S: Stream<Item = Result<Bytes, io::Error>> + Send + Unpin + 'static,
{
    struct Wrapped<S>(S);
    impl<S> Stream for Wrapped<S>
    where
        S: Stream<Item = Result<Bytes, io::Error>> + Unpin,
    {
        type Item = Result<Bytes, io::Error>;

        fn poll_next(
            mut self: std::pin::Pin<&mut Self>,
            context: &mut std::task::Context<'_>,
        ) -> std::task::Poll<Option<Self::Item>> {
            std::pin::Pin::new(&mut self.0).poll_next(context)
        }
    }
    impl<S> ByteStreamTrait for Wrapped<S> where
        S: Stream<Item = Result<Bytes, io::Error>> + Send + Unpin + 'static
    {
    }
    Box::new(Wrapped(stream))
}
