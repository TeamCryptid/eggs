## ---------------------------------------------------------------------------
## TeamCryptid eggs: ValheimPlus install for Valheim.
## tools/build.py appends this to the upstream SteamCMD part of the install.
##
## Changes from upstream (pelican-eggs/games-steamcmd, MIT):
##   - downloads the release asset directly instead of through the GitHub API
##     (no unauthenticated API rate limit; no jq parsing of release lists)
##   - an unknown VERSION fails the install instead of silently installing
##     whatever the latest release is
##   - any failed download or extract fails the install (upstream always
##     reported "Installation completed")
##   - configs in BepInEx/config are kept across a reinstall
## ---------------------------------------------------------------------------

fatal() {
    echo -e "\nERROR: $*\n"
    exit 1
}

WORK=$(mktemp -d)
cd /mnt/server || fatal "cannot enter /mnt/server"

if [ -z "${VERSION}" ] || [ "${VERSION}" = "latest" ]; then
    DOWNLOAD_LINK="https://github.com/${GITHUB_PACKAGE}/releases/latest/download/${MATCH}"
else
    DOWNLOAD_LINK="https://github.com/${GITHUB_PACKAGE}/releases/download/${VERSION}/${MATCH}"
fi

echo "-------------------------------------------------"
echo "downloading ValheimPlus: ${DOWNLOAD_LINK}"
echo "-------------------------------------------------"
curl -sfSL -o "${WORK}/vplus.zip" "${DOWNLOAD_LINK}" || fatal "ValheimPlus download failed (${GITHUB_PACKAGE}, version ${VERSION:-latest})"

# Keep existing configs (BepInEx.cfg, valheim_plus.cfg) so a reinstall does not reset them.
if [ -d BepInEx/config ]; then
    cp -a BepInEx/config "${WORK}/config.keep"
fi

unzip -q -o "${WORK}/vplus.zip" -d /mnt/server || fatal "ValheimPlus archive is damaged"
[ -f BepInEx/core/BepInEx.Preloader.dll ] || fatal "ValheimPlus archive has no BepInEx preloader"

if [ -d "${WORK}/config.keep" ]; then
    cp -a "${WORK}/config.keep/." BepInEx/config/
    echo "kept existing BepInEx/config"
fi

rm -rf "${WORK}"

echo "-------------------------------------------------"
echo "Installation completed"
echo "-------------------------------------------------"
