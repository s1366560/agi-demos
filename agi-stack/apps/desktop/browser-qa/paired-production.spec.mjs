import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { arch, platform, release } from "node:os";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import {
  buildPairedEvidenceCases,
  createPairedAttemptEvidence,
  createPairedEvidenceMetadata,
  createPairedEvidenceRun,
  pairedFailureDomainForPhase,
} from "./paired-production-evidence.mjs";
import {
  serializePairedRendererBuildReceipt,
  validatePairedRendererBuildReceipt,
} from "./production-renderer-build-attestation.mjs";
import { createVisualDiff } from "./paired-visual-diff.mjs";
import {
  inspectEvidenceRepositoryBinding,
} from "../contracts/desktop-web-parity/evidence-run-validator.mjs";
import { validateEvidencePacket } from "../contracts/desktop-web-parity/paired-evidence-packet-validator.mjs";

const matrix = JSON.parse(
  readFileSync(
    new URL("./paired-production.matrix.v1.json", import.meta.url),
    "utf8",
  ),
);
const desiredContractBytes = readFileSync(
  new URL(
    "../contracts/desktop-web-parity/parity-manifest.v2.json",
    import.meta.url,
  ),
);
const desiredContract = JSON.parse(desiredContractBytes.toString("utf8"));
const pairedCases = buildPairedEvidenceCases(matrix, desiredContract);
const evidenceRunSchemaBytes = readFileSync(
  new URL(
    "../contracts/desktop-web-parity/evidence-run.v1.schema.json",
    import.meta.url,
  ),
);
const evidenceRunSchemaSha256 = createHash("sha256")
  .update(evidenceRunSchemaBytes)
  .digest("hex");
const sourceRevision = process.env.AGISTACK_PAIRED_SOURCE_REVISION;
if (!sourceRevision || !/^[0-9a-f]{40}$/u.test(sourceRevision)) {
  throw new Error(
    "AGISTACK_PAIRED_SOURCE_REVISION must pin this evidence run to one commit",
  );
}
const repositoryRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const webDistRoot = fileURLToPath(
  new URL("../../../../web/dist/", import.meta.url),
);
const desktopRendererRoot = fileURLToPath(
  new URL("../out/renderer/", import.meta.url),
);
const contractRelativePath =
  "agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v2.json";
const repositoryBinding = inspectEvidenceRepositoryBinding({
  repositoryRoot,
  contractRelativePath,
});
const rendererBuildReceiptPath =
  process.env.AGISTACK_PAIRED_BUILD_RECEIPT;
const invocationNonce = process.env.AGISTACK_PAIRED_INVOCATION_NONCE;
if (
  !rendererBuildReceiptPath ||
  !/^[0-9a-f]{64}$/u.test(invocationNonce ?? "")
) {
  throw new Error(
    "AGISTACK_PAIRED_BUILD_RECEIPT and AGISTACK_PAIRED_INVOCATION_NONCE are required",
  );
}
const rendererBuildReceiptBytes = readFileSync(rendererBuildReceiptPath);
const rendererBuildReceipt = JSON.parse(
  rendererBuildReceiptBytes.toString("utf8"),
);
const rendererBuildReceiptErrors = validatePairedRendererBuildReceipt(
  rendererBuildReceipt,
  {
    expectedSourceRevision: sourceRevision,
    expectedInvocationNonce: invocationNonce,
    repositoryRoot,
    webRoot: webDistRoot,
    desktopRendererRoot,
    now: Date.now(),
  },
);
if (rendererBuildReceiptErrors.length > 0) {
  throw new Error(
    `fresh renderer build receipt is invalid: ${rendererBuildReceiptErrors.join("; ")}`,
  );
}
if (
  !serializePairedRendererBuildReceipt(rendererBuildReceipt).equals(
    rendererBuildReceiptBytes,
  )
) {
  throw new Error("renderer build receipt must use canonical serialization");
}
const webBaseURL = `http://127.0.0.1:${process.env.AGISTACK_PAIRED_WEB_PORT ?? 5191}`;
const desktopBaseURL = `http://127.0.0.1:${process.env.AGISTACK_PAIRED_DESKTOP_PORT ?? 5192}`;
const worktreeState = repositoryBinding.worktreeState;
const rustVersion = execFileSync("rustc", ["--version"], {
  encoding: "utf8",
}).trim();

