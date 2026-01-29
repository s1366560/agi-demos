# Sandbox MCP Server Dockerfile
# Multi-language development environment with Python, Java, Node.js
# Optimized for fast builds using layer caching and BuildKit
#
# Build: docker build -t sandbox-mcp-server .
# Run:   docker run -p 8765:8765 -v $(pwd)/workspace:/workspace sandbox-mcp-server

FROM ubuntu:25.04

LABEL maintainer="MemStack Team"
LABEL description="Sandbox MCP Server with XFCE 4.20, Python, Java, Node.js"

# ====================
# Environment Variables
# ====================
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Development versions
ENV PYTHON_VERSION=3.13 \
    NODE_VERSION=22 \
    JAVA_VERSION=21

# MCP Server configuration
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8765 \
    MCP_WORKSPACE=/workspace

# Desktop configuration
ENV DESKTOP_ENABLED=true \
    DESKTOP_RESOLUTION=1920x1080 \
    DESKTOP_PORT=6080

# ====================
# Base System Setup
# ====================
# Configure apt mirrors and update in one layer
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    if [ "$ARCH" = "amd64" ]; then MIRROR="http://mirrors.aliyun.com/ubuntu"; \
    elif [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then MIRROR="http://mirrors.ustc.edu.cn/ubuntu-ports"; \
    else MIRROR="http://mirrors.ustc.edu.cn/ubuntu-ports"; \
    fi; \
    echo "Using mirror: $MIRROR for $ARCH"; \
    printf "Enabled: yes\nTypes: deb deb-src\nURIs: %s\nSuites: plucky plucky-updates plucky-backports\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\nEnabled: yes\nTypes: deb deb-src\nURIs: %s\nSuites: plucky-security\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n" "$MIRROR" "$MIRROR" > /etc/apt/sources.list.d/ubuntu.sources; \
    apt-get update; \
    apt-get upgrade -y

# ====================
# Install System Dependencies (cached layer)
# ====================
RUN set -eux; \
    apt-get install -y --no-install-recommends \
    # Basic utilities
    curl wget ca-certificates gnupg lsb-release git vim nano unzip zip tar gzip bzip2 xz-utils \
    # Build essentials
    build-essential gcc g++ make cmake pkg-config \
    # Python
    python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev python3-pip \
    # Java
    openjdk-${JAVA_VERSION}-jdk maven gradle \
    # Network tools
    iputils-ping net-tools dnsutils \
    # Process management
    procps htop \
    # Text processing
    jq \
    # File management
    tree rsync sudo \
    ; \
    rm -rf /var/lib/apt/lists/*

# ====================
# Install Node.js via NodeSource (cached layer)
# ====================
RUN set -eux; \
    curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash -; \
    apt-get install -y nodejs; \
    rm -rf /var/lib/apt/lists/*

# ====================
# Install Global Node Packages (with cache mount)
# ====================
RUN --mount=type=cache,target=/root/.npm npm install -g pnpm yarn

# ====================
# Configure Python Alternatives (cached layer)
# ====================
RUN update-alternatives --install /usr/bin/python python /usr/bin/python${PYTHON_VERSION} 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1

# ====================
# Install Python Tools (with cache mount for pip)
# ====================
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages pipx uv && \
    pipx ensurepath

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages \
    "aiohttp>=3.9.0" "aiofiles>=24.1.0" "pydantic>=2.5.0" "watchfiles>=0.21.0" \
    virtualenv pipenv poetry ipython black ruff mypy pytest pytest-asyncio

# ====================
# Install ttyd for Web Terminal
# ====================
ENV TTYD_VERSION=1.7.7
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    TTYD_ARCH=$([ "$ARCH" = "x86_64" ] && echo "x86_64" || \
               [ "$ARCH" = "aarch64" ] && echo "aarch64" || \
               [ "$ARCH" = "arm64" ] && echo "aarch64" || \
               echo "$ARCH"); \
    curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${TTYD_ARCH}" \
        -o /usr/local/bin/ttyd; \
    chmod +x /usr/local/bin/ttyd

# ====================
# Install XFCE 4.20 Desktop Environment
# ====================
# Ubuntu 25.04 includes XFCE 4.20 natively
# Note: Some packages from 24.04 are not available in 25.04 yet
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        # X11 and display
        xorg xvfb \
        # XFCE 4.20 desktop core
        xfce4 xfce4-goodies xfce4-terminal xfce4-taskmanager thunar \
        # Panel plugins (available in Ubuntu 25.04)
        xfce4-whiskermenu-plugin \
        xfce4-pulseaudio-plugin \
        xfce4-power-manager \
        xfce4-clipman-plugin \
        xfce4-xkb-plugin \
        xfce4-time-out-plugin \
        xfce4-diskperf-plugin \
        xfce4-netload-plugin \
        xfce4-cpugraph-plugin \
        xfce4-genmon-plugin \
        # File manager enhancements
        thunar-archive-plugin thunar-media-tags-plugin \
        # Desktop and window manager
        xfdesktop4 xfwm4 \
        # Settings and appearance
        xfce4-settings \
        gtk2-engines-murrine gtk2-engines-pixbuf \
        xfce4-indicator-plugin xfce4-places-plugin \
        # Themes and icons (Ubuntu 25.04 available packages)
        arc-theme \
        # Sound
        pulseaudio pulseaudio-utils pavucontrol \
        # Network
        network-manager-gnome \
        # Utilities
        dbus-x11 dconf-cli dconf-gsettings-backend gsettings-desktop-schemas \
        # VNC servers
        x11vnc tigervnc-standalone-server tigervnc-tools \
        # Fonts (including CJK support for Asian languages)
        fonts-freefont-ttf fonts-noto-cjk fonts-noto-color-emoji \
        fonts-liberation fonts-dejavu-core \
        # System monitor
        htop \
    ; \
    rm -rf /var/lib/apt/lists/*

# ====================
# Install noVNC
# ====================
ENV NOVNC_VERSION=1.6.0
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends python3-websockify; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz" \
        | tar -xz -C /opt; \
    mv /opt/noVNC-${NOVNC_VERSION} /opt/noVNC; \
    chmod +x /opt/noVNC/utils/novnc_proxy

# ====================
# User Setup
# ====================
RUN set -eux; \
    groupadd --gid 1001 sandbox; \
    useradd --uid 1001 --gid sandbox --shell /bin/bash --create-home sandbox; \
    usermod -aG sudo sandbox; \
    echo "sandbox ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/sandbox; \
    chmod 440 /etc/sudoers.d/sandbox; \
    mkdir -p /workspace /home/sandbox/.vnc; \
    chown -R sandbox:sandbox /workspace /home/sandbox/.vnc

# ====================
# Java Environment Setup
# ====================
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    JAVA_HOME_PATH="/usr/lib/jvm/java-21-openjdk-${ARCH}"; \
    echo "export JAVA_HOME=${JAVA_HOME_PATH}" >> /etc/profile.d/java.sh; \
    echo "export PATH=\${JAVA_HOME}/bin:\${PATH}" >> /etc/profile.d/java.sh; \
    echo "JAVA_HOME=${JAVA_HOME_PATH}" >> /etc/environment

ARG TARGETARCH
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-${TARGETARCH:-arm64}
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# ====================
# Application Setup
# ====================
WORKDIR /app
COPY --chown=sandbox:sandbox . /app/

# Install MCP server (with cache mount)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages -e .

# ====================
# Configuration Files
# ====================
# XFCE configs
COPY docker/xfce-configs/ /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/
COPY docker/xfce-configs/whiskermenu-1.rc /etc/xdg/xfce4/panel/
COPY docker/xfce-configs/autostart/ /etc/xdg/autostart/

# VNC configs
COPY docker/vnc-configs/vncserver-config /etc/vnc/config
COPY docker/vnc-configs/xstartup /etc/vnc/xstartup.template
COPY docker/vnc-configs/test-vnc-config.sh /etc/vnc/test-vnc-config.sh
COPY docker/vnc-configs/test-novnc-config.sh /etc/vnc/test-novnc-config.sh
COPY docker/vnc-configs/test-complete-setup.sh /etc/vnc/test-complete-setup.sh
COPY docker/vnc-configs/novnc-defaults.json /opt/noVNC/defaults.json
RUN chmod +x /etc/vnc/xstartup.template /etc/vnc/test-vnc-config.sh /etc/vnc/test-novnc-config.sh /etc/vnc/test-complete-setup.sh

# Entrypoint
COPY scripts/entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod +x /usr/local/bin/sandbox-entrypoint.sh

# ====================
# Final Setup
# ====================
WORKDIR /workspace

HEALTHCHECK --interval=30s --timeout=15s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${MCP_PORT}/health || exit 1

EXPOSE 8765 7681 6080
CMD ["/usr/local/bin/sandbox-entrypoint.sh"]
