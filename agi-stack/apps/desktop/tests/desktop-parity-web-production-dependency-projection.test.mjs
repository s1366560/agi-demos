import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  projectReviewedProductionDependencies,
  resolveReviewedProductionDependencies,
} from "../contracts/desktop-web-parity/web-production-dependency-projection.mjs";

const wrapper = "web/src/pages/project/CommunitiesList.tsx";
const implementation = "web/src/pages/project/communities/index.tsx";
const taskList = "web/src/components/tasks/TaskList.tsx";
const dependencyEdges = [
  {
    from_source_entry: wrapper,
    relationship: "re_export",
    to_source_entry: implementation,
  },
  {
    from_source_entry: implementation,
    relationship: "static_import",
    to_source_entry: taskList,
  },
];
const auditedSourceByEntry = new Map(
  [implementation, taskList].map((sourceEntry) => [
    sourceEntry,
    {
      roles: ["production_dependency"],
      sha256: `sha256:${"a".repeat(64)}`,
      source_entry: sourceEntry,
    },
  ]),
);
const productionInventory = JSON.parse(
  readFileSync(
    new URL(
      "../contracts/desktop-web-parity/web-route-inventory.v2.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

test("reviewed production dependencies resolve revision-bound direct and transitive paths", () => {
  assert.deepEqual(
    resolveReviewedProductionDependencies({
      auditedSourceByEntry,
      capabilityId: "project-project-communities",
      declarations: [
        {
          routed_source_entry: wrapper,
          source_entry: implementation,
        },
        {
          routed_source_entry: wrapper,
          source_entry: taskList,
        },
      ],
      dependencyEdges,
      kind: "canonical",
      routedSourceEntries: [wrapper],
    }),
    [
      {
        dependency_path: [dependencyEdges[0]],
        routed_source_entry: wrapper,
        source_entry: implementation,
      },
      {
        dependency_path: dependencyEdges,
        routed_source_entry: wrapper,
        source_entry: taskList,
      },
    ],
  );
});

test("production projection includes only routed and reviewed root-to-target path nodes", () => {
  const unrelated = "web/src/pages/project/Unrelated.tsx";
  assert.deepEqual(
    projectReviewedProductionDependencies({
      auditedSourceByEntry,
      capabilityId: "project-project-communities",
      declarations: [
        {
          routed_source_entry: wrapper,
          source_entry: taskList,
        },
      ],
      dependencyEdges: [
        ...dependencyEdges,
        {
          from_source_entry: wrapper,
          relationship: "static_import",
          to_source_entry: unrelated,
        },
      ],
      kind: "canonical",
      routedSourceEntries: [wrapper],
    }).productionSourceEntries,
    [taskList, wrapper, implementation].sort(),
  );
});

test("Communities production dependencies resolve against the checked-in revision-bound graph", () => {
  const projection = projectReviewedProductionDependencies({
    auditedSourceByEntry: new Map(
      productionInventory.audited_sources.map((source) => [
        source.source_entry,
        source,
      ]),
    ),
    capabilityId: "project-project-communities",
    declarations: [
      {
        routed_source_entry: wrapper,
        source_entry: implementation,
      },
      {
        routed_source_entry: wrapper,
        source_entry: taskList,
      },
    ],
    dependencyEdges: productionInventory.production_dependency_edges,
    kind: "canonical",
    routedSourceEntries: [wrapper],
  });

  assert.deepEqual(
    projection.productionSourceEntries,
    [implementation, taskList, wrapper].sort(),
  );
  assert.deepEqual(
    projection.reviewedDependencies.map((dependency) => [
      dependency.routed_source_entry,
      dependency.source_entry,
      dependency.dependency_path.map((edge) => edge.relationship),
    ]),
    [
      [wrapper, implementation, ["re_export"]],
      [wrapper, taskList, ["re_export", "static_import"]],
    ],
  );
  const auditedSources = new Map(
    productionInventory.audited_sources.map((source) => [
      source.source_entry,
      source,
    ]),
  );
  for (const sourceEntry of [implementation, taskList]) {
    const source = auditedSources.get(sourceEntry);
    assert.ok(source);
    assert.equal(source.roles.includes("production_dependency"), true);
    assert.match(source.sha256, /^sha256:[0-9a-f]{64}$/u);
  }
});

test("reviewed production dependencies reject unreachable or unaudited targets", () => {
  assert.throws(
    () =>
      resolveReviewedProductionDependencies({
        auditedSourceByEntry,
        capabilityId: "project-project-communities",
        declarations: [
          {
            routed_source_entry: wrapper,
            source_entry: "web/src/pages/project/Unrelated.tsx",
          },
        ],
        dependencyEdges,
        kind: "canonical",
        routedSourceEntries: [wrapper],
      }),
    /is not an audited production dependency/u,
  );
  assert.throws(
    () =>
      resolveReviewedProductionDependencies({
        auditedSourceByEntry,
        capabilityId: "project-project-communities",
        declarations: [
          {
            routed_source_entry: wrapper,
            source_entry: taskList,
          },
        ],
        dependencyEdges: [],
        kind: "canonical",
        routedSourceEntries: [wrapper],
      }),
    /is not reachable from routed source/u,
  );
});

test("reviewed production dependencies reject malformed, duplicate, and unknown-root declarations", () => {
  assert.throws(
    () =>
      resolveReviewedProductionDependencies({
        auditedSourceByEntry,
        capabilityId: "project-project-communities",
        declarations: {
          routed_source_entry: wrapper,
          source_entry: implementation,
        },
        dependencyEdges,
        kind: "canonical",
        routedSourceEntries: [wrapper],
      }),
    /must be an array/u,
  );

  const validDeclaration = {
    routed_source_entry: wrapper,
    source_entry: implementation,
  };
  const invalidCases = [
    {
      declarations: [implementation],
      pattern: /must be an exact record/u,
    },
    {
      declarations: [{ ...validDeclaration, rationale: "manual" }],
      pattern: /must contain exactly/u,
    },
    {
      declarations: [
        {
          routed_source_entry: "",
          source_entry: implementation,
        },
      ],
      pattern: /routed_source_entry must be a non-empty string/u,
    },
    {
      declarations: [
        {
          routed_source_entry: "web/src/pages/project/Unrelated.tsx",
          source_entry: implementation,
        },
      ],
      pattern: /is not a routed Web source/u,
    },
    {
      declarations: [validDeclaration, validDeclaration],
      pattern: /duplicates production dependency/u,
    },
  ];

  for (const invalidCase of invalidCases) {
    assert.throws(
      () =>
        resolveReviewedProductionDependencies({
          auditedSourceByEntry,
          capabilityId: "project-project-communities",
          declarations: invalidCase.declarations,
          dependencyEdges,
          kind: "canonical",
          routedSourceEntries: [wrapper],
        }),
      invalidCase.pattern,
    );
  }
});

test("native-only capabilities cannot claim Web production dependencies", () => {
  assert.deepEqual(
    resolveReviewedProductionDependencies({
      auditedSourceByEntry,
      capabilityId: "application-encrypted-vault",
      declarations: [],
      dependencyEdges,
      kind: "native_only",
      routedSourceEntries: [],
    }),
    [],
  );
  assert.throws(
    () =>
      resolveReviewedProductionDependencies({
        auditedSourceByEntry,
        capabilityId: "application-encrypted-vault",
        declarations: [
          {
            routed_source_entry: wrapper,
            source_entry: implementation,
          },
        ],
        dependencyEdges,
        kind: "native_only",
        routedSourceEntries: [],
      }),
    /cannot declare Web production dependencies/u,
  );
});

test("reviewed production dependencies remain many-to-many and separate from route ownership", () => {
  for (const capabilityId of [
    "project-project-communities",
    "project-project-maintenance",
  ]) {
    assert.equal(
      resolveReviewedProductionDependencies({
        auditedSourceByEntry,
        capabilityId,
        declarations: [
          {
            routed_source_entry: wrapper,
            source_entry: taskList,
          },
        ],
        dependencyEdges,
        kind: "canonical",
        routedSourceEntries: [wrapper],
      })[0].source_entry,
      taskList,
    );
  }
});
