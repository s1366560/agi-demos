# Billing

Both clients use the [signed billing page](ui/shared/WebBillingPage.tsx) and [invoice table](ui/shared/InvoiceTable.tsx).

The installable identity is `memstack-billing`. Start with [package.json](package.json) for the default signed quote release and [build.py](build.py) for a release with a digest-pinned invoice worker. A single worker release exports quotes, invoices, page actions, and CLI commands together.

| Change | Entry point |
| --- | --- |
| Create, list, or read a project invoice | [Worker implementation](workers/invoice_worker.py) and [operation schemas](workers/invoice_contract.py) |
| Change the tenant billing API | [HTTP handlers](backend/http.py), [tenant authorization](backend/authority.py), and [tenant invoices and entitlements](backend/service.py) |
| Change pages | [shared billing view](ui/web/BillingView.tsx) and [project invoice actions](ui/shared/ProjectInvoiceActions.tsx) |
| Change stored invoice data | [Tenant invoice model](backend/invoices.py), [package migrations](migrations/), and [worker record contract](invoice_record.py) |
| Run package tests | `uv run pytest plugins/business/billing/tests` and `pnpm -C web exec vitest run ../plugins/business/billing/tests/Billing.test.tsx` |


The plan catalog in `plans.json` supplies the `quote` Wasm guest used by the tenant upgrade API. The guest accepts a plan identifier and returns its storage limit in bytes. The API authenticates the caller, checks the current tenant owner, validates the guest response and commits the quota update through the tenancy service. Invoice data and its Alembic revision history belong to this package.

The tenant marketplace can install Billing in a tenant with zero projects. Its signed page at `/tenant/:tenantId/billing` reads tenant usage and invoice history. Tenant administrators approve its exact release digest and permissions independently of project installations. The project marketplace mounts its own selected version at `/billing`. `app.billing.account.read` requires tenant billing access. The owner can confirm a plan change with `app.billing.plan.write`. Both commands use the same scoped entitlement and billing services as tenant HTTP. Project-issued invoices use the package worker and stay within the selected project.

Web and Electron mount the same [Billing page](ui/shared/WebBillingPage.tsx) and stylesheet. The page binds tenant and project actions to the approved commands for the selected release. To regenerate its checked-in browser artifact and resource digest after editing it, run `corepack pnpm --dir plugins/business/billing/ui/shared install --frozen-lockfile` followed by `corepack pnpm --dir plugins/business/billing/ui/shared run build`. The Python publisher includes the prepared artifact without a Node toolchain.

## Publish a release

Install the repository's Python dependencies and make its plugin SDK available. From the repository root, run:

```sh
PYTHONPATH=sdk/memstack-plugin-sdk/src uv run python plugins/business/billing/build.py \
  --version 3.1.0 --key "$PUBLISHER_KEY_FILE" --out billing.zip
```

The resulting Ed25519-signed archive contains a Wasm module, the `quote` operation, a settings page for Web and Desktop, and a command for each plan. The project package installer accepts this archive with `tools.execute`, `ui.slot`, `app.billing.account.read` and `app.billing.plan.write` approval. Its commands return a quote for the requested plan. The project installation can be upgraded or rolled back independently.

## Select a tenant quota policy

The deployment controls the archive used for quota mutations. Place the signed zip in `BILLING_POLICY_ARCHIVE_DIRECTORY` on each API replica, under its lowercase SHA-256 hash followed by `.zip`. Configure the publisher's public key in `PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES`. Set `policy_archive_digest` on the billing provider's profile entry to `sha256:<hash>` and publish that generation. The host verifies the archive hash and signature and compiles the guest before admission. The guest has bounded fuel, memory and output and receives no host imports.

Publish the previous digest to roll back. Removing the optional digest restores the bundled guest. Open operations retain the guest from their admitted generation. Invoice migrations use a separate `billing_alembic_version` table and retain invoice records during code rollback.

To reproduce the bundled guest after changing the default catalog, run:

```sh
uv run python plugins/business/billing/build.py --out plugins/business/billing/quote.wasm
```

A change to the bundled default also changes the digest in `backend/policy.py`. Independently signed releases use the digest selected by the profile.

## Project invoices

Build this directory as an OCI image and publish it by digest. The worker implements the quote, invoice creation, lookup and paginated listing operations. Its settings page exposes both plan quotes and the project invoice list. From the repository root, with a publisher key and registry coordinates already configured, run:

