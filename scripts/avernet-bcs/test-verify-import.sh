#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly VERIFY_IMPORT="${SCRIPT_DIR}/verify-import.sh"
readonly temp_dir="$(mktemp -d)"
trap 'rm -rf "${temp_dir:?}"' EXIT

new_fixture() {
  local fixture_root="$1"
  mkdir -p "${fixture_root}"
  printf 'upstream\n' > "${fixture_root}/source.rs"
  printf '#!/usr/bin/env bash\n' > "${fixture_root}/tool.sh"
  chmod 755 "${fixture_root}/tool.sh"
  local source_sha tool_sha
  source_sha="$(shasum -a 256 "${fixture_root}/source.rs" | cut -d ' ' -f1)"
  tool_sha="$(shasum -a 256 "${fixture_root}/tool.sh" | cut -d ' ' -f1)"
  {
    printf '%s  source.rs\n' "${source_sha}"
    printf '%s  tool.sh\n' "${tool_sha}"
  } > "${fixture_root}/UPSTREAM_MANIFEST.sha256"
  {
    printf '100644 blob 0000000000000000000000000000000000000000\tsource.rs\n'
    printf '100755 blob 0000000000000000000000000000000000000000\ttool.sh\n'
  } > "${fixture_root}/UPSTREAM_TREE.tsv"
  printf '# path<TAB>upstream_sha256<TAB>local_sha256<TAB>reason\n' > "${fixture_root}/DOWNSTREAM_PATCHES.tsv"
  printf '# path<TAB>local_sha256<TAB>mode<TAB>reason\n' > "${fixture_root}/DOWNSTREAM_ADDITIONS.tsv"
  touch "${fixture_root}/UPSTREAM.md" "${fixture_root}/rust-toolchain.toml" "${fixture_root}/Makefile"
}

expect_success() {
  local name="$1"
  local fixture_root="$2"
  if ! "${VERIFY_IMPORT}" "${fixture_root}" > "${temp_dir}/${name}.out" 2>&1; then
    echo "expected success: ${name}" >&2
    sed -n '1,80p' "${temp_dir}/${name}.out" >&2
    exit 1
  fi
}

expect_failure() {
  local name="$1"
  local fixture_root="$2"
  local expected_message="$3"
  if "${VERIFY_IMPORT}" "${fixture_root}" > "${temp_dir}/${name}.out" 2>&1; then
    echo "expected failure: ${name}" >&2
    exit 1
  fi
  if ! grep -Fq "${expected_message}" "${temp_dir}/${name}.out"; then
    echo "failure did not contain expected message: ${name}" >&2
    sed -n '1,80p' "${temp_dir}/${name}.out" >&2
    exit 1
  fi
}

clean_root="${temp_dir}/clean"
new_fixture "${clean_root}"
expect_success clean_baseline "${clean_root}"

unregistered_root="${temp_dir}/unregistered"
new_fixture "${unregistered_root}"
printf 'downstream\n' > "${unregistered_root}/source.rs"
expect_failure unregistered_drift "${unregistered_root}" 'content differs from the upstream baseline or registered downstream changes'

registered_root="${temp_dir}/registered"
new_fixture "${registered_root}"
upstream_sha="$(shasum -a 256 "${registered_root}/source.rs" | cut -d ' ' -f1)"
printf 'downstream\n' > "${registered_root}/source.rs"
local_sha="$(shasum -a 256 "${registered_root}/source.rs" | cut -d ' ' -f1)"
printf 'source.rs\t%s\t%s\tMemStack compatibility patch\n' "${upstream_sha}" "${local_sha}" >> "${registered_root}/DOWNSTREAM_PATCHES.tsv"
expect_success registered_patch "${registered_root}"

wrong_local_root="${temp_dir}/wrong-local"
cp -R "${registered_root}" "${wrong_local_root}"
sed 's/downstream/tampered/' "${wrong_local_root}/source.rs" > "${wrong_local_root}/source.rs.tmp"
mv "${wrong_local_root}/source.rs.tmp" "${wrong_local_root}/source.rs"
expect_failure wrong_local_hash "${wrong_local_root}" 'content differs from the upstream baseline or registered downstream changes'

