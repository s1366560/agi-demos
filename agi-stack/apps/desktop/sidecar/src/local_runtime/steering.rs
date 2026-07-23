use serde::{Deserialize, Serialize};

use super::composer_context::ComposerContextItem;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum RunInputDelivery {
    SteerNow,
    QueueNext,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum RunInputStatus {
    PendingBoundary,
    Queued,
    Applied,
    Ready,
    Blocked,
    PromotedToPlan,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ChangeReferenceSide {
    Old,
    New,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub(super) enum RunInputReference {
    CodeRange {
        snapshot_id: String,
        environment_id: String,
        path: String,
        start_line: u64,
        end_line: u64,
        side: ChangeReferenceSide,
        patch_digest: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct DesktopRunInput {
    pub id: String,
    pub conversation_id: String,
    pub run_id: String,
    pub expected_run_revision: u64,
    pub message_id: String,
    pub idempotency_key: String,
    pub delivery: RunInputDelivery,
    pub status: RunInputStatus,
    pub sequence: u64,
    pub queue_position: Option<u64>,
    pub content: String,
    pub references: Vec<RunInputReference>,
    #[serde(default)]
    pub context_items: Vec<ComposerContextItem>,
    pub applied_round: Option<u64>,
    pub applied_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub promotion_idempotency_key: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub promoted_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

impl DesktopRunInput {
    pub(super) fn steering_content(&self) -> String {
        if self.references.is_empty() && self.context_items.is_empty() {
            return self.content.clone();
        }
        let mut content = self.content.clone();
        if !self.references.is_empty() {
            content.push_str("\n\nAuthoritative change references:");
        }
        for reference in &self.references {
            match reference {
                RunInputReference::CodeRange {
                    path,
                    start_line,
                    end_line,
                    side,
                    snapshot_id,
                    ..
                } => {
                    content.push_str(&format!(
                        "\n- {path}:{start_line}-{end_line} ({side:?}, snapshot {snapshot_id})"
                    ));
                }
            }
        }
        if !self.context_items.is_empty() {
            content.push_str("\n\nStructured composer context:");
            for item in &self.context_items {
                content.push_str(&format!(
                    "\n- {:?}: {} ({})",
                    item.kind, item.label, item.resource_id
                ));
            }
        }
        content
    }
}
