# Ligoj CLI — developer tasks, powered by uv (https://docs.astral.sh/uv/)

.DEFAULT_GOAL := help

# Resolve a real uv binary, skipping the pyenv shim. The shim resolves
# .python-version (a fuzzy `3.11`) against installed pyenv versions and aborts
# before uv ever runs if none match. uv manages Python itself, so we bypass
# pyenv entirely; on machines without pyenv this is a harmless no-op. The extra
# leading paths let us find uv right after `make init` installs it.
UV := $(shell PATH="$$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$$(echo "$$PATH" | tr ':' '\n' | grep -v '/.pyenv/shims' | paste -sd: -)" command -v uv)
ifeq ($(UV),)
ifeq ($(filter init,$(MAKECMDGOALS)),)
$(error uv not found — run 'make init' to install it)
endif
endif

# Release knobs (override on the command line, e.g. `make release PART=patch`).
# Recursive '=' so $(UV) is expanded at use time, after it is resolved above.
PART ?= minor
RELEASE = UV="$(UV)" $(UV) run python scripts/release.py

help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

init: ## Create the venv and install all dependencies (installs uv if missing)
	@uv="$(UV)"; \
	if [ -z "$$uv" ]; then \
		echo "▶ uv not found — installing from https://astral.sh/uv …"; \
		curl -LsSf https://astral.sh/uv/install.sh | sh || { echo "uv install failed" >&2; exit 1; }; \
		uv="$$HOME/.local/bin/uv"; \
	fi; \
	echo "▶ using uv: $$uv"; \
	"$$uv" sync

run: ## Run the CLI, e.g. make run ARGS="--version"
	$(UV) run ligoj $(ARGS)

format: ## Auto-format and apply safe fixes with ruff
	$(UV) run ruff format .
	$(UV) run ruff check . --fix

lint: ## Static analysis with ruff and flake8
	$(UV) run ruff check .
	$(UV) run flake8

test: ## Run the full local quality gate (lint, format check, build, twine check)
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run flake8
	rm -rf dist build *.egg-info
	$(UV) build
	$(UV) run --with twine twine check dist/*

build: ## Build the sdist and wheel into dist/
	rm -rf dist build *.egg-info
	$(UV) build

check: build ## Validate the built distributions with twine
	$(UV) run --with twine twine check dist/*

release-test: ## Publish a dev build to TestPyPI (via develop) and wait until live
	$(RELEASE) test

release: ## Cut a PyPI release: gate, bump version, tag, push, publish, wait (PART=minor)
	$(RELEASE) release --part $(PART) $(if $(YES),--yes,)

clean: ## Remove build artifacts and caches
	rm -rf dist build *.egg-info .ruff_cache .pytest_cache

.PHONY: help init run format lint test build check release-test release clean
