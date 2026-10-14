#!/usr/bin/env bash
# Install restic and rclone into ~/.local/bin (no sudo), verifying official checksums.
# Skips any tool that's already there.
set -euo pipefail
BIN="$HOME/.local/bin"; mkdir -p "$BIN"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
case "$(uname -m)" in x86_64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) echo "Unsupported CPU" >&2; exit 1 ;; esac
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"

if [ ! -x "$BIN/restic" ]; then
  V=$(curl -sf https://api.github.com/repos/restic/restic/releases/latest | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))")
  F="restic_${V}_${OS}_${ARCH}.bz2"
  curl -sfL -o "$F" "https://github.com/restic/restic/releases/download/v$V/$F"
  curl -sfL -o SHA256SUMS "https://github.com/restic/restic/releases/download/v$V/SHA256SUMS"
  grep " $F\$" SHA256SUMS | sha256sum -c - >/dev/null
  bunzip2 -c "$F" > restic && install -m 755 restic "$BIN/restic"
  echo "✓ restic $V installed (checksum verified)"
fi

if [ ! -x "$BIN/rclone" ]; then
  V=$(curl -sf https://downloads.rclone.org/version.txt | awk '{print $2}')
  F="rclone-$V-$OS-$ARCH.zip"
  curl -sfL -o "$F" "https://downloads.rclone.org/$V/$F"
  curl -sfL -o SHA256SUMS "https://downloads.rclone.org/$V/SHA256SUMS"
  grep " $F\$" SHA256SUMS | sha256sum -c - >/dev/null
  unzip -oq "$F" && install -m 755 "rclone-$V-$OS-$ARCH/rclone" "$BIN/rclone"
  echo "✓ rclone $V installed (checksum verified)"
fi
