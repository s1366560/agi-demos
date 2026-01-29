# =============================================================================
# MemStack - Enterprise AI Memory Cloud Platform
# =============================================================================
# A comprehensive Makefile for managing the MemStack project including
# backend services, web frontend, SDK, testing, and development tools.
#
# Quick Start:
#   make init     - First time setup (install + start infra)
#   make dev      - Start development services
#   make reset    - Complete reset (stop + clean + reinit)
#   make fresh    - Fresh start from zero (reset + init + dev)
#
# Project Structure:
#   - src/          : Hexagonal architecture backend (Python)
#   - src/tests/    : Unit, integration, contract & performance tests
#   - web/          : React frontend (TypeScript/Vite)
#   - sdk/python/   : Python SDK
# =============================================================================

.PHONY: help install update clean init reset fresh restart
.PHONY: sandbox-build sandbox-run sandbox-run-tigervnc sandbox-stop sandbox-restart sandbox-logs sandbox-shell sandbox-root-shell sandbox-status sandbox-ps sandbox-test sandbox-clean sandbox-reset
.PHONY: sandbox-desktop-start sandbox-desktop-stop sandbox-desktop-status sandbox-desktop-logs
.PHONY: sandbox-terminal-start sandbox-terminal-stop sandbox-terminal-status sandbox-terminal-logs
.PHONY: sandbox-start-all sandbox-stop-all sandbox-all-status

# =============================================================================
# Default Target
# =============================================================================

help: ## Show this help message
	@echo "MemStack Development Commands"
	@echo "============================="
	@echo ""
	@echo "🚀 Quick Start:"
	@echo "  make init             - First time setup (install + infra)"
	@echo "  make dev              - Start all services (API + workers + web)"
	@echo "  make dev-web          - Start web frontend only"
	@echo "  make reset            - Complete reset (stop + clean + reinit)"
	@echo "  make fresh            - Fresh start from zero"
	@echo "  make restart          - Quick restart services"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make install          - Install all dependencies (backend + web)"
	@echo "  make install-backend  - Install backend dependencies only"
	@echo "  make install-web      - Install web dependencies only"
	@echo "  make update           - Update all dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make dev              - Start all services (API + workers + web + infra)"
	@echo "  make dev-stop         - Stop all background services"
	@echo "  make dev-logs         - View all service logs"
	@echo "  make dev-backend      - Start API server only (foreground)"
	@echo "  make dev-worker       - Start data processing worker only (foreground)"
	@echo "  make dev-agent-worker - Start agent worker only (foreground)"
	@echo "  make dev-mcp-worker   - Start MCP worker service only (foreground)"
	@echo "  make dev-web          - Start web development server only (foreground)"
	@echo "  make dev-web-stop     - Stop web development server"
	@echo "  make dev-infra        - Start infrastructure services (Neo4j, Postgres, Redis)"
	@echo ""
	@echo "Testing:"
	@echo "  make test             - Run all tests"
	@echo "  make test-unit        - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo "  make test-backend     - Run backend tests"
	@echo "  make test-web         - Run web tests"
	@echo "  make test-e2e         - Run end-to-end tests (Playwright)"
	@echo "  make test-coverage    - Run tests with coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  make format           - Format all code (Python + TypeScript)"
	@echo "  make format-backend   - Format Python code with ruff"
	@echo "  make format-web       - Format TypeScript code"
	@echo "  make lint             - Lint all code"
	@echo "  make lint-backend     - Lint Python code (ruff + mypy)"
	@echo "  make lint-web         - Lint TypeScript code"
	@echo "  make type-check       - Type check all code"
	@echo "  make check            - Run all quality checks (format + lint + test)"
	@echo ""
	@echo "Database:"
	@echo "  make db-init          - Initialize database (create if not exists)"
	@echo "  make db-reset         - Reset database (WARNING: deletes all data)"
	@echo "  make db-shell         - Open PostgreSQL shell"
	@echo "  make db-migrate       - Run Alembic migrations (upgrade to latest)"
	@echo "  make db-status        - Show Alembic migration status"
	@echo "  make db-history       - Show migration history"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up        - Start all Docker services"
	@echo "  make docker-down      - Stop all Docker services"
	@echo "  make docker-logs      - Show Docker service logs"
	@echo "  make docker-build     - Build Docker images"
	@echo "  make docker-clean     - Clean up containers, volumes, and orphans"
	@echo ""
	@echo "Sandbox (All-in-one Dev Environment):"
	@echo "  make sandbox-build        - Build sandbox Docker image"
	@echo "  make sandbox-run          - Start sandbox (x11vnc VNC, XFCE desktop)"
	@echo "  make sandbox-run-tigervnc - Start sandbox (TigerVNC, experimental)"
	@echo "  make sandbox-stop         - Stop sandbox container"
	@echo "  make sandbox-restart      - Restart sandbox container"
	@echo "  make sandbox-status       - Show status, VNC type, processes"
	@echo "  make sandbox-logs         - Show and follow logs"
	@echo "  make sandbox-shell        - Open sandbox shell (sandbox user)"
	@echo "  make sandbox-root-shell   - Open root shell in sandbox"
	@echo "  make sandbox-ps           - Show all running processes"
	@echo "  make sandbox-test         - Run VNC config validation test"
	@echo "  make sandbox-test-complete - Run complete XFCE 4.20 + VNC verification"
	@echo "  make sandbox-clean        - Remove container and volume"
	@echo "  make sandbox-reset        - Clean and rebuild sandbox"
	@echo ""
	@echo "Sandbox Desktop (XFCE4 + noVNC):"
	@echo "  make sandbox-desktop-status  - Show desktop & VNC processes"
	@echo "  make sandbox-desktop-logs    - Show desktop & VNC logs"
	@echo ""
	@echo "Sandbox Terminal (ttyd):"
	@echo "  make sandbox-terminal-status - Show terminal process"
	@echo "  make sandbox-terminal-logs   - Show terminal logs"
	@echo ""
	@echo "Production:"
	@echo "  make build            - Build all for production"
	@echo "  make build-backend    - Build backend"
	@echo "  make build-web        - Build web frontend"
	@echo "  make serve            - Start production server"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean            - Remove all generated files and caches"
	@echo "  make clean-backend    - Clean backend build artifacts"
	@echo "  make clean-web        - Clean web build artifacts"
	@echo "  make clean-docker     - Clean Docker volumes"
	@echo "  make clean-logs       - Clean log files"
	@echo "  make shell            - Open Python shell in project environment"
	@echo "  make get-api-key      - Show API key information"
	@echo "  make test-data        - Generate test data (default: 50 episodes)"
	@echo "  make hooks-install    - Install git hooks (pre-commit runs 'make check')"
	@echo "  make hooks-uninstall  - Uninstall git hooks"
	@echo ""
	@echo "Use 'make help' to show this message"