function registerRuntimeDiagnostics(page, runtimeErrors, runtime) {
  page.on("pageerror", (error) => {
    runtimeErrors.push({
      runtime,
      channel: "pageerror",
      message: error.message,
    });
  });
  page.on("console", (message) => {
    if (message.type() === "error") {
      runtimeErrors.push({
        runtime,
        channel: "console",
        message: message.text(),
      });
    }
  });
}

async function applyMatchedState(page, matchedState) {
  await page.addInitScript(({ locale, theme }) => {
    try {
      localStorage.setItem("agistack.desktop.locale", locale);
      localStorage.setItem("agistack.desktop.theme", theme);
      localStorage.setItem("i18nextLng", locale);
      localStorage.setItem(
        "theme-storage",
        JSON.stringify({
          state: { theme, computedTheme: theme },
          version: 0,
        }),
      );
    } catch {
      // Storage can be unavailable before an origin is committed.
    }
  }, matchedState);
}

function assertSupportedMatchedState(matchedState) {
  const supported =
    matchedState.authentication_state === "signed_out" &&
    matchedState.account_state === "none" &&
    matchedState.permission_state === "public_entry_only" &&
    matchedState.data_state === "empty" &&
    matchedState.interaction_state === "focused:email_entry";
  if (!supported) {
    throw new Error(
      "Paired production scenario declares state without an implemented state driver",
    );
  }
}

async function assertMeaningfulProductionPage(
  page,
  expectedPath,
  expectedReady,
) {
  await expect.poll(() => new URL(page.url()).pathname).toBe(expectedPath);
  await expect(page.locator("#root")).not.toBeEmpty();
  await expect(
    page.locator(".app-fatal-error, vite-error-overlay"),
  ).toHaveCount(0);
  await expect.poll(() => page.title()).not.toBe("");
  const readyLandmark = page.getByRole(expectedReady.role, {
    name: expectedReady.name,
    exact: true,
  });
  await expect(readyLandmark).toHaveCount(1);
  await expect(readyLandmark).toBeVisible();
}

function matchedFocusLocator(page, focus) {
  return page.getByRole(focus.role, {
    name: focus.name,
    exact: true,
  });
}

async function driveMatchedInteractionState(page, matchedState, focus) {
  if (matchedState.interaction_state !== "focused:email_entry") {
    throw new Error(
      "Paired production interaction state does not have a deterministic driver",
    );
  }
  const focusTarget = matchedFocusLocator(page, focus);
  await expect(focusTarget).toHaveCount(1);
  await focusTarget.focus();
  await expect(focusTarget).toBeFocused();
}

