import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:8000";
const FIXTURE_NAMES = Object.freeze([
  "Ariadne Vale",
  "Deterministic Graph Labs",
]);
const FIXTURE_CONTENT =
  "Ariadne Vale founded Deterministic Graph Labs. " +
  "Deterministic Graph Labs develops reproducible graph systems.";

test("Web and Desktop render one real Neo4j fixture with matched authority state", async ({
  browser,
  request,
}, testInfo) => {
  const evidenceRoot = resolve(String(testInfo.config.metadata.evidenceRoot));
  const webBaseURL = String(testInfo.config.metadata.webBaseURL);
  const desktopBaseURL = String(testInfo.config.metadata.desktopBaseURL);
  mkdirSync(evidenceRoot, { recursive: true, mode: 0o700 });

  const cleanup = [];
  let token = null;
  let projectId = null;
  let episodeName = null;
  try {
    token = await authenticate(request);
    const user = await loadCurrentUser(request, token);
    const tenantId = await loadFirstTenantId(request, token);
    projectId = await createProject(request, token, tenantId);
    episodeName = `neo4j-ui-${randomUUID()}`;
    const episodeId = await createEpisode(
      request,
      token,
      projectId,
      episodeName,
    );
    await waitForSyncedEpisode(request, token, episodeName);
    await rebuildCommunities(request, token, projectId);

    const fixture = await loadFixtureSnapshot(
      request,
      token,
      tenantId,
      projectId,
    );
    writeJson(evidenceRoot, "fixture-scope.json", {
      tenant_id: tenantId,
      project_id: projectId,
      episode_id: episodeId,
      episode_name: episodeName,
      entity_ids: fixture.entities.ids,
      community_ids: fixture.communities.ids,
      graph_node_ids: fixture.graph.ids,
      search_result_ids: fixture.search.ids,
    });

    const webContext = await browser.newContext({
      colorScheme: "light",
      locale: "en-US",
      viewport: { width: 1440, height: 900 },
    });
    const desktopContext = await browser.newContext({
      colorScheme: "light",
      locale: "en-US",
      viewport: { width: 1440, height: 900 },
    });

    try {
      const webPage = await webContext.newPage();
      const desktopPage = await desktopContext.newPage();
      await Promise.all([
        installApiOriginRewrite(webPage),
        installApiOriginRewrite(desktopPage),
      ]);
      await primeWebSession(webPage, token, user);
      await primeDesktopPreferences(desktopPage);
      await authenticateDesktop(desktopPage, desktopBaseURL);

      const expectedScope = Object.freeze({ tenantId, projectId });
      const webTracker = createKnowledgeTracker(webPage, "web", expectedScope);
      const desktopTracker = createKnowledgeTracker(
        desktopPage,
        "desktop",
        expectedScope,
      );
      try {
        const webRecords = await exerciseWeb(
          webPage,
          webTracker,
          webBaseURL,
          evidenceRoot,
          expectedScope,
          fixture,
        );
        const desktopRecords = await exerciseDesktop(
          desktopPage,
          desktopTracker,
          evidenceRoot,
          expectedScope,
          fixture,
        );
        const comparisons = compareMatchedState(webRecords, desktopRecords);
        const networkEvidence = {
          scope: { tenant_id: tenantId, project_id: projectId },
          comparisons,
          web: webRecords,
          desktop: desktopRecords,
        };
        const serializedEvidence = JSON.stringify(networkEvidence);
        expect(serializedEvidence).not.toContain("Authorization");
        expect(serializedEvidence).not.toContain("Bearer ");
        expect(serializedEvidence).not.toContain(token);
        writeJson(evidenceRoot, "matched-state-network.json", networkEvidence);
        captureNeo4jQueryEvidence(evidenceRoot, projectId);
      } finally {
        webTracker.dispose();
        desktopTracker.dispose();
      }
    } finally {
      await Promise.allSettled([webContext.close(), desktopContext.close()]);
    }
  } finally {
    if (token && episodeName) {
      try {
        const response = await request.delete(
          `${API_BASE}/api/v1/episodes/by-name/${encodeURIComponent(episodeName)}`,
          { headers: authorizationHeaders(token) },
        );
        cleanup.push({ resource: "episode", status: response.status() });
      } catch {
        cleanup.push({ resource: "episode", status: "request_failed" });
      }
    }
    if (token && projectId) {
      try {
        const graphCleanup = cleanupNeo4jProject(projectId);
        cleanup.push({
          resource: "neo4j_project",
          status: 204,
          ...graphCleanup,
        });
      } catch {
        cleanup.push({ resource: "neo4j_project", status: "request_failed" });
      }
      try {
        const response = await request.delete(
          `${API_BASE}/api/v1/projects/${projectId}`,
          {
            headers: authorizationHeaders(token),
          },
        );
        cleanup.push({ resource: "project", status: response.status() });
      } catch {
        cleanup.push({ resource: "project", status: "request_failed" });
      }
    }
    writeJson(evidenceRoot, "cleanup.json", cleanup);
    expect(
      cleanup.filter(
        ({ status }) =>
          typeof status !== "number" || status < 200 || status >= 300,
      ),
      "The matched-state fixture must be fully deleted",
    ).toEqual([]);
  }
});

