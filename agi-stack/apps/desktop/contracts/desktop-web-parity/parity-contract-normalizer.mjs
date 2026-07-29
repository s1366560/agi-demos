const DESKTOP_SURFACES = ["desktop_cloud", "desktop_local"];

export function apiContract(surface, method, path, authority) {
  return { surface, method, path, authority };
}

export function normalizeUnavailableDesktopContracts(contracts, surfaces) {
  const replacements = new Map();
  for (const surfaceName of DESKTOP_SURFACES) {
    const surface = surfaces[surfaceName];
    if (surface?.authority !== "none") continue;
    if (
      typeof surface.reason_code !== "string" ||
      surface.reason_code.length === 0
    ) {
      throw new Error(
        `${surfaceName} without authority must declare a stable reason_code`,
      );
    }
    replacements.set(
      surfaceName,
      apiContract(
        surfaceName,
        "NONE",
        `not_applicable:${surface.reason_code}`,
        "none",
      ),
    );
  }

  const normalized = [];
  const emitted = new Set();
  for (const contract of contracts) {
    const replacement = replacements.get(contract.surface);
    if (!replacement) {
      normalized.push(contract);
      continue;
    }
    if (!emitted.has(contract.surface)) {
      normalized.push(replacement);
      emitted.add(contract.surface);
    }
  }
  for (const [surfaceName, replacement] of replacements) {
    if (!emitted.has(surfaceName)) normalized.push(replacement);
  }
  return normalized;
}