# =============================================================================
# Quick Start Commands (Environment Reset & Initialization)
# =============================================================================

init: ## First time setup: install deps, start infra
	@echo "🚀 Initializing MemStack development environment..."
	@echo ""
	@echo "Step 1/2: Installing dependencies..."
	@$(MAKE) install
	@echo ""
	@echo "Step 2/2: Starting infrastructure services..."
	@$(MAKE) dev-infra
	@sleep 3
	@echo ""
	@echo "✅ Environment initialized!"
	@echo ""
	@echo "📋 Default credentials (auto-created on first 'make dev'):"
	@echo "   Admin: admin@memstack.ai / adminpassword"
	@echo "   User:  user@memstack.ai  / userpassword"
	@echo ""
	@echo "🚀 Start development with: make dev"

reset: ## Complete reset: stop services, clean everything, prepare for reinit
	@echo "🔄 Resetting MemStack environment..."
	@echo ""
	@echo "Step 1/3: Stopping all services..."
	@$(MAKE) dev-stop 2>/dev/null || true
	@echo ""
	@echo "Step 2/3: Cleaning Docker volumes and containers..."
	@docker compose down -v --remove-orphans 2>/dev/null || true
	@echo ""
	@echo "Step 3/3: Cleaning build artifacts and logs..."
	@$(MAKE) clean-backend
	@$(MAKE) clean-logs
	@echo ""
	@echo "✅ Environment reset complete!"
	@echo ""
	@echo "🚀 Reinitialize with: make init"
	@echo "🚀 Or start fresh with: make fresh"

fresh: reset init dev ## Fresh start: reset everything and start development
	@echo ""
	@echo "✅ Fresh environment ready!"

restart: dev-stop dev ## Quick restart: stop and start services
	@echo "✅ Services restarted"

reset-db: ## Reset only the database (keep Docker volumes)
	@echo "🗄️  Resetting database only..."
	@docker compose exec -T postgres psql -U postgres -c "DROP DATABASE IF EXISTS memstack;" 2>/dev/null || true
	@docker compose exec -T postgres psql -U postgres -c "CREATE DATABASE memstack;" 2>/dev/null || true
	@$(MAKE) db-schema
	@echo "✅ Database reset complete (default data will be created on next 'make dev')"

reset-hard: ## Hard reset: remove all Docker data including images
	@echo "⚠️  WARNING: This will remove ALL Docker data including images!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(MAKE) dev-stop 2>/dev/null || true; \
		docker compose down -v --remove-orphans --rmi local 2>/dev/null || true; \
		$(MAKE) clean; \
		echo "✅ Hard reset complete"; \
		echo ""; \
		echo "🚀 Reinitialize with: make init"; \
	else \
		echo "❌ Aborted"; \
	fi

# =============================================================================
# Setup & Installation
# =============================================================================

install: install-backend install-web ## Install all dependencies
	@echo "✅ All dependencies installed"

install-backend: ## Install backend Python dependencies
	@echo "📦 Installing backend dependencies..."
	uv sync --extra dev --extra neo4j --extra evaluation
	@echo "✅ Backend dependencies installed"

install-web: ## Install web frontend dependencies
	@echo "📦 Installing web dependencies..."
	cd web && pnpm install
	@echo "✅ Web dependencies installed"

update: ## Update all dependencies
	@echo "📦 Updating dependencies..."
	uv lock --upgrade
	cd web && pnpm update
	@echo "✅ Dependencies updated"

# =============================================================================
# Development
# =============================================================================

