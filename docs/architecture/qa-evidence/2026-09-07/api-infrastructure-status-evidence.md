# Infrastructure API 状态证据

日期：2026-09-07。下列记录按原始观察顺序归档，仅保留方法、路径和HTTP状态，不包含请求或响应正文。历史软删除故障的200不是最终通过结果；修复后的GET/PUT404见后续记录。隔离配置CRUD仅验证持久化与清理，未执行部署或外部发送。

### GET `/api/v1/tenants/` → 200

### GET `/api/v1/instances/` → 200

### GET `/api/v1/clusters/` → 200

### GET `/api/v1/instance-templates/` → 200

### GET `/api/v1/admin/pool/status` → 403

### GET `/api/v1/admin/pool/instances` → 403

### GET `/api/v1/admin/pool/metrics` → 403

### GET `/api/v1/graph-stores/types` → 200

### GET `/api/v1/retrieval-stores/types` → 200

### GET `/api/v1/graph-stores` → 200

### GET `/api/v1/retrieval-stores` → 200

### POST `/api/v1/instance-templates/` → 201

### GET `/api/v1/instance-templates/ad1ac177-68c1-4183-8958-17f225e66a04` → 200

### PUT `/api/v1/instance-templates/ad1ac177-68c1-4183-8958-17f225e66a04` → 200

### GET `/api/v1/instance-templates/ad1ac177-68c1-4183-8958-17f225e66a04` → 200

### DELETE `/api/v1/instance-templates/ad1ac177-68c1-4183-8958-17f225e66a04` → 204

### GET `/api/v1/instance-templates/ad1ac177-68c1-4183-8958-17f225e66a04` → 404

### POST `/api/v1/clusters/` → 201

### GET `/api/v1/clusters/827376f3-fa6d-4b3f-b30e-56bff0a74fd2` → 200

### PUT `/api/v1/clusters/827376f3-fa6d-4b3f-b30e-56bff0a74fd2` → 200

### GET `/api/v1/clusters/827376f3-fa6d-4b3f-b30e-56bff0a74fd2` → 200

### DELETE `/api/v1/clusters/827376f3-fa6d-4b3f-b30e-56bff0a74fd2` → 204

### GET `/api/v1/clusters/827376f3-fa6d-4b3f-b30e-56bff0a74fd2` → 404

### POST `/api/v1/instances/` → 201

### GET `/api/v1/instances/814af60a-e3c0-4cb3-9853-058b380920ee` → 200

### PUT `/api/v1/instances/814af60a-e3c0-4cb3-9853-058b380920ee` → 200

### GET `/api/v1/instances/814af60a-e3c0-4cb3-9853-058b380920ee` → 200

### DELETE `/api/v1/instances/814af60a-e3c0-4cb3-9853-058b380920ee` → 204

### GET `/api/v1/instances/814af60a-e3c0-4cb3-9853-058b380920ee` → 200

### POST `/api/v1/graph-stores` → 201

### GET `/api/v1/graph-stores/cc2b4431-a2e3-48bf-b58a-b7d780520a61` → 200

### PUT `/api/v1/graph-stores/cc2b4431-a2e3-48bf-b58a-b7d780520a61` → 200

### GET `/api/v1/graph-stores/cc2b4431-a2e3-48bf-b58a-b7d780520a61` → 200

### DELETE `/api/v1/graph-stores/cc2b4431-a2e3-48bf-b58a-b7d780520a61` → 204

### GET `/api/v1/graph-stores/cc2b4431-a2e3-48bf-b58a-b7d780520a61` → 404

### POST `/api/v1/retrieval-stores` → 201

### GET `/api/v1/retrieval-stores/71961554-38f9-4464-842e-91dec8246aca` → 200

### PUT `/api/v1/retrieval-stores/71961554-38f9-4464-842e-91dec8246aca` → 200

### GET `/api/v1/retrieval-stores/71961554-38f9-4464-842e-91dec8246aca` → 200

