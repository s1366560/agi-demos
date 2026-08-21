#!/usr/bin/env bash

set -Eeuo pipefail

readonly SANDBOX_UID=10001
readonly SERVICE_AUTH_USERNAME=sandbox
readonly VNC_DISPLAY=:1
readonly CHROMIUM_EXTENSION_ID=hehggadaopoacecdllhhajmbjkdcmajg
readonly CHROMIUM_NATIVE_HOST_NAME=com.openai.codexextension
readonly CHROMIUM_NATIVE_HOST_PATH=/opt/sky-cua/browser/native-host/sky-cua-chrome-host
readonly CHROMIUM_EXTENSION_PATH=/opt/sky-cua/browser/extension
readonly CHROMIUM_PROFILE_PATH=/home/sandbox/.config/chromium

MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_PORT="${MCP_PORT:-8765}"
DESKTOP_ENABLED="${DESKTOP_ENABLED:-true}"
DESKTOP_RESOLUTION="${DESKTOP_RESOLUTION:-1920x1080}"
DESKTOP_PORT="${DESKTOP_PORT:-6080}"
TERMINAL_ENABLED="${TERMINAL_ENABLED:-true}"
TERMINAL_PORT="${TERMINAL_PORT:-7681}"
SKIP_MCP_SERVER="${SKIP_MCP_SERVER:-false}"
SERVICE_AUTH_TOKEN="${SANDBOX_SERVICE_AUTH_TOKEN:-${MCP_STATIC_TOKEN:-}}"
CONTAINER_HOSTNAME="${SANDBOX_ID:-$(cat /etc/hostname)}"

DBUS_PID=""
VNC_LAUNCH_PID=""
CHROMIUM_PID=""
MCP_PID=""
TTYD_PID=""

log_info() {
    printf '[INFO] %s\n' "$*"
}

log_success() {
    printf '[OK] %s\n' "$*"
}

log_error() {
    printf '[ERROR] %s\n' "$*" >&2
}

terminate_pid() {
    local pid="$1"
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
        kill "${pid}" 2>/dev/null || true
    fi
}

cleanup() {
    local exit_code=$?
    set +e
    log_info "Shutting down sandbox services"
    terminate_pid "${MCP_PID}"
    terminate_pid "${TTYD_PID}"
    terminate_pid "${CHROMIUM_PID}"
    if [ -n "${VNC_LAUNCH_PID}" ]; then
        terminate_pid "${VNC_LAUNCH_PID}"
    fi
    vncserver -kill "${VNC_DISPLAY}" >/dev/null 2>&1 || true
    terminate_pid "${DBUS_PID}"
    wait 2>/dev/null || true
    exit "${exit_code}"
}

trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