dev: dev-all ## Start all services (API + worker + infra + web)
	@echo "🚀 Starting full development environment..."

dev-all: dev-infra db-init
	@echo "🚀 Starting API server, Temporal worker, Agent worker, MCP worker and Web in background..."
	@echo "   API: http://localhost:8000 (logs: logs/api.log)"
	@echo "   Web: http://localhost:3000 (logs: logs/web.log)"
	@echo "   Data Worker: running in background (logs: logs/worker.log)"
	@echo "   Agent Worker: running in background (logs: logs/agent-worker.log)"
	@echo "   MCP Worker: running in background (logs: logs/mcp-worker.log)"
	@mkdir -p logs
	@nohup uv run uvicorn src.infrastructure.adapters.primary.web.main:app --reload --host 0.0.0.0 --port 8000 > logs/api.log 2>&1 & echo $$! > logs/api.pid
	@nohup uv run python src/worker_temporal.py > logs/worker.log 2>&1 & echo $$! > logs/worker.pid
	@nohup uv run python src/agent_worker.py > logs/agent-worker.log 2>&1 & echo $$! > logs/agent-worker.pid
	@nohup uv run python src/worker_mcp.py > logs/mcp-worker.log 2>&1 & echo $$! > logs/mcp-worker.pid
	@(cd web && nohup pnpm run dev > ../logs/web.log 2>&1) & echo $$! > logs/web.pid
	@sleep 3
	@echo "✅ Services started!"
	@echo ""
	@echo "View logs with:"
	@echo "  tail -f logs/api.log            # API server logs"
	@echo "  tail -f logs/web.log            # Web frontend logs"
	@echo "  tail -f logs/worker.log         # Data Worker logs"
	@echo "  tail -f logs/agent-worker.log   # Agent Worker logs"
	@echo "  tail -f logs/mcp-worker.log     # MCP Worker logs"
	@echo ""
	@echo "Stop services with:"
	@echo "  make dev-stop"

dev-stop: ## Stop all background services
	@echo "🛑 Stopping background services..."
	@# Stop API (with port 8000 fallback)
	@if [ -f logs/api.pid ]; then \
		PID=$$(cat logs/api.pid); \
		kill -TERM -- -$$PID 2>/dev/null || kill -TERM $$PID 2>/dev/null || true; \
		rm -f logs/api.pid; \
	fi; \
	PORT_PID=$$(lsof -ti :8000 2>/dev/null); \
	if [ -n "$$PORT_PID" ]; then \
		kill -TERM $$PORT_PID 2>/dev/null || true; \
		sleep 0.5; \
		kill -9 $$PORT_PID 2>/dev/null || true; \
	fi; \
	echo "✅ API stopped"
	@# Stop Web (with port 3000 fallback)
	@if [ -f logs/web.pid ]; then \
		PID=$$(cat logs/web.pid); \
		kill -TERM -- -$$PID 2>/dev/null || kill -TERM $$PID 2>/dev/null || true; \
		rm -f logs/web.pid; \
	fi; \
	PORT_PID=$$(lsof -ti :3000 2>/dev/null); \
	if [ -n "$$PORT_PID" ]; then \
		kill -TERM $$PORT_PID 2>/dev/null || true; \
		sleep 0.5; \
		kill -9 $$PORT_PID 2>/dev/null || true; \
	fi; \
	echo "✅ Web stopped"
	@# Stop Data Worker
	@if [ -f logs/worker.pid ]; then \
		PID=$$(cat logs/worker.pid); \
		kill -TERM -- -$$PID 2>/dev/null || kill -TERM $$PID 2>/dev/null || true; \
		rm -f logs/worker.pid; \
	fi; \
	echo "✅ Data Worker stopped"
	@# Stop Agent Worker
	@if [ -f logs/agent-worker.pid ]; then \
		PID=$$(cat logs/agent-worker.pid); \
		kill -TERM -- -$$PID 2>/dev/null || kill -TERM $$PID 2>/dev/null || true; \
		rm -f logs/agent-worker.pid; \
	fi; \
	echo "✅ Agent Worker stopped"
	@# Stop MCP Worker
	@if [ -f logs/mcp-worker.pid ]; then \
		PID=$$(cat logs/mcp-worker.pid); \
		kill -TERM -- -$$PID 2>/dev/null || kill -TERM $$PID 2>/dev/null || true; \
		rm -f logs/mcp-worker.pid; \
	fi; \
	echo "✅ MCP Worker stopped"
	@# Fallback: kill any remaining worker processes by name
	@pkill -9 -f "src/worker_temporal.py" 2>/dev/null || true
	@pkill -9 -f "src/agent_worker.py" 2>/dev/null || true
	@pkill -9 -f "src/worker_mcp.py" 2>/dev/null || true
	@pkill -9 -f "uv run python src/" 2>/dev/null || true
	@pkill -9 -f "uvicorn src.infrastructure" 2>/dev/null || true
	@pkill -9 -f "vite" 2>/dev/null || true
	@echo "✅ All services stopped"

dev-logs: ## Show all service logs (follow mode)
	@echo "📋 Showing logs (Ctrl+C to exit)..."
	@tail -f logs/api.log logs/web.log logs/worker.log logs/agent-worker.log logs/mcp-worker.log

