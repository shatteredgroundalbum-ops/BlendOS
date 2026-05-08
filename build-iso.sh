#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# BledOS ISO Build Script
# ═══════════════════════════════════════════════════════════════
# This script builds a bootable BledOS ISO image using Archiso.
#
# Prerequisites:
#   - Arch Linux host system
#   - archiso package installed (pacman -S archiso)
#   - At least 25 GB free disk space
#   - Internet connection for downloading packages
#
# Usage:
#   chmod +x build-iso.sh
#   sudo ./build-iso.sh
#
# Output:
#   ./bledos-iso-output/BledOS-0.1.0-x86_64.iso
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ─── Configuration ─────────────────────────────────────────────

BLEDOs_VERSION="0.1.0"
BLEDOs_CODENAME="Genesis"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE_DIR="${SCRIPT_DIR}/bledos-archiso"
WORK_DIR="${SCRIPT_DIR}/work"
OUTPUT_DIR="${SCRIPT_DIR}/bledos-iso-output"
ISO_NAME="BledOS-${BLEDOs_VERSION}-x86_64.iso"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ─── Functions ─────────────────────────────────────────────────

log_info()  { echo -e "${CYAN}[BledOS]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[BledOS]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[BledOS]${NC} $1"; }
log_error() { echo -e "${RED}[BledOS]${NC} $1"; }

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if running on Arch Linux
    if [[ ! -f /etc/arch-release ]]; then
        log_error "This script must be run on Arch Linux"
        exit 1
    fi

    # Check if archiso is installed
    if ! pacman -Q archiso &>/dev/null; then
        log_error "archiso is not installed. Run: pacman -S archiso"
        exit 1
    fi

    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi

    # Check disk space (at least 25 GB)
    available_gb=$(df -BG "$SCRIPT_DIR" | awk 'NR==2 {print $4}' | tr -d 'G')
    if [[ $available_gb -lt 25 ]]; then
        log_warn "Low disk space: ${available_gb}GB available (25GB recommended)"
    fi

    log_ok "Prerequisites satisfied"
}

setup_profile() {
    log_info "Setting up Archiso profile..."

    # Create profile directory from releng template
    if [[ -d "$PROFILE_DIR" ]]; then
        log_warn "Profile directory exists, cleaning..."
        rm -rf "$PROFILE_DIR"
    fi

    cp -r /usr/share/archiso/configs/releng/ "$PROFILE_DIR"

    # Copy our custom package list
    cp "${SCRIPT_DIR}/bledos-archiso/packages.x86_64" "${PROFILE_DIR}/packages.x86_64"

    # Create custom overlay directory structure
    mkdir -p "${PROFILE_DIR}/airootfs/etc/bledos"
    mkdir -p "${PROFILE_DIR}/airootfs/run/bledos"
    mkdir -p "${PROFILE_DIR}/airootfs/usr/share/blender/BledOS"
    mkdir -p "${PROFILE_DIR}/airootfs/usr/share/blender/BledOS/scripts/addons"
    mkdir -p "${PROFILE_DIR}/airootfs/usr/lib/systemd/system"
    mkdir -p "${PROFILE_DIR}/airootfs/etc/systemd/system/graphical.target.wants"

    log_ok "Profile directory created"
}

