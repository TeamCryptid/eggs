## ---------------------------------------------------------------------------
## TeamCryptid eggs: BepInEx + Thunderstore modpack install for Valheim.
## tools/build.py appends this to the upstream SteamCMD part of the install.
##
## Changes from upstream (pelican-eggs/games-steamcmd, MIT):
##   - any failed download or extract fails the install (upstream called an
##     undefined fatal() and then reported "Installation completed")
##   - modpacks follow nested dependencies (packs of packs) and keep every
##     file, placed the way r2modman does; upstream copied only *.dll files
##   - configs in BepInEx/config are kept across a reinstall
## ---------------------------------------------------------------------------

fatal() {
    echo -e "\nERROR: $*\n"
    exit 1
}

TS_API="https://thunderstore.io/api/experimental/package"
TS_DOWNLOAD="https://thunderstore.io/package/download"
SKIP_PACKAGE="denikson-BepInExPack_Valheim"
WORK=$(mktemp -d)

cd /mnt/server || fatal "cannot enter /mnt/server"

# Keep existing configs (BepInEx.cfg, mod configs) so a reinstall does not reset them.
if [ -d BepInEx/config ]; then
    cp -a BepInEx/config "${WORK}/config.keep"
fi

echo "-------------------------------------------------------"
echo "installing BepInEx..."
echo "-------------------------------------------------------"
api_response=$(curl -sfSL -H "accept: application/json" "${BEPINEX_URL}") || fatal "could not reach Thunderstore (${BEPINEX_URL})"
download_url=$(jq -r '.latest.download_url // empty' <<< "${api_response}")
version_number=$(jq -r '.latest.version_number // empty' <<< "${api_response}")
[ -n "${download_url}" ] || fatal "Thunderstore returned no BepInEx download"

curl -sfSL -o "${WORK}/bepinex.zip" "${download_url}" || fatal "BepInEx download failed"
unzip -q -o "${WORK}/bepinex.zip" -d "${WORK}/bepinex" || fatal "BepInEx archive is damaged"
[ -d "${WORK}/bepinex/BepInExPack_Valheim" ] || fatal "unexpected BepInEx archive layout"
cp -r "${WORK}/bepinex/BepInExPack_Valheim/." /mnt/server/ || fatal "could not copy BepInEx into place"
echo "BepInEx ${version_number} installed"

# Split "Namespace-Name-Version" (Thunderstore names never contain dashes).
split_id() {
    IFS='-' read -r PKG_NS PKG_NAME PKG_VER <<< "$1"
}

# Depth-first walk of a package's dependencies; ORDER ends up dependencies-first.
declare -A SEEN
ORDER=()
resolve() {
    local id="$1" ns name ver key json deps dep
    split_id "${id}"
    ns="${PKG_NS}"; name="${PKG_NAME}"; ver="${PKG_VER}"
    key="${ns}-${name}"
    [ "${key}" = "${SKIP_PACKAGE}" ] && return
    [ -n "${SEEN[${key}]}" ] && return
    SEEN[${key}]=1
    json=$(curl -sfSL -H "accept: application/json" "${TS_API}/${ns}/${name}/${ver}/") || fatal "could not read ${id} from Thunderstore"
    deps=$(jq -r '.dependencies[]?' <<< "${json}")
    for dep in ${deps}; do
        resolve "${dep}"
    done
    ORDER+=("${id}")
}

# Place one package's files where BepInEx expects them (same layout as r2modman):
#   BepInEx/          -> merged into BepInEx/
#   plugins/ patchers/ monomod/ -> BepInEx/<folder>/<Namespace-Name>/
#   config/           -> BepInEx/config/
#   anything else     -> BepInEx/plugins/<Namespace-Name>/
install_package() {
    local id="$1" key dir entry base lower
    split_id "${id}"
    key="${PKG_NS}-${PKG_NAME}"
    dir="${WORK}/pkg/${key}"
    rm -rf "${dir}" && mkdir -p "${dir}"
    curl -sfSL -o "${WORK}/pkg.zip" "${TS_DOWNLOAD}/${PKG_NS}/${PKG_NAME}/${PKG_VER}/" || fatal "download failed: ${id}"
    unzip -q -o "${WORK}/pkg.zip" -d "${dir}" || fatal "damaged archive: ${id}"

    for entry in "${dir}"/* "${dir}"/.[!.]*; do
        [ -e "${entry}" ] || continue
        base=$(basename "${entry}")
        lower="${base,,}"
        case "${lower}" in
            manifest.json|icon.png|readme*|changelog*|license*)
                ;;
            bepinex)
                mkdir -p BepInEx && cp -a "${entry}/." BepInEx/ ;;
            plugins|patchers|monomod)
                mkdir -p "BepInEx/${lower}/${key}" && cp -a "${entry}/." "BepInEx/${lower}/${key}/" ;;
            config)
                mkdir -p BepInEx/config && cp -a "${entry}/." BepInEx/config/ ;;
            *)
                mkdir -p "BepInEx/plugins/${key}" && cp -a "${entry}" "BepInEx/plugins/${key}/" ;;
        esac || fatal "could not place files for ${id}"
    done
    echo "  installed ${id}"
}

if [ -n "${V_MODPACK}" ]; then
    echo "-------------------------------------------------------"
    echo "installing modpack ${V_MODPACK}..."
    echo "-------------------------------------------------------"
    split_id "${V_MODPACK}"
    [ -n "${PKG_NS}" ] && [ -n "${PKG_NAME}" ] || fatal "modpack must look like Author-PackName or Author-PackName-1.2.3, got: ${V_MODPACK}"
    if [ -z "${PKG_VER}" ]; then
        json=$(curl -sfSL -H "accept: application/json" "${TS_API}/${PKG_NS}/${PKG_NAME}/") || fatal "modpack ${V_MODPACK} not found on Thunderstore"
        PKG_VER=$(jq -r '.latest.version_number // empty' <<< "${json}")
        [ -n "${PKG_VER}" ] || fatal "modpack ${V_MODPACK} has no published version"
    fi
    MODPACK_ID="${PKG_NS}-${PKG_NAME}-${PKG_VER}"

    resolve "${MODPACK_ID}"
    echo "${#ORDER[@]} packages to install (including the modpack itself)"

    # Fresh plugin set for the pack, as upstream did.
    rm -rf BepInEx/plugins/*
    mkdir -p BepInEx/plugins

    # Dependencies first, the modpack itself last, so the pack's own configs win over mod defaults.
    for id in "${ORDER[@]}"; do
        install_package "${id}"
    done
fi

# Existing configs win over the pack's and the mods' defaults.
if [ -d "${WORK}/config.keep" ]; then
    mkdir -p BepInEx/config
    cp -a "${WORK}/config.keep/." BepInEx/config/
    echo "kept existing BepInEx/config"
fi

rm -rf "${WORK}"

echo "-------------------------------------------------------"
echo "Installation completed"
echo "-------------------------------------------------------"
