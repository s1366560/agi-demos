# Cordis V2 历史数据库备份、恢复与升级证据

日期：2026-09-07。

本次从真实开发数据库的停止卷取得副本，完成数据库逻辑备份、向另一空数据库的实际恢复，以及从真实历史 Alembic revision 到当前 head 的完整升级验证。原数据库没有升级，没有执行 V1 转换、V2 发布或原库退役。

升级验证使用的代码 revision 为 `eee908c0d842ce484cbf6c118ee143b493b8d1aa`。证据来自真实停止卷，而非以预置测试 schema 替代历史数据库。

## 源对象与隔离

| 项目 | 实际对象或结果 |
| --- | --- |
| 源容器 | `memstack-postgres` |
| 源数据卷 | `agi-demos_postgres_data` |
| PostgreSQL 镜像 | `pgvector/pgvector:pg16` |
| 源卷观察大小 | 94 MiB |
| 操作前磁盘 | 宿主可用约 48 GiB，Docker 文件系统可用约 873 GiB |
| 源容器初始及最终状态 | `exited` |
| 原 loopback 5432 | 最终 TCP 探测未开放；本次未启动该端口 |

复制容器将原卷挂载到 `/source`，使用 `readonly`；Docker inspect 记录 `RW=false`。`cp -a /source/. /destination/` 的目标是任务专有新卷。后续 PostgreSQL 启动、备份、恢复及升级只接触专有卷。本次未向原卷写入，也未停止或启动原服务。

用于初始化空库的随机密码只在进程内存和子进程环境中传递，没有写入脚本、日志、命令参数或仓库配置。证据目录权限为 `0700`，备份及证据文件权限为 `0600`。完整备份包含数据库内容，保留在私有目录，未复制进仓库或输出业务内容。

## 冷卷副本、备份与实际恢复

任务对象如下：

- 克隆容器：`cordis-v1-backup-restore-h5nulhe6-clone`，端口 `127.0.0.1:55535`。
- 克隆卷：`cordis-v1-backup-restore-h5nulhe6-clone-data`。
- 空库恢复容器：`cordis-v1-backup-restore-h5nulhe6-restore`，端口 `127.0.0.1:55536`。
- 恢复卷：`cordis-v1-backup-restore-h5nulhe6-restore-data`。

宿主 PATH 中没有 `pg_dump`、`pg_restore`，因此使用上述 PG16 镜像内工具，通过容器内 Unix socket 操作副本。

执行顺序及退出结果：

1. 从只读原卷复制到专有卷，启动克隆数据库。
2. `pg_dump --format=custom --no-owner --no-privileges`：exit 0。
3. `pg_restore --list` 检查 custom archive：exit 0。
4. 将该备份输入另一全新数据库，执行 `pg_restore --exit-on-error --no-owner --no-privileges`：exit 0。
5. 读取恢复前后迁移版本及指定表的存在性、计数，结果相等。

这是完整单数据库逻辑备份及恢复验证；显式不恢复原对象 owner 和权限授予，不包含集群角色等全局对象。检查归档列表不是唯一证据，本次确实执行了向空数据库的恢复；但未进行全部业务记录的语义比较或应用功能验收。

| 恢复前后读取项 | 结果 |
| --- | --- |
| `alembic_version` | 1 行，`822cd9402ce6` |
| `platform_plugin_desired_states` | 表存在，0 行 |
| `platform_plugin_v1_conversion_runs` | 表不存在 |
| `platform_plugin_v2_publications` | 表不存在，因此没有 ROOT globally-ready publication 基线 |

备份路径：`/var/tmp/cordis-v1-backup-restore-h5nulhe6/database.backup`。

备份大小：3,371,203 字节。

备份 SHA256：

```text
6d8dc654acccedfbce79224f8522f7c8726b13c5c0c9d61eb4f3ee1782525eac
```

备份/恢复证据：`/var/tmp/cordis-v1-backup-restore-h5nulhe6/evidence.json`。

证据 SHA256：

```text
c6dd736771b7cb79715c44a7d3a01b53e3db3c5fc74878d330b1246e47e521e1
```

## 从真实历史 revision 完整升级

从上述同一 custom archive 再次恢复新的专有 PG16 数据库：

- 容器：`cordis-historical-upgrade-ud3hah3c-pg`。
- 数据卷：`cordis-historical-upgrade-ud3hah3c-data`。
- 成功升级使用的端口：`127.0.0.1:55757`。

`alembic/env.py` 从 `get_settings().postgres_url` 读取连接配置。一次性外部 harness 通过 `Settings.model_copy(update={"database_url": SecretStr(owned_url)})` 在内存中替换本进程的 `get_settings`，然后执行标准入口：

