const SURFACE_NAMES = Object.freeze([
  "web",
  "desktop_cloud",
  "desktop_local",
  "native_only",
]);

export function assertSurfacePermissionCoverage({
  capabilityId,
  capabilityKind,
  surfaces,
  permissionRequirements,
}) {
  for (const surfaceName of SURFACE_NAMES) {
    const allowedActions = surfaces[surfaceName]?.allowed_actions ?? [];
    if (allowedActions.length === 0) continue;

    const permissionSurface =
      capabilityKind === "native_only" && surfaceName !== "web"
        ? "native_only"
        : surfaceName;
    const coveredActions = new Set(
      permissionRequirements
        .filter((requirement) => requirement.surface === permissionSurface)
        .flatMap((requirement) => requirement.actions),
    );
    const missingActions = allowedActions.filter(
      (action) => !coveredActions.has(action),
    );
    if (missingActions.length > 0) {
      throw new Error(
        `Capability ${capabilityId}.${surfaceName} lacks permission requirements for: ` +
          missingActions.join(", "),
      );
    }
  }
}
