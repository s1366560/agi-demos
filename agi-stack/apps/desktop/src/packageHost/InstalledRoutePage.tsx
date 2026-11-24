import { useState } from "react";

import { RichPackagePages } from "../../../../packages/plugin-marketplace-ui/src/RichPackagePages";
import { useI18n } from "../i18nContext";
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
  const [pathname, navigate] = useState(prefix + "/" + segment);
  return (
    <RichPackagePages
      scope={{ tenantId, projectId }}
      target="desktop-renderer"
      locale={locale}
      pathname={pathname}
      transport={transport}
      streamCommand={streamCommand}
      navigate={navigate}
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
