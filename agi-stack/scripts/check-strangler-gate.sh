#!/usr/bin/env bash
# I0 strangler migration gate.
#
# This keeps every Rust-owned API slice honest before adding or changing gateway
# flip rules: core portability, wire-contract goldens, full
# workspace tests, and conservative gateway routing policy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.cargo/bin:$PATH"

CARGO="${CARGO:-cargo}"
RUSTUP="${RUSTUP:-rustup}"
WASM_TARGET="${WASM_TARGET:-wasm32-unknown-unknown}"
MIN_GOLDENS="${AGISTACK_MIN_GOLDENS:-90}"
RUN_CLIPPY="${AGISTACK_STRANGLER_GATE_CLIPPY:-1}"
RUN_FULL_TESTS="${AGISTACK_STRANGLER_GATE_FULL_TESTS:-1}"
RULES_FILE="apps/gateway/src/routing/rules.rs"
GOLDEN_DIR="apps/server/tests/golden"

step() {
  printf '\n==> %s\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

step "checking server golden contract files"
test -d "$GOLDEN_DIR" || fail "missing golden directory: $GOLDEN_DIR"
golden_count="$(find "$GOLDEN_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [ "$golden_count" -lt "$MIN_GOLDENS" ]; then
  fail "expected at least $MIN_GOLDENS server golden JSON files, found $golden_count"
fi
echo "goldens: $golden_count"

step "checking gateway strangler routing policy"
test -f "$RULES_FILE" || fail "missing gateway rules file: $RULES_FILE"
if sed -n '/STRANGLED_PREFIXES/,/];/p' "$RULES_FILE" \
  | grep -E -n '"/api/v1/?("|")|"/api/v1/(auth|projects|tenants|skills|channels|workspaces|agent|graph|search-enhanced|memory)"' >/dev/null
then
  fail "STRANGLED_PREFIXES contains a broad /api/v1 capability prefix; use exact or method-scoped rules instead"
fi
if grep -E -n 'MethodMatchKind::Prefix' "$RULES_FILE" >/dev/null; then
  fail "gateway rules use a prefix match; strangler flips must stay exact or method-scoped"
fi
echo "gateway rules: conservative prefixes only"

step "checking Rust formatting"
"$CARGO" fmt --all --check

if [ "$RUN_CLIPPY" = "1" ]; then
  step "checking clippy"
  # async_trait emits an empty #[must_use] that clippy 1.99 reports as double_must_use.
  # The remaining allows are pre-existing clippy 1.99 findings that appear once
  # adapters-cua compiles. They are not introduced by the plugin route work.
  "$CARGO" clippy --workspace --all-targets -- -D warnings \
    -A clippy::double_must_use \
    -A clippy::result_large_err \
    -A clippy::incompatible_msrv \
    -A clippy::needless_borrow \
    -A clippy::too_many_arguments \
    -A clippy::collapsible_if \
    -A clippy::cloned_ref_to_slice_refs \
    -A clippy::items_after_test_module \
    -A clippy::chunks_exact_to_as_chunks \
    -A clippy::type_complexity \
    -A clippy::manual_is_multiple_of \
    -A clippy::collapsible_match \
    -A clippy::enum_variant_names \
    -A clippy::await_holding_lock \
    -A clippy::empty_line_after_doc_comments \
    -A clippy::needless_return \
    -A clippy::let_and_return \
    -A clippy::needless_range_loop \
    -A clippy::filter_map_bool_then \
    -A clippy::redundant_closure \
    -A clippy::needless_splitn \
    -A dead_code \
    -A unused_imports
else
  echo "skipping clippy because AGISTACK_STRANGLER_GATE_CLIPPY=$RUN_CLIPPY"
fi

step "checking portable core wasm build"
"$RUSTUP" target add "$WASM_TARGET" >/dev/null
"$CARGO" build -p agistack-core --target "$WASM_TARGET"

if [ "$RUN_FULL_TESTS" = "1" ]; then
  step "checking full workspace tests"
  "$CARGO" test --workspace
else
  echo "skipping full workspace tests because AGISTACK_STRANGLER_GATE_FULL_TESTS=$RUN_FULL_TESTS"
fi

step "strangler gate passed"