wrong_upstream_root="${temp_dir}/wrong-upstream"
cp -R "${registered_root}" "${wrong_upstream_root}"
sed "s/${upstream_sha}/0000000000000000000000000000000000000000000000000000000000000000/" "${wrong_upstream_root}/DOWNSTREAM_PATCHES.tsv" > "${wrong_upstream_root}/DOWNSTREAM_PATCHES.tsv.tmp"
mv "${wrong_upstream_root}/DOWNSTREAM_PATCHES.tsv.tmp" "${wrong_upstream_root}/DOWNSTREAM_PATCHES.tsv"
expect_failure wrong_upstream_hash "${wrong_upstream_root}" 'downstream patch baseline checksum differs from UPSTREAM_MANIFEST.sha256'

unknown_path_root="${temp_dir}/unknown-path"
new_fixture "${unknown_path_root}"
printf 'new\n' > "${unknown_path_root}/new.rs"
new_sha="$(shasum -a 256 "${unknown_path_root}/new.rs" | cut -d ' ' -f1)"
printf 'new.rs\t%s\t%s\tUntracked addition\n' "${upstream_sha}" "${new_sha}" >> "${unknown_path_root}/DOWNSTREAM_PATCHES.tsv"
expect_failure unknown_patch_path "${unknown_path_root}" 'downstream patch path is not in the fixed upstream baseline'

extra_file_root="${temp_dir}/extra-file"
new_fixture "${extra_file_root}"
printf 'unregistered\n' > "${extra_file_root}/extra.rs"
expect_failure unregistered_path "${extra_file_root}" 'import path set differs from the fixed upstream tree'

addition_root="${temp_dir}/addition"
new_fixture "${addition_root}"
printf 'downstream addition\n' > "${addition_root}/addition.rs"
addition_sha="$(shasum -a 256 "${addition_root}/addition.rs" | cut -d ' ' -f1)"
printf 'addition.rs\t%s\t100644\tMemStack extension\n' "${addition_sha}" >> "${addition_root}/DOWNSTREAM_ADDITIONS.tsv"
expect_success registered_addition "${addition_root}"

wrong_addition_root="${temp_dir}/wrong-addition"
cp -R "${addition_root}" "${wrong_addition_root}"
printf 'tampered addition\n' > "${wrong_addition_root}/addition.rs"
expect_failure wrong_addition_hash "${wrong_addition_root}" 'content differs from the upstream baseline or registered downstream changes'

addition_collision_root="${temp_dir}/addition-collision"
new_fixture "${addition_collision_root}"
source_sha="$(shasum -a 256 "${addition_collision_root}/source.rs" | cut -d ' ' -f1)"
printf 'source.rs\t%s\t100644\tInvalid collision\n' "${source_sha}" >> "${addition_collision_root}/DOWNSTREAM_ADDITIONS.tsv"
expect_failure addition_collision "${addition_collision_root}" 'downstream addition path already exists in the fixed upstream baseline'

duplicate_root="${temp_dir}/duplicate"
cp -R "${registered_root}" "${duplicate_root}"
duplicate_entry="$(tail -n 1 "${duplicate_root}/DOWNSTREAM_PATCHES.tsv")"
printf '%s\n' "${duplicate_entry}" >> "${duplicate_root}/DOWNSTREAM_PATCHES.tsv"
expect_failure duplicate_patch "${duplicate_root}" 'duplicate path in downstream patch manifest'

stale_root="${temp_dir}/stale"
new_fixture "${stale_root}"
stale_sha="$(shasum -a 256 "${stale_root}/source.rs" | cut -d ' ' -f1)"
printf 'source.rs\t%s\t%s\tNo longer changed\n' "${stale_sha}" "${stale_sha}" >> "${stale_root}/DOWNSTREAM_PATCHES.tsv"
expect_failure stale_patch "${stale_root}" 'stale downstream patch entry has no content change'

mode_root="${temp_dir}/mode"
new_fixture "${mode_root}"
chmod 755 "${mode_root}/source.rs"
expect_failure mode_drift "${mode_root}" 'unexpected executable file: source.rs'

addition_mode_root="${temp_dir}/addition-mode"
cp -R "${addition_root}" "${addition_mode_root}"
chmod 755 "${addition_mode_root}/addition.rs"
expect_failure addition_mode_drift "${addition_mode_root}" 'unexpected executable file: addition.rs'

echo 'verify-import self-test passed (clean, patch, addition, drift, baseline, path, duplicate, stale, and mode cases)'
