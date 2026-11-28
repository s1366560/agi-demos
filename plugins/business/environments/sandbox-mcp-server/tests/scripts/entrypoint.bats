#!/usr/bin/env bats
# Unit tests for entrypoint.sh functions

load 'test_helper/bats-support/load'
load 'test_helper/bats/assert/load'

# Source the entrypoint script to test functions
# We'll test individual functions by sourcing them

setup() {
    # Set up test environment variables
    export MCP_HOST="127.0.0.1"
    export MCP_PORT="8765"
    export DESKTOP_ENABLED="false"
    export TERMINAL_PORT="7681"
    export SANDBOX_USER="sandbox"
    export VNC_SERVER_TYPE="tigervnc"
    export SKIP_MCP_SERVER="true"
}

@test "log_info outputs info message" {
    run bash -c 'source scripts/entrypoint.sh && log_info "test message"'
    [ "$status" -eq 0 ]
    [[ "$output" == *"[INFO]"* ]]
    [[ "$output" == *"test message"* ]]
}

@test "log_success outputs success message" {
    run bash -c 'source scripts/entrypoint.sh && log_success "test success"'
    [ "$status" -eq 0 ]
    [[ "$output" == *"[OK]"* ]]
    [[ "$output" == *"test success"* ]]
}

@test "log_warn outputs warning message" {
    run bash -c 'source scripts/entrypoint.sh && log_warn "test warning"'
    [ "$status" -eq 0 ]
    [[ "$output" == *"[WARN]"* ]]
    [[ "$output" == *"test warning"* ]]
}

@test "log_error outputs error message" {
    run bash -c 'source scripts/entrypoint.sh && log_error "test error"'
    [ "$status" -eq 0 ]
    [[ "$output" == *"[ERROR]"* ]]
    [[ "$output" == *"test error"* ]]
}

@test "default configuration values are set" {
    run bash -c 'source scripts/entrypoint.sh && echo $MCP_PORT'
    [ "$output" == "8765" ]
}

@test "custom MCP_PORT overrides default" {
    export MCP_PORT="9999"
    run bash -c 'source scripts/entrypoint.sh && echo $MCP_PORT'
    [ "$output" == "9999" ]
}

@test "custom TERMINAL_PORT overrides default" {
    export TERMINAL_PORT="8080"
    run bash -c 'source scripts/entrypoint.sh && echo $TERMINAL_PORT'
    [ "$output" == "8080" ]
}

@test "DESKTOP_ENABLED can be set to false" {
    export DESKTOP_ENABLED="false"
    run bash -c 'source scripts/entrypoint.sh && echo $DESKTOP_ENABLED'
    [ "$output" == "false" ]
}

@test "VNC_SERVER_TYPE defaults to tigervnc" {
    run bash -c 'source scripts/entrypoint.sh && echo $VNC_SERVER_TYPE'
    [ "$output" == "tigervnc" ]
}

@test "VNC_SERVER_TYPE can be set to x11vnc" {
    export VNC_SERVER_TYPE="x11vnc"
    run bash -c 'source scripts/entrypoint.sh && echo $VNC_SERVER_TYPE'
    [ "$output" == "x11vnc" ]
}

@test "SANDBOX_USER defaults to sandbox" {
    run bash -c 'source scripts/entrypoint.sh && echo $SANDBOX_USER'
    [ "$output" == "sandbox" ]
}

@test "custom SANDBOX_USER overrides default" {
    export SANDBOX_USER="testuser"
    run bash -c 'source scripts/entrypoint.sh && echo $SANDBOX_USER'
    [ "$output" == "testuser" ]
}

@test "SKIP_MCP_SERVER defaults to false" {
    run bash -c 'source scripts/entrypoint.sh && echo $SKIP_MCP_SERVER'
    [ "$output" == "false" ]
}

@test "SKIP_MCP_SERVER can be set to true" {
    export SKIP_MCP_SERVER="true"
    run bash -c 'source/entrypoint.sh && echo $SKIP_MCP_SERVER'
    [ "$output" == "true" ]
}

@test "DESKTOP_RESOLUTION defaults to 1920x1080" {
    run bash -c 'source scripts/entrypoint.sh && echo $DESKTOP_RESOLUTION'
    [ "$output" == "1920x1080" ]
}

@test "DESKTOP_RESOLUTION can be customized" {
    export DESKTOP_RESOLUTION="1280x720"
    run bash -c 'source scripts/entrypoint.sh && echo $DESKTOP_RESOLUTION'
    [ "$output" == "1280x720" ]
}

@test "DESKTOP_PORT defaults to 6080" {
    run bash -c 'source scripts/entrypoint.sh && echo $DESKTOP_PORT'
    [ "$output" == "6080" ]
}

@test "cleanup function can be sourced without errors" {
    run bash -c 'source scripts/entrypoint.sh && type cleanup'
    [ "$status" -eq 0 ]
}

@test "start_xvfb function is defined" {
    run bash -c 'source scripts/entrypoint.sh && type start_xvfb'
    [ "$status" -eq 0 ]
}

@test "start_desktop function is defined" {
    run bash -c 'source scripts/entrypoint.sh && type start_desktop'
    [ "$status" -eq 0 ]
}

@test "start_tigervnc function is defined" {
    run bash -c 'source scripts/entrypoint.sh && type start_tigervnc'
    [ "$status" -eq 0 ]
}

@test "start_x11vnc function is defined" {
    run bash -c 'source scripts/entrypoint.sh && type start_x11vnc'
    [ "$status" -eq 0 ]
}

@test "start_novnc function is defined" {
    run bash -c 'source scripts/entrypoint.sh && type start_novnc'
    [ "$status" -eq 0 ]
}

@test "start_ttyd function is defined" {
    run bash -c 'source scripts/entrypoint.sh && type start_ttyd'
    [ "$status" -eq 0 ]
}

@test "start_mcp_server function is defined" {
    run bash -c 'source scripts/entrypoint.sh && type start_mcp_server'
    [ "$status" -eq 0 ]
}

@test "main function is defined" {
    run bash -c 'source scripts/entrypoint.sh && type main'
    [ "$status" -eq 0 ]
}
