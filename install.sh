#!/usr/bin/env bash
# Steerable installer:
#
#   curl -fsSL https://raw.githubusercontent.com/archit3ckt/steerable/master/install.sh | bash
#
# Clones (or updates) the kit into ~/.steerable and puts the `steerable` command in
# ~/.local/bin. Override with STEERABLE_HOME and STEERABLE_REPO.
set -euo pipefail

REPO="${STEERABLE_REPO:-https://github.com/archit3ckt/steerable.git}"
HOME_DIR="${STEERABLE_HOME:-$HOME/.steerable}"
BIN_DIR="$HOME/.local/bin"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C='\033[36m'; G='\033[32m'; Y='\033[33m'; R='\033[31m'; B='\033[1m'; D='\033[2m'; N='\033[0m'
else
  C=''; G=''; Y=''; R=''; B=''; D=''; N=''
fi
step() { echo -e "${C}→${N} $1"; }
ok()   { echo -e "${G}✓${N} $1"; }
fail() { echo -e "${R}✗${N} $1" >&2; [ -n "${2:-}" ] && echo -e "  ${D}$2${N}" >&2; exit 1; }

echo -e "${B}${C}◆ Steerable${N}${D}  installer${N}"
echo

case "$(uname -s)" in
  Linux|Darwin) ;;
  *) fail "Unsupported system: $(uname -s)" "Steerable runs on Linux and macOS (Windows: use WSL2)." ;;
esac

command -v git >/dev/null || fail "git is missing" "Install it with your package manager, then rerun this installer."
command -v python3 >/dev/null || fail "python3 is missing" "Install Python 3.10+, then rerun this installer."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || fail "Python $(python3 -V 2>&1 | cut -d' ' -f2) is too old" "Steerable needs Python 3.10 or newer."
python3 -c 'import venv, ensurepip' 2>/dev/null \
  || fail "Python can't create virtual environments" "On Debian/Ubuntu: sudo apt install python3-venv"
ok "git and Python $(python3 -V 2>&1 | cut -d' ' -f2)"

if [ -d "$HOME_DIR/.git" ]; then
  step "Updating $HOME_DIR"
  git -C "$HOME_DIR" pull -q --ff-only || fail "Couldn't update $HOME_DIR" "Local changes there? Check: git -C $HOME_DIR status"
else
  step "Downloading Steerable into $HOME_DIR"
  git clone -q --depth 1 "$REPO" "$HOME_DIR" || fail "Couldn't download from $REPO"
fi
ok "Steerable $(git -C "$HOME_DIR" describe --always)"

mkdir -p "$BIN_DIR"
ln -sf "$HOME_DIR/bin/steerable" "$BIN_DIR/steerable"
chmod +x "$HOME_DIR/bin/steerable" "$HOME_DIR/setup.sh"
ok "Command installed: $BIN_DIR/steerable"

if command -v claude >/dev/null; then
  ok "Claude Code found"
else
  echo -e "${Y}!${N} Claude Code isn't installed yet. Your business manager runs on it: ${B}https://claude.com/claude-code${N}"
fi

echo
case ":$PATH:" in
  *":$BIN_DIR:"*) echo -e "Next: ${B}steerable setup${N}" ;;
  *) echo -e "${Y}!${N} $BIN_DIR isn't on your PATH. Add this to your shell profile (~/.bashrc or ~/.zshrc):"
     echo -e "    ${B}export PATH=\"\$HOME/.local/bin:\$PATH\"${N}"
     echo -e "Then: ${B}steerable setup${N}" ;;
esac
