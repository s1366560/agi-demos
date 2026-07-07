//! In-memory [`GraphStore`]: a project-scoped knowledge graph over `HashMap`s,
//! traversed with [`petgraph`].
//!
//! This is the browser/test tier of the graph port (`10-production-migration.md`
//! §6.3, decision 4): on the server the same port is Neo4j (`neo4rs`, future F8),
//! on device SQLite relational tables (`agistack-adapters-device`), here plain
//! maps. All three share the one [`GraphStore`] contract and the same pure ranking
//! math in [`agistack_core::graph`], so query *scores* match across tiers — only
//! the storage/traversal substrate differs.
//!
//! Traversal uses `petgraph`: [`subgraph`](InMemoryGraphStore::subgraph) builds a
//! project-scoped `DiGraph` on demand and runs a depth-bounded BFS. `petgraph` is
//! pure Rust with no I/O, so this whole adapter compiles to `wasm32` unchanged —
//! the same reason the core does.

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::Mutex;

use async_trait::async_trait;
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::Direction;

use agistack_core::model::{
    GraphEntity, GraphExport, GraphStats, GraphStatsScope, Relationship, Subgraph,
};
use agistack_core::ports::{CoreError, CoreResult, GraphStore};

/// Entities keyed by `(project_id, uuid)` and relationships keyed by `uuid`.
/// Keying entities by project keeps tenants isolated: no traversal or search ever
/// crosses a `project_id` boundary, mirroring the Python graph's per-project scope.
#[derive(Default)]
pub struct InMemoryGraphStore {
    entities: Mutex<HashMap<(String, String), GraphEntity>>,
    relationships: Mutex<HashMap<String, Relationship>>,
}

impl InMemoryGraphStore {
    pub fn new() -> Self {
        Self::default()
    }

    /// Snapshot the project-scoped entities and the relationships whose *both*
    /// endpoints exist in that project. Taken under lock, then released before any
    /// traversal so we never hold two locks at once.
    fn project_slice(&self, project_id: &str) -> CoreResult<(Vec<GraphEntity>, Vec<Relationship>)> {
        let entities = self.entities.lock().map_err(|_| poisoned())?;
        let rels = self.relationships.lock().map_err(|_| poisoned())?;
        let present: HashSet<&str> = entities
            .keys()
            .filter(|(p, _)| p == project_id)
            .map(|(_, u)| u.as_str())
            .collect();
        let ents: Vec<GraphEntity> = entities
            .iter()
            .filter(|((p, _), _)| p == project_id)
            .map(|(_, e)| e.clone())
            .collect();
        let rs: Vec<Relationship> = rels
            .values()
            .filter(|r| {
                r.project_id == project_id
                    && present.contains(r.source_uuid.as_str())
                    && present.contains(r.target_uuid.as_str())
            })
            .cloned()
            .collect();
        Ok((ents, rs))
    }

    fn scoped_slice(
        &self,
        scope: GraphStatsScope,
    ) -> CoreResult<(Vec<GraphEntity>, Vec<Relationship>)> {
        let project_filter = match scope {
            GraphStatsScope::All => None,
            GraphStatsScope::Projects(project_ids) => {
                Some(project_ids.into_iter().collect::<HashSet<_>>())
            }
        };
        if project_filter.as_ref().is_some_and(HashSet::is_empty) {
            return Ok((Vec::new(), Vec::new()));
        }

        let entities = self.entities.lock().map_err(|_| poisoned())?;
        let rels = self.relationships.lock().map_err(|_| poisoned())?;
        let ents: Vec<GraphEntity> = entities
            .iter()
            .filter(|((project_id, _), _)| {
                project_filter
                    .as_ref()
                    .is_none_or(|ids| ids.contains(project_id))
            })
            .map(|(_, entity)| entity.clone())
            .collect();
        let present: HashSet<(String, String)> = ents
            .iter()
            .map(|entity| (entity.project_id.clone(), entity.uuid.clone()))
            .collect();
        let rs: Vec<Relationship> = rels
            .values()
            .filter(|rel| {
                project_filter
                    .as_ref()
                    .is_none_or(|ids| ids.contains(&rel.project_id))
                    && present.contains(&(rel.project_id.clone(), rel.source_uuid.clone()))
                    && present.contains(&(rel.project_id.clone(), rel.target_uuid.clone()))
            })
            .cloned()
            .collect();
        Ok((ents, rs))
    }
}

