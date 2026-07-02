//! SQLite [`GraphStore`] — the durable on-device knowledge graph
//! (`10-production-migration.md` §6.3, decision 4: "SQLite 关系表 + petgraph 遍历").
//!
//! Entities and relationships live in two relational tables; `k`-hop traversal
//! loads the project slice and walks it with [`petgraph`] (identical BFS shape to
//! [`agistack_adapters_mem::InMemoryGraphStore`], so both tiers return the same
//! subgraph for the same data). This is the local-first analogue of the server's
//! Neo4j (`neo4rs`, future F8): same [`GraphStore`] port, same ranking math in
//! [`agistack_core::graph`], durable across restarts — which is what makes on-device
//! offline graph queries and crash recovery real.
//!
//! `rusqlite` is native-only (bundled C SQLite), so this adapter never targets
//! wasm — the browser tier uses the in-memory store instead. `petgraph` itself is
//! pure Rust; the traversal helper mirrors the mem adapter's, kept local so this
//! crate has no runtime dependency on `adapters-mem`.

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::Mutex;

use async_trait::async_trait;
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::Direction;
use rusqlite::{params, Connection};

use agistack_core::model::{GraphEntity, Relationship, Subgraph};
use agistack_core::ports::{CoreError, CoreResult, GraphStore};

pub struct SqliteGraphStore {
    conn: Mutex<Connection>,
}

impl SqliteGraphStore {
    pub fn open(path: &str) -> CoreResult<Self> {
        Self::init(Connection::open(path).map_err(to_graph)?)
    }

    pub fn in_memory() -> CoreResult<Self> {
        Self::init(Connection::open_in_memory().map_err(to_graph)?)
    }

    fn init(conn: Connection) -> CoreResult<Self> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS graph_entities (
                project_id   TEXT NOT NULL,
                uuid         TEXT NOT NULL,
                name         TEXT NOT NULL,
                entity_type  TEXT NOT NULL,
                summary      TEXT NOT NULL,
                tenant_id    TEXT,
                created_at_ms INTEGER NOT NULL,
                name_embedding TEXT,
                PRIMARY KEY (project_id, uuid)
            );
            CREATE TABLE IF NOT EXISTS graph_relationships (
                uuid          TEXT PRIMARY KEY,
                project_id    TEXT NOT NULL,
                source_uuid   TEXT NOT NULL,
                target_uuid   TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                fact          TEXT NOT NULL,
                score         REAL NOT NULL,
                created_at_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rel_project ON graph_relationships (project_id);
            CREATE INDEX IF NOT EXISTS idx_rel_source ON graph_relationships (project_id, source_uuid);",
        )
        .map_err(to_graph)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    /// Load the project-scoped entities and the relationships whose *both*
    /// endpoints exist in that project (so traversal never dangles across a
    /// project boundary), matching the in-memory adapter's `project_slice`.
    fn project_slice(&self, project_id: &str) -> CoreResult<(Vec<GraphEntity>, Vec<Relationship>)> {
        let conn = self.conn.lock().map_err(to_graph)?;
        let ents = load_entities(&conn, project_id)?;
        let present: HashSet<String> = ents.iter().map(|e| e.uuid.clone()).collect();
        let mut rels = load_relationships(&conn, project_id)?;
        rels.retain(|r| present.contains(&r.source_uuid) && present.contains(&r.target_uuid));
        Ok((ents, rels))
    }
}

fn to_graph<E: std::fmt::Display>(e: E) -> CoreError {
    CoreError::Graph(e.to_string())
}

fn row_to_entity(r: &rusqlite::Row) -> rusqlite::Result<GraphEntity> {
    let emb_json: Option<String> = r.get("name_embedding")?;
    let name_embedding = emb_json
        .as_deref()
        .and_then(|s| serde_json::from_str::<Vec<f32>>(s).ok());
    Ok(GraphEntity {
        project_id: r.get("project_id")?,
        uuid: r.get("uuid")?,
        name: r.get("name")?,
        entity_type: r.get("entity_type")?,
        summary: r.get("summary")?,
        tenant_id: r.get("tenant_id")?,
        created_at_ms: r.get("created_at_ms")?,
        name_embedding,
    })
}

