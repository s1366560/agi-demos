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
    // other `/auth/*` siblings (force-change-password, me, ...) stay in Python.
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
    // migration/export/import and tenant fan-out contracts stay in Python.
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
    // P5 channel config read/status + DB-only observability foundation. Only
    // these read-side routes are Rust-owned; config writes, plugin runtime
    // management, active connection summary, webhook ingress and
    // delivery/runtime endpoints remain Python-owned.
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
    // P5 skill store/versioning flip. Only database-backed CRUD, content,
    // status, versions, rollback, JSON/zip package import, package export,
    // filesystem system import, skill-evolution config/overview/detail, and
    // evolution job apply/reject are in Rust; evolution run siblings remain
    // Python until scheduler semantics move.
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