fn poisoned() -> CoreError {
    CoreError::Graph("poisoned lock".into())
}

#[async_trait]
impl GraphStore for InMemoryGraphStore {
    async fn upsert_entity(&self, entity: GraphEntity) -> CoreResult<()> {
        let mut entities = self.entities.lock().map_err(|_| poisoned())?;
        entities.insert((entity.project_id.clone(), entity.uuid.clone()), entity);
        Ok(())
    }

    async fn upsert_relationship(&self, rel: Relationship) -> CoreResult<()> {
        let mut rels = self.relationships.lock().map_err(|_| poisoned())?;
        rels.insert(rel.uuid.clone(), rel);
        Ok(())
    }

    async fn delete_entity(&self, project_id: &str, uuid: &str) -> CoreResult<()> {
        let mut entities = self.entities.lock().map_err(|_| poisoned())?;
        entities.remove(&(project_id.to_string(), uuid.to_string()));
        drop(entities);

        let mut rels = self.relationships.lock().map_err(|_| poisoned())?;
        rels.retain(|_, rel| {
            rel.project_id != project_id || (rel.source_uuid != uuid && rel.target_uuid != uuid)
        });
        Ok(())
    }

    async fn delete_relationship(&self, project_id: &str, uuid: &str) -> CoreResult<()> {
        let mut rels = self.relationships.lock().map_err(|_| poisoned())?;
        if rels
            .get(uuid)
            .is_some_and(|rel| rel.project_id == project_id)
        {
            rels.remove(uuid);
        }
        Ok(())
    }

    async fn get_entity(&self, project_id: &str, uuid: &str) -> CoreResult<Option<GraphEntity>> {
        let entities = self.entities.lock().map_err(|_| poisoned())?;
        Ok(entities
            .get(&(project_id.to_string(), uuid.to_string()))
            .cloned())
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
        let entities = self.entities.lock().map_err(|_| poisoned())?;
        let needle = query.to_lowercase();
        let mut hits: Vec<GraphEntity> = entities
            .iter()
            .filter(|((p, _), _)| p == project_id)
            .map(|(_, e)| e)
            .filter(|e| {
                e.name.to_lowercase().contains(&needle)
                    || e.summary.to_lowercase().contains(&needle)
            })
            .cloned()
            .collect();
        hits.sort_by(|a, b| a.uuid.cmp(&b.uuid));
        hits.truncate(limit);
        Ok(hits)
    }

    async fn stats(&self, scope: GraphStatsScope) -> CoreResult<GraphStats> {
        let (entities, relationships) = self.scoped_slice(scope)?;
        let mut stats = GraphStats::default();
        for entity in entities {
            stats.add_entity_type(&entity.entity_type, 1);
        }
        stats.add_relationships(relationships.len());
        Ok(stats)
    }

    async fn export(&self, scope: GraphStatsScope) -> CoreResult<GraphExport> {
        let (mut entities, mut relationships) = self.scoped_slice(scope)?;
        entities.sort_by(|a, b| {
            a.project_id
                .cmp(&b.project_id)
                .then_with(|| a.uuid.cmp(&b.uuid))
        });
        relationships.sort_by(|a, b| {
            a.project_id
                .cmp(&b.project_id)
                .then_with(|| a.uuid.cmp(&b.uuid))
        });
        Ok(GraphExport {
            entities,
            relationships,
        })
    }

    async fn count_episodes_older_than(
        &self,
        scope: GraphStatsScope,
        cutoff_ms: i64,
    ) -> CoreResult<usize> {
        let (entities, _) = self.scoped_slice(scope)?;
        Ok(entities
            .iter()
            .filter(|entity| entity.entity_type == "Episodic" && entity.created_at_ms < cutoff_ms)
            .count())
    }

    async fn delete_episodes_older_than(
        &self,
        scope: GraphStatsScope,
        cutoff_ms: i64,
    ) -> CoreResult<usize> {
        let (entities, _) = self.scoped_slice(scope)?;
        let expired: Vec<(String, String)> = entities
            .into_iter()
            .filter(|entity| entity.entity_type == "Episodic" && entity.created_at_ms < cutoff_ms)
            .map(|entity| (entity.project_id, entity.uuid))
            .collect();
        let deleted = expired.len();
        for (project_id, uuid) in expired {
            self.delete_entity(&project_id, &uuid).await?;
        }
        Ok(deleted)
    }
}

