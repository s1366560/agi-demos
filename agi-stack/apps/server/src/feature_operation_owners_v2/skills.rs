use super::{
    declared, parameter, resource, FeatureOperationOwnerV2, PROJECT, TENANT, TENANT_PROJECT,
};

pub(super) fn owner(method: &str, route: &str) -> Option<FeatureOperationOwnerV2> {
    let owner = match (method, route) {
        ("GET", "/api/v1/skills" | "/api/v1/skills/") => {
            declared(&["tenant-skills"]).query(TENANT_PROJECT)
        }
        (
            "POST",
            "/api/v1/skills"
            | "/api/v1/skills/"
            | "/api/v1/skills/import"
            | "/api/v1/skills/system/import",
        ) => declared(&["tenant-skills"]).query(TENANT).body(PROJECT),
        ("POST", "/api/v1/skills/import/zip") => declared(&["tenant-skills"])
            .query(TENANT)
            .body(PROJECT)
            .multipart(),
        (
            "GET",
            "/api/v1/skills/system/list"
            | "/api/v1/skills/evolution/config"
            | "/api/v1/skills/evolution/overview"
            | "/api/v1/tenant/skills/config/"
            | "/api/v1/tenant/skills/config"
            | "/api/v1/tenant/skills/config/status/:system_skill_name"
            | "/api/v1/tenant/skills/config/:system_skill_name",
        )
        | ("PUT", "/api/v1/skills/evolution/config")
        | ("DELETE", "/api/v1/tenant/skills/config/:system_skill_name")
        | (
            "POST",
            "/api/v1/skills/evolution/run"
            | "/api/v1/tenant/skills/config/disable"
            | "/api/v1/tenant/skills/config/override"
            | "/api/v1/tenant/skills/config/enable",
        ) => declared(&["tenant-skills"]).query(TENANT),
        (
            "POST",
            "/api/v1/skills/evolution/jobs/:job_id/apply"
            | "/api/v1/skills/evolution/jobs/:job_id/reject",
        ) => declared(&["tenant-skills"])
            .query(TENANT)
            .path(const { &[parameter("job_id", "job_id")] })
            .resources(const { &[resource("skill_evolution", "job_id")] }),
        (
            "GET",
            "/api/v1/skills/:skill_id"
            | "/api/v1/skills/:skill_id/evolution"
            | "/api/v1/skills/:skill_id/content"
            | "/api/v1/skills/:skill_id/versions"
            | "/api/v1/skills/:skill_id/versions/:version_number"
            | "/api/v1/skills/:skill_id/export",
        )
        | ("PUT", "/api/v1/skills/:skill_id" | "/api/v1/skills/:skill_id/content")
        | ("DELETE", "/api/v1/skills/:skill_id")
        | ("PATCH", "/api/v1/skills/:skill_id/status")
        | (
            "POST",
            "/api/v1/skills/:skill_id/evolution/run" | "/api/v1/skills/:skill_id/rollback",
        ) => declared(&["tenant-skills"])
            .query(TENANT)
            .path(const { &[parameter("skill_id", "skill_id")] })
            .resources(const { &[resource("skill", "skill_id")] }),
        _ => return None,
    };
    Some(owner)
}