wait_for_port() {
    local port="$1"
    local timeout_seconds="$2"
    local elapsed=0

    while [ "${elapsed}" -lt "${timeout_seconds}" ]; do
        if netstat -lnt 2>/dev/null | grep -q ":${port} "; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

ensure_owned_directory() {
    local path="$1"
    local mode="$2"

    mkdir -p "${path}"
    if [ "$(stat -c '%u' "${path}")" != "${SANDBOX_UID}" ]; then
        log_error "Directory is not owned by uid ${SANDBOX_UID}: ${path}"
        return 1
    fi
    chmod "${mode}" "${path}"
}

configure_hostname() {
    if ! grep -Fq "${CONTAINER_HOSTNAME}" /etc/hosts 2>/dev/null; then
        log_error "Container hostname is not present in /etc/hosts: ${CONTAINER_HOSTNAME}"
        return 1
    fi
    log_success "Container hostname is configured: ${CONTAINER_HOSTNAME}"
}

prepare_session_directories() {
    if [ "$(id -u)" != "${SANDBOX_UID}" ]; then
        log_error "Entrypoint must run as uid ${SANDBOX_UID}"
        return 1
    fi
    if [ "${HOME}" != "/home/sandbox" ]; then
        log_error "HOME must remain /home/sandbox, got ${HOME}"
        return 1
    fi
    if [ "${DISPLAY}" != "${VNC_DISPLAY}" ]; then
        log_error "DISPLAY must remain ${VNC_DISPLAY}, got ${DISPLAY}"
        return 1
    fi

    umask 077
    ensure_owned_directory "${XDG_RUNTIME_DIR}" 0700
    ensure_owned_directory "${XDG_RUNTIME_DIR}/sky-cua" 0700
    ensure_owned_directory "${SKY_CUA_BROWSER_USE_SOCKET_DIR}" 0700
    ensure_owned_directory "${SKY_CUA_BROWSER_USE_SESSIONS_DIR}" 0700
    ensure_owned_directory "${CHROMIUM_PROFILE_PATH}" 0700
    ensure_owned_directory "${HOME}/.vnc" 0700
    ensure_owned_directory "${HOME}/.config/openbox" 0700

    rm -f \
        "${XDG_RUNTIME_DIR}/bus" \
        "${SKY_CUA_SERVICE_SOCKET_PATH}" \
        "${SKY_CUA_SERVICE_SOCKET_PATH}.lock" \
        "${SKY_CUA_SERVICE_SOCKET_PATH}.lifecycle.lock" \
        "${SKY_CUA_CODEX_BROWSER_SOCKET_PATH}" \
        /tmp/.X1-lock \
        /tmp/.X11-unix/X1
    find "${SKY_CUA_BROWSER_USE_SOCKET_DIR}" -maxdepth 1 \
        -type s -name 'extension-*.sock' -delete

    cp /etc/xdg/openbox/rc.xml "${HOME}/.config/openbox/rc.xml"
    cp /etc/xdg/openbox/menu.xml "${HOME}/.config/openbox/menu.xml"
    cp /etc/kasmvnc/xstartup.template "${HOME}/.vnc/xstartup"
    cp /etc/kasmvnc/kasmvnc.yaml "${HOME}/.vnc/kasmvnc.yaml"
    chmod 0755 "${HOME}/.vnc/xstartup"
    touch "${HOME}/.vnc/.de-was-selected"
}

start_session_dbus() {
    log_info "Starting the shared session D-Bus"
    DBUS_PID="$(dbus-daemon \
        --session \
        --fork \
        --nopidfile \
        --address="${DBUS_SESSION_BUS_ADDRESS}" \
        --print-pid=1)"
    case "${DBUS_PID}" in
        ''|*[!0-9]*)
            log_error "dbus-daemon returned an invalid pid: ${DBUS_PID}"
            return 1
            ;;
    esac

    local elapsed=0
    while [ "${elapsed}" -lt 10 ]; do
        if [ -S "${XDG_RUNTIME_DIR}/bus" ] \
            && dbus-send --session --print-reply \
                --dest=org.freedesktop.DBus \
                /org/freedesktop/DBus \
                org.freedesktop.DBus.ListNames >/dev/null 2>&1; then
            log_success "Session D-Bus is ready"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    log_error "Session D-Bus did not become ready"
    return 1
}

activate_at_spi() {
    log_info "Activating org.a11y.Bus"
    local elapsed=0
    local address_file=/tmp/sky-cua-at-spi-address

    while [ "${elapsed}" -lt 15 ]; do
        if gdbus call \
            --session \
            --dest org.a11y.Bus \
            --object-path /org/a11y/bus \
            --method org.a11y.Bus.GetAddress >"${address_file}" 2>/dev/null \
            && grep -q 'unix:' "${address_file}"; then
            gsettings set org.gnome.desktop.interface toolkit-accessibility true
            if [ "$(gsettings get org.gnome.desktop.interface toolkit-accessibility)" \
                != true ]; then
                log_error "GTK toolkit accessibility did not remain enabled"
                return 1
            fi
            log_success "AT-SPI bus is ready: $(tr -d '\n' <"${address_file}")"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    log_error "org.a11y.Bus did not return an AT-SPI address"
    return 1
}