async function authenticate(request) {
  const response = await request.post(`${API_BASE}/api/v1/auth/token`, {
    form: { username: "admin@memstack.ai", password: "adminpassword" },
  });
  const payload = await requireJsonResponse(response, "authenticate admin");
  expect(
    payload.access_token,
    "Authentication must return an access token",
  ).toEqual(expect.any(String));
  return payload.access_token;
}

async function loadCurrentUser(request, token) {
  const response = await request.get(`${API_BASE}/api/v1/auth/me`, {
    headers: authorizationHeaders(token),
  });
  return requireJsonResponse(response, "load current user");
}

async function loadFirstTenantId(request, token) {
  const response = await request.get(`${API_BASE}/api/v1/tenants/`, {
    headers: authorizationHeaders(token),
  });
  const payload = await requireJsonResponse(response, "load tenants");
  const tenants = Array.isArray(payload) ? payload : payload.tenants;
  expect(
    Array.isArray(tenants),
    "Tenant response must contain a tenant collection",
  ).toBeTruthy();
  const tenantId = tenants[0]?.id;
  expect(
    tenantId,
    "The Neo4j matched-state test requires an admin tenant",
  ).toEqual(expect.any(String));
  return tenantId;
}

async function createProject(request, token, tenantId) {
  const response = await request.post(`${API_BASE}/api/v1/projects/`, {
    headers: authorizationHeaders(token),
    data: {
      name: `Neo4j Matched State ${randomUUID().slice(0, 8)}`,
      description: "Deterministic Web and Desktop Neo4j matched-state fixture",
      tenant_id: tenantId,
      is_public: false,
    },
  });
  const payload = await requireJsonResponse(
    response,
    "create matched-state project",
  );
  const projectId = payload.project?.id ?? payload.id;
  expect(projectId, "Project creation must return an id").toEqual(
    expect.any(String),
  );
  return projectId;
}

async function createEpisode(request, token, projectId, episodeName) {
  const response = await request.post(`${API_BASE}/api/v1/episodes/`, {
    headers: authorizationHeaders(token),
    data: {
      name: episodeName,
      content: FIXTURE_CONTENT,
      project_id: projectId,
    },
  });
  expect(
    response.status(),
    "Episode ingest must preserve the accepted contract",
  ).toBe(202);
  const payload = await requireJsonResponse(
    response,
    "create matched-state episode",
  );
  expect(payload.id, "Episode creation must return an id").toEqual(
    expect.any(String),
  );
  return payload.id;
}

async function waitForSyncedEpisode(request, token, episodeName) {
  let observedStatus = null;
  await expect
    .poll(
      async () => {
        const response = await request.get(
          `${API_BASE}/api/v1/episodes/by-name/${encodeURIComponent(episodeName)}`,
          { headers: authorizationHeaders(token) },
        );
        if (!response.ok()) return `http_${response.status()}`;
        const payload = await response.json();
        observedStatus = payload.status ?? null;
        return observedStatus;
      },
      { timeout: 60_000, intervals: [250, 500, 1_000] },
    )
    .toBe("Synced");
  return observedStatus;
}

