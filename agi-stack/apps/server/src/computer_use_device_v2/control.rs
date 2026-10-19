//! Generation-bound receipts acknowledge successful native control, never tool replay.
use super::*;
use agistack_core::agent::react::ToolControlResolution;
use agistack_core::ports::ToolControlOutcome;

#[derive(Deserialize)]
pub(super) struct Frame {
    pub request_id: String,
    pub session_id: String,
    pub control_generation: String,
    pub state: String,
}
fn denied() -> CoreError {
    CoreError::Tool("computer_use_control_state_denied".into())
}
impl Broker {
    fn control_preview(
        &self,
        connection: &str,
        frame: &Frame,
    ) -> CoreResult<(Owner, broker::Claim, authority::RunAuthority)> {
        if !matches!(frame.state.as_str(), "resumed" | "stopped")
            || uuid::Uuid::parse_str(&frame.control_generation).is_err()
        {
            return Err(denied());
        }
        let requests = self.requests.lock().expect("CUA requests");
        let request = requests.get(&frame.request_id).ok_or_else(denied)?;
        if request.connection_id != connection
            || request.claim.session_id != frame.session_id
            || request.cancelled
            || request.failed
            || !matches!(request.status, "claimed" | "completed")
        {
            return Err(denied());
        }
        if request.status == "completed"
            && !request.result.as_ref().is_some_and(|result| {
                result.control_outcome == Some(ToolControlOutcome::UserPaused)
                    && result.control_generation.as_deref()
                        == Some(frame.control_generation.as_str())
            })
        {
            return Err(denied());
        }
        self.validate_request_device(request)?;
        Ok((
            request.owner.clone(),
            request.claim.clone(),
            request.run.clone(),
        ))
    }
    pub(super) async fn receive_control_state(
        &self,
        connection: &str,
        frame: Frame,
    ) -> CoreResult<()> {
        let (owner, claim, run) = self.control_preview(connection, &frame)?;
        self.authority
            .as_ref()
            .ok_or_else(denied)?
            .recheck_running(&owner, &claim.conversation_id, &run)
            .await?;
        self.control_preview(connection, &frame)?;
        // Hold the request lock through storage to serialize with cancellation.
        let requests = self.requests.lock().expect("CUA requests");
        let request = requests
            .get(&frame.request_id)
            .filter(|r| !r.cancelled && r.connection_id == connection)
            .ok_or_else(denied)?;
        if request.status == "completed"
            && !request.result.as_ref().is_some_and(|result| {
                result.control_outcome == Some(ToolControlOutcome::UserPaused)
                    && result.control_generation.as_deref()
                        == Some(frame.control_generation.as_str())
            })
        {
            return Err(denied());
        }
        self.validate_request_device(request)?;
        let mut receipts = self.control_receipts.lock().expect("CUA control receipts");
        let key = (frame.request_id, frame.control_generation);
        if request.status == "completed" {
            // An early candidate with an unmatched generation never blocks the
            // authenticated receipt matching the eventual paused result.
            receipts.retain(|(id, generation), _| id != &key.0 || generation == &key.1);
        } else if receipts
            .keys()
            .any(|(id, generation)| id == &key.0 && generation != &key.1)
        {
            return Err(denied());
        }
        if receipts.get(&key).is_none_or(|state| state != "stopped") {
            receipts.insert(key, frame.state);
        }
        request.notify.notify_one();
        Ok(())
    }
    pub(crate) async fn wait_for_control(
        &self,
        owner: &Owner,
        session: &str,
        generation: &str,
    ) -> CoreResult<ToolControlResolution> {
        loop {
            let (notify, claim, run, completed) = {
                let requests = self.requests.lock().expect("CUA requests");
                let (id, request) = requests
                    .iter()
                    .find(|(_, request)| {
                        request.owner == *owner
                            && request.claim.session_id == session
                            && request.result.as_ref().is_some_and(|result| {
                                result.control_outcome == Some(ToolControlOutcome::UserPaused)
                                    && result.control_generation.as_deref() == Some(generation)
                            })
                    })
                    .ok_or_else(denied)?;
                if request.cancelled || request.failed {
                    return Err(denied());
                }
                self.validate_request_device(request)?;
                let completed = self
                    .control_receipts
                    .lock()
                    .expect("CUA control receipts")
                    .get(&(id.clone(), generation.into()))
                    .cloned();
                (
                    request.notify.clone(),
                    request.claim.clone(),
                    request.run.clone(),
                    completed,
                )
            };
            self.authority
                .as_ref()
                .ok_or_else(denied)?
                .recheck_running(owner, &claim.conversation_id, &run)
                .await?;
            if let Some(completed) = completed {
                let requests = self.requests.lock().expect("CUA requests");
                let request = requests
                    .get(&claim.request_id)
                    .filter(|request| !request.cancelled && !request.failed)
                    .ok_or_else(denied)?;
                self.validate_request_device(request)?;
                return Ok(if completed == "stopped" {
                    ToolControlResolution::Stopped
                } else {
                    ToolControlResolution::Resumed
                });
            }
            let _ =
                tokio::time::timeout(std::time::Duration::from_secs(1), notify.notified()).await;
        }
    }
}
