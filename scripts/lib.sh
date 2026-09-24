# Shared helpers for install scripts. Source, don't execute.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/tools"
CACHE="$TOOLS/cache"
# shellcheck source=versions.env
. "$ROOT/scripts/versions.env"

log() { printf '[%s] %s\n' "$(basename "$0")" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# download URL DEST SHA256 -- fetch to a cache path and verify. Reuses a cached file
# only if its checksum matches, so a partial or tampered download is never trusted.
download() {
  local url="$1" dest="$2" want="$3" got
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ]; then
    got="$(sha256_of "$dest")"
    if [ "$got" = "$want" ]; then log "cached: $dest"; return 0; fi
    log "checksum mismatch on cached file, re-downloading"; rm -f "$dest"
  fi
  log "downloading $url"
  curl --fail --location --progress-bar --output "$dest.part" "$url"
  got="$(sha256_of "$dest.part")"
  [ "$got" = "$want" ] || { rm -f "$dest.part"; die "checksum mismatch for $url: expected $want got $got"; }
  mv "$dest.part" "$dest"
}

host_triple() {
  local os arch
  case "$(uname -s)" in Darwin) os=apple-darwin ;; Linux) os=unknown-linux-gnu ;; *) die "unsupported OS $(uname -s)" ;; esac
  case "$(uname -m)" in arm64|aarch64) arch=aarch64 ;; x86_64|amd64) arch=x86_64 ;; *) die "unsupported arch $(uname -m)" ;; esac
  echo "$arch-$os"
}
