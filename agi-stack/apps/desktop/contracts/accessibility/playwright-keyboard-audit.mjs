const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "summary",
  "[contenteditable='true']",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export async function auditKeyboardTraversal(
  page,
  { maxSteps = 24, allowNoFocusable = false } = {},
) {
  const focusableCount = await page.locator(FOCUSABLE_SELECTOR).evaluateAll((elements) =>
    elements.filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return (
        element.tabIndex >= 0 &&
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0
      );
    }).length,
  );
  if (focusableCount === 0) {
    if (allowNoFocusable) return ["keyboard:focusable=0", "keyboard:controls=not_applicable"];
    throw new Error("accessibility_keyboard_target_missing");
  }

  const stepCount = Math.min(focusableCount, maxSteps);
  const records = [];
  let documentBoundaryReached = false;
  for (let index = 0; index < stepCount; index += 1) {
    await page.keyboard.press("Tab");
    const record = await inspectStableActiveElement(page);
    if (record.documentBoundary) {
      if (records.length === 0) {
        throw new Error("accessibility_keyboard_document_boundary_without_target");
      }
      documentBoundaryReached = true;
      break;
    }
    assertKeyboardRecord(record);
    records.push(record);
  }

  const uniqueFocusTargets = new Set(records.map(({ identity }) => identity));
  if (records.length > 1 && uniqueFocusTargets.size < 2) {
    throw new Error("accessibility_keyboard_trap_detected");
  }

  await page.keyboard.press("Shift+Tab");
  const reverseRecord = await inspectStableActiveElement(page);
  assertKeyboardRecord(reverseRecord);

  return [
    `keyboard:focusable=${focusableCount}`,
    `keyboard:steps=${records.length}`,
    `keyboard:unique=${uniqueFocusTargets.size}`,
    `keyboard:reverse=${reverseRecord.identity}`,
    `keyboard:document-boundary=${documentBoundaryReached}`,
    "keyboard:focus-visible=true",
    "keyboard:focus-obscured=false",
  ];
}

async function inspectStableActiveElement(page) {
  const first = await inspectActiveElement(page);
  if (first.documentBoundary || (first.visible && !first.obscured)) return first;
  await page.waitForTimeout(16);
  return inspectActiveElement(page);
}

async function inspectActiveElement(page) {
  return page.evaluate(() => {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) {
      return {
        identity: "missing",
        attached: false,
        documentBoundary: false,
        focusVisible: false,
        visible: false,
        obscured: true,
      };
    }
    const rect = active.getBoundingClientRect();
    const centerX = Math.min(Math.max(rect.left + rect.width / 2, 0), innerWidth - 1);
    const centerY = Math.min(Math.max(rect.top + rect.height / 2, 0), innerHeight - 1);
    const hit = document.elementFromPoint(centerX, centerY);
    const style = getComputedStyle(active);
    const identity =
      active === document.body
        ? "body"
        : active === document.documentElement
          ? "html"
          : active.id ||
      active.getAttribute("data-testid") ||
      active.getAttribute("aria-label") ||
      active.textContent?.trim().slice(0, 80) ||
      active.tagName.toLowerCase();
    return {
      identity,
      attached: document.contains(active),
      documentBoundary: active === document.body || active === document.documentElement,
      focusVisible: active.matches(":focus-visible"),
      visible:
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0 &&
        rect.bottom > 0 &&
        rect.top < innerHeight &&
        rect.right > 0 &&
        rect.left < innerWidth,
      obscured: hit === null || !(active === hit || active.contains(hit) || hit.contains(active)),
    };
  });
}

function assertKeyboardRecord(record) {
  const target = `:${record.identity}`;
  if (!record.attached) throw new Error(`accessibility_keyboard_focus_detached${target}`);
  if (!record.visible) throw new Error(`accessibility_keyboard_focus_not_visible${target}`);
  if (!record.focusVisible) {
    throw new Error(`accessibility_keyboard_focus_indicator_missing${target}`);
  }
  if (record.obscured) throw new Error(`accessibility_keyboard_focus_obscured${target}`);
}