install_bledos_components() {
    log_info "Installing BledOS components into overlay..."

    # ─── Compositor ────────────────────────────────────────
    # (In production, this would be a pre-built package from our repo)
    # For now, we build from source
    log_info "Building BledOS compositor..."
    COMPOSITOR_DIR="${SCRIPT_DIR}/bledos-compositor"
    if [[ -d "$COMPOSITOR_DIR" ]]; then
        cd "$COMPOSITOR_DIR"
        meson setup build --prefix=/usr 2>/dev/null || true
        ninja -C build
        # Copy the binary to the overlay
        cp build/bledos-compositor "${PROFILE_DIR}/airootfs/usr/bin/"
        log_ok "Compositor binary installed"
    else
        log_warn "Compositor source not found, skipping"
    fi

    # ─── Shell Add-ons ────────────────────────────────────
    log_info "Installing BledOS shell add-ons..."
    ADDONS_DIR="${SCRIPT_DIR}/bledos-shell-addons"
    if [[ -d "$ADDONS_DIR" ]]; then
        cp -r "$ADDONS_DIR"/* "${PROFILE_DIR}/airootfs/usr/share/blender/BledOS/scripts/addons/"
        log_ok "Shell add-ons installed"
    else
        log_warn "Shell add-ons directory not found, skipping"
    fi

    # ─── Application Template ─────────────────────────────
    log_info "Installing BledOS application template..."
    TEMPLATE_DIR="${SCRIPT_DIR}/bledos-default-template"
    if [[ -d "$TEMPLATE_DIR" ]]; then
        cp -r "$TEMPLATE_DIR"/* "${PROFILE_DIR}/airootfs/usr/share/blender/BledOS/"
        log_ok "Application template installed"
    else
        log_warn "Application template directory not found, skipping"
    fi

    # ─── Systemd Services ─────────────────────────────────
    log_info "Installing systemd services..."
    SERVICES_DIR="${SCRIPT_DIR}/bledos-services"
    if [[ -d "$SERVICES_DIR" ]]; then
        cp "${SERVICES_DIR}"/*.service "${PROFILE_DIR}/airootfs/usr/lib/systemd/system/"

        # Enable services
        ln -sf /usr/lib/systemd/system/bledos-compositor.service \
            "${PROFILE_DIR}/airootfs/etc/systemd/system/graphical.target.wants/"
        ln -sf /usr/lib/systemd/system/bledos-shell.service \
            "${PROFILE_DIR}/airootfs/etc/systemd/system/graphical.target.wants/"

        log_ok "Systemd services installed and enabled"
    else
        log_warn "Services directory not found, skipping"
    fi

    cd "$SCRIPT_DIR"
}

customize_airootfs() {
    log_info "Customizing airootfs..."

    # ─── Create BledOS default user ────────────────────────
    cat >> "${PROFILE_DIR}/airootfs/root/customize_airootfs.sh" << 'BLEDOs_CUSTOMIZE'

# BledOS Customization
echo "[BledOS] Running customizations..."

# Create default user 'bledos' with password 'bledos'
useradd -m -G wheel,video,audio,input,storage,network -s /bin/bash bledos
echo "bledos:bledos" | chpasswd
echo "%wheel ALL=(ALL) ALL" >> /etc/sudoers.d/wheel

# Set hostname
echo "bledos" > /etc/hostname

# Set locale
echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf

# Set timezone
ln -sf /usr/share/zoneinfo/UTC /etc/localtime

# Enable NetworkManager
systemctl enable NetworkManager

# Enable PipeWire for the bledos user
systemctl --user -u bledos enable pipewire pipewire-pulse wireplumber

# Create BledOS runtime directory
mkdir -p /run/bledos
chown root:wheel /run/bledos
chmod 775 /run/bledos

# Configure Blender to use BledOS template by default
mkdir -p /home/bledos/.config/blender
BLENDER_VER=$(blender --version | head -1 | grep -oP '\d+\.\d+' | head -1)
mkdir -p /home/bledos/.config/blender/${BLENDER_VER}/config
echo "BLEDOs" > /home/bledos/.config/blender/${BLENDER_VER}/config/app_template

# Set default session to BledOS
mkdir -p /home/bledos/.config/environment.d
cat > /home/bledos/.config/environment.d/bledos.conf << 'EOF'
WAYLAND_DISPLAY=bledos-0
XDG_SESSION_TYPE=wayland
XDG_CURRENT_DESKTOP=BledOS
EOF

# Fix ownership
chown -R bledos:bledos /home/bledos

echo "[BledOS] Customization complete!"
BLEDOs_CUSTOMIZE

    chmod +x "${PROFILE_DIR}/airootfs/root/customize_airootfs.sh"
    log_ok "Customization script configured"
}

build_iso() {
    log_info "Building ISO image..."
    log_info "This may take 20-60 minutes depending on your internet speed and CPU."

    # Clean previous builds
    rm -rf "$WORK_DIR" "$OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"

    # Build the ISO using mkarchiso
    cd "$PROFILE_DIR"
    mkarchiso -v -w "$WORK_DIR" -o "$OUTPUT_DIR" .

    if [[ $? -eq 0 ]]; then
        log_ok "ISO built successfully!"
        log_ok "Output: ${OUTPUT_DIR}/${ISO_NAME}"

        # Show ISO size
        iso_size=$(du -h "${OUTPUT_DIR}/${ISO_NAME}" | cut -f1)
        log_ok "ISO size: ${iso_size}"

        # Generate checksums
        cd "$OUTPUT_DIR"
        sha256sum "$ISO_NAME" > "${ISO_NAME}.sha256sum"
        log_ok "SHA256 checksum generated"
    else
        log_error "ISO build failed!"
        exit 1
    fi
}

# ─── Main ──────────────────────────────────────────────────────

main() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════╗"
    echo "║           BledOS ISO Builder v${BLEDOs_VERSION}                  ║"
    echo "║     Blender as Operating System - '${BLEDOs_CODENAME}'          ║"
    echo "╚═══════════════════════════════════════════════════════╝"
    echo ""

    check_prerequisites
    setup_profile
    install_bledos_components
    customize_airootfs
    build_iso

    echo ""
    log_ok "Build complete! Flash the ISO to a USB drive with:"
    log_ok "  dd if=${OUTPUT_DIR}/${ISO_NAME} of=/dev/sdX bs=4M status=progress"
    echo ""
    log_ok "Or test in QEMU:"
    log_ok "  qemu-system-x86_64 -m 4G -smp 4 -cdrom ${OUTPUT_DIR}/${ISO_NAME}"
    echo ""
}

main "$@"