async function observeFinalMatchedState(page, probe) {
  return page.evaluate(
    ({
      rootSelector,
      stateAttributes,
      focusTargetAttribute,
      documentTheme,
    }) => {
      const matchingRoots = document.querySelectorAll(rootSelector);
      if (matchingRoots.length !== 1) {
        throw new Error(
          `parity probe expected one root but observed ${matchingRoots.length}`,
        );
      }
      const root = matchingRoots[0];
      const structuredState = {};
      for (const [stateKey, attributeName] of Object.entries(
        stateAttributes,
      )) {
        const value = root.getAttribute(attributeName);
        if (!value) {
          throw new Error(
            `parity probe is missing ${attributeName} for ${stateKey}`,
          );
        }
        structuredState[stateKey] = value;
      }
      const documentRoot = document.documentElement;
      const themeAttribute = documentRoot.getAttribute(
        documentTheme.attribute,
      );
      const themeTokens = (themeAttribute ?? "")
        .split(/\s+/u)
        .filter(Boolean);
      let theme;
      if (themeTokens.includes(documentTheme.darkToken)) {
        theme = "dark";
      } else if (
        documentTheme.lightToken &&
        themeTokens.includes(documentTheme.lightToken)
      ) {
        theme = "light";
      } else if (
        documentTheme.lightWhenTokenAbsent &&
        !themeTokens.includes(documentTheme.darkToken)
      ) {
        theme = "light";
      } else {
        throw new Error("document theme probe did not resolve");
      }
      if (!document.documentElement.lang) {
        throw new Error("document language probe is missing");
      }
      const activeElement = document.activeElement;
      const focusTargetId =
        activeElement?.getAttribute(focusTargetAttribute) ?? "";
      if (!focusTargetId) {
        throw new Error("active element has no parity target id");
      }
      return {
        locale: document.documentElement.lang,
        locale_rendering: {
          date_sample: new Intl.DateTimeFormat(document.documentElement.lang, {
            dateStyle: "full",
            timeZone: "UTC",
          }).format(new Date(Date.UTC(2020, 0, 2))),
          number_sample: new Intl.NumberFormat(
            document.documentElement.lang,
          ).format(1234567.89),
        },
        theme,
        browser_color_scheme: window.matchMedia("(prefers-color-scheme: dark)")
          .matches
          ? "dark"
          : "light",
        viewport: {
          width: window.innerWidth,
          height: window.innerHeight,
        },
        device_scale_factor: window.devicePixelRatio,
        ...structuredState,
        interaction_state: `focused:${focusTargetId}`,
        focus: {
          target_id: focusTargetId,
          tag_name: activeElement?.tagName.toLowerCase() ?? "none",
          input_type:
            activeElement instanceof HTMLInputElement
              ? activeElement.type
              : "not_applicable",
        },
      };
    },
    probe,
  );
}

function diagnosticForError(error) {
  if (error instanceof Error) {
    return {
      runtime: "runner",
      channel: error.name || "Error",
      message: error.message || "Unknown paired production failure",
    };
  }
  return {
    runtime: "runner",
    channel: "NonError",
    message: String(error),
  };
}

