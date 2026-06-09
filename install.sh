#!/bin/bash

set -e

APP_NAME="bookstack-wordpress-migration"
INSTALL_DIR="$HOME/.local/bin/$APP_NAME"
DESKTOP_FILE="$HOME/.local/share/applications/$APP_NAME.desktop"
CONFIG_DIR="$HOME/.wordpress-migration"
CONFIG_FILE="$CONFIG_DIR/config.json"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "========================================"
echo "  $APP_NAME Installer"
echo "========================================"

check_python() {
    log_info "Checking for Python..."

    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        log_info "Python found: $PYTHON_VERSION"

        if [[ $(echo "$PYTHON_VERSION" | cut -d. -f1) -lt 3 ]] || [[ $(echo "$PYTHON_VERSION" | cut -d. -f1) -eq 3 && $(echo "$PYTHON_VERSION" | cut -d. -f2) -lt 10 ]]; then
            log_error "Python 3.10+ required. Found: $PYTHON_VERSION"
            log_info "Please install Python 3.10 or higher"
            exit 1
        fi
        return 0
    else
        log_warn "Python not found!"
        read -p "Install Python 3? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Installing Python 3..."
            if command -v apt-get &> /dev/null; then
                sudo apt-get update && sudo apt-get install -y python3 python3-pip
            elif command -v pacman &> /dev/null; then
                sudo pacman -S python python-pip
            elif command -v dnf &> /dev/null; then
                sudo dnf install -y python3 python3-pip
            elif command -v zypper &> /dev/null; then
                sudo zypper install -y python3 python3-pip
            else
                log_error "Could not detect package manager. Please install Python 3.10+ manually."
                exit 1
            fi
            log_info "Python installed successfully"
        else
            log_error "Python is required to run this application."
            exit 1
        fi
    fi
}

install_modules() {
    log_info "Checking required Python modules..."

    MISSING_MODULES=()

    for module in requests openai pillow pydantic pyqt6 pyqt6-qt6; do
        if ! python3 -c "import $module" 2>/dev/null; then
            MISSING_MODULES+=("$module")
        fi
    done

    if [ ${#MISSING_MODULES[@]} -eq 0 ]; then
        log_info "All required modules already installed"
        return 0
    fi

    log_info "Missing modules: ${MISSING_MODULES[*]}"
    log_info "Installing missing modules..."

    PIP_PACKAGES="requests openai pillow pydantic pyqt6 pyqt6-qt6"

    if ! pip3 install $PIP_PACKAGES 2>&1; then
        log_warn "Standard installation failed."
        log_warn "This may require --break-system-packages flag on some systems."

        read -p "Try installing with --break-system-packages? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Installing with --break-system-packages..."
            pip3 install --break-system-packages $PIP_PACKAGES
            log_info "Modules installed successfully"
        else
            log_error "Installation aborted. Please install manually:"
            echo "  pip3 install $PIP_PACKAGES"
            exit 1
        fi
    else
        log_info "Modules installed successfully"
    fi
}

install_app() {
    log_info "Installing application to $INSTALL_DIR..."

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$HOME/.local/share/applications"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    cp "$SCRIPT_DIR/cli.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/gui.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/config.py" "$INSTALL_DIR/"

    chmod +x "$INSTALL_DIR/gui.py"
    chmod +x "$INSTALL_DIR/cli.py"

    log_info "Application files copied"

    create_desktop_shortcut
    create_config
}

create_desktop_shortcut() {
    log_info "Creating desktop shortcut..."

    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=WordPress Migration
Comment=Migrate BookStack pages to WordPress
Exec=$INSTALL_DIR/gui.py
Icon=utilities-terminal
Type=Application
Categories=Development;
Terminal=false
EOF

    chmod +x "$DESKTOP_FILE"

    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true
    fi

    log_info "Desktop shortcut created at $DESKTOP_FILE"
}

create_config() {
    log_info "Creating default configuration..."

    mkdir -p "$CONFIG_DIR"

    if [ ! -f "$CONFIG_FILE" ]; then
        cat > "$CONFIG_FILE" << EOF
{
  "bookstack": {
    "url": "https://wiki.yourdomain.com",
    "token_id": "",
    "token_secret": ""
  },
  "wordpress": {
    "url": "https://yourblog.com",
    "username": "",
    "app_password": ""
  },
  "api": {
    "endpoint": "https://api.bluesminds.com/v1",
    "key": ""
  },
  "models": {
    "text": "openai/gpt-oss-120b",
    "image": "grok-imagine-image-lite"
  }
}
EOF
        log_info "Config file created at $CONFIG_FILE"
        log_warn "Please edit the config file and add your credentials:"
        log_warn "  nano $CONFIG_FILE"
    else
        log_info "Config file already exists"
    fi
}

cleanup() {
    log_info "Cleaning up installation files..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    rm -f "$SCRIPT_DIR/install.sh"
}

final_message() {
    echo ""
    echo "========================================"
    echo -e "${GREEN}Installation Complete!${NC}"
    echo "========================================"
    echo ""
    echo "To run the GUI:"
    echo "  $INSTALL_DIR/gui.py"
    echo ""
    echo "To run CLI:"
    echo "  $INSTALL_DIR/cli.py \"https://wiki.example.com/page/slug\""
    echo ""
    echo "Desktop shortcut available in your app menu"
    echo ""
    echo "IMPORTANT: Edit your config file before running:"
    echo "  nano $CONFIG_FILE"
    echo ""
}

main() {
    check_python
    install_modules
    install_app
    final_message
}

main "$@"