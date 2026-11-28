import { useMemo } from "react";
import {
  marketplaceEn,
  marketplaceZh,
  type MarketplaceMessage,
} from "../../../../../packages/plugin-marketplace-ui/src/messages";
import type { DesktopPluginMarketplaceOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import { useI18n } from "../../i18n";
import type { DesktopRuntimeConfig } from "../../types";
import { MarketplaceView } from "./MarketplaceView";

export function PluginMarketplaceV3({
  config,
  canManage,
  onInstallSignedV2,
  operations,
}: {
  config: DesktopRuntimeConfig;
  canManage: boolean;
  onInstallSignedV2?: () => void;
  operations: Pick<DesktopPluginMarketplaceOperationsV2, 'marketplaceClient'>;
}) {
  const { locale } = useI18n();
  const t = (key: MarketplaceMessage) =>
    (locale === "zh-CN" ? marketplaceZh : marketplaceEn)[key];
  const client = useMemo(
    () => operations.marketplaceClient(config),
    [config, operations],
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
