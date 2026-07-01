# ADR-0002 · 不可信插件只走 WASM,绝不进 cdylib

- 状态:**已接受**(决策 Spike 证伪通过)
- 日期:2026-06
- 关联:[02-extensibility](../architecture/02-extensibility.md)、《基于 Rust 的插件化与模块化架构》调研 §12

## 背景

MemStack 是插件平台:L1 工具、L3 子智能体、MCP 工具中相当一部分是**第三方/不可信**代码。Rust 加载外部代码主要有三条路:`cdylib`/`abi_stable`(进程内动态库)、WASM 沙箱、跨进程 RPC。需要为"不可信扩展"定一条强制路径。

## 决策

**不可信代码一律只走 WASM 沙箱**(WASI / Component Model + WIT 契约)。**绝不**用 `cdylib` / `abi_stable` / 进程内动态库加载不可信代码。

- 可信一方内置工具 → `dyn Trait` 注册中心,编入核心(原生速度,不在此约束内)。
- 不可信第三方/MCP 工具 → WASM,经 `ToolHost` 端口调用(见 [ADR-0003](0003-plugin-host-as-hexagonal-port.md))。

## 理由

| 机制 | 隔离 | ABI 稳定 | 崩溃影响 | 可移植 | 判定 |
|---|---|---|---|---|---|
| `cdylib`/`abi_stable` | ❌ 无(同进程) | ❌ 脆弱 | ❌ 一崩全崩 | ❌ 平台相关 | **禁用于不可信** |
| **WASM 沙箱** | ✅ 内存/能力隔离 | ✅ WIT 契约 | ✅ 限于沙箱 | ✅ 可上端 | **采用** |
| 跨进程 RPC | ✅ 强 | ✅ | ✅ | ❌ Docker 上不了手机 | 重型 MCP 备选 |

WASM 还能**上移动端**(Docker/子进程不能),契合 local-first 端上工具。性能代价(≈60–80% 原生)对低频第三方工具可接受。

## 后果

- ➕ 不可信代码强隔离、契约化、可上端;一处崩溃不殃及宿主。
- ➖ 第三方工具须编为 WASM(WIT 契约),有性能与编译约束。
- ⚠️ 热路径工具必须是可信内置(`dyn Trait`),不可走 WASM,否则性能不达标(见 [02 §7 性能梯队](../architecture/02-extensibility.md))。
