# Ligoj CLI — developer tasks, powered by uv (https://docs.astral.sh/uv/)

.DEFAULT_GOAL := help

help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

init: ## Create the venv and install runtime + dev dependencies
	uv sync

run: ## Run the CLI, e.g. make run ARGS="--version"
	uv run ligoj $(ARGS)

format: ## Auto-format and apply safe fixes with ruff
	uv run ruff format .
	uv run ruff check . --fix

lint: ## Static analysis with ruff and flake8
	uv run ruff check .
	uv run flake8

build: ## Build the sdist and wheel into dist/
	rm -rf dist build *.egg-info
	uv build

check: build ## Validate the built distributions with twine
	uv run --with twine twine check dist/*

clean: ## Remove build artifacts and caches
	rm -rf dist build *.egg-info .ruff_cache .pytest_cache

.PHONY: help init run format lint build check clean
