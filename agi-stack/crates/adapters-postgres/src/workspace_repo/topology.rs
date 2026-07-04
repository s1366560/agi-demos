use super::*;

impl PgWorkspaceRepository {
    pub async fn create_node(&self, node: TopologyNodeRecord) -> CoreResult<TopologyNodeRecord> {
        sqlx::query(&format!(
            "INSERT INTO topology_nodes \
                (id, workspace_id, node_type, ref_id, title, position_x, position_y, hex_q, \
                 hex_r, status, tags_json, data_json, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) \
             RETURNING {NODE_COLS}"
        ))
        .bind(&node.id)
        .bind(&node.workspace_id)
        .bind(&node.node_type)
        .bind(&node.ref_id)
        .bind(&node.title)
        .bind(node.position_x)
        .bind(node.position_y)
        .bind(node.hex_q)
        .bind(node.hex_r)
        .bind(&node.status)
        .bind(Json(&node.tags_json))
        .bind(Json(&node.data_json))
        .bind(node.created_at)
        .bind(node.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_node)
    }

    pub async fn list_nodes(
        &self,
        workspace_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<TopologyNodeRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {NODE_COLS} FROM topology_nodes WHERE workspace_id = $1 \
             ORDER BY created_at ASC, id ASC OFFSET $2 LIMIT $3"
        ))
        .bind(workspace_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_node).collect()
    }

    pub async fn get_node(
        &self,
        workspace_id: &str,
        node_id: &str,
    ) -> CoreResult<Option<TopologyNodeRecord>> {
        sqlx::query(&format!(
            "SELECT {NODE_COLS} FROM topology_nodes WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(node_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_node)
        .transpose()
    }

    pub async fn save_node(&self, node: TopologyNodeRecord) -> CoreResult<TopologyNodeRecord> {
        sqlx::query(&format!(
            "UPDATE topology_nodes SET node_type=$3, ref_id=$4, title=$5, position_x=$6, \
                 position_y=$7, hex_q=$8, hex_r=$9, status=$10, tags_json=$11, data_json=$12, \
                 updated_at=$13 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {NODE_COLS}"
        ))
        .bind(&node.id)
        .bind(&node.workspace_id)
        .bind(&node.node_type)
        .bind(&node.ref_id)
        .bind(&node.title)
        .bind(node.position_x)
        .bind(node.position_y)
        .bind(node.hex_q)
        .bind(node.hex_r)
        .bind(&node.status)
        .bind(Json(&node.tags_json))
        .bind(Json(&node.data_json))
        .bind(node.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_node)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("topology node update returned no row".into()))
    }

    pub async fn delete_node(&self, workspace_id: &str, node_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM topology_nodes WHERE id = $1 AND workspace_id = $2")
            .bind(node_id)
            .bind(workspace_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_edge(&self, edge: TopologyEdgeRecord) -> CoreResult<TopologyEdgeRecord> {
        sqlx::query(&format!(
            "INSERT INTO topology_edges \
                (id, workspace_id, source_node_id, target_node_id, label, source_hex_q, \
                 source_hex_r, target_hex_q, target_hex_r, direction, auto_created, data_json, \
                 created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) \
             RETURNING {EDGE_COLS}"
        ))
        .bind(&edge.id)
        .bind(&edge.workspace_id)
        .bind(&edge.source_node_id)
        .bind(&edge.target_node_id)
        .bind(&edge.label)
        .bind(edge.source_hex_q)
        .bind(edge.source_hex_r)
        .bind(edge.target_hex_q)
        .bind(edge.target_hex_r)
        .bind(&edge.direction)
        .bind(edge.auto_created)
        .bind(Json(&edge.data_json))
        .bind(edge.created_at)
        .bind(edge.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_edge)
    }

    pub async fn list_edges(
        &self,
        workspace_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<TopologyEdgeRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {EDGE_COLS} FROM topology_edges WHERE workspace_id = $1 \
             ORDER BY created_at ASC, id ASC OFFSET $2 LIMIT $3"
        ))
        .bind(workspace_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_edge).collect()
    }

    pub async fn get_edge(
        &self,
        workspace_id: &str,
        edge_id: &str,
    ) -> CoreResult<Option<TopologyEdgeRecord>> {
        sqlx::query(&format!(
            "SELECT {EDGE_COLS} FROM topology_edges WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(edge_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_edge)
        .transpose()
    }

    pub async fn save_edge(&self, edge: TopologyEdgeRecord) -> CoreResult<TopologyEdgeRecord> {
        sqlx::query(&format!(
            "UPDATE topology_edges SET source_node_id=$3, target_node_id=$4, label=$5, \
                 source_hex_q=$6, source_hex_r=$7, target_hex_q=$8, target_hex_r=$9, \
                 direction=$10, auto_created=$11, data_json=$12, updated_at=$13 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {EDGE_COLS}"
        ))
        .bind(&edge.id)
        .bind(&edge.workspace_id)
        .bind(&edge.source_node_id)
        .bind(&edge.target_node_id)
        .bind(&edge.label)
        .bind(edge.source_hex_q)
        .bind(edge.source_hex_r)
        .bind(edge.target_hex_q)
        .bind(edge.target_hex_r)
        .bind(&edge.direction)
        .bind(edge.auto_created)
        .bind(Json(&edge.data_json))
        .bind(edge.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_edge)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("topology edge update returned no row".into()))
    }

    pub async fn delete_edge(&self, workspace_id: &str, edge_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM topology_edges WHERE id = $1 AND workspace_id = $2")
            .bind(edge_id)
            .bind(workspace_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn edge_endpoints_in_workspace(
        &self,
        workspace_id: &str,
        source_node_id: &str,
        target_node_id: &str,
    ) -> CoreResult<Option<(Option<i32>, Option<i32>, Option<i32>, Option<i32>)>> {
        let row = sqlx::query_as::<_, (Option<i32>, Option<i32>, Option<i32>, Option<i32>)>(
            "SELECT s.hex_q, s.hex_r, t.hex_q, t.hex_r \
             FROM topology_nodes s \
             JOIN topology_nodes t ON t.id = $3 AND t.workspace_id = $1 \
             WHERE s.id = $2 AND s.workspace_id = $1",
        )
        .bind(workspace_id)
        .bind(source_node_id)
        .bind(target_node_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row)
    }
}
