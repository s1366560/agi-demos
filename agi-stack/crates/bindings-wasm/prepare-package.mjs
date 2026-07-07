import { copyFileSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const crateDir = dirname(fileURLToPath(import.meta.url));
const outDir = join(crateDir, process.argv[2] ?? "pkg");
const helperFile = "web-persistence.mjs";
const packageJsonPath = join(outDir, "package.json");

copyFileSync(join(crateDir, helperFile), join(outDir, helperFile));

const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8"));
const files = new Set(packageJson.files ?? []);
files.add(helperFile);
packageJson.files = Array.from(files);

writeFileSync(packageJsonPath, `${JSON.stringify(packageJson, null, 2)}\n`);
