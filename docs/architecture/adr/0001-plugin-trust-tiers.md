# ADR 0001: Plugin trust tiers and optional business

## Status

Accepted for the in-repo implementation on `main` after `87c33b230`. This document records the target and the behavior that code actually executes. A type or fixture is not an implementation claim.

## Context

Protocol v2 already runs host business as builtin modules and can admit signed WASM. That coupling is the current composition, not a decision that every business route must remain inside the host forever. `REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS` is the list of route rows the current builtin graph mounts. It is not an ownership freeze.

## Decision

Three executing tiers, plus two reserved protocol values:

| Tier | What it may do | What it may not do |
| --- | --- | --- |
| Host mechanism | Identity, tenant and project authorization, key storage, signature checks, transactions, generation leases, publication receipts, sandbox policy enforcement, the agent loop, CSP, and Electron IPC | Hand those mechanisms to an untrusted package |
| High-privilege first party | Same-process `register_*` for channels, tools, skills, and agent definitions that ship with the host | Be treated as a third-party package. These modules are still host source |
| Signed third party | A signed package whose wasm exports `invoke` or `score`, whose UI is signed structured bytes, and whose storage goes through the host namespace proxy | Import host modules, supply its own authorization object, or open a database connection |

`tenant-approved` and `untrusted` remain protocol values. This change does not add executors for them. Desktop registry acceptance of a `signed:` prefix is only a registration predicate. UI is loaded only after the host checks digest, source, and target plane and renders the bytes in a sandboxed document.

## Optional business

Channels, memory strategies, provider adapters, commands, workflows, and MCP bridges have not all gained executors here. The executed third-party surface in this change is a generic tool invoke, a skill record, a structured UI document, and namespaced storage. Later contracts must name an executor before they are described as supported.

## Lifecycle

Package recorded, desired enabled, runtime phase, UI mounted, and sync status are separate fields. `loading` means apply is in progress. It does not mean loaded. A failed apply keeps the previous active generation. User rollback writes a new desired revision that points at the previous verified digest.

Disable and uninstall keep namespace data and record `retained`. Purge deletes that scope's keys and records `purged`.

## Scan evidence

`security_scan_passed` on an install request is not a scan report. With no scanner configured, the stored status is `unknown`. `unknown` does not mean a scan passed. A `failed` report still blocks permission approval. Signature checks stay in force.

## Offline desktop

A 30 second poll is the next sync attempt, not a revocation deadline. If the poll fails, the last generation stays mounted and sync is `degraded`. High-risk permissions (`tools.execute`, `storage.write`) require a host capability lease. The default lease is 15 minutes. After expiry those calls fail. Storage reads of an already active, unrevoked package remain available. An explicit revoke rejects both old sessions and new calls. No untested SLA is claimed.

## Consequences

Sample packages live under `samples/` and are installed through the generic signed runtime. They do not add a sample-specific builtin module or catalog row. The SDK under `sdk/memstack-plugin-sdk` exports contracts only and is not published.
