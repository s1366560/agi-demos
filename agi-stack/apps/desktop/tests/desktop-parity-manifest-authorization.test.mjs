import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { assertSurfacePermissionCoverage } from "../contracts/desktop-web-parity/parity-permission-coverage.mjs";
import { validateJsonSchema } from "../contracts/desktop-web-parity/schema-validator.mjs";

const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const generatorSource = readFileSync(
  new URL(
    "../contracts/desktop-web-parity/generate-parity-manifest-v2.mjs",
    import.meta.url,
  ),
  "utf8",
);

function readJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), "utf8"));
}

test("authorization predicates use a closed vocabulary without tightening legacy permissions", () => {
  const schema = readJson("parity-manifest.v2.schema.json");
  const expectedAuthorizationPredicates = [
    "global_admin",
    "tenant_member",
    "tenant_admin",
    "tenant_owner",
    "project_member",
    "project_contributor",
    "project_admin",
    "project_owner",
    "workspace_member",
    "workspace_editor",
    "workspace_manager",
    "workspace_owner",
    "conversation_access",
    "conversation_owner_or_project_owner",
    "memory_editor",
    "memory_admin",
    "resource_owner",
    "valid_invitation_token",
    "pending_device_code",
    "trusted-renderer-origin",
    "allowlisted-preload-bridge",
    "sidecar-control",
    "vault:use",
    "signed-production-package",
  ];

  assert.deepEqual(
    schema.$defs.authorizationPredicate.enum,
    expectedAuthorizationPredicates,
  );
  assert.deepEqual(
    schema.$defs.permissionRequirement.properties.authorization.items,
    { $ref: "#/$defs/authorizationPredicate" },
  );
  assert.deepEqual(
    schema.$defs.capability.properties.required_permissions.items,
    { $ref: "#/$defs/nonEmptyString" },
  );

  const requirementSchema = {
    $schema: schema.$schema,
    $defs: schema.$defs,
    $ref: "#/$defs/permissionRequirement",
  };
  const requirement = {
    surface: "web",
    actions: ["view"],
    authentication: "authenticated",
    authorization: ["tenant_member"],
    enforcement: "enforced",
    feature_gate: null,
  };
  assert.deepEqual(validateJsonSchema(requirementSchema, requirement), []);
  assert.equal(
    validateJsonSchema(requirementSchema, {
      ...requirement,
      authorization: ["tenant_member_for_read"],
    }).length > 0,
    true,
  );
  assert.deepEqual(
    validateJsonSchema(
      {
        $schema: schema.$schema,
        $defs: schema.$defs,
        type: "array",
        items: schema.$defs.capability.properties.required_permissions.items,
      },
      ["authenticated", "tenant_member_for_read"],
    ),
    [],
  );
});

test("all capability definitions declare reviewed authorization requirements explicitly", () => {
  const schema = readJson("parity-manifest.v2.schema.json");
  const allowedPredicates = new Set(schema.$defs.authorizationPredicate.enum);
  const fragmentRegistry = readJson("parity-capability-fragments.v2.json");
  const fragments = fragmentRegistry.fragments.map(readJson);
  let capabilityCount = 0;

  for (const fragment of fragments) {
    for (const capability of fragment.capabilities) {
      capabilityCount += 1;
      assert.equal(
        Object.hasOwn(capability, "permission_requirements"),
        true,
        capability.id,
      );
      assert.equal(
        capability.permission_requirements.length > 0,
        true,
        capability.id,
      );
      for (const requirement of capability.permission_requirements) {
        for (const predicate of requirement.authorization) {
          assert.equal(
            allowedPredicates.has(predicate),
            true,
            `${capability.id}: ${predicate}`,
          );
        }
      }
    }
  }

  assert.equal(capabilityCount, 66);
  assert.match(
    generatorSource,
    /must declare reviewed permission_requirements/u,
  );
  assert.doesNotMatch(generatorSource, /defaultPermissionRequirements/u);
  assert.doesNotMatch(generatorSource, /authorization:\s*\[\.\.\.declared\]/u);
});

test("every advertised surface action has an explicit permission requirement", () => {
  assert.match(generatorSource, /assertSurfacePermissionCoverage/u);
  const surfaces = {
    web: { allowed_actions: ["view"] },
    desktop_cloud: { allowed_actions: ["view", "update"] },
    desktop_local: { allowed_actions: [] },
    native_only: { allowed_actions: [] },
  };
  const permissionRequirements = [
    {
      surface: "web",
      actions: ["view"],
      authentication: "authenticated",
      authorization: ["tenant_member"],
      enforcement: "enforced",
      feature_gate: null,
    },
    {
      surface: "desktop_cloud",
      actions: ["view", "update"],
      authentication: "authenticated",
      authorization: ["tenant_admin"],
      enforcement: "enforced",
      feature_gate: null,
    },
  ];

  assert.doesNotThrow(() =>
    assertSurfacePermissionCoverage({
      capabilityId: "complete-capability",
      surfaces,
      permissionRequirements,
    }),
  );
  assert.throws(
    () =>
      assertSurfacePermissionCoverage({
        capabilityId: "incomplete-capability",
        surfaces,
        permissionRequirements: permissionRequirements.map((requirement) =>
          requirement.surface === "desktop_cloud"
            ? { ...requirement, actions: ["view"] }
            : requirement,
        ),
      }),
    /incomplete-capability\.desktop_cloud.*update/u,
  );
});

test("native-only permissions cover the same Electron boundary in both Desktop modes", () => {
  const nativeSurfaces = {
    web: { allowed_actions: [] },
    desktop_cloud: { allowed_actions: ["invoke"] },
    desktop_local: { allowed_actions: ["invoke"] },
    native_only: { allowed_actions: ["invoke"] },
  };
  const nativePermission = [
    {
      surface: "native_only",
      actions: ["invoke"],
      authentication: "native_shell",
      authorization: ["allowlisted_preload_bridge"],
      enforcement: "enforced",
      feature_gate: null,
    },
  ];

  assert.doesNotThrow(() =>
    assertSurfacePermissionCoverage({
      capabilityId: "native-boundary",
      capabilityKind: "native_only",
      surfaces: nativeSurfaces,
      permissionRequirements: nativePermission,
    }),
  );
  assert.throws(
    () =>
      assertSurfacePermissionCoverage({
        capabilityId: "ordinary-capability",
        capabilityKind: "canonical",
        surfaces: nativeSurfaces,
        permissionRequirements: nativePermission,
      }),
    /ordinary-capability\.desktop_cloud.*invoke/u,
  );
});