### DELETE `/api/v1/retrieval-stores/71961554-38f9-4464-842e-91dec8246aca` → 204

### GET `/api/v1/retrieval-stores/71961554-38f9-4464-842e-91dec8246aca` → 404

### POST `/api/v1/agent/templates?tenant_id=02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 201

### GET `/api/v1/agent/templates/379eb01f-0352-4dde-a596-2b92e88ed9cd?tenant_id=02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 200

### PUT `/api/v1/agent/templates/379eb01f-0352-4dde-a596-2b92e88ed9cd?tenant_id=02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 200

### GET `/api/v1/agent/templates/379eb01f-0352-4dde-a596-2b92e88ed9cd?tenant_id=02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 200

### DELETE `/api/v1/agent/templates/379eb01f-0352-4dde-a596-2b92e88ed9cd?tenant_id=02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 204

### GET `/api/v1/agent/templates/379eb01f-0352-4dde-a596-2b92e88ed9cd?tenant_id=02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 404

### POST `/api/v1/tenant-webhooks/02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 200

### GET `/api/v1/tenant-webhooks/02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 200

### PUT `/api/v1/tenant-webhooks/ff0ac9d1-e266-466d-b183-872a0dd2bbd4` → 200

### DELETE `/api/v1/tenant-webhooks/ff0ac9d1-e266-466d-b183-872a0dd2bbd4` → 204

### GET `/api/v1/tenant-webhooks/02f6fccc-0ac9-4729-bac7-38e77d1c61ef` → 200

### GET `/api/v1/instances/` → 200

### PUT `/api/v1/instances/814af60a-e3c0-4cb3-9853-058b380920ee` → 200

### Instance soft-delete remediation validation

### GET `/api/v1/tenants/02f6fccc-0ac9-4729-bac7-38e77d1c61ef/projects/738ace12-0d21-48ca-847d-cd0c2802816d/workspaces` → 200

### GET `/api/v1/instances/814af60a-e3c0-4cb3-9853-058b380920ee` → 404

### PUT `/api/v1/instances/814af60a-e3c0-4cb3-9853-058b380920ee` → 404

### GET `/api/v1/workspace-context` → 404

### GET `/api/v1/projects/` → 200

### Native cloud login Workspace Context diagnosis and fix

### GET `/api/v1/workspace-context` → 200

### GET `/api/v1/agent/conversations/4b6602f0-dedb-44fe-8475-89ab96c9689a?project_id=9fa840d9-f0b4-4ab0-9ff1-5aeac420dcb8` → 200

### GET `/api/v1/platform-plugins/v2/desired-bundle-sets/current?scope_kind=SESSION&tenant_id=02f6fccc-0ac9-4729-bac7-38e77d1c61ef&project_id=9fa840d9-f0b4-4ab0-9ff1-5aeac420dcb8&session_id=4b6602f0-dedb-44fe-8475-89ab96c9689a` → 403

### Restart8 live verification and historical recovery classification

### Native cloud authority remains unavailable: missing deployment grant

### GET `/api/v1/workspaces/b30bf32d-36f0-4832-bcca-252a8df18b15/autonomy/attentions` → 404

### GET `/api/v1/workspaces/b30bf32d-36f0-4832-bcca-252a8df18b15/tasks` → 200

### GET `/api/v1/workspaces/b30bf32d-36f0-4832-bcca-252a8df18b15/plan` → 404

### GET `/api/v1/agent/conversations/5a6c6808-9454-4838-9131-0deae9338e56?project_id=738ace12-0d21-48ca-847d-cd0c2802816d` → 200

### GET `/api/v1/agent/conversations/5a6c6808-9454-4838-9131-0deae9338e56/status?project_id=738ace12-0d21-48ca-847d-cd0c2802816d` → 200

### GET `/api/v1/agent/conversations/5a6c6808-9454-4838-9131-0deae9338e56/messages?project_id=738ace12-0d21-48ca-847d-cd0c2802816d` → 200
