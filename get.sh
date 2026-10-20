#!/usr/bin/env sh
# Steerable with Docker, in one line:
#
#   curl -fsSL https://raw.githubusercontent.com/archit3ckt/steerable/master/get.sh | sh
#
# Puts docker-compose.yml and your settings (.env) in ~/steerable-docker, asks a few questions
# the first time, and starts your COO and your dashboard. Run it again to update (or
# `docker compose pull && docker compose up -d` in that folder).
#
# Without questions (CI, scripts): STEERABLE_YES=1 COMPANY_NAME=... DASHBOARD_PASSWORD=... sh get.sh
# From a checkout, building the images here instead of pulling them: sh get.sh --build
# Starting from a company you already have (an export from your dashboard or Steerable Cloud):
#   sh get.sh --import company.tar.gz
# More businesses or projects (spaces, each with its own COO): New space, in the dashboard.
set -eu

REPO_RAW="${STEERABLE_RAW:-https://raw.githubusercontent.com/archit3ckt/steerable/master}"
DIR="${STEERABLE_DIR:-$HOME/steerable-docker}"
BUILD=""
IMPORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="--build" ;;
    --import) IMPORT="${2:-}"; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ -n "$IMPORT" ]; then
  [ -f "$IMPORT" ] || { echo "No such file: $IMPORT" >&2; exit 2; }
  IMPORT=$(cd "$(dirname "$IMPORT")" && pwd)/$(basename "$IMPORT")
fi

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C='\033[36m'; G='\033[32m'; Y='\033[33m'; R='\033[31m'; B='\033[1m'; D='\033[2m'; N='\033[0m'
else
  C=''; G=''; Y=''; R=''; B=''; D=''; N=''
fi
step() { printf "${C}→${N} %s\n" "$1"; }
ok()   { printf "${G}✓${N} %s\n" "$1"; }
fail() { printf "${R}✗${N} %s\n" "$1" >&2; [ -n "${2:-}" ] && printf "  ${D}%s${N}\n" "$2" >&2; exit 1; }

printf "${B}${C}◆ Steerable${N}${D}  with Docker${N}\n"
printf "${D}Your business manager acts in your name, and what it does is your responsibility: see \"Your responsibility\" in the README.${N}\n\n"

command -v docker >/dev/null || fail "Docker is missing" "Install Docker Desktop (Mac, Windows) or Docker Engine (Linux): https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is missing" "It comes with Docker Desktop; on Linux install the docker-compose-plugin package."
docker info >/dev/null 2>&1 || fail "Docker isn't running" "Start Docker, then run this again."
ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"

# Questions read from the terminal even when this script comes through a pipe.
ask() { # ask VAR "Question" [default]
  eval "current=\${$1:-}"
  [ -n "$current" ] && return
  if [ -n "${STEERABLE_YES:-}" ] || ! [ -r /dev/tty ]; then eval "$1=\${3:-}"; return; fi
  printf "%s${3:+ ${D}[$3]${N}}: " "$2" > /dev/tty
  read -r answer < /dev/tty || answer=""
  eval "$1=\${answer:-\${3:-}}"
}
locale_tag() { # this machine's language as a browser sends it: en_GB.UTF-8 -> en-GB
  l=$(printf %s "${LC_ALL:-${LANG:-}}" | sed 's/[.@].*//; s/_/-/')
  case "$l" in ""|C|POSIX) echo en-US;; *) echo "$l";; esac
}
ask_secret() {
  eval "current=\${$1:-}"
  [ -n "$current" ] && return
  if [ -n "${STEERABLE_YES:-}" ] || ! [ -r /dev/tty ]; then return; fi
  printf "%s: " "$2" > /dev/tty
  stty -echo < /dev/tty 2>/dev/null || true
  read -r answer < /dev/tty || answer=""
  stty echo < /dev/tty 2>/dev/null || true
  printf "\n" > /dev/tty
  eval "$1=\$answer"
}

# The compose file: from this checkout when building, otherwise the published one.
here=$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)
if [ -n "$BUILD" ]; then
  [ -f "$here/docker-compose.yml" ] || fail "--build needs to run from a Steerable checkout" "git clone https://github.com/archit3ckt/steerable && sh steerable/get.sh --build"
  DIR="$here"; cd "$DIR"
  # The engine updates a company's files when this changes, so a new checkout means a new version.
  ENGINE_VERSION=$(git rev-parse --short HEAD 2>/dev/null || date +%s); export ENGINE_VERSION
else
  mkdir -p "$DIR"
  cd "$DIR"
  step "Downloading docker-compose.yml"
  curl -fsSL "$REPO_RAW/docker-compose.yml" -o docker-compose.yml.new || fail "Couldn't download it from $REPO_RAW"
  mv docker-compose.yml.new docker-compose.yml
fi

