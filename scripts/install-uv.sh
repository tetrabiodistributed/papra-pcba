#!/usr/bin/env bash
# Install a pinned uv into tools/bin. Never touches the system or PATH.
. "$(dirname "$0")/lib.sh"

triple="$(host_triple)"
var="UV_SHA256_${triple//-/_}"
sha="${!var:-}"
[ -n "$sha" ] || die "no checksum recorded for $triple in scripts/versions.env"

tarball="$CACHE/uv-$UV_VERSION-$triple.tar.gz"
download "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$triple.tar.gz" "$tarball" "$sha"

mkdir -p "$TOOLS/bin"
tar -xzf "$tarball" -C "$TOOLS/bin" --strip-components=1
"$TOOLS/bin/uv" --version
