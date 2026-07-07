use super::{MethodMatchKind, MethodRule};

/// Path prefixes already served by the Rust server. Everything else falls
/// through to the Python upstream. Add a prefix here to strangle a capability;
/// remove it to roll back.
pub const STRANGLED_PREFIXES: &[&str] = &[
    "/api/v1/memories",
    "/api/v1/episodes",
    "/api/v1/recall",
    // P2 login vertical (surgical — coarse prefix match, so only fully-covered
    // paths are listed). `/auth/token` and `/auth/oauth/*` are complete in Rust;
    // other `/auth/*` siblings (force-change-password, keys, ...) stay in Python.
    "/api/v1/auth/token",
    "/api/v1/auth/oauth",
];

/// Method-scoped strangler rules for resources where the Rust backend only owns
/// read-side routes. This prevents a coarse `/api/v1/tenants` prefix from
/// accidentally capturing sibling endpoints such as `/tenants/{id}/members` or
/// write operations that still belong to Python.
pub const STRANGLED_METHOD_RULES: &[MethodRule] = &[
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "PATCH",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "invitations",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "invitations",
            excluded: &[],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "invitations",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "policies"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "policies"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "policies", "check"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "approval-requests"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "approval-requests", "*", "resolve"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "decision-records"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["trust", "decision-records", "*"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildExcept(&["sandboxes"]),
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildExcept(&["sandboxes"]),
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildExcept(&["sandboxes"]),
    },
    // P7 project schema CRUD slice. Collection GET/POST plus item PUT/DELETE
    // for entity/edge types and DELETE for mappings are Rust-owned; item GET
    // and unsupported methods stay Python-owned. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "entities"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "entities"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "entities", "*"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "entities", "*"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "edges"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "edges"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "edges", "*"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "edges", "*"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "mappings"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "mappings"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["schema", "mappings", "*"],
            excluded: &["sandboxes"],
        },
    },
    // P7 cron job read slice. Only list/detail/run-history GETs are
    // Rust-owned; create/update/delete/toggle/manual-run and scheduler runtime
    // remain Python-owned. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["cron-jobs"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["cron-jobs", "*"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["cron-jobs", "*", "runs"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "stats",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "PATCH",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "members",
            excluded: &["sandboxes"],
        },
    },
    // P5 sandbox profile discovery exact slice. Rollback by deleting this one
    // rule plus the Rust handler; the legacy `/sandbox` lifecycle/tools/events
    // siblings remain Python-owned.
    MethodRule {
        method: "GET",
        path: "/api/v1/sandbox/profiles",
        match_kind: MethodMatchKind::Exact,
    },
    // P7 runtime engine catalog exact slice. Rollback by deleting this one
    // rule plus the Rust handler; sandbox lifecycle, image management, and
    // engine execution remain Python-owned.
    MethodRule {
        method: "GET",
        path: "/api/v1/engines",
        match_kind: MethodMatchKind::Exact,
    },
    // P7 system metadata exact slice. Rollback by deleting these two rules plus
    // the Rust handler; runtime mutation and unrelated `/system/*` siblings
    // remain Python-owned.
    MethodRule {
        method: "GET",
        path: "/api/v1/system/features",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/system/info",
        match_kind: MethodMatchKind::Exact,
    },
    // P7 maintenance status exact read slice. Rollback by deleting this rule
    // plus the Rust handler; refresh/optimize/invalidation runtime mutation
    // siblings remain Python-owned.
    MethodRule {
        method: "GET",
        path: "/api/v1/maintenance/status",
        match_kind: MethodMatchKind::Exact,
    },
    // P2 current-user read exact slice. Rollback by deleting these two rules
    // plus the Rust handler; user updates, auth key management, and
    // force-change-password remain Python-owned.
    MethodRule {
        method: "GET",
        path: "/api/v1/auth/me",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/users/me",
        match_kind: MethodMatchKind::Exact,
    },
    // P5 sandbox HTTP control-plane flip. These are deliberately method-scoped
    // and exclude the reserved `/projects/sandboxes/*` sibling namespace so the
    // data-plane proxy and unported collection siblings can be rolled back by
    // deleting only this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/projects/sandboxes",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "sandbox",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "sandbox",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "sandbox",
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "health"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "stats"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "sync"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "execute"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "proxy-auth-cookie"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "restart"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "desktop"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "desktop"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "terminal"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "terminal"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "http-services"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "http-services"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "http-services", "*", "preview-session"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["sandbox", "http-services", "*"],
            excluded: &["sandboxes"],
        },
    },
    // P5 sandbox path data-plane flip. These remain exact method/tail rules:
    // no coarse `/projects/{id}/sandbox` prefix, and no preview-host wildcard.
    MethodRule {
        method: "GET",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailPrefixExcept {
            tail_prefix: &["sandbox", "desktop", "proxy"],
            excluded: &["sandboxes"],
        },
    },
    MethodRule {
        method: "*",
        path: "/api/v1/projects",
        match_kind: MethodMatchKind::SingleChildWithTailPrefixExcept {
            tail_prefix: &["sandbox", "http-services", "*", "proxy"],
            excluded: &["sandboxes"],
        },
    },
    // P4 graph/search foundation flip. These are project-scoped GraphStore
    // read/write surfaces already covered by Rust goldens; broader graph
    // traversal fan-out contracts stay in Python.
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/export",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/graph/import",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/communities",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/graph/communities/rebuild",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/communities/rebuild/jobs",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/communities",
        match_kind: MethodMatchKind::SingleChildExcept(&["rebuild"]),
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/communities",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &["rebuild"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/entities",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/graph/entities",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/entities/types",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/entities",
        match_kind: MethodMatchKind::SingleChildExcept(&["types"]),
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/entities",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "relationships",
            excluded: &["types"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/graph/relationships",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph/memory/graph",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/graph/memory/graph/subgraph",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/search-enhanced/advanced",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/search-enhanced/graph-traversal",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/search-enhanced/community",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/search-enhanced/temporal",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/search-enhanced/faceted",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/search-enhanced/capabilities",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/memory/search",
        match_kind: MethodMatchKind::Exact,
    },
    // P5 channel config read/status + DB-only observability foundation, exact
    // Feishu webhook ingress, and local connection lifecycle status markers.
    // Config writes, plugin runtime management, message routing, and delivery
    // runtime endpoints remain Python-owned.
    // Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/channels/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["configs"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/channels/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["observability", "outbox"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/channels/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["observability", "summary"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/channels/projects",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["observability", "session-bindings"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/channels/configs",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/channels/configs",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "status",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/channels/configs",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "connect",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/channels/configs",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "disconnect",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/channels/configs",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "health-check",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/channels/configs",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["webhook", "feishu"],
            excluded: &[],
        },
    },
    // P5 skill store/versioning flip. Only database-backed CRUD, content,
    // status, versions, rollback, JSON/zip package import, package export,
    // filesystem system import, skill-evolution config/overview/detail,
    // evolution job apply/reject, and run admission are in Rust.
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills/system/list",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills/system/import",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills/import",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills/import/zip",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills/evolution/config",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/skills/evolution/config",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills/evolution/overview",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills/evolution/run",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills/evolution/jobs",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "apply",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills/evolution/jobs",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "reject",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildExcept(&["system"]),
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildExcept(&["system"]),
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildExcept(&["system"]),
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "content",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "content",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "PATCH",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "status",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "versions",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixAndGrandchildExcept {
            suffix: "versions",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "rollback",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "export",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "evolution",
            excluded: &["system"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/skills",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["evolution", "run"],
            excluded: &["system"],
        },
    },
    // P3/F11 SubAgent template marketplace discovery exact slice. Rollback by
    // deleting this one rule plus the Rust handler; template list/create/detail,
    // install, and runtime SubAgent siblings remain Python-owned.
    MethodRule {
        method: "GET",
        path: "/api/v1/subagents/templates/categories",
        match_kind: MethodMatchKind::Exact,
    },
    // P5 tenant skill config flip. This owns only the tenant disable/override
    // collection and its exact action/status children; other `/tenant/*`
    // resources continue to fall back to Python. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/tenant/skills/config",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenant/skills/config/disable",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenant/skills/config/override",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenant/skills/config/enable",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenant/skills/config",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/tenant/skills/config",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenant/skills/config",
        match_kind: MethodMatchKind::FixedChildWithGrandchild { child: "status" },
    },
    // P6 workspace autonomy tick flip. This is only the durable supervisor
    // outbox trigger; sibling autonomy/runtime endpoints remain Python-owned.
    // Rollback = delete this single rule.
    MethodRule {
        method: "POST",
        path: "/api/v1/workspaces",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["autonomy", "tick"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/agent/ws",
        match_kind: MethodMatchKind::Exact,
    },
    // P3/F11 builtin slash-command catalog exact slice. Rollback by deleting
    // this one rule plus the Rust handler; command execution, agent tools,
    // workflow patterns, and conversation/message siblings remain Python-owned.
    MethodRule {
        method: "GET",
        path: "/api/v1/agent/commands",
        match_kind: MethodMatchKind::Exact,
    },
    // F7 agent event replay flip. Only the completed replay resource moves;
    // sibling `/agent/conversations/*` routes remain Python-owned. Rollback =
    // delete this single rule.
    MethodRule {
        method: "GET",
        path: "/api/v1/agent/conversations",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "events",
            excluded: &[],
        },
    },
    // P7 observability/events exact read slice. Event log list/type discovery
    // are Rust-owned; filter/export siblings remain Python-owned. Rollback =
    // delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/events",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/events/types",
        match_kind: MethodMatchKind::Exact,
    },
    // P7 data stats/export/cleanup exact slice. Cleanup is POST-only and keeps
    // Python's dry-run/admin-gated delete contract. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/data/stats",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/data/export",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/data/cleanup",
        match_kind: MethodMatchKind::Exact,
    },
    // P7 tenant audit-log read/export slice. List/filter/runtime-hook reads and
    // bounded export are Rust-owned; write-side logging remains Python-owned.
    // Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "audit-logs",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["audit-logs", "filter"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["audit-logs", "export"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["audit-logs", "runtime-hooks"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["audit-logs", "runtime-hooks", "summary"],
            excluded: &[],
        },
    },
    // P7 notification exact API-v1 slice. Trailing-slash current-user list plus
    // mark-read/read-all/delete/create mutations are Rust-owned; no-slash list
    // and unknown children remain Python-owned. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/notifications/",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/notifications/read-all",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/notifications/create",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/notifications",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "read",
            excluded: &["read-all", "create"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/notifications",
        match_kind: MethodMatchKind::SingleChildExcept(&["read-all", "create"]),
    },
    // P7 LLM provider metadata slice. Static provider discovery, provider
    // metadata list/detail/create/update/soft-delete, admin-only env detection,
    // read-only model catalog list/search/provider-model routes, latest
    // persisted provider-health reads, tenant assignment list reads, and
    // provider usage statistics reads are Rust-owned; catalog refresh, active
    // health checks, tenant assignment mutations/resolution, system resilience
    // runtime, and usage writes remain Python-owned.
    // Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers/",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/llm-providers",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/llm-providers/",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers/types",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers/env-detection",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers/models/catalog",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers/models/catalog/search",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers",
        match_kind: MethodMatchKind::FixedChildWithGrandchild { child: "models" },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers",
        match_kind: MethodMatchKind::SingleChildExcept(&[
            "models",
            "types",
            "env-detection",
            "tenants",
            "system",
        ]),
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/llm-providers",
        match_kind: MethodMatchKind::SingleChildExcept(&[
            "models",
            "types",
            "env-detection",
            "tenants",
            "system",
        ]),
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/llm-providers",
        match_kind: MethodMatchKind::SingleChildExcept(&[
            "models",
            "types",
            "env-detection",
            "tenants",
            "system",
        ]),
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "assignments",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "health",
            excluded: &["models", "types", "env-detection", "tenants", "system"],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/llm-providers",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "usage",
            excluded: &["models", "types", "env-detection", "tenants", "system"],
        },
    },
    // P7 deploy read slice. Only list/detail/latest GETs are Rust-owned;
    // create, lifecycle transitions, cancel, and progress SSE remain
    // Python-owned. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/deploys/",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/deploys",
        match_kind: MethodMatchKind::SingleChildExcept(&["instances"]),
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/deploys/instances",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "latest",
            excluded: &[],
        },
    },
    // P7 instance read slice. Only current-tenant list/detail GETs, config
    // config GET/PUTs, pending-config PUT, LLM-config GET/PUTs, member
    // list/search/mutations, and channel config list GETs are Rust-owned;
    // create/update/delete, scale/restart, config apply, files, channel
    // mutations/tests, and runtime side effects remain Python-owned.
    // Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/instances/",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "config",
            excluded: &[],
        },
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "config",
            excluded: &[],
        },
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["config", "pending"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "llm-config",
            excluded: &[],
        },
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "llm-config",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "members",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["members", "search-users"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["members", "*"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithTailExcept {
            tail: &["members", "*"],
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/instances",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "channels",
            excluded: &[],
        },
    },
    // P7 gene marketplace read slice. Only list/detail GETs are Rust-owned;
    // gene writes, genomes, instance installation, ratings, reviews, and
    // evolution events remain Python-owned. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/genes/",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/genes/genomes",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/genes/genomes",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/genes",
        match_kind: MethodMatchKind::SingleChildExcept(&["genomes", "evolution", "instances"]),
    },
    // P7 billing exact slice. Tenant billing summary, invoice listing, and
    // owner-only plan upgrade are Rust-owned; other billing writes stay Python.
    // Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "billing",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "invoices",
            excluded: &[],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenants",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "upgrade",
            excluded: &[],
        },
    },
    // P7 support ticket slice. API-v1 and legacy ticket
    // list/detail/create/update/close are Rust-owned; unknown ticket children
    // remain Python-owned. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/support/tickets",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/support/tickets",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/support/tickets",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/support/tickets",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/support/tickets",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "close",
            excluded: &[],
        },
    },
    MethodRule {
        method: "GET",
        path: "/support/tickets",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/support/tickets",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/support/tickets",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "PUT",
        path: "/support/tickets",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "POST",
        path: "/support/tickets",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "close",
            excluded: &[],
        },
    },
    // P7 artifact slice. List/detail/category-list GETs plus exact content
    // save-back are Rust-owned; download, URL refresh, deletion, upload, and
    // multipart writes remain Python-owned. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/artifacts",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/artifacts",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/artifacts/categories/list",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/artifacts",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "content",
            excluded: &["categories"],
        },
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/artifacts",
        match_kind: MethodMatchKind::SingleChildExcept(&["categories"]),
    },
    // P7 attachment read + exact simple-upload/hard-delete slice. List/detail
    // metadata GETs, POST `/api/v1/attachments/upload/simple`, and DELETE
    // `/api/v1/attachments/{id}` are Rust-owned; multipart and download URL
    // generation stay Python-owned. Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/attachments",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/attachments",
        match_kind: MethodMatchKind::SingleChildExcept(&["upload"]),
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/attachments/upload/simple",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/attachments",
        match_kind: MethodMatchKind::SingleChildExcept(&["upload"]),
    },
    // P4/P7 graph-store metadata slice. Static engine discovery, list/detail,
    // and metadata CRUD are Rust-owned; live connection tests stay Python-owned.
    // Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/graph-stores/types",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph-stores",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/graph-stores",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/graph-stores",
        match_kind: MethodMatchKind::SingleChildExcept(&["types", "test"]),
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/graph-stores",
        match_kind: MethodMatchKind::SingleChildExcept(&["types", "test"]),
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/graph-stores",
        match_kind: MethodMatchKind::SingleChildExcept(&["types", "test"]),
    },
    // P7 retrieval-store metadata slice. Static engine discovery, list/detail,
    // and metadata CRUD are Rust-owned; live connection tests stay Python-owned.
    // Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/retrieval-stores/types",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/retrieval-stores",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/retrieval-stores",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/retrieval-stores",
        match_kind: MethodMatchKind::SingleChildExcept(&["types", "test"]),
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/retrieval-stores",
        match_kind: MethodMatchKind::SingleChildExcept(&["types", "test"]),
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/retrieval-stores",
        match_kind: MethodMatchKind::SingleChildExcept(&["types", "test"]),
    },
    // P7 admin DLQ slice. List/detail/stats reads plus retry/discard/cleanup
    // mutations are Rust-owned. Other DLQ siblings stay Python-owned.
    // Rollback = delete this block.
    MethodRule {
        method: "GET",
        path: "/api/v1/admin/dlq/messages",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/admin/dlq/messages",
        match_kind: MethodMatchKind::SingleChildExcept(&["retry", "discard"]),
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/admin/dlq/messages",
        match_kind: MethodMatchKind::SingleChildExcept(&["retry", "discard"]),
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/admin/dlq/messages/retry",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/admin/dlq/messages",
        match_kind: MethodMatchKind::SingleChildWithSuffixExcept {
            suffix: "retry",
            excluded: &["retry", "discard"],
        },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/admin/dlq/messages/discard",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/admin/dlq/cleanup/expired",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/admin/dlq/cleanup/resolved",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/admin/dlq/stats",
        match_kind: MethodMatchKind::Exact,
    },
    // P7 tenant webhook CRUD slice. Only the method-scoped single-child CRUD
    // contract is Rust-owned; webhook provider delivery remains Python-owned.
    // Rollback = delete these four method rules.
    MethodRule {
        method: "GET",
        path: "/api/v1/tenant-webhooks",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/tenant-webhooks",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "PUT",
        path: "/api/v1/tenant-webhooks",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "DELETE",
        path: "/api/v1/tenant-webhooks",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/shared",
        match_kind: MethodMatchKind::SingleChild,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/auth/device/code",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/auth/device/approve",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/auth/device/token",
        match_kind: MethodMatchKind::Exact,
    },
    MethodRule {
        method: "GET",
        path: "/api/v1/invitations",
        match_kind: MethodMatchKind::FixedChildWithGrandchild { child: "verify" },
    },
    MethodRule {
        method: "POST",
        path: "/api/v1/invitations",
        match_kind: MethodMatchKind::FixedChildWithGrandchild { child: "accept" },
    },
];
