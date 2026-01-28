# Sandbox MCP Server Dockerfile
# Multi-language development environment with Python, Java, and Node.js
#
# Build: docker build -t sandbox-mcp-server .
# Run:   docker run -p 8765:8765 -v $(pwd)/workspace:/workspace sandbox-mcp-server
#
# SECURITY NOTE: The 'sandbox' user has sudo access with NOPASSWD for development
# flexibility. This allows installation of system packages via 'apt install'.
# In production, consider removing sudo access or using a more restricted setup.

FROM ubuntu:24.04

LABEL maintainer="MemStack Team"
LABEL description="Sandbox MCP Server with Python, Java, Node.js development environment"

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Language environment
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Development environment versions
ENV PYTHON_VERSION=3.12
ENV NODE_VERSION=22
ENV JAVA_VERSION=21

# MCP Server configuration
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8765
ENV MCP_WORKSPACE=/workspace

# Install system dependencies and development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Basic utilities
    curl \
    wget \
    ca-certificates \
    gnupg \
    lsb-release \
    git \
    vim \
    nano \
    unzip \
    zip \
    tar \
    gzip \
    bzip2 \
    xz-utils \
    # Build essentials
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    pkg-config \
    # Python dependencies
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-venv \
    python${PYTHON_VERSION}-dev \
    python3-pip \
    # Java OpenJDK
    openjdk-${JAVA_VERSION}-jdk \
    maven \
    gradle \
    # Network tools
    iputils-ping \
    net-tools \
    dnsutils \
    # Process management
    procps \
    htop \
    # Text processing
    jq \
    # File management
    tree \
    rsync \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (using NodeSource)
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install pnpm and yarn globally
RUN npm install -g pnpm yarn

# Set Python 3.12 as default python/python3
RUN update-alternatives --install /usr/bin/python python /usr/bin/python${PYTHON_VERSION} 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1

# Install pipx and uv globally
RUN python -m pip install --no-cache-dir --break-system-packages pipx uv \
    && pipx ensurepath

# Install Python development tools using pip (without upgrading system pip)
RUN python -m pip install --no-cache-dir --break-system-packages \
    # MCP server dependencies
    "aiohttp>=3.9.0" \
    "aiofiles>=24.1.0" \
    "pydantic>=2.5.0" \
    "watchfiles>=0.21.0" \
    # Common Python tools
    virtualenv \
    pipenv \
    poetry \
    # Development utilities
    ipython \
    black \
    ruff \
    mypy \
    pytest \
    pytest-asyncio

# Install sudo for package management capability
RUN apt-get update && apt-get install -y sudo \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security (use GID/UID 1001 to avoid conflicts)
RUN groupadd --gid 1001 sandbox \
    && useradd --uid 1001 --gid sandbox --shell /bin/bash --create-home sandbox \
    && usermod -aG sudo sandbox \
    && echo "sandbox ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/sandbox \
    && chmod 440 /etc/sudoers.d/sandbox

# Create workspace directory
RUN mkdir -p /workspace && chown sandbox:sandbox /workspace

# Copy application code
WORKDIR /app
COPY --chown=sandbox:sandbox . /app/

# Install the MCP server package
RUN python -m pip install --no-cache-dir --break-system-packages -e .

# Set environment variables for Java (auto-detect architecture at build time)
RUN ARCH=$(dpkg --print-architecture) && \
    JAVA_HOME_PATH="/usr/lib/jvm/java-21-openjdk-${ARCH}" && \
    echo "export JAVA_HOME=${JAVA_HOME_PATH}" >> /etc/profile.d/java.sh && \
    echo "export PATH=\${JAVA_HOME}/bin:\${PATH}" >> /etc/profile.d/java.sh && \
    # Also write to /etc/environment for non-login shells
    echo "JAVA_HOME=${JAVA_HOME_PATH}" >> /etc/environment

# Dynamically set JAVA_HOME based on architecture  
ARG TARGETARCH
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-${TARGETARCH:-arm64}
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Set workspace ownership
RUN chown -R sandbox:sandbox /workspace

# Switch to non-root user
USER sandbox

# Set working directory
WORKDIR /workspace

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${MCP_PORT}/health || exit 1

# Expose the MCP server port
EXPOSE 8765

# Default command
CMD ["python", "-m", "src.server.main"]
