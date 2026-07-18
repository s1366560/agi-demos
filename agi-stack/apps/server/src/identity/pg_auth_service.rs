use super::*;

impl PgIdentityService {
    pub(super) async fn pg_login(
        &self,
        username: &str,
        password: &str,
        now_ms: i64,
    ) -> Result<LoginOutcome, IdentityError> {
        // 1. Look up by email (the OAuth2 form `username`). Missing user and bad
        //    password both map to the SAME 401 (Python parity), and Python
        //    short-circuits on a missing user without calling verify — so do we.
        let user = self
            .users
            .find_auth_by_email(username)
            .await
            .map_err(IdentityError::internal)?;

        let user = match user {
            Some(u) if verify_password(password, &u.hashed_password) => u,
            _ => {
                return Err(IdentityError::unauthorized(
                    "Incorrect username or password",
                    true,
                ))
            }
        };

        // 2. Inactive accounts get a distinct 401 WITHOUT WWW-Authenticate.
        if !user.is_active {
            return Err(IdentityError::unauthorized(
                "User account is inactive",
                false,
            ));
        }

        // 3. Permissions on the minted key: read/write, plus admin for superusers.
        //    (Python detects admin via a roles join; `is_superuser` is a faithful
        //    proxy here and the field is not response-visible. Full role-join
        //    detection is a documented follow-up.)
        let mut permissions = vec!["read".to_string(), "write".to_string()];
        if user.is_superuser {
            permissions.push("admin".to_string());
        }

        // 4. Mint + persist the session key (name/TTL identical to Python).
        let plain_key = try_generate_api_key().map_err(IdentityError::internal)?;
        let key_id = try_generate_uuid_v4().map_err(IdentityError::internal)?;
        let name = format!("Login Session {username}");
        let expires_at = chrono::DateTime::from_timestamp_millis(now_ms + LOGIN_KEY_TTL_MS);
        self.users
            .insert_api_key(
                &key_id,
                &plain_key,
                &name,
                &user.id,
                expires_at,
                &permissions,
            )
            .await
            .map_err(IdentityError::internal)?;

        // NOTE: Python also runs `_ensure_default_project` (first-login only). It
        // does not affect the response bytes and the users the cutover serves
        // already have projects; skipping it avoids the `projects` table's
        // client-side-default landmine. Documented P2 follow-up.

        Ok(LoginOutcome {
            access_token: plain_key,
            token_type: "bearer".to_string(),
            must_change_password: user.must_change_password,
        })
    }

    pub(super) async fn pg_create_device_code(&self) -> Result<DeviceCodeView, IdentityError> {
        create_device_code_with_store(&*self.device_grants).await
    }