/// Load all entities for a project, ordered by uuid for deterministic traversal.
fn load_entities(conn: &Connection, project_id: &str) -> CoreResult<Vec<GraphEntity>> {
    let mut stmt = conn
        .prepare("SELECT * FROM graph_entities WHERE project_id = ?1 ORDER BY uuid")
        .map_err(to_graph)?;
    let rows = stmt
        .query_map(params![project_id], row_to_entity)
        .map_err(to_graph)?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(to_graph)?);
    }
    Ok(out)
}

fn load_relationships(conn: &Connection, project_id: &str) -> CoreResult<Vec<Relationship>> {
    let mut stmt = conn
        .prepare("SELECT * FROM graph_relationships WHERE project_id = ?1 ORDER BY uuid")
        .map_err(to_graph)?;
    let rows = stmt
        .query_map(params![project_id], |r| {
            Ok(Relationship {
                uuid: r.get("uuid")?,
                source_uuid: r.get("source_uuid")?,
                target_uuid: r.get("target_uuid")?,
                relation_type: r.get("relation_type")?,
                fact: r.get("fact")?,
                score: r.get("score")?,
                project_id: r.get("project_id")?,
                created_at_ms: r.get("created_at_ms")?,
            })
        })
        .map_err(to_graph)?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(to_graph)?);
    }
    Ok(out)
}

#[async_trait]
impl GraphStore for SqliteGraphStore {
    async fn upsert_entity(&self, entity: GraphEntity) -> CoreResult<()> {
        let emb = match &entity.name_embedding {
            Some(v) => Some(serde_json::to_string(v).map_err(to_graph)?),
            None => None,
        };
        let conn = self.conn.lock().map_err(to_graph)?;
        conn.execute(
            "INSERT OR REPLACE INTO graph_entities
             (project_id, uuid, name, entity_type, summary, tenant_id, created_at_ms, name_embedding)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                entity.project_id,
                entity.uuid,
                entity.name,
                entity.entity_type,
                entity.summary,
                entity.tenant_id,
                entity.created_at_ms,
                emb,
            ],
        )
        .map_err(to_graph)?;
        Ok(())
    }

    async fn upsert_relationship(&self, rel: Relationship) -> CoreResult<()> {
        let conn = self.conn.lock().map_err(to_graph)?;
        conn.execute(
            "INSERT OR REPLACE INTO graph_relationships
             (uuid, project_id, source_uuid, target_uuid, relation_type, fact, score, created_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                rel.uuid,
                rel.project_id,
                rel.source_uuid,
                rel.target_uuid,
                rel.relation_type,
                rel.fact,
                rel.score,
                rel.created_at_ms,
            ],
        )
        .map_err(to_graph)?;
        Ok(())
    }

    async fn get_entity(&self, project_id: &str, uuid: &str) -> CoreResult<Option<GraphEntity>> {
        let conn = self.conn.lock().map_err(to_graph)?;
        let mut stmt = conn
            .prepare("SELECT * FROM graph_entities WHERE project_id = ?1 AND uuid = ?2")
            .map_err(to_graph)?;
        let mut rows = stmt
            .query_map(params![project_id, uuid], row_to_entity)
            .map_err(to_graph)?;
        match rows.next() {
            Some(row) => Ok(Some(row.map_err(to_graph)?)),
            None => Ok(None),
        }
    }

    async fn neighbors(&self, project_id: &str, uuid: &str) -> CoreResult<Vec<GraphEntity>> {
        let (ents, rels) = self.project_slice(project_id)?;
        let by_uuid: HashMap<&str, &GraphEntity> =
            ents.iter().map(|e| (e.uuid.as_str(), e)).collect();
        let mut out: Vec<GraphEntity> = rels
            .iter()
            .filter(|r| r.source_uuid == uuid)
            .filter_map(|r| by_uuid.get(r.target_uuid.as_str()).map(|e| (*e).clone()))
            .collect();
        out.sort_by(|a, b| a.uuid.cmp(&b.uuid));
        out.dedup_by(|a, b| a.uuid == b.uuid);
        Ok(out)
    }

    async fn subgraph(
        &self,
        project_id: &str,
        uuid: &str,
        max_depth: usize,
    ) -> CoreResult<Subgraph> {
        let (ents, rels) = self.project_slice(project_id)?;
        Ok(bfs_subgraph(&ents, &rels, uuid, max_depth))
    }

    async fn search_entities(
        &self,
        project_id: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<GraphEntity>> {
        let conn = self.conn.lock().map_err(to_graph)?;
        // Escape LIKE wildcards in the user query, then wrap for substring match.
        let escaped = query
            .to_lowercase()
            .replace('\\', "\\\\")
            .replace('%', "\\%")
            .replace('_', "\\_");
        let pattern = format!("%{escaped}%");
        // Re-run the LIKE-filtered load, then truncate to the limit.
        let mut hits = load_entities_like(&conn, project_id, &pattern)?;
        hits.truncate(limit);
        Ok(hits)
    }
}

