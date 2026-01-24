# MemStack - Gemini CLI Context

This document provides an overview of the MemStack project, intended to serve as instructional context for Gemini CLI interactions.

## Project Overview

**MemStack** is an enterprise-grade AI Memory Cloud Platform designed to provide robust long-term and short-term memory management capabilities for AI applications and agents. It is built upon the open-source project [Graphiti](https://github.com/getzep/graphiti) and supports various Large Language Model (LLM) providers, including Google Gemini.

### Core Features:
-   **Dynamic Knowledge Integration**: Real-time integration of conversational data, structured business data, and external information.
-   **Temporal Awareness**: Dual-timestamp model for precise historical querying.
-   **High-Performance Retrieval**: Hybrid retrieval mechanisms (semantic + keyword + graph traversal).
-   **API Key Authentication**: Secure authentication with access control.
-   **Comprehensive SDK**: Python synchronous/asynchronous clients with retry and error handling.
-   **Web Console**: React-based visual management interface.
-   **Memos**: Lightweight record-keeping similar to Flomo, with tagging and privacy control.
-   **Graph Visualization**: Interactive knowledge graph display.
-   **High Test Coverage**: Over 80% test coverage with continuous integration.
-   **Multi-LLM Support**: Integrates with Google Gemini, Alibaba Cloud Qwen, Deepseek, ZhipuAI, OpenAI, etc.

### Key Technologies:
-   **Backend**: Python (3.12+), FastAPI (0.110+), Neo4j (5.26+), PostgreSQL (16+), Redis (7+).
-   **Frontend**: React, Node.js (18+), Ant Design.
-   **Build Tools**: Docker, Docker Compose, `make`, `uv`, `pnpm`.

### Architecture:
MemStack employs a three-tiered architecture:
1.  **Server (FastAPI Backend)**: Handles REST API endpoints, business logic, Graphiti integration, Pydantic data models, LLM provider integrations, authentication, and configuration.
2.  **SDK (Python Client)**: Provides synchronous and asynchronous HTTP clients, request/response models, and exception definitions for interacting with the MemStack API.
3.  **Web (React Console)**: A user interface for managing episodes, searching memory, and visualizing the knowledge graph, built with React components and services.

## Building and Running

### Prerequisites:
-   **Python**: 3.12+
-   **Node.js**: 18+ (for Web development)
-   **Neo4j**: 5.26+
-   **PostgreSQL**: 16+ (optional, for metadata)
-   **Redis**: 7+ (optional, for caching)
-   **LLM API**: Access to a supported LLM provider (e.g., Google Gemini API Key).

### Setup and Configuration:
1.  **Clone the repository:**
    ```bash
    git clone https://github.com/s1366560/memstack.git
    cd memstack
    ```
2.  **Install dependencies:**
    ```bash
    uv sync --extra dev  # Recommended
    # or
    pip install -e ".[dev,neo4j,evaluation]"
    ```
3.  **Configure environment variables:**
    ```bash
    cp .env.example .env
    # Edit .env to set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, LLM_PROVIDER, and LLM API keys.
    ```

### Starting Services:

#### Recommended (Docker Compose):
```bash
docker-compose up -d
```

#### Local Development:
1.  **Start dependent services (Neo4j, PostgreSQL, Redis):**
    ```bash
    make docker-up
    ```
2.  **Start API service (FastAPI):**
    ```bash
    make dev  # Access at http://localhost:8000
    ```
3.  **Start Web console (React) in a new terminal:**
    ```bash
    cd web
    pnpm install
    pnpm run dev  # Access at http://localhost:3000
    ```

### Verification:
-   **Health check:** `curl http://localhost:8000/health`
-   **API Documentation:** `open http://localhost:8000/docs`

## Development Conventions

### Code Style and Quality:
-   **Python:** Adheres to PEP 8.
-   **Formatting & Linting:** Uses `Ruff` for Python code.
-   **Type Checking:** Uses `MyPy` for Python code.
-   **Web:** `eslint.config.js` and `postcss.config.js` are present for frontend code style.

### Testing:
-   **Test Suite:** Can be run via `make test`.
-   **Unit Tests:** `make test-unit`.
-   **Integration Tests:** `make test-integration`.
-   **Coverage:** Current test coverage is over 80%.

### Contribution Guidelines:
-   Ensure code is formatted (`make format`) and linted (`make lint`).
-   All tests must pass (`make test`).
-   Update relevant documentation.
-   Add test coverage for new features.
-   Refer to `AGENTS.md` for detailed development specifications.
