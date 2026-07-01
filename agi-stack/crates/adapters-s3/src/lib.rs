//! S3/MinIO adapter for the [`ObjectStore`] port — the **production** blob-store
//! tier (F6).
//!
//! This is the server-only sibling of
//! [`agistack_adapters_mem::InMemoryObjectStore`]. It stores objects in the exact
//! same S3 bucket the Python backend uses (artifacts / attachments /
//! instance-files), so during the strangler migration the Rust server can serve
//! blob read/write against a bucket the existing Python code keeps writing — no
//! data migration, flip one path at a time. In dev it points at the same MinIO
//! container (`memstack-minio`, S3-compatible).
//!
//! ## Semantics (kept parity with the in-memory oracle)
//! - [`put`](S3ObjectStore::put) → `PutObject` (overwrite), tagging `Content-Type`.
//! - [`get`](S3ObjectStore::get) / [`stat`](S3ObjectStore::stat) → `GetObject` /
//!   `HeadObject`, mapping a `NoSuchKey`/404 to `None` (never an error), matching
//!   the in-memory tier's `Option` return.
//! - [`delete`](S3ObjectStore::delete) → `DeleteObject` (deleting an absent key is
//!   a success, S3 semantics).
//! - [`list`](S3ObjectStore::list) → `ListObjectsV2` (paginated), returning keys
//!   **sorted ascending** to match the `BTreeMap`-ordered in-memory tier.
//!
//! Everything here is `tokio`-bound and lives strictly outside the core.

use async_trait::async_trait;
use aws_sdk_s3::config::{BehaviorVersion, Credentials, Region};
use aws_sdk_s3::error::SdkError;
use aws_sdk_s3::primitives::ByteStream;
use aws_sdk_s3::Client;

use agistack_core::ports::{CoreError, CoreResult, ObjectMeta, ObjectStore};

/// Connect to an S3-compatible endpoint (AWS S3 or MinIO) and ensure `bucket`
/// exists, returning a ready [`S3ObjectStore`].
///
/// `endpoint` may be `None` for real AWS (region-derived), or e.g.
/// `Some("http://localhost:9000")` for MinIO. Path-style addressing is forced so
/// MinIO's `http://host:9000/{bucket}/{key}` layout works without DNS wildcards.
pub async fn connect(
    endpoint: Option<&str>,
    region: &str,
    access_key: &str,
    secret_key: &str,
    bucket: &str,
) -> CoreResult<S3ObjectStore> {
    let creds = Credentials::new(access_key, secret_key, None, None, "agistack-static");
    let mut builder = aws_sdk_s3::config::Builder::new()
        .behavior_version(BehaviorVersion::latest())
        .region(Region::new(region.to_string()))
        .credentials_provider(creds)
        .force_path_style(true);
    if let Some(ep) = endpoint {
        builder = builder.endpoint_url(ep);
    }
    let client = Client::from_conf(builder.build());

    // Create the bucket if it does not already exist (idempotent: an
    // already-owned bucket is fine). Mirrors dev bootstrap; on real AWS the
    // bucket is typically pre-provisioned and this is a no-op success.
    match client.create_bucket().bucket(bucket).send().await {
        Ok(_) => {}
        Err(e) => {
            let msg = format!("{e:?}");
            if !(msg.contains("BucketAlreadyOwnedByYou") || msg.contains("BucketAlreadyExists")) {
                return Err(gerr(e));
            }
        }
    }

    Ok(S3ObjectStore {
        client,
        bucket: bucket.to_string(),
    })
}

/// Production [`ObjectStore`] backed by an S3 bucket.
#[derive(Clone)]
pub struct S3ObjectStore {
    client: Client,
    bucket: String,
}

impl S3ObjectStore {
    /// Wrap an already-configured client + bucket (e.g. one shared with other
    /// S3-backed adapters).
    pub fn new(client: Client, bucket: impl Into<String>) -> Self {
        Self {
            client,
            bucket: bucket.into(),
        }
    }
}

/// Map any SDK error to the port-level [`CoreError::Storage`], keeping the
/// concrete `aws_sdk_s3` types out of the core contract.
fn gerr<E: std::fmt::Debug>(e: E) -> CoreError {
    CoreError::Storage(format!("{e:?}"))
}

/// `true` when an SDK error is a "not found" (missing key / 404), which we model
/// as `Ok(None)` rather than an error.
fn is_not_found<E, R>(err: &SdkError<E, R>) -> bool
where
    E: std::fmt::Debug,
    R: std::fmt::Debug,
{
    // Prefer the raw HTTP status when available; fall back to the debug string
    // (covers `NoSuchKey` / `NotFound` service errors across get/head).
    if let SdkError::ServiceError(ctx) = err {
        let dbg = format!("{:?}", ctx.err());
        if dbg.contains("NoSuchKey") || dbg.contains("NotFound") {
            return true;
        }
    }
    let dbg = format!("{err:?}");
    dbg.contains("NoSuchKey") || dbg.contains("NotFound") || dbg.contains("status: 404")
}

#[async_trait]
impl ObjectStore for S3ObjectStore {
    async fn put(&self, key: &str, bytes: Vec<u8>, content_type: Option<&str>) -> CoreResult<()> {
        let mut req = self
            .client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(bytes));
        if let Some(ct) = content_type {
            req = req.content_type(ct);
        }
        req.send().await.map_err(gerr)?;
        Ok(())
    }

    async fn get(&self, key: &str) -> CoreResult<Option<Vec<u8>>> {
        match self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
        {
            Ok(out) => {
                let data = out.body.collect().await.map_err(gerr)?;
                Ok(Some(data.into_bytes().to_vec()))
            }
            Err(e) if is_not_found(&e) => Ok(None),
            Err(e) => Err(gerr(e)),
        }
    }

    async fn stat(&self, key: &str) -> CoreResult<Option<ObjectMeta>> {
        match self
            .client
            .head_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
        {
            Ok(out) => Ok(Some(ObjectMeta {
                size: out.content_length().unwrap_or(0).max(0) as u64,
                content_type: out.content_type().map(str::to_string),
            })),
            Err(e) if is_not_found(&e) => Ok(None),
            Err(e) => Err(gerr(e)),
        }
    }

    async fn delete(&self, key: &str) -> CoreResult<()> {
        self.client
            .delete_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .map_err(gerr)?;
        Ok(())
    }

    async fn list(&self, prefix: &str) -> CoreResult<Vec<String>> {
        let mut keys = Vec::new();
        let mut continuation: Option<String> = None;
        loop {
            let mut req = self
                .client
                .list_objects_v2()
                .bucket(&self.bucket)
                .prefix(prefix);
            if let Some(token) = &continuation {
                req = req.continuation_token(token);
            }
            let out = req.send().await.map_err(gerr)?;
            for obj in out.contents() {
                if let Some(k) = obj.key() {
                    keys.push(k.to_string());
                }
            }
            if out.is_truncated().unwrap_or(false) {
                continuation = out.next_continuation_token().map(str::to_string);
                if continuation.is_none() {
                    break;
                }
            } else {
                break;
            }
        }
        // S3 returns keys in lexicographic (UTF-8) order already, but sort
        // defensively so the result is byte-identical to the BTreeMap-ordered
        // in-memory oracle regardless of pagination boundaries.
        keys.sort();
        Ok(keys)
    }
}