/// LIKE-filtered entity load with an explicit ESCAPE clause (so user `%`/`_` are
/// literal). Kept separate from [`load_entities`] to carry the ESCAPE.
fn load_entities_like(
    conn: &Connection,
    project_id: &str,
    pattern: &str,
) -> CoreResult<Vec<GraphEntity>> {
    let mut stmt = conn
        .prepare(
            "SELECT * FROM graph_entities
             WHERE project_id = ?1
               AND (LOWER(name) LIKE ?2 ESCAPE '\\' OR LOWER(summary) LIKE ?2 ESCAPE '\\')
             ORDER BY uuid",
        )
        .map_err(to_graph)?;
    let rows = stmt
        .query_map(params![project_id, pattern], row_to_entity)
        .map_err(to_graph)?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(to_graph)?);
    }
    Ok(out)
}

/// Depth-bounded BFS over a project slice using `petgraph` — mirrors the in-memory
/// adapter so the durable tier returns identical subgraphs. Seed is depth 0; edges
/// followed outgoing; a relationship is kept only when both endpoints were reached.
fn bfs_subgraph(
    ents: &[GraphEntity],
    rels: &[Relationship],
    seed: &str,
    max_depth: usize,
) -> Subgraph {
    let mut g: DiGraph<String, ()> = DiGraph::new();
    let mut idx: HashMap<&str, NodeIndex> = HashMap::new();
    for e in ents {
        let n = g.add_node(e.uuid.clone());
        idx.insert(e.uuid.as_str(), n);
    }
    for r in rels {
        if let (Some(&s), Some(&t)) = (
            idx.get(r.source_uuid.as_str()),
            idx.get(r.target_uuid.as_str()),
        ) {
            g.add_edge(s, t, ());
        }
    }

    let mut reached: HashSet<String> = HashSet::new();
    if let Some(&start) = idx.get(seed) {
        let mut visited: HashSet<NodeIndex> = HashSet::new();
        let mut queue: VecDeque<(NodeIndex, usize)> = VecDeque::new();
        visited.insert(start);
        queue.push_back((start, 0));
        while let Some((node, depth)) = queue.pop_front() {
            reached.insert(g[node].clone());
            if depth < max_depth {
                for nbr in g.neighbors_directed(node, Direction::Outgoing) {
                    if visited.insert(nbr) {
                        queue.push_back((nbr, depth + 1));
                    }
                }
            }
        }
    }

    let by_uuid: HashMap<&str, &GraphEntity> = ents.iter().map(|e| (e.uuid.as_str(), e)).collect();
    let mut entities: Vec<GraphEntity> = reached
        .iter()
        .filter_map(|u| by_uuid.get(u.as_str()).map(|e| (*e).clone()))
        .collect();
    entities.sort_by(|a, b| a.uuid.cmp(&b.uuid));

    let mut relationships: Vec<Relationship> = rels
        .iter()
        .filter(|r| reached.contains(&r.source_uuid) && reached.contains(&r.target_uuid))
        .cloned()
        .collect();
    relationships.sort_by(|a, b| a.uuid.cmp(&b.uuid));

    Subgraph {
        entities,
        relationships,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    fn ent(uuid: &str, name: &str, summary: &str, project: &str) -> GraphEntity {
        GraphEntity {
            uuid: uuid.into(),
            name: name.into(),
            entity_type: "Concept".into(),
            summary: summary.into(),
            project_id: project.into(),
            tenant_id: None,
            created_at_ms: 7,
            name_embedding: Some(vec![0.1, 0.2]),
        }
    }

    fn rel(uuid: &str, src: &str, dst: &str, project: &str) -> Relationship {
        Relationship {
            uuid: uuid.into(),
            source_uuid: src.into(),
            target_uuid: dst.into(),
            relation_type: "MENTIONS".into(),
            fact: "f".into(),
            score: 0.9,
            project_id: project.into(),
            created_at_ms: 7,
        }
    }

    #[test]
    fn upsert_get_and_embedding_roundtrip() {
        let s = SqliteGraphStore::in_memory().unwrap();
        block_on(s.upsert_entity(ent("e1", "Alpha", "first", "p1"))).unwrap();
        let got = block_on(s.get_entity("p1", "e1")).unwrap().unwrap();
        assert_eq!(got.name, "Alpha");
        assert_eq!(got.name_embedding, Some(vec![0.1, 0.2]));
        // scoped: same uuid other project absent
        assert!(block_on(s.get_entity("p2", "e1")).unwrap().is_none());
    }

    #[test]
    fn durable_across_reopen() {
        let dir = std::env::temp_dir();
        let path = dir.join(format!("agistack_graph_{}.db", std::process::id()));
        let p = path.to_str().unwrap();
        {
            let s = SqliteGraphStore::open(p).unwrap();
            block_on(s.upsert_entity(ent("e1", "Persisted", "", "p1"))).unwrap();
            block_on(s.upsert_relationship(rel("r1", "e1", "e1", "p1"))).unwrap();
        }
        {
            let s = SqliteGraphStore::open(p).unwrap();
            let got = block_on(s.get_entity("p1", "e1")).unwrap().unwrap();
            assert_eq!(got.name, "Persisted");
        }
        let _ = std::fs::remove_file(p);
    }

    #[test]
    fn neighbors_outgoing_only() {
        let s = SqliteGraphStore::in_memory().unwrap();
        for e in ["e1", "e2", "e3"] {
            block_on(s.upsert_entity(ent(e, e, "", "p1"))).unwrap();
        }
        block_on(s.upsert_relationship(rel("r1", "e1", "e2", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r2", "e1", "e3", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r3", "e2", "e1", "p1"))).unwrap();
        let nbrs = block_on(s.neighbors("p1", "e1")).unwrap();
        let ids: Vec<&str> = nbrs.iter().map(|e| e.uuid.as_str()).collect();
        assert_eq!(ids, vec!["e2", "e3"]);
    }

    #[test]
    fn subgraph_depth_budget_matches_mem_adapter() {
        let s = SqliteGraphStore::in_memory().unwrap();
        for e in ["e1", "e2", "e3", "e4"] {
            block_on(s.upsert_entity(ent(e, e, "", "p1"))).unwrap();
        }
        block_on(s.upsert_relationship(rel("r1", "e1", "e2", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r2", "e2", "e3", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r3", "e3", "e4", "p1"))).unwrap();

        let g0 = block_on(s.subgraph("p1", "e1", 0)).unwrap();
        assert_eq!(g0.entities.len(), 1);
        assert!(g0.relationships.is_empty());

        let g2 = block_on(s.subgraph("p1", "e1", 2)).unwrap();
        let ids: Vec<&str> = g2.entities.iter().map(|e| e.uuid.as_str()).collect();
        assert_eq!(ids, vec!["e1", "e2", "e3"]);
        let redges: Vec<&str> = g2.relationships.iter().map(|r| r.uuid.as_str()).collect();
        assert_eq!(redges, vec!["r1", "r2"]);
    }

    #[test]
    fn search_scoped_limited_and_wildcard_safe() {
        let s = SqliteGraphStore::in_memory().unwrap();
        block_on(s.upsert_entity(ent("e1", "Quantum Physics", "matter", "p1"))).unwrap();
        block_on(s.upsert_entity(ent("e2", "Cooking", "quantum flavor", "p1"))).unwrap();
        block_on(s.upsert_entity(ent("e3", "Quantum", "", "p2"))).unwrap();
        let hits = block_on(s.search_entities("p1", "quantum", 10)).unwrap();
        let ids: Vec<&str> = hits.iter().map(|e| e.uuid.as_str()).collect();
        assert_eq!(ids, vec!["e1", "e2"]); // p2 excluded, name+summary matched
        let limited = block_on(s.search_entities("p1", "quantum", 1)).unwrap();
        assert_eq!(limited.len(), 1);
        // a literal '%' must not act as a wildcard
        block_on(s.upsert_entity(ent("e4", "100% pure", "", "p1"))).unwrap();
        let pct = block_on(s.search_entities("p1", "100%", 10)).unwrap();
        assert_eq!(pct.len(), 1);
        assert_eq!(pct[0].uuid, "e4");
    }
}