dev-backend: ## Start backend development server with hot reload (API only, foreground)
	@echo "🚀 Starting backend API server..."
	uv run uvicorn src.infrastructure.adapters.primary.web.main:app --reload --host 0.0.0.0 --port 8000

dev-worker: ## Start worker service only (foreground)
	@echo "🔧 Starting data processing worker service with hot reload..."
	uv run watchmedo auto-restart --directory src --pattern "*.py" --recursive -- python src/worker_temporal.py

dev-agent-worker: ## Start agent worker service only (foreground)
	@echo "🔧 Starting agent worker service..."
	uv run python src/agent_worker.py

dev-mcp-worker: ## Start MCP worker service only (foreground)
	@echo "🔧 Starting MCP worker service..."
	uv run python src/worker_mcp.py

dev-web: ## Start web development server
	@echo "🚀 Starting web development server..."
	@if lsof -i :3000 2>/dev/null | grep -q LISTEN; then \
		echo "❌ Port 3000 is already in use. Stop existing process first with: make dev-web-stop"; \
		exit 1; \
	fi
	cd web && pnpm run dev

dev-web-stop: ## Stop web development server (kill process on port 3000)
	@echo "🛑 Stopping web development server..."
	@PID=$$(lsof -ti :3000 2>/dev/null); \
	if [ -n "$$PID" ]; then \
		kill $$PID 2>/dev/null && echo "✅ Web server stopped (PID: $$PID)"; \
	else \
		echo "ℹ️  No web server running on port 3000"; \
	fi

dev-infra: ## Start infrastructure services only
	@echo "🚀 Starting infrastructure services..."
	docker compose up -d neo4j postgres redis minio minio-setup temporal temporal-ui
	@echo "✅ Infrastructure services started"
	@echo "   Neo4j: http://localhost:7474"
	@echo "   Postgres: localhost:5432"
	@echo "   Redis: localhost:6379"
	@echo "   MinIO: http://localhost:9000 (console: http://localhost:9001)"
	@echo "   Temporal: http://localhost:7233 (console: http://localhost:8080/namespaces/default)"

status: ## Show status of all services
	@echo "📊 Service Status"
	@echo "================"
	@echo ""
	@echo "Docker Services:"
	@docker compose ps 2>/dev/null || echo "  Docker not running"
	@echo ""
	@echo "Background Processes:"
	@if [ -f logs/api.pid ] && kill -0 $$(cat logs/api.pid) 2>/dev/null; then \
		echo "  API Server: ✅ Running (PID: $$(cat logs/api.pid))"; \
	else \
		echo "  API Server: ❌ Not running"; \
	fi
	@if [ -f logs/web.pid ] && kill -0 $$(cat logs/web.pid) 2>/dev/null; then \
		echo "  Web Frontend: ✅ Running (PID: $$(cat logs/web.pid))"; \
	else \
		echo "  Web Frontend: ❌ Not running"; \
	fi
	@if [ -f logs/worker.pid ] && kill -0 $$(cat logs/worker.pid) 2>/dev/null; then \
		echo "  Data Worker: ✅ Running (PID: $$(cat logs/worker.pid))"; \
	else \
		echo "  Data Worker: ❌ Not running"; \
	fi
	@if [ -f logs/agent-worker.pid ] && kill -0 $$(cat logs/agent-worker.pid) 2>/dev/null; then \
		echo "  Agent Worker: ✅ Running (PID: $$(cat logs/agent-worker.pid))"; \
	else \
		echo "  Agent Worker: ❌ Not running"; \
	fi
	@if [ -f logs/mcp-worker.pid ] && kill -0 $$(cat logs/mcp-worker.pid) 2>/dev/null; then \
		echo "  MCP Worker: ✅ Running (PID: $$(cat logs/mcp-worker.pid))"; \
	else \
		echo "  MCP Worker: ❌ Not running"; \
	fi
	@echo ""
	@echo "Ports:"
	@lsof -i :8000 2>/dev/null | grep -q LISTEN && echo "  8000 (API): ✅ In use" || echo "  8000 (API): ❌ Free"
	@lsof -i :3000 2>/dev/null | grep -q LISTEN && echo "  3000 (Web): ✅ In use" || echo "  3000 (Web): ❌ Free"
	@lsof -i :5432 2>/dev/null | grep -q LISTEN && echo "  5432 (Postgres): ✅ In use" || echo "  5432 (Postgres): ❌ Free"
	@lsof -i :7687 2>/dev/null | grep -q LISTEN && echo "  7687 (Neo4j): ✅ In use" || echo "  7687 (Neo4j): ❌ Free"
	@lsof -i :6379 2>/dev/null | grep -q LISTEN && echo "  6379 (Redis): ✅ In use" || echo "  6379 (Redis): ❌ Free"
	@lsof -i :9000 2>/dev/null | grep -q LISTEN && echo "  9000 (MinIO): ✅ In use" || echo "  9000 (MinIO): ❌ Free"
	@lsof -i :7233 2>/dev/null | grep -q LISTEN && echo "  7233 (Temporal): ✅ In use" || echo "  7233 (Temporal): ❌ Free"
	@lsof -i :6080 2>/dev/null | grep -q LISTEN && echo "  6080 (Desktop): ✅ In use" || echo "  6080 (Desktop): ❌ Free"
	@lsof -i :7681 2>/dev/null | grep -q LISTEN && echo "  7681 (Terminal): ✅ In use" || echo "  7681 (Terminal): ❌ Free"

