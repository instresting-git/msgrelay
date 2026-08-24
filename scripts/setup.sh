#!/usr/bin/env bash
# =============================================================================
#  MsgRelay — WhatsApp → Automation Workflows
#  One-shot installer
#
#  What it does:
#    1. Downloads & installs the wacli binary (WhatsApp CLI, MIT license)
#    2. Bootstraps the ~/.wacli directory layout
#    3. Installs MsgRelay scripts (NLP engine, Calendar/Tasks sync, reports)
#    4. Creates config.yaml + wacli_secrets.json templates
#
#  Usage:
#    bash setup.sh
#
#  Optional env overrides:
#    WACLI_VERSION   e.g. 0.17.1  (default: latest release)
#    INSTALL_DIR     where the wacli binary goes (default: ~/bin)
#    WACLI_HOME      data dir (default: ~/.wacli)
# =============================================================================

set -euo pipefail

WACLI_VERSION="${WACLI_VERSION:-latest}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/bin}"
WACLI_HOME="${WACLI_HOME:-$HOME/.wacli}"
SCRIPTS_DIR="$WACLI_HOME/scripts"
REPO="openclaw/wacli"
BASE_URL="https://github.com/$REPO/releases/download"

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_CYAN='\033[0;36m'; C_RED='\033[0;31m'; C_RESET='\033[0m'
info()  { echo -e "${C_CYAN}==>${C_RESET} $*"; }
ok()    { echo -e "${C_GREEN}  ✓${C_RESET} $*"; }
warn()  { echo -e "${C_YELLOW}  ⚠${C_RESET} $*"; }
die()   { echo -e "${C_RED}  ✗ $*${C_RESET}" >&2; exit 1; }

# ── Detect platform ────────────────────────────────────────────────
detect_platform() {
    local os arch
    case "$(uname -s)" in
        Darwin) os="darwin" ;;
        Linux)  os="linux" ;;
        *) die "Unsupported OS: $(uname -s) (only macOS / Linux)" ;;
    esac
    case "$(uname -m)" in
        arm64|aarch64) arch="arm64" ;;
        x86_64|amd64)  arch="amd64" ;;
        *) die "Unsupported architecture: $(uname -m)" ;;
    esac
    echo "${os}_${arch}"
}

# ── Resolve latest version ─────────────────────────────────────────
resolve_version() {
    if [ "$WACLI_VERSION" != "latest" ]; then
        echo "$WACLI_VERSION"
        return
    fi
    python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen("https://api.github.com/repos/openclaw/wacli/releases/latest", timeout=15) as r:
    data = json.load(r)
print(data["tag_name"].lstrip("v"))
PY
}

