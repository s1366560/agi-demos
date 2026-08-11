import baseConfig from "./playwright.config.mjs";

export default {
  ...baseConfig,
  testMatch: "accessibility.spec.mjs",
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["line"]],
  outputDir: "accessibility-results",
  preserveOutput: "always",
  timeout: 120_000,
};