# =============================================================================
# Testing
# =============================================================================

test: test-backend test-web ## Run all tests
	@echo "✅ All tests completed"

test-backend: ## Run backend tests
	@echo "🧪 Running backend tests..."
	uv run pytest src/tests/ -v --tb=short

test-unit: ## Run unit tests only
	@echo "🧪 Running unit tests..."
	uv run pytest src/tests/ -m "not integration" -v --tb=short

test-integration: ## Run integration tests only
	@echo "🧪 Running integration tests..."
	uv run pytest src/tests/ -m "integration" -v --tb=short

test-performance: ## Run performance tests only (requires perf infra)
	@echo "🧪 Running performance tests..."
	uv run pytest src/tests/ -m "performance" -v --tb=short

test-web: ## Run web tests
	@echo "🧪 Running web tests..."
	cd web && pnpm run test

test-e2e: ## Run end-to-end tests (requires services running)
	@echo "🧪 Running E2E tests..."
	cd web && pnpm run test:e2e

test-coverage: ## Run tests with coverage report
	@echo "🧪 Running tests with coverage..."
	uv run pytest src/tests/ --cov=src --cov-report=html --cov-report=term-missing --cov-fail-under=80
	@echo "📊 Coverage report generated: htmlcov/index.html"

test-watch: ## Run tests in watch mode
	@echo "🧪 Running tests in watch mode..."
	uv run pytest src/tests/ -f

# =============================================================================
# Code Quality
# =============================================================================

format: format-backend format-web ## Format all code
	@echo "✅ All code formatted"

format-backend: ## Format Python code
	@echo "🎨 Formatting Python code..."
	uv run ruff check --fix src/ sdk/
	uv run ruff format src/ sdk/
	@echo "✅ Python code formatted"

format-web: ## Format TypeScript code
	@echo "🎨 Formatting TypeScript code..."
	cd web && pnpm run lint --fix
	@echo "✅ TypeScript code formatted"

lint: lint-backend lint-web ## Lint all code
	@echo "✅ All code linted"

lint-backend: ## Lint Python code
	@echo "🔍 Linting Python code..."
	uv run ruff check src/ sdk/
	uv run mypy src/ --ignore-missing-imports
	@echo "✅ Python code linted"

lint-web: ## Lint TypeScript code
	@echo "🔍 Linting TypeScript code..."
	cd web && pnpm run lint
	cd web && pnpm run type-check
	@echo "✅ TypeScript code linted"

type-check: lint-backend ## Type check all code (alias for lint-backend)

check: format lint test ## Run all quality checks
	@echo "✅ All quality checks passed"

# =============================================================================
# Git Hooks
# =============================================================================
.PHONY: hooks-install hooks-uninstall

hooks-install: ## Install git hooks (requires git)
	@echo "🔧 Installing git hooks..."
	@git config core.hooksPath .githooks
	@chmod +x .githooks/pre-commit
	@echo "✅ Git hooks installed (pre-commit will run 'make check')"

hooks-uninstall: ## Uninstall git hooks (restore default hooks path)
	@echo "🔧 Uninstalling git hooks..."
	@git config --unset core.hooksPath || true
	@echo "✅ Git hooks uninstalled"

# =============================================================================
# Database
# =============================================================================

db-init: ## Initialize database (create if not exists)
	@echo "🗄️  Initializing database..."
	@if docker compose exec -T postgres psql -U postgres -lqt | grep -q memstack; then \
		echo "✓ Database 'memstack' already exists"; \
	else \
		echo "Creating database 'memstack'..."; \
		docker compose exec -T postgres psql -U postgres -c "CREATE DATABASE memstack;"; \
		echo "✓ Database created"; \
	fi
	@echo "✅ Database ready (Run 'make db-schema' to initialize schema)"

db-reset: ## Reset database (WARNING: deletes all data)
	@echo "⚠️  WARNING: This will delete all data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		echo "🗑️  Dropping database..."; \
		docker compose exec -T postgres psql -U postgres -c "DROP DATABASE IF EXISTS memstack;"; \
		echo "📦 Creating new database..."; \
		docker compose exec -T postgres psql -U postgres -c "CREATE DATABASE memstack;"; \
		echo "🔄 Initializing schema..."; \
		$(MAKE) db-schema; \
		echo "✅ Database reset completed"; \
		echo ""; \
		echo "📋 Default credentials (auto-created on next 'make dev'):"; \
		echo "   Admin: admin@memstack.ai / adminpassword"; \
		echo "   User:  user@memstack.ai  / userpassword"; \
	else \
		echo "❌ Aborted"; \
	fi

db-shell: ## Open PostgreSQL shell
	@echo "🐚 Opening PostgreSQL shell..."
	docker compose exec postgres psql -U postgres memstack

