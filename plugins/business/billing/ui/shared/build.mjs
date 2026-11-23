import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const contributions = new URL("../../contributions.json", import.meta.url);
const contract = JSON.parse(await readFile(contributions, "utf8"));
const page = contract.pages.find((item) => item.entry.path === "ui/account.js");
const { outputFiles } = await build({
  entryPoints: [fileURLToPath(new URL("AccountPage.tsx", import.meta.url))],
  bundle: true,
  platform: "browser",
  format: "iife",
  jsx: "automatic",
  minify: true,
  define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "inline",
  banner: {
    js:
      "/*! React and React DOM\n" +
      (await readFile(
        new URL("node_modules/react/LICENSE", import.meta.url),
        "utf8",
      )) +
      "\n*/",
  },
  write: false,
});
const bytes = outputFiles[0].contents;
page.entry.digest =
  "sha256:" + createHash("sha256").update(bytes).digest("hex");
await writeFile(new URL("../account.js", import.meta.url), bytes);
await writeFile(contributions, JSON.stringify(contract, null, 2) + "\n");
