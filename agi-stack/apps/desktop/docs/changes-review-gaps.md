# Changes 审查面板 — 后端契约缺口(P1-4)

本文记录桌面端 Changes canvas 升级为审查面板(P1-4,`docs/design/desktop-ux-benchmark-roadmap.md`)
过程中确认的后端契约缺口,供后端排期参考。前端侧已交付:按文件展开/折叠(含全部展开/全部折叠)、
行内行锚定评论并批量回喂 agent、空闲零重绘守卫。

## 缺口 1:范围切换(本轮改动 / 会话全部改动)无法真实派生

路线图 1a 要求"本轮改动 / 会话全部改动"范围切换。核实当前变更快照契约
(`GET` run changes,前端类型 `ChangeSnapshot`/`ChangeFile`/`ChangeHunk`,见
`src/types.ts`)后结论:**无法真实派生,暂不 shipped,绝不伪造范围**。

快照 payload 现状:

- 一个快照 = 单个 run 的 `base_revision → head_revision` 扁平 diff;`run_id`、`run_revision`、
  `captured_at` 只标识快照本身。
- `ChangeFile` 无 turn id、无 staged 标记、无 mtime;`ChangeHunk`/`ChangeLine` 无任何
  turn/hunk 级归属元数据。
- 前端只有当前 run 的快照,没有会话级(跨 run/跨轮)的变更端点。

因此两种候选语义都缺数据:

- 若"本轮"= 当前 run:快照本身即是本轮,但"会话全部"需要跨 run 的会话基线 diff,端点不存在。
- 若"本轮"= 会话中的最近一轮(turn):需要每文件/每 hunk 的 turn 归属,或至少
  turn 边界 + 文件级时间戳;两者 payload 均未携带。时间线 turn 边界与文件 mtime 的客户端
  拼接无法保证真实性(mtime 不在 payload 内,且与 diff 行无可靠映射),属于伪造范围,已排除。

后端建议(任一即可解锁):

1. 快照增加会话级视图:`GET /runs/{id}/changes?scope=session`,或在 `ChangeSnapshot` 上增加
   `session_base_revision`,由后端产出会话基线 → head 的 diff;
2. 或为 `ChangeFile`/`ChangeHunk` 增加 `turn_id`(或 `run_revision` 区间)归属字段,前端即可
   在本地做真实的范围过滤。

## 缺口 2(Cloud 侧已交付 revert;stage 与本地模式仍为后续):按文件/hunk 的 revert/stage

~~依赖沙箱 git 写权限,本期明确不做。当前 diff 端点为只读(`git_diff_failed` 等 reason 文案也
表明只读语义)。需要沙箱写路径开放后,再补按文件/hunk 的 revert 入口与对应的 HITL 确认。~~

**进展更新(本轮,Cloud 侧 revert 已落地)**:新增
`POST /api/v1/agent/runs/{run_id}/changes/revert`,语义与守门如下:

- **机制(诚实路径)**:Cloud 快照是录制变更事件的归因回放(每文件携带完整 hunk 行内容 +
  `patch_digest`),不是实时 git diff。回退由服务端重算快照后,从录制 hunk 重建统一 diff,
  在项目 Cloud 沙箱内 `git apply --check --reverse` → `git apply --reverse`
  (先全量校验、后应用,单一组合补丁保证全有或全无);无 hunk 内容的 untracked/新建文件以
  守卫过的 `rm` 删除;`rm` 失败会前向重放补丁回滚。重命名、二进制、无录制内容的修改一律
  失败关闭(`change_content_not_recorded`),绝不猜测。
- **契约**:客户端只发送选择子(`selectors: [{path, hunk_indices?}]`)+ `snapshot_digest` +
  `expected_run_revision` + `idempotency_key`。digest 失配 → 409 `snapshot_digest_mismatch`;
  未知文件/hunk → 409 `unknown_change_selector`;运行进行中 → 409 `run_active`;无运行中的
  Cloud 沙箱/非 Cloud/未运行 → 503 `sandbox_write_unavailable`(retryable);补丁不再适用 →
  409 `revert_patch_conflict`,且不落任何写。权限沿用 `_load_scoped_run`(403/404);
  幂等回执持久化在 `authorization_snapshot.change_revert_receipts`,同 key 同载荷重放返回
  `created=false`,同 key 异载荷 409。沙箱写入包裹在 `pin_agent_turn_operation_v2` 审计上下文中。
- **回放一致性**:成功回退记录 `change_reverted` 执行事件;`GET .../changes` 重放会按
  (path, patch_digest, hunk_index) 扣减已回退选择子,刷新后的快照 digest 变化,旧评论锚点
  按既有设计自然失效。响应携带新 `snapshot_digest` 与 `head_commit`。
- **桌面端**:Changes 面板按文件与按 hunk 提供 Revert 入口,先弹破坏性确认
  (`alertdialog`,说明将回退什么、其余改动保留);成功后刷新快照;`snapshot_digest_mismatch`
  提示刷新;本地模式结构化不可用(客户端不发请求,`local_run_changes_revert_unavailable`)。
  i18n en+zh 均为追加。

**仍为后续**:stage(本次明确只做 revert)、本地模式回退(sidecar 写路径,仍 fail-closed)、
跨会话基线已过期的会话级回退在补丁冲突时依赖 `revert_patch_conflict` 诚实报错。

## 前端已交付的对应约定

- 行内评论消息:文本携带引用锚点(`path#L12` 新侧 / `path#L-9` 旧侧),结构化
  `CodeRangeReference`(含 `snapshot_id` + `patch_digest`)随 run-input payload 上行,与
  composer 现有引用机制完全同路。快照刷新后旧锚点因 digest 失配自然失效,这是有意设计。
- 待发送评论仅按会话存于内存(不写 localStorage):评论锚定特定快照,重启后锚点必然过期。

## 进展更新(缺口 1 已解锁,Cloud 侧)

`GET /api/v1/agent/runs/{id}/changes` 的 `scope` 参数现已支持 `session`(`turn`/`run`/`session`,
缺省 `run`,缺省时响应与 `scope=run` 逐字节一致)。会话级语义:

- 会话基线锚点 = 会话内最早一个记录了 `authorization_snapshot.environment.base_commit` 的运行的
  base commit;快照的 `base_revision`/`environment_id`/`repository_root`/`workspace_path`/`branch`
  均取自该锚点环境,而非当前运行。
- 失败关闭:首个触及工作区的运行未记录 base commit、或整个会话无任何环境记录时,返回
  `status="unavailable"` + `reason="session_baseline_unavailable"`;会话内运行跨多个
  repository_root/workspace_path 时返回 `reason="session_baseline_environment_mismatch"`;
  两种情形均不产出文件/归因数据,绝不伪造差异。
- 桌面端面板在会话范围不可用时展示该结构化原因,并提供"查看本轮改动"显式回退按钮
  (`session.changesBackToRunScope`),不做客户端拼接。
- 本地模式(sidecar 单 run git diff)仍只暴露 `run` 范围,前端按 `availableScopes` 禁用其余档位。
