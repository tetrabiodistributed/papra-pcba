#!/usr/bin/env bash
# Install a pinned KiCad into tools/KiCad (macOS). Linux hosts use the container
# image named in versions.env instead; see the Makefile.
. "$(dirname "$0")/lib.sh"

[ "$(uname -s)" = Darwin ] || die "install-kicad.sh only handles macOS; on Linux run kicad-cli from $KICAD_IMAGE"

dest="$TOOLS/KiCad"
stamp="$dest/.version"
if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$KICAD_VERSION" ]; then
  log "KiCad $KICAD_VERSION already installed at $dest"; exit 0
fi

dmg="$CACHE/kicad-unified-universal-$KICAD_VERSION.dmg"
download "$KICAD_DMG_URL" "$dmg" "$KICAD_DMG_SHA256"

mnt="$(mktemp -d /tmp/kicad-dmg.XXXXXX)"
trap 'hdiutil detach "$mnt" -quiet 2>/dev/null || true; rmdir "$mnt" 2>/dev/null || true' EXIT
log "mounting $dmg"
hdiutil attach -nobrowse -readonly -quiet -mountpoint "$mnt" "$dmg"
[ -d "$mnt/KiCad/KiCad.app" ] || die "unexpected DMG layout: $(ls "$mnt")"

rm -rf "$dest.new"
log "copying KiCad.app (this is large, be patient)"
ditto "$mnt/KiCad" "$dest.new"
rm -rf "$dest"
mv "$dest.new" "$dest"
echo "$KICAD_VERSION" > "$stamp"
"$dest/KiCad.app/Contents/MacOS/kicad-cli" version
