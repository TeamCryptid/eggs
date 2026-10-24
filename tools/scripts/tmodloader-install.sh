#!/bin/bash
## ---------------------------------------------------------------------------
## TeamCryptid eggs: tModLoader (Terraria) server install.
## Replaces the upstream install script (pelican-eggs/games-standalone, MIT).
##
## Changes from upstream:
##   - any failure exits 1
##   - downloads straight from the release (no GitHub API, so no rate limit and no
##     token needed); a pinned VERSION is honoured (upstream's lookup always fell
##     back to latest) and an unknown one fails the install
##   - staged on the server's disk, not the 100 MB /tmp
##   - serverconfig.txt is created only when missing, so a reinstall keeps it
##   - Workshop mods: the Steam Workshop IDs in WORKSHOP_MODS are downloaded with
##     SteamCMD into steamapps/workshop (the startup passes -steamworkshopfolder) and
##     enabled in mods/enabled.json. IDs removed from the list are deleted and disabled.
##   - records the .NET major version tModLoader needs in .tml-dotnet; the startup
##     command uses it to say which Docker image to pick when it doesn't match
## Server Files: /mnt/server
## ---------------------------------------------------------------------------

fatal() {
    echo "-----------------------------------------"
    echo "Installation failed: $*"
    echo "-----------------------------------------"
    exit 1
}

RELEASES="https://github.com/tModLoader/tModLoader/releases"
STEAMCMD_URL="https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
APP_ID=1281930   # tModLoader's Steam app, which owns its Workshop
WORK=/mnt/server/.tml-install
CONTENT=/mnt/server/steamapps/workshop/content/${APP_ID}
trap 'rm -rf "${WORK}"' EXIT

cd /mnt/server || fatal "cannot enter /mnt/server"
rm -rf "${WORK}" && mkdir -p "${WORK}/new" || fatal "cannot create ${WORK}"

# --- tModLoader itself -------------------------------------------------------
LEGACY=0
if [ -z "${VERSION}" ] || [ "${VERSION}" = "latest" ]; then
    TAG="latest"
    URL="${RELEASES}/latest/download/tModLoader.zip"
else
    TAG="v${VERSION#v}"   # v2026.08.3.0 and 2026.08.3.0 both work
    case "${TAG}" in
        v0.*) LEGACY=1; URL="${RELEASES}/download/${TAG}/tModLoader.Linux.${TAG}.zip" ;;   # tModLoader for Terraria 1.3
        *)    URL="${RELEASES}/download/${TAG}/tModLoader.zip" ;;
    esac
fi
echo "tModLoader: ${TAG}"
echo "Download:   ${URL}"
curl -sfSL -o "${WORK}/tml.zip" "${URL}" || fatal "download failed. Check that tModLoader version '${VERSION}' exists on ${RELEASES}"
unzip -q "${WORK}/tml.zip" -d "${WORK}/new" || fatal "the download is not a valid zip"
rm -f "${WORK}/tml.zip"

if [ "${LEGACY}" = 1 ]; then
    [ -f "${WORK}/new/tModLoaderServer.bin.x86_64" ] || fatal "the archive has no tModLoaderServer"
    chmod +x "${WORK}/new/tModLoaderServer" "${WORK}/new/tModLoaderServer.bin.x86_64"
    DOTNET_MAJOR=""
