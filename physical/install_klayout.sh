#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Install the pinned upstream KLayout executable on an Ubuntu CI runner.
set -euo pipefail
. /etc/os-release
if [[ "$ID" != ubuntu ]]; then
  echo "This installer requires Ubuntu; install KLayout 0.30.13 for your platform." >&2
  exit 1
fi
case "$VERSION_ID" in
  22.04) platform=Ubuntu-22; checksum=da9eba81efee88a4c6da00b3bf3ae5d4 ;;
  24.04) platform=Ubuntu-24; checksum=ce86dbab94a1dd92bb293cfd86f8e97e ;;
  26.04) platform=Ubuntu-26; checksum=5bf50ce8daeaa376cc296d6c851c5469 ;;
  *) echo "No pinned KLayout package for Ubuntu $VERSION_ID" >&2; exit 1 ;;
esac
package=$(mktemp --suffix=.deb)
trap 'rm -f "$package"' EXIT
curl -fsSL --retry 3 \
  "https://www.klayout.org/downloads/$platform/klayout_0.30.13-1_amd64.deb" \
  -o "$package"
# Check the upstream download-page checksum before installing, and record
# a SHA-256 digest in the build log alongside the executable version.
printf '%s  %s\n' "$checksum" "$package" | md5sum -c -
sha256sum "$package"
chmod 644 "$package"
apt-get install -y -qq "$package"
test "$(klayout -v)" = "KLayout 0.30.13"
klayout -v
