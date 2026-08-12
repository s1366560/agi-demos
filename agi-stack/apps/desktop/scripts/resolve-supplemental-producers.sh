#!/usr/bin/env bash

set -euo pipefail
if [[ "${AGISTACK_PRODUCER_RESOLVER_TRACE:-0}" == '1' ]]; then
  set -x
fi

readonly trusted_workflow='.github/workflows/desktop-release-supplemental-evidence.yml'

blocked() {
  local reason="$1"
  printf '%s\n' "${AGISTACK_PRODUCER_STATUS_PREFIX:-evidence_status}=blocked reason=${reason}" >&2
  exit 1
}

if [[ "$#" -ne 4 ]]; then
  blocked 'producer_resolver_arguments_invalid'
fi

readonly expected_commit_sha="$1"
readonly expected_tag="$2"
readonly asset_manifest="$3"
readonly producer_manifest="$4"
readonly work_root="${RUNNER_TEMP}/desktop-supplemental-producers"

if [[ ! "$expected_commit_sha" =~ ^[a-f0-9]{40}$ || \
      ! "$expected_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]]; then
  blocked 'producer_resolver_identity_invalid'
fi

mkdir -m 0700 "$work_root"
printf '%s\n' \
  '{"contract_version":"github-workflow-producers-v1","repository":"'"$GITHUB_REPOSITORY"'","runs":[]}' \
  > "$producer_manifest"

runs_json="$work_root/workflow-runs.json"
gh api --paginate --slurp \
  "repos/${GITHUB_REPOSITORY}/actions/workflows/desktop-release-supplemental-evidence.yml/runs?event=workflow_dispatch&status=completed&per_page=100" \
  > "$runs_json.pages"
jq '[.[] | .workflow_runs[] | select(.conclusion == "success")]' \
  "$runs_json.pages" > "$runs_json"
if ! jq -e '([.[].id] | length) == ([.[].id] | unique | length)' "$runs_json" >/dev/null; then
  blocked 'producer_candidate_set_invalid'
fi

for supplemental_id in neo4j_runtime wcag_aa browser_bridge; do
  case "$supplemental_id" in
    neo4j_runtime) artifact_name='desktop-neo4j-runtime-evidence' ;;
    wcag_aa) artifact_name='desktop-wcag-aa-evidence' ;;
    browser_bridge) artifact_name='desktop-browser-bridge-release-evidence' ;;
    *) blocked 'supplemental_id_invalid' ;;
  esac

  candidate_root="$work_root/$supplemental_id"
  mkdir -m 0700 "$candidate_root"
  : > "$candidate_root/matches.jsonl"

  while IFS= read -r run_json; do
    run_id="$(jq -er '.id | tostring' <<<"$run_json")"
    attempt="$(jq -er '.run_attempt | tostring' <<<"$run_json")"
    if ! jq -e \
      --arg workflow_path "$trusted_workflow" \
      --arg repository "$GITHUB_REPOSITORY" \
      --arg expected_commit_sha "$expected_commit_sha" '
        .path == $workflow_path and
        .event == "workflow_dispatch" and
        .status == "completed" and
        .conclusion == "success" and
        .head_sha == $expected_commit_sha and
        .repository.full_name == $repository
      ' <<<"$run_json" >/dev/null; then
      continue
    fi
    candidate_dir="$candidate_root/$run_id-$attempt"
    mkdir -m 0700 "$candidate_dir"

    artifacts_json="$candidate_dir/artifacts.json"
    gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}/artifacts" > "$artifacts_json"
    artifact_count="$(
      jq --arg name "$artifact_name" \
        '[.artifacts[] | select(.name == $name and .expired == false)] | length' \
        "$artifacts_json"
    )"
    if [[ "$artifact_count" != '1' ]]; then
      continue
    fi

    artifact_json="$candidate_dir/artifact.json"
    jq --arg name "$artifact_name" \
      '[.artifacts[] | select(.name == $name and .expired == false)][0]' \
      "$artifacts_json" > "$artifact_json"
    expected_archive_url="https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/artifacts/$(jq -r '.id' "$artifact_json")/zip"
    if ! jq -e \
      --arg name "$artifact_name" \
      --arg archive_download_url "$expected_archive_url" '
        (.id | type == "number" and . > 0) and
        .name == $name and
        .expired == false and
        .archive_download_url == $archive_download_url
      ' "$artifact_json" >/dev/null; then
      continue
    fi
    zip_path="$candidate_dir/producer-artifact.zip"
    gh api \
      "repos/${GITHUB_REPOSITORY}/actions/artifacts/$(jq -r '.id' "$artifact_json")/zip" \
      > "$zip_path"
    if [[ "$(unzip -Z1 "$zip_path")" != 'producer-status.json' ]]; then
      continue
    fi
    unzip -qq "$zip_path" -d "$candidate_dir/unpacked"
    status_path="$candidate_dir/unpacked/producer-status.json"
    if [[ ! -f "$status_path" || -L "$status_path" ]]; then
      continue
    fi
    expected_url="https://github.com/${GITHUB_REPOSITORY}/actions/runs/${run_id}/attempts/${attempt}"
    if ! jq -e \
      --arg supplemental_id "$supplemental_id" \
      --arg expected_tag "$expected_tag" \
      --arg expected_commit_sha "$expected_commit_sha" \
      --arg trusted_workflow "$trusted_workflow" \
      --arg run_id "$run_id" \
      --arg attempt "$attempt" \
      --arg expected_url "$expected_url" '
        .contract_version == "desktop-release-supplemental-producer-status-v1" and
        .supplemental_id == $supplemental_id and
        .release_identity.tag == $expected_tag and
        .release_identity.commit_sha == $expected_commit_sha and
        .producer_run.workflow_path == $trusted_workflow and
        .producer_run.id == $run_id and
        .producer_run.attempt == $attempt and
        .producer_run.url == $expected_url and
        .producer_run.head_sha == $expected_commit_sha and
        .status == "passed" and
        .reason_code == null and
        .retryable == false
      ' "$status_path" >/dev/null; then
      continue
    fi

    sha256="$(shasum -a 256 "$zip_path" | awk '{print $1}')"
    size="$(wc -c < "$zip_path" | tr -d ' ')"
    release_asset_name="$supplemental_id-producer-artifact.zip"
    live_asset_count="$(
      jq --arg name "$release_asset_name" '[.assets[] | select(.name == $name)] | length' \
        "$asset_manifest"
    )"
    if [[ "$live_asset_count" != '1' ]]; then
      continue
    fi
    live_asset="$(
      jq -cer --arg name "$release_asset_name" '.assets[] | select(.name == $name)' \
        "$asset_manifest"
    )"
    if [[ "$(jq -r '.size' <<<"$live_asset")" != "$size" || \
          "$(jq -r '.digest' <<<"$live_asset")" != "sha256:$sha256" ]]; then
      continue
    fi

    jq -cn \
      --arg supplemental_id "$supplemental_id" \
      --arg workflow_path "$trusted_workflow" \
      --arg run_id "$run_id" \
      --arg attempt "$attempt" \
      --arg url "$expected_url" \
      --arg head_sha "$expected_commit_sha" \
      --arg conclusion "$(jq -r '.conclusion' <<<"$run_json")" \
      --arg artifact_id "$(jq -r '.id | tostring' "$artifact_json")" \
      --arg artifact_name "$artifact_name" \
      --argjson size "$size" \
      --arg sha256 "$sha256" \
      --arg release_asset_name "$release_asset_name" \
      '{
        supplemental_id: $supplemental_id,
        workflow_path: $workflow_path,
        id: $run_id,
        attempt: $attempt,
        url: $url,
        head_sha: $head_sha,
        conclusion: $conclusion,
        artifact: {
          github_artifact_id: $artifact_id,
          name: $artifact_name,
          size: $size,
          sha256: $sha256,
          release_asset_name: $release_asset_name
        }
      }' >> "$candidate_root/matches.jsonl"
  done < <(jq -c '.[]' "$runs_json")

  match_count="$(wc -l < "$candidate_root/matches.jsonl" | tr -d ' ')"
  if [[ "$match_count" != '1' ]]; then
    blocked 'producer_candidate_set_invalid'
  fi
  jq -s '.[0]' "$candidate_root/matches.jsonl" > "$candidate_root/match.json"
  jq --slurpfile run "$candidate_root/match.json" '.runs += [$run[0]]' \
    "$producer_manifest" > "$producer_manifest.next"
  mv "$producer_manifest.next" "$producer_manifest"
done
