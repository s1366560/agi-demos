# Sandbox MCP Server Dockerfile
# Multi-language development environment with Python, Java, Node.js
# Optimized for fast builds using layer caching and BuildKit
#
# Build: docker build -t sandbox-mcp-server .
# Run:   docker run -p 8765:8765 -v $(pwd)/workspace:/workspace sandbox-mcp-server

ARG DOCKER_CLI_IMAGE=docker:cli@sha256:862099ada15c669000bef53aa4cb9d821262829f45b0dda2159ccb276443043b
FROM ${DOCKER_CLI_IMAGE} AS docker-cli

FROM ubuntu:24.04

LABEL maintainer="MemStack Team"
LABEL description="Sandbox MCP Server with KDE Plasma, Python, Java, Node.js"

# ====================
# Environment Variables
# ====================
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    LANGUAGE=zh_CN:en

# Development versions
ENV PYTHON_VERSION=3.12 \
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
# First install ca-certificates for HTTPS support, then configure mirrors
RUN set -eux; \
    apt-get update; \
    apt-get install -y ca-certificates; \
    ARCH=$(dpkg --print-architecture); \
    if [ "$ARCH" = "amd64" ]; then MIRROR="http://archive.ubuntu.com/ubuntu"; \
    elif [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then MIRROR="http://ports.ubuntu.com/ubuntu-ports"; \
    else MIRROR="http://ports.ubuntu.com/ubuntu-ports"; \
    fi; \
    echo "Using mirror: $MIRROR for $ARCH"; \
    printf "Enabled: yes\nTypes: deb deb-src\nURIs: %s\nSuites: noble noble-updates noble-backports\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\nEnabled: yes\nTypes: deb deb-src\nURIs: %s\nSuites: noble-security\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n" "$MIRROR" "$MIRROR" > /etc/apt/sources.list.d/ubuntu.sources; \
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

# Run untrusted tools and interactive services as an unprivileged user.
RUN set -eux; \
    groupadd --gid 10001 sandbox; \
    useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash sandbox

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
    install -m 0755 /root/.bun/bin/bun /usr/local/bin/bun; \
    ln -sf /usr/local/bin/bun /usr/local/bin/bunx

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
# Setup Python Virtual Environment for MCP and Skills
# ====================
# Keep one Python dependency environment. Installing the same scientific and
# browser stacks globally and in a venv nearly doubled the complete image.
ENV SKILLS_VENV=/opt/skills-venv
ENV PATH="${SKILLS_VENV}/bin:${PATH}"
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv ${SKILLS_VENV} && \
    python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir \
    pipx uv \
    "aiohttp>=3.9.0" "aiofiles>=24.1.0" "pydantic>=2.5.0" "watchfiles>=0.21.0" \
    virtualenv pipenv poetry ipython black ruff mypy pytest pytest-asyncio

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir \
    pypdf pdfplumber reportlab pdf2image \
    "pillow>=10.0.0" "imageio>=2.31.0" "imageio-ffmpeg>=0.4.9" "numpy>=1.24.0" \
    openpyxl pandas xlrd xlwt \
    python-docx defusedxml lxml \
    playwright markitdown \
    matplotlib seaborn scipy \
    requests httpx \
    typing-extensions jinja2 pyyaml toml

# ====================
# Install Playwright Browsers (webapp-testing skill)
# ====================
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN playwright install --with-deps chromium firefox && \
    chmod -R a+rX /opt/ms-playwright

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
        PW_CHROME=$(find /opt/ms-playwright -name "chrome" -path "*/chrome-linux/*" 2>/dev/null | head -1); \
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
# Install Firefox (use Playwright's Firefox — Ubuntu apt ships snap stubs)
# ====================
# Playwright already installed Firefox with deps; just symlink and create .desktop entry
RUN set -eux; \
    FF_BIN=$(find /opt/ms-playwright -path '*/firefox/firefox' -type f | head -1); \
    FF_DIR=$(dirname "$FF_BIN"); \
    ln -sf "$FF_BIN" /usr/local/bin/firefox; \
    printf '[Desktop Entry]\nVersion=1.0\nType=Application\nName=Firefox\nGenericName=Web Browser\nComment=Mozilla Firefox Web Browser\nExec=%s %%U\nIcon=firefox\nTerminal=false\nCategories=Network;WebBrowser;\nMimeType=text/html;text/xml;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;\nStartupNotify=true\n' \
      "$FF_BIN" > /usr/share/applications/firefox.desktop

# ====================
# Full-profile compiled language toolchains
# ====================
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends golang-go rustc cargo; \
    rm -rf /var/lib/apt/lists/*

# ====================
# Install ttyd for Web Terminal
# ====================
ENV TTYD_VERSION=1.7.7
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    case "$ARCH" in \
        amd64) TTYD_ARCH=x86_64; TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 ;; \
        arm64) TTYD_ARCH=aarch64; TTYD_SHA256=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165 ;; \
        *) echo "Unsupported ttyd architecture: $ARCH"; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${TTYD_ARCH}" \
    -o /usr/local/bin/ttyd; \
    echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c -; \
    chmod +x /usr/local/bin/ttyd

# ====================
# Install KDE Plasma Desktop Environment
# ====================
# Ubuntu 24.04 LTS supplies a supported KDE Plasma desktop stack.
# KDE Plasma provides a modern, feature-rich desktop closest to
# real desktop experience with Dolphin file manager, Konsole terminal,
# and extensive customization options.
# The desktop package set is intentionally split into two cached layers. A
# transient mirror failure must not discard every already-downloaded package.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    sed -i \
        -e 's#http://ports.ubuntu.com#https://ports.ubuntu.com#g' \
        -e 's#http://archive.ubuntu.com#https://archive.ubuntu.com#g' \
        -e 's#Types: deb deb-src#Types: deb#g' \
        /etc/apt/sources.list.d/ubuntu.sources; \
    apt-get -o Acquire::Retries=10 -o Acquire::https::Timeout=30 update; \
    DEBIAN_FRONTEND=noninteractive apt-get \
        -o Acquire::Retries=10 -o Acquire::https::Timeout=30 \
        install -y --no-install-recommends \
        xorg \
        kde-plasma-desktop \
        breeze breeze-icon-theme breeze-cursor-theme \
        plasma-workspace-wallpapers \
        pulseaudio pulseaudio-utils pavucontrol-qt \
        openbox obconf \
        xdg-utils xdg-user-dirs desktop-file-utils shared-mime-info \
        dbus-x11 ssl-cert \
        fonts-freefont-ttf fonts-noto-color-emoji fonts-liberation fonts-dejavu-core \
        fonts-firacode \
        ibus ibus-libpinyin \
        htop xclip xsel

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    apt-get -o Acquire::Retries=10 -o Acquire::https::Timeout=30 update; \
    DEBIAN_FRONTEND=noninteractive apt-get \
        -o Acquire::Retries=10 -o Acquire::https::Timeout=30 \
        install -y --no-install-recommends \
        dolphin konsole \
        kate gwenview \
        okular okular-extra-backends \
        ark kcalc kolourpaint filelight plasma-systemmonitor \
        kcolorchooser kcharselect systemsettings \
        kde-spectacle ksystemlog \
        vlc \
        p7zip-full unrar-free lhasa \
        baobab gnome-disk-utility

RUN set -eux; \
    xdg-user-dirs-update --force 2>/dev/null || true; \
    fc-cache -fv; \
    update-mime-database /usr/share/mime 2>/dev/null || true; \
    update-desktop-database /usr/share/applications 2>/dev/null || true; \
    systemctl disable sddm 2>/dev/null || true

# ====================
# Install KasmVNC (replaces TigerVNC + noVNC + websockify)
# ====================
# KasmVNC is an all-in-one VNC server with built-in web client,
# WebP/QOI encoding, dynamic resize, clipboard, file transfer, and audio.
# KasmVNC v1.4.0 publishes a native Ubuntu 24.04 (noble) package.
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
    # Add the runtime user to ssl-cert group (required by KasmVNC)
    adduser sandbox ssl-cert 2>/dev/null || true; \
    # Pre-create the KasmVNC runtime directory. The entrypoint writes a unique
    # per-sandbox credential to $HOME/.kasmpasswd when the container starts.
    mkdir -p /home/sandbox/.vnc; \
    # Mark DE as already selected to skip interactive select-de.sh prompt
    # KasmVNC's select-de.sh relies on legacy entrypoints, so bypass detection
    # and rely on our own xstartup.
    touch /home/sandbox/.vnc/.de-was-selected; \
    chown -R sandbox:sandbox /home/sandbox

# ====================
# Workspace Setup (runs as root)
# ====================
RUN mkdir -p /workspace /run/user/10001 && \
    chown -R sandbox:sandbox /workspace /run/user/10001 && \
    chmod 700 /run/user/10001

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
    python -m pip install --no-cache-dir -e .

# ====================
# Configuration Files
# ====================
# KDE Plasma configs (Breeze theme defaults)
COPY docker/kde-configs/kdeglobals /etc/xdg/kdeglobals
COPY docker/kde-configs/kwinrc /etc/xdg/kwinrc
COPY docker/kde-configs/katerc /etc/xdg/katerc
COPY docker/kde-configs/dolphinrc /etc/xdg/dolphinrc
COPY docker/kde-configs/konsolerc /etc/xdg/konsolerc

# Konsole profile
RUN mkdir -p /usr/share/konsole
COPY docker/kde-configs/Sandbox.profile /usr/share/konsole/Sandbox.profile

# Openbox window manager config (Breeze-ob theme, used as X11 WM since kwin-x11 is removed)
COPY docker/openbox-configs/rc.xml /etc/xdg/openbox/rc.xml
COPY docker/openbox-configs/menu.xml /etc/xdg/openbox/menu.xml

# KasmVNC configs
COPY docker/kasmvnc-configs/kasmvnc.yaml /etc/kasmvnc/kasmvnc.yaml
COPY docker/kasmvnc-configs/xstartup /etc/kasmvnc/xstartup.template
RUN chmod +x /etc/kasmvnc/xstartup.template

# Entrypoint
COPY scripts/entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod +x /usr/local/bin/sandbox-entrypoint.sh

# Docker CLI only. The daemon is supplied by an explicitly mounted Docker socket or
# remote Docker context when a sandbox is allowed to inspect host/container state.
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

# ====================
# Final Setup
# ====================
# NOTE: Hostname is configured at runtime via --hostname and --add-host parameters
# in mcp_sandbox_adapter.py to support proper VNC hostname resolution

WORKDIR /workspace

ENV HOME=/home/sandbox \
    USER=sandbox \
    XDG_RUNTIME_DIR=/run/user/10001

USER sandbox

HEALTHCHECK --interval=30s --timeout=15s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${MCP_PORT}/health && \
        { [ "$DESKTOP_ENABLED" != "true" ] || timeout 2 bash -c "</dev/tcp/127.0.0.1/${DESKTOP_PORT}"; } && \
        { [ "${TERMINAL_ENABLED:-true}" != "true" ] || timeout 2 bash -c "</dev/tcp/127.0.0.1/${TERMINAL_PORT:-7681}"; } || exit 1

EXPOSE 8765 7681 6080
CMD ["/usr/local/bin/sandbox-entrypoint.sh"]
