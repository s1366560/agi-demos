SHELL := /usr/bin/env bash

REPO_ROOT := ../..
BCS_CARGO := $(REPO_ROOT)/scripts/avernet-bcs/cargo.sh
VERIFY_IMPORT := $(REPO_ROOT)/scripts/avernet-bcs/verify-import.sh
TEST_DATA_DIR := $(abspath $(REPO_ROOT)/.cache/avernet-bcs/test-data)

.PHONY: verify-import verify-import-test metadata check contract-test state-machine-test test audit supply-chain sbom baseline

verify-import:
	@$(VERIFY_IMPORT)

verify-import-test:
	@$(REPO_ROOT)/scripts/avernet-bcs/test-verify-import.sh

metadata:
	@$(BCS_CARGO) metadata --locked --no-deps --format-version 1 >/dev/null

check:
	@$(BCS_CARGO) check --workspace --locked

contract-test:
	@$(BCS_CARGO) test --locked --package bcs-db-api
	@$(BCS_CARGO) test --locked --package bcs-service-api --test message_flow_contracts

state-machine-test:
	@$(BCS_CARGO) test --locked --package bcs-collaboration-runtime --test runtime_progression

test:
	@# Upstream log-capture tests share tracing state and race under libtest parallelism.
	@mkdir -p $(TEST_DATA_DIR)
	@BCS_DATA_DIR=$(TEST_DATA_DIR) RUST_TEST_THREADS=1 $(BCS_CARGO) test --workspace --locked

audit:
	@$(REPO_ROOT)/scripts/avernet-bcs/audit.sh

supply-chain:
	@$(REPO_ROOT)/scripts/avernet-bcs/test-supply-chain.sh
	@$(REPO_ROOT)/scripts/avernet-bcs/audit.sh

sbom:
	@test -n "$(SOURCE_DATE_EPOCH)" || { echo "SOURCE_DATE_EPOCH is required" >&2; exit 2; }
	@python3 $(REPO_ROOT)/scripts/avernet-bcs/generate-sbom.py \
		--output-dir "$(if $(SBOM_OUTPUT),$(SBOM_OUTPUT),$(REPO_ROOT)/.cache/avernet-bcs/sbom)"

baseline: verify-import verify-import-test metadata check contract-test state-machine-test
