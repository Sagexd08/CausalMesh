# CausalMesh — developer entry points.
# Works on Windows (Git Bash / MSYS make) and POSIX shells alike.

PYTHON ?= python

.DEFAULT_GOAL := help
.PHONY: help install install-dev doctor test test-unit test-integration \
        test-property test-adversarial test-failure test-repro lint format \
        typecheck smoke verify analyze report audit reproduce clean

help: ## Show this help
	@echo "CausalMesh — available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

install: ## Install the package (runtime only)
	$(PYTHON) -m pip install -e .

install-dev: ## Install with analysis and development extras
	$(PYTHON) -m pip install -e ".[analysis,dev]"

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

doctor: ## Run the environment health check
	$(PYTHON) -m causalmesh.cli.main doctor

audit: ## Self-audit for untested modules, missing provenance, dirty raw data
	$(PYTHON) -m causalmesh.cli.main audit

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test: ## Run the full test suite
	$(PYTHON) -m pytest

test-unit: ## Unit tests only
	$(PYTHON) -m pytest -m unit

test-integration: ## Integration tests only
	$(PYTHON) -m pytest -m integration

test-property: ## Property-based invariant tests
	$(PYTHON) -m pytest -m property

test-adversarial: ## Attacks the verifier must detect
	$(PYTHON) -m pytest -m adversarial

test-failure: ## Fault-injection and recovery tests
	$(PYTHON) -m pytest -m failure

test-repro: ## Reproducibility tests
	$(PYTHON) -m pytest -m reproducibility

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

lint: ## Lint the source tree
	$(PYTHON) -m ruff check src tests

format: ## Auto-format the source tree
	$(PYTHON) -m ruff format src tests

typecheck: ## Static type checking
	$(PYTHON) -m mypy src

# ---------------------------------------------------------------------------
# Experiment pipeline
# ---------------------------------------------------------------------------

smoke: ## Plan and run the smoke profile
	$(PYTHON) -m causalmesh.cli.main experiment plan --profile smoke
	$(PYTHON) -m causalmesh.cli.main experiment run  --profile smoke

verify: ## Verify all event chains offline
	$(PYTHON) -m causalmesh.cli.main verify --all

analyze: ## Analyze the most recent experiment
	$(PYTHON) -m causalmesh.cli.main analyze --latest

report: ## Generate figures, tables and the report
	$(PYTHON) -m causalmesh.cli.main report --latest

reproduce: ## Full reproducibility sequence (spec §70)
	$(PYTHON) -m causalmesh.cli.main reproduce

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

clean: ## Remove caches and build artifacts (never touches data/raw)
	$(PYTHON) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
	$(PYTHON) -c "import shutil; [shutil.rmtree(d, ignore_errors=True) for d in ['.pytest_cache','.ruff_cache','.mypy_cache','build','dist']]"
	@echo "Caches cleared. data/raw is never touched by this target."
