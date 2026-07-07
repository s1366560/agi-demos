//! Live-Neo4j cross-adapter parity test for [`Neo4jGraphStore`].
//!
//! **Gated on a reachable Neo4j.** It targets `NEO4J_TEST_URI` (default
//! `bolt://localhost:7687`) with `NEO4J_TEST_USER` / `NEO4J_TEST_PASSWORD`
//! (defaults `neo4j` / `your_password_here`, matching the dev Docker Neo4j). If
//! the database is unreachable the test short-circuits to a pass with a `[skip]`
//! note, so `cargo test --workspace` is green with or without a live graph.
//!
//! What it proves: the production Neo4j tier returns results **byte-identical** to
//! the in-memory tier (`InMemoryGraphStore`) for the same seed data, across
//! `get_entity` / `neighbors` / `subgraph`(depth 0..=4) / `search_entities`. That
//! is the whole point of the shared `GraphStore` port — the portable core cannot
//! tell which tier is behind it, so the strangler can flip `/graph/*` traffic from
//! Python to Rust with no behavioural drift.
//!
//! Hermetic on a shared database: every run uses a **unique `project_id`** and
//! `DETACH DELETE`s its nodes before and after, so concurrent runs and reruns do
//! not collide.

use std::time::{SystemTime, UNIX_EPOCH};

use agistack_adapters_mem::InMemoryGraphStore;
use agistack_adapters_neo4j::{connect, Neo4jGraphStore};
use agistack_core::model::{GraphEntity, GraphStatsScope, Relationship};
use agistack_core::ports::GraphStore;
use neo4rs::{query, Graph};

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key)
        .ok()
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| default.to_string())
}

/// Connect to the test Neo4j, or return `None` (skip) if unreachable.
async fn graph_or_skip(test: &str) -> Option<Graph> {
    let uri = env_or("NEO4J_TEST_URI", "bolt://localhost:7687");
    let user = env_or("NEO4J_TEST_USER", "neo4j");
    let password = env_or("NEO4J_TEST_PASSWORD", "your_password_here");
    match connect(&uri, &user, &password).await {
        Ok(g) => match g.run(query("RETURN 1")).await {
            Ok(_) => Some(g),
            Err(e) => {
                eprintln!("[skip] {test}: Neo4j at {uri} not queryable: {e}");
                None
            }
        },
        Err(e) => {
            eprintln!("[skip] {test}: Neo4j at {uri} unreachable: {e}");
            None
        }
    }
}

/// A unique project id so parallel runs / reruns never collide on the shared graph.
fn unique_project(tag: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("agistack-neo4j-it-{tag}-{}-{nanos}", std::process::id())
}

async fn wipe(graph: &Graph, project: &str) {
    graph
        .run(query("MATCH (e:Entity {project_id: $pid}) DETACH DELETE e").param("pid", project))
        .await
        .expect("cleanup wipe");
}

fn ent(uuid: &str, name: &str, summary: &str, project: &str) -> GraphEntity {
    GraphEntity {
        uuid: uuid.into(),
        name: name.into(),
        entity_type: "Concept".into(),
        summary: summary.into(),
        project_id: project.into(),
        tenant_id: None,
        created_at_ms: 0,
        name_embedding: None,
    }
}

fn rel(uuid: &str, src: &str, dst: &str, rt: &str, project: &str) -> Relationship {
    Relationship {
        uuid: uuid.into(),
        source_uuid: src.into(),
        target_uuid: dst.into(),
        relation_type: rt.into(),
        fact: "".into(),
        score: 1.0,
        project_id: project.into(),
        created_at_ms: 0,
    }
}

/// Seed the same entities-then-relationships into both stores.
async fn seed(
    neo: &Neo4jGraphStore,
    mem: &InMemoryGraphStore,
    ents: &[GraphEntity],
    rels: &[Relationship],
) {
    for e in ents {
        neo.upsert_entity(e.clone()).await.expect("neo upsert ent");
        mem.upsert_entity(e.clone()).await.expect("mem upsert ent");
    }
    for r in rels {
        neo.upsert_relationship(r.clone())
            .await
            .expect("neo upsert rel");
        mem.upsert_relationship(r.clone())
            .await
            .expect("mem upsert rel");
    }
}

