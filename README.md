# MemStack - Enterprise AI Agent Platform

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-green.svg)](https://fastapi.tiangolo.com/)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.26%2B-blue.svg)](https://neo4j.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**MemStack** (code name: Vanus) is an **enterprise-level AI agent platform** built with a **progressive capability composition** architecture. It implements a four-layer capability model: **Tool → Skill → SubAgent → Agent**, enabling AI agents to become efficient collaborative partners for enterprise teams.

## Core Features

### Multi-Level Thinking Agent
- **Work-Level Planning**: High-level task decomposition for complex queries
- **Task-Level Execution**: Detailed reasoning and per-step execution
- **Query Complexity Detection**: Automatic classification (Simple/Moderate/Complex)

### Human-AI Collaboration
- **Planning Clarification**: Ask questions to confirm understanding before execution
- **Execution Decision**: Request user confirmation at critical decision points
- **Loop Detection**: Detect and intervene when agent gets stuck in loops
- **Permission Control**: Fine-grained tool permission system (allow/deny/ask)

### Interaction Experience Accumulation
- **Pattern Learning**: Extract reusable patterns from successful human-AI interactions
- **Experience Retrieval**: Find and apply similar historical experiences
- **Continuous Optimization**: Evolve patterns based on feedback and usage

### Knowledge & Memory Management
- **Dynamic Knowledge Integration**: Real-time integration of conversations, structured data, and external information
- **Temporal Awareness**: Dual-timestamp model for precise historical queries
- **High-Performance Retrieval**: Hybrid search (semantic + keyword + graph traversal) with sub-second response

### Multi-Tenant Architecture
- **Tenant Isolation**: Complete separation of tenants, projects, and configurations
- **API Key Authentication**: SHA256-hashed keys with format `ms_sk_` + 64 hex chars
- **Flexible LLM Support**: Google Gemini, Alibaba Qwen, Deepseek, ZhipuAI, OpenAI

## Architecture

MemStack follows **Domain-Driven Design (DDD)** with **Hexagonal Architecture (Ports & Adapters)**:

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend Layer                            │
│                  (React + TypeScript)                        │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP/SSE
┌────────────────────▼────────────────────────────────────────┐
│              API Gateway Layer                               │
│         (FastAPI Routers + Middleware)                      │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│           Application Layer                                  │
│   ┌───────────────┬──────────────┬──────────────────────┐   │
│   │ Use Cases     │   Services   │     DTOs (Schemas)   │   │
│   └───────────────┴──────────────┴──────────────────────┘   │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│            Domain Layer                                     │
│   ┌──────────────────┬──────────────┬────────────────────┐  │
│   │   Entities       │ Aggregates   │  Domain Services   │  │
│   │  (Agent, Memory, │   (Roots)    │  (Business Logic)  │  │
│   │   Auth, Project) │              │                    │  │
│   ├──────────────────┴──────────────┴────────────────────┤  │
│   │              Ports (Interfaces)                       │  │
│   └───────────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│        Infrastructure Layer                                 │
│   ┌──────────────────┬──────────────┬────────────────────┐  │
│   │ Primary Adapters │ Secondary    │    Config          │  │
│   │  (Web API, CLI)  │ Adapters     │  (DI Container)    │  │
│   │                  │ (DB, Graph,  │                    │  │
│   │                  │  Cache, LLM) │                    │  │
│   └──────────────────┴──────────────┴────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Four-Layer Capability Model

| Layer | Name | Description | Features |
|-------|------|-------------|----------|
| **L1: Tool** | Tool Layer | Atomic capability units | 8+ built-in tools (memory search, graph query, web search), MCP extensibility |
| **L2: Skill** | Skill Layer | Declarative knowledge documents | Auto-activation based on triggers, Markdown format, version management |
| **L3: SubAgent** | Sub-Agent Layer | Specialized agents with domain expertise | Configurable tools/skills, parallel/sequential orchestration |
| **L4: Agent** | Agent Layer | Complete ReAct agents | Experience accumulation, human collaboration, autonomous decision-making |

## Technology Stack

### Backend
| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.12+ | Main development language |
| **FastAPI** | 0.110+ | High-performance web framework |
| **ReAct Core** | (self-developed) | Agent reasoning engine |
| **LangChain** | 0.3+ | LLM toolchain |
| **SQLAlchemy** | 2.0+ | ORM for PostgreSQL |
| **Alembic** | 1.12+ | Database migrations |
| **Pydantic** | 2.5+ | Data validation |
| **Neo4j** | 5.26+ | Knowledge graph |
| **PostgreSQL** | 16+ | Metadata storage |
| **Redis** | 7+ | Caching |

### Frontend
| Technology | Version | Purpose |
|------------|---------|---------|
| **React** | 19.2+ | UI framework |
| **TypeScript** | 5.9+ | Type safety |
| **Vite** | 6.3+ | Build tool |
| **Ant Design** | 6.1+ | UI component library |
| **Zustand** | 5.0+ | State management |

### LLM Providers (Multi-Provider Support)
| Provider | Models | Purpose |
|----------|--------|---------|
| **Google Gemini** | Gemini Pro | Entity extraction, summarization (default) |
| **Alibaba Qwen** | Qwen-Turbo/Plus/Max | Chinese language optimization, embedding, reranking |
| **Deepseek** | Deepseek-Chat | Cost-effective reasoning |
| **ZhipuAI (Z.AI)** | GLM models | Chinese language model |
| **OpenAI** | GPT models | General purpose |

## Quick Start

### Prerequisites
- **Python**: 3.12+
- **Node.js**: 18+ (for web development)
- **Neo4j**: 5.26+
- **PostgreSQL**: 16+ (for metadata)
- **Redis**: 7+ (for caching)
- **LLM API**: Google Gemini, Alibaba Qwen, Deepseek, ZhipuAI, or OpenAI

### Installation

```bash
# Clone the repository
git clone https://github.com/s1366560/memstack.git
cd memstack

# Install dependencies using uv (recommended)
uv sync --extra dev

# Or using pip
pip install -e ".[dev,neo4j,evaluation]"
```

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
# Required settings:
# - NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
# - DATABASE_URL (PostgreSQL)
# - REDIS_URL
# - LLM_PROVIDER (gemini, qwen, deepseek, zhipu, openai)
# - Corresponding LLM API keys
```

### Start Services

#### Option 1: Docker Compose (Recommended)
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api
```

#### Option 2: Local Development
```bash
# Start infrastructure services (Neo4j, PostgreSQL, Redis)
make docker-up

# Start backend API server
make dev  # http://localhost:8000

# Start web console (in a new terminal)
make dev-web  # http://localhost:3000
```

### Verification

```bash
# Check health status
curl http://localhost:8000/health

# View API documentation
open http://localhost:8000/docs

# Get default API key (development mode)
# Check server startup logs for:
# "Generated default API key: ms_sk_..."
```

## Usage

### Python SDK

#### Installation
```bash
pip install ./sdk/python
```

#### Synchronous Client
```python
from memstack import MemStackClient

# Initialize client
client = MemStackClient(
    api_key="ms_sk_your_api_key",
    base_url="http://localhost:8000/api/v1"
)

# Create an episode
response = client.create_episode(
    name="User Conversation",
    content="User wants to book a meeting room for tomorrow",
    source_type="text",
    group_id="user_123"
)
print(f"Episode ID: {response.id}")

# Search memories
results = client.search_memory(
    query="meeting room booking",
    limit=10
)
for result in results.results:
    print(f"- {result.content} (score: {result.score})")
```

#### Asynchronous Client
```python
from memstack import MemStackAsyncClient
import asyncio

async def main():
    async with MemStackAsyncClient(api_key="ms_sk_...") as client:
        # Create episode
        response = await client.create_episode(
            name="Async Conversation",
            content="Test content"
        )

        # Search memories
        results = await client.search_memory(query="test")
        print(f"Found {results.total} results")

asyncio.run(main())
```

### Agent Chat (SSE Streaming)

```python
import httpx

async def chat_with_agent():
    api_key = "ms_sk_your_api_key"

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            "http://localhost:8000/api/v1/agent/chat",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "message": "Analyze Q3 and Q4 sales performance",
                "project_id": "your-project-id"
            },
            timeout=300
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    event_type = data.get("type")

                    if event_type == "work_plan":
                        print(f"Plan: {data['data']['total_steps']} steps")
                    elif event_type == "step_start":
                        print(f"Step: {data['data']['description']}")
                    elif event_type == "thought":
                        print(f"Thinking: {data['data']['thought']}")
                    elif event_type == "complete":
                        print(f"Result: {data['data']['content']}")
```

### Direct API Calls

```bash
# Set API key
export API_KEY="ms_sk_your_api_key"

# Create episode
curl -X POST http://localhost:8000/api/v1/episodes/ \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Episode",
    "content": "This is test content",
    "source_type": "text"
  }'

# Search memories
curl -X POST http://localhost:8000/api/v1/memory/search \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test",
    "limit": 10
  }'
```

## Development

### Common Commands

```bash
# Setup & Installation
make install              # Install all dependencies
make install-backend      # Install Python dependencies
make install-web          # Install frontend dependencies

# Running Services
make dev                  # Start all backend services
make dev-backend          # Start API server only (port 8000)
make dev-worker           # Start worker service only
make dev-web              # Start web dev server (port 3000)
make dev-infra            # Start Neo4j, PostgreSQL, Redis via Docker
make dev-stop             # Stop all background services

# Testing
make test                 # Run all tests
make test-unit            # Unit tests only
make test-integration     # Integration tests only
make test-coverage        # Run with coverage report (80%+ target)
make test-e2e             # E2E tests (Playwright)

# Code Quality
make format               # Format all code
make lint                 # Lint all code
make check                # Run format + lint + test

# Database Operations
make db-init              # Initialize PostgreSQL database
make db-migrate           # Run Alembic migrations
make db-reset             # WARNING: Drops and recreates database
make db-shell             # Open PostgreSQL shell

# Docker Operations
make docker-up            # Start all Docker services
make docker-down          # Stop Docker services
make docker-logs          # Show Docker logs
```

### Testing

Current test coverage: **80%+**

```bash
# Run tests with coverage
make test

# View HTML coverage report
open htmlcov/index.html
```

### Code Style
- Follow PEP 8 standards
- Use Ruff for formatting and linting
- Use MyPy for type checking
- See `CLAUDE.md` for detailed guidelines

## Documentation

### Architecture
- **[Complete Architecture (English)](docs/architecture/ARCHITECTURE.md)** - Full system architecture design
- **[CLAUDE.md](CLAUDE.md)** - Developer guidelines and coding standards

### API Reference
- **[API Documentation](docs/api-reference.md)** - Complete API endpoint documentation
- **[OpenAPI Schema](specs/003-react-agent/contracts/openapi.yaml)** - OpenAPI specification

### SDK
- **[Python SDK](sdk/python/README.md)** - Python SDK documentation

## Authentication

MemStack uses API Key authentication:

### API Key Format
- Prefix: `ms_sk_`
- Length: 71 characters (prefix + 64 hex characters)
- Storage: SHA256 hashed, plaintext never stored

### Development Environment
Service automatically generates a default API key on startup:
```
INFO:     Generated default API key: ms_sk_abc123...
INFO:     Default user created: developer@memstack.local
```

### Production Environment
Manage API keys via API:
```python
POST /api/v1/auth/keys    # Create key
GET  /api/v1/auth/keys    # List keys
DELETE /api/v1/auth/keys/{id}  # Delete key
```

## Database Design

### PostgreSQL Schema (Metadata)
Key tables:
- `users`, `tenants`, `projects` - Multi-tenant structure
- `api_keys` - Authentication (SHA256 hashed)
- `conversations` - Multi-turn dialogues
- `messages` - Messages with tool calls/results
- `agent_executions` - Execution records
- `work_plans` - Work-level plans
- `interaction_patterns` - Learned patterns (tenant-scoped)
- `tool_compositions` - Tool chains
- `episodes` - Episode metadata

### Neo4j Schema (Knowledge Graph)
Node Types:
- `Memory` - Memory units
- `Entity` - Real-world objects
- `Community` - Entity communities

Relationship Types:
- `MERGED_WITH` - Entity merge
- `RELATED_TO` - Generic relationship
- Custom edge types supported

### Alembic Migration Guidelines

**Critical Rules**:
1. **NEVER modify database directly without migrations**
2. **Always use `--autogenerate` for schema changes**
3. **Review autogenerated migrations** (may include false positives)

```bash
# Migration workflow
# 1. Modify SQLAlchemy models
# 2. Generate migration
PYTHONPATH=. uv run alembic revision --autogenerate -m "description"

# 3. Review and edit if needed
# 4. Test migration
PYTHONPATH=. uv run alembic upgrade head

# 5. Check status
PYTHONPATH=. uv run alembic current
```

## Deployment

### Docker Deployment
```bash
# Build images
docker-compose build

# Start services
docker-compose up -d

# Check status
docker-compose ps
```

### Web Application Deployment
```bash
# Build web application image
cd web
docker build -t memstack-web .

# Run container
docker run -d -p 80:80 \
  -e API_URL=http://api:8000 \
  memstack-web
```

## Project Structure

```
memstack/
├── src/                          # Hexagonal Architecture Backend
│   ├── domain/                   # Domain Layer (Core business logic)
│   │   ├── model/                # Domain entities organized by bounded context
│   │   │   ├── agent/           # React Agent entities
│   │   │   ├── auth/            # Authentication entities
│   │   │   ├── memory/          # Memory entities
│   │   │   ├── project/         # Project entities
│   │   │   └── tenant/          # Tenant entities
│   │   └── ports/               # Repository and service interfaces
│   ├── application/              # Application Layer (Use cases)
│   │   ├── use_cases/           # Business use cases
│   │   ├── services/            # Application services
│   │   └── schemas/             # DTOs for API requests/responses
│   ├── infrastructure/           # Infrastructure Layer (Adapters)
│   │   ├── adapters/
│   │   │   ├── primary/         # Driving adapters (web API)
│   │   │   └── secondary/       # Driven adapters (databases)
│   │   ├── agent/               # Agent infrastructure (Self-developed ReAct)
│   │   ├── llm/                 # LLM provider clients
│   │   └── security/            # Authentication, authorization
│   ├── configuration/            # Settings and DI container
│   └── tests/                    # Backend tests
│
├── web/                          # React Frontend
│   └── src/
│       ├── pages/                # Route-level page components
│       ├── components/           # Reusable UI components
│       ├── stores/               # Zustand state management
│       └── services/             # API clients
│
├── alembic/                      # Database migrations
├── docs/architecture/            # Architecture documentation
├── scripts/                      # Utility scripts
├── Makefile                      # Development commands
└── pyproject.toml               # Python dependencies
```

## Contributing

We welcome contributions!

### Pre-Submission Checklist
- [ ] Run `make format` to format code
- [ ] Run `make lint` to pass code checks
- [ ] Run `make test` to ensure tests pass
- [ ] Update relevant documentation
- [ ] Add tests for new features

### Development Workflow
1. Fork this repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Submit a Pull Request

See `CLAUDE.md` for detailed development guidelines.

## License

MIT License - see [LICENSE](LICENSE) file for details

## Acknowledgments

This project is built upon excellent open-source projects:
- [Graphiti](https://github.com/getzep/graphiti) - Core knowledge graph engine
- [FastAPI](https://fastapi.tiangolo.com/) - High-performance web framework
- [LangChain](https://github.com/langchain-ai/langchain) - LLM utilities
- [Neo4j](https://neo4j.com/) - Graph database
- [React](https://react.dev/) - UI framework
- [Ant Design](https://ant.design/) - Component library

## References
- **Architecture Design**: Inspired by [JoyAgent-JDGenie](https://github.com/jd-opensource/joyagent-jdgenie) for multi-level thinking
- **Plugin Architecture**: Based on [Claude Code Plugin Architecture](https://github.com/anthropics/claude-code)
- **MCP Integration**: Following [Model Context Protocol](https://modelcontextprotocol.io/) specification

## Contact

- Project Homepage: [https://github.com/s1366560/memstack](https://github.com/s1366560/memstack)
- Issue Tracker: [GitHub Issues](https://github.com/s1366560/memstack/issues)

---

**Note**: This project is currently in active development. APIs may change before v1.0 release. Please test thoroughly before production use.
