import assert from "node:assert/strict";
import { test } from "node:test";

import { deriveZoomEquivalentViewport } from "../contracts/accessibility/viewport.mjs";
import { auditKeyboardTraversal } from "../contracts/accessibility/playwright-keyboard-audit.mjs";

test("400% zoom uses a cross-engine equivalent CSS viewport", () => {
  assert.deepEqual(
    deriveZoomEquivalentViewport({ width: 1280, height: 720 }, 4),
    {
      referenceWidth: 1280,
      referenceHeight: 720,
      zoomFactor: 4,
      width: 320,
      height: 180,
    },
  );
  assert.throws(
    () => deriveZoomEquivalentViewport({ width: 1280, height: 720 }, 0),
    /accessibility_zoom_factor_invalid/u,
  );
});

test("keyboard traversal excludes roving controls with a negative DOM tab index", async () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  const pressed = [];
  const element = (tabIndex) => ({
    tabIndex,
    getBoundingClientRect: () => ({ width: 40, height: 24 }),
  });
  globalThis.getComputedStyle = () => ({
    display: "block",
    visibility: "visible",
  });
  const page = {
    locator() {
      return {
        evaluateAll(callback) {
          return callback([element(0), element(-1)]);
        },
      };
    },
    keyboard: {
      async press(key) {
        pressed.push(key);
      },
    },
    async evaluate() {
      return {
        identity: "reachable-control",
        attached: true,
        focusVisible: true,
        visible: true,
        obscured: false,
      };
    },
  };

  try {
    const evidence = await auditKeyboardTraversal(page);
    assert.ok(evidence.includes("keyboard:focusable=1"));
    assert.deepEqual(pressed, ["Tab", "Shift+Tab"]);
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test("keyboard traversal identifies the control that loses its focus indicator", async () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  globalThis.getComputedStyle = () => ({
    display: "block",
    visibility: "visible",
  });
  const page = {
    locator() {
      return {
        evaluateAll(callback) {
          return callback([
            {
              tabIndex: 0,
              getBoundingClientRect: () => ({ width: 40, height: 24 }),
            },
          ]);
        },
      };
    },
    keyboard: { async press() {} },
    async evaluate() {
      return {
        identity: "Retry",
        attached: true,
        focusVisible: false,
        visible: true,
        obscured: false,
      };
    },
  };

  try {
    await assert.rejects(
      auditKeyboardTraversal(page),
      /accessibility_keyboard_focus_indicator_missing:Retry/u,
    );
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test("keyboard traversal waits for native focus scrolling before judging visibility", async () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  const waits = [];
  const records = [
    {
      identity: "Import",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: false,
      obscured: true,
    },
    {
      identity: "Import",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: true,
      obscured: false,
    },
    {
      identity: "Import",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: true,
      obscured: false,
    },
  ];
  globalThis.getComputedStyle = () => ({
    display: "block",
    visibility: "visible",
  });
  const page = {
    locator() {
      return {
        evaluateAll(callback) {
          return callback([
            {
              tabIndex: 0,
              getBoundingClientRect: () => ({ width: 40, height: 24 }),
            },
          ]);
        },
      };
    },
    keyboard: { async press() {} },
    async evaluate() {
      return records.shift();
    },
    async waitForTimeout(delay) {
      waits.push(delay);
    },
  };

  try {
    const evidence = await auditKeyboardTraversal(page);
    assert.ok(evidence.includes("keyboard:focus-visible=true"));
    assert.deepEqual(waits, [16]);
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test("keyboard traversal treats leaving web content as a document boundary", async () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  const pressed = [];
  const records = [
    {
      identity: "last-control",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: true,
      obscured: false,
    },
    {
      identity: "body",
      attached: true,
      documentBoundary: true,
      focusVisible: false,
      visible: true,
      obscured: false,
    },
    {
      identity: "last-control",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: true,
      obscured: false,
    },
  ];
  globalThis.getComputedStyle = () => ({
    display: "block",
    visibility: "visible",
  });
  const page = {
    locator() {
      return {
        evaluateAll(callback) {
          return callback([
            {
              tabIndex: 0,
              getBoundingClientRect: () => ({ width: 40, height: 24 }),
            },
            {
              tabIndex: 0,
              getBoundingClientRect: () => ({ width: 40, height: 24 }),
            },
          ]);
        },
      };
    },
    keyboard: {
      async press(key) {
        pressed.push(key);
      },
    },
    async evaluate() {
      return records.shift();
    },
  };

  try {
    const evidence = await auditKeyboardTraversal(page);
    assert.ok(evidence.includes("keyboard:steps=1"));
    assert.ok(evidence.includes("keyboard:document-boundary=true"));
    assert.deepEqual(pressed, ["Tab", "Tab", "Shift+Tab"]);
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});
