use super::*;

impl PgWorkspaceRepository {
    pub async fn create_post(
        &self,
        post: BlackboardPostRecord,
    ) -> CoreResult<BlackboardPostRecord> {
        sqlx::query(&format!(
            "INSERT INTO blackboard_posts \
                (id, workspace_id, author_id, title, content, status, is_pinned, metadata_json, \
                 created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) \
             RETURNING {POST_COLS}"
        ))
        .bind(&post.id)
        .bind(&post.workspace_id)
        .bind(&post.author_id)
        .bind(&post.title)
        .bind(&post.content)
        .bind(&post.status)
        .bind(post.is_pinned)
        .bind(Json(&post.metadata_json))
        .bind(post.created_at)
        .bind(post.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_post)
    }

    pub async fn list_posts(
        &self,
        workspace_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<BlackboardPostRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {POST_COLS} FROM blackboard_posts WHERE workspace_id = $1 \
             ORDER BY is_pinned DESC, created_at DESC, id ASC OFFSET $2 LIMIT $3"
        ))
        .bind(workspace_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_post).collect()
    }

    pub async fn get_post(
        &self,
        workspace_id: &str,
        post_id: &str,
    ) -> CoreResult<Option<BlackboardPostRecord>> {
        sqlx::query(&format!(
            "SELECT {POST_COLS} FROM blackboard_posts WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(post_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_post)
        .transpose()
    }

    pub async fn save_post(&self, post: BlackboardPostRecord) -> CoreResult<BlackboardPostRecord> {
        sqlx::query(&format!(
            "UPDATE blackboard_posts SET title=$3, content=$4, status=$5, is_pinned=$6, \
                 metadata_json=$7, updated_at=$8 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {POST_COLS}"
        ))
        .bind(&post.id)
        .bind(&post.workspace_id)
        .bind(&post.title)
        .bind(&post.content)
        .bind(&post.status)
        .bind(post.is_pinned)
        .bind(Json(&post.metadata_json))
        .bind(post.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_post)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("blackboard post update returned no row".into()))
    }

    pub async fn delete_post(&self, workspace_id: &str, post_id: &str) -> CoreResult<bool> {
        let result =
            sqlx::query("DELETE FROM blackboard_posts WHERE id = $1 AND workspace_id = $2")
                .bind(post_id)
                .bind(workspace_id)
                .execute(&self.pool)
                .await
                .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_reply(
        &self,
        reply: BlackboardReplyRecord,
    ) -> CoreResult<BlackboardReplyRecord> {
        sqlx::query(&format!(
            "INSERT INTO blackboard_replies \
                (id, post_id, workspace_id, author_id, content, metadata_json, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8) \
             RETURNING {REPLY_COLS}"
        ))
        .bind(&reply.id)
        .bind(&reply.post_id)
        .bind(&reply.workspace_id)
        .bind(&reply.author_id)
        .bind(&reply.content)
        .bind(Json(&reply.metadata_json))
        .bind(reply.created_at)
        .bind(reply.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_reply)
    }

    pub async fn list_replies(
        &self,
        workspace_id: &str,
        post_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<BlackboardReplyRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {REPLY_COLS} FROM blackboard_replies \
             WHERE workspace_id = $1 AND post_id = $2 \
             ORDER BY created_at ASC, id ASC OFFSET $3 LIMIT $4"
        ))
        .bind(workspace_id)
        .bind(post_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_reply).collect()
    }

    pub async fn get_reply(
        &self,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> CoreResult<Option<BlackboardReplyRecord>> {
        sqlx::query(&format!(
            "SELECT {REPLY_COLS} FROM blackboard_replies \
             WHERE id = $1 AND post_id = $2 AND workspace_id = $3"
        ))
        .bind(reply_id)
        .bind(post_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_reply)
        .transpose()
    }

    pub async fn save_reply(
        &self,
        reply: BlackboardReplyRecord,
    ) -> CoreResult<BlackboardReplyRecord> {
        sqlx::query(&format!(
            "UPDATE blackboard_replies SET content=$4, metadata_json=$5, updated_at=$6 \
             WHERE id=$1 AND post_id=$2 AND workspace_id=$3 RETURNING {REPLY_COLS}"
        ))
        .bind(&reply.id)
        .bind(&reply.post_id)
        .bind(&reply.workspace_id)
        .bind(&reply.content)
        .bind(Json(&reply.metadata_json))
        .bind(reply.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_reply)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("blackboard reply update returned no row".into()))
    }

    pub async fn delete_reply(
        &self,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> CoreResult<bool> {
        let result = sqlx::query(
            "DELETE FROM blackboard_replies WHERE id = $1 AND post_id = $2 AND workspace_id = $3",
        )
        .bind(reply_id)
        .bind(post_id)
        .bind(workspace_id)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_file(
        &self,
        file: BlackboardFileRecord,
    ) -> CoreResult<BlackboardFileRecord> {
        sqlx::query(&format!(
            "INSERT INTO blackboard_files \
                (id, workspace_id, parent_path, name, is_directory, file_size, content_type, \
                 storage_key, uploader_type, uploader_id, uploader_name, checksum_sha256, \
                 mime_type_detected, created_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) \
             RETURNING {FILE_COLS}"
        ))
        .bind(&file.id)
        .bind(&file.workspace_id)
        .bind(&file.parent_path)
        .bind(&file.name)
        .bind(file.is_directory)
        .bind(file.file_size)
        .bind(&file.content_type)
        .bind(&file.storage_key)
        .bind(&file.uploader_type)
        .bind(&file.uploader_id)
        .bind(&file.uploader_name)
        .bind(&file.checksum_sha256)
        .bind(&file.mime_type_detected)
        .bind(file.created_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_file)
    }

    pub async fn list_files(
        &self,
        workspace_id: &str,
        parent_path: &str,
    ) -> CoreResult<Vec<BlackboardFileRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {FILE_COLS} FROM blackboard_files \
             WHERE workspace_id = $1 AND parent_path = $2 \
             ORDER BY is_directory DESC, name ASC"
        ))
        .bind(workspace_id)
        .bind(parent_path)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_file).collect()
    }

    pub async fn find_file_by_path(
        &self,
        workspace_id: &str,
        parent_path: &str,
        name: &str,
    ) -> CoreResult<Option<BlackboardFileRecord>> {
        sqlx::query(&format!(
            "SELECT {FILE_COLS} FROM blackboard_files \
             WHERE workspace_id = $1 AND parent_path = $2 AND name = $3"
        ))
        .bind(workspace_id)
        .bind(parent_path)
        .bind(name)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_file)
        .transpose()
    }

    pub async fn get_file(
        &self,
        workspace_id: &str,
        file_id: &str,
    ) -> CoreResult<Option<BlackboardFileRecord>> {
        sqlx::query(&format!(
            "SELECT {FILE_COLS} FROM blackboard_files WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(file_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_file)
        .transpose()
    }

    pub async fn find_file_descendants(
        &self,
        workspace_id: &str,
        path_prefix: &str,
    ) -> CoreResult<Vec<BlackboardFileRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {FILE_COLS} FROM blackboard_files \
             WHERE workspace_id = $1 AND parent_path LIKE $2 \
             ORDER BY parent_path ASC, is_directory DESC, name ASC"
        ))
        .bind(workspace_id)
        .bind(format!("{path_prefix}%"))
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_file).collect()
    }

    pub async fn save_file(&self, file: BlackboardFileRecord) -> CoreResult<BlackboardFileRecord> {
        sqlx::query(&format!(
            "UPDATE blackboard_files SET parent_path=$3, name=$4, is_directory=$5, \
                 file_size=$6, content_type=$7, storage_key=$8, uploader_type=$9, \
                 uploader_id=$10, uploader_name=$11, checksum_sha256=$12, \
                 mime_type_detected=$13 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {FILE_COLS}"
        ))
        .bind(&file.id)
        .bind(&file.workspace_id)
        .bind(&file.parent_path)
        .bind(&file.name)
        .bind(file.is_directory)
        .bind(file.file_size)
        .bind(&file.content_type)
        .bind(&file.storage_key)
        .bind(&file.uploader_type)
        .bind(&file.uploader_id)
        .bind(&file.uploader_name)
        .bind(&file.checksum_sha256)
        .bind(&file.mime_type_detected)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_file)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("blackboard file update returned no row".into()))
    }

    pub async fn bulk_update_file_parent_path(
        &self,
        workspace_id: &str,
        old_prefix: &str,
        new_prefix: &str,
    ) -> CoreResult<u64> {
        let result = sqlx::query(
            "UPDATE blackboard_files \
             SET parent_path = CASE \
                 WHEN parent_path = $2 THEN $3 \
                 ELSE concat($3, substr(parent_path, $4)) \
             END \
             WHERE workspace_id = $1 AND (parent_path = $2 OR parent_path LIKE $5)",
        )
        .bind(workspace_id)
        .bind(old_prefix)
        .bind(new_prefix)
        .bind((old_prefix.len() + 1) as i32)
        .bind(format!("{old_prefix}%"))
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(result.rows_affected())
    }

    pub async fn delete_file(&self, workspace_id: &str, file_id: &str) -> CoreResult<bool> {
        let result =
            sqlx::query("DELETE FROM blackboard_files WHERE id = $1 AND workspace_id = $2")
                .bind(file_id)
                .bind(workspace_id)
                .execute(&self.pool)
                .await
                .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }
}
