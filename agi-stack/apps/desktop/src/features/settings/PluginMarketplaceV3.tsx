import { useMemo } from "react";
import {
  marketplaceEn,
  marketplaceZh,
  type MarketplaceMessage,
} from "../../../../../packages/plugin-marketplace-ui/src/messages";
import { DesktopApiClient } from "../../api/client";
import { useI18n } from "../../i18n";
import type { DesktopRuntimeConfig } from "../../types";
import { MarketplaceView } from "./MarketplaceView";

export function PluginMarketplaceV3({
  config,
  canManage,
  onInstallSignedV2,
}: {
  config: DesktopRuntimeConfig;
  canManage: boolean;
  onInstallSignedV2?: () => void;
}) {
  const { locale } = useI18n();
  const t = (key: MarketplaceMessage) =>
    (locale === "zh-CN" ? marketplaceZh : marketplaceEn)[key];
  const client = useMemo(
    () => new DesktopApiClient(config).pluginMarketplaceV3(),
    [config],
  );
  if (!config.tenantId || (config.mode === "local" && !config.projectId))
    return <p>{t("noScope")}</p>;
  return (
    <MarketplaceView
      key={`${config.mode}:${config.tenantId}:${config.projectId}`}
      client={client}
      t={t}
      scope={`${config.tenantId} / ${config.projectId}`}
      canManage={canManage}
      local={config.mode === "local"}
      onInstallSignedV2={onInstallSignedV2}
    />
  );
}
