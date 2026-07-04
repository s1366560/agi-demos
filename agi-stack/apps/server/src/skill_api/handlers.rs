use super::*;

pub(super) async fn create_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SkillCreatePayload>,
) -> Result<(StatusCode, Json<SkillView>), SkillApiError> {
    let view = app
        .skills
        .create_skill(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

pub(super) async fn list_skills(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<SkillListQuery>,
) -> Result<Json<SkillListView>, SkillApiError> {
    Ok(Json(
        app.skills.list_skills(&identity.user_id, query).await?,
    ))
}

pub(super) async fn import_skill_package(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SkillImportPayload>,
) -> Result<(StatusCode, Json<SkillLifecycleView>), SkillApiError> {
    let view = app
        .skills
        .import_package(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

pub(super) async fn import_skill_zip_package(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    multipart: Multipart,
) -> Result<(StatusCode, Json<SkillLifecycleView>), SkillApiError> {
    let body = zip_import::skill_import_payload_from_multipart(multipart).await?;
    let view = app
        .skills
        .import_package(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

pub(super) async fn import_system_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SystemSkillImportPayload>,
) -> Result<(StatusCode, Json<SkillLifecycleView>), SkillApiError> {
    let view = app
        .skills
        .import_system_skill(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

pub(super) async fn list_system_skills(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<SystemSkillListQuery>,
) -> Result<Json<SkillListView>, SkillApiError> {
    let mut view = app
        .skills
        .list_system_skills(
            &identity.user_id,
            q.tenant_id.as_deref(),
            q.status.as_deref(),
        )
        .await?;
    let disabled_names = app
        .tenant_skill_configs
        .list_configs(&identity.user_id, q.tenant_id.as_deref())
        .await
        .map_err(tenant_skill_config_error)?
        .disabled_system_skill_names();
    filter_disabled_system_skills(&mut view, &disabled_names);
    Ok(Json(view))
}

pub(super) async fn get_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_skill(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
            .await?,
    ))
}

pub(super) async fn update_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
    Json(body): Json<SkillUpdatePayload>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .update_skill(&identity.user_id, q.tenant_id.as_deref(), &skill_id, body)
            .await?,
    ))
}

pub(super) async fn delete_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<StatusCode, SkillApiError> {
    app.skills
        .delete_skill(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

pub(super) async fn update_skill_status(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<SkillStatusQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .update_status(
                &identity.user_id,
                q.tenant_id.as_deref(),
                &skill_id,
                &q.status,
            )
            .await?,
    ))
}

pub(super) async fn get_skill_content(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillContentView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_content(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
            .await?,
    ))
}

pub(super) async fn update_skill_content(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
    Json(body): Json<SkillContentUpdatePayload>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .update_content(&identity.user_id, q.tenant_id.as_deref(), &skill_id, body)
            .await?,
    ))
}

pub(super) async fn list_skill_versions(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<SkillVersionQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillVersionListView>, SkillApiError> {
    Ok(Json(
        app.skills
            .list_versions(
                &identity.user_id,
                q.tenant_id.as_deref(),
                &skill_id,
                q.limit.unwrap_or(50),
                q.offset.unwrap_or(0),
            )
            .await?,
    ))
}

pub(super) async fn get_skill_version(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path((skill_id, version_number)): Path<(String, i32)>,
) -> Result<Json<SkillVersionDetailView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_version(
                &identity.user_id,
                q.tenant_id.as_deref(),
                &skill_id,
                version_number,
            )
            .await?,
    ))
}

pub(super) async fn rollback_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
    Json(body): Json<SkillRollbackPayload>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .rollback(&identity.user_id, q.tenant_id.as_deref(), &skill_id, body)
            .await?,
    ))
}

pub(super) async fn export_skill_package(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillPackageView>, SkillApiError> {
    Ok(Json(
        app.skills
            .export_package(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
            .await?,
    ))
}

pub(super) async fn get_skill_evolution_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
) -> Result<Json<SkillEvolutionConfigView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_evolution_config(&identity.user_id, q.tenant_id.as_deref())
            .await?,
    ))
}

pub(super) async fn update_skill_evolution_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SkillEvolutionConfigUpdatePayload>,
) -> Result<Json<SkillEvolutionConfigView>, SkillApiError> {
    Ok(Json(
        app.skills
            .update_evolution_config(&identity.user_id, q.tenant_id.as_deref(), body)
            .await?,
    ))
}

pub(super) async fn get_skill_evolution_overview(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<SkillEvolutionOverviewQuery>,
) -> Result<Json<SkillEvolutionOverviewView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_evolution_overview(&identity.user_id, query)
            .await?,
    ))
}

pub(super) async fn get_skill_evolution_detail(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<SkillEvolutionDetailQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillEvolutionDetailView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_evolution_detail(&identity.user_id, query, &skill_id)
            .await?,
    ))
}

pub(super) async fn run_tenant_skill_evolution(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
) -> Result<Json<SkillEvolutionTenantRunView>, SkillApiError> {
    Ok(Json(
        app.skills
            .run_tenant_evolution(&identity.user_id, q.tenant_id.as_deref())
            .await?,
    ))
}

pub(super) async fn run_skill_evolution(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillEvolutionRunView>, SkillApiError> {
    Ok(Json(
        app.skills
            .run_skill_evolution(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
            .await?,
    ))
}

pub(super) async fn apply_skill_evolution_job(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(job_id): Path<String>,
) -> Result<Json<SkillEvolutionJobView>, SkillApiError> {
    Ok(Json(
        app.skills
            .apply_evolution_job(&identity.user_id, q.tenant_id.as_deref(), &job_id)
            .await?,
    ))
}

pub(super) async fn reject_skill_evolution_job(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(job_id): Path<String>,
) -> Result<Json<SkillEvolutionJobView>, SkillApiError> {
    Ok(Json(
        app.skills
            .reject_evolution_job(&identity.user_id, q.tenant_id.as_deref(), &job_id)
            .await?,
    ))
}
