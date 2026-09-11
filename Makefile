.DEFAULT_GOAL := help
SHELL := /bin/sh

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Create .venv and install everything
	uv sync --all-groups
	@test -f .env || cp .env.example .env

test:  ## Run the containment suite - no model, no network, no database
	uv run pytest -q

ui:  ## Ops console on :8503
	uv run streamlit run ui/app.py --server.port 8503

demo:  ## Run a real LLM agent against the demo toolset
	uv run bar demo

lint:  ## Lint
	uv run ruff check src tests
	uv run ruff format --check src tests

fmt:  ## Auto-format
	uv run ruff format src tests
	uv run ruff check --fix src tests

.PHONY: help install test demo ui lint fmt