start_kasmvnc() {
    log_info "Starting KasmVNC on ${VNC_DISPLAY}"
    printf '%s\n%s\n' "${SERVICE_AUTH_TOKEN}" "${SERVICE_AUTH_TOKEN}" \
        | vncpasswd \
            -u "${SERVICE_AUTH_USERNAME}" \
            -w "${HOME}/.kasmpasswd" >/dev/null
    chmod 0600 "${HOME}/.kasmpasswd"

    # KasmVNC authenticates HTTP and WebSocket upgrades with the password file below.
    # No legacy RFB viewer is exposed, so avoid a second VncAuth/DES prompt afterwards.
    vncserver "${VNC_DISPLAY}" \
        -geometry "${DESKTOP_RESOLUTION}" \
        -depth 24 \
        -websocketPort "${DESKTOP_PORT}" \
        -interface 0.0.0.0 \
        -KasmPasswordFile "${HOME}/.kasmpasswd" \
        -SecurityTypes None \
        > /tmp/kasmvnc.log 2>&1 &
    VNC_LAUNCH_PID=$!

    if ! wait_for_port "${DESKTOP_PORT}" 30; then
        log_error "KasmVNC did not listen on port ${DESKTOP_PORT}"
        tail -n 100 /tmp/kasmvnc.log >&2 || true
        return 1
    fi
    log_success "KasmVNC web endpoint is ready on port ${DESKTOP_PORT}"
}

wait_for_x11_session() {
    log_info "Waiting for X11 extensions, xrandr, and Openbox EWMH"
    local elapsed=0
    local extensions_file=/tmp/sky-cua-x11-extensions

    while [ "${elapsed}" -lt 30 ]; do
        if [ -S /tmp/.X11-unix/X1 ] \
            && xdpyinfo -display "${DISPLAY}" -queryExtensions \
                >"${extensions_file}" 2>/dev/null \
            && grep -q 'XTEST' "${extensions_file}" \
            && grep -q 'MIT-SHM' "${extensions_file}" \
            && xrandr --display "${DISPLAY}" --query >/dev/null 2>&1 \
            && xprop -display "${DISPLAY}" -root _NET_SUPPORTING_WM_CHECK 2>/dev/null \
                | grep -q 'window id' \
            && wmctrl -m 2>/dev/null | grep -Fq 'Name: Openbox'; then
            log_success "X11, XTEST, MIT-SHM, xrandr, and Openbox are ready"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    log_error "The shared Openbox/X11 session did not become ready"
    tail -n 100 /tmp/kasmvnc.log >&2 || true
    return 1
}

install_chromium_native_host() {
    log_info "Installing the Chromium native-host manifest"
    "${CHROMIUM_NATIVE_HOST_PATH}" install-manifest \
        --browser chromium \
        --host-name "${CHROMIUM_NATIVE_HOST_NAME}" \
        --extension-id "${CHROMIUM_EXTENSION_ID}" \
        --host-path "${CHROMIUM_NATIVE_HOST_PATH}"

    local manifest_path="${CHROMIUM_PROFILE_PATH}/NativeMessagingHosts/${CHROMIUM_NATIVE_HOST_NAME}.json"
    jq -e \
        --arg path "${CHROMIUM_NATIVE_HOST_PATH}" \
        --arg origin "chrome-extension://${CHROMIUM_EXTENSION_ID}/" \
        '.name == "com.openai.codexextension"
         and .path == $path
         and .type == "stdio"
         and .allowed_origins == [$origin]' \
        "${manifest_path}" >/dev/null
    log_success "Chromium native-host manifest is installed"
}

