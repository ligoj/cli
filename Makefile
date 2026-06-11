# Ligoj CLI — developer tasks, powered by uv (https://docs.astral.sh/uv/)

.DEFAULT_GOAL := help

# Resolve a real uv binary, skipping the pyenv shim. The shim resolves
# .python-version (a fuzzy `3.11`) against installed pyenv versions and aborts
# before uv ever runs if none match. uv manages Python itself, so we bypass
# pyenv entirely; on machines without pyenv this is a harmless no-op.
UV := $(shell PATH="$$(echo "$$PATH" | tr ':' '\n' | grep -v '/.pyenv/shims' | paste -sd: -)" command -v uv)
ifeq ($(UV),)
$(error uv not found — install it from https://docs.astral.sh/uv/)
endif

help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

init: ## Create the venv and install runtime + dev dependencies
	$(UV) sync

run: ## Run the CLI, e.g. make run ARGS="--version"
	$(UV) run ligoj $(ARGS)

format: ## Auto-format and apply safe fixes with ruff
	$(UV) run ruff format .
	$(UV) run ruff check . --fix

lint: ## Static analysis with ruff and flake8
	$(UV) run ruff check .
	$(UV) run flake8

build: ## Build the sdist and wheel into dist/
	rm -rf dist build *.egg-info
	$(UV) build

check: build ## Validate the built distributions with twine
	$(UV) run --with twine twine check dist/*

clean: ## Remove build artifacts and caches
	rm -rf dist build *.egg-info .ruff_cache .pytest_cache

.PHONY: help init run format lint build check clean
