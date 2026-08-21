# syntax=docker/dockerfile:1.7

ARG RUST_VERSION=1.97.1
ARG NODE_VERSION=22
ARG PYTHON_VERSION=3.12
ARG PLAYWRIGHT_VERSION=1.57.0

FROM rust:${RUST_VERSION}-bookworm AS sky-cua-builder

ARG RUST_VERSION
ARG SKY_CUA_COMMIT=9e4d9f0baa04b001631f9c8dd73dab439988524a
ENV RUSTUP_TOOLCHAIN=${RUST_VERSION}

RUN rustc --version | grep -F "rustc ${RUST_VERSION} "

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cmake \
        git \
        libegl1-mesa-dev \
        libgstreamer-plugins-base1.0-dev \
        libgstreamer1.0-dev \
        libwayland-dev \
        libxkbcommon-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/sky-cua

RUN git init \
    && git remote add origin https://github.com/becksclair/sky-cua.git \
    && git fetch --depth 1 origin "${SKY_CUA_COMMIT}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${SKY_CUA_COMMIT}"

RUN --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,target=/build/sky-cua/target,sharing=locked \
    cargo build --locked --release \
        -p sky-cua-client \
        -p sky-cua-service \
        -p sky-cua-chrome-host \
    && install -D -m 0755 target/release/sky-cua-client /out/bin/sky-cua-client \
    && install -D -m 0755 target/release/sky-cua-service /out/bin/sky-cua-service \
    && install -D -m 0755 \
        target/release/sky-cua-chrome-host \
        /out/browser/native-host/sky-cua-chrome-host \
    && strip --strip-unneeded \
        /out/bin/sky-cua-client \
        /out/bin/sky-cua-service \
        /out/browser/native-host/sky-cua-chrome-host \
    && mkdir -p /out/resources /out/browser \
    && cp -a resources/app-instructions /out/resources/app-instructions \
    && cp -a \
        resources/chrome-extension/codex/1.2.27221.15725_0 \
        /out/browser/extension

FROM node:${NODE_VERSION}-bookworm-slim AS node-runtime

ARG PNPM_VERSION=11.15.1

RUN npm install --global "pnpm@${PNPM_VERSION}" \
    && npm cache clean --force

FROM node:${NODE_VERSION}-bookworm-slim AS playwright-browser

ARG PLAYWRIGHT_VERSION
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

RUN npx --yes "playwright@${PLAYWRIGHT_VERSION}" install chromium --no-shell \
    && find "${PLAYWRIGHT_BROWSERS_PATH}" -mindepth 1 -maxdepth 1 \
        ! -name 'chromium-*' -exec rm -rf '{}' + \
    && rm -rf /root/.npm

FROM python:${PYTHON_VERSION}-slim-bookworm AS python-wheel-builder

WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip wheel --no-cache-dir --wheel-dir /wheelhouse .

FROM ubuntu:24.04 AS python-runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-wheel-builder /wheelhouse /wheelhouse

RUN python3 -m venv /opt/sandbox-mcp-venv \
    && /opt/sandbox-mcp-venv/bin/pip install \
        --no-cache-dir \
        --no-index \
        --find-links=/wheelhouse \
        sandbox-mcp-server==0.1.0 \
    && rm -rf /wheelhouse

FROM ubuntu:24.04

ARG KASMVNC_VERSION=1.4.0
ARG TTYD_VERSION=1.7.7
ARG TARGETARCH

