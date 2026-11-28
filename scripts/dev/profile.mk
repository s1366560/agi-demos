# Preserve an existing full-stack checkout. Fresh checkouts use the standalone project.
STANDARD_DIRECTORY ?= $(MEMSTACK_DEV_ROOT)/.memstack/standard
MEMSTACK_DEV_PROFILE ?= $(if $(wildcard $(STANDARD_DIRECTORY)/owner.json),standard,$(if $(wildcard $(MEMSTACK_DEV_ROOT)/.env),full,standard))
ifneq ($(MEMSTACK_DEV_PROFILE),standard)
ifneq ($(MEMSTACK_DEV_PROFILE),full)
$(error MEMSTACK_DEV_PROFILE must be standard or full)
endif
endif