```sh
docker build -t "$BILLING_IMAGE_TAG" plugins/business/billing
docker push "$BILLING_IMAGE_TAG"
# BILLING_IMAGE_DIGEST_REF is the repository@sha256:... reference returned by the registry.
PYTHONPATH=sdk/memstack-plugin-sdk/src uv run python plugins/business/billing/build.py \
  --version 3.2.0 --key "$PUBLISHER_KEY_FILE" --worker-image "$BILLING_IMAGE_DIGEST_REF" \
  --out billing-invoices.zip
```

The deployment must allow the image registry in `PLUGIN_WORKER_ALLOWED_REGISTRIES` and trust the archive publisher. A project administrator approves `tools.execute`, `ui.slot`, `storage.read` and `storage.write` on the project installation. Members with project execution permission can invoke the active release. The worker container receives an MCP stdio connection. All persistence goes through that connection.

| Operation | Input | Result |
| --- | --- | --- |
| `invoice.create` | Unique `idempotency_key`, integer `amount` in the currency's minor unit, three-letter uppercase `currency`, timezone-aware ISO timestamps `period_start` and `period_end` | A pending invoice with its immutable ID, UTC billing period, creation and due dates. Repeating the same request returns the first invoice. Reuse of its key for different data returns `idempotency_conflict`. |
| `invoice.get` | An invoice `id` | The project invoice, or `not_found`. |
| `invoice.list` | Optional `limit` from 1 to 16 and the prior page's `next_cursor` as `after` | A page ordered by invoice ID and a `next_cursor` when another page is available. |

The independent worker owns the meaning and JSON representation of these immutable records. Its initial document format shares the legacy tenant invoice fields and adds `due_at`. The package's `workers/invoice_terms.json` defines the due date for new invoices. A code rollback keeps the fields and dates stored when each invoice was created.

The host binds every record callback to the admitted tenant, project and package. A tool can call `memstack/records/get` and `memstack/records/list` with an approved `storage.read` grant, and `memstack/records/create` with an approved `storage.write` grant. The grant must cover both the signed tool and the storage contribution. The host accepts one immutable create attempt per invocation and commits only after the guest returns output matching its signed schema and the executor finishes container cleanup. Revocation, quota or transport failures, invalid output and cancellation abort uncommitted writes. Disable, uninstall and code rollback retain committed records. Explicit project package purge removes them.

These project-issued invoices do not charge a payment method or change tenant quotas. Previously issued tenant-wide invoices remain accessible via the tenant Billing API and its own Alembic history. Importing them into a project requires an explicit ownership decision because the existing invoice table records only `tenant_id`.

## Optional integration with a separately published plan service

The default Billing release keeps plan calculation inside `memstack-billing`. For deployments that delegate plan ownership to a separate publisher, the `--plan-service` example builds the pure Wasm provider `memstack-billing-plans`. Build and approve its signed `quote` export in the project first. Then publish the Billing invoice worker with the matching signed import. The two archives may use different trusted publisher keys.

```sh
PYTHONPATH=sdk/memstack-plugin-sdk/src uv run python plugins/business/billing/build.py \
  --plan-service --version 1.0.0 --key "$PLANS_PUBLISHER_KEY_FILE" --out billing-plans.zip
PYTHONPATH=sdk/memstack-plugin-sdk/src uv run python plugins/business/billing/build.py \
  --plan-service --version 4.0.0 --key "$BILLING_PUBLISHER_KEY_FILE" \
  --worker-image "$BILLING_IMAGE_DIGEST_REF" --out billing-invoices.zip
```

The provider requires `tools.execute` and `services.provide`. The invoice package adds `services.call` to its usual grants, and only its `quote` tool declares the alias `plans`. Calling a Billing plan command now delegates to the approved provider for that project. Changing the Wasm plan catalog and releasing it at another package version changes the quote on the next call. The exact service contract version stays at `1.0.0`. Rolling back the provider restores its prior quotes.

In an SDK `package.json`, declare `services.provides` with entries such as `{"service":"service:package:memstack-billing-plans:quote","version":"1.0.0"}`. The consumer declares the same service and version under `services.requires` and adds `"alias":"plans"`. Its tool in `contributions.json` lists `"service_aliases":["plans"]` and the required permission. The packer signs both the v2 service contract and the profile entry bindings. The guest can use the admitted alias over its existing MCP stdio connection:

```json
{"jsonrpc":"2.0","id":"quote-1","method":"memstack/services/call","params":{"alias":"plans","input":{"plan":"pro"}}}
```

The JSON-RPC result contains the provider's validated structured output. A runtime admits at most eight signed aliases per consumer, four service calls per tool invocation and 64 KiB of combined callback inputs and outputs. The caller and provider retain their separate wall-time, memory, output and concurrency limits. An ordinary compatible upgrade preserves in-flight pins. Project withdrawal or registry revocation ends their admission. The deployment must change or disable dependent packages before replacing a service contract they still require.
