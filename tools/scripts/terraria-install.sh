#!/bin/bash
## ---------------------------------------------------------------------------
## TeamCryptid eggs: Terraria (vanilla) server install.
## Replaces the upstream install script (pelican-eggs/games-standalone, MIT).
##
## Changes from upstream:
##   - any failure exits 1 (upstream reported "Install complete" even when nothing
##     was installed, e.g. for an unknown version)
##   - exact versions download from terraria.org's own API (1.4.4.9 or 1449);
##     only versions the API doesn't serve fall back to the wiki's download links
##   - staged on the server's disk, not the 100 MB /tmp; the zip is removed afterwards
##   - serverconfig.txt is created only when missing, so settings customers add
##     there survive a reinstall
## Server Files: /mnt/server
## ---------------------------------------------------------------------------

fatal() {
    echo "-----------------------------------------"
    echo "Installation failed: $*"
    echo "-----------------------------------------"
    exit 1
}

API="https://terraria.org/api"
WORK=/mnt/server/.terraria-install
trap 'rm -rf "${WORK}"' EXIT

cd /mnt/server || fatal "cannot enter /mnt/server"
rm -rf "${WORK}" && mkdir -p "${WORK}" || fatal "cannot create ${WORK}"

if [ -z "${TERRARIA_VERSION}" ] || [ "${TERRARIA_VERSION}" = "latest" ]; then
    FILE=$(curl -sfSL "${API}/get/dedicated-servers-names" | jq -r '.[0] // empty') || fatal "could not reach terraria.org"
    [ -n "${FILE}" ] || fatal "terraria.org listed no server versions"
else
    # 1.4.4.9 and 1449 both mean terraria-server-1449.zip
    DIGITS=$(echo "${TERRARIA_VERSION}" | tr -d '.')
    echo "${DIGITS}" | grep -qE '^[0-9]+$' || fatal "'${TERRARIA_VERSION}' is not a version (use latest, or e.g. 1.4.4.9 or 1449)"
    FILE="terraria-server-${DIGITS}.zip"
fi
NUM=$(echo "${FILE}" | sed -E 's/^terraria-server-([0-9]+)\.zip$/\1/')
echo "${NUM}" | grep -qE '^[0-9]+$' || fatal "unexpected file name from terraria.org: ${FILE}"

URL="${API}/download/pc-dedicated-server/${FILE}"
if ! curl -sfSL -o "${WORK}/server.zip" "${URL}"; then
    # Older versions aren't on the API; the wiki links to terraria.org's archive for them.
    echo "terraria.org's API doesn't serve ${FILE}; looking it up on the wiki"
    URL=$(curl -sfSL "https://terraria.wiki.gg/wiki/Server" | grep -Eo "https://[^\"' ]+/${FILE}" | head -1)
    [ -n "${URL}" ] || fatal "Terraria server ${TERRARIA_VERSION} not found. Check the version number."
    curl -sfSL -o "${WORK}/server.zip" "${URL}" || fatal "download failed: ${URL}"
fi
echo "Downloaded: ${URL}"

unzip -tqq "${WORK}/server.zip" >/dev/null || fatal "the download is not a valid zip"
unzip -l "${WORK}/server.zip" "${NUM}/Linux/TerrariaServer.bin.x86_64" >/dev/null 2>&1 || fatal "Terraria server ${NUM} has no Linux version"
unzip -q "${WORK}/server.zip" "${NUM}/Linux/*" -d "${WORK}" || fatal "could not unpack the server archive"
rm -f "${WORK}/server.zip"

cp -a "${WORK}/${NUM}/Linux/." /mnt/server/ || fatal "could not copy the server files into place"
chmod +x TerrariaServer.bin.x86_64 TerrariaServer
rm -f terraria-server-*.zip   # left behind by the upstream install

if [ -f serverconfig.txt ]; then
    echo "Keeping existing serverconfig.txt"
else
    echo "Generating serverconfig.txt"
    cat <<EOF > serverconfig.txt
worldpath=/home/container/saves/Worlds
worldname=default
world=/home/container/saves/Worlds/default.wld
difficulty=0
autocreate=1
port=7777
maxplayers=8
EOF
fi
mkdir -p saves/Worlds
echo "${NUM}" > .terraria-version

echo "-----------------------------------------"
echo "Installation completed: Terraria server ${NUM}"
echo "-----------------------------------------"