if [ -f .env ]; then
  ok "Using your settings in $DIR/.env"
else
  printf "\n${B}A few questions${N} ${D}(change them later in $DIR/.env)${N}\n"
  ask COMPANY_NAME "Your business's name" ""
  [ -n "$COMPANY_NAME" ] || fail "Your business needs a name" "Run this again, or set COMPANY_NAME."
  ask OWNER_NAME "Your first name" ""
  ask COO_NAME "What should your business manager be called" "Juno"
  ask_secret DASHBOARD_PASSWORD "A passphrase for your dashboard (8+ characters)"
  [ "${#DASHBOARD_PASSWORD}" -ge 8 ] 2>/dev/null || fail "The passphrase needs 8 or more characters" "Run this again, or set DASHBOARD_PASSWORD."
  ask_secret ANTHROPIC_API_KEY "Anthropic API key (Enter to sign in with your Claude account instead)"
  for v in "$COMPANY_NAME" "$OWNER_NAME" "${COO_NAME:-}" "$DASHBOARD_PASSWORD"; do
    case "$v" in *"'"*) fail "Please avoid the ' character in names and the passphrase" "Run this again.";; esac
  done
  ask TZ "Your time zone" "$(cat /etc/timezone 2>/dev/null || readlink /etc/localtime 2>/dev/null | sed 's|.*zoneinfo/||' || echo UTC)"
  umask 077
  # Single quotes: Docker reads the value as is (spaces, & and $ included).
  cat > .env <<EOF
COMPANY_NAME='$COMPANY_NAME'
OWNER_NAME='$OWNER_NAME'
COO_NAME='${COO_NAME:-Juno}'
DASHBOARD_PASSWORD='$DASHBOARD_PASSWORD'
ANTHROPIC_API_KEY='${ANTHROPIC_API_KEY:-}'
MONTHLY_BUDGET_USD=${MONTHLY_BUDGET_USD:-20}
TZ=${TZ:-UTC}
BROWSER_LOCALE=$(locale_tag)
DASHBOARD_BIND=${DASHBOARD_BIND:-127.0.0.1}
DASHBOARD_PORT=${DASHBOARD_PORT:-3100}
TELEGRAM_BOT_TOKEN=
SMTP_HOST=
SMTP_USER=
SMTP_PASS=
ALERT_TO=
EOF
  ok "Saved your settings in $DIR/.env (only you can read it)"
fi

# The dashboard's key to the spaces service (New space): made once, kept in .env.
if ! grep -q "^SPACES_TOKEN=." .env 2>/dev/null; then
  grep -v '^SPACES_TOKEN=' .env > .env.new 2>/dev/null || true
  echo "SPACES_TOKEN=$(od -An -tx1 -N24 /dev/urandom | tr -d ' \n')" >> .env.new
  cat .env.new > .env && rm -f .env.new
fi

if [ -n "$BUILD" ]; then
  step "Building and starting (the first build takes a few minutes)"
else
  step "Downloading and starting"
  docker compose pull -q || fail "Couldn't download the images" "Check your connection, then run this again."
fi
ENGINE=engine; SHARED=/shared
if [ -n "$IMPORT" ]; then
  # Hand the archive to the engine before its first start; it brings the files in then.
  docker compose up --no-start $BUILD >/dev/null || fail "Couldn't create the containers"
  if docker compose run --rm --no-deps --entrypoint test "$ENGINE" -d /company/.git 2>/dev/null; then
    printf "${Y}!${N} This install already has a company, so %s wasn't brought in.\n" "$IMPORT"
    printf "  ${D}To replace it (this deletes the current one): docker compose down -v, then run this again.${N}\n"
  else
    docker compose cp "$IMPORT" "$ENGINE:$SHARED/import.tar.gz" || fail "Couldn't hand over $IMPORT"
    ok "Your company's files will come in on the first start"
  fi
fi
docker compose up -d $BUILD --wait 2>/dev/null || docker compose up -d $BUILD || fail "Couldn't start" "See what happened: docker compose -f $DIR/docker-compose.yml logs"

port=$(sed -n 's/^DASHBOARD_PORT=//p' .env 2>/dev/null); port=${port:-3100}
echo
ok "Steerable is running"
printf "\n  Open ${B}http://localhost:%s${N} and sign in with your passphrase.\n" "$port"
if ! grep -q "^ANTHROPIC_API_KEY='\?[^' ]" .env; then
  printf "  ${Y}!${N} No API key: sign your business manager in to Claude once:\n"
  printf "    ${B}cd %s && docker compose exec -it %s claude${N}   then type /login\n" "$DIR" "$ENGINE"
fi
printf "\n  ${D}Update:  cd %s && docker compose pull && docker compose up -d${N}\n" "$DIR"
printf "  ${D}Logs:    docker compose -f %s/docker-compose.yml logs -f engine${N}\n" "$DIR"
