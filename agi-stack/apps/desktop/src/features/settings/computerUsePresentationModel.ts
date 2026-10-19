import type {
  ComputerUseImageArtifact,
  ComputerUsePresentation,
  ComputerUseSnapshot,
} from "../../api/computerUseClientV2";

export function computerUseImageIdentity(
  artifact: ComputerUseImageArtifact | undefined,
): string | null {
  return artifact &&
    /^cua-image-[0-9a-f-]+$/u.test(artifact.artifact_id) &&
    ["image/png", "image/jpeg", "image/webp"].includes(artifact.mime_type)
    ? artifact.artifact_id
    : null;
}

/** Only native-declared state and exact pending-session membership decide affordances. */
export function computerUseSessionView(
  snapshot: ComputerUseSnapshot,
  session: ComputerUseSnapshot["sessions"][number],
): ComputerUsePresentation {
  const declared = session.presentation;
  if (session.stopped)
    return { ...declared, phase: "stopped", can_resume: false };
  if (declared) return declared;
  if (
    snapshot.pending.some(
      (pending) => pending.session_id === session.session_id,
    )
  )
    return { phase: "awaiting_permission" };
  return { phase: "idle", can_resume: false };
}

export function computerUsePhaseLabel(phase: string): string {
  const phases = [
    "idle",
    "observing",
    "acting",
    "awaiting_permission",
    "paused",
    "stopped",
    "focus_required",
    "error",
  ];
  return phases.includes(phase) ? `cua.phase.${phase}` : "cua.phase.idle";
}
