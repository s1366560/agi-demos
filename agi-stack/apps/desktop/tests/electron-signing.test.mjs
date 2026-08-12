import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { parseDocument } from 'yaml';

const repositoryRoot = fileURLToPath(new URL('../../../..', import.meta.url));
const builderConfig = readFileSync(new URL('../electron-builder.yml', import.meta.url), 'utf8');
const macEntitlements = readFileSync(
  new URL('../electron/resources/entitlements.mac.plist', import.meta.url),
  'utf8',
);
const inheritedMacEntitlements = readFileSync(
  new URL('../electron/resources/entitlements.mac.inherit.plist', import.meta.url),
  'utf8',
);
const localMacEntitlements = readFileSync(
  new URL('../electron/resources/entitlements.mac.local.plist', import.meta.url),
  'utf8',
);
const stageScript = readFileSync(new URL('../scripts/stage-sidecar.mjs', import.meta.url), 'utf8');
const stageWorkspaceCoreScript = readFileSync(
  new URL('../scripts/stage-workspace-core.mjs', import.meta.url),
  'utf8',
);
const updaterSource = readFileSync(new URL('../electron/main/updater.ts', import.meta.url), 'utf8');
const updatePolicySource = readFileSync(
  new URL('../electron/main/updatePolicy.ts', import.meta.url),
  'utf8',
);
const automaticUpdateLoopSource = readFileSync(
  new URL('../electron/main/automaticUpdateLoop.ts', import.meta.url),
  'utf8',
);
const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const localBuilderConfig = readFileSync(
  new URL('../electron-builder.local.yml', import.meta.url),
  'utf8',
);
const localSigningHook = readFileSync(
  new URL('../scripts/sign-local-macos.mjs', import.meta.url),
  'utf8',
);
const releaseVerification = readFileSync(
  new URL('../scripts/verify-release-artifacts.mjs', import.meta.url),
  'utf8',
);
const releasePackageVerification = readFileSync(
  new URL('../scripts/release-package-verification.mjs', import.meta.url),
  'utf8',
);
const releaseDraftValidation = readFileSync(
  new URL('../scripts/release-draft-validation.mjs', import.meta.url),
  'utf8',
);
const releaseArtifactContract = readFileSync(
  new URL('../scripts/release-artifact-contract.mjs', import.meta.url),
  'utf8',
);
const releaseWorkflow = readFileSync(
  new URL('../../../../.github/workflows/desktop-release.yml', import.meta.url),
  'utf8',
);
const ciWorkflow = readFileSync(
  new URL('../../../../.github/workflows/ci.yml', import.meta.url),
  'utf8',
);
const cleanCheckoutResources = [
  'agi-stack/apps/desktop/electron-builder.yml',
  'agi-stack/apps/desktop/electron-builder.local.yml',
  'agi-stack/apps/desktop/electron/resources/icon.png',
  'agi-stack/apps/desktop/electron/resources/icon.icns',
  'agi-stack/apps/desktop/electron/resources/entitlements.mac.plist',
  'agi-stack/apps/desktop/electron/resources/entitlements.mac.inherit.plist',
  'agi-stack/apps/desktop/electron/resources/entitlements.mac.local.plist',
  'agi-stack/apps/desktop/scripts/sign-local-macos.mjs',
  'agi-stack/apps/desktop/scripts/verify-release-artifacts.mjs',
];

test('desktop release workflow is valid YAML without duplicate mapping keys', () => {
  const document = parseDocument(releaseWorkflow, { uniqueKeys: true });
  assert.deepEqual(
    document.errors.map((error) => error.message),
    [],
  );
});