async function rebuildCommunities(request, token, projectId) {
  const url = new URL("/api/v1/graph/communities/rebuild", API_BASE);
  url.searchParams.set("project_id", projectId);
  url.searchParams.set("background", "false");
  const response = await request.post(url.toString(), {
    headers: authorizationHeaders(token),
  });
  const payload = await requireJsonResponse(response, "rebuild communities");
  expect(payload.status).toBe("success");
  expect(payload.communities_count).toBeGreaterThan(0);
}

async function loadFixtureSnapshot(request, token, tenantId, projectId) {
  const headers = authorizationHeaders(token);
  const scope = `tenant_id=${encodeURIComponent(tenantId)}&project_id=${encodeURIComponent(projectId)}`;
  const [entitiesResponse, communitiesResponse, graphResponse, searchResponse] =
    await Promise.all([
      request.get(
        `${API_BASE}/api/v1/graph/entities/?${scope}&limit=50&offset=0`,
        { headers },
      ),
      request.get(
        `${API_BASE}/api/v1/graph/communities/?${scope}&limit=50&offset=0`,
        { headers },
      ),
      request.get(`${API_BASE}/api/v1/graph/memory/graph?${scope}&limit=1000`, {
        headers,
      }),
      request.post(`${API_BASE}/api/v1/search-enhanced/advanced`, {
        headers,
        data: {
          query: FIXTURE_NAMES[0],
          strategy: "COMBINED_HYBRID_SEARCH_RRF",
          limit: 50,
          tenant_id: tenantId,
          project_id: projectId,
        },
      }),
    ]);
  const entities = summarizeResponse(
    "entities",
    await requireJsonResponse(entitiesResponse, "load entities"),
  );
  const communities = summarizeResponse(
    "communities",
    await requireJsonResponse(communitiesResponse, "load communities"),
  );
  const graph = summarizeResponse(
    "graph",
    await requireJsonResponse(graphResponse, "load graph"),
  );
  const search = summarizeResponse(
    "search",
    await requireJsonResponse(searchResponse, "run advanced search"),
  );
  expect(entities.fixture_matches).toEqual(
    expect.arrayContaining(FIXTURE_NAMES),
  );
  expect(graph.fixture_matches).toEqual(expect.arrayContaining(FIXTURE_NAMES));
  expect(search.fixture_matches.length).toBeGreaterThan(0);
  expect(communities.ids.length).toBeGreaterThan(0);
  return Object.freeze({ entities, communities, graph, search });
}

async function primeWebSession(page, token, user) {
  const authStorage = {
    state: {
      user: {
        id: user.user_id ?? user.id,
        email: user.email,
        name: user.name,
        roles: user.roles,
        is_active: user.is_active,
        created_at: user.created_at,
        profile: user.profile,
        preferred_language: user.preferred_language ?? "en-US",
      },
      token,
      isAuthenticated: true,
    },
    version: 0,
  };
  await page.addInitScript((storage) => {
    window.localStorage.setItem(
      "memstack-auth-storage",
      JSON.stringify(storage),
    );
    window.localStorage.setItem("i18nextLng", "en-US");
    window.localStorage.setItem("memstack_onboarding_complete", "true");
    window.localStorage.setItem(
      "theme-storage",
      JSON.stringify({
        state: { theme: "light", computedTheme: "light" },
        version: 0,
      }),
    );
  }, authStorage);
}

async function primeDesktopPreferences(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("agistack.desktop.locale", "en");
    window.localStorage.setItem("agistack.desktop.theme", "light");
    window.localStorage.setItem(
      "agistack.desktop.login-mode",
      JSON.stringify({ version: 1, mode: "cloud" }),
    );
  });
}

