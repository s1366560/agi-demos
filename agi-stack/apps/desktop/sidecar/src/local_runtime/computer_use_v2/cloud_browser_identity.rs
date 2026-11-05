//! Browser scope comes only from an authenticated cloud claim, never REPL input.
use super::*;
use agistack_adapters_browser::caller::BrowserCaller;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct BrowserScope {
    execution_id: String,
    main_conversation_id: String,
    parent_run_id: String,
    engine_session_id: String,
    is_child: bool,
}

impl Claim {
    pub(super) fn browser_caller(&self) -> CoreResult<BrowserCaller> {
        let invalid = || CoreError::Tool("cua_cloud_browser_scope_invalid".into());
        let child = self.child_run_id.as_deref();
        if child.is_some_and(|id| id.is_empty() || id.len() > 256 || id == self.run_id) {
            return Err(invalid());
        }
        if let Some(scope) = &self.browser_scope {
            if scope.execution_id != child.unwrap_or(&self.run_id)
                || scope.main_conversation_id != self.conversation_id
                || scope.parent_run_id != self.run_id
                || scope.engine_session_id != self.session_id
                || scope.is_child != child.is_some()
            {
                return Err(invalid());
            }
        } else if child.is_some() {
            // An older server may issue root claims, but cannot silently discard
            // a child identity and let it inherit its parent's IAB claims.
            return Err(invalid());
        }
        Ok(BrowserCaller {
            session_id: child.unwrap_or(&self.conversation_id).to_owned(),
            main_session_id: self.conversation_id.clone(),
            caller_id: child.unwrap_or(&self.run_id).to_owned(),
            turn_id: self.run_id.clone(),
            allow_dot: child.is_some(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn claim(child: bool) -> Value {
        json!({"request_id":"request","user_id":"user","tenant_id":"tenant",
            "project_id":"project","device_id":"device","conversation_id":"main",
            "run_id":"turn","run_kind":"chat","session_id":"engine","round":1,
            "tool_name":"cua_repl_js","input_json":"{}","permission_profile":"read_only",
            "approved_tools":[],"expires_at":9999999999_i64,"authorization_revision":1,
            "plan_version_id":null,"child_run_id":if child {json!("child-execution")} else {Value::Null},
            "browser_scope":{"execution_id":if child {"child-execution"} else {"turn"},
                "main_conversation_id":"main","parent_run_id":"turn","engine_session_id":"engine","is_child":child}})
    }

    #[test]
    fn root_and_child_are_bound_to_authoritative_run_and_main_conversation() {
        let root: Claim = serde_json::from_value(claim(false)).unwrap();
        let root = root.browser_caller().unwrap();
        assert_eq!(root.session_id, "main");
        assert_eq!(root.caller_id, "turn");
        assert!(!root.allow_dot);
        let child: Claim = serde_json::from_value(claim(true)).unwrap();
        let child = child.browser_caller().unwrap();
        assert_eq!(child.session_id, "child-execution");
        assert_eq!(child.caller_id, "child-execution");
        assert_eq!(child.main_session_id, "main");
        assert_eq!(child.turn_id, "turn");
        assert!(child.allow_dot);
    }

    #[test]
    fn missing_or_conflicting_child_scope_never_inherits_root_control() {
        for (field, value) in [
            ("execution_id", json!("sibling")),
            ("parent_run_id", json!("other")),
            ("main_conversation_id", json!("other")),
            ("engine_session_id", json!("other")),
            ("is_child", json!(false)),
        ] {
            let mut value_claim = claim(true);
            value_claim["browser_scope"][field] = value;
            assert!(serde_json::from_value::<Claim>(value_claim)
                .unwrap()
                .browser_caller()
                .is_err());
        }
        let mut child = claim(true);
        child.as_object_mut().unwrap().remove("browser_scope");
        assert!(serde_json::from_value::<Claim>(child)
            .unwrap()
            .browser_caller()
            .is_err());
        let mut forged = claim(false);
        forged["input_json"] =
            json!(r#"{"child_run_id":"forged","browser_scope":{"is_child":true}}"#);
        assert!(
            !serde_json::from_value::<Claim>(forged)
                .unwrap()
                .browser_caller()
                .unwrap()
                .allow_dot
        );
    }
}
