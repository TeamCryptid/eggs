#!/bin/bash
## ---------------------------------------------------------------------------
## TeamCryptid eggs: TShock (Terraria) server install.
## Replaces the upstream install script (pelican-eggs/games-standalone, MIT).
##
## Changes from upstream:
##   - any failure exits 1 (upstream reported "install complete" after failed downloads)
##   - an unknown TSHOCK_VERSION fails the install instead of silently installing latest
##   - one GitHub API call per install (upstream made two), with a clear message when
##     GitHub's rate limit is hit
##   - staged on the server's disk, not the 100 MB /tmp
##   - plugins customers added to ServerPlugins/ are kept; tshock/ (config, users,
##     database) and worlds are never touched
##   - records the installed version in .tshock-version and the .NET major version it
##     needs in .tshock-dotnet; the startup command uses .tshock-dotnet to say which
##     Docker image to pick when it doesn't match
## Server Files: /mnt/server
## ---------------------------------------------------------------------------

fatal() {
    echo "-----------------------------------------"
    echo "Installation failed: $*"
    echo "-----------------------------------------"
    exit 1
}

REPO="Pryaxis/TShock"
WORK=/mnt/server/.tshock-install
trap 'rm -rf "${WORK}"' EXIT

# TShock 6 names its builds linux-x64, TShock 5 linux-amd64.
case "$(uname -m)" in
    x86_64)  MATCH="linux-(x64|amd64)-" ;;
    aarch64) MATCH="linux-arm64-" ;;
    *) fatal "unsupported CPU architecture $(uname -m)" ;;
esac

if [ -z "${TSHOCK_VERSION}" ] || [ "${TSHOCK_VERSION}" = "latest" ]; then
    API_URL="https://api.github.com/repos/${REPO}/releases/latest"
else
    TAG="v${TSHOCK_VERSION#v}"   # 6.2.1 and v6.2.1 both work
    API_URL="https://api.github.com/repos/${REPO}/releases/tags/${TAG}"
fi

cd /mnt/server || fatal "cannot enter /mnt/server"
rm -rf "${WORK}" && mkdir -p "${WORK}" || fatal "cannot create ${WORK}"

CODE=$(curl -sSL -o "${WORK}/release.json" -w '%{http_code}' -H "Accept: application/vnd.github+json" "${API_URL}") || fatal "could not reach GitHub"
case "${CODE}" in
    200) ;;
    404) fatal "TShock version '${TSHOCK_VERSION}' not found. Check the tag on https://github.com/${REPO}/releases" ;;
    403|429) fatal "GitHub's API rate limit was hit (60 requests per hour per IP address). Try again later." ;;
    *) fatal "GitHub answered HTTP ${CODE} for ${API_URL}" ;;
esac
TAG=$(jq -r '.tag_name // empty' "${WORK}/release.json")
DOWNLOAD_URL=$(jq -r --arg m "${MATCH}" '.assets[]? | select(.name | test($m)) | .browser_download_url' "${WORK}/release.json" | head -1)
[ -n "${DOWNLOAD_URL}" ] || fatal "TShock ${TAG} has no Linux $(uname -m) download"

echo "TShock:   ${TAG}"
echo "Download: ${DOWNLOAD_URL}"

curl -sfSL -o "${WORK}/tshock.zip" "${DOWNLOAD_URL}" || fatal "download failed"
mkdir -p "${WORK}/zip" "${WORK}/new"
unzip -q "${WORK}/tshock.zip" -d "${WORK}/zip" || fatal "the download is not a valid zip"
rm -f "${WORK}/tshock.zip"
# TShock 5+ ships a tar inside the zip; older releases are a plain zip.
TAR=$(find "${WORK}/zip" -maxdepth 1 -name 'TShock-*.tar' | head -1)
if [ -n "${TAR}" ]; then
    tar -xf "${TAR}" -C "${WORK}/new" || fatal "could not unpack ${TAR##*/}"
    rm -rf "${WORK}/zip"
else
    mv "${WORK}/zip/"* "${WORK}/new/" || fatal "unexpected archive layout"
fi
[ -f "${WORK}/new/TShock.Server" ] || fatal "the archive does not contain TShock.Server"
chmod +x "${WORK}/new/TShock.Server"

# .NET major version: from a runtimeconfig file if there is one, otherwise from the
# config embedded in the single-file TShock.Server.
if [ -f "${WORK}/new/TShock.Server.runtimeconfig.json" ]; then
    TFM=$(jq -r '.runtimeOptions.tfm // empty' "${WORK}/new/TShock.Server.runtimeconfig.json")
else
    TFM=$(grep -a -o -m1 '"tfm": "net[0-9]*' "${WORK}/new/TShock.Server" | grep -o 'net[0-9]*')
fi
DOTNET_MAJOR=$(echo "${TFM}" | sed -E 's/^net([0-9]+).*/\1/')

# Replace TShock's own files. ServerPlugins/ is merged so customers' plugins stay.
for entry in "${WORK}/new"/* "${WORK}/new"/.[!.]*; do
    [ -e "${entry}" ] || continue
    name=$(basename "${entry}")
    case "${name}" in tshock|*.wld|*.wld.bak*) continue ;; esac
    if [ "${name}" = "ServerPlugins" ] && [ -d ServerPlugins ]; then
        cp -a "${entry}/." ServerPlugins/ || fatal "could not update ServerPlugins"
    else
        rm -rf "/mnt/server/${name}" && mv "${entry}" "/mnt/server/${name}" || fatal "could not move ${name} into place"
    fi
done

echo "${TAG}" > .tshock-version
if echo "${DOTNET_MAJOR}" | grep -qE '^[0-9]+$'; then
    echo "${DOTNET_MAJOR}" > .tshock-dotnet
    echo "This version needs .NET ${DOTNET_MAJOR}: pick the 'Dotnet ${DOTNET_MAJOR}' Docker image in Startup."
else
    rm -f .tshock-dotnet
    echo "WARNING: could not tell which .NET version TShock ${TAG} needs"
fi

echo "-----------------------------------------"
echo "Installation completed: TShock ${TAG}"
echo "-----------------------------------------"