LABEL org.opencontainers.image.title="MemStack Sandbox MCP Server" \
      org.opencontainers.image.description="Openbox/X11 sandbox with sky-cua and Chromium" \
      org.opencontainers.image.vendor="MemStack" \
      org.opencontainers.image.version="sky-cua-0.3.1"

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    LANGUAGE=zh_CN:en \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8765 \
    MCP_WORKSPACE=/workspace \
    DESKTOP_ENABLED=true \
    DESKTOP_RESOLUTION=1920x1080 \
    DESKTOP_PORT=6080 \
    TERMINAL_ENABLED=true \
    TERMINAL_PORT=7681 \
    HOME=/home/sandbox \
    USER=sandbox \
    LOGNAME=sandbox \
    DISPLAY=:1 \
    XAUTHORITY=/home/sandbox/.Xauthority \
    XDG_SESSION_TYPE=x11 \
    XDG_CURRENT_DESKTOP=Openbox \
    DESKTOP_SESSION=openbox \
    XDG_RUNTIME_DIR=/run/user/10001 \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/10001/bus \
    NO_AT_BRIDGE=0 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    CHROME_BIN=/usr/local/bin/chromium \
    CHROME_PATH=/usr/local/bin/chromium \
    SKY_CUA_REPO_ROOT=/opt/sky-cua \
    SKY_CUA_SERVICE_PATH=/opt/sky-cua/bin/sky-cua-service \
    SKY_CUA_SERVICE_SOCKET_PATH=/run/user/10001/sky-cua/service.sock \
    SKY_CUA_CODEX_BROWSER_SOCKET_PATH=/run/user/10001/sky-cua/codex-browser.sock \
    SKY_CUA_BROWSER_USE_SOCKET_DIR=/run/user/10001/sky-cua/browser \
    CODEX_BROWSER_USE_SOCKET_DIR=/run/user/10001/sky-cua/browser \
    SKY_CUA_BROWSER_USE_SESSIONS_DIR=/run/user/10001/sky-cua/sessions \
    CODEX_BROWSER_USE_SESSIONS_DIR=/run/user/10001/sky-cua/sessions \
    SKY_CUA_SURFACES=desktop,browser \
    SKY_CUA_BROWSER=chromium \
    SKY_CUA_INPUT_BACKEND=x11 \
    SKY_CUA_ISOLATED_DESKTOP=0 \
    SKY_CUA_PHONE=0 \
    SKY_CUA_AGENT_CURSOR=0 \
    SKY_CUA_SCREENSHOT_CURSOR=0 \
    PATH=/opt/sandbox-mcp-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        at-spi2-core \
        bash \
        ca-certificates \
        curl \
        dbus \
        dbus-x11 \
        desktop-file-utils \
        dnsutils \
        file \
        fonts-dejavu-core \
        fonts-liberation \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        git \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-tools \
        gstreamer1.0-x \
        iputils-ping \
        jq \
        less \
        libasound2t64 \
        libatk-bridge2.0-0t64 \
        libatk1.0-0t64 \
        libatspi2.0-0t64 \
        libcairo2 \
        libcups2t64 \
        libdbus-1-3 \
        libdrm2 \
        libegl1 \
        libgbm1 \
        libglib2.0-0t64 \
        libglib2.0-bin \
        libgtk-3-0t64 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libstdc++6 \
        libvulkan1 \
        libwayland-client0 \
        libwayland-cursor0 \
        libwayland-egl1 \
        libx11-6 \
        libx11-xcb1 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
        locales \
        mesa-vulkan-drivers \
        nano \
        net-tools \
        openbox \
        procps \
        python3 \
        shared-mime-info \
        ssl-cert \
        sudo \
        x11-utils \
        x11-xserver-utils \
        xauth \
        xclip \
        xdg-user-dirs \
        xdg-utils \
        xdotool \
        xsel \
        xterm \
        wmctrl \
    && case "${TARGETARCH}" in \
        amd64) \
            KASM_ARCH=amd64; \
            KASM_SHA256=12bac6014149c5fdee75f0d403785aaa3e5dd4ea222de73253a5d4181bc9567e \
            ;; \
        arm64) \
            KASM_ARCH=arm64; \
            KASM_SHA256=120d9462cb5e917cad91a23f6cb0b780c06f701def40e900b29f996979200638 \
            ;; \
        *) echo "unsupported KasmVNC architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL \
        "https://github.com/kasmtech/KasmVNC/releases/download/v${KASMVNC_VERSION}/kasmvncserver_noble_${KASMVNC_VERSION}_${KASM_ARCH}.deb" \
        -o /tmp/kasmvnc.deb \
    && echo "${KASM_SHA256}  /tmp/kasmvnc.deb" | sha256sum -c - \
    && apt-get install -y --no-install-recommends /tmp/kasmvnc.deb \
    && rm -f /tmp/kasmvnc.deb \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i '/zh_CN.UTF-8/s/^# //g' /etc/locale.gen \
    && locale-gen zh_CN.UTF-8

RUN case "${TARGETARCH}" in \
        amd64) \
            TTYD_ARCH=x86_64; \
            TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 \
            ;; \
        arm64) \
            TTYD_ARCH=aarch64; \
            TTYD_SHA256=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165 \
            ;; \
        *) echo "unsupported ttyd architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL \
        "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${TTYD_ARCH}" \
        -o /usr/local/bin/ttyd \
    && echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c - \
    && chmod 0755 /usr/local/bin/ttyd

RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash sandbox \
    && usermod --append --groups ssl-cert sandbox \
    && install -d -m 0755 -o sandbox -g sandbox /workspace \
    && install -d -m 0700 -o sandbox -g sandbox \
        /run/user/10001 \
        /run/user/10001/sky-cua \
        /run/user/10001/sky-cua/browser \
        /run/user/10001/sky-cua/sessions \
        /home/sandbox/.config \
        /home/sandbox/.config/chromium \
        /home/sandbox/.config/openbox \
        /home/sandbox/.vnc \
    && touch /home/sandbox/.vnc/.de-was-selected \
    && chown sandbox:sandbox /home/sandbox/.vnc/.de-was-selected

COPY --from=node-runtime /usr/local/ /usr/local/
COPY --from=python-runtime /opt/sandbox-mcp-venv /opt/sandbox-mcp-venv
COPY --from=playwright-browser /opt/ms-playwright /opt/ms-playwright
COPY --from=sky-cua-builder /out/ /opt/sky-cua/

RUN chromium_path="$(find /opt/ms-playwright -type f -path '*/chrome-linux*/chrome' -print -quit)" \
    && test -n "${chromium_path}" \
    && ln -s "${chromium_path}" /usr/local/bin/chromium \
    && sandbox_path="$(dirname "${chromium_path}")/chrome_sandbox" \
    && test -f "${sandbox_path}" \
    && case "${TARGETARCH}" in \
        amd64) binary_arch='x86-64' ;; \
        arm64) binary_arch='ARM aarch64' ;; \
        *) echo "unsupported target architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && for binary in \
        /opt/sky-cua/bin/sky-cua-client \
        /opt/sky-cua/bin/sky-cua-service \
        /opt/sky-cua/browser/native-host/sky-cua-chrome-host; do \
        file "${binary}" | grep -F "${binary_arch}"; \
        if ldd "${binary}" | grep -q 'not found'; then \
            ldd "${binary}"; \
            exit 1; \
        fi; \
    done \
    && test "$(jq -r .version /opt/sky-cua/browser/extension/manifest.json)" = \
        '1.2.27221.15725' \
    && test -f /opt/sky-cua/resources/app-instructions/index.json \
    && chown -R root:root /opt/sky-cua /opt/ms-playwright /opt/sandbox-mcp-venv \
    && chmod -R a+rX /opt/sky-cua /opt/ms-playwright /opt/sandbox-mcp-venv \
    && chown root:root "${sandbox_path}" \
    && chmod 4755 "${sandbox_path}"

COPY docker/openbox-configs/rc.xml /etc/xdg/openbox/rc.xml
COPY docker/openbox-configs/menu.xml /etc/xdg/openbox/menu.xml
COPY docker/kasmvnc-configs/kasmvnc.yaml /etc/kasmvnc/kasmvnc.yaml
COPY docker/kasmvnc-configs/xstartup /etc/kasmvnc/xstartup.template
COPY docker/seccomp-profile.json /opt/seccomp/default.json
COPY docker/sudoers /etc/sudoers.d/sandbox
COPY scripts/entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh

RUN chmod 0440 /etc/sudoers.d/sandbox \
    && chmod 0755 /etc/kasmvnc/xstartup.template /usr/local/bin/sandbox-entrypoint.sh \
    && cp /etc/xdg/openbox/rc.xml /home/sandbox/.config/openbox/rc.xml \
    && cp /etc/xdg/openbox/menu.xml /home/sandbox/.config/openbox/menu.xml \
    && chown -R sandbox:sandbox /home/sandbox/.config/openbox \
    && fc-cache -f

WORKDIR /workspace
USER sandbox

HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${MCP_PORT}/health" >/dev/null \
        && { [ "${DESKTOP_ENABLED}" != true ] \
             || { test -S /tmp/.X11-unix/X1 \
                  && find "${SKY_CUA_BROWSER_USE_SOCKET_DIR}" -maxdepth 1 \
                      -type s -name 'extension-*.sock' -print -quit | grep -q .; }; } \
        && { [ "${TERMINAL_ENABLED}" != true ] \
             || timeout 2 bash -c "</dev/tcp/127.0.0.1/${TERMINAL_PORT}"; }

EXPOSE 8765 7681 6080

CMD ["/usr/local/bin/sandbox-entrypoint.sh"]
