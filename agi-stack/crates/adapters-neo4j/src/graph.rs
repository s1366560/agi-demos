//! Neo4j [`GraphStore`]: the production server tier, talking Bolt to the same
//! graph the Python backend uses.
//!
//! Design for **cross-tier parity** with `InMemoryGraphStore` and
//! `SqliteGraphStore`:
//! - Entities are `(:Entity {uuid, project_id, ...})` nodes; MERGE is keyed on
//!   `(uuid, project_id)` so the same uuid in a different project is a distinct
//!   node — mirroring the in-memory `(project_id, uuid)` map key and the Python
//!   per-project scoping.
//! - Relationships use their `relation_type` as the Neo4j relationship type
//!   (validated to `^[A-Za-z_][A-Za-z0-9_]*$` to keep the type name injection-safe
//!   since it is interpolated), carrying `{uuid, fact, score, project_id,
//!   created_at_ms}`. `upsert_relationship` uses `MATCH ... MATCH ... MERGE`, so an
//!   edge is only created when **both endpoints already exist in the project**.
//!   Combined with the read-time both-endpoints filter the other tiers apply, this
//!   yields identical structural reads for well-formed seed data (entities before
//!   edges, same project).
//! - `subgraph` fetches the project slice over Bolt then runs the **same**
//!   depth-bounded BFS as the other tiers ([`bfs_subgraph`], duplicated locally to
//!   avoid a cross-adapter dependency — the device adapter does the same).
//! - `neighbors` / `search_entities` order by `uuid` and honour `limit`, matching
//!   the other tiers' stable ordering.

use std::collections::{HashMap, HashSet, VecDeque};

use async_trait::async_trait;
use neo4rs::{query, Graph, Node};

use agistack_core::model::{GraphEntity, Relationship, Subgraph};
use agistack_core::ports::{CoreError, CoreResult, GraphStore};

/// Production knowledge-graph adapter over a Bolt-connected [`neo4rs::Graph`].
///
/// Clone-cheap: `neo4rs::Graph` is an `Arc`-backed connection pool, so wrap it in
/// the server's DI container and share freely.
pub struct Neo4jGraphStore {
    graph: Graph,
}

impl Neo4jGraphStore {
    /// Wrap an already-connected Bolt graph (see [`crate::connect`]).
    pub fn new(graph: Graph) -> Self {
        Self { graph }
    }

    /// All entities in the project.
    async fn load_entities(&self, project_id: &str) -> CoreResult<Vec<GraphEntity>> {
        let mut stream = self
            .graph
            .execute(
                query("MATCH (e:Entity {project_id: $pid}) RETURN e ORDER BY e.uuid")
                    .param("pid", project_id),
            )
            .await
            .map_err(gerr)?;
        let mut out = Vec::new();
        while let Some(row) = stream.next().await.map_err(gerr)? {
            let node: Node = row.get("e").map_err(gerr)?;
            out.push(node_to_entity(&node)?);
        }
        Ok(out)
    }

    /// All relationships whose **both** endpoints are entities in the project.
    async fn load_relationships(&self, project_id: &str) -> CoreResult<Vec<Relationship>> {
        let mut stream = self
            .graph
            .execute(
                query(
                    "MATCH (a:Entity {project_id: $pid})-[r]->(b:Entity {project_id: $pid}) \
                     WHERE r.project_id = $pid \
                     RETURN a.uuid AS src, b.uuid AS tgt, type(r) AS rt, r.uuid AS uuid, \
                            r.fact AS fact, r.score AS score, r.created_at_ms AS cams",
                )
                .param("pid", project_id),
            )
            .await
            .map_err(gerr)?;
        let mut out = Vec::new();
        while let Some(row) = stream.next().await.map_err(gerr)? {
            out.push(Relationship {
                uuid: row.get("uuid").map_err(gerr)?,
                source_uuid: row.get("src").map_err(gerr)?,
                target_uuid: row.get("tgt").map_err(gerr)?,
                relation_type: row.get("rt").map_err(gerr)?,
                fact: row.get("fact").ok().unwrap_or_default(),
                score: row.get::<f64>("score").map(|s| s as f32).unwrap_or(0.0),
                project_id: project_id.to_string(),
                created_at_ms: row.get("cams").ok().unwrap_or(0),
            });
        }
        Ok(out)
    }
}

/// Map any `neo4rs`/deserialize error to a port error.
fn gerr<E: std::fmt::Display>(e: E) -> CoreError {
    CoreError::Graph(e.to_string())
}

