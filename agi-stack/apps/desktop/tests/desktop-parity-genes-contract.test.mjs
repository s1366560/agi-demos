import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const registry = JSON.parse(
  readFileSync(new URL("parity-capability-fragments.v2.json", contractRoot)),
);
const capabilities = registry.fragments.flatMap(
  (fileName) =>
    JSON.parse(readFileSync(new URL(fileName, contractRoot), "utf8"))
      .capabilities,
);
const genes = capabilities.find(
  (capability) => capability.id === "tenant-tenant-genes",
);

const contractsFor = (surface) =>
  genes.api_contracts
    .filter((contract) => contract.surface === surface)
    .map(({ method, path, authority }) => ({ method, path, authority }));

test("Gene Market contracts only include APIs consumed by its owned production pages", () => {
  assert.ok(genes);
  assert.deepEqual(contractsFor("web"), [
    { method: "GET", path: "/api/v1/genes/", authority: "web_service" },
    { method: "POST", path: "/api/v1/genes/", authority: "web_service" },
    {
      method: "GET",
      path: "/api/v1/genes/{gene_id}",
      authority: "web_service",
    },
    {
      method: "PUT",
      path: "/api/v1/genes/{gene_id}",
      authority: "web_service",
    },
    {
      method: "DELETE",
      path: "/api/v1/genes/{gene_id}",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/{gene_id}/publish",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/{gene_id}/unpublish",
      authority: "web_service",
    },
    {
      method: "GET",
      path: "/api/v1/genes/genomes",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/genomes",
      authority: "web_service",
    },
    {
      method: "GET",
      path: "/api/v1/genes/genomes/{genome_id}",
      authority: "web_service",
    },
    {
      method: "PUT",
      path: "/api/v1/genes/genomes/{genome_id}",
      authority: "web_service",
    },
    {
      method: "DELETE",
      path: "/api/v1/genes/genomes/{genome_id}",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/genomes/{genome_id}/publish",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/genomes/{genome_id}/unpublish",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/instances/{instance_id}/install",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/instances/{instance_id}/genomes/{genome_id}/install",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/genomes/{genome_id}/ratings",
      authority: "web_service",
    },
    {
      method: "GET",
      path: "/api/v1/genes/evolution",
      authority: "web_service",
    },
    {
      method: "GET",
      path: "/api/v1/genes/{gene_id}/reviews",
      authority: "web_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/{gene_id}/reviews",
      authority: "web_service",
    },
    {
      method: "DELETE",
      path: "/api/v1/genes/{gene_id}/reviews/{review_id}",
      authority: "web_service",
    },
  ]);
  assert.deepEqual(contractsFor("desktop_cloud"), [
    { method: "GET", path: "/api/v1/genes/", authority: "cloud_service" },
    { method: "POST", path: "/api/v1/genes/", authority: "cloud_service" },
    {
      method: "PUT",
      path: "/api/v1/genes/{gene_id}",
      authority: "cloud_service",
    },
    {
      method: "DELETE",
      path: "/api/v1/genes/{gene_id}",
      authority: "cloud_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/{gene_id}/publish",
      authority: "cloud_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/{gene_id}/unpublish",
      authority: "cloud_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/instances/{instance_id}/install",
      authority: "cloud_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/{gene_id}/ratings",
      authority: "cloud_service",
    },
    {
      method: "POST",
      path: "/api/v1/genes/{gene_id}/reviews",
      authority: "cloud_service",
    },
    {
      method: "DELETE",
      path: "/api/v1/genes/{gene_id}/reviews/{review_id}",
      authority: "cloud_service",
    },
  ]);
});

test("Gene Market actions preserve tenant and review ownership enforcement", () => {
  assert.deepEqual(genes.actions, [
    "view",
    "list",
    "create",
    "update",
    "delete",
    "publish",
    "unpublish",
    "install",
    "rate",
    "list-reviews",
    "create-review",
    "delete-own-review",
    "inspect-genome",
    "inspect-evolution",
  ]);
  assert.deepEqual(genes.permission_requirements, [
    {
      surface: "web",
      actions: [
        "view",
        "list",
        "inspect-genome",
        "inspect-evolution",
        "list-reviews",
      ],
      authentication: "authenticated",
      authorization: ["tenant_member"],
      enforcement: "enforced",
      feature_gate: null,
    },
    {
      surface: "web",
      actions: [
        "create",
        "update",
        "delete",
        "publish",
        "unpublish",
        "install",
      ],
      authentication: "authenticated",
      authorization: ["tenant_admin"],
      enforcement: "enforced",
      feature_gate: null,
    },
    {
      surface: "web",
      actions: ["rate", "create-review"],
      authentication: "authenticated",
      authorization: ["tenant_member"],
      enforcement: "enforced",
      feature_gate: null,
    },
    {
      surface: "web",
      actions: ["delete-own-review"],
      authentication: "authenticated",
      authorization: ["tenant_member", "resource_owner"],
      enforcement: "enforced",
      feature_gate: null,
    },
    {
      surface: "desktop_cloud",
      actions: [
        "view",
        "list",
        "rate",
        "create-review",
      ],
      authentication: "authenticated",
      authorization: ["tenant_member"],
      enforcement: "enforced",
      feature_gate: null,
    },
    {
      surface: "desktop_cloud",
      actions: ["delete-own-review"],
      authentication: "authenticated",
      authorization: ["tenant_member", "resource_owner"],
      enforcement: "enforced",
      feature_gate: null,
    },
    {
      surface: "desktop_cloud",
      actions: [
        "create",
        "update",
        "delete",
        "publish",
        "unpublish",
        "install",
      ],
      authentication: "authenticated",
      authorization: ["tenant_admin"],
      enforcement: "enforced",
      feature_gate: null,
    },
  ]);
});
