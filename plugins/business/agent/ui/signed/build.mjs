import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import tailwind from "@tailwindcss/postcss";
import postcss from "postcss";
import { buildPackagePages } from "../../../../../sdk/memstack-plugin-sdk/buildPages.mjs";

const localRequire = createRequire(import.meta.url);
const directory = fileURLToPath(new URL(".", import.meta.url));
const webRoot = join(directory, '../../../../../web/src');
// An isolated document doesn't inherit Ant's control sizes or the shell's
// light/dark tokens. Compile the same definitions into the signed Web page.
const webStyles = postcss.parse(await readFile(join(webRoot, 'index.css'), 'utf8'));
const sharedStyles = webStyles.nodes.filter(node =>
  (node.type === 'atrule' && node.name === 'theme') ||
  (node.type === 'rule' && (/^(:root|\.dark|body|\.dark body|html.dark)$/.test(node.selector) ||
    node.selector.includes('.ant-btn') || node.selector.endsWith('.chat-search-highlight') || node.selector.startsWith('.memstack-prose')))
).map(node => node.toString()).join('\n');
await buildPackagePages({
  root: fileURLToPath(new URL("../../", import.meta.url)),
  sourceDirectory: "ui/signed",
  entries: {
    dashboard: "WebDashboardPage.tsx",
    chat: "WebChatPage.tsx",
  },
  plugins: [
    {
      name: "page-renderer-dependencies",
      setup(build) {
        build.onResolve({ filter: /^@\/services\/(projectWorkService|runReviewService)$/ }, () => ({
          path: join(directory, "reviewAuthority.ts"),
        }));
        build.onResolve({ filter: /^@\/(components\/common\/Spinner|services\/client\/ApiError)$/ }, ({path}) => ({
          path: join(directory, "../../../../../web/src", path.slice(2) + (path.endsWith("Spinner") ? ".tsx" : ".ts")),
        }));
        build.onResolve({filter: /(?:agentConfigService|^@\/services\/(?:systemService|traceService))$/}, () => ({path: join(directory, "dashboardAuthority.ts")}));
        build.onResolve({filter: /^@\/utils\/date$/}, () => ({path: join(directory, "signedDate.ts")}));
        // The original transcript pieces enter the page through these host modules.
        // Only their pure parts are bundled: opening an MCP app needs the shell canvas,
        // and the card that tracks HITL state in the shell is the same card without it.
        build.onResolve({filter: /^@\/components\/agent\/styles$/}, () => ({path: join(directory, '../web/chat/styles.ts')}));
        build.onResolve({filter: /^@\/components\/common$/}, () => ({path: join(webRoot, 'components/common/AppModal.tsx')}));
        build.onResolve({filter: /^@\/components\/agent\/InlineHITLCard$/}, () => ({path: join(directory, '../web/hitl/InlineHITLCard.tsx')}));
        build.onResolve({filter: /^\.\/useMCPAppOpen$/}, () => ({path: join(directory, 'noMCPAppOpen.ts')}));
        build.onResolve({filter: /^@\/utils\/hitlOptionDisplay$/}, () => ({path: join(directory, '../web/hitl/hitlOptionDisplay.ts')}));
        build.onResolve({filter: /^@\/(?:utils\/(?:toolCallTimeline|executionSummary)|i18n\/formatters|components\/agent\/results\/MultiSourceResultsCard|components\/agent\/chat\/AgentSection)$/}, ({path}) => ({
          path: join(webRoot, path.slice(2) + (path.startsWith('@/components/') ? '.tsx' : '.ts')),
        }));
        build.onResolve({filter: /^(?:@desktop\/|@\/components\/agent\/multiAgent\/)/}, ({path}) => {
          const file = path.startsWith("@desktop/") ? join(directory, "../../../../../agi-stack/apps/desktop/src", path.slice(9)) : join(directory, "../../../../../web/src", path.slice(2));
          return {path: [file, file + ".ts", file + ".tsx"].find(existsSync)};
        });
        build.onResolve({ filter: /^(?:@\/services\/commandService|@business\/agent\/ui\/web\/services\/skillService)$/ }, () => ({path: join(directory, 'chatCatalog.ts')}));
        build.onResolve({ filter: /^@\/services\/projectStatsService$/ }, () => ({path: join(directory, 'chatProjectContext.ts')}));
        build.onResolve({ filter: /^@\/components\/layout\/Resizer$/ }, () => ({path: join(webRoot, 'components/layout/Resizer.tsx')}));
        build.onResolve({ filter: /^@business\/agent\/ui\/web\/chat\/(EmptyState|styles)$/ }, ({path}) => ({
          path: join(directory, '../web/chat', path.endsWith('/styles') ? 'styles.ts' : 'EmptyState.tsx'),
        }));
        build.onResolve({ filter: /^@\/services\/agentService$|^@\/hooks\/useThemeColor$/ }, () => ({path: join(directory, 'chatContextAuthority.ts')}));
        build.onResolve({ filter: /^@\/components\/ui\/lazyAntd$/ }, () => ({path: join(directory, 'chatAnt.ts')}));
        build.initialOptions.supported = { "template-literal": false };
        build.onResolve(
          { filter: /^(?:react|react-dom|react-i18next|i18next)(?:\/.*)?$/ },
          ({ path }) => ({ path: localRequire.resolve(path) }),
        );
        build.onResolve(
          { filter: /^@copilotkit\/a2ui-renderer\/dist\// },
          ({ path }) => ({
            path: join(
              dirname(
                localRequire.resolve("@copilotkit/a2ui-renderer/package.json"),
              ),
              path.slice(path.indexOf("dist/")),
            ),
          }),
        );
      },
    },
    {
      name: "package-tailwind",
      setup(build) {
        build.onLoad(
          { filter: /(?:web|desktop)(?:Chat|Dashboard)\.css$/ },
          async ({ path }) => {
            const result = await postcss([
              tailwind({ base: directory, optimize: true }),
            ]).process((await readFile(path, 'utf8')) + (path.endsWith('webChat.css') ? '\n' + sharedStyles : ''), { from: path });
            return { contents: result.css, loader: "css" };
          },
        );
      },
    },
  ],
});