db-schema: ## Initialize database schema (create tables)
	@echo "🏗️  Initializing database schema..."
	@PYTHONPATH=. uv run python -c \
		"import asyncio; from src.infrastructure.adapters.secondary.persistence.database import initialize_database; asyncio.run(initialize_database())"
	@echo "✅ Schema initialized"

db-migrate-messages: ## Migrate messages table to unified event timeline (one-time migration)
	@echo "🔄 Migrating messages to unified event timeline..."
	@PYTHONPATH=. uv run python -c \
		"import asyncio; from src.infrastructure.adapters.secondary.persistence.database import migrate_messages_to_events; asyncio.run(migrate_messages_to_events())"
	@echo "✅ Migration completed"

# =============================================================================
# Docker
# =============================================================================

docker-up: ## Start all Docker services
	@echo "🐳 Starting Docker services..."
	docker compose up -d
	@echo "✅ Docker services started"
	@echo "   API: http://localhost:8000"
	@echo "   Web: http://localhost:3000"
	@echo "   Neo4j: http://localhost:7474"
	@docker compose ps

docker-down: ## Stop all Docker services
	@echo "🐳 Stopping Docker services..."
	docker compose down
	@echo "✅ Docker services stopped"

docker-logs: ## Show Docker service logs
	docker compose logs -f

docker-build: ## Build Docker images
	@echo "🐳 Building Docker images..."
	docker compose build
	@echo "✅ Docker images built"

docker-restart: docker-down docker-up ## Restart Docker services

docker-clean: ## Clean up containers, volumes, and orphans
	@echo "🧹 Cleaning Docker containers and volumes..."
	docker compose down -v --remove-orphans
	@echo "✅ Docker containers and volumes cleaned"

# =============================================================================
# Sandbox MCP Server - All-in-one development environment
# =============================================================================
# Services: MCP Server (8765), noVNC Desktop (6080), Web Terminal (7681)
# Desktop: XFCE4 (lightweight, container-friendly)
# VNC: x11vnc (default, no-password) or TigerVNC (experimental)
# =============================================================================

SANDBOX_PORT?=8765
SANDBOX_DESKTOP_PORT?=6080
SANDBOX_TERMINAL_PORT?=7681
SANDBOX_NAME?=sandbox-mcp-server
SANDBOX_VNC?=tigervnc  # Options: tigervnc (default, high-performance), x11vnc (fallback, stable)

sandbox-build: ## Build sandbox MCP server Docker image
	@echo "🏗️  Building sandbox MCP server image..."
	cd sandbox-mcp-server && docker build -t $(SANDBOX_NAME):latest .
	@echo "✅ Sandbox image built"
	@docker images | grep $(SANDBOX_NAME) | head -1

sandbox-run: ## Start sandbox container (with XFCE desktop, TigerVNC by default)
	@echo "🚀 Starting sandbox MCP server with XFCE Desktop ($(SANDBOX_VNC) VNC)..."
	@if docker ps --format '{{.Names}}' | grep -q "^$(SANDBOX_NAME)$$"; then \
		echo "⚠️  Sandbox already running. Stop with: make sandbox-stop"; \
	else \
		if docker run -d --name $(SANDBOX_NAME) \
			-p $(SANDBOX_PORT):8765 \
			-p $(SANDBOX_DESKTOP_PORT):6080 \
			-p $(SANDBOX_TERMINAL_PORT):7681 \
			-v sandbox-workspace:/workspace \
			-e VNC_SERVER_TYPE=$(SANDBOX_VNC) \
			-e DESKTOP_RESOLUTION=$(DESKTOP_RESOLUTION) \
			--memory=4g --cpus=3 \
			--shm-size=1g \
			$(SANDBOX_NAME):latest; then \
			sleep 5; \
			echo "✅ Sandbox started"; \
			echo ""; \
			echo "   Service Endpoints:"; \
			echo "   • MCP Server:    ws://localhost:$(SANDBOX_PORT)"; \
			echo "   • Health Check:  http://localhost:$(SANDBOX_PORT)/health"; \
			echo "   • Remote Desktop: http://localhost:$(SANDBOX_DESKTOP_PORT)/vnc.html"; \
			echo "   • Web Terminal:  ws://localhost:$(SANDBOX_TERMINAL_PORT)"; \
			echo ""; \
			echo "   VNC Server: $(SANDBOX_VNC)"; \
			echo ""; \
			curl -s http://localhost:$(SANDBOX_PORT)/health | jq . 2>/dev/null || true; \
		else \
			echo "❌ Failed to start sandbox container"; \
			exit 1; \
		fi \
	fi

sandbox-stop: ## Stop sandbox MCP server container
	@echo "🛑 Stopping sandbox..."
	@docker stop $(SANDBOX_NAME) 2>/dev/null && docker rm $(SANDBOX_NAME) 2>/dev/null && echo "✅ Sandbox stopped" || echo "ℹ️  Sandbox not running"

sandbox-restart: sandbox-stop sandbox-run ## Restart sandbox container

# Run with specific VNC server types
sandbox-run-x11vnc: ## Start sandbox with x11vnc (stable fallback)
	@echo "🚀 Starting sandbox with x11vnc (stable fallback)..."
	@$(MAKE) sandbox-run SANDBOX_VNC=x11vnc

