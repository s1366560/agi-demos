//! Local execution record upload.
//!
//! The desktop machine executes tools. This crate redacts the record, keeps an
//! isolated outbound queue, and posts it to the cloud run. It does not treat a
//! local login or a local conversation row as the account source of truth.

mod drive;
mod execute;
mod queue;
mod redact;

pub use drive::{
    drive_local_run, request_cancel, resume_pending_uploads, CloudCall, CloudReply, DriveReport,
    DriveRequest, LocalRunCloud, ReqwestCloud,
};
pub use execute::execute_local_turn;
pub use queue::{production_limits, QueueError, UploadLimits, UploadQueue};
pub use redact::{redact_uploaded_json, redact_with_root, LOCAL_ROOT_TOKEN, REDACTED_TOKEN};
