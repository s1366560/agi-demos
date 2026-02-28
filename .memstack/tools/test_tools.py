"""Deep test custom tools for comprehensive testing.

This file contains multiple test tools to verify the custom tool system:
1. Simple echo tool - basic string parameter
2. Calculator tool - multiple numeric parameters
3. Error tool - test error handling
4. Complex tool - structured input/output
5. Validation tool - parameter validation
"""


from memstack_tools import ToolResult, tool_define


@tool_define(
    name="test_tool_echo",
    description="Echo back the provided message. Simple string parameter test.",
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to echo back.",
            },
        },
        "required": ["message"],
    },
    permission="read",
    category="test",
)
async def test_tool_echo(ctx: object, message: str) -> ToolResult:
    """Return message unchanged."""
    return ToolResult(output=f"Echo: {message}")


@tool_define(
    name="test_tool_calculator",
    description="Perform basic arithmetic operations on two numbers.",
    parameters={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": "Operation: add, subtract, multiply, divide",
                "enum": ["add", "subtract", "multiply", "divide"],
            },
            "a": {
                "type": "number",
                "description": "First operand",
            },
            "b": {
                "type": "number",
                "description": "Second operand",
            },
        },
        "required": ["operation", "a", "b"],
    },
    permission="read",
    category="test",
)
async def test_tool_calculator(ctx: object, operation: str, a: float, b: float) -> ToolResult:
    """Perform calculation based on operation type."""
    try:
        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            if b == 0:
                return ToolResult(error="Division by zero is not allowed")
            result = a / b
        else:
            return ToolResult(error=f"Unknown operation: {operation}")
        
        return ToolResult(output=f"Result: {result}")
    except Exception as e:
        return ToolResult(error=f"Calculation error: {e!s}")


@tool_define(
    name="test_tool_error",
    description="Test error handling by returning an error result.",
    parameters={
        "type": "object",
        "properties": {
            "error_type": {
                "type": "string",
                "description": "Type of error to generate",
                "enum": ["validation", "runtime", "custom"],
            },
            "message": {
                "type": "string",
                "description": "Error message",
            },
        },
        "required": ["error_type", "message"],
    },
    permission="read",
    category="test",
)
async def test_tool_error(ctx: object, error_type: str, message: str) -> ToolResult:
    """Return an error result to test error handling."""
    if error_type == "validation":
        return ToolResult(error=f"Validation error: {message}")
    elif error_type == "runtime":
        return ToolResult(error=f"Runtime error: {message}")
    elif error_type == "custom":
        return ToolResult(error=message)
    else:
        return ToolResult(error="Unknown error type")


@tool_define(
    name="test_tool_complex",
    description="Test complex structured input and output with nested data.",
    parameters={
        "type": "object",
        "properties": {
            "user_data": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "email": {"type": "string"},
                },
                "required": ["name"],
            },
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of items",
            },
            "metadata": {
                "type": "object",
                "description": "Additional metadata",
            },
        },
        "required": ["user_data"],
    },
    permission="read",
    category="test",
)
async def test_tool_complex(
    ctx: object, 
    user_data: dict, 
    items: list | None = None, 
    metadata: dict | None = None
) -> ToolResult:
    """Test handling of complex nested parameters."""
    output = {
        "received_user": user_data,
        "received_items": items or [],
        "received_metadata": metadata or {},
        "status": "success",
    }
    return ToolResult(output=str(output))


@tool_define(
    name="test_tool_validation",
    description="Test parameter validation with constraints.",
    parameters={
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "Username (3-20 chars, alphanumeric)",
            },
            "count": {
                "type": "integer",
                "description": "Count (1-100)",
                "minimum": 1,
                "maximum": 100,
            },
            "enabled": {
                "type": "boolean",
                "description": "Whether feature is enabled",
            },
        },
        "required": ["username", "count"],
    },
    permission="read",
    category="test",
)
async def test_tool_validation(
    ctx: object, 
    username: str, 
    count: int, 
    enabled: bool = False
) -> ToolResult:
    """Test parameter validation constraints."""
    # Manual validation as JSON Schema is checked by the framework
    if len(username) < 3 or len(username) > 20:
        return ToolResult(error="Username must be 3-20 characters")
    
    if not username.isalnum():
        return ToolResult(error="Username must be alphanumeric")
    
    return ToolResult(output=f"Valid: username={username}, count={count}, enabled={enabled}")


@tool_define(
    name="test_tool_status",
    description="Check the custom tool system status.",
    parameters={
        "type": "object",
        "properties": {
            "check_type": {
                "type": "string",
                "description": "Type of status check",
                "enum": ["basic", "detailed", "full"],
            },
        },
        "required": ["check_type"],
    },
    permission="read",
    category="test",
)
async def test_tool_status(ctx: object, check_type: str) -> ToolResult:
    """Return system status information."""
    if check_type == "basic":
        return ToolResult(output="Custom tools: OK")
    elif check_type == "detailed":
        return ToolResult(output="Custom tools: OK | 6 tools loaded | Test category active")
    elif check_type == "full":
        return ToolResult(output="Full status: All systems operational | Tools: echo, calculator, error, complex, validation, status")
    else:
        return ToolResult(error="Unknown check type")
