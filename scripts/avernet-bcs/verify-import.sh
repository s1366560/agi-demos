#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if (( $# > 1 )); then
  echo "usage: $0 [avernet-bcs-root]" >&2
  exit 2
fi

readonly BCS_ROOT="${1:-${REPO_ROOT}/third_party/avernet-bcs}"
readonly MANIFEST="${BCS_ROOT}/UPSTREAM_MANIFEST.sha256"
readonly TREE_MANIFEST="${BCS_ROOT}/UPSTREAM_TREE.tsv"
readonly PATCH_MANIFEST="${BCS_ROOT}/DOWNSTREAM_PATCHES.tsv"
readonly ADDITION_MANIFEST="${BCS_ROOT}/DOWNSTREAM_ADDITIONS.tsv"

for required_manifest in \
  "${MANIFEST}" \
  "${TREE_MANIFEST}" \
  "${PATCH_MANIFEST}" \
  "${ADDITION_MANIFEST}"; do
  [[ -f "${required_manifest}" ]] || {
    echo "missing Avernet import manifest: ${required_manifest}" >&2
    exit 1
  }
done

readonly temp_dir="$(mktemp -d)"
trap 'rm -rf "${temp_dir:?}"' EXIT
readonly upstream_records="${temp_dir}/upstream-records.tsv"
readonly tree_records="${temp_dir}/tree-records.tsv"
readonly patch_records="${temp_dir}/patch-records.tsv"
readonly addition_records="${temp_dir}/addition-records.tsv"
readonly effective_manifest="${temp_dir}/effective-manifest.sha256"
readonly expected_paths="${temp_dir}/expected-paths"
readonly actual_paths="${temp_dir}/actual-paths"
readonly path_diff="${temp_dir}/path-diff"

while IFS= read -r line || [[ -n "${line}" ]]; do
  [[ -n "${line}" ]] || {
    echo "blank line in upstream checksum manifest" >&2
    exit 1
  }
  sha="${line%%  *}"
  path="${line#*  }"
  if [[ "${path}" == "${line}" || ! "${sha}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "invalid upstream checksum manifest entry: ${line}" >&2
    exit 1
  fi
  case "${path}" in
    /*|../*|*/../*|*/..|.|..)
      echo "unsafe upstream path: ${path}" >&2
      exit 1
      ;;
  esac
  printf '%s\t%s\n' "${path}" "${sha}" >> "${upstream_records}"
done < "${MANIFEST}"

while IFS=$'\t' read -r metadata path extra || [[ -n "${metadata}${path}${extra}" ]]; do
  if [[ -z "${metadata}" || -z "${path}" || -n "${extra}" ]]; then
    echo "invalid upstream tree manifest entry: ${metadata}${path:+<TAB>${path}}" >&2
    exit 1
  fi
  read -r mode object_type blob trailing <<< "${metadata}"
  if [[ "${object_type}" != "blob" || ! "${blob}" =~ ^[0-9a-f]{40}$ || -n "${trailing:-}" ]]; then
    echo "invalid upstream tree metadata for ${path}: ${metadata}" >&2
    exit 1
  fi
  case "${mode}" in
    100644|100755) ;;
    *)
      echo "unsupported upstream file mode ${mode}: ${path}" >&2
      exit 1
      ;;
  esac
  case "${path}" in
    /*|../*|*/../*|*/..|.|..)
      echo "unsafe upstream tree path: ${path}" >&2
      exit 1
      ;;
  esac
  printf '%s\t%s\n' "${path}" "${mode}" >> "${tree_records}"
done < "${TREE_MANIFEST}"

if [[ -n "$(cut -f1 "${upstream_records}" | LC_ALL=C sort | uniq -d)" ]]; then
  echo "duplicate path in upstream checksum manifest" >&2
  exit 1
fi
if [[ -n "$(cut -f1 "${tree_records}" | LC_ALL=C sort | uniq -d)" ]]; then
  echo "duplicate path in upstream tree manifest" >&2
  exit 1
fi

cut -f1 "${upstream_records}" | LC_ALL=C sort > "${expected_paths}"
cut -f1 "${tree_records}" | LC_ALL=C sort > "${actual_paths}"
if ! cmp -s "${expected_paths}" "${actual_paths}"; then
  echo "upstream checksum and tree manifests contain different path sets" >&2
  comm -3 "${expected_paths}" "${actual_paths}" | sed -n '1,80p' >&2
  exit 1
fi