/// Reconstruct a [`GraphEntity`] from an `:Entity` node's properties. Absent
/// optional properties (Neo4j drops null properties on write) decode to `None` /
/// defaults.
fn node_to_entity(node: &Node) -> CoreResult<GraphEntity> {
    Ok(GraphEntity {
        uuid: node.get("uuid").map_err(gerr)?,
        name: node.get("name").map_err(gerr)?,
        entity_type: node.get("entity_type").map_err(gerr)?,
        summary: node.get("summary").ok().unwrap_or_default(),
        project_id: node.get("project_id").map_err(gerr)?,
        tenant_id: node.get::<Option<String>>("tenant_id").ok().flatten(),
        created_at_ms: node.get("created_at_ms").ok().unwrap_or(0),
        name_embedding: node
            .get::<Option<Vec<f64>>>("name_embedding")
            .ok()
            .flatten()
            .map(|v| v.into_iter().map(|x| x as f32).collect()),
    })
}

/// Validate a relationship type so it can be safely interpolated into Cypher as a
/// backtick-quoted type name. Neo4j does not allow parameterising relationship
/// types, so the type must be a plain identifier.
fn sanitize_rel_type(rt: &str) -> CoreResult<&str> {
    let ok = !rt.is_empty()
        && rt
            .chars()
            .next()
            .map(|c| c.is_ascii_alphabetic() || c == '_')
            .unwrap_or(false)
        && rt.chars().all(|c| c.is_ascii_alphanumeric() || c == '_');
    if ok {
        Ok(rt)
    } else {
        Err(CoreError::Graph(format!("invalid relation_type: {rt:?}")))
    }
}

#[async_trait]
impl GraphStore for Neo4jGraphStore {
    async fn upsert_entity(&self, entity: GraphEntity) -> CoreResult<()> {
        self.graph
            .run(
                query(
                    "MERGE (e:Entity {uuid: $uuid, project_id: $pid}) \
                     SET e.name = $name, e.entity_type = $etype, e.summary = $summary, \
                         e.tenant_id = $tenant, e.created_at_ms = $cams, \
                         e.name_embedding = $emb",
                )
                .param("uuid", entity.uuid)
                .param("pid", entity.project_id)
                .param("name", entity.name)
                .param("etype", entity.entity_type)
                .param("summary", entity.summary)
                .param("tenant", entity.tenant_id)
                .param("cams", entity.created_at_ms)
                .param("emb", entity.name_embedding),
            )
            .await
            .map_err(gerr)
    }

    async fn upsert_relationship(&self, rel: Relationship) -> CoreResult<()> {
        let rt = sanitize_rel_type(&rel.relation_type)?;
        // Relationship type cannot be parameterised in Cypher; interpolate the
        // validated identifier, backtick-quoted.
        let cypher = format!(
            "MATCH (a:Entity {{uuid: $src, project_id: $pid}}) \
             MATCH (b:Entity {{uuid: $tgt, project_id: $pid}}) \
             MERGE (a)-[r:`{rt}` {{uuid: $uuid}}]->(b) \
             SET r.fact = $fact, r.score = $score, r.project_id = $pid, \
                 r.created_at_ms = $cams"
        );
        self.graph
            .run(
                query(&cypher)
                    .param("src", rel.source_uuid)
                    .param("tgt", rel.target_uuid)
                    .param("pid", rel.project_id)
                    .param("uuid", rel.uuid)
                    .param("fact", rel.fact)
                    .param("score", rel.score)
                    .param("cams", rel.created_at_ms),
            )
            .await
            .map_err(gerr)
    }

    async fn get_entity(&self, project_id: &str, uuid: &str) -> CoreResult<Option<GraphEntity>> {
        let mut stream = self
            .graph
            .execute(
                query("MATCH (e:Entity {uuid: $uuid, project_id: $pid}) RETURN e LIMIT 1")
                    .param("uuid", uuid)
                    .param("pid", project_id),
            )
            .await
            .map_err(gerr)?;
        match stream.next().await.map_err(gerr)? {
            Some(row) => {
                let node: Node = row.get("e").map_err(gerr)?;
                Ok(Some(node_to_entity(&node)?))
            }
            None => Ok(None),
        }
    }