/// Depth-bounded BFS over a project slice using `petgraph`. Shared shape with the
/// device adapter's traversal so both tiers return identical subgraphs for the
/// same data. The seed is depth 0; edges are followed outgoing; a relationship is
/// included only when *both* endpoints were reached (so it never dangles).
pub(crate) fn bfs_subgraph(
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
            created_at_ms: 0,
            name_embedding: None,
        }
    }

    fn rel(uuid: &str, src: &str, dst: &str, project: &str) -> Relationship {
        Relationship {
            uuid: uuid.into(),
            source_uuid: src.into(),
            target_uuid: dst.into(),
            relation_type: "MENTIONS".into(),
            fact: "".into(),
            score: 1.0,
            project_id: project.into(),
            created_at_ms: 0,
        }
    }

    #[test]
    fn upsert_and_get_roundtrip_and_replace() {
        let s = InMemoryGraphStore::new();
        block_on(s.upsert_entity(ent("e1", "Alpha", "first", "p1"))).unwrap();
        let got = block_on(s.get_entity("p1", "e1")).unwrap().unwrap();
        assert_eq!(got.name, "Alpha");
        // upsert replaces by (project, uuid)
        block_on(s.upsert_entity(ent("e1", "Alpha2", "changed", "p1"))).unwrap();
        let got = block_on(s.get_entity("p1", "e1")).unwrap().unwrap();
        assert_eq!(got.name, "Alpha2");
        assert_eq!(got.summary, "changed");
    }

    #[test]
    fn get_entity_is_project_scoped() {
        let s = InMemoryGraphStore::new();
        block_on(s.upsert_entity(ent("e1", "Alpha", "", "p1"))).unwrap();
        // same uuid, different project must not leak
        assert!(block_on(s.get_entity("p2", "e1")).unwrap().is_none());
    }

    #[test]
    fn neighbors_are_outgoing_and_scoped() {
        let s = InMemoryGraphStore::new();
        for e in ["e1", "e2", "e3"] {
            block_on(s.upsert_entity(ent(e, e, "", "p1"))).unwrap();
        }
        block_on(s.upsert_relationship(rel("r1", "e1", "e2", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r2", "e1", "e3", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r3", "e2", "e1", "p1"))).unwrap();
        let nbrs = block_on(s.neighbors("p1", "e1")).unwrap();
        let ids: Vec<&str> = nbrs.iter().map(|e| e.uuid.as_str()).collect();
        assert_eq!(ids, vec!["e2", "e3"]); // outgoing only, not e2->e1
    }

    #[test]
    fn neighbors_skip_edges_to_other_projects() {
        let s = InMemoryGraphStore::new();
        block_on(s.upsert_entity(ent("e1", "e1", "", "p1"))).unwrap();
        block_on(s.upsert_entity(ent("e2", "e2", "", "p2"))).unwrap();
        // edge references a target that lives in another project -> excluded
        block_on(s.upsert_relationship(rel("r1", "e1", "e2", "p1"))).unwrap();
        assert!(block_on(s.neighbors("p1", "e1")).unwrap().is_empty());
    }

    #[test]
    fn subgraph_respects_depth_budget() {
        let s = InMemoryGraphStore::new();
        // chain e1 -> e2 -> e3 -> e4
        for e in ["e1", "e2", "e3", "e4"] {
            block_on(s.upsert_entity(ent(e, e, "", "p1"))).unwrap();
        }
        block_on(s.upsert_relationship(rel("r1", "e1", "e2", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r2", "e2", "e3", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r3", "e3", "e4", "p1"))).unwrap();

        // depth 0 = seed only, no edges
        let g0 = block_on(s.subgraph("p1", "e1", 0)).unwrap();
        assert_eq!(g0.entities.len(), 1);
        assert!(g0.relationships.is_empty());

        // depth 2 = e1, e2, e3 and the two edges among them (not e3->e4)
        let g2 = block_on(s.subgraph("p1", "e1", 2)).unwrap();
        let ids: Vec<&str> = g2.entities.iter().map(|e| e.uuid.as_str()).collect();
        assert_eq!(ids, vec!["e1", "e2", "e3"]);
        let redges: Vec<&str> = g2.relationships.iter().map(|r| r.uuid.as_str()).collect();
        assert_eq!(redges, vec!["r1", "r2"]);
    }

    #[test]
    fn subgraph_handles_cycles_without_looping() {
        let s = InMemoryGraphStore::new();
        for e in ["e1", "e2"] {
            block_on(s.upsert_entity(ent(e, e, "", "p1"))).unwrap();
        }
        block_on(s.upsert_relationship(rel("r1", "e1", "e2", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r2", "e2", "e1", "p1"))).unwrap();
        let g = block_on(s.subgraph("p1", "e1", 5)).unwrap();
        assert_eq!(g.entities.len(), 2);
        assert_eq!(g.relationships.len(), 2);
    }

    #[test]
    fn subgraph_missing_seed_is_empty() {
        let s = InMemoryGraphStore::new();
        block_on(s.upsert_entity(ent("e1", "e1", "", "p1"))).unwrap();
        let g = block_on(s.subgraph("p1", "nope", 3)).unwrap();
        assert!(g.entities.is_empty());
        assert!(g.relationships.is_empty());
    }

    #[test]
    fn search_matches_name_or_summary_case_insensitive() {
        let s = InMemoryGraphStore::new();
        block_on(s.upsert_entity(ent("e1", "Quantum Physics", "study of matter", "p1"))).unwrap();
        block_on(s.upsert_entity(ent("e2", "Cooking", "quantum leaps in flavor", "p1"))).unwrap();
        block_on(s.upsert_entity(ent("e3", "Gardening", "plants", "p1"))).unwrap();
        let hits = block_on(s.search_entities("p1", "QUANTUM", 10)).unwrap();
        let ids: Vec<&str> = hits.iter().map(|e| e.uuid.as_str()).collect();
        assert_eq!(ids, vec!["e1", "e2"]); // e1 by name, e2 by summary
    }

    #[test]
    fn search_is_project_scoped_and_limited() {
        let s = InMemoryGraphStore::new();
        block_on(s.upsert_entity(ent("e1", "Alpha", "", "p1"))).unwrap();
        block_on(s.upsert_entity(ent("e2", "Alpha", "", "p1"))).unwrap();
        block_on(s.upsert_entity(ent("e3", "Alpha", "", "p2"))).unwrap();
        let hits = block_on(s.search_entities("p1", "alpha", 1)).unwrap();
        assert_eq!(hits.len(), 1); // limit honored
        assert_eq!(hits[0].project_id, "p1"); // p2 excluded
    }

    #[test]
    fn delete_entity_is_scoped_and_removes_touching_relationships() {
        let s = InMemoryGraphStore::new();
        for project in ["p1", "p2"] {
            for e in ["e1", "e2"] {
                block_on(s.upsert_entity(ent(e, e, "", project))).unwrap();
            }
        }
        block_on(s.upsert_relationship(rel("r1", "e1", "e2", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r2", "e1", "e2", "p2"))).unwrap();

        block_on(s.delete_entity("p1", "e1")).unwrap();

        assert!(block_on(s.get_entity("p1", "e1")).unwrap().is_none());
        assert!(block_on(s.get_entity("p2", "e1")).unwrap().is_some());
        assert!(block_on(s.subgraph("p1", "e2", 1))
            .unwrap()
            .relationships
            .is_empty());
        assert_eq!(
            block_on(s.subgraph("p2", "e1", 1))
                .unwrap()
                .relationships
                .len(),
            1
        );
    }

    #[test]
    fn delete_relationship_is_project_scoped() {
        let s = InMemoryGraphStore::new();
        for project in ["p1", "p2"] {
            for e in ["e1", "e2"] {
                block_on(s.upsert_entity(ent(e, e, "", project))).unwrap();
            }
        }
        block_on(s.upsert_relationship(rel("r1", "e1", "e2", "p1"))).unwrap();

        block_on(s.delete_relationship("p2", "r1")).unwrap();
        assert_eq!(
            block_on(s.subgraph("p1", "e1", 1))
                .unwrap()
                .relationships
                .len(),
            1
        );

        block_on(s.delete_relationship("p1", "r1")).unwrap();
        assert!(block_on(s.subgraph("p1", "e1", 1))
            .unwrap()
            .relationships
            .is_empty());
    }

    #[test]
    fn stats_counts_special_entity_types_and_scopes() {
        let s = InMemoryGraphStore::new();
        block_on(s.upsert_entity(ent("e1", "Alpha", "", "p1"))).unwrap();
        let mut episodic = ent("ep1", "Episode", "", "p1");
        episodic.entity_type = "Episodic".to_string();
        block_on(s.upsert_entity(episodic)).unwrap();
        let mut community = ent("c1", "Community", "", "p1");
        community.entity_type = "Community".to_string();
        block_on(s.upsert_entity(community)).unwrap();
        block_on(s.upsert_entity(ent("e2", "Other", "", "p2"))).unwrap();
        block_on(s.upsert_relationship(rel("r1", "e1", "ep1", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r2", "e2", "e2", "p2"))).unwrap();

        let scoped = block_on(s.stats(GraphStatsScope::Projects(vec!["p1".to_string()])))
            .expect("stats succeeds");
        assert_eq!(scoped.entities, 1);
        assert_eq!(scoped.episodes, 1);
        assert_eq!(scoped.communities, 1);
        assert_eq!(scoped.relationships, 1);
        assert_eq!(scoped.total_nodes, 3);

        let empty =
            block_on(s.stats(GraphStatsScope::Projects(Vec::new()))).expect("stats succeeds");
        assert_eq!(empty, GraphStats::default());

        let all = block_on(s.stats(GraphStatsScope::All)).expect("stats succeeds");
        assert_eq!(all.entities, 2);
        assert_eq!(all.relationships, 2);

        let exported = block_on(s.export(GraphStatsScope::Projects(vec!["p1".to_string()])))
            .expect("export succeeds");
        assert_eq!(
            exported
                .entities
                .iter()
                .map(|entity| entity.uuid.as_str())
                .collect::<Vec<_>>(),
            vec!["c1", "e1", "ep1"]
        );
        assert_eq!(
            exported
                .relationships
                .iter()
                .map(|relationship| relationship.uuid.as_str())
                .collect::<Vec<_>>(),
            vec!["r1"]
        );
    }

    #[test]
    fn cleanup_counts_and_deletes_only_old_scoped_episodes() {
        let s = InMemoryGraphStore::new();
        block_on(s.upsert_entity(ent("e1", "Alpha", "", "p1"))).unwrap();
        let mut old_episode = ent("ep-old", "Old", "", "p1");
        old_episode.entity_type = "Episodic".to_string();
        old_episode.created_at_ms = 1_000;
        block_on(s.upsert_entity(old_episode)).unwrap();
        let mut fresh_episode = ent("ep-fresh", "Fresh", "", "p1");
        fresh_episode.entity_type = "Episodic".to_string();
        fresh_episode.created_at_ms = 10_000;
        block_on(s.upsert_entity(fresh_episode)).unwrap();
        let mut other_project_episode = ent("ep-other", "Other", "", "p2");
        other_project_episode.entity_type = "Episodic".to_string();
        other_project_episode.created_at_ms = 1_000;
        block_on(s.upsert_entity(other_project_episode)).unwrap();
        block_on(s.upsert_relationship(rel("r-old", "e1", "ep-old", "p1"))).unwrap();
        block_on(s.upsert_relationship(rel("r-fresh", "e1", "ep-fresh", "p1"))).unwrap();

        let scope = GraphStatsScope::Projects(vec!["p1".to_string()]);
        let count =
            block_on(s.count_episodes_older_than(scope.clone(), 5_000)).expect("count succeeds");
        assert_eq!(count, 1);

        let deleted =
            block_on(s.delete_episodes_older_than(scope, 5_000)).expect("delete succeeds");
        assert_eq!(deleted, 1);
        assert!(block_on(s.get_entity("p1", "ep-old"))
            .expect("read succeeds")
            .is_none());
        assert!(block_on(s.get_entity("p1", "ep-fresh"))
            .expect("read succeeds")
            .is_some());
        assert!(block_on(s.get_entity("p2", "ep-other"))
            .expect("read succeeds")
            .is_some());
        let remaining = block_on(s.subgraph("p1", "e1", 1)).expect("subgraph succeeds");
        assert_eq!(
            remaining
                .relationships
                .iter()
                .map(|relationship| relationship.uuid.as_str())
                .collect::<Vec<_>>(),
            vec!["r-fresh"]
        );
    }
}