test('macOS packaging signs the sidecar and enables hardened notarized builds', () => {
  assert.match(builderConfig, /hardenedRuntime:\s*true/u);
  assert.match(builderConfig, /notarize:\s*true/u);
  assert.match(builderConfig, /forceCodeSigning:\s*true/u);
  assert.match(builderConfig, /icon:\s*electron\/resources\/icon\.icns/u);
  assert.equal(builderConfig.match(/icon:\s*electron\/resources\/icon\.png/gu)?.length, 2);
  assert.match(builderConfig, /entitlements:\s*electron\/resources\/entitlements\.mac\.plist/u);
  assert.match(
    builderConfig,
    /entitlementsInherit:\s*electron\/resources\/entitlements\.mac\.inherit\.plist/u,
  );
  assert.match(
    builderConfig,
    /binaries:\s*\n\s*-\s*Contents\/Resources\/sidecar\/agistack-desktop-sidecar/u,
  );
  assert.doesNotMatch(macEntitlements, /disable-library-validation/u);
  assert.doesNotMatch(inheritedMacEntitlements, /disable-library-validation/u);
  for (const entitlements of [macEntitlements, inheritedMacEntitlements, localMacEntitlements]) {
    assert.match(entitlements, /com\.apple\.security\.device\.audio-input/u);
  }
});

test('packaging configuration, signing scripts, icons, and entitlements are tracked', () => {
  for (const resource of cleanCheckoutResources) {
    assert.equal(existsSync(`${repositoryRoot}/${resource}`), true, `${resource} must exist`);
  }
  const repositoryResources = execFileSync(
    'git',
    ['ls-files', '--cached', '--', ...cleanCheckoutResources],
    { cwd: repositoryRoot, encoding: 'utf8' },
  )
    .trim()
    .split('\n')
    .sort();
  assert.deepEqual(repositoryResources, [...cleanCheckoutResources].sort());
});