    async fn neighbors(&self, project_id: &str, uuid: &str) -> CoreResult<Vec<GraphEntity>> {
        let mut stream = self
            .graph
            .execute(
                query(
                    "MATCH (a:Entity {uuid: $uuid, project_id: $pid})-[r]->(b:Entity {project_id: $pid}) \
                     WHERE r.project_id = $pid \
                     RETURN DISTINCT b ORDER BY b.uuid",
                )
                .param("uuid", uuid)
                .param("pid", project_id),
            )
            .await
            .map_err(gerr)?;
        let mut out = Vec::new();
        while let Some(row) = stream.next().await.map_err(gerr)? {
            let node: Node = row.get("b").map_err(gerr)?;
            out.push(node_to_entity(&node)?);
        }
        Ok(out)
    }

    async fn subgraph(
        &self,
        project_id: &str,
        uuid: &str,
        max_depth: usize,
    ) -> CoreResult<Subgraph> {
        // Fetch the project slice, then run the exact same BFS as the other tiers
        // so structural results are identical across in-memory / SQLite / Neo4j.
        let ents = self.load_entities(project_id).await?;
        let rels = self.load_relationships(project_id).await?;
        Ok(bfs_subgraph(&ents, &rels, uuid, max_depth))
    }

    async fn search_entities(
        &self,
        project_id: &str,
        query_text: &str,
        limit: usize,
    ) -> CoreResult<Vec<GraphEntity>> {
        let mut stream = self
            .graph
            .execute(
                query(
                    "MATCH (e:Entity {project_id: $pid}) \
                     WHERE toLower(e.name) CONTAINS toLower($q) \
                        OR toLower(e.summary) CONTAINS toLower($q) \
                     RETURN e ORDER BY e.uuid LIMIT $limit",
                )
                .param("pid", project_id)
                .param("q", query_text)
                .param("limit", limit as i64),
            )
            .await
            .map_err(gerr)?;
        let mut out = Vec::new();
        while let Some(row) = stream.next().await.map_err(gerr)? {
            let node: Node = row.get("e").map_err(gerr)?;
            out.push(node_to_entity(&node)?);
        }
        Ok(out)
    }
}

/// Depth-bounded BFS over a project slice using `petgraph`-free plain queues —
/// byte-identical shape to the in-memory and device adapters' traversal so all
/// three tiers return the same subgraph for the same data. The seed is depth 0;
/// edges are followed outgoing; a relationship is included only when *both*
/// endpoints were reached. Entities and relationships are sorted by `uuid`.
///
/// (Duplicated locally rather than shared, so this server crate never depends on
/// the mem/device adapters — the same rationale the device adapter documents.)
fn bfs_subgraph(
    ents: &[GraphEntity],
    rels: &[Relationship],
    seed: &str,
    max_depth: usize,
) -> Subgraph {
    // Adjacency by source uuid -> ordered target uuids.
    let present: HashSet<&str> = ents.iter().map(|e| e.uuid.as_str()).collect();
    let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();
    for r in rels {
        if present.contains(r.source_uuid.as_str()) && present.contains(r.target_uuid.as_str()) {
            adj.entry(r.source_uuid.as_str())
                .or_default()
                .push(r.target_uuid.as_str());
        }
    }

    let mut reached: HashSet<String> = HashSet::new();
    if present.contains(seed) {
        let mut visited: HashSet<&str> = HashSet::new();
        let mut queue: VecDeque<(&str, usize)> = VecDeque::new();
        visited.insert(seed);
        queue.push_back((seed, 0));
        while let Some((node, depth)) = queue.pop_front() {
            reached.insert(node.to_string());
            if depth < max_depth {
                if let Some(neighbors) = adj.get(node) {
                    for &nbr in neighbors {
                        if visited.insert(nbr) {
                            queue.push_back((nbr, depth + 1));
                        }
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
    use super::sanitize_rel_type;

    #[test]
    fn rel_type_validation_accepts_identifiers_and_rejects_injection() {
        assert!(sanitize_rel_type("MENTIONS").is_ok());
        assert!(sanitize_rel_type("RELATES_TO").is_ok());
        assert!(sanitize_rel_type("_private").is_ok());
        // rejects anything that could break out of the backtick-quoted type
        assert!(sanitize_rel_type("").is_err());
        assert!(sanitize_rel_type("1BAD").is_err());
        assert!(sanitize_rel_type("has space").is_err());
        assert!(sanitize_rel_type("ev`il").is_err());
        assert!(sanitize_rel_type("drop]->()//").is_err());
    }
}
