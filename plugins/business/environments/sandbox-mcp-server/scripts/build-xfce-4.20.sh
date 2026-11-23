#!/bin/bash
# Build and Install XFCE 4.20 from Source
# This script downloads and compiles XFCE 4.20 components to upgrade from 4.18

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Build directory
BUILD_DIR="/tmp/xfce-4.20-build"
INSTALL_PREFIX="/usr"

# Clean and create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# XFCE 4.20 component versions
declare -A COMPONENTS=(
    ["xfce4-dev-tools"]="4.20.0"
    ["libxfce4util"]="4.20.1"
    ["xfconf"]="4.20.0"
    ["libxfce4ui"]="4.20.0"
    ["garcon"]="4.20.0"
    ["exo"]="4.20.0"
    ["libxfce4windowing"]="4.20.0"
    ["xfce4-panel"]="4.20.0"
    ["xfce4-appfinder"]="4.20.0"
    ["xfce4-terminal"]="1.1.0"
    ["xfwm4"]="4.20.0"
    ["thunar"]="4.20.0"
    ["tumbler"]="4.20.0"
)

# Build order - dependencies first
BUILD_ORDER=(
    "xfce4-dev-tools"
    "libxfce4util"
    "xfconf"
    "libxfce4ui"
    "garcon"
    "exo"
    "libxfce4windowing"
    "xfce4-panel"
    "xfce4-appfinder"
    "xfce4-terminal"
    "xfwm4"
    "thunar"
    "tumbler"
)

# Base URL for XFCE downloads
BASE_URL="https://archive.xfce.org/src/xfce"

# Function to get subdirectory for a component
get_subdir() {
    local comp=$1
    case "$comp" in
        libxfce4util) echo "xfce4/libxfce4util" ;;
        xfconf) echo "xfce/xfconf" ;;
        libxfce4ui) echo "xfce4/libxfce4ui" ;;
        garcon) echo "xfce4/garcon" ;;
        exo) echo "xfce/exo" ;;
        xfce4-panel) echo "xfce4/xfce4-panel" ;;
        xfce4-session) echo "xfce/xfce4-session" ;;
        xfwm4) echo "xfce/xfwm4" ;;
        xfdesktop) echo "xfce/xfdesktop" ;;
        thunar) echo "xfce/thunar" ;;
        tumbler) echo "xfce/tumbler" ;;
        xfce4-appfinder) echo "xfce/xfce4-appfinder" ;;
        xfce4-settings) echo "xfce/xfce4-settings" ;;
        xfce4-terminal) echo "apps/xfce4-terminal" ;;
        xfce4-dev-tools) echo "xfce/xfce4-dev-tools" ;;
        libxfce4windowing) echo "xfce/libxfce4windowing" ;;
    esac
}

# Function to build a component
build_component() {
    local comp=$1
    local version=$2

    log_info "Building $comp-$version..."

    local subdir=$(get_subdir "$comp")
    local version_dir="${version%.*}"
    local url="${BASE_URL}/${subdir}/${version_dir}/${comp}-${version}.tar.bz2"
    local tarball="${comp}-${version}.tar.bz2"

    # Download
    log_info "Downloading $comp from $url..."
    if ! wget -q --show-progress "$url" -O "$tarball"; then
        log_error "Failed to download $comp-$version"
        return 1
    fi

    # Extract
    log_info "Extracting $tarball..."
    tar xjf "$tarball"
    cd "${comp}-${version}"

    # Configure with proper paths
    log_info "Configuring $comp..."
    ./configure \
        --prefix="$INSTALL_PREFIX" \
        --sysconfdir=/etc \
        --localstatedir=/var \
        --disable-static \
        --enable-introspection=no \
        --enable-gtk-doc=no \
        --enable-debug=no \
        CFLAGS="-O2" \
    2>&1 | tee configure.log | tail -5

    # Build
    log_info "Compiling $comp..."
    make -j$(nproc) 2>&1 | tee build.log | tail -5

    # Install
    log_info "Installing $comp..."
    make install 2>&1 | tail -5

    # Update library cache
    ldconfig

    cd "$BUILD_DIR"
    log_success "$comp-$version built and installed"

    return 0
}

# Main build process
main() {
    log_info "Starting XFCE 4.20 build process..."
    log_info "Build directory: $BUILD_DIR"
    log_info "Install prefix: $INSTALL_PREFIX"
    echo ""

    # Set PKG_CONFIG_PATH to prefer /usr/lib over multiarch directories
    export PKG_CONFIG_PATH="/usr/lib/pkgconfig:$PKG_CONFIG_PATH"
    export LD_LIBRARY_PATH="/usr/lib:$LD_LIBRARY_PATH"

    local built=0
    local failed=0

    # Build each component in order
    for comp in "${BUILD_ORDER[@]}"; do
        version="${COMPONENTS[$comp]}"

        if build_component "$comp" "$version"; then
            built=$((built + 1))
            log_success "$comp build completed ($built/${#BUILD_ORDER[@]})"
        else
            failed=$((failed + 1))
            log_error "$comp build failed ($failed failed)"
            # Continue with next component
        fi
        echo ""
    done

    log_success "XFCE 4.20 build process completed!"
    log_info "Built: $built components"
    if [ $failed -gt 0 ]; then
        log_warn "Failed: $failed components"
    fi

    # Clean up
    log_info "Cleaning up build directory..."
    rm -rf "$BUILD_DIR"

    echo ""
    log_info "Verifying installation..."
    echo "Core XFCE 4.20 components:"
    echo "  - thunar: $(thunar --version 2>&1 | head -1 || echo 'NOT FOUND')"
    echo "  - xfwm4: $(xfwm4 --version 2>&1 | head -1 || echo 'NOT FOUND')"
    echo "  - xfce4-panel: $(xfce4-panel --version 2>&1 | head -1 || echo 'NOT FOUND')"
    echo "  - xfce4-appfinder: $(xfce4-appfinder --version 2>&1 | head -1 || echo 'NOT FOUND')"
}

main "$@"