#[tokio::test]
async fn neo4j_matches_in_memory_across_all_reads() {
    let Some(graph) = graph_or_skip("neo4j_matches_in_memory_across_all_reads").await else {
        return;
    };
    let project = unique_project("parity");
    let other = unique_project("other"); // isolation decoy project
    wipe(&graph, &project).await;
    wipe(&graph, &other).await;

    let neo = Neo4jGraphStore::new(graph.clone());
    let mem = InMemoryGraphStore::new();

    // Diamond + tail so depth bounds actually bite:
    //   a -> b -> d ,  a -> c -> d ,  d -> e
    let ents = vec![
        ent("a", "Alpha", "the alpha root", &project),
        ent("b", "Beta", "beta branch left", &project),
        ent("c", "Cappa", "cappa branch right ALPHA", &project),
        ent("d", "Delta", "delta join", &project),
        ent("e", "Epsilon", "epsilon tail", &project),
    ];
    let rels = vec![
        rel("r1", "a", "b", "MENTIONS", &project),
        rel("r2", "a", "c", "RELATES_TO", &project),
        rel("r3", "b", "d", "MENTIONS", &project),
        rel("r4", "c", "d", "MENTIONS", &project),
        rel("r5", "d", "e", "MENTIONS", &project),
    ];
    seed(&neo, &mem, &ents, &rels).await;

    // Decoy: same uuids in a different project must never leak in.
    let decoy_ents = vec![ent("a", "AlphaX", "leak canary alpha", &other)];
    for e in &decoy_ents {
        neo.upsert_entity(e.clone()).await.expect("neo decoy");
    }

    // get_entity: every seed + a missing one.
    for uuid in ["a", "b", "c", "d", "e", "missing"] {
        let got_neo = neo.get_entity(&project, uuid).await.expect("neo get");
        let got_mem = mem.get_entity(&project, uuid).await.expect("mem get");
        assert_eq!(got_neo, got_mem, "get_entity parity for {uuid}");
    }

    // neighbors: every seed.
    for uuid in ["a", "b", "c", "d", "e"] {
        let n_neo = neo.neighbors(&project, uuid).await.expect("neo neighbors");
        let n_mem = mem.neighbors(&project, uuid).await.expect("mem neighbors");
        assert_eq!(n_neo, n_mem, "neighbors parity for {uuid}");
    }

    // subgraph: seed a and d, depth 0..=4.
    for seed_uuid in ["a", "d"] {
        for depth in 0..=4usize {
            let sg_neo = neo
                .subgraph(&project, seed_uuid, depth)
                .await
                .expect("neo subgraph");
            let sg_mem = mem
                .subgraph(&project, seed_uuid, depth)
                .await
                .expect("mem subgraph");
            assert_eq!(
                sg_neo, sg_mem,
                "subgraph parity for seed {seed_uuid} depth {depth}"
            );
        }
    }

    // search_entities: case-insensitive over name OR summary, plus a limit.
    for (q, limit) in [
        ("alpha", 10usize),
        ("branch", 10),
        ("e", 2),
        ("zzz-none", 10),
    ] {
        let s_neo = neo
            .search_entities(&project, q, limit)
            .await
            .expect("neo search");
        let s_mem = mem
            .search_entities(&project, q, limit)
            .await
            .expect("mem search");
        assert_eq!(s_neo, s_mem, "search parity for {q:?} limit {limit}");
    }

    let mut old_episode = ent("ep-old", "Old episode", "cleanup candidate", &project);
    old_episode.entity_type = "Episodic".to_string();
    old_episode.created_at_ms = 1_000;
    let mut fresh_episode = ent("ep-fresh", "Fresh episode", "keep", &project);
    fresh_episode.entity_type = "Episodic".to_string();
    fresh_episode.created_at_ms = 10_000;
    let cleanup_ents = vec![old_episode, fresh_episode];
    let cleanup_rels = vec![
        rel("r-old-episode", "a", "ep-old", "MENTIONS", &project),
        rel("r-fresh-episode", "a", "ep-fresh", "MENTIONS", &project),
    ];
    seed(&neo, &mem, &cleanup_ents, &cleanup_rels).await;
    let cleanup_scope = GraphStatsScope::Projects(vec![project.clone()]);
    assert_eq!(
        neo.stats(cleanup_scope.clone()).await.expect("neo stats"),
        mem.stats(cleanup_scope.clone()).await.expect("mem stats"),
        "stats parity before cleanup"
    );
    assert_eq!(
        neo.export(cleanup_scope.clone()).await.expect("neo export"),
        mem.export(cleanup_scope.clone()).await.expect("mem export"),
        "export parity before cleanup"
    );
    assert_eq!(
        neo.count_episodes_older_than(cleanup_scope.clone(), 5_000)
            .await
            .expect("neo cleanup count"),
        mem.count_episodes_older_than(cleanup_scope.clone(), 5_000)
            .await
            .expect("mem cleanup count"),
        "cleanup count parity"
    );
    assert_eq!(
        neo.delete_episodes_older_than(cleanup_scope.clone(), 5_000)
            .await
            .expect("neo cleanup delete"),
        mem.delete_episodes_older_than(cleanup_scope.clone(), 5_000)
            .await
            .expect("mem cleanup delete"),
        "cleanup delete parity"
    );
    assert_eq!(
        neo.subgraph(&project, "a", 1).await.expect("neo subgraph"),
        mem.subgraph(&project, "a", 1).await.expect("mem subgraph"),
        "cleanup removes old episode relationships"
    );

    // delete_relationship and delete_entity: same project scope, no dangling
    // relationship after an entity delete.
    neo.delete_relationship(&project, "r5")
        .await
        .expect("neo delete rel");
    mem.delete_relationship(&project, "r5")
        .await
        .expect("mem delete rel");
    assert_eq!(
        neo.subgraph(&project, "d", 1).await.expect("neo subgraph"),
        mem.subgraph(&project, "d", 1).await.expect("mem subgraph"),
        "delete_relationship parity"
    );

    neo.delete_entity(&project, "d")
        .await
        .expect("neo delete entity");
    mem.delete_entity(&project, "d")
        .await
        .expect("mem delete entity");
    assert_eq!(
        neo.get_entity(&project, "d")
            .await
            .expect("neo get deleted"),
        mem.get_entity(&project, "d")
            .await
            .expect("mem get deleted"),
        "delete_entity get parity"
    );
    assert_eq!(
        neo.subgraph(&project, "b", 1).await.expect("neo subgraph"),
        mem.subgraph(&project, "b", 1).await.expect("mem subgraph"),
        "delete_entity removes touching relationships"
    );

    // Decoy project sees only its own node (isolation), independent of `project`.
    let leak = neo
        .get_entity(&project, "a")
        .await
        .expect("neo get a")
        .unwrap();
    assert_eq!(leak.name, "Alpha", "project scoping: no cross-project leak");

    wipe(&graph, &project).await;
    wipe(&graph, &other).await;
}
