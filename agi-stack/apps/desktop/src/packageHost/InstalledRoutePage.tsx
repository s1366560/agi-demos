import { openVoiceSocket } from './voiceSocket';
import { useState } from "react";

import { RichPackagePages } from "./DesktopRichPackagePages";
import { useI18n } from "../i18nContext";
import { devicePageCall } from "./device";
import { transport, streamCommand } from "./transport";

export function InstalledRoutePage({
  tenantId,
  projectId,
  segment,
}: {
  tenantId: string;
  projectId: string | null;
  segment: string;
}) {
  const { locale, t } = useI18n();
  const base = "/tenant/" + encodeURIComponent(tenantId);
  const prefix = projectId
    ? base + "/project/" + encodeURIComponent(projectId)
    : base;
  const [page, setPage] = useState<{ pathname: string; pluginId?: string }>({
    pathname: prefix + "/" + segment,
  });
  return (
    <RichPackagePages
      scope={{ tenantId, projectId }}
      target="desktop-renderer"
      locale={locale}
      pathname={page.pathname}
      pluginId={page.pluginId}
      invokeDevice={projectId ? devicePageCall(tenantId, projectId) : undefined}
      transport={transport}
      openVoiceSocket={openVoiceSocket}
          streamCommand={streamCommand}
      navigate={(pathname, options) => {
        setPage({ pathname, pluginId: options?.pluginId ?? page.pluginId });
      }}
      backToMarket={
        <a
          href={
            "#" +
            base +
            "/plugins?marketScope=" +
            (projectId ? "project" : "tenant")
          }
        >
          {t("nav.plugins")}
        </a>
      }
    />
  );
}
