import { App } from "antd";
import { createInstance } from "i18next";
import { createRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";

import type { RichPageRuntime } from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";
import {
  WorkflowPatternsView,
  type PatternClient,
  type PatternRecord,
} from "../web/tenant/WorkflowPatternsView";
import en from "../web/locales/en-US.json";
import zh from "../web/locales/zh-CN.json";
import "./workflow-patterns.css";

async function mount(host: RichPageRuntime) {
  const scope = await host.getContext();
  const instance = createInstance();
  await instance.init({
    lng: scope.locale.startsWith("zh") ? "zh" : "en",
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const client: PatternClient = {
    listPatterns: () =>
      host.invoke("list-patterns", {}) as Promise<{
        patterns: PatternRecord[];
      }>,
    deletePattern: (id) => host.invoke("delete-pattern", { pattern_id: id }),
    errorMessage: (error) => (error instanceof Error ? error.message : null),
  };
  createRoot(document.getElementById("root")!).render(
    <I18nextProvider i18n={instance}>
      <App>
        <WorkflowPatternsView
          tenantId={scope.tenantId}
          client={client}
          canDelete={scope.commands.includes("delete-pattern")}
        />
      </App>
    </I18nextProvider>,
  );
}
void mount(window.memstack);