else
    [ -f "${WORK}/new/tModLoader.dll" ] || fatal "the archive does not contain tModLoader.dll"
    # Tiny launcher for the startup command, as upstream.
    echo 'dotnet tModLoader.dll -server "$@"' > "${WORK}/new/tModLoaderServer"
    chmod +x "${WORK}/new/tModLoaderServer"
    ( cd "${WORK}/new" && rm -rf DedicatedServerUtils LaunchUtils PlatformVariantLibs tModPorter RecentGitHubCommits.txt ./*.bat ./*.sh )
    DOTNET_MAJOR=$(jq -r '.runtimeOptions.tfm // empty' "${WORK}/new/tModLoader.runtimeconfig.json" 2>/dev/null | sed -E 's/^net([0-9]+).*/\1/')
fi

# serverconfig.txt: keep the customer's; on a first install use the shipped one with
# difficulty uncommented, because the panel sets difficulty there (as upstream).
if [ -f serverconfig.txt ]; then
    echo "Keeping existing serverconfig.txt"
    rm -f "${WORK}/new/serverconfig.txt"
elif [ -f "${WORK}/new/serverconfig.txt" ]; then
    sed -i 's/^#difficulty/difficulty/' "${WORK}/new/serverconfig.txt"
else
    echo "difficulty=0" > "${WORK}/new/serverconfig.txt"
fi

for entry in "${WORK}/new"/* "${WORK}/new"/.[!.]*; do
    [ -e "${entry}" ] || continue
    name=$(basename "${entry}")
    case "${name}" in mods|saves|steamapps) continue ;; esac
    rm -rf "/mnt/server/${name}" && mv "${entry}" "/mnt/server/${name}" || fatal "could not move ${name} into place"
done
mkdir -p mods saves/Worlds

if [ -n "${DOTNET_MAJOR}" ]; then
    echo "${DOTNET_MAJOR}" > .tml-dotnet
    echo "This version needs .NET ${DOTNET_MAJOR}: pick the 'Dotnet ${DOTNET_MAJOR}' Docker image in Startup."
else
    rm -f .tml-dotnet
fi
echo "${TAG}" > .tml-version

# --- Workshop mods -------------------------------------------------------------
IDS=$(echo "${WORKSHOP_MODS}" | tr ',;' '  ' | xargs)
for id in ${IDS}; do
    echo "${id}" | grep -qE '^[0-9]+$' || fatal "Workshop mods must be Steam Workshop IDs (numbers), got '${id}'"
done
[ -z "${IDS}" ] || [ "${LEGACY}" = 0 ] || fatal "Workshop mods need tModLoader 1.4 (the version setting is a 1.3 release)"

# .tml-workshop lists what an earlier install added: "<id> <ModName>" per line.
touch .tml-workshop
NEW_LIST="${WORK}/workshop.list"
: > "${NEW_LIST}"

if [ -n "${IDS}" ]; then
    echo "Downloading SteamCMD"
    mkdir -p "${WORK}/steamcmd"
    curl -sfSL "${STEAMCMD_URL}" | tar -xzf - -C "${WORK}/steamcmd" || fatal "could not download SteamCMD"
    ARGS=""
    for id in ${IDS}; do ARGS="${ARGS} +workshop_download_item ${APP_ID} ${id}"; done
    echo "Downloading Workshop mods: ${IDS}"
    # shellcheck disable=SC2086
    HOME="${WORK}" "${WORK}/steamcmd/steamcmd.sh" +force_install_dir /mnt/server +login anonymous ${ARGS} +quit \
        | grep -E 'Success|ERROR|rror!|Downloaded item'
    for id in ${IDS}; do
        names=$(find "${CONTENT}/${id}" -name '*.tmod' -printf '%f\n' 2>/dev/null | sed 's/\.tmod$//' | sort -u)
        [ -n "${names}" ] || fatal "Workshop item ${id} did not download, or has no tModLoader mod in it. Check the ID."
        for n in ${names}; do echo "${id} ${n}" >> "${NEW_LIST}"; echo "  ${id} -> ${n}"; done
    done
fi

# IDs taken off the list: delete their files and disable their mods (unless a listed item provides the same mod).
REMOVE_NAMES=""
while read -r id n; do
    [ -n "${id}" ] || continue
    if ! echo " ${IDS} " | grep -q " ${id} "; then
        rm -rf "${CONTENT:?}/${id}"
        grep -q " ${n}\$" "${NEW_LIST}" || REMOVE_NAMES="${REMOVE_NAMES} ${n}"
    fi
done < .tml-workshop
ADD_NAMES=$(cut -d' ' -f2 "${NEW_LIST}" | sort -u | xargs)

if [ -n "${ADD_NAMES}${REMOVE_NAMES}" ]; then
    [ -f mods/enabled.json ] && jq -e 'type == "array"' mods/enabled.json >/dev/null 2>&1 || echo '[]' > mods/enabled.json
    jq --arg add "${ADD_NAMES}" --arg rm "${REMOVE_NAMES}" \
        '(. - ($rm | split(" ") | map(select(length > 0)))) + ($add | split(" ") | map(select(length > 0))) | unique' \
        mods/enabled.json > "${WORK}/enabled.json" && mv "${WORK}/enabled.json" mods/enabled.json || fatal "could not update mods/enabled.json"
    [ -z "${REMOVE_NAMES}" ] || echo "Disabled (removed from Workshop mods):${REMOVE_NAMES}"
    echo "Enabled mods: $(jq -r 'join(", ")' mods/enabled.json)"
fi
cp "${NEW_LIST}" .tml-workshop

echo "-----------------------------------------"
echo "Installation completed: tModLoader ${TAG}"
echo "-----------------------------------------"
