.PHONY: help install install-dev test lint format type-check run clean docker-build docker-run

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install production dependencies
	poetry install --only=main

install-dev:  ## Install all dependencies including dev
	poetry install

install-aws:  ## Install with AWS dependencies
	poetry install --extras aws

install-local:  ## Install with local dependencies
	poetry install --extras local

install-all:  ## Install with all optional dependencies
	poetry install --extras all

test:  ## Run tests
	poetry run pytest

test-cov:  ## Run tests with coverage
	poetry run pytest --cov=app --cov-report=html --cov-report=term

lint:  ## Run linting
	poetry run ruff check app tests

format:  ## Format code
	poetry run ruff format app tests

check:  ## Run linting and formatting checks
	poetry run ruff check app tests
	poetry run ruff format --check app tests

type-check:  ## Run type checking
	poetry run mypy app

run:  ## Run the development server
	poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-prod:  ## Run the production server
	poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000

clean:  ## Clean up build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

docker-build:  ## Build Docker image
	docker build -t weather-api .

docker-run:  ## Run Docker container
	docker-compose up

docker-stop:  ## Stop Docker containers
	docker-compose down

setup-local-env:  ## Set up local development environment
	cp .env.example .env
	mkdir -p data/weather_files
	echo "Local environment setup complete. Edit .env file with your settings."