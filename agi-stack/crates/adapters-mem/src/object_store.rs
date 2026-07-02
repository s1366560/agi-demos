//! In-memory [`ObjectStore`] — the test/browser/device tier of the blob store
//! (F6). Mirrors the S3/MinIO adapter's observable behaviour (put/get/stat/
//! delete/prefix-list) without any I/O, so it backs unit tests and the wasm
//! build and serves as the parity oracle for the S3 tier.
//!
//! A `BTreeMap` keeps keys sorted, so [`list`](InMemoryObjectStore::list) is
//! naturally ascending — the same order the S3 adapter sorts into — making
//! cross-adapter `list` comparisons a direct `Vec<String>` equality.

use std::collections::BTreeMap;
use std::sync::Mutex;

use async_trait::async_trait;

use agistack_core::ports::{CoreResult, ObjectMeta, ObjectStore};

/// Process-local blob store: `key -> (bytes, content_type)`.
#[derive(Default)]
pub struct InMemoryObjectStore {
    inner: Mutex<BTreeMap<String, StoredObject>>,
}

#[derive(Clone)]
struct StoredObject {
    bytes: Vec<u8>,
    content_type: Option<String>,
}

impl InMemoryObjectStore {
    pub fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl ObjectStore for InMemoryObjectStore {
    async fn put(&self, key: &str, bytes: Vec<u8>, content_type: Option<&str>) -> CoreResult<()> {
        let mut inner = self.inner.lock().expect("object store mutex");
        inner.insert(
            key.to_string(),
            StoredObject {
                bytes,
                // Normalize an absent content-type to S3/MinIO's canonical default
                // so this oracle faithfully models the production tier (which
                // always reports `application/octet-stream` for untyped objects).
                content_type: Some(
                    content_type
                        .unwrap_or("application/octet-stream")
                        .to_string(),
                ),
            },
        );
        Ok(())
    }

    async fn get(&self, key: &str) -> CoreResult<Option<Vec<u8>>> {
        let inner = self.inner.lock().expect("object store mutex");
        Ok(inner.get(key).map(|o| o.bytes.clone()))
    }

    async fn stat(&self, key: &str) -> CoreResult<Option<ObjectMeta>> {
        let inner = self.inner.lock().expect("object store mutex");
        Ok(inner.get(key).map(|o| ObjectMeta {
            size: o.bytes.len() as u64,
            content_type: o.content_type.clone(),
        }))
    }

    async fn delete(&self, key: &str) -> CoreResult<()> {
        let mut inner = self.inner.lock().expect("object store mutex");
        inner.remove(key);
        Ok(())
    }

    async fn list(&self, prefix: &str) -> CoreResult<Vec<String>> {
        let inner = self.inner.lock().expect("object store mutex");
        // BTreeMap iterates in ascending key order already.
        Ok(inner
            .keys()
            .filter(|k| k.starts_with(prefix))
            .cloned()
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    #[test]
    fn put_get_roundtrip_and_missing_is_none() {
        let s = InMemoryObjectStore::new();
        block_on(s.put("a/1", b"hello".to_vec(), Some("text/plain"))).unwrap();
        assert_eq!(block_on(s.get("a/1")).unwrap(), Some(b"hello".to_vec()));
        assert_eq!(block_on(s.get("a/missing")).unwrap(), None);
    }

    #[test]
    fn stat_reports_size_and_content_type() {
        let s = InMemoryObjectStore::new();
        block_on(s.put("k", b"1234".to_vec(), Some("application/json"))).unwrap();
        let meta = block_on(s.stat("k")).unwrap().unwrap();
        assert_eq!(meta.size, 4);
        assert_eq!(meta.content_type.as_deref(), Some("application/json"));
        assert_eq!(block_on(s.stat("nope")).unwrap(), None);
    }

    #[test]
    fn absent_content_type_defaults_to_octet_stream() {
        // Mirrors S3/MinIO: an untyped object reports `application/octet-stream`,
        // so this oracle stays byte-parity with the production tier.
        let s = InMemoryObjectStore::new();
        block_on(s.put("k", b"x".to_vec(), None)).unwrap();
        let meta = block_on(s.stat("k")).unwrap().unwrap();
        assert_eq!(
            meta.content_type.as_deref(),
            Some("application/octet-stream")
        );
    }

    #[test]
    fn overwrite_replaces_bytes() {
        let s = InMemoryObjectStore::new();
        block_on(s.put("k", b"v1".to_vec(), None)).unwrap();
        block_on(s.put("k", b"v2".to_vec(), None)).unwrap();
        assert_eq!(block_on(s.get("k")).unwrap(), Some(b"v2".to_vec()));
    }

    #[test]
    fn delete_is_idempotent() {
        let s = InMemoryObjectStore::new();
        block_on(s.put("k", b"x".to_vec(), None)).unwrap();
        block_on(s.delete("k")).unwrap();
        block_on(s.delete("k")).unwrap(); // absent key: no-op success
        assert_eq!(block_on(s.get("k")).unwrap(), None);
    }

    #[test]
    fn list_by_prefix_is_sorted() {
        let s = InMemoryObjectStore::new();
        for k in ["b/2", "a/1", "a/3", "c/9"] {
            block_on(s.put(k, b"x".to_vec(), None)).unwrap();
        }
        assert_eq!(block_on(s.list("a/")).unwrap(), vec!["a/1", "a/3"]);
        assert_eq!(
            block_on(s.list("")).unwrap(),
            vec!["a/1", "a/3", "b/2", "c/9"]
        );
        assert!(block_on(s.list("z/")).unwrap().is_empty());
    }
}
