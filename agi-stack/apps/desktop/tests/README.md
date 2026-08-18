# Desktop tests

Run the full suite from this package root:

```bash
pnpm test          # equivalent to: node tests/run.mjs
```

`tests/run.mjs` first compiles the TypeScript sources into
`/tmp/agistack-desktop-test-dist` and then executes every discovered
`*.test.mjs` file with the compiled output on `NODE_PATH`.

Do **not** run individual test files directly with `node --test tests/xxx.test.mjs`:
without the runner-injected `NODE_PATH` they fail with `MODULE_NOT_FOUND`.
To run a single file, either go through `pnpm test`, or replicate the runner
setup (compile via `tsconfig.test.json`, then run node with `NODE_PATH`
pointing at the compiled dist).
