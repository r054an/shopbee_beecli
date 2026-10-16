# ShopBee — "You said you needed it. Bee remembers."
.PHONY: help install test lint clean run pending add search cart dev

SHELL := /bin/bash
PYTHON ?= python3
VENV_DIR := .venv
SRC_DIRS := shopbee tests

## Show this help message
help:
	@echo "ShopBee — 'You said you needed it. Bee remembers.'"
	@echo ""
	@echo "Usage:"
	@echo "  make <target>"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

## Install dependencies and set up the project
install: ## Install ShopBee in development mode
	$(PYTHON) -m venv $(VENV_DIR)
	. $(VENV_DIR)/bin/activate && pip install --upgrade pip
	. $(VENV_DIR)/bin/activate && pip install -e ".[dev]"

## Run tests
test: ## Run the test suite
	. $(VENV_DIR)/bin/activate && pytest tests/ -v

## Run tests with coverage
coverage: ## Run tests with coverage report
	. $(VENV_DIR)/bin/activate && pytest tests/ --cov=shopbee --cov-report=term-missing -v

## Lint the codebase
lint: ## Check code style and type hints
	. $(VENV_DIR)/bin/activate && ruff check $(SRC_DIRS)
	. $(VENV_DIR)/bin/activate && mypy shopbee/

## Auto-fix linting issues
fix: ## Auto-fix linting issues with ruff
	. $(VENV_DIR)/bin/activate && ruff check --fix $(SRC_DIRS)

## Run ShopBee (finds pending shopping items)
run: ## Run ShopBee to find pending shopping items
	. $(VENV_DIR)/bin/activate && python -m shopbee pending

## Find pending shopping items
pending: ## Alias for 'make run'
	@$(MAKE) run

## Add a product to cart (usage: make add PRODUCT="USB-C cable")
add: ## Add product to cart
ifndef PRODUCT
	$(error Usage: make add PRODUCT="<product_name>")
endif
	. $(VENV_DIR)/bin/activate && python -m shopbee add "$(PRODUCT)"

## Search and add a product in one step (usage: make search QUERY="mechanical keyboard")
search: ## Search and add in one step
ifndef QUERY
	$(error Usage: make search QUERY="<query>")
endif
	. $(VENV_DIR)/bin/activate && python -m shopbee search "$(QUERY)"

## Build complete shopping cart from all sources
cart: ## Build the full shopping cart
	. $(VENV_DIR)/bin/activate && python -m shopbee cart

## Set up development environment with pre-commit hooks
dev: install ## Install dev dependencies and set up project
	@echo "ShopBee is ready to use!"
	@echo ""
	@echo "Quick start:"
	@echo "  make pending    # Find items you mentioned needing"
	@echo "  make add PRODUCT=\"USB-C cable\""
	@echo "  make search QUERY=\"mechanical keyboard\""

## Clean up build artifacts and cache files
clean: ## Remove generated files and caches
	rm -rf $(VENV_DIR) .pytest_cache .mypy_cache htmlcov coverage.xml
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
