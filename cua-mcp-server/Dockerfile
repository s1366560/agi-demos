FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Copy repo (needed for vendor/cua libs)
COPY . /app

# Install CUA MCP server dependencies
RUN pip install --no-cache-dir -e /app/cua-mcp-server \
 && pip install --no-cache-dir -e /app/vendor/cua/libs/python/computer

ENV CUA_ENABLED=true
ENV CUA_MCP_HOST=0.0.0.0
ENV CUA_MCP_PORT=18766

EXPOSE 18766

CMD ["python", "-m", "server.main"]