: > "${patch_records}"
while IFS= read -r line || [[ -n "${line}" ]]; do
  [[ -z "${line}" || "${line}" == \#* ]] && continue
  IFS=$'\t' read -r path upstream_sha local_sha reason extra <<< "${line}"
  if [[ -z "${path}" || -z "${upstream_sha}" || -z "${local_sha}" || -z "${reason}" || -n "${extra}" ]]; then
    echo "invalid downstream patch entry; expected path<TAB>upstream_sha256<TAB>local_sha256<TAB>reason" >&2
    exit 1
  fi
  case "${path}" in
    /*|../*|*/../*|*/..|.|..)
      echo "unsafe downstream patch path: ${path}" >&2
      exit 1
      ;;
  esac
  if [[ ! "${upstream_sha}" =~ ^[0-9a-f]{64}$ || ! "${local_sha}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "invalid downstream patch checksum for ${path}" >&2
    exit 1
  fi
  if [[ "${upstream_sha}" == "${local_sha}" ]]; then
    echo "stale downstream patch entry has no content change: ${path}" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\n' "${path}" "${upstream_sha}" "${local_sha}" "${reason}" >> "${patch_records}"
done < "${PATCH_MANIFEST}"

if [[ -n "$(cut -f1 "${patch_records}" | LC_ALL=C sort | uniq -d)" ]]; then
  echo "duplicate path in downstream patch manifest" >&2
  exit 1
fi

if ! awk -F '\t' '
  FNR == NR { baseline[$1] = $2; next }
  !($1 in baseline) {
    print "downstream patch path is not in the fixed upstream baseline: " $1 > "/dev/stderr"
    failed = 1
    next
  }
  baseline[$1] != $2 {
    print "downstream patch baseline checksum differs from UPSTREAM_MANIFEST.sha256: " $1 > "/dev/stderr"
    failed = 1
  }
  END { exit failed }
' "${upstream_records}" "${patch_records}"; then
  exit 1
fi

: > "${addition_records}"
while IFS= read -r line || [[ -n "${line}" ]]; do
  [[ -z "${line}" || "${line}" == \#* ]] && continue
  IFS=$'\t' read -r path local_sha mode reason extra <<< "${line}"
  if [[ -z "${path}" || -z "${local_sha}" || -z "${mode}" || -z "${reason}" || -n "${extra}" ]]; then
    echo "invalid downstream addition entry; expected path<TAB>local_sha256<TAB>mode<TAB>reason" >&2
    exit 1
  fi
  case "${path}" in
    /*|../*|*/../*|*/..|.|..)
      echo "unsafe downstream addition path: ${path}" >&2
      exit 1
      ;;
  esac
  if [[ ! "${local_sha}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "invalid downstream addition checksum for ${path}" >&2
    exit 1
  fi
  case "${mode}" in
    100644|100755) ;;
    *)
      echo "unsupported downstream addition mode ${mode}: ${path}" >&2
      exit 1
      ;;
  esac
  printf '%s\t%s\t%s\t%s\n' "${path}" "${local_sha}" "${mode}" "${reason}" >> "${addition_records}"
done < "${ADDITION_MANIFEST}"

if [[ -n "$(cut -f1 "${addition_records}" | LC_ALL=C sort | uniq -d)" ]]; then
  echo "duplicate path in downstream addition manifest" >&2
  exit 1
fi
if ! awk -F '\t' '
  FNR == NR { baseline[$1] = 1; next }
  $1 in baseline {
    print "downstream addition path already exists in the fixed upstream baseline: " $1 > "/dev/stderr"
    failed = 1
  }
  END { exit failed }
' "${upstream_records}" "${addition_records}"; then
  exit 1
fi

cd "${BCS_ROOT}"
awk -F '\t' '
  FNR == NR { expected[$1] = $2; paths[++count] = $1; next }
  { expected[$1] = $3 }
  END {
    for (row = 1; row <= count; row++) {
      path = paths[row]
      print expected[path] "  " path
    }
  }
' "${upstream_records}" "${patch_records}" > "${effective_manifest}"
awk -F '\t' '{ print $2 "  " $1 }' "${addition_records}" >> "${effective_manifest}"
if ! shasum -a 256 --check --quiet "${effective_manifest}"; then
  echo "Avernet BCS content differs from the upstream baseline or registered downstream changes" >&2
  exit 1
fi

cut -f1 "${upstream_records}" > "${expected_paths}"
cut -f1 "${addition_records}" >> "${expected_paths}"
LC_ALL=C sort -o "${expected_paths}" "${expected_paths}"
find . -type f \
  ! -path './target/*' \
  ! -path './UPSTREAM.md' \
  ! -path './UPSTREAM_MANIFEST.sha256' \
  ! -path './UPSTREAM_TREE.tsv' \
  ! -path './DOWNSTREAM_PATCHES.tsv' \
  ! -path './DOWNSTREAM_ADDITIONS.tsv' \
  ! -path './rust-toolchain.toml' \
  ! -path './Makefile' \
  -print | sed 's#^\./##' | LC_ALL=C sort > "${actual_paths}"

if ! comm -3 "${expected_paths}" "${actual_paths}" > "${path_diff}"; then
  echo "failed to compare Avernet BCS import paths" >&2
  exit 1
fi
if [[ -s "${path_diff}" ]]; then
  echo "Avernet BCS import path set differs from the fixed upstream tree:" >&2
  sed -n '1,80p' "${path_diff}" >&2
  exit 1
fi

awk -F '\t' '{ print $1 "\t" $3 }' "${addition_records}" >> "${tree_records}"

while IFS=$'\t' read -r path mode; do
  case "${mode}" in
    100755)
      [[ -x "${path}" ]] || { echo "expected executable file: ${path}" >&2; exit 1; }
      ;;
    100644)
      [[ ! -x "${path}" ]] || { echo "unexpected executable file: ${path}" >&2; exit 1; }
      ;;
  esac
done < "${tree_records}"

readonly verified_count="$(wc -l < "${upstream_records}" | tr -d ' ')"
readonly patch_count="$(wc -l < "${patch_records}" | tr -d ' ')"
readonly addition_count="$(wc -l < "${addition_records}" | tr -d ' ')"
echo "verified ${verified_count} Avernet BCS upstream files, paths, and modes (${patch_count} registered downstream patches, ${addition_count} registered downstream additions)"
