use super::*;
use crate::local_runtime::browser_auth::{AuthOwner, AuthRequest};

impl<E: BridgeEndpoint> BrowserRunToolHost<E> {
    pub(super) async fn request_browser_auth(&self, input: &Value) -> CoreResult<String> {
        let (Some(broker), Some(run)) = (&self.browser_auth, &self.run) else {
            return Ok(json!({"status":"unavailable"}).to_string());
        };
        let expected = run.clone();
        let store = self.session_store.clone();
        let owner = self.owner.clone();
        let current = Arc::new(move || {
            if owner.as_ref().is_some_and(|owner| {
                !store
                    .session_context_is_current(owner, chrono::Utc::now().timestamp_millis())
                    .unwrap_or(false)
            }) {
                return false;
            }
            store.run(&expected.id).is_ok_and(|run| {
                run.is_some_and(|run| {
                    run.status == super::super::authority_store::DesktopRunStatus::Running
                        && run.revision == expected.revision
                        && run.permission_profile == expected.permission_profile
                        && run.environment == expected.environment
                        && run.conversation_id == expected.conversation_id
                        && run.project_id == expected.project_id
                })
            })
        });
        self.request_browser_auth_scoped(
            input,
            broker,
            &run.conversation_id,
            &run.id,
            run.revision,
            current,
        )
        .await
    }

    pub(super) async fn request_browser_auth_scoped(
        &self,
        input: &Value,
        broker: &crate::local_runtime::browser_auth::BrowserAuthBroker,
        conversation_id: &str,
        run_id: &str,
        run_revision: u64,
        current: Arc<dyn Fn() -> bool + Send + Sync>,
    ) -> CoreResult<String> {
        if !current() {
            return Err(CoreError::Tool("browser_auth_run_changed".into()));
        }
        let request = match AuthRequest::parse(&input["args"][0]) {
            Ok(request) => request,
            Err(_) => return Ok(json!({"status":"unavailable"}).to_string()),
        };
        let backend = input["backend"].as_str().unwrap_or("chrome");
        let tab = input["tabId"]
            .as_u64()
            .filter(|tab| *tab > 0)
            .ok_or_else(|| CoreError::Tool("browser_auth_tab_invalid".into()))?;
        let current_url = self.inner.current_url_for_input(input, tab as i64).await?;
        if Url::parse(&current_url)
            .ok()
            .map(|url| url.origin().ascii_serialization())
            .as_deref()
            != Some(request.origin.as_str())
        {
            return Ok(json!({"status":"origin_changed"}).to_string());
        }
        let request_id = uuid::Uuid::new_v4().to_string();
        let wire = serde_json::to_value(&request)
            .map_err(|_| CoreError::Tool("browser_auth_request_invalid".into()))?;
        let prepared = match self
            .inner
            .prepare_browser_auth(backend, tab, &request_id, &wire)
            .await
        {
            Ok(prepared) => prepared,
            Err(error) => return Ok(auth_failure(&error.to_string()).to_string()),
        };
        let qr_image = if request.qr_code {
            match self.inner.browser_auth_qr_image(&prepared).await {
                Ok(image) => Some(image),
                Err(error) => return Ok(auth_failure(&error.to_string()).to_string()),
            }
        } else {
            None
        };
        let mut ticket = broker
            .begin_current(
                AuthOwner {
                    conversation_id: conversation_id.into(),
                    run_id: run_id.into(),
                    run_revision,
                    backend: backend.into(),
                    tab_id: tab,
                },
                request,
                current.clone(),
                qr_image,
            )
            .map_err(CoreError::Tool)?;
        let lifetime = crate::local_runtime::execution_authority::current_cell_lifetime();
        let response=async {
            let _human_wait = crate::local_runtime::execution_authority::begin_human_wait();
            let received=ticket.receive();tokio::pin!(received);
            loop {
                tokio::select! {
                    response=&mut received=>break response,
                    _=tokio::time::sleep(std::time::Duration::from_millis(100))=> {
                        if !current() || lifetime.as_ref().is_some_and(|live|!live.load(std::sync::atomic::Ordering::SeqCst)) {break Err("browser_auth_cancelled".into());}
                    }
                }
            }
        }.await;
        let result = match response {
            Ok(reply) if reply.declined => json!({"status":"declined"}),
            Ok(reply)
                if current()
                    && lifetime
                        .as_ref()
                        .is_none_or(|live| live.load(std::sync::atomic::Ordering::SeqCst)) =>
            {
                self.inner
                    .submit_browser_auth(&prepared, reply.selected_option.as_deref(), &reply.values)
                    .await
                    .unwrap_or_else(|error| auth_failure(&error.to_string()))
            }
            Ok(_) => json!({"status":"cancelled"}),
            Err(error) if error == "browser_auth_expired" => json!({"status":"expired"}),
            Err(_) => json!({"status":"cancelled"}),
        };
        self.inner.finish_browser_auth(&prepared, false).await;
        Ok(result.to_string())
    }
}

fn auth_failure(error: &str) -> Value {
    // Never forward page exception text or bridge diagnostics into an agent-visible result.
    let status = if error == "origin_changed" || error.ends_with(": origin_changed") {
        "origin_changed"
    } else if error == "locator_invalid" || error.ends_with(": locator_invalid") {
        "locator_invalid"
    } else if error == "page_changed" || error.ends_with(": page_changed") {
        "page_changed"
    } else {
        "unavailable"
    };
    json!({"status":status})
}