    pub(super) async fn pg_approve_device_code(
        &self,
        user_id: &str,
        user_code: &str,
        now_ms: i64,
    ) -> Result<DeviceApproveView, IdentityError> {
        let user_code = normalize_device_user_code(user_code);
        if user_code.is_empty() {
            return Err(IdentityError::bad_request("user_code required"));
        }

        let device_code = self
            .device_grants
            .device_code_for_user_code(&user_code)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::not_found("user_code expired or unknown"))?;
        let mut transition = self
            .users
            .begin_device_grant_transition(&device_code)
            .await
            .map_err(IdentityError::internal)?;
        let grant = self
            .device_grants
            .get(&device_code)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::gone("device code expired"))?;
        if grant.status != "pending" {
            return Err(IdentityError::conflict(
                "Device code has already been handled",
            ));
        }

        let user = self
            .users
            .find_auth_by_id(user_id)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::unauthorized("Invalid API key", true))?;
        if !user.is_active {
            return Err(IdentityError::unauthorized(
                "User account is inactive",
                false,
            ));
        }

        let mut permissions = vec!["read".to_string(), "write".to_string()];
        if user.is_superuser {
            permissions.push("admin".to_string());
        }

        let plain_key = try_generate_api_key().map_err(IdentityError::internal)?;
        let key_id = try_generate_uuid_v4().map_err(IdentityError::internal)?;
        let name = format!("CLI device login ({user_code})");
        let expires_at = chrono::DateTime::from_timestamp_millis(now_ms + DEVICE_KEY_TTL_MS);
        transition
            .insert_api_key(
                &key_id,
                &plain_key,
                &name,
                &user.id,
                expires_at,
                &permissions,
            )
            .await
            .map_err(IdentityError::internal)?;

        let approved = DeviceGrant::approved(grant.user_code.clone(), user.id, plain_key.clone());
        // Commit the credential before publishing it. Python pollers do not
        // share this PostgreSQL advisory lock and must never observe a bearer
        // that is still uncommitted.
        if let Err(commit_error) = transition.commit().await {
            let revoke_result = self.users.revoke_api_key_by_raw(&plain_key).await;
            if let Err(error) = revoke_result {
                return Err(IdentityError::internal(format!(
                    "device approval commit failed and key rollback failed: {commit_error}; {error}"
                )));
            }
            return Err(IdentityError::internal(commit_error));
        }

        match self
            .device_grants
            .compare_and_set(&device_code, &grant, &approved)
            .await
        {
            Ok(true) => {}
            Ok(false) => {
                self.users
                    .revoke_api_key_by_raw(&plain_key)
                    .await
                    .map_err(|error| {
                        IdentityError::internal(format!(
                            "device approval lost its grant and key rollback failed: {error}"
                        ))
                    })?;
                return Err(IdentityError::conflict(
                    "Device code has already been handled",
                ));
            }
            Err(publish_error) => {
                let revoke_result = self.users.revoke_api_key_by_raw(&plain_key).await;
                let restore_result = self
                    .device_grants
                    .compare_and_set(&device_code, &approved, &grant)
                    .await;
                if let Err(error) = revoke_result {
                    return Err(IdentityError::internal(format!(
                        "device approval publish failed and key rollback failed: \
                         {publish_error}; {error}"
                    )));
                }
                if let Err(error) = restore_result {
                    return Err(IdentityError::internal(format!(
                        "device approval publish failed and grant cleanup failed: \
                         {publish_error}; {error}"
                    )));
                }
                return Err(IdentityError::internal(publish_error));
            }
        }

        Ok(DeviceApproveView {
            status: "approved".to_string(),
        })
    }

    pub(super) async fn pg_poll_device_token(
        &self,
        device_code: &str,
    ) -> Result<DeviceTokenView, IdentityError> {
        let device_code = device_code.trim();
        if device_code.is_empty() {
            return Err(IdentityError::bad_request("device_code required"));
        }
        poll_device_token_from_store(&*self.device_grants, device_code).await
    }

    pub(super) async fn pg_cancel_device_code(
        &self,
        device_code: &str,
    ) -> Result<DeviceCancelView, IdentityError> {
        let device_code = device_code.trim();
        if device_code.is_empty() {
            return Err(IdentityError::bad_request("device_code required"));
        }
        loop {
            let mut transition = self
                .users
                .begin_device_grant_transition(device_code)
                .await
                .map_err(IdentityError::internal)?;
            let Some(grant) = self
                .device_grants
                .get(device_code)
                .await
                .map_err(IdentityError::internal)?
            else {
                transition.commit().await.map_err(IdentityError::internal)?;
                return Ok(DeviceCancelView { success: true });
            };

            if let Some(access_token) = grant.access_token.as_deref() {
                transition
                    .revoke_api_key_by_raw(access_token)
                    .await
                    .map_err(IdentityError::internal)?;
                // Make the token unusable before removing its only server-side
                // recovery record. A failed Redis operation remains retryable.
                transition.commit().await.map_err(IdentityError::internal)?;
            } else {
                let deleted = self
                    .device_grants
                    .compare_and_delete_pair(device_code, &grant)
                    .await
                    .map_err(IdentityError::internal)?;
                if deleted {
                    transition.commit().await.map_err(IdentityError::internal)?;
                    return Ok(DeviceCancelView { success: true });
                }
                transition
                    .rollback()
                    .await
                    .map_err(IdentityError::internal)?;
                continue;
            }

            if self
                .device_grants
                .compare_and_delete_pair(device_code, &grant)
                .await
                .map_err(IdentityError::internal)?
            {
                return Ok(DeviceCancelView { success: true });
            }
        }
    }
}