sandbox-run-tigervnc: ## Start sandbox with TigerVNC (default)
	@echo "🚀 Starting sandbox with TigerVNC (default, high-performance)..."
	@$(MAKE) sandbox-run SANDBOX_VNC=tigervnc

sandbox-logs: ## Show sandbox container logs
	@docker logs -f $(SANDBOX_NAME) 2>/dev/null || echo "ℹ️  Sandbox not running"

sandbox-shell: ## Open shell in sandbox container
	@echo "🐚 Opening sandbox shell..."
	@docker exec -it $(SANDBOX_NAME) bash 2>/dev/null || echo "ℹ️  Sandbox not running. Start with: make sandbox-run"

sandbox-status: ## Show sandbox status, services, and VNC type
	@echo "📊 Sandbox Status"
	@echo "================"
	@if docker ps --format '{{.Names}}' | grep -q "^$(SANDBOX_NAME)$$"; then \
		echo "Status: ✅ Running"; \
		echo ""; \
		docker exec $(SANDBOX_NAME) bash -c 'echo "VNC Server: $$VNC_SERVER_TYPE"' 2>/dev/null || echo "VNC: unknown"; \
		echo ""; \
		docker exec $(SANDBOX_NAME) ps aux | grep -E "vnc|xfce|ttyd" | grep -v grep || echo "No services found"; \
		echo ""; \
		curl -s http://localhost:$(SANDBOX_PORT)/health | jq . 2>/dev/null || echo "Health check: failed"; \
	else \
		echo "Status: ❌ Not running"; \
		echo ""; \
		echo "Start with: make sandbox-run"; \
	fi

sandbox-clean: ## Remove sandbox container and volume
	@echo "🧹 Cleaning sandbox..."
	@docker stop $(SANDBOX_NAME) 2>/dev/null || true
	@docker rm $(SANDBOX_NAME) 2>/dev/null || true
	@docker volume rm sandbox-workspace 2>/dev/null || true
	@echo "✅ Sandbox cleaned"

sandbox-reset: sandbox-clean sandbox-build ## Reset sandbox (clean + rebuild)

sandbox-ps: ## Show all running processes in sandbox
	@echo "📋 Sandbox Processes"
	@echo "==================="
	@docker exec $(SANDBOX_NAME) ps aux 2>/dev/null || echo "Sandbox not running"

sandbox-root-shell: ## Open root shell in sandbox container
	@echo "🔓 Opening root shell in sandbox..."
	@docker exec -it -u root $(SANDBOX_NAME) bash 2>/dev/null || echo "ℹ️  Sandbox not running. Start with: make sandbox-run"

sandbox-test: ## Run VNC configuration validation test
	@echo "🧪 Running VNC config validation..."
	@docker exec $(SANDBOX_NAME) bash /etc/vnc/test-vnc-config.sh 2>/dev/null || echo "Sandbox not running or test script not found"

sandbox-test-complete: ## Run complete XFCE 4.20 + VNC setup verification
	@echo "🧪 Running complete setup verification..."
	@docker exec $(SANDBOX_NAME) bash /etc/vnc/test-complete-setup.sh 2>/dev/null || echo "Sandbox not running or test script not found"

# =============================================================================
# Sandbox Desktop (noVNC) - Remote Desktop Access
# =============================================================================

DESKTOP_PORT?=6080
DESKTOP_DISPLAY?=:0
DESKTOP_RESOLUTION?=1920x1080

sandbox-desktop-start: ## (Deprecated) Desktop starts automatically with container
	@echo "ℹ️  Desktop starts automatically with the container. Use 'make sandbox-run'."

sandbox-desktop-stop: ## (Deprecated) Desktop stops when container stops
	@echo "ℹ️  Desktop stops when container stops. Use 'make sandbox-stop'."

sandbox-desktop-status: ## Show desktop component status in sandbox
	@echo "📊 Desktop Component Status"
	@echo "==========================="
	@docker exec $(SANDBOX_NAME) ps aux | grep -E "xfce|Xvnc|x11vnc|vncserver" | grep -v grep || echo "No desktop processes. Sandbox running?"

sandbox-desktop-logs: ## Show desktop & VNC logs from sandbox
	@echo "📋 Desktop & VNC logs..."
	@docker logs $(SANDBOX_NAME) 2>/dev/null | grep -iE "vnc|xfce|desktop" | tail -30 || echo "No desktop logs. Sandbox running?"

# =============================================================================
# Sandbox Terminal (ttyd) - Web Terminal Access
# =============================================================================

TERMINAL_PORT?=7681

sandbox-terminal-start: ## (Deprecated) Terminal starts automatically with container
	@echo "ℹ️  Terminal starts automatically with the container. Use 'make sandbox-run'."

sandbox-terminal-stop: ## (Deprecated) Terminal stops when container stops
	@echo "ℹ️  Terminal stops when container stops. Use 'make sandbox-stop'."

sandbox-terminal-status: ## Show web terminal status
	@echo "📊 Terminal Status"
	@echo "================"
	@if docker exec $(SANDBOX_NAME) ps aux | grep -q ttyd; then \
		echo "Status: ✅ Running"; \
		docker exec $(SANDBOX_NAME) ps aux | grep ttyd | grep -v grep; \
	else \
		echo "Status: ❌ Not running"; \
	fi