```python
alembic.command.upgrade(alembic.config.Config("alembic.ini"), "head")
```

执行前硬性核对 Docker 端口绑定仅为 `127.0.0.1`，URL 端口等于专有容器的实际随机端口、不是 5432，数据库名与专有恢复库一致。没有修改 `.env`、`alembic/env.py` 或业务代码；没有 `create_all`、`stamp`、跳 revision 或手工修改 SQL 绕过失败。

真实起点为 `822cd9402ce6`，ScriptDirectory 的目标 head 为 `e83f7c901b52`。日志记录标准升级依次执行全部十个 revision：

| 顺序 | Revision | 迁移内容 |
| --- | --- | --- |
| 1 | `dc206dd13ac3` | V2 publication ledger |
| 2 | `e91f4c7b2d60` | V2 publication readiness |
| 3 | `a4d8e2c7b901` | V2 desired bundle sets |
| 4 | `b5e9f3d8c012` | V1 conversion audit |
| 5 | `f43f5cd2fb21` | V2 data-plane credentials |
| 6 | `a47a93b38981` | Workspace contract actor authority audit |
| 7 | `b58c04d49a92` | Scoped publication ledger 与版本 head |
| 8 | `c69d15e50ba3` | Scope-private ProfileSource revisions |
| 9 | `d72e6b8f0a41` | Publication source bindings |
| 10 | `e83f7c901b52` | Outcome supersession audit |

备份恢复 exit 0，Alembic upgrade exit 0，升级后实际读取的 `alembic_version` 为 `e83f7c901b52`。

### 首次准备失败与重试

第一次新副本准备使用 Unix socket `pg_isready`，该检测不能区分镜像初始化期间的临时 PostgreSQL server 与最终 server。随后 restore 命令 exit 1，尚未进入 Alembic，没有失败的 migration revision。首轮 stderr 未保留，因此不能把具体 PostgreSQL 错误归因为某一个未捕获异常。

首轮记录保存在 `/var/tmp/cordis-historical-upgrade-ud3hah3c/attempt-1.json`，其专有容器和卷已清理。第二轮改用容器内 TCP `pg_isready -h 127.0.0.1` 等待正式 server，从同一未变备份重新恢复，再执行完整标准升级并成功。这是初始化就绪检查的调整，没有复用部分迁移结果或跳过失败步骤。

### 升级后只读状态

| 表 | 存在 | 行数 |
| --- | --- | --- |
| `platform_plugin_desired_states` | 是 | 0 |
| `platform_plugin_v1_conversion_runs` | 是 | 0 |
| `platform_plugin_v2_publications` | 是 | 0 |
| `platform_plugin_v2_desired_bundle_sets` | 是 | 0 |

V1 desired 行数保持不变，未执行转换写入。V2 publications 为空，仍没有可供退役 preflight 使用的 ROOT globally-ready 基线。现有 HTTP V1 retired 入口是代码层边界；本次未通过写入探测验证数据库触发器或权限层的 V1 freeze，也不宣称存在该类数据库强制机制。

完整脱敏升级日志：`/var/tmp/cordis-historical-upgrade-ud3hah3c/alembic-upgrade.log`。

日志 SHA256：

```text
59f916e378392f7f20b58793d53c43d8b65a216c3a51419e7ccfedc32b434f5d
```

升级证据：`/var/tmp/cordis-historical-upgrade-ud3hah3c/evidence.json`。

证据 SHA256：

```text
34fc78408aa3432db4b19086f0e0e0899b855bca0b71fd73aafe74de2d675aeb
```

## 清理与结论边界

备份/恢复的两个专有容器、两个命名卷、复制容器产生的匿名卷，以及历史升级的专有容器和卷，均已清理，记录的清理退出码均为 0。原容器最终仍为 `exited`，原 loopback 5432 未开放。私有备份、harness 和证据文件保留供后续审核。

本次证据支持：真实停止卷可生成逻辑备份、该备份可恢复到空 PG16 数据库、真实历史 revision 可通过仓库全部后续 Alembic migration 升级到所记录 head。

本次不证明从 Alembic base 建立全新 schema 的完整历史链，也不证明原数据库已经升级或退役。原库仍处于历史 revision；副本中没有非空 V1 desired 转换样本，没有 ROOT ready publication，未执行 conversion/apply、V2 runtime publication 或原服务切换。后续退役必须另行完成正式目标库升级、ROOT 运行及 ready 基线、审查映射和实际转换等剩余门禁，不能用本次副本验证替代。
