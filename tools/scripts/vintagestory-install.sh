#!/bin/bash
## ---------------------------------------------------------------------------
## TeamCryptid eggs: Vintage Story server install.
## Replaces the upstream install script (pelican-eggs/games-standalone, MIT).
##
## Changes from upstream:
##   - any failure exits 1 (upstream used a bare `exit`, so the panel showed success)
##   - downloads and verifies (MD5 from the release API) BEFORE touching the
##     installed files; a failed download leaves the server as it was
##   - release API over https
##   - refuses to install an older version than the one installed (worlds can
##     break on downgrade) unless ALLOW_DOWNGRADE=1, which only staff can set
##   - records the installed version in .vs-version and the .NET major version it
##     needs in .vs-dotnet; the startup command uses .vs-dotnet to say which
##     Docker image to pick when it doesn't match
## Server Files: /mnt/server
## ---------------------------------------------------------------------------

fatal() {
    echo "-----------------------------------------"
    echo "Installation failed: $*"
    echo "-----------------------------------------"
    exit 1
}

API="https://api.vintagestory.at"
CDN="https://cdn.vintagestory.at/gamefiles"
BRANCH="${FILES_BRANCH:-stable}"
VERSION="${RELEASE_VERSION:-latest}"
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT

case "${BRANCH}" in
    stable|unstable|pre) ;;
    *) fatal "unknown release branch '${BRANCH}' (use stable, unstable or pre)" ;;
esac

# Debian version order, with -rc / -pre treated as pre-releases (1.22.0-rc.10 < 1.22.0).
vs_ver() { echo "$1" | sed -E 's/-(rc|pre)/~\1/'; }

EXPECTED_MD5=""
if [ "${BRANCH}" = "pre" ]; then
    [ "${VERSION}" != "latest" ] || fatal "the pre branch has no release list; set Release version to an exact version"
    DOWNLOAD_URL="${CDN}/pre/vs_server_linux-x64_${VERSION}.tar.gz"
else
    LIST=$(curl -sfSL "${API}/${BRANCH}.json") || fatal "could not reach ${API}/${BRANCH}.json"
    if [ "${VERSION}" = "latest" ]; then
        VERSION=$(jq -r 'keys_unsorted[0] // empty' <<< "${LIST}")
        [ -n "${VERSION}" ] || fatal "no versions listed on the ${BRANCH} branch"
    fi
    ENTRY=$(jq -c --arg v "${VERSION}" '.[$v].linuxserver // empty' <<< "${LIST}")
    if [ -n "${ENTRY}" ]; then
        DOWNLOAD_URL=$(jq -r '.urls.cdn // .urls.local // empty' <<< "${ENTRY}")
        EXPECTED_MD5=$(jq -r '.md5 // empty' <<< "${ENTRY}")
    else
        echo "Version ${VERSION} is not listed on the ${BRANCH} branch; trying the CDN directly (no checksum)"
        DOWNLOAD_URL="${CDN}/${BRANCH}/vs_server_linux-x64_${VERSION}.tar.gz"
    fi
fi

echo "Branch:   ${BRANCH}"
echo "Version:  ${VERSION}"
echo "Download: ${DOWNLOAD_URL}"

cd /mnt/server || fatal "cannot enter /mnt/server"

# Downgrade guard.
if [ -f .vs-version ]; then
    INSTALLED=$(cat .vs-version)
    if dpkg --compare-versions "$(vs_ver "${VERSION}")" lt "$(vs_ver "${INSTALLED}")"; then
        if [ "${ALLOW_DOWNGRADE}" = "1" ]; then
            echo "WARNING: downgrading ${INSTALLED} -> ${VERSION} because Allow Downgrade is on"
        else
            fatal "${VERSION} is older than the installed ${INSTALLED}. Downgrading can damage worlds. Back up the server, then ask staff to turn on Allow Downgrade."
        fi
    fi
fi

curl -sfSL -o "${WORK}/vs_server.tar.gz" "${DOWNLOAD_URL}" || fatal "download failed. Check that version ${VERSION} exists on the ${BRANCH} branch."
if [ -n "${EXPECTED_MD5}" ]; then
    ACTUAL_MD5=$(md5sum "${WORK}/vs_server.tar.gz" | cut -d' ' -f1)
    [ "${ACTUAL_MD5}" = "${EXPECTED_MD5}" ] || fatal "checksum mismatch (expected ${EXPECTED_MD5}, got ${ACTUAL_MD5})"
    echo "MD5 verified: ${ACTUAL_MD5}"
fi

mkdir -p "${WORK}/new"
tar -xzf "${WORK}/vs_server.tar.gz" -C "${WORK}/new" || fatal "the download is not a valid server archive"
[ -f "${WORK}/new/VintagestoryServer.dll" ] || fatal "the archive does not contain VintagestoryServer.dll"
DOTNET_MAJOR=$(jq -r '.runtimeOptions.tfm // empty' "${WORK}/new/VintagestoryServer.runtimeconfig.json" 2>/dev/null | sed -E 's/^net([0-9]+).*/\1/')

# Only now replace the installed game files. Old assets/ and Lib/ go first so files
# removed in the new version don't linger (as upstream did). data/ (worlds, config, mods) is never touched.
if [ -d assets ]; then
    echo "Removing old installation files"
    rm -rf assets/ Lib/
fi
cp -a "${WORK}/new/." /mnt/server/ || fatal "could not copy the new server files into place"
rm -f server.sh

echo "${VERSION}" > .vs-version
if [ -n "${DOTNET_MAJOR}" ]; then
    echo "${DOTNET_MAJOR}" > .vs-dotnet
    echo "This version needs .NET ${DOTNET_MAJOR}: pick the 'Dotnet ${DOTNET_MAJOR}' Docker image in Startup."
else
    rm -f .vs-dotnet
fi

echo "-----------------------------------------"
echo "Installation completed: Vintage Story ${VERSION} (${BRANCH})"
echo "-----------------------------------------"