for (const pairedCase of pairedCases) {
  test(pairedCase.id, async ({ browser }, testInfo) => {
    const browserStartedAt = new Date().toISOString();
    const matchedState = pairedCase.web.matchedState;
    assertSupportedMatchedState(matchedState);
    mkdirSync(testInfo.outputDir, { recursive: true });
    const attemptOutputPath = testInfo.outputPath("attempt-evidence.json");
    const evidenceRunOutputPath = testInfo.outputPath("evidence-run.json");
    let phase = "initialize";
    let webContext;
    let desktopContext;
    let finalObservedState = null;
    let metadata = null;
    let declaredArtifacts = null;
    let browserObservationStatus = "not_run";
    const runtimeErrors = [];
    const environment = {
      host_os: platform(),
      host_os_version: release(),
      architecture: arch(),
      execution_context: process.env.CI ? "ci" : "local",
      sandboxed: process.env.AGISTACK_PAIRED_SANDBOXED === "true",
      locale: matchedState.locale,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      dependency_versions: {
        node: process.version,
        pnpm: rendererBuildReceipt.toolchain.desktop_pnpm,
        rustc: rustVersion,
        electron: rendererBuildReceipt.toolchain.electron,
      },
    };
    const writeAttemptEvidence = ({
      status,
      completedAt,
      diagnostics,
      failureDomain = null,
    }) => {
      const attemptEvidence = createPairedAttemptEvidence({
        scenarioId: pairedCase.id,
        capabilityId: pairedCase.capabilityId,
        sourceRevision,
        attemptIndex: testInfo.retry,
        status,
        startedAt: browserStartedAt,
        completedAt,
        phase,
        failureDomain,
        diagnostics,
        finalObservedState,
      });
      writeFileSync(
        attemptOutputPath,
        Buffer.from(`${JSON.stringify(attemptEvidence, null, 2)}\n`),
      );
    };
    writeAttemptEvidence({
      status: "running",
      completedAt: null,
      diagnostics: [],
    });

    const contextOptions = {
      locale: matchedState.locale,
      colorScheme: matchedState.theme,
      viewport: matchedState.viewport,
      deviceScaleFactor: matchedState.device_scale_factor,
    };
    try {
      phase = "create-contexts";
      [webContext, desktopContext] = await Promise.all([
        browser.newContext(contextOptions),
        browser.newContext(contextOptions),
      ]);
      const [webPage, desktopPage] = await Promise.all([
        webContext.newPage(),
        desktopContext.newPage(),
      ]);
      registerRuntimeDiagnostics(webPage, runtimeErrors, "web");
      registerRuntimeDiagnostics(desktopPage, runtimeErrors, "desktop");
      await Promise.all([
        applyMatchedState(webPage, matchedState),
        applyMatchedState(desktopPage, matchedState),
      ]);

      phase = "navigate";
      const [webResponse, desktopResponse] = await Promise.all([
        webPage.goto(new URL(pairedCase.web.path, webBaseURL).href, {
          waitUntil: "domcontentloaded",
        }),
        desktopPage.goto(
          new URL(pairedCase.desktop.path, desktopBaseURL).href,
          {
            waitUntil: "domcontentloaded",
          },
        ),
      ]);
      expect(webResponse?.status()).toBeLessThan(400);
      expect(desktopResponse?.status()).toBeLessThan(400);
      await Promise.all([
        assertMeaningfulProductionPage(
          webPage,
          pairedCase.web.path,
          pairedCase.web.ready,
        ),
        assertMeaningfulProductionPage(
          desktopPage,
          pairedCase.desktop.path,
          pairedCase.desktop.ready,
        ),
      ]);

      phase = "drive-matched-interaction";
      await Promise.all([
        driveMatchedInteractionState(
          webPage,
          matchedState,
          pairedCase.web.focus,
        ),
        driveMatchedInteractionState(
          desktopPage,
          matchedState,
          pairedCase.desktop.focus,
        ),
      ]);

      phase = "observe-final-state";
      const [webFinalState, desktopFinalState] = await Promise.all([
        observeFinalMatchedState(webPage, pairedCase.web.probe),
        observeFinalMatchedState(desktopPage, pairedCase.desktop.probe),
      ]);
      finalObservedState = {
        web: webFinalState,
        desktop: desktopFinalState,
      };

      phase = "capture-artifacts";
      const [webScreenshot, desktopScreenshot, webText, desktopText] =
        await Promise.all([
          webPage.screenshot(),
          desktopPage.screenshot(),
          webPage.locator("body").innerText(),
          desktopPage.locator("body").innerText(),
        ]);
      const { png: diffScreenshot, observation } = await createVisualDiff(
        webPage,
        webScreenshot,
        desktopScreenshot,
      );
      phase = "validate-final-state";
      metadata = createPairedEvidenceMetadata({
        scenarioId: pairedCase.id,
        expectedObservableResult: pairedCase.expectedObservableResult,
        sourceRevision,
        worktreeState,
        matchedState,
        finalObservedState,
        rendererBuildReceipt: rendererBuildReceiptBytes,
        webScreenshot,
        desktopScreenshot,
        diffScreenshot,
        webText,
        desktopText,
        pixelObservation: observation,
      });
      browserObservationStatus = "failed";
      declaredArtifacts = [
        [
          "evidence-run.v1.schema.json",
          evidenceRunSchemaBytes,
          "application/schema+json",
        ],
        [
          "parity-manifest.v2.json",
          desiredContractBytes,
          "application/json",
        ],
        [
          "renderer-build-receipt.json",
          rendererBuildReceiptBytes,
          "application/json",
        ],
        ["web-screenshot.png", webScreenshot, "image/png"],
        ["desktop-screenshot.png", desktopScreenshot, "image/png"],
        ["visual-diff.png", diffScreenshot, "image/png"],
        [
          "evidence-metadata.json",
          Buffer.from(`${JSON.stringify(metadata, null, 2)}\n`),
          "application/json",
        ],
      ];

      phase = "final-runtime-diagnostics";
      await Promise.all([
        webPage.waitForTimeout(250),
        desktopPage.waitForTimeout(250),
      ]);
      await Promise.all([webContext.close(), desktopContext.close()]);
      webContext = undefined;
      desktopContext = undefined;
      if (runtimeErrors.length > 0) {
        throw new Error(
          `Captured ${runtimeErrors.length} production renderer runtime diagnostics`,
        );
      }
      browserObservationStatus = "passed";

      phase = "attach-artifacts";
      for (const [name, body, contentType] of declaredArtifacts) {
        const outputPath = testInfo.outputPath(name);
        writeFileSync(outputPath, body);
        await testInfo.attach(name, { path: outputPath, contentType });
      }

      phase = "validate-evidence-run";
      const completedAt = new Date().toISOString();
      const evidenceRun = createPairedEvidenceRun({
        scenarioId: pairedCase.id,
        capabilityId: pairedCase.capabilityId,
        sourceRevision,
        contractRevision: sourceRevision,
        contractSha256:
          repositoryBinding.contractSha256 ??
          repositoryBinding.workingTreeContractSha256,
        contractPath: contractRelativePath,
        schemaSha256: evidenceRunSchemaSha256,
        prototypeRevision: desiredContract.references.prototype_revision,
        worktreeState,
        startedAt: rendererBuildReceipt.orchestration.started_at,
        completedAt,
        matchedState,
        metadata,
        rendererBuildReceipt,
        rendererBuildReceiptBytes,
        environment,
        browserStatus: "passed",
        browserStartedAt,
      });
      writeFileSync(
        evidenceRunOutputPath,
        Buffer.from(`${JSON.stringify(evidenceRun, null, 2)}\n`),
      );
      expect(
        validateEvidencePacket({
          repositoryRoot,
          evidenceRunPath: evidenceRunOutputPath,
        }),
      ).toEqual([]);

      phase = "attach-evidence-run";
      await testInfo.attach("evidence-run.json", {
        path: evidenceRunOutputPath,
        contentType: "application/json",
      });

      phase = "completed";
      writeAttemptEvidence({
        status: "passed",
        completedAt,
        diagnostics: [],
      });
    } catch (error) {
      const completedAt = new Date().toISOString();
      const failureDiagnostics = [...runtimeErrors, diagnosticForError(error)];
      writeAttemptEvidence({
        status: "failed",
        completedAt,
        failureDomain: pairedFailureDomainForPhase(phase),
        diagnostics: failureDiagnostics,
      });

      if (metadata && declaredArtifacts) {
        for (const [name, body] of declaredArtifacts) {
          writeFileSync(testInfo.outputPath(name), body);
        }
        const failedRun = createPairedEvidenceRun({
          scenarioId: pairedCase.id,
          capabilityId: pairedCase.capabilityId,
          sourceRevision,
          contractRevision: sourceRevision,
          contractSha256:
            repositoryBinding.contractSha256 ??
            repositoryBinding.workingTreeContractSha256,
          contractPath: contractRelativePath,
          schemaSha256: evidenceRunSchemaSha256,
          prototypeRevision: desiredContract.references.prototype_revision,
          worktreeState,
          startedAt: rendererBuildReceipt.orchestration.started_at,
          completedAt,
          matchedState,
          metadata,
          rendererBuildReceipt,
          rendererBuildReceiptBytes,
          environment,
          browserStatus: browserObservationStatus,
          browserStartedAt,
        });
        writeFileSync(
          testInfo.outputPath("evidence-run.json"),
          Buffer.from(`${JSON.stringify(failedRun, null, 2)}\n`),
        );
      }
      throw error;
    } finally {
      await Promise.allSettled([webContext?.close(), desktopContext?.close()]);
    }
  });
}
