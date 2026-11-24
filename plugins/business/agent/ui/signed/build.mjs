import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import tailwind from "@tailwindcss/postcss";
import postcss from "postcss";
import { buildPackagePages } from "../../../../../sdk/memstack-plugin-sdk/buildPages.mjs";

const localRequire = createRequire(import.meta.url);
const directory = fileURLToPath(new URL(".", import.meta.url));
await buildPackagePages({
  root: fileURLToPath(new URL("../../", import.meta.url)),
  sourceDirectory: "ui/signed",
  entries: {
    chat: { web: "WebChatPage.tsx", "desktop-renderer": "DesktopChatPage.tsx" },
  },
  plugins: [
    {
      name: "page-renderer-dependencies",
      setup(build) {
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
          { filter: /(?:web|desktop)Chat\.css$/ },
          async ({ path }) => {
            const result = await postcss([
              tailwind({ base: directory, optimize: true }),
            ]).process(await readFile(path, "utf8"), { from: path });
            return { contents: result.css, loader: "css" };
          },
        );
      },
    },
  ],
});