# ── Main ────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "  ██████╗██╗  ██╗ █████╗ ████████╗███████╗██╗      ██████╗ ██╗    ██╗"
    echo " ██╔════╝██║  ██║██╔══██╗╚══██╔══╝██╔════╝██║     ██╔═══██╗██║    ██║"
    echo " ██║     ███████║███████║   ██║   █████╗  ██║     ██║   ██║██║ █╗ ██║"
    echo " ██║     ██╔══██║██╔══██║   ██║   ██╔══╝  ██║     ██║   ██║██║███╗██║"
    echo " ╚██████╗██║  ██║██║  ██║   ██║   ██║     ███████╗╚██████╔╝╚███╔███╔╝"
    echo "  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝"
    echo "          WhatsApp → Calendar · Tasks · Reports · Lark"
    echo ""

    info "Detecting platform..."
    PLATFORM=$(detect_platform)
    ok "platform: $PLATFORM"

    info "Resolving wacli version..."
    VERSION=$(resolve_version)
    ok "wacli v$VERSION"

    # 1. Install wacli binary
    if command -v "$INSTALL_DIR/wacli" >/dev/null 2>&1; then
        INSTALLED=$("$INSTALL_DIR/wacli" --version 2>/dev/null | awk '{print $2}')
        if [ "$INSTALLED" = "$VERSION" ]; then
            ok "wacli v$VERSION already installed at $INSTALL_DIR/wacli"
        else
            warn "wacli v$INSTALLED found (want v$VERSION) — will upgrade"
            install_wacli "$VERSION" "$PLATFORM"
        fi
    else
        install_wacli "$VERSION" "$PLATFORM"
    fi

    # 2. Ensure PATH
    if ! echo "$PATH" | tr ':' '\n' | grep -qx "$INSTALL_DIR"; then
        warn "$INSTALL_DIR is not on your PATH"
        SHELL_RC=""
        [ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"
        [ -f "$HOME/.bashrc" ] && SHELL_RC="$HOME/.bashrc"
        if [ -n "$SHELL_RC" ] && ! grep -q "export PATH=.*$INSTALL_DIR" "$SHELL_RC"; then
            echo "export PATH=\"\$PATH:$INSTALL_DIR\"" >> "$SHELL_RC"
            ok "added $INSTALL_DIR to PATH in $SHELL_RC"
        fi
    fi

    # 3. Bootstrap ~/.wacli layout
    mkdir -p "$WACLI_HOME/accounts" "$WACLI_HOME/logs" "$WACLI_HOME/reports" "$SCRIPTS_DIR"
    ok "created $WACLI_HOME/{accounts,logs,reports,scripts}"

    # 4. Copy MsgRelay scripts
    SCRIPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../src"
    if [ ! -d "$SCRIPT_SRC" ]; then
        # setup.sh may live in scripts/ next to src/
        SCRIPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/src"
    fi
    [ -d "$SCRIPT_SRC" ] || die "Cannot find src/ directory (looked at $SCRIPT_SRC)"
    cp "$SCRIPT_SRC"/wacli_*.py "$SCRIPTS_DIR/"
    cp "$SCRIPT_SRC"/msgrelay_*.py "$SCRIPTS_DIR/" 2>/dev/null || true
    cp -r "$SCRIPT_SRC/modules" "$SCRIPTS_DIR/" 2>/dev/null || true
    # LLM prompt workflows
    PROMPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/prompts"
    if [ -d "$PROMPT_SRC" ]; then
        mkdir -p "$SCRIPTS_DIR/prompts"
        cp "$PROMPT_SRC"/*.md "$SCRIPTS_DIR/prompts/" 2>/dev/null || true
        ok "installed LLM prompt workflows → $SCRIPTS_DIR/prompts"
    fi
    chmod +x "$SCRIPTS_DIR"/*.py 2>/dev/null || true
    ok "installed MsgRelay scripts → $SCRIPTS_DIR"

    # 5. Config template (do not overwrite existing)
    if [ ! -f "$WACLI_HOME/config.yaml" ]; then
        cat > "$WACLI_HOME/config.yaml" <<'YAML'
# wacli multi-account configuration
# See: https://wacli.sh/accounts.html
default_account: personal

accounts:
  personal:
    store: accounts/personal
  # work:
  #   store: accounts/work
YAML
        ok "created config.yaml template"
    else
        ok "config.yaml exists — kept as-is"
    fi

    # 6. Secrets template (chmod 600, never share)
    if [ ! -f "$SCRIPTS_DIR/wacli_secrets.json" ]; then
        cat > "$SCRIPTS_DIR/wacli_secrets.json" <<'JSON'
{
  "google_client_id": "",
  "google_client_secret": "",
  "smtp_user": "",
  "smtp_password": "",
  "report_to": "",
  "discord_webhook_url": "",
  "lark_user_id": "",
  "llm_api_key": "",
  "llm_base_url": "",
  "llm_model": ""
}
JSON
        chmod 600 "$SCRIPTS_DIR/wacli_secrets.json"
        ok "created wacli_secrets.json (chmod 600) — fill in your credentials"
    else
        warn "wacli_secrets.json exists — kept as-is"
    fi

    # 7. Python dependencies
    info "Installing Python dependencies..."
    python3 -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    python3 -m pip install --quiet pyyaml requests google-auth google-auth-oauthlib google-api-python-client || \
        warn "pip install failed — run manually: pip install -r requirements.txt"
    ok "Python dependencies ready"

    # ── Next steps ──
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────┐"
    echo "  │  🎉 MsgRelay installed! Next steps:                     │"
    echo "  │                                                         │"
    echo "  │  1. Pair WhatsApp:                                      │"
    echo "  │       wacli --account personal pair                     │"
    echo "  │       (scan the QR code with WhatsApp → Linked Devices) │"
    echo "  │                                                         │"
    echo "  │  2. Fill credentials:                                   │"
    echo "  │       $SCRIPTS_DIR/wacli_secrets.json                   │"
    echo "  │                                                         │"
    echo "  │  3. Google OAuth (one-time):                            │"
    echo "  │       python3 $SCRIPTS_DIR/wacli_calendar.py --auth     │"
    echo "  │                                                         │"
    echo "  │  4. Test the pipeline:                                  │"
    echo "  │       python3 $SCRIPTS_DIR/wacli_calendar.py --once     │"
    echo "  │                                                         │"
    echo "  │  Full guide: README.md                                  │"
    echo "  └─────────────────────────────────────────────────────────┘"
    echo ""
    warn "MsgRelay is a third-party tool. Using WhatsApp's Web protocol"
    warn "is subject to WhatsApp's Terms of Service — use at your own risk."
}

install_wacli() {
    local version="$1" platform="$2" tarball url
    tarball="wacli_${version}_${platform}.tar.gz"
    url="$BASE_URL/v${version}/$tarball"

    info "Downloading wacli v$version ($platform)..."
    curl -fL --retry 3 -o "/tmp/$tarball" "$url" || die "download failed: $url"

    mkdir -p "$INSTALL_DIR"
    tar -xzf "/tmp/$tarball" -C "$INSTALL_DIR" || die "extract failed"
    chmod +x "$INSTALL_DIR/wacli"
    rm -f "/tmp/$tarball"
    ok "installed wacli → $INSTALL_DIR/wacli"
}

main "$@"
