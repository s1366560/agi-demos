# Sandbox MCP Server Dockerfile
# Multi-language development environment with Python, Java, Node.js
# Optimized for fast builds using layer caching and BuildKit
#
# Build: docker build -t sandbox-mcp-server .
# Run:   docker run -p 8765:8765 -v $(pwd)/workspace:/workspace sandbox-mcp-server

FROM ubuntu:25.04

LABEL maintainer="MemStack Team"
LABEL description="Sandbox MCP Server with KDE Plasma 6, Python, Java, Node.js"

# ====================
# Environment Variables
# ====================
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    LANGUAGE=zh_CN:en

# Development versions
ENV PYTHON_VERSION=3.13 \
    NODE_VERSION=22 \
    JAVA_VERSION=21

# MCP Server configuration
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8765 \
    MCP_WORKSPACE=/workspace \
    HOSTNAME=mcp-sandbox

# Desktop configuration
ENV DESKTOP_ENABLED=true \
    DESKTOP_RESOLUTION=1920x1080 \
    DESKTOP_PORT=6080

# ====================
# Base System Setup
# ====================
# First install ca-certificates for HTTPS support, then configure mirrors
RUN set -eux; \
    apt-get update; \
    apt-get install -y ca-certificates; \
    ARCH=$(dpkg --print-architecture); \
    if [ "$ARCH" = "amd64" ]; then MIRROR="https://mirrors.tuna.tsinghua.edu.cn/ubuntu"; \
    elif [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then MIRROR="https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports"; \
    else MIRROR="https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports"; \
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
    # Locale support for Chinese
    locales \
    # Document Processing (docx, pptx, xlsx, pdf skills)
    pandoc libreoffice-writer libreoffice-calc libreoffice-impress poppler-utils \
    # Video/Media Processing (remotion, slack-gif-creator skills)
    ffmpeg \
    # Chinese fonts for document/image generation
    fonts-noto-cjk fonts-noto-cjk-extra \
    fonts-wqy-microhei fonts-wqy-zenhei \
    fonts-arphic-ukai fonts-arphic-uming \
    ; \
    # Generate Chinese locale
    sed -i '/zh_CN.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen zh_CN.UTF-8 && \
    update-locale LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8; \
    # Refresh font cache
    fc-cache -fv; \
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
# Install Bun Runtime (varg-video-generation skill)
# ====================
RUN set -eux; \
    curl -fsSL https://bun.sh/install | bash; \
    ln -sf /root/.bun/bin/bun /usr/local/bin/bun; \
    ln -sf /root/.bun/bin/bunx /usr/local/bin/bunx

# ====================
# Install Skills Dependencies - Global Node Packages
# ====================
# PPT/DOCX Processing (pptx, docx skills)
RUN --mount=type=cache,target=/root/.npm npm install -g \
    pptxgenjs docx

# Web Development (web-artifacts-builder, frontend-design skills)
RUN --mount=type=cache,target=/root/.npm npm install -g \
    typescript vite parcel

# Remotion Video Generation (remotion, create-remotion-geist skills)
RUN --mount=type=cache,target=/root/.npm npm install -g \
    remotion @remotion/cli

# HTML Rendering Dependencies (pptx html2pptx workflow)
RUN --mount=type=cache,target=/root/.npm npm install -g \
    puppeteer sharp react react-dom react-icons

# TailwindCSS for frontend development
RUN --mount=type=cache,target=/root/.npm npm install -g \
    tailwindcss postcss autoprefixer

# MCP Development (mcp-builder skill)
RUN --mount=type=cache,target=/root/.npm npm install -g \
    zod @types/node

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
# Install Skills Dependencies - Python Packages
# ====================
# PDF Processing (pdf skill)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages \
    pypdf pdfplumber reportlab pdf2image

# Image/GIF Processing (slack-gif-creator, canvas-design skills)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages \
    "pillow>=10.0.0" "imageio>=2.31.0" "imageio-ffmpeg>=0.4.9" "numpy>=1.24.0"

# Excel/Spreadsheet Processing (xlsx skill)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages \
    openpyxl pandas xlrd xlwt

# Word/OOXML Processing (docx skill)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages \
    python-docx defusedxml lxml

# Web Automation (webapp-testing skill)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages \
    playwright

# Document Conversion (pptx, docx skills)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages \
    markitdown

# Data Visualization & Science
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages \
    matplotlib seaborn scipy

# ====================
# Install Playwright Browsers (webapp-testing skill)
# ====================
RUN playwright install chromium --with-deps

# ====================
# Install Google Chrome / Chromium (chrome-devtools-mcp and puppeteer)
# ====================
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    mkdir -p /opt/google/chrome; \
    if [ "$ARCH" = "amd64" ]; then \
        curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
            -o /tmp/chrome.deb; \
        apt-get update; \
        apt-get install -y --no-install-recommends /tmp/chrome.deb; \
        rm -f /tmp/chrome.deb; \
        rm -rf /var/lib/apt/lists/*; \
    else \
        PW_CHROME=$(find /root/.cache/ms-playwright -name "chrome" -path "*/chrome-linux/*" 2>/dev/null | head -1); \
        if [ -n "$PW_CHROME" ]; then \
            ln -sf "$PW_CHROME" /opt/google/chrome/chrome; \
        else \
            echo "WARNING: No Chromium binary found for $ARCH"; \
        fi; \
    fi
ENV CHROME_BIN=/opt/google/chrome/chrome
ENV CHROME_PATH=/opt/google/chrome/chrome
ENV PUPPETEER_EXECUTABLE_PATH=/opt/google/chrome/chrome
ENV CHROME_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage"
ENV PUPPETEER_ARGS="--no-sandbox --disable-gpu --disable-dev-shm-usage"

# ====================
# Setup Python Virtual Environment for Skills
# ====================
# Create a pre-configured virtual environment for sandbox operations
ENV SKILLS_VENV=/opt/skills-venv
ENV PATH="${SKILLS_VENV}/bin:${PATH}"
RUN python -m venv ${SKILLS_VENV} && \
    ${SKILLS_VENV}/bin/pip install --upgrade pip && \
    ${SKILLS_VENV}/bin/pip install \
    # Core dependencies for skills
    pypdf pdfplumber reportlab pdf2image \
    "pillow>=10.0.0" "imageio>=2.31.0" "numpy>=1.24.0" \
    openpyxl pandas xlrd xlwt \
    python-docx defusedxml lxml \
    playwright markitdown \
    matplotlib seaborn scipy \
    # Additional common packages
    requests httpx aiohttp \
    pydantic typing-extensions \
    jinja2 pyyaml toml

# Install Playwright browsers in venv
RUN ${SKILLS_VENV}/bin/playwright install chromium

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
# Install KDE Plasma 6 Desktop Environment
# ====================
# Ubuntu 25.04 includes KDE Plasma 6 natively.
# KDE Plasma provides a modern, feature-rich desktop closest to
# real desktop experience with Dolphin file manager, Konsole terminal,
# and extensive customization options.
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    # X11 and display
    xorg \
    # KDE Plasma 6 desktop core (minimal install)
    kde-plasma-desktop \
    # KDE core applications
    dolphin konsole \
    # KDE system utilities
    kde-spectacle ksystemlog \
    # KDE themes and visual polish
    breeze breeze-icon-theme breeze-cursor-theme \
    plasma-workspace-wallpapers \
    # Sound (PulseAudio for KasmVNC audio streaming)
    pulseaudio pulseaudio-utils pavucontrol-qt \
    # X11 window manager (kwin-x11 removed in Ubuntu 25.04, openbox as fallback)
    openbox \
    # Utilities
    dbus-x11 \
    # SSL certificates (required by KasmVNC)
    ssl-cert \
    # Fonts (including CJK support for Asian languages)
    fonts-freefont-ttf fonts-noto-color-emoji \
    fonts-liberation fonts-dejavu-core \
    # Chinese fonts already installed in base layer, add input method
    ibus ibus-libpinyin \
    # System monitor
    htop \
    ; \
    # Refresh font cache for desktop
    fc-cache -fv; \
    # Disable SDDM (not needed for VNC sessions)
    systemctl disable sddm 2>/dev/null || true; \
    rm -rf /var/lib/apt/lists/*

# ====================
# Install KasmVNC (replaces TigerVNC + noVNC + websockify)
# ====================
# KasmVNC is an all-in-one VNC server with built-in web client,
# WebP/QOI encoding, dynamic resize, clipboard, file transfer, and audio.
# Note: KasmVNC v1.4.0 doesn't publish Ubuntu 25.04 (plucky) packages.
# The noble (24.04) package is ABI-compatible and works on plucky.
ENV KASMVNC_VERSION=1.4.0
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    if [ "$ARCH" = "amd64" ]; then \
        KASM_PKG="kasmvncserver_noble_${KASMVNC_VERSION}_amd64.deb"; \
    elif [ "$ARCH" = "arm64" ]; then \
        KASM_PKG="kasmvncserver_noble_${KASMVNC_VERSION}_arm64.deb"; \
    else \
        echo "Unsupported architecture: $ARCH"; exit 1; \
    fi; \
    curl -fsSL "https://github.com/kasmtech/KasmVNC/releases/download/v${KASMVNC_VERSION}/${KASM_PKG}" \
        -o /tmp/kasmvnc.deb; \
    apt-get update; \
    apt-get install -y --no-install-recommends /tmp/kasmvnc.deb; \
    rm -f /tmp/kasmvnc.deb; \
    rm -rf /var/lib/apt/lists/*; \
    # Add root to ssl-cert group (required by KasmVNC)
    adduser root ssl-cert 2>/dev/null || true; \
    # Pre-create KasmVNC user with write permissions (non-interactive)
    # KasmVNC reads $HOME/.kasmpasswd (NOT .vnc/kasmpasswd)
    # Format: username:password:permissions (r=read, w=write, o=owner)
    # Password is irrelevant since -disableBasicAuth is used
    mkdir -p /root/.vnc; \
    echo "root:kasmvnc:ow" > /root/.kasmpasswd; \
    chmod 600 /root/.kasmpasswd; \
    # Mark DE as already selected to skip interactive select-de.sh prompt
    # (KasmVNC's select-de.sh detects KDE via 'startkde' which is KDE 5;
    #  KDE Plasma 6 uses 'startplasma-x11', so we bypass detection entirely
    #  and rely on our own xstartup)
    touch /root/.vnc/.de-was-selected

# ====================
# Workspace Setup (runs as root)
# ====================
RUN mkdir -p /workspace

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
COPY . /app/

# Install MCP server (with cache mount)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --break-system-packages -e .

# ====================
# Configuration Files
# ====================
# KDE Plasma configs (Breeze theme defaults)
COPY docker/kde-configs/ /etc/xdg/

# Openbox window manager config (Breeze-ob theme, used as X11 WM since kwin-x11 is removed)
COPY docker/openbox-configs/rc.xml /etc/xdg/openbox/rc.xml

# KasmVNC configs
COPY docker/kasmvnc-configs/kasmvnc.yaml /etc/kasmvnc/kasmvnc.yaml
COPY docker/kasmvnc-configs/xstartup /etc/kasmvnc/xstartup.template
RUN chmod +x /etc/kasmvnc/xstartup.template

# Entrypoint
COPY scripts/entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod +x /usr/local/bin/sandbox-entrypoint.sh

# ====================
# Final Setup
# ====================
# NOTE: Hostname is configured at runtime via --hostname and --add-host parameters
# in mcp_sandbox_adapter.py to support proper VNC hostname resolution

WORKDIR /workspace

HEALTHCHECK --interval=30s --timeout=15s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${MCP_PORT}/health || exit 1

EXPOSE 8765 7681 6080
CMD ["/usr/local/bin/sandbox-entrypoint.sh"]