async function installApiOriginRewrite(page) {
  const targetOrigin = new URL(API_BASE).origin;
  if (targetOrigin === "http://127.0.0.1:8000") return;
  await page.route("**/api/v1/**", async (route) => {
    const source = new URL(route.request().url());
    if (source.origin === targetOrigin) {
      await route.fallback();
      return;
    }
    const target = new URL(
      `${source.pathname}${source.search}`,
      `${targetOrigin}/`,
    );
    const response = await route.fetch({ url: target.toString() });
    await route.fulfill({ response });
  });
}

async function authenticateDesktop(page, desktopBaseURL) {
  const response = await page.goto(desktopBaseURL, {
    waitUntil: "domcontentloaded",
  });
  expect(response?.status()).toBeLessThan(400);
  const login = page.locator(".desktop-login-card");
  await expect(login).toBeVisible();
  await login
    .locator('[data-parity-target-id="email_entry"]')
    .fill("admin@memstack.ai");
  await login.locator('input[type="password"]').fill("adminpassword");
  await login.locator(".desktop-login-submit").click();
  await expect(page.locator(".desktop-login-screen")).toHaveCount(0, {
    timeout: 20_000,
  });
}

async function exerciseWeb(
  page,
  tracker,
  baseURL,
  evidenceRoot,
  scope,
  fixture,
) {
  const records = {};
  for (const kind of ["entities", "communities", "graph", "search"]) {
    const path = canonicalPath(
      scope,
      kind === "search" ? "advanced-search" : kind,
    );
    const startIndex = tracker.recordCount();
    await page.goto(`${baseURL}${path}`, { waitUntil: "domcontentloaded" });
    await assertWebSurface(page, kind, fixture);
    records[kind] = await tracker.waitFor(kind, startIndex);
    assertNetworkRecord(records[kind], kind, scope, fixture[kind]);
    await page.screenshot({
      path: resolve(evidenceRoot, `web-${kind}.png`),
      fullPage: true,
    });
  }
  return records;
}

async function assertWebSurface(page, kind, fixture) {
  if (kind === "entities") {
    await expect(page.getByTestId("entities-header")).toBeVisible();
    for (const name of FIXTURE_NAMES)
      await expect(page.getByText(name).first()).toBeVisible();
    return;
  }
  if (kind === "communities") {
    await expect(page.getByTestId("communities-list-root")).toBeVisible();
    await expect(
      page.getByText(fixture.communities.names[0]).first(),
    ).toBeVisible();
    return;
  }
  if (kind === "graph") {
    await expect(page.getByTestId("memory-graph-page")).toBeVisible();
    const accessibleGraph = page.locator(
      '[aria-label="Accessible graph data"]',
    );
    await expect(accessibleGraph).toContainText(FIXTURE_NAMES[0]);
    await expect(accessibleGraph).toContainText(FIXTURE_NAMES[1]);
    return;
  }
  const input = page.locator('input[type="search"][name="search"]');
  await expect(input).toBeVisible();
  await input.fill(FIXTURE_NAMES[0]);
  await page.getByRole("button", { name: /Retrieve/i }).click();
  await expect(
    page.getByText(fixture.search.fixture_matches[0]).first(),
  ).toBeVisible();
}

async function exerciseDesktop(page, tracker, evidenceRoot, scope, fixture) {
  const records = {};
  for (const kind of ["entities", "communities", "graph", "search"]) {
    const suffix = kind === "search" ? "advanced-search" : kind;
    const routeId =
      kind === "search" ? "project-project-search" : `project-project-${kind}`;
    const startIndex = tracker.recordCount();
    await page.evaluate(
      (path) => {
        window.location.hash = path;
      },
      canonicalPath(scope, suffix),
    );
    const stage = page.locator(
      `.desktop-production-route-stage[data-route-id="${routeId}"]`,
    );
    await expect(stage).toBeVisible();
    if (kind === "search") {
      await stage
        .locator('[data-action="search-query"]')
        .fill(FIXTURE_NAMES[0]);
      await stage.locator('[data-action="search-submit"]').click();
      await expect(
        stage.getByText(fixture.search.fixture_matches[0]).first(),
      ).toBeVisible();
    } else if (kind === "communities") {
      await expect(
        stage.getByText(fixture.communities.names[0]).first(),
      ).toBeVisible();
    } else {
      for (const name of FIXTURE_NAMES)
        await expect(stage.getByText(name).first()).toBeVisible();
    }
    records[kind] = await tracker.waitFor(kind, startIndex);
    assertNetworkRecord(records[kind], kind, scope, fixture[kind]);
    await page.screenshot({
      path: resolve(evidenceRoot, `desktop-${kind}.png`),
      fullPage: true,
    });
  }
  return records;
}