sandbox-terminal-logs: ## Show terminal logs from sandbox container
	@echo "📋 Terminal logs..."
	@docker logs $(SANDBOX_NAME) 2>/dev/null | grep -i ttyd || echo "No terminal logs found. Sandbox running?"

sandbox-start-all: sandbox-run ## Start all sandbox services (alias for sandbox-run)
	@echo "✅ All sandbox services started"

sandbox-stop-all: sandbox-stop ## Stop all sandbox services (alias for sandbox-stop)
	@echo "✅ All sandbox services stopped"

sandbox-all-status: sandbox-status ## Show all sandbox services status (alias for sandbox-status)

# =============================================================================
# Production
# =============================================================================

build: build-backend build-web ## Build all for production
	@echo "✅ Build completed"

build-backend: ## Build backend for production
	@echo "🏗️  Building backend..."
	@echo "✅ Backend built"

build-web: ## Build web frontend for production
	@echo "🏗️  Building web frontend..."
	cd web && pnpm run build
	@echo "✅ Web frontend built"

serve: ## Start production server
	@echo "🚀 Starting production server..."
	uv run uvicorn src.infrastructure.adapters.primary.web.main:app --host 0.0.0.0 --port 8000 --workers 4

# =============================================================================
# Utilities
# =============================================================================

clean: clean-backend clean-web clean-docker ## Remove all generated files and caches
	@echo "✅ All cleaned up"

clean-backend: ## Clean backend build artifacts
	@echo "🧹 Cleaning backend artifacts..."
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info
	rm -rf logs
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	@echo "✅ Backend artifacts cleaned"

clean-web: ## Clean web build artifacts
	@echo "🧹 Cleaning web artifacts..."
	cd web && rm -rf node_modules/.vite
	cd web && rm -rf dist
	@echo "✅ Web artifacts cleaned"

clean-docker: ## Clean Docker volumes
	@echo "🧹 Cleaning Docker volumes..."
	@docker compose down -v 2>/dev/null || echo "No Docker volumes to clean"
	@echo "✅ Docker volumes cleaned"

clean-logs: ## Clean log files
	@echo "🧹 Cleaning logs..."
	rm -rf logs
	@echo "✅ Logs cleaned"

shell: ## Open Python shell in project environment
	@echo "🐚 Opening Python shell..."
	uv run python

shell-ipython: ## Open IPython shell in project environment
	@echo "🐚 Opening IPython shell..."
	uv run ipython

get-api-key: ## Show API key information
	@echo "🔑 API Key Information:"
	@echo ""
	@echo "To get an API key, you need to:"
	@echo "1. Start the dev server: make dev"
	@echo "2. Register a user at http://localhost:8000/docs#/auth/register"
	@echo "3. Login at http://localhost:8000/docs#/auth/login"
	@echo "4. Copy the access_token from the response"
	@echo ""
	@echo "Then use it in your requests:"
	@echo "  Authorization: Bearer <your-token>"

# =============================================================================
# Test Data Generation
# =============================================================================

COUNT?=50
USER_NAME?="Alice Johnson"
PROJECT_NAME?="Alpha Research"
DAYS?=7

test-data: ## Generate test data (default: 50 random episodes)
	@echo "📊 Generating test data..."
	uv run python scripts/generate_test_data.py --count $(COUNT) --mode random
	@echo "✅ Test data generated"

test-data-user: ## Generate user activity series
	@echo "📊 Generating user activity data..."
	uv run python scripts/generate_test_data.py --mode user-series --user-name "$(USER_NAME)" --days $(DAYS)
	@echo "✅ User activity data generated"

test-data-collab: ## Generate project collaboration data
	@echo "📊 Generating collaboration data..."
	uv run python scripts/generate_test_data.py --mode collaboration --project-name "$(PROJECT_NAME)" --days $(DAYS)
	@echo "✅ Collaboration data generated"

# =============================================================================
# SDK Commands
# =============================================================================

sdk-install: ## Install SDK in development mode
	@echo "📦 Installing SDK..."
	cd sdk/python && pip install -e ".[dev]"
	@echo "✅ SDK installed"

sdk-test: ## Run SDK tests
	@echo "🧪 Testing SDK..."
	cd sdk/python && pytest tests/ --cov=memstack --cov-report=term-missing
	@echo "✅ SDK tests completed"

sdk-build: ## Build SDK package
	@echo "🏗️  Building SDK..."
	cd sdk/python && python -m build
	@echo "✅ SDK built"

# =============================================================================
# CI/CD Support
# =============================================================================

ci-install: install ## Install dependencies for CI
	@echo "✅ CI dependencies installed"

ci-lint: lint ## Run linting for CI
	@echo "✅ CI linting passed"

ci-test: test ## Run tests for CI
	@echo "✅ CI tests passed"

ci-build: build ## Build for CI
	@echo "✅ CI build completed"

ci: ci-lint ci-test ci-build ## Run complete CI pipeline
	@echo "✅ CI pipeline completed successfully"

# =============================================================================
# Miscellaneous
# =============================================================================

.DEFAULT_GOAL := help
