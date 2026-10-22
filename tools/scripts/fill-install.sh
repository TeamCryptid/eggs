#!/bin/ash
# fill-install.sh v1.0.1 - TeamCryptid eggs
# Installs Paper or Velocity from the PaperMC Fill v3 API.
# PROJECT is set by tools/build.py when the egg is built.
#
# Based on pelican-eggs/minecraft (MIT). Changes from upstream:
#   - User-Agent sent on every API call (required by PaperMC)
#   - "latest" resolves to the newest stable version (no SNAPSHOT/rc/pre)
#   - Download verified against the API's SHA-256 before replacing the jar
#   - Old jar is kept until the new one is verified
#   - Velocity: honours VELOCITY_VERSION, random forwarding.secret
#
# Server Files: /mnt/server
PROJECT="__PROJECT__"

: "${API_ENDPOINT:=fill.papermc.io}"
: "${SERVER_JARFILE:=server.jar}"
: "${BUILD_NUMBER:=latest}"
: "${USER_AGENT:=TeamCryptid-eggs/__EGGS_VERSION__ (https://github.com/TeamCryptid/eggs)}"
CONFIG_BASE="https://raw.githubusercontent.com/TeamCryptid/eggs/main/minecraft"
API="https://${API_ENDPOINT}/v3/projects/${PROJECT}"

fail() {
	echo "ERROR: $*"
	exit 1
}

api() {
	curl -fsSL -H "User-Agent: ${USER_AGENT}" "$1"
}

if [ "${PROJECT}" = "velocity" ]; then
	VERSION="${VELOCITY_VERSION:-latest}"
else
	VERSION="${MINECRAFT_VERSION:-latest}"
fi

mkdir -p /mnt/server
cd /mnt/server || fail "cannot enter /mnt/server"

EXPECTED_SHA=""
if [ -n "${DL_PATH}" ]; then
	echo "Using supplied download URL: ${DL_PATH}"
	DOWNLOAD_URL=$(eval echo "$(echo "${DL_PATH}" | sed -e 's/{{/${/g' -e 's/}}/}/g')")
else
	PROJECT_JSON=$(api "${API}") || fail "could not reach ${API}"

	LATEST_VERSION=$(printf '%s' "${PROJECT_JSON}" | jq -r '[.versions[][] | select(test("SNAPSHOT|-rc|-pre|-beta|-alpha"; "i") | not)][0] // empty')
	[ -n "${LATEST_VERSION}" ] || fail "no stable ${PROJECT} version found"

	if [ "${VERSION}" = "latest" ]; then
		VERSION="${LATEST_VERSION}"
	elif ! printf '%s' "${PROJECT_JSON}" | jq -e --arg v "${VERSION}" '[.versions[][]] | index($v)' >/dev/null; then
		echo "Version ${VERSION} not found. Using latest stable ${LATEST_VERSION}"
		VERSION="${LATEST_VERSION}"
	fi

	BUILD_JSON=$(api "${API}/versions/${VERSION}/builds/${BUILD_NUMBER}") || {
		echo "Build ${BUILD_NUMBER} not found for ${VERSION}. Using latest build"
		BUILD_JSON=$(api "${API}/versions/${VERSION}/builds/latest") || fail "no builds for ${PROJECT} ${VERSION}"
	}

	BUILD_NUMBER=$(printf '%s' "${BUILD_JSON}" | jq -r '.id')
	DOWNLOAD_URL=$(printf '%s' "${BUILD_JSON}" | jq -r '.downloads."server:default".url // empty')
	EXPECTED_SHA=$(printf '%s' "${BUILD_JSON}" | jq -r '.downloads."server:default".checksums.sha256 // empty')
	[ -n "${DOWNLOAD_URL}" ] || fail "no download URL for ${PROJECT} ${VERSION} build ${BUILD_NUMBER}"

	echo "Project: ${PROJECT}"
	echo "Version: ${VERSION}"
	echo "Build:   ${BUILD_NUMBER}"
fi

echo "Downloading ${DOWNLOAD_URL}"
curl -fsSL -H "User-Agent: ${USER_AGENT}" -o "${SERVER_JARFILE}.new" "${DOWNLOAD_URL}" || {
	rm -f "${SERVER_JARFILE}.new"
	fail "download failed"
}

if [ -n "${EXPECTED_SHA}" ]; then
	ACTUAL_SHA=$(sha256sum "${SERVER_JARFILE}.new" | cut -d' ' -f1)
	if [ "${ACTUAL_SHA}" != "${EXPECTED_SHA}" ]; then
		rm -f "${SERVER_JARFILE}.new"
		fail "SHA-256 mismatch (expected ${EXPECTED_SHA}, got ${ACTUAL_SHA})"
	fi
	echo "SHA-256 verified: ${ACTUAL_SHA}"
fi

if [ -f "${SERVER_JARFILE}" ]; then
	mv "${SERVER_JARFILE}" "${SERVER_JARFILE}.old"
fi
mv "${SERVER_JARFILE}.new" "${SERVER_JARFILE}"

if [ "${PROJECT}" = "velocity" ]; then
	if [ ! -f velocity.toml ]; then
		echo "Downloading velocity.toml"
		curl -fsSL -o velocity.toml "${CONFIG_BASE}/proxy/velocity/velocity.toml" || fail "could not download velocity.toml"
	fi
	if [ ! -s forwarding.secret ]; then
		echo "Creating forwarding.secret"
		head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32 > forwarding.secret
	fi
else
	if [ ! -f server.properties ]; then
		echo "Downloading server.properties"
		curl -fsSL -o server.properties "${CONFIG_BASE}/java/server.properties" || fail "could not download server.properties"
	fi
fi

echo "Install complete"
