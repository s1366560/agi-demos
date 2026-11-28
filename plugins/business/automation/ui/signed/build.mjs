import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import tailwind from "@tailwindcss/postcss";
import postcss from "postcss";
import { buildPackagePages } from "../../../../../sdk/memstack-plugin-sdk/buildPages.mjs";

const directory = fileURLToPath(new URL(".", import.meta.url));
await buildPackagePages({
  root: fileURLToPath(new URL("../../", import.meta.url)),
  sourceDirectory: "ui/signed",
  contribution: "contributions.json",
  entries: {
    events: "TenantActivityWeb.tsx",
    schedules: "CronJobsPage.tsx",
    "workflow-patterns": "WorkflowPatternsPage.tsx",
    playbooks: "PlaybooksWeb.tsx",
  },
  plugins: [
    {
      name: "package-tailwind",
      setup(build) {
        build.initialOptions.define = {
          ...build.initialOptions.define,
          "import.meta.env.DEV": "false",
          "import.meta.env.VITE_ENABLE_DEBUG_LOGS": "undefined",
          "import.meta.env.VITE_DEBUG_LOGS": "undefined",
        };
        const local = (name) => fileURLToPath(new URL(name, import.meta.url));
        const require = createRequire(import.meta.url);
        build.onResolve(
          {
            filter: /^(react|react-dom|react-router-dom|react-i18next)(\/.*)?$/,
          },
          ({ path }) => ({ path: require.resolve(path) }),
        );
        build.onResolve({ filter: /^antd$/ }, () => ({
          path: require.resolve("antd/es/index.js"),
        }));
        build.onResolve({ filter: /^@desktop\/i18n$/ }, () => ({
          path: local(
            "../../../../../agi-stack/apps/desktop/src/i18nContext.ts",
          ),
        }));
        build.onResolve(
          { filter: /^@desktop\/features\/tenant-admin\// },
          ({ path }) => {
            const file = path.replace(
              "@desktop/",
              "../../../../../agi-stack/apps/desktop/src/",
            );
            return {
              path: local(
                file +
                  (file.endsWith("TenantAdminRouteState") ? ".tsx" : ".ts"),
              ),
            };
          },
        );
        build.onResolve(
          { filter: /^\.\.\/\.\.\/api\/client$/ },
          ({ importer }) =>
            importer.endsWith("tenantManagementController.ts")
              ? {
                  path: local(
                    "../../../../../agi-stack/apps/desktop/src/api/desktopApiError.ts",
                  ),
                }
              : undefined,
        );
        const aliases = {
          "@desktop/api/client":
            "../../../../../agi-stack/apps/desktop/src/api/desktopApiError.ts",
          "../services/eventService": "./tenantAutomation.ts",
          "../services/webhookService": "./tenantAutomation.ts",
          "@/stores/tenant": "./tenantAutomation.ts",
          "@/hooks/useThemeColor":
            "../../../../../sdk/memstack-plugin-sdk/ui/hostAppearance.ts",
          "@/utils/logger": "../../../../../web/src/utils/logger.ts",
          "@/components/common/SkeletonLoader":
            "../../../../../web/src/components/common/SkeletonLoader.tsx",
        };
        build.onResolve(
          { filter: /^(?:@desktop\/api\/client|@\/|\.\.\/services\/)/ },
          ({ path }) =>
            aliases[path] ? { path: local(aliases[path]) } : undefined,
        );
        build.onResolve({ filter: /^\.\.\/services\/cronService$/ }, () => ({
          path: local("./cronService.ts"),
        }));
        build.onResolve({ filter: /^@\/types\/common$/ }, () => ({
          path: local("./pageError.ts"),
        }));
        build.onResolve({ filter: /^@\/utils\/date$/ }, () => ({
          path: local("../../../../../sdk/memstack-plugin-sdk/ui/localDate.ts"),
        }));
        build.onResolve({ filter: /^@\/utils\/confirmAction$/ }, () => ({
          path: local(
            "../../../../../sdk/memstack-plugin-sdk/ui/confirmAction.ts",
          ),
        }));
        build.onLoad({ filter: /\.css$/ }, async ({ path }) => {
          const result = await postcss([
            tailwind({ base: directory, optimize: true }),
          ]).process(await readFile(path, "utf8"), { from: path });
          return { contents: result.css, loader: "css" };
        });
      },
    },
  ],
});