start_chromium() {
    log_info "Starting Chromium with the pinned sky-cua extension"
    chromium \
        --user-data-dir="${CHROMIUM_PROFILE_PATH}" \
        --ozone-platform=x11 \
        --force-renderer-accessibility \
        --disable-extensions-except="${CHROMIUM_EXTENSION_PATH}" \
        --load-extension="${CHROMIUM_EXTENSION_PATH}" \
        --remote-debugging-port=0 \
        --silent-debugger-extension-api \
        --no-first-run \
        --no-default-browser-check \
        about:blank \
        > /tmp/chromium.log 2>&1 &
    CHROMIUM_PID=$!

    local elapsed=0
    while [ "${elapsed}" -lt 45 ]; do
        if ! kill -0 "${CHROMIUM_PID}" 2>/dev/null; then
            log_error "Chromium exited before a browser window appeared"
            tail -n 100 /tmp/chromium.log >&2 || true
            return 1
        fi
        if wmctrl -lx 2>/dev/null | grep -qi 'chromium'; then
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    if [ "${elapsed}" -ge 45 ]; then
        log_error "Chromium did not expose a visible X11 window"
        tail -n 100 /tmp/chromium.log >&2 || true
        return 1
    fi

    elapsed=0
    while [ "${elapsed}" -lt 45 ]; do
        local bridge_socket
        bridge_socket="$(find "${SKY_CUA_BROWSER_USE_SOCKET_DIR}" -maxdepth 1 \
            -type s -name 'extension-*.sock' -print -quit)"
        if [ -n "${bridge_socket}" ]; then
            log_success "Chromium bridge is ready: ${bridge_socket}"
            return 0
        fi
        if ! kill -0 "${CHROMIUM_PID}" 2>/dev/null; then
            log_error "Chromium exited before the extension bridge was ready"
            tail -n 100 /tmp/chromium.log >&2 || true
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_error "No extension-*.sock bridge appeared"
    tail -n 100 /tmp/chromium.log >&2 || true
    return 1
}

start_mcp_server() {
    if [ "${SKIP_MCP_SERVER}" = true ]; then
        log_info "Skipping the main MCP server"
        return 0
    fi

    log_info "Starting the main MCP server on ${MCP_HOST}:${MCP_PORT}"
    (
        cd /workspace
        exec python -m src.server.main
    ) &
    MCP_PID=$!

    if ! wait_for_port "${MCP_PORT}" 30; then
        log_error "The main MCP server did not listen on port ${MCP_PORT}"
        return 1
    fi
    log_success "The main MCP server is ready"
}

start_ttyd() {
    if [ "${TERMINAL_ENABLED}" != true ]; then
        return 0
    fi

    log_info "Starting ttyd on port ${TERMINAL_PORT}"
    (
        cd /workspace
        exec ttyd \
            -W \
            -c "${SERVICE_AUTH_USERNAME}:${SERVICE_AUTH_TOKEN}" \
            -p "${TERMINAL_PORT}" \
            -- /bin/bash
    ) &
    TTYD_PID=$!

    if ! wait_for_port "${TERMINAL_PORT}" 15; then
        log_error "ttyd did not listen on port ${TERMINAL_PORT}"
        return 1
    fi
    log_success "ttyd is ready"
}

wait_for_primary_process() {
    if [ -n "${MCP_PID}" ]; then
        wait "${MCP_PID}"
        return $?
    fi
    if [ -n "${CHROMIUM_PID}" ]; then
        wait "${CHROMIUM_PID}"
        return $?
    fi
    if [ -n "${TTYD_PID}" ]; then
        wait "${TTYD_PID}"
        return $?
    fi
    log_error "No long-lived sandbox process was started"
    return 1
}

main() {
    configure_hostname

    if { [ "${DESKTOP_ENABLED}" = true ] || [ "${TERMINAL_ENABLED}" = true ]; } \
        && [ -z "${SERVICE_AUTH_TOKEN}" ]; then
        log_error "Interactive services require SANDBOX_SERVICE_AUTH_TOKEN"
        return 1
    fi

    prepare_session_directories
    start_session_dbus
    activate_at_spi

    if [ "${DESKTOP_ENABLED}" = true ]; then
        start_kasmvnc
        wait_for_x11_session
        install_chromium_native_host
        start_chromium
    fi

    start_mcp_server
    start_ttyd

    log_success "All requested sandbox services are ready"
    wait_for_primary_process
}

main "$@"
