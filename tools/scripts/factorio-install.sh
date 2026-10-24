#!/bin/bash
## ---------------------------------------------------------------------------
## TeamCryptid eggs: Factorio headless server install.
## Replaces the upstream install script (pelican-eggs/games-standalone, MIT).
##
## Changes from upstream:
##   - any failure exits 1 (upstream reported "Installation completed" for an
##     unknown version)
##   - verifies the download against factorio.com's published SHA-256 sums
##   - staged on the server's disk, not the 100 MB /tmp; game files are replaced
##     only after the download is verified
##   - map-settings.json is kept on reinstall (upstream checked the wrong path and
##     reset it every time); server-settings.json and map-gen-settings.json too
##   - the save is created by the startup command on first start, after the Space
##     Age setting is applied (upstream created it here with Space Age always on)
## Server Files: /mnt/server
## ---------------------------------------------------------------------------

fatal() {
    echo "-----------------------------------------"
    echo "Installation failed: $*"
    echo "-----------------------------------------"
    exit 1
}

WORK=/mnt/server/.factorio-install
trap 'rm -rf "${WORK}"' EXIT

if ! command -v xz >/dev/null; then
    echo "Installing xz-utils"
    { apt-get update -qq && apt-get install -y -qq xz-utils; } >/dev/null 2>&1 || fatal "could not install xz-utils"
fi

LATEST=$(curl -sfSL https://factorio.com/api/latest-releases) || fatal "could not reach factorio.com"
case "${FACTORIO_VERSION}" in
    ""|latest)    VERSION=$(jq -r '.stable.headless // empty' <<< "${LATEST}") ;;
    experimental) VERSION=$(jq -r '.experimental.headless // empty' <<< "${LATEST}") ;;
    *)            VERSION="${FACTORIO_VERSION}" ;;
esac
echo "${VERSION}" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || fatal "'${FACTORIO_VERSION}' is not a version (use latest, experimental, or e.g. 2.0.72)"

cd /mnt/server || fatal "cannot enter /mnt/server"
rm -rf "${WORK}" && mkdir -p "${WORK}/new" || fatal "cannot create ${WORK}"

URL="https://www.factorio.com/get-download/${VERSION}/headless/linux64"
echo "Factorio: ${VERSION}"
FINAL=$(curl -sfSL -o "${WORK}/factorio.tar.xz" -w '%{url_effective}' "${URL}") || fatal "download failed. Check that Factorio ${VERSION} exists."
FILE=$(basename "${FINAL%%\?*}")
EXPECTED=$(curl -sfSL https://www.factorio.com/download/sha256sums/ | awk -v f="${FILE}" '$2 == f {print $1}')
if [ -n "${EXPECTED}" ]; then
    ACTUAL=$(sha256sum "${WORK}/factorio.tar.xz" | cut -d' ' -f1)
    [ "${ACTUAL}" = "${EXPECTED}" ] || fatal "checksum mismatch for ${FILE} (expected ${EXPECTED}, got ${ACTUAL})"
    echo "SHA-256 verified: ${FILE}"
else
    echo "WARNING: factorio.com lists no checksum for ${FILE}; not verified"
fi

tar -xJf "${WORK}/factorio.tar.xz" --strip-components=1 -C "${WORK}/new" || fatal "could not unpack the server archive"
rm -f "${WORK}/factorio.tar.xz"
[ -x "${WORK}/new/bin/x64/factorio" ] || fatal "the archive does not contain bin/x64/factorio"

# Game-owned files: bin/ and each folder in data/ (base, core, space-age...) are
# replaced; the rest of data/ is merged, so the customer's settings files stay.
mkdir -p data
for entry in "${WORK}/new"/*; do
    name=$(basename "${entry}")
    if [ "${name}" = "data" ]; then
        for d in "${entry}"/*; do
            dn=$(basename "${d}")
            if [ -d "${d}" ]; then
                rm -rf "data/${dn}" && mv "${d}" "data/${dn}" || fatal "could not move data/${dn} into place"
            else
                mv -f "${d}" "data/${dn}" || fatal "could not move data/${dn} into place"
            fi
        done
    else
        rm -rf "/mnt/server/${name}" && mv "${entry}" "/mnt/server/${name}" || fatal "could not move ${name} into place"
    fi
done

for f in server-settings map-gen-settings map-settings; do
    if [ -f "data/${f}.json" ]; then
        echo "Keeping existing data/${f}.json"
    else
        cp "data/${f}.example.json" "data/${f}.json" || fatal "data/${f}.example.json is missing"
        echo "Created data/${f}.json"
    fi
done
mkdir -p saves mods
echo "${VERSION}" > .factorio-version

echo "-----------------------------------------"
echo "Installation completed: Factorio ${VERSION}"
echo "-----------------------------------------"