test('packaging stages an integrity digest and enables signed auto-updates', () => {
  assert.match(stageScript, /createHash\('sha256'\)/u);
  assert.match(stageScript, /SHA256SUMS/u);
  assert.match(stageWorkspaceCoreScript, /createHash\('sha256'\)/u);
  assert.match(stageWorkspaceCoreScript, /SHA256SUMS/u);
  assert.match(builderConfig, /provider:\s*github/u);
  assert.match(builderConfig, /releaseType:\s*draft/u);
  assert.match(builderConfig, /publishAutoUpdate:\s*true/u);
  assert.match(builderConfig, /tagNamePrefix:\s*v/u);
  assert.match(updaterSource, /autoUpdater/u);
  assert.match(updaterSource, /releaseUpdateFeedIsEnabled/u);
  assert.match(updatePolicySource, /app-update\.yml/u);
  assert.match(updatePolicySource, /provider:\s*'github'/u);
  assert.match(updatePolicySource, /owner:\s*'s1366560'/u);
  assert.match(updatePolicySource, /repo:\s*'agi-demos'/u);
  assert.match(automaticUpdateLoopSource, /autoDownload\s*=\s*true/u);
  assert.match(automaticUpdateLoopSource, /autoInstallOnAppQuit\s*=\s*true/u);
  assert.match(
    packageJson.scripts['package:electron'],
    /^corepack pnpm run build:electron && corepack pnpm run build:sidecar/u,
  );
  assert.match(packageJson.scripts['package:electron'], /electron-builder\.local\.yml/u);
  assert.match(localBuilderConfig, /forceCodeSigning:\s*false/u);
  assert.match(localBuilderConfig, /identity:\s*null/u);
  assert.match(localBuilderConfig, /publish:\s*null/u);
  assert.match(localBuilderConfig, /afterPack:\s*scripts\/sign-local-macos\.mjs/u);
  assert.match(localSigningHook, /--sign',\s*'-'/u);
  assert.match(localSigningHook, /entitlements\.mac\.local\.plist/u);
  assert.match(localSigningHook, /--verify/u);
  assert.doesNotMatch(packageJson.scripts['release:electron'], /electron-builder\.local\.yml/u);
  assert.match(packageJson.scripts['release:electron'], /--publish never/u);
  assert.equal(packageJson.dependencies.yaml, '2.8.1');
});

test('tag releases fail closed and stage only a draft after package verification', () => {
  assert.match(releaseWorkflow, /tags:\s*\n\s*-\s*["']v\*["']/u);
  assert.match(releaseWorkflow, /macos-latest/u);
  assert.match(releaseWorkflow, /windows-latest/u);
  assert.match(releaseWorkflow, /ubuntu-latest/u);
  for (const secret of [
    'MAC_CSC_LINK',
    'MAC_CSC_KEY_PASSWORD',
    'APPLE_API_KEY_BASE64',
    'APPLE_API_KEY_ID',
    'APPLE_API_ISSUER',
    'APPLE_TEAM_ID',
    'WIN_CSC_LINK',
    'WIN_CSC_KEY_PASSWORD',
    'WIN_CSC_SHA1',
  ]) {
    assert.match(releaseWorkflow, new RegExp(`secrets\\.${secret}`, 'u'));
  }
  assert.doesNotMatch(releaseWorkflow, /secrets\.APPLE_API_KEY\s*\}\}/u);
  assert.match(releaseWorkflow, /Buffer\.from\(process\.env\.APPLE_API_KEY_BASE64,\s*'base64'\)/u);
  assert.match(releaseWorkflow, /AuthKey_\$\{process\.env\.APPLE_API_KEY_ID\}\.p8/u);
  assert.match(releaseWorkflow, /writeFileSync\(keyPath,\s*key,\s*\{\s*mode:\s*0o600\s*\}\)/u);
  assert.match(releaseWorkflow, /chmodSync\(keyPath,\s*0o600\)/u);
  assert.match(
    releaseWorkflow,
    /appendFileSync\(process\.env\.GITHUB_ENV,\s*`APPLE_API_KEY=\$\{keyPath\}\\n`/u,
  );
  assert.equal(releaseWorkflow.match(/--publish never/gu)?.length, 3);
  assert.doesNotMatch(releaseWorkflow, /--publish always/u);
  assert.match(releaseWorkflow, /parity-preflight:/u);
  assert.match(releaseWorkflow, /make -C agi-stack desktop-parity-check/u);
  assert.match(releaseWorkflow, /playwright install --with-deps chromium/u);
  assert.match(releaseWorkflow, /needs:\s*\[authorize,\s*parity-preflight\]/u);
  assert.match(releaseWorkflow, /AGISTACK_RELEASE_VERSION:\s*["']0\.1\.0["']/u);
  assert.match(releaseWorkflow, /packageJson\.version\s*!==\s*expectedVersion/u);
  assert.match(releaseWorkflow, /builder-args:\s*--mac --universal/u);
  assert.match(releaseWorkflow, /x86_64-apple-darwin/u);
  assert.match(releaseWorkflow, /aarch64-apple-darwin/u);
  assert.match(releaseWorkflow, /lipo -create/u);
  assert.match(releaseWorkflow, /xcrun notarytool submit/u);
  assert.match(releaseWorkflow, /xcrun stapler staple/u);
  assert.match(releaseWorkflow, /release-evidence-\*\.json/u);

  const stageIndex = releaseWorkflow.indexOf('pnpm run stage:sidecar');
  const authorizeJobIndex = releaseWorkflow.indexOf('\n  authorize:');
  const parityJobIndex = releaseWorkflow.indexOf('\n  parity-preflight:');
  const buildJobIndex = releaseWorkflow.indexOf('\n  build:');
  const authorizeJob = releaseWorkflow.slice(authorizeJobIndex, parityJobIndex);
  assert.ok(authorizeJobIndex >= 0 && authorizeJobIndex < parityJobIndex);
  assert.ok(parityJobIndex < buildJobIndex);
  assert.match(authorizeJob, /permissions:\s*\n\s*contents:\s*read/u);
  assert.match(authorizeJob, /github\.ref_protected/u);
  assert.match(authorizeJob, /DESKTOP_RELEASE_ALLOWED_ACTORS/u);
  assert.match(authorizeJob, /GITHUB_ACTOR/u);
  assert.match(authorizeJob, /compare\/\$\{GITHUB_SHA\}\.\.\.main/u);
  assert.match(authorizeJob, /contents\/agi-stack\/apps\/desktop\/package\.json/u);
  assert.doesNotMatch(authorizeJob, /uses:/u);
  assert.doesNotMatch(authorizeJob, /secrets\./u);
  assert.match(
    releaseWorkflow,
    /build:[\s\S]*needs:\s*\[[^\]]*authorize[^\]]*parity-preflight[^\]]*\]/u,
  );
  assert.match(releaseWorkflow, /build:[\s\S]*environment:\s*desktop-release-signing/u);
  assert.match(releaseWorkflow, /parity-preflight:[\s\S]*needs:\s*authorize/u);
  const materializeIndex = releaseWorkflow.indexOf('Materialize App Store Connect API key');
  const macBuildIndex = releaseWorkflow.indexOf('Build macOS release artifacts');
  const dmgNotarizeIndex = releaseWorkflow.indexOf('Notarize and staple macOS disk image');
  const verifyIndex = releaseWorkflow.indexOf('node scripts/verify-release-artifacts.mjs');
  const cleanupIndex = releaseWorkflow.indexOf('Remove App Store Connect API key');
  const workflowUploadIndex = releaseWorkflow.indexOf('actions/upload-artifact@', cleanupIndex);
  const draftJobIndex = releaseWorkflow.indexOf('\n  stage-draft:');
  const buildJob = releaseWorkflow.slice(buildJobIndex, draftJobIndex);
  const draftJob = releaseWorkflow.slice(draftJobIndex);
  const buildCheckoutIndex = buildJob.indexOf('uses: actions/checkout@');
  assert.ok(
    buildJob.indexOf('Validate macOS signing and notarization credentials') < buildCheckoutIndex,
  );
  assert.ok(buildJob.indexOf('Validate Windows signing credentials') < buildCheckoutIndex);
  const downloadIndex = releaseWorkflow.indexOf('actions/download-artifact@');
  const validateAssetsIndex = releaseWorkflow.indexOf('Validate the combined release asset set');
  const createDraftIndex = releaseWorkflow.indexOf('gh release create');
  const releaseUploadIndex = releaseWorkflow.indexOf('gh release upload');
  const exactRemoteIndex = releaseWorkflow.indexOf(
    'Download and verify the exact remote asset bytes',
  );
  const assertDraftIndex = releaseWorkflow.indexOf('Assert the release remains a draft');
  assert.ok(stageIndex >= 0 && stageIndex < materializeIndex);
  assert.ok(materializeIndex < macBuildIndex);
  assert.ok(macBuildIndex < dmgNotarizeIndex);
  assert.ok(dmgNotarizeIndex < verifyIndex);
  assert.ok(verifyIndex < cleanupIndex);
  assert.match(
    releaseWorkflow.slice(cleanupIndex, workflowUploadIndex),
    /if:\s*always\(\)\s*&&\s*runner\.os\s*==\s*'macOS'/u,
  );
  assert.ok(verifyIndex >= 0 && verifyIndex < workflowUploadIndex);
  assert.ok(workflowUploadIndex < draftJobIndex);
  assert.ok(draftJobIndex < downloadIndex);
  assert.ok(downloadIndex < validateAssetsIndex);
  assert.ok(validateAssetsIndex < createDraftIndex);
  assert.ok(createDraftIndex < releaseUploadIndex);
  assert.ok(releaseUploadIndex < exactRemoteIndex);
  assert.ok(exactRemoteIndex < assertDraftIndex);
  assert.equal(releaseWorkflow.match(/gh release create/gu)?.length, 1);
  assert.equal(releaseWorkflow.match(/actions\/download-artifact@\S+/gu)?.length, 3);
  assert.doesNotMatch(releaseWorkflow, /uses:\s+\S+@v\d+/u);
  assert.match(releaseWorkflow, /name:\s*agistack-desktop-macOS/u);
  assert.match(releaseWorkflow, /name:\s*agistack-desktop-Windows/u);
  assert.match(releaseWorkflow, /name:\s*agistack-desktop-Linux/u);
  assert.match(releaseWorkflow, /needs:\s*build/u);
  assert.match(releaseWorkflow, /Validate the combined release asset set/u);
  assert.match(
    releaseWorkflow,
    /run:\s*node agi-stack\/apps\/desktop\/scripts\/release-draft-validation\.mjs validate-combined/u,
  );
  assert.equal(
    releaseWorkflow.match(/release-draft-validation\.mjs validate-combined/gu)?.length,
    1,
  );
  assert.match(draftJob, /uses:\s*actions\/checkout@[a-f0-9]{40}/u);
  assert.match(draftJob, /ref:\s*\$\{\{\s*github\.sha\s*\}\}/u);
  assert.match(draftJob, /persist-credentials:\s*false/u);
  assert.ok(
    draftJob.indexOf('uses: actions/checkout@') < draftJob.indexOf('actions/download-artifact@'),
  );
  assert.doesNotMatch(releaseWorkflow, /desktop-release-draft-tools/u);
  assert.doesNotMatch(releaseWorkflow, /const policies\s*=/u);
  assert.doesNotMatch(releaseWorkflow, /validatePackageEvidence/u);
  assert.match(releaseDraftValidation, /basename\(name\)\s*!==\s*name/u);
  assert.match(releaseDraftValidation, /release asset basename collision/u);
  assert.match(
    releaseDraftValidation,
    /writeFileSync\(\s*join\(resolvedRoot,\s*'verified-assets\.txt'\)/u,
  );
  assert.doesNotMatch(releaseWorkflow, /--clobber/u);
  assert.match(releaseDraftValidation, /fileDigest\(path,\s*'sha256'/u);
  assert.match(
    releaseDraftValidation,
    /writeFileSync\(\s*join\(resolvedRoot,\s*'verified-assets\.json'\)/u,
  );
  assert.match(releaseWorkflow, /gh release download/u);
  assert.match(releaseWorkflow, /mktemp -d/u);
  assert.match(releaseWorkflow, /assert_exact_draft/u);
  assert.match(releaseWorkflow, /release-draft-validation\.mjs/u);
  assert.match(releaseDraftValidation, /remote asset SHA-256 mismatch/u);
  assert.match(releaseDraftValidation, /unexpected existing asset/u);
  assert.match(releaseWorkflow, /commits\/\$\{GITHUB_REF_NAME\}/u);
  assert.match(releaseWorkflow, /resolved_tag_commit[^]*GITHUB_SHA/u);
  for (const releaseAssetGlob of [
    'release/*.dmg',
    'release/*.zip',
    'release/*.exe',
    'release/*.AppImage',
    'release/*.deb',
    'release/*.blockmap',
    'release/latest*.yml',
  ]) {
    assert.ok(releaseWorkflow.includes(releaseAssetGlob));
  }
  assert.doesNotMatch(releaseWorkflow, /release\/builder-(?:debug|effective)/u);
  assert.doesNotMatch(releaseWorkflow, /release\/\*\*/u);
  assert.doesNotMatch(releaseWorkflow, /gh release edit/u);
  assert.doesNotMatch(releaseWorkflow, /--draft=false/u);
  assert.doesNotMatch(releaseWorkflow, /\bnative verification\b/iu);
  assert.match(releaseWorkflow, /name:\s*Stage verified desktop release draft/u);
  assert.match(releaseWorkflow, /Assert the release remains a draft[\s\S]*--json isDraft,tagName/u);
  assert.match(releaseWorkflow, /permissions:\s*\{\}/u);
  assert.match(releaseWorkflow, /build:[\s\S]*permissions:\s*\n\s*contents:\s*read/u);
  assert.match(
    releaseWorkflow,
    /stage-draft:[\s\S]*permissions:\s*\n\s*actions:\s*read\s*\n\s*contents:\s*write/u,
  );
  assert.match(releaseWorkflow, /persist-credentials:\s*false/u);
  assert.match(ciWorkflow, /permissions:\s*\n\s*contents:\s*read/u);
  assert.doesNotMatch(ciWorkflow, /agi-stack\/apps\/desktop\/release\/\*\*/u);
  for (const workflow of [releaseWorkflow, ciWorkflow]) {
    for (const match of workflow.matchAll(/uses:\s*[^@\s]+@([^\s#]+)/gu)) {
      assert.match(match[1], /^[a-f0-9]{40}$/u);
    }
  }
  assert.match(releaseArtifactContract, /latest-mac\.yml/u);
  assert.match(releaseArtifactContract, /latest\.yml/u);
  assert.match(releaseArtifactContract, /latest-linux\.yml/u);
  assert.match(releaseArtifactContract, /parseDocument/u);
  assert.match(releaseArtifactContract, /createHash\('sha512'\)/u);
  assert.match(releaseVerification, /SHA256SUMS/u);
  assert.match(releaseVerification, /memstack-workspace-core/u);
  assert.match(releaseVerification, /workspace_core_sha256/u);
  assert.match(releaseVerification, /workspace_core_signature_valid/u);
  assert.match(releaseWorkflow, /Build universal macOS Workspace Core/u);
  assert.match(releaseWorkflow, /pnpm run build:workspace-core/u);
  assert.match(releaseWorkflow, /pnpm run stage:workspace-core/u);
  assert.match(releaseVerification, /verifyMacPackageArtifacts/u);
  assert.match(releaseVerification, /verifyWindowsInstallerArtifact/u);
  assert.match(releasePackageVerification, /ditto/u);
  assert.match(releasePackageVerification, /hdiutil/u);
  assert.match(releasePackageVerification, /'7z'/u);
  assert.match(releasePackageVerification, /app-64\.7z/u);
  assert.match(releasePackageVerification, /inspectPortableExecutableArchitecture/u);
  assert.match(releaseVerification, /stapler',\s*'validate'/u);
  assert.match(releaseVerification, /lipo/u);
  assert.match(releaseVerification, /x86_64/u);
  assert.match(releaseVerification, /arm64/u);
  assert.match(releaseVerification, /Get-AuthenticodeSignature/u);
  assert.match(releaseVerification, /SignerCertificate\.Thumbprint/u);
  assert.match(releaseVerification, /WIN_CSC_SHA1/u);
  assert.match(releaseVerification, /Developer ID Authority is missing/u);
  assert.match(releaseVerification, /TeamIdentifier is missing/u);
  assert.match(releaseVerification, /--extract-certificates/u);
  assert.match(releaseVerification, /signing_certificate_sha256/u);
  assert.match(releaseVerification, /AGISTACK_EXPECTED_MAC_TEAM_ID/u);
  assert.match(releaseVerification, /com\.apple\.security\.device\.audio-input/u);
  assert.match(releaseVerification, /dpkg-deb/u);
  assert.match(releaseVerification, /--appimage-extract/u);
  assert.match(releaseVerification, /Desktop Entry/u);
  assert.match(releaseArtifactContract, /desktop-release-evidence-v2/u);
  assert.match(releaseArtifactContract, /package_artifacts_only/u);
  assert.match(releaseArtifactContract, /blockmap_structure_and_coverage_only/u);
  assert.match(releaseWorkflow, /blockmap_structure_and_coverage_only/u);
  assert.match(releaseArtifactContract, /artifact_verification_status/u);
  assert.match(releaseArtifactContract, /release_disposition/u);
  assert.match(releaseArtifactContract, /package_verification/u);
  assert.doesNotMatch(releaseArtifactContract, /native_verification/u);
  assert.doesNotMatch(releaseArtifactContract, /(?:^|\n)\s*verification_status:/u);
  assert.match(releaseDraftValidation, /RELEASE_EVIDENCE_KEYS/u);
  assert.match(releaseDraftValidation, /PACKAGE_VERIFICATION_KEYS/u);
  assert.match(releaseDraftValidation, /contains unexpected field/u);
  assert.match(releaseVerification, /DESKTOP_RELEASE_ARTIFACTS_VERIFIED/u);
  assert.doesNotMatch(releaseVerification, /\bnativeVerification\b/u);
  assert.match(releaseArtifactContract, /flag:\s*'wx'/u);
  assert.match(releaseVerification, /\['sidecar',\s*sidecarSignature\]/u);
  assert.match(releaseVerification, /\['Workspace Core',\s*workspaceCoreSignature\]/u);
  assert.match(
    releaseVerification,
    /appSignature\.developerIdAuthority\s*!==\s*signature\.developerIdAuthority/u,
  );
  assert.match(
    releaseVerification,
    /appSignature\.teamIdentifier\s*!==\s*signature\.teamIdentifier/u,
  );
  assert.match(
    releaseVerification,
    /appSignature\.signingCertificateSha256\s*!==\s*signature\.signingCertificateSha256/u,
  );
  const notarizationGateIndex = releaseVerification.indexOf(
    "process.env.AGISTACK_REQUIRE_NOTARIZATION === '1'",
  );
  const signatureInspectionIndex = releaseVerification.indexOf(
    "['--display', '--verbose=4', path]",
  );
  const notarizationAssessmentIndex = releaseVerification.indexOf(
    "['--assess', '--type', 'execute', '--verbose=4', appPath]",
  );
  assert.ok(notarizationGateIndex >= 0);
  assert.ok(signatureInspectionIndex < notarizationGateIndex);
  assert.ok(notarizationGateIndex < notarizationAssessmentIndex);
});