function createKnowledgeTracker(page, surface, expectedScope) {
  const records = [];
  const pending = new Set();
  const onResponse = (response) => {
    const kind = knowledgeResponseKind(response);
    if (!kind) return;
    const task = (async () => {
      const request = response.request();
      const url = new URL(request.url());
      const requestBody = parseRequestBody(request.postData());
      const responseBody = await response.json().catch(() => null);
      records.push({
        surface,
        kind,
        endpoint: url.pathname,
        method: request.method(),
        status: response.status(),
        canonical_scope: {
          tenant_id: expectedScope.tenantId,
          project_id: expectedScope.projectId,
        },
        request_scope: {
          tenant_id:
            url.searchParams.get("tenant_id") ?? requestBody?.tenant_id ?? null,
          project_id:
            url.searchParams.get("project_id") ??
            requestBody?.project_id ??
            null,
        },
        response: summarizeResponse(kind, responseBody),
      });
    })();
    pending.add(task);
    void task.finally(() => pending.delete(task));
  };
  page.on("response", onResponse);
  return Object.freeze({
    dispose() {
      page.off("response", onResponse);
    },
    recordCount() {
      return records.length;
    },
    async waitFor(kind, startIndex) {
      await expect
        .poll(
          () =>
            records.slice(startIndex).find((record) => record.kind === kind) ??
            null,
        )
        .not.toBeNull();
      await Promise.all([...pending]);
      return records.slice(startIndex).find((record) => record.kind === kind);
    },
  });
}

function knowledgeResponseKind(response) {
  const request = response.request();
  const path = new URL(request.url()).pathname;
  if (request.method() === "GET" && path === "/api/v1/graph/entities/")
    return "entities";
  if (request.method() === "GET" && path === "/api/v1/graph/communities/")
    return "communities";
  if (request.method() === "GET" && path === "/api/v1/graph/memory/graph")
    return "graph";
  if (
    request.method() === "POST" &&
    path === "/api/v1/search-enhanced/advanced"
  )
    return "search";
  return null;
}

function summarizeResponse(kind, payload) {
  const values =
    kind === "entities"
      ? payload?.entities
      : kind === "communities"
        ? payload?.communities
        : kind === "graph"
          ? payload?.elements?.nodes
          : payload?.results;
  const items = Array.isArray(values) ? values : [];
  const ids = items.map(resultIdentity).filter(Boolean).sort();
  const names = items.map(resultName).filter(Boolean).sort();
  const serialized = JSON.stringify(payload ?? null);
  const fixtureMatches = FIXTURE_NAMES.filter((name) =>
    serialized.includes(name),
  );
  return Object.freeze({ ids, names, fixture_matches: fixtureMatches });
}

function resultIdentity(item) {
  return (
    item?.uuid ?? item?.id ?? item?.data?.id ?? item?.metadata?.uuid ?? null
  );
}

function resultName(item) {
  return item?.name ?? item?.data?.name ?? item?.metadata?.name ?? null;
}

