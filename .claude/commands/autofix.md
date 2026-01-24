---
name: autofix: Apply
description: 自动执行代码检查并修复代码中的错误
category: loop
tags: [autofix]
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

自动执行代码检查并修复所有错误

## Steps
1. 执行单元测试
2. 修复单元测试发现的问题
3. 执行集成测试
4. 修复集成测试发现的问题
5. 执行端到端测试
6. 修复端到端测试发现的问题
7. 在 Chrome 中测试新增功能，并修复所有发现的问题
8. 执行 '/pr-review-toolkit:review-pr all' 并根据建议修改方案修复所有代码问题，直到 '/pr-review-toolkit:review-pr all' 不再返回任何问题。全部修复后直接输出 '所有代码问题已修复' 
