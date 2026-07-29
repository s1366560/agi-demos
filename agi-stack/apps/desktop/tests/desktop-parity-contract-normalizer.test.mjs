import assert from "node:assert/strict";
import { test } from "node:test";

import {
  apiContract,
  normalizeUnavailableDesktopContracts,
} from "../contracts/desktop-web-parity/parity-contract-normalizer.mjs";

test("unavailable Desktop authorities collapse to one structured NONE contract", () => {
  const contracts = [
    apiContract("web", "GET", "/items", "web_service"),
    apiContract("web", "POST", "/items", "web_service"),
    apiContract("desktop_cloud", "GET", "/items", "cloud_service"),
    apiContract("desktop_cloud", "POST", "/items", "cloud_service"),
    apiContract("desktop_local", "GET", "/items", "sidecar"),
    apiContract("native_only", "NONE", "not_applicable:native", "none"),
  ];

  assert.deepEqual(
    normalizeUnavailableDesktopContracts(contracts, {
      desktop_cloud: {
        authority: "none",
        reason_code: "desktop_native_route_planned",
      },
      desktop_local: { authority: "sidecar", reason_code: null },
    }),
    [
      apiContract("web", "GET", "/items", "web_service"),
      apiContract("web", "POST", "/items", "web_service"),
      apiContract(
        "desktop_cloud",
        "NONE",
        "not_applicable:desktop_native_route_planned",
        "none",
      ),
      apiContract("desktop_local", "GET", "/items", "sidecar"),
      apiContract("native_only", "NONE", "not_applicable:native", "none"),
    ],
  );
});

test("unavailable authority requires a stable reason code", () => {
  assert.throws(
    () =>
      normalizeUnavailableDesktopContracts([], {
        desktop_cloud: { authority: "none", reason_code: null },
        desktop_local: { authority: "sidecar", reason_code: null },
      }),
    /stable reason_code/u,
  );
});
