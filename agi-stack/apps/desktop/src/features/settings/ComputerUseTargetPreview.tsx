import { useEffect, useState } from "react";
import type {
  ComputerUseClientV2,
  ComputerUseImageArtifact,
  ComputerUsePresentation,
  ComputerUseTarget,
} from "../../api/computerUseClientV2";
import { useI18n } from "../../i18n";
import { computerUseTimestamp } from '../../api/computerUseTime';
import { computerUsePreviewBlobV2 } from "../chat/computerUseResultPresentationV2";
import {
  computerUseImageIdentity,
  computerUsePhaseLabel,
} from "./computerUsePresentationModel";
import type { ComputerUseInputStore } from './computerUseInputStore';
import { ComputerUseWindowPreview } from './ComputerUseWindowPreview';

export function useComputerUseArtifact(
  client: ComputerUseClientV2 | null,
  artifact: ComputerUseImageArtifact | undefined,
): string | null {
  const id = computerUseImageIdentity(artifact);
  const [loaded, setLoaded] = useState<{
    client: ComputerUseClientV2;
    id: string;
    url: string;
  } | null>(null);
  useEffect(() => {
    if (!client || !id) return;
    const abort = new AbortController();
    let url: string | undefined;
    void client
      .preview(id, abort.signal)
      .then((data) => {
        if (abort.signal.aborted) return;
        url = URL.createObjectURL(computerUsePreviewBlobV2(data));
        setLoaded({ client, id, url });
      })
      .catch(() => undefined);
    return () => {
      abort.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [client, id]);
  return loaded?.client === client && loaded.id === id ? loaded.url : null;
}

export function ComputerUseAppIdentity({
  target,
  icon,
  client,
  fallback = "",
}: {
  target?: ComputerUseTarget;
  icon?: ComputerUseImageArtifact;
  client: ComputerUseClientV2 | null;
  fallback?: string;
}) {
  const url = useComputerUseArtifact(client, icon);
  const name = target?.display_name || target?.app_id || fallback;
  return (
    <div className="computer-use-app-identity">
      {url ? (
        <img src={url} alt="" className="computer-use-app-icon" />
      ) : (
        <svg
          className="computer-use-app-icon computer-use-placeholder-icon"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <rect x="3" y="4" width="18" height="13" rx="3" />
          <path d="M8 21h8M12 17v4" />
        </svg>
      )}
      <div>
        <strong title={target?.app_id}>{name}</strong>
        {target?.window_title ? (
          <span title={target.window_id}>{target.window_title}</span>
        ) : null}
      </div>
    </div>
  );
}

export function ComputerUseTargetPreview({
  presentation,
  client,
  recent = false,
  sessionId,
  inputStore,
}: {
  presentation: ComputerUsePresentation;
  client: ComputerUseClientV2 | null;
  recent?: boolean;
  sessionId?: string;
  inputStore?: ComputerUseInputStore | null;
}) {
  const { t } = useI18n();
  const image = useComputerUseArtifact(client, presentation.preview);
  const icon = useComputerUseArtifact(client, presentation.app_icon);
  const observed = computerUseTimestamp(presentation.preview?.observed_at ?? presentation.updated_at);
  const time = observed ? new Date(observed).toLocaleTimeString() : null;
  return (
    <figure
      className="computer-use-target-preview"
      data-phase={presentation.phase}
    >
      <ComputerUseAppIdentity
        target={presentation.target}
        icon={presentation.app_icon}
        client={client}
      />
      <ComputerUseWindowPreview image={image} icon={icon} presentation={presentation}
        sessionId={recent ? undefined : sessionId} inputStore={recent ? null : inputStore} />
      <figcaption>
        <span>
          {t(recent ? "cua.recentObservation" : "cua.latestObservation")}
        </span>
        {time ? (
          <time dateTime={observed ?? undefined}>{time}</time>
        ) : (
          <span>{t("cua.observationTimeUnknown")}</span>
        )}
        {presentation.preview?.window_id || presentation.target?.window_id ? (
          <code>
            {presentation.preview?.window_id ?? presentation.target?.window_id}
          </code>
        ) : null}
        {!recent ? (
          <span className="computer-use-phase">
            {t(computerUsePhaseLabel(presentation.phase))}
          </span>
        ) : null}
      </figcaption>
      {presentation.error_code ? (
        <code className="computer-use-error-code">
          {presentation.error_code}
        </code>
      ) : null}
    </figure>
  );
}
