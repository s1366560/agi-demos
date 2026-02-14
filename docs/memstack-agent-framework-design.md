# MemStack Agent Framework Design

## Overview

`memstack-agent` is a reusable AI Agent development framework extracted from the MemStack project. It combines the **simplicity of OpenAI Swarm** with the **production-grade features of LangGraph**, using a four-layer architecture design.

## Design Philosophy

### Core Principles

| Principle | Source | Description |
|-----------|--------|-------------|
| **Minimal Abstraction** | Swarm | Function as tool, return Agent to switch |
| **Low Abstraction Level** | LangGraph | Write Agent like normal code |
| **Optional Features** | LangGraph | Every feature is an optional building block |
| **Event-Driven** | MemStack | Rich SSE event streams |
| **Declarative Orchestration** | MemStack | Skill/SubAgent composition, not hardcoded |

### Design Goals

1. **Simplicity First** - Default configuration works, complex features optional
2. **Reusability** - Independent of business logic, usable in any Python project
3. **Extensibility** - Clear extension points: tools, skills, SubAgents
4. **Production-Ready** - Built-in checkpoint, HITL, streaming, observability
5. **Type Safety** - Complete type annotations, static checking support

## Framework Comparison

| Feature | Swarm | LangGraph | MemStack Agent |
|----------|--------|-----------|----------------|
| Complexity | Minimal | Production | **Configurable** |
| State Management | None | Checkpoint | **Optional** |
| Multi-Agent | Handoff | Graph | **4-Layer Architecture** |
| Tools | Functions | Tool Class | **Tool Protocol** |
| Orchestration | Client Loop | Pregel | **ReAct Loop** |
| Streaming | Basic | 6 modes | **Event-Driven** |

## Architecture Design

### Four-Layer Architecture

```
L4: Agent (ReAct Reasoning Loop)
  - ReActAgent: Main entry, coordinates layers
  - SessionProcessor: Think -> Act -> Observe loop

L3: SubAgent
  - Routing decisions
  - Independent execution

L2: Skill
  - Trigger matching
  - Tool orchestration

L1: Tool
  - Atomic capabilities
  - Parameter definitions
```

## Framework Directory Structure

```
memstack-agent/
|-- src/memstack_agent/
|   |-- core/              # Core abstractions
|   |   |-- types.py
|   |   |-- events.py
|   |   |-- state.py
|   |
|   |-- processor/          # Processor layer
|   |-- tools/             # Tool layer
|   |-- skills/            # Skill layer
|   |-- subagents/         # SubAgent layer
|   |-- agent/             # Agent layer
|   |-- llm/              # LLM abstraction
|   |-- events/            # Event system
|   |-- context/           # Context management
|   |-- resilience/        # Retry, circuit breaker, rate limit
|   |-- checkpoint/        # State snapshot (from LangGraph)
|   |-- hitl/              # Human-in-the-Loop
|   |-- adapters/          # LLM/Storage/Event adapters
|
|-- examples/
|-- tests/
|-- docs/
```

## Core Interface Definitions

### 1. Tool Protocol (from Swarm: function as tool)

```python
class AgentTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> List[ToolParam]: ...

    @abstractmethod
    async def execute(self, **kwargs) -> str: ...
```

### 2. Skill Dataclass (declarative composition)

```python
@dataclass(kw_only=True)
class Skill:
    id: str
    name: str
    description: str
    tools: List[str]
    trigger_type: TriggerType
    trigger_patterns: List[TriggerPattern]
```

### 3. SubAgent Dataclass (from Swarm Handoff)

```python
@dataclass(kw_only=True)
class SubAgent:
    id: str
    name: str
    system_prompt: str
    allowed_tools: List[str]
    trigger_description: str
```

### 4. Checkpoint Protocol (from LangGraph)

```python
class CheckpointProtocol(ABC):
    @abstractmethod
    async def save(self, agent_id: str, state: AgentState) -> str: ...

    @abstractmethod
    async def load(self, checkpoint_id: str) -> Optional[AgentState]: ...
```

## Core Features

### 1. Function as Tool (from Swarm)

```python
from memstack_agent import ReActAgent, tool

@tool
async def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"The weather in {city} is sunny, 22C"
```

### 2. Agent Handoff (from Swarm)

```python
from memstack_agent import handoff

sales_agent = ReActAgent(name="sales")
support_agent = ReActAgent(name="support")

@handoff
def transfer_to_support():
    """Transfer customer to support."""
    return support_agent  # Return another Agent to switch
```

### 3. Event System (from LangGraph Streaming)

```python
# Six streaming event types
class StreamEventType(str, Enum):
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END = "tool_call_end"
```

## Migration Path

### Phase 1: Extract Core Abstractions
- Create `memstack-agent` repo
- Extract `core/` layer (types, events, state)

### Phase 2: Extract Tools and Skills
- Extract `tools/base.py` and built-in tools
- Extract `skills/` orchestration system

### Phase 3: Extract SubAgent System
- Extract `subagents/` routing and execution
- Implement handoff mechanism

### Phase 4: Adapter Layer
- Create LLM adapter interfaces
- Implement checkpoint protocol

### Phase 5: Integration Testing
- End-to-end tests
- Performance comparison

### Phase 6: Gradual Migration
- Introduce dependency in existing project
- Replace modules one by one
- Maintain backward compatibility
