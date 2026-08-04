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

## 缺口 2(已知,路线图 1c):按文件/hunk 的 revert/stage

依赖沙箱 git 写权限,本期明确不做。当前 diff 端点为只读(`git_diff_failed` 等 reason 文案也
表明只读语义)。需要沙箱写路径开放后,再补按文件/hunk 的 revert 入口与对应的 HITL 确认。

## 前端已交付的对应约定

- 行内评论消息:文本携带引用锚点(`path#L12` 新侧 / `path#L-9` 旧侧),结构化
  `CodeRangeReference`(含 `snapshot_id` + `patch_digest`)随 run-input payload 上行,与
  composer 现有引用机制完全同路。快照刷新后旧锚点因 digest 失配自然失效,这是有意设计。
- 待发送评论仅按会话存于内存(不写 localStorage):评论锚定特定快照,重启后锚点必然过期。