function parseRequestBody(value) {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function assertNetworkRecord(record, kind, scope, fixtureSummary) {
  expect(
    record,
    `${kind} must produce a captured network response`,
  ).toBeTruthy();
  expect(record.status, `${kind} network response must succeed`).toBe(200);
  expect(
    record.request_scope.project_id,
    `${kind} request must carry project scope`,
  ).toBe(scope.projectId);
  if (record.request_scope.tenant_id !== null) {
    expect(
      record.request_scope.tenant_id,
      `${kind} tenant scope must not drift`,
    ).toBe(scope.tenantId);
  }
  expect(record.response.ids).toEqual(fixtureSummary.ids);
}

function compareMatchedState(webRecords, desktopRecords) {
  return Object.fromEntries(
    ["entities", "communities", "graph", "search"].map((kind) => {
      expect(
        desktopRecords[kind].response.ids,
        `${kind} response ids must match Web`,
      ).toEqual(webRecords[kind].response.ids);
      return [
        kind,
        {
          status: "passed",
          web_status: webRecords[kind].status,
          desktop_status: desktopRecords[kind].status,
          matched_ids: webRecords[kind].response.ids,
        },
      ];
    }),
  );
}

function captureNeo4jQueryEvidence(evidenceRoot, projectId) {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(projectId)) {
    throw new Error(
      "Neo4j evidence project id contains unsupported characters",
    );
  }
  const container =
    process.env.NEO4J_RUNTIME_CONTAINER ?? "memstack-neo4j-runtime";
  const user = process.env.NEO4J_USER;
  const password = process.env.NEO4J_PASSWORD;
  if (!user || !password)
    throw new Error("Neo4j query evidence credentials are unavailable");
  const query =
    `MATCH (n) WHERE n.project_id = '${projectId}' ` +
    "RETURN labels(n) AS labels, coalesce(n.uuid, n.id, '') AS id, " +
    "coalesce(n.name, '') AS name ORDER BY name";
  const output = execFileSync(
    "docker",
    [
      "exec",
      container,
      "cypher-shell",
      "-u",
      user,
      "-p",
      password,
      "--format",
      "plain",
      query,
    ],
    { encoding: "utf8", timeout: 30_000 },
  );
  for (const name of FIXTURE_NAMES) expect(output).toContain(name);
  writeJson(evidenceRoot, "neo4j-query.json", {
    project_id: projectId,
    query,
    output,
  });
}

function cleanupNeo4jProject(projectId) {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(projectId)) {
    throw new Error("Neo4j cleanup project id contains unsupported characters");
  }
  const container =
    process.env.NEO4J_RUNTIME_CONTAINER ?? "memstack-neo4j-runtime";
  const user = process.env.NEO4J_USER;
  const password = process.env.NEO4J_PASSWORD;
  if (!user || !password)
    throw new Error("Neo4j cleanup credentials are unavailable");
  const runQuery = (query) =>
    execFileSync(
      "docker",
      [
        "exec",
        container,
        "cypher-shell",
        "-u",
        user,
        "-p",
        password,
        "--format",
        "plain",
        query,
      ],
      { encoding: "utf8", timeout: 30_000 },
    );
  const deleteOutput = runQuery(
    `MATCH (n) WHERE n.project_id = '${projectId}' ` +
      "WITH collect(n) AS nodes, count(n) AS deleted " +
      "FOREACH (n IN nodes | DETACH DELETE n) RETURN deleted",
  );
  const countOutput = runQuery(
    `MATCH (n) WHERE n.project_id = '${projectId}' RETURN count(n) AS remaining`,
  );
  const deleted = parseLastInteger(deleteOutput, "deleted graph node count");
  const remaining = parseLastInteger(countOutput, "remaining graph node count");
  expect(
    remaining,
    "Matched-state graph cleanup must remove every project-scoped node",
  ).toBe(0);
  return { deleted, remaining };
}

function parseLastInteger(output, description) {
  const lines = output.trim().split(/\r?\n/u);
  const value = Number(lines.at(-1));
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`Neo4j did not return a valid ${description}`);
  }
  return value;
}

function canonicalPath(scope, suffix) {
  return `/tenant/${encodeURIComponent(scope.tenantId)}/project/${encodeURIComponent(
    scope.projectId,
  )}/${suffix}`;
}

function authorizationHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

async function requireJsonResponse(response, action) {
  const body = await response.text();
  expect(
    response.ok(),
    `${action} failed with HTTP ${response.status()}`,
  ).toBeTruthy();
  return JSON.parse(body);
}

function writeJson(root, name, value) {
  writeFileSync(resolve(root, name), `${JSON.stringify(value, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
}
