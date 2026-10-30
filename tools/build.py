#!/usr/bin/env python3
"""build.py - TeamCryptid eggs

Builds the curated egg set from upstream pelican-eggs checkouts.
Every change we make to upstream eggs lives in this file, so a resync is:

    git clone https://github.com/pelican-eggs/minecraft.git /tmp/minecraft
    git clone https://github.com/pelican-eggs/games-steamcmd.git /tmp/steamcmd
    git clone https://github.com/pelican-eggs/games-standalone.git /tmp/standalone
    python3 tools/build.py --minecraft /tmp/minecraft --steamcmd /tmp/steamcmd --standalone /tmp/standalone
    python3 tools/check_eggs.py
    git diff   # review, then commit
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

UPSTREAMS = {
    "minecraft": "https://github.com/pelican-eggs/minecraft",
    "steamcmd": "https://github.com/pelican-eggs/games-steamcmd",
    "standalone": "https://github.com/pelican-eggs/games-standalone",
}
RAW_BASE = "https://raw.githubusercontent.com/TeamCryptid/eggs/main"
JAVA25_IMAGE = "ghcr.io/pelican-eggs/yolks:java_25"

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILL_SCRIPT = ROOT / "tools" / "scripts" / "fill-install.sh"
VALHEIM_BEPINEX_SCRIPT = ROOT / "tools" / "scripts" / "valheim-bepinex.sh"
VALHEIM_PLUS_SCRIPT = ROOT / "tools" / "scripts" / "valheim-plus.sh"
VINTAGESTORY_SCRIPT = ROOT / "tools" / "scripts" / "vintagestory-install.sh"
TERRARIA_SCRIPT = ROOT / "tools" / "scripts" / "terraria-install.sh"
TSHOCK_SCRIPT = ROOT / "tools" / "scripts" / "tshock-install.sh"
TMODLOADER_SCRIPT = ROOT / "tools" / "scripts" / "tmodloader-install.sh"
FACTORIO_SCRIPT = ROOT / "tools" / "scripts" / "factorio-install.sh"

# id, upstream, upstream source path, destination path in this repo, patches applied
EGGS = [
    ("neoforge", "minecraft", "java/neoforge/egg-pterodactyl-neo-forge.json",
     "minecraft/java/neoforge/egg-pterodactyl-neo-forge.json", []),
    ("forge", "minecraft", "java/forge/pterodactyl-egg-forge-minecraft.json",
     "minecraft/java/forge/pterodactyl-egg-forge-minecraft.json", ["java25", "forge_launch_detect"]),
    ("fabric", "minecraft", "java/fabric/egg-pterodactyl-fabric.json",
     "minecraft/java/fabric/egg-pterodactyl-fabric.json", []),
    ("curseforge", "minecraft", "java/curseforge/egg-pterodactyl-curse-forge-generic.json",
     "minecraft/java/curseforge/egg-pterodactyl-curse-forge-generic.json", []),
    ("modrinth", "minecraft", "java/modrinth/egg-pterodactyl-modrinth-generic.json",
     "minecraft/java/modrinth/egg-pterodactyl-modrinth-generic.json", ["modrinth_script"]),
    ("ftb", "minecraft", "java/ftb/egg-pterodactyl-f-t-b-server.json",
     "minecraft/java/ftb/egg-pterodactyl-f-t-b-server.json", []),
    ("paper", "minecraft", "java/paper/pterodactyl-egg-paper.json",
     "minecraft/java/paper/pterodactyl-egg-paper.json", ["java25", "fill_script"]),
    ("purpur", "minecraft", "java/purpur/egg-pterodactyl-purpur.json",
     "minecraft/java/purpur/egg-pterodactyl-purpur.json", ["server_properties_url"]),
    ("velocity", "minecraft", "proxy/java/velocity/egg-pterodactyl-velocity.json",
     "minecraft/proxy/velocity/egg-pterodactyl-velocity.json", ["java25", "fill_script"]),
    ("zomboid", "steamcmd", "project_zomboid/egg-pterodactyl-project-zomboid.json",
     "zomboid/egg-pterodactyl-project-zomboid.json",
     ["zomboid_startup", "zomboid_max_players", "zomboid_steam_port"]),
    ("valheim", "steamcmd", "valheim/valheim_vanilla/egg-pterodactyl-valheim.json",
     "valheim/vanilla/egg-pterodactyl-valheim.json",
     ["valheim_startup", "valheim_password_text"]),
    ("valheim-bepinex", "steamcmd", "valheim/valheim_bepinex/egg-pterodactyl-valheim-bep-i-nex.json",
     "valheim/bepinex/egg-pterodactyl-valheim-bep-i-nex.json",
     ["valheim_startup", "valheim_password_text", "valheim_bepinex_install", "valheim_modpack_text"]),
    ("valheim-plus", "steamcmd", "valheim/valheim_plus/egg-pterodactyl-valheim-plus-mod.json",
     "valheim/plus/egg-pterodactyl-valheim-plus-mod.json",
     ["valheim_plus_doorstop", "valheim_startup", "valheim_password_text", "valheim_plus_install"]),
    ("hytale", "standalone", "hytale/pterodactyl-egg-hytale.json",
     "hytale/pterodactyl-egg-hytale.json",
     ["hytale_keep_config", "hytale_heap"]),
    ("rust", "steamcmd", "rust/vanilla/egg-pterodactyl-rust.json",
     "rust/egg-pterodactyl-rust.json",
     ["rust_ports", "rust_rcon_password", "rust_max_players", "rust_startup_checks"]),
    ("unturned", "steamcmd", "unturned/egg-pterodactyl-unturned.json",
     "unturned/egg-pterodactyl-unturned.json",
     ["unturned_install", "unturned_variables", "unturned_startup"]),
    ("vintagestory", "standalone", "vintage_story/egg-pterodactyl-vintage-story.json",
     "vintagestory/egg-pterodactyl-vintage-story.json",
     ["vintagestory_install", "vintagestory_variables", "vintagestory_startup"]),
    ("terraria", "standalone", "terraria/vanilla/egg-pterodactyl-terraria-vanilla.json",
     "terraria/vanilla/egg-pterodactyl-terraria-vanilla.json",
     ["terraria_install", "terraria_variables"]),
    ("tshock", "standalone", "terraria/tshock/egg-pterodactyl-tshock.json",
     "terraria/tshock/egg-pterodactyl-tshock.json",
     ["tshock_install", "tshock_images", "tshock_variables", "tshock_startup"]),
    ("tmodloader", "standalone", "terraria/tmodloader/egg-pterodactyl-t-modloader.json",
     "terraria/tmodloader/egg-pterodactyl-t-modloader.json",
     ["tmodloader_install", "tmodloader_images", "tmodloader_variables", "tmodloader_startup"]),
    ("factorio", "standalone", "factorio/factorio/egg-pterodactyl-factorio.json",
     "factorio/egg-pterodactyl-factorio.json",
     ["factorio_install", "factorio_variables", "factorio_startup"]),
    ("7daystodie", "steamcmd", "7_days_to_die/egg-pterodactyl-7-days-to-die.json",
     "7daystodie/egg-pterodactyl-7-days-to-die.json",
     ["7dtd_install", "7dtd_variables", "7dtd_startup"]),
]

# Plain files the eggs download at install time, hosted here instead of upstream.
ASSETS = [
    ("minecraft", "java/server.properties", "minecraft/java/server.properties"),
    ("minecraft", "proxy/java/velocity/velocity.toml", "minecraft/proxy/velocity/velocity.toml"),
]

FILL_PROJECT = {"paper": "paper", "velocity": "velocity"}
OLD_PROPERTIES_URL = "https://raw.githubusercontent.com/parkervcp/eggs/master/minecraft/java/server.properties"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def java_key(name):
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else -1


def patch_java25(egg, _upstream, _egg_id):
    """Add a Java 25 image and list images newest-first so 25 is the first choice."""
    images = dict(egg["docker_images"])
    images.setdefault("Java 25", JAVA25_IMAGE)
    egg["docker_images"] = dict(sorted(images.items(), key=lambda kv: java_key(kv[0]), reverse=True))


def patch_modrinth_script(egg, upstream, _egg_id):
    """Use the newer install script from the Pelican-format egg (adds NeoForge modpacks).
    Both eggs define the same variables (PROJECT_ID, VERSION_ID)."""
    newer = json.loads((upstream / "java/modrinth/egg-modrinth-generic.json").read_text())
    old_vars = {v["env_variable"] for v in egg["variables"]}
    new_vars = {v["env_variable"] for v in newer["variables"]}
    if old_vars != new_vars:
        sys.exit(f"modrinth: upstream variables changed ({old_vars} vs {new_vars}); review the patch")
    egg["scripts"]["installation"]["script"] = newer["scripts"]["installation"]["script"]


def patch_fill_script(egg, _upstream, egg_id):
    """Replace the install script with our Fill v3 installer."""
    inst = egg["scripts"]["installation"]
    if inst.get("entrypoint") != "ash" or "alpine" not in inst.get("container", ""):
        sys.exit(f"{egg_id}: expected an alpine/ash installer, got {inst.get('container')} / {inst.get('entrypoint')}")
    script = FILL_SCRIPT.read_text()
    script = script.replace("__PROJECT__", FILL_PROJECT[egg_id])
    inst["script"] = script


def patch_server_properties_url(egg, _upstream, egg_id):
    """Fetch server.properties from this repo instead of the archived parkervcp/eggs repo."""
    inst = egg["scripts"]["installation"]
    if OLD_PROPERTIES_URL not in inst["script"]:
        sys.exit(f"{egg_id}: archived server.properties URL not found; review the patch")
    inst["script"] = inst["script"].replace(OLD_PROPERTIES_URL, f"{RAW_BASE}/minecraft/java/server.properties")


# Runs before the upstream Zomboid startup on every boot (after any auto-update).
# 1. Java heap = 95% of the panel memory limit, written into ProjectZomboid64.json
#    (game updates reset that file, so it is reapplied each start; 0 = unlimited, skipped).
#    Wings adds 5% on top of the plan for the container hard limit (more on plans <= 4 GB),
#    so the JVM's non-heap memory has about 10% of the plan to work with.
# 2. MaxPlayers in the server ini set from the MAX_PLAYERS variable (ini exists after first boot).
# The image entrypoint runs `echo ${STARTUP}` and `eval` unquoted, so this text must not
# contain glob characters (* ? [ ]); build() refuses to write it if it does.
ZOMBOID_PREFIX = (
    'test "${SERVER_MEMORY:-0}" -gt 0 && test -f ProjectZomboid64.json && '
    'sed -i -E "s/-Xmx\\w+/-Xmx$(( SERVER_MEMORY - SERVER_MEMORY / 20 ))m/" ProjectZomboid64.json ; '
    'grep -q -- "-Xmx" ProjectZomboid64.json && echo "Java heap: $(grep -oE -- "-Xmx\\w+" ProjectZomboid64.json)" '
    '|| echo "WARNING: no -Xmx in ProjectZomboid64.json, heap not tied to panel memory" ; '
    'test -f ".cache/Server/${SERVER_NAME}.ini" && '
    'sed -i -E "s/^MaxPlayers=\\w+/MaxPlayers=${MAX_PLAYERS}/" ".cache/Server/${SERVER_NAME}.ini" && '
    'echo "Max players: ${MAX_PLAYERS}" ; '
)
ZOMBOID_UPSTREAM_START = 'export PATH="./jre64/bin:$PATH" ;'


def patch_zomboid_startup(egg, _upstream, egg_id):
    """Tie the Java heap to panel memory and apply MAX_PLAYERS on every start."""
    if not egg["startup"].startswith(ZOMBOID_UPSTREAM_START) or "./ProjectZomboid64" not in egg["startup"]:
        sys.exit(f"{egg_id}: upstream startup changed; review the patch")
    bad = set(ZOMBOID_PREFIX) & set("*?[]")
    if bad:
        sys.exit(f"{egg_id}: startup prefix contains glob characters {sorted(bad)}")
    egg["startup"] = ZOMBOID_PREFIX + egg["startup"]


def find_var(egg, env, egg_id):
    for v in egg["variables"]:
        if v["env_variable"] == env:
            return v
    sys.exit(f"{egg_id}: upstream variable {env} missing; review the patch")


def patch_zomboid_max_players(egg, _upstream, egg_id):
    """Upstream defines MAX_PLAYERS but never uses it. Make it a customer setting that works."""
    v = find_var(egg, "MAX_PLAYERS", egg_id)
    v.update({
        "description": "Maximum players. Applied to the server ini on every start, so change it here rather than in the ini.",
        "user_viewable": True,
        "user_editable": True,
        "rules": "required|integer|between:1,100",
    })


ZOMBOID_UPSTREAM_UDPPORT = "-udpport {{STEAM_PORT}}"
ZOMBOID_PORT_NAME = "Second UDP Port"
# Runs first on every boot. The container only knows its primary allocation, so the customer
# adds a second allocation in the Network tab and enters its port in STEAM_PORT. If it's empty
# or the same as the primary, stop with a bold red message. "\33\133" is ESC + "[" written in
# octal: the entrypoint's unquoted echo forbids a literal "[" (glob character), and the
# two-digit "\33" isn't decoded by the entrypoint's "echo -e" of the command line.
ZOMBOID_PORT_CHECK = (
    'test -n "${STEAM_PORT}" && test "${STEAM_PORT}" != "${SERVER_PORT}" || { '
    'printf "\\33\\1331;31mERROR: Project Zomboid needs a second port. '
    'Open the Network tab, click Create Allocation, enter the new port in Startup > '
    + ZOMBOID_PORT_NAME + ', then restart.\\33\\1330m\\n" ; exit 1 ; } ; '
    'echo "Ports: game UDP ${SERVER_PORT}, second UDP ${STEAM_PORT}" ; '
)


def patch_zomboid_steam_port(egg, _upstream, egg_id):
    """Second UDP port: customer adds an allocation and enters it; startup refuses if missing."""
    v = find_var(egg, "STEAM_PORT", egg_id)
    if egg["startup"].count(ZOMBOID_UPSTREAM_UDPPORT) != 1:
        sys.exit(f"{egg_id}: upstream startup port arguments changed; review the patch")
    bad = set(ZOMBOID_PORT_CHECK) & set("*?[]")
    if bad:
        sys.exit(f"{egg_id}: port check contains glob characters {sorted(bad)}")
    v.update({
        "name": ZOMBOID_PORT_NAME,
        "description": "Add an allocation in the Network tab, then enter its port here. "
                       "Must be different from the primary port.",
        "default_value": "",
        "user_viewable": True,
        "user_editable": True,
        "rules": "nullable|integer|between:1024,65535",
    })
    egg["startup"] = ZOMBOID_PORT_CHECK + egg["startup"]


FORGE_OLD_DETECT = """# Check if we need a symlink for 1.17+ Forge JPMS args
if [[ $MC_VERSION =~ ^1\\.(17|18|19|20|21|22|23) || $FORGE_VERSION =~ ^1\\.(17|18|19|20|21|22|23) ]]; then
  unix_args

# Check if someone has set MC to latest but overwrote it with older Forge version, otherwise we would have false positives
elif [[ $MC_VERSION == "latest" && $FORGE_VERSION =~ ^1\\.(17|18|19|20|21|22|23) ]]; then
  unix_args
else
  # For versions below 1.17 that ship with jar
  mv $FORGE_JAR $SERVER_JARFILE
fi"""

FORGE_NEW_DETECT = """# Forge 1.17+ writes libraries/net/minecraftforge/forge/<version>/unix_args.txt; older Forge ships a jar.
# Decide by what the installer produced, not by version number: Minecraft moved to 26.x versioning,
# which the old 1.17-1.23 regex sent down the old-jar branch, leaving neither file and an unbootable server.
if compgen -G "libraries/net/minecraftforge/forge/*/unix_args.txt" > /dev/null; then
  unix_args
elif compgen -G "$FORGE_JAR" > /dev/null; then
  # For versions below 1.17 that ship with jar
  mv $FORGE_JAR $SERVER_JARFILE
else
  echo -e "Install failed: Forge ${FORGE_VERSION} produced neither unix_args.txt nor ${FORGE_JAR}."
  exit 5
fi"""

FORGE_FIXES = [
    # the launch-file detection above
    (FORGE_OLD_DETECT, FORGE_NEW_DETECT),
    # a failed download exited 0, so the panel reported a successful install
    ('echo "!!! Error downloading forge version ${FORGE_VERSION} !!!"\n  exit\n',
     'echo "!!! Error downloading forge version ${FORGE_VERSION} !!!"\n  exit 1\n'),
    # failure message printed an undefined variable
    ("and Minecraft version ${MINECRAFT_VERSION}.", "and Minecraft version ${MC_VERSION}."),
]


def patch_forge_launch_detect(egg, _upstream, egg_id):
    """Set up the launch files by what the Forge installer produced, and fail loudly if neither exists."""
    inst = egg["scripts"]["installation"]
    script = inst["script"].replace("\r\n", "\n")
    for old, new in FORGE_FIXES:
        if old not in script:
            sys.exit(f"{egg_id}: upstream install script changed near {old.splitlines()[0][:60]!r}; review the patch")
        script = script.replace(old, new)
    inst["script"] = script


# Runs before the upstream Valheim startup on every boot (after any auto-update).
# 1. States the second port: Valheim always uses -port and -port + 1, and has no setting
#    for the second one, so both must be allocated to the server.
# 2. Warns (does not block) when the password appears in the world or server name.
#    Valheim refuses such passwords with "Error bad password" and exits; sources disagree
#    on which name it checks, so this only explains, and the game still decides.
# The image entrypoint runs `echo -e ${STARTUP}` then `eval` unquoted, so this text must
# not contain glob characters (* ? [ ]) or backslashes; the patch refuses to build if it does.
VALHEIM_PREFIX = (
    'echo "Valheim uses UDP ports ${SERVER_PORT} and $(( SERVER_PORT + 1 )). '
    'Both must be allocated to this server." ; '
    '{ printf %s "${WORLD}" | grep -qF -- "${PASSWORD}" || '
    'printf %s "${SERVER_NAME}" | grep -qF -- "${PASSWORD}" ; } && '
    'echo "WARNING: the server password appears in the world name or the server name. '
    'Valheim may refuse it and stop with: Error bad password. '
    'Change the password on the Startup page if the server does not start." ; '
)
VALHEIM_STEAMCMD_END = "cp -v linux64/steamclient.so ../.steam/sdk64/steamclient.so"

# Doorstop 4 launcher settings, exactly as start_server_bepinex.sh in the current BepInExPack
# and ValheimPlus releases sets them (both ship Doorstop 4.4.0).
DOORSTOP4_ENV = (
    'export DOORSTOP_ENABLED=1; '
    'export DOORSTOP_TARGET_ASSEMBLY=./BepInEx/core/BepInEx.Preloader.dll; '
    'export LD_LIBRARY_PATH="./doorstop_libs:$LD_LIBRARY_PATH"; '
    'export LD_PRELOAD="libdoorstop_x64.so:$LD_PRELOAD"; '
    'export LD_LIBRARY_PATH="./linux64:$LD_LIBRARY_PATH"; '
    'export SteamAppId=892970; '
)


def patch_valheim_startup(egg, _upstream, egg_id):
    """Show the two-port requirement and warn about passwords Valheim will refuse."""
    if "./valheim_server.x86_64" not in egg["startup"] or '"{{PASSWORD}}"' not in egg["startup"]:
        sys.exit(f"{egg_id}: upstream startup changed; review the patch")
    bad = set(VALHEIM_PREFIX) & set("*?[]\\")
    if bad:
        sys.exit(f"{egg_id}: startup prefix contains unsafe characters {sorted(bad)}")
    egg["startup"] = VALHEIM_PREFIX + egg["startup"]


def patch_valheim_password_text(egg, _upstream, egg_id):
    """Say up front which passwords Valheim refuses."""
    v = find_var(egg, "PASSWORD", egg_id)
    v["description"] = ("Server password, at least 5 characters. Must not appear inside the world name "
                        "or the server name, or Valheim refuses it and stops.")


def splice_valheim_install(egg, egg_id, script_path):
    """Keep upstream's SteamCMD install, replace everything after it with our script."""
    inst = egg["scripts"]["installation"]
    script = inst["script"].replace("\r\n", "\n")
    if script.count(VALHEIM_STEAMCMD_END) != 1:
        sys.exit(f"{egg_id}: SteamCMD end marker not found exactly once; review the patch")
    head = script.split(VALHEIM_STEAMCMD_END)[0] + VALHEIM_STEAMCMD_END + "\n\n"
    inst["script"] = head + script_path.read_text()


def patch_valheim_bepinex_install(egg, _upstream, egg_id):
    """Fail on errors, follow nested modpack dependencies, keep all mod files and configs."""
    splice_valheim_install(egg, egg_id, VALHEIM_BEPINEX_SCRIPT)


def patch_valheim_modpack_text(egg, _upstream, egg_id):
    v = find_var(egg, "V_MODPACK", egg_id)
    v["description"] = ("Thunderstore modpack to install, as Author-PackName (latest version) or "
                        "Author-PackName-1.2.3 (that version). Packs inside the pack are followed. "
                        "Leave blank for BepInEx only. Changing this needs a server reinstall; "
                        "it replaces BepInEx/plugins, and existing configs are kept.")


def patch_valheim_plus_doorstop(egg, _upstream, egg_id):
    """ValheimPlus now ships Doorstop 4, which ignores the Doorstop 3 settings upstream exports.
    Must run before valheim_startup, because it replaces everything before the server binary."""
    start = egg["startup"]
    cut = start.find("./valheim_server.x86_64")
    if cut < 0 or "DOORSTOP_INVOKE_DLL_PATH" not in start[:cut] or start.startswith(VALHEIM_PREFIX):
        sys.exit(f"{egg_id}: upstream startup no longer uses Doorstop 3 settings; review the patch")
    egg["startup"] = DOORSTOP4_ENV + start[cut:]


def patch_valheim_plus_install(egg, _upstream, egg_id):
    """Direct release download, fail on errors, keep configs."""
    splice_valheim_install(egg, egg_id, VALHEIM_PLUS_SCRIPT)


HYTALE_CONFIG_START = "echo '[2/2] Creating config.json...'\ncat > /mnt/server/Server/config.json << 'EOF'\n"
HYTALE_CONFIG_END = "EOF\necho '  ✓ config.json created'\n"


def patch_hytale_keep_config(egg, _upstream, egg_id):
    """Upstream rewrote Server/config.json on every install, so a reinstall reset the
    server name, password, player limit and view distance. Only create it when missing."""
    inst = egg["scripts"]["installation"]
    script = inst["script"].replace("\r\n", "\n")
    a = script.find(HYTALE_CONFIG_START)
    b = script.find(HYTALE_CONFIG_END, a)
    if a < 0 or b < 0 or script.count(HYTALE_CONFIG_START) != 1:
        sys.exit(f"{egg_id}: upstream config.json block changed; review the patch")
    heredoc = script[a + len("echo '[2/2] Creating config.json...'\n"):b + len("EOF\n")]
    new_block = ("if [ -f /mnt/server/Server/config.json ]; then\n"
                 "  echo '[2/2] Keeping existing config.json'\n"
                 "else\n"
                 "  echo '[2/2] Creating config.json...'\n"
                 + heredoc +
                 "  echo '  ✓ config.json created'\n"
                 "fi\n")
    inst["script"] = script[:a] + new_block + script[b + len(HYTALE_CONFIG_END):]


# Java heap = 92% of the panel memory. MaxRAMPercentage alone is measured against the
# container limit, which Wings sets 5-15% above the plan depending on size; -XX:MaxRAM
# makes the JVM size the heap from the plan itself, so 92% holds at every plan size.
# Memory 0 (unlimited) would give MaxRAM=0 and a 128 MB heap: Hytale servers need a set limit.
HYTALE_UPSTREAM_HEAP = "-XX:MaxRAMPercentage=95.0"
HYTALE_HEAP = "-XX:MaxRAM={{SERVER_MEMORY}}M -XX:MaxRAMPercentage=92.0"


def patch_hytale_heap(egg, _upstream, egg_id):
    """Heap = 92% of the plan, independent of Wings' container overhead."""
    if egg["startup"].count(HYTALE_UPSTREAM_HEAP) != 1 or "-jar HytaleServer.jar" not in egg["startup"]:
        sys.exit(f"{egg_id}: upstream startup memory flags changed; review the patch")
    egg["startup"] = egg["startup"].replace(HYTALE_UPSTREAM_HEAP, HYTALE_HEAP)


# Rust uses four ports: game (primary allocation), query (server browser), RCON and Rust+.
# Wings passes only the primary allocation into the container, so the other three are
# variables the customer fills in from allocations they add in the Network tab.
RUST_PORT_VARS = {
    "QUERY_PORT": ("Query Port", 1024,
                   "Allocation for the server browser query (UDP). Add an allocation in the Network tab and enter its port here. Required."),
    "RCON_PORT": ("RCON Port", 1024,
                  "Allocation for RCON (TCP), used by the panel console and remote admin tools. Add an allocation in the Network tab and enter its port here. Required."),
    "APP_PORT": ("Rust+ App Port", 10000,
                 "Allocation for the Rust+ companion app (TCP, 10000 or higher). Add an allocation in the Network tab and enter its port here. Required."),
}


def patch_rust_ports(egg, _upstream, egg_id):
    """Query, RCON and Rust+ ports become customer-entered; the startup check requires them.
    Rules are nullable so panel/store server creation works before the customer adds allocations."""
    for env, (name, low, desc) in RUST_PORT_VARS.items():
        v = find_var(egg, env, egg_id)
        v.update({"name": name, "description": desc, "default_value": "",
                  "user_viewable": True, "user_editable": True,
                  "rules": f"nullable|integer|between:{low},65535"})
        if "{{" + env + "}}" not in egg["startup"]:
            sys.exit(f"{egg_id}: upstream startup no longer uses {{{{{env}}}}}; review the patch")


def patch_rust_rcon_password(egg, _upstream, egg_id):
    """RCON is now always on an allocation, so it is reachable from the internet."""
    v = find_var(egg, "RCON_PASS", egg_id)
    if not v["rules"].startswith("required|regex:"):
        sys.exit(f"{egg_id}: upstream RCON_PASS rules changed; review the patch")
    v["rules"] = "required|regex:/^[\\w.-]*$/|min:8|max:64|not_in:CHANGEME,changeme"
    v["description"] = ("RCON password, 8 to 64 characters (letters, numbers, . _ -). RCON is reachable "
                        "from the internet on the RCON Port, so use a strong password. The server will "
                        "not start with an empty, short or CHANGEME password.")


def patch_rust_max_players(egg, _upstream, egg_id):
    """Plans are priced on CPU, memory and disk, not players."""
    find_var(egg, "MAX_PLAYERS", egg_id)["user_editable"] = True


# Runs first on every boot. The image's entrypoint runs `eval echo -e ${STARTUP}`, then its Node
# wrapper runs the result with /bin/sh (dash). So the added commands are one single-quoted block
# (eval passes it through untouched), use only shell builtins, and avoid glob characters (* ? [ ]),
# backslashes and apostrophes. It starts with `export LD_PRELOAD` because the entrypoint puts
# `LD_PRELOAD=...libdoorstop.so ` in front of the startup for Carbon; an assignment before the
# `export` builtin stays set and is exported, so it still reaches RustDedicated.
# On failure it stops the wrapper (kill $PPID): the wrapper otherwise waits for RCON forever and
# the panel would show the server as starting. The 1-second sleep lets the wrapper print the
# message first; LD_PRELOAD is cleared for it so Carbon's doorstop isn't injected into sleep.
RUST_CHECK = (
    "'export LD_PRELOAD ; "
    "rustfail() { echo \"ERROR: $1\" ; LD_PRELOAD= sleep 1 ; kill ${PPID} ; exit 1 ; } ; "
    "test -n \"${QUERY_PORT}\" && test -n \"${RCON_PORT}\" && test -n \"${APP_PORT}\" || "
    "rustfail \"Rust needs 4 ports. Open the Network tab, click Create Allocation until the server has 4, "
    "then enter the 3 new ports in Startup as Query Port, RCON Port and Rust+ App Port, and restart.\" ; "
    "test \"${QUERY_PORT}\" != \"${SERVER_PORT}\" && test \"${RCON_PORT}\" != \"${SERVER_PORT}\" && "
    "test \"${APP_PORT}\" != \"${SERVER_PORT}\" && test \"${QUERY_PORT}\" != \"${RCON_PORT}\" && "
    "test \"${QUERY_PORT}\" != \"${APP_PORT}\" && test \"${RCON_PORT}\" != \"${APP_PORT}\" || "
    "rustfail \"The game port, Query Port, RCON Port and Rust+ App Port must all be different allocations.\" ; "
    "test \"${#RCON_PASS}\" -ge 8 && test \"${RCON_PASS}\" != CHANGEME && test \"${RCON_PASS}\" != changeme || "
    "rustfail \"RCON Password must be at least 8 characters and not CHANGEME. Set it in Startup, then restart.\" ; "
    "echo \"Ports: game ${SERVER_PORT} UDP, query ${QUERY_PORT} UDP, RCON ${RCON_PORT} TCP, Rust+ ${APP_PORT} TCP\" ; ' "
)


def patch_rust_startup_checks(egg, _upstream, egg_id):
    if not egg["startup"].startswith("./RustDedicated "):
        sys.exit(f"{egg_id}: upstream startup no longer starts with ./RustDedicated; review the patch")
    inner = RUST_CHECK.strip()[1:-1]
    bad = set(inner) & set("*?[]\\'")
    if bad:
        sys.exit(f"{egg_id}: startup check contains unsafe characters {sorted(bad)}")
    egg["startup"] = RUST_CHECK + egg["startup"]


OPENMOD_URL = "https://github.com/openmod/openmod/releases/latest/download/OpenMod.Unturned.Module.zip"
UNTURNED_OLD_LINKS = ("ln -s ../../../steamcmd/linux64/steamclient.so Unturned_Headless_Data/Plugins/x86_64/steamclient.so\n"
                      "ln -s ../Extras/Rocket.Unturned/ Modules/\n")
UNTURNED_NEW_LINKS = f"""ln -sfn ../../../steamcmd/linux64/steamclient.so Unturned_Headless_Data/Plugins/x86_64/steamclient.so

## TeamCryptid eggs: the Framework setting (vanilla / ldm / openmod) is applied by the startup
## command, which links the chosen module into Modules/. LDM ships with the game in
## Extras/Rocket.Unturned; OpenMod is downloaded here into .openmod/ (outside Modules/).
echo "Downloading OpenMod module..."
rm -rf /mnt/server/.openmod.new && mkdir -p /mnt/server/.openmod.new
if curl -sfSL -o /tmp/openmod.zip {OPENMOD_URL} \\
   && unzip -q -o /tmp/openmod.zip -d /mnt/server/.openmod.new \\
   && [ -f /mnt/server/.openmod.new/OpenMod.Unturned/OpenMod.Unturned.module ]; then
    rm -rf /mnt/server/.openmod && mv /mnt/server/.openmod.new /mnt/server/.openmod
    echo "OpenMod module ready"
else
    rm -rf /mnt/server/.openmod.new
    if [ "${{FRAMEWORK}}" = "openmod" ]; then
        echo "ERROR: OpenMod download failed and Framework is openmod"
        exit 1
    fi
    echo "WARNING: OpenMod download failed (only needed for Framework openmod)"
fi
"""


def patch_unturned_install(egg, _upstream, egg_id):
    """Reinstall-safe links; Rocket link moved to startup; OpenMod module downloaded."""
    inst = egg["scripts"]["installation"]
    script = inst["script"].replace("\r\n", "\n")
    if script.count(UNTURNED_OLD_LINKS) != 1:
        sys.exit(f"{egg_id}: upstream install links changed; review the patch")
    inst["script"] = script.replace(UNTURNED_OLD_LINKS, UNTURNED_NEW_LINKS)


def patch_unturned_variables(egg, _upstream, egg_id):
    """Framework option, optional login token, password that may be empty or contain spaces."""
    g = find_var(egg, "GSLT", egg_id)
    g.update({"name": "Login Token (GSLT)", "rules": "nullable|string|max:64",
              "description": "Steam Game Server Login Token. Optional, but without one the server is hidden from "
                             "the internet server list and its Server Code changes every restart. Create one at "
                             "https://steamcommunity.com/dev/managegameservers with app ID 304930, one per server."})
    pw = find_var(egg, "SRV_PW", egg_id)
    pw.update({"rules": "nullable|string|max:64",
               "description": "Server password. Leave empty for no password."})
    if any(v["env_variable"] == "FRAMEWORK" for v in egg["variables"]):
        sys.exit(f"{egg_id}: upstream now has a FRAMEWORK variable; review the patch")
    egg["variables"].append({
        "name": "Framework",
        "description": "vanilla, ldm (Legally Distinct Missile, the RocketMod fork that ships with Unturned) "
                       "or openmod. Applied on restart. Servers installed before this option existed need one "
                       "reinstall before openmod works.",
        "env_variable": "FRAMEWORK", "default_value": "vanilla",
        "user_viewable": True, "user_editable": True,
        "rules": "required|string|in:vanilla,ldm,openmod", "field_type": "text"})


# Runs first on every boot. The SteamCMD image runs `echo ${STARTUP}` and `eval` unquoted, so
# this text avoids glob characters (* ? [ ]) and backslashes. It only ever removes symlinks in
# Modules/, never real folders a customer put there.
UNTURNED_PREFIX = (
    'mkdir -p Modules ; '
    'for m in Rocket.Unturned OpenMod.Unturned ; do test -L "Modules/$m" && rm -f "Modules/$m" ; done ; '
    'if test "${FRAMEWORK}" = ldm ; then '
    'if test ! -d Extras/Rocket.Unturned ; then echo "WARNING: Extras/Rocket.Unturned is missing, so LDM was not loaded. Reinstall the server." ; '
    'elif test -e Modules/Rocket.Unturned ; then echo "WARNING: Modules/Rocket.Unturned is a real folder, so the Framework setting leaves it alone." ; '
    'else ln -s ../Extras/Rocket.Unturned Modules/Rocket.Unturned ; fi ; fi ; '
    'if test "${FRAMEWORK}" = openmod ; then '
    'if test ! -d .openmod/OpenMod.Unturned ; then echo "WARNING: OpenMod is not downloaded yet, so it was not loaded. Reinstall the server once (Settings, Reinstall Server)." ; '
    'elif test -e Modules/OpenMod.Unturned ; then echo "WARNING: Modules/OpenMod.Unturned is a real folder, so the Framework setting leaves it alone." ; '
    'else ln -s ../.openmod/OpenMod.Unturned Modules/OpenMod.Unturned ; fi ; fi ; '
    'echo "Framework: ${FRAMEWORK}" ; '
    'echo "Unturned uses UDP ports ${SERVER_PORT} (server list) and $(( SERVER_PORT + 1 )) (game). '
    'Players can join through the server list without the second one; joining by IP needs both allocated to this server." ; '
    'test -n "${GSLT}" || echo "WARNING: No Login Token (GSLT) set. The server runs, but it is hidden from the internet '
    'server list and its Server Code changes every restart. Create one at steamcommunity.com/dev/managegameservers '
    '(app ID 304930) and enter it in Startup." ; '
)


def patch_unturned_startup(egg, _upstream, egg_id):
    """Framework links, port and token messages; pass -GSLT and -Password only when set, quoted."""
    st = egg["startup"]
    for old in ("-GSLT {{GSLT}}", "-Password {{SRV_PW}}"):
        if st.count(old) != 1:
            sys.exit(f"{egg_id}: upstream startup no longer has {old!r}; review the patch")
    if not st.startswith("./Unturned_Headless.x86_64 "):
        sys.exit(f"{egg_id}: upstream startup changed; review the patch")
    st = st.replace("-GSLT {{GSLT}}", '${GSLT:+-GSLT "${GSLT}"}')
    st = st.replace("-Password {{SRV_PW}}", '${SRV_PW:+-Password "${SRV_PW}"}')
    bad = set(UNTURNED_PREFIX) & set("*?[]\\")
    if bad:
        sys.exit(f"{egg_id}: startup prefix contains unsafe characters {sorted(bad)}")
    egg["startup"] = UNTURNED_PREFIX + st


def patch_vintagestory_install(egg, _upstream, egg_id):
    """Replace the install script: fail loudly, verify before replacing, block downgrades,
    record version and .NET major for the startup check."""
    inst = egg["scripts"]["installation"]
    old = inst["script"].replace("\r\n", "\n")
    for marker in ("api.vintagestory.at", "vs_server_linux-x64_", "rm -rf assets/"):
        if marker not in old:
            sys.exit(f"{egg_id}: upstream install script changed ({marker!r} missing); review the patch")
    if inst.get("entrypoint") != "bash" or "debian" not in inst.get("container", ""):
        sys.exit(f"{egg_id}: expected a debian/bash installer, got {inst.get('container')} / {inst.get('entrypoint')}")
    inst["script"] = VINTAGESTORY_SCRIPT.read_text()


def patch_vintagestory_variables(egg, _upstream, egg_id):
    for env in ("FILES_BRANCH", "RELEASE_VERSION", "MAX_CLIENTS"):
        find_var(egg, env, egg_id)
    find_var(egg, "FILES_BRANCH", egg_id)["description"] = (
        "stable, unstable or pre. Note: unstable can be older than stable (between release cycles), "
        "and the install refuses to downgrade. Changing this needs a reinstall.")
    find_var(egg, "RELEASE_VERSION", egg_id)["description"] = (
        "latest, or an exact version such as 1.22.7 (required for the pre branch). Changing this needs a "
        "reinstall. Versions older than the installed one are refused unless staff turn on Allow Downgrade.")
    if any(v["env_variable"] == "ALLOW_DOWNGRADE" for v in egg["variables"]):
        sys.exit(f"{egg_id}: upstream now has ALLOW_DOWNGRADE; review the patch")
    egg["variables"].append({
        "name": "Allow Downgrade",
        "description": "Staff only. 1 lets the next reinstall install an older version than the installed one. "
                       "Downgrading can damage worlds: take a backup first, and set this back to 0 afterwards.",
        "env_variable": "ALLOW_DOWNGRADE", "default_value": "0",
        "user_viewable": True, "user_editable": False,
        "rules": "required|boolean", "field_type": "text"})


def dotnet_prefix(game, marker):
    """Startup prefix for .NET game servers (Vintage Story, TShock, tModLoader). Runs first on
    every boot. The .NET images run `echo -e ${STARTUP}` then `eval` unquoted, so this text
    avoids glob characters (* ? [ ]) and backslashes; 92% is m - 2m/25 and MB to bytes is << 20,
    so no `*` is needed.
    1. .NET GC heap limit = 92% of the panel memory (DOTNET_GCHeapHardLimit, hex bytes). Without
       it .NET uses 75% of the container limit. Memory 0 (unlimited) leaves .NET's default.
    2. If the installed version needs a different .NET than this image has, stop with a message
       naming the image to pick (the install writes the needed major version to <marker>-dotnet
       and the installed version to <marker>-version)."""
    return (
        'test "${SERVER_MEMORY:-0}" -gt 0 && '
        'export DOTNET_GCHeapHardLimit=$(printf %x $(( (SERVER_MEMORY - (SERVER_MEMORY + SERVER_MEMORY) / 25) << 20 ))) && '
        'echo "Memory: .NET heap limit $(( SERVER_MEMORY - (SERVER_MEMORY + SERVER_MEMORY) / 25 )) MB, 92 percent of ${SERVER_MEMORY} MB" ; '
        f'if test -f {marker}-dotnet && ! dotnet --list-runtimes 2>/dev/null | grep -q "Microsoft.NETCore.App $(cat {marker}-dotnet)." ; then '
        f'echo "ERROR: {game} $(cat {marker}-version 2>/dev/null) needs .NET $(cat {marker}-dotnet), which this Docker image does not have. '
        f'Choose the Dotnet $(cat {marker}-dotnet) image under Startup, Docker Image, then restart." ; exit 1 ; fi ; '
    )


def add_prefix(egg, egg_id, prefix, starts_with):
    """Put a startup prefix in front of upstream's command, after checking both."""
    if not egg["startup"].startswith(starts_with):
        sys.exit(f"{egg_id}: upstream startup no longer starts with {starts_with!r}; review the patch")
    bad = set(prefix) & set("*?[]\\")
    if bad:
        sys.exit(f"{egg_id}: startup prefix contains unsafe characters {sorted(bad)}")
    egg["startup"] = prefix + egg["startup"]


def patch_vintagestory_startup(egg, _upstream, egg_id):
    add_prefix(egg, egg_id, dotnet_prefix("Vintage Story", ".vs"), "./VintagestoryServer ")


def replace_install(egg, egg_id, script_path, markers):
    """Replace upstream's whole install script with ours, after checking upstream still
    looks like the script we reviewed and still runs on a debian/bash installer."""
    inst = egg["scripts"]["installation"]
    old = inst["script"].replace("\r\n", "\n")
    for marker in markers:
        if marker not in old:
            sys.exit(f"{egg_id}: upstream install script changed ({marker!r} missing); review the patch")
    if inst.get("entrypoint") not in ("bash", "/bin/bash") or "debian" not in inst.get("container", ""):
        sys.exit(f"{egg_id}: expected a debian/bash installer, got {inst.get('container')} / {inst.get('entrypoint')}")
    inst["entrypoint"] = "bash"
    inst["script"] = script_path.read_text()


def set_dotnet_images(egg, egg_id, expected, majors):
    """Image list for a .NET egg: majors[0] is the default. `expected` is upstream's list,
    so the build stops if upstream changes its images."""
    if egg["docker_images"] != expected:
        sys.exit(f"{egg_id}: upstream docker images changed to {egg['docker_images']}; review the patch")
    egg["docker_images"] = {f"Dotnet {m}": f"ghcr.io/parkervcp/yolks:dotnet_{m}" for m in majors}


def update_var(egg, egg_id, env, **fields):
    find_var(egg, env, egg_id).update(fields)


def add_var(egg, egg_id, env, name, description, default, rules, editable=True):
    if any(v["env_variable"] == env for v in egg["variables"]):
        sys.exit(f"{egg_id}: upstream now has {env}; review the patch")
    egg["variables"].append({
        "name": name, "description": description, "env_variable": env, "default_value": default,
        "user_viewable": True, "user_editable": editable, "rules": rules, "field_type": "text"})


def remove_var(egg, egg_id, env):
    find_var(egg, env, egg_id)
    egg["variables"] = [v for v in egg["variables"] if v["env_variable"] != env]


# --- Terraria (vanilla) ---------------------------------------------------------

def patch_terraria_install(egg, _upstream, egg_id):
    replace_install(egg, egg_id, TERRARIA_SCRIPT,
                    ("terraria.org/api/get/dedicated-servers-names", "TerrariaServer.bin.x86_64", "serverconfig.txt"))


def patch_terraria_variables(egg, _upstream, egg_id):
    update_var(egg, egg_id, "TERRARIA_VERSION", description=(
        "latest, or an exact version such as 1.4.4.9 (or 1449). Changing this needs a reinstall."))
    v = find_var(egg, egg_id=egg_id, env="WORLD_DIFFICULTY")
    if v["default_value"] != "3":
        sys.exit(f"{egg_id}: upstream WORLD_DIFFICULTY default changed; review the patch")
    v["default_value"] = "0"
    v["description"] = ("Difficulty of a newly created world: 0 normal, 1 expert, 2 master, 3 journey. "
                        "An existing world keeps its difficulty.")


# --- TShock ----------------------------------------------------------------------

def patch_tshock_install(egg, _upstream, egg_id):
    replace_install(egg, egg_id, TSHOCK_SCRIPT, ("Pryaxis/TShock", "TShock.Server"))


def patch_tshock_images(egg, _upstream, egg_id):
    """TShock 6 needs .NET 9 (upstream's default image was .NET 6, which can't run it);
    TShock 5 needs .NET 6; TShock has announced .NET 10 next."""
    set_dotnet_images(egg, egg_id, {"Dotnet 6": "ghcr.io/parkervcp/yolks:dotnet_6",
                                    "Dotnet 9": "ghcr.io/parkervcp/yolks:dotnet_9"}, [9, 10, 6])


def patch_tshock_variables(egg, _upstream, egg_id):
    update_var(egg, egg_id, "MAX_PLAYERS", user_editable=True)
    update_var(egg, egg_id, "WORLD_SIZE", user_editable=True, rules="required|integer|in:1,2,3",
               description="Size of a newly created world: 1 small, 2 medium, 3 large. An existing world keeps its size.")
    update_var(egg, egg_id, "TSHOCK_VERSION", description=(
        "latest (newest non-pre-release), or a release tag such as v6.2.1. Changing this needs a reinstall. "
        "TShock 6 needs the Dotnet 9 image, TShock 5 the Dotnet 6 image."))


def patch_tshock_startup(egg, _upstream, egg_id):
    add_prefix(egg, egg_id, dotnet_prefix("TShock", ".tshock"), "./TShock.Server ")


# --- tModLoader --------------------------------------------------------------------

TML_WORKSHOP_ARG = " -steamworkshopfolder ~/steamapps/workshop"


def patch_tmodloader_install(egg, _upstream, egg_id):
    replace_install(egg, egg_id, TMODLOADER_SCRIPT, ("tmodloader/tmodloader/releases", "tModLoader.dll"))


def patch_tmodloader_images(egg, _upstream, egg_id):
    """tModLoader for Terraria 1.4.4 needs .NET 8; 2022-era builds .NET 6."""
    set_dotnet_images(egg, egg_id, {"Dotnet 8": "ghcr.io/parkervcp/yolks:dotnet_8",
                                    "Dotnet 6": "ghcr.io/parkervcp/yolks:dotnet_6"}, [8, 10, 6])


def patch_tmodloader_variables(egg, _upstream, egg_id):
    update_var(egg, egg_id, "MAX_PLAYERS", user_editable=True)
    update_var(egg, egg_id, "VERSION", description=(
        "latest, or a release tag such as v2026.08.3.0. Changing this needs a reinstall."))
    # The install no longer uses the GitHub API (and upstream's token never took effect).
    remove_var(egg, egg_id, "GITHUB_USER")
    remove_var(egg, egg_id, "GITHUB_OAUTH_TOKEN")
    add_var(egg, egg_id, "WORKSHOP_MODS", "Workshop Mods",
            "Steam Workshop IDs of tModLoader mods, separated by commas (the number at the end of the mod's "
            "Workshop page address). They are downloaded and enabled when the server is reinstalled; "
            "reinstall again to update them. IDs removed from the list are deleted and disabled.",
            "", "nullable|regex:/^[0-9 ,]*$/|max:2000")


def patch_tmodloader_startup(egg, _upstream, egg_id):
    if TML_WORKSHOP_ARG.strip() in egg["startup"]:
        sys.exit(f"{egg_id}: upstream startup already has -steamworkshopfolder; review the patch")
    add_prefix(egg, egg_id, dotnet_prefix("tModLoader", ".tml"), "./tModLoaderServer ")
    egg["startup"] += TML_WORKSHOP_ARG


# --- Factorio ------------------------------------------------------------------------

FACTORIO_UPSTREAM_STARTUP = (
    '[ ! -f "./saves/{{SAVE_NAME}}.zip" ] && ./bin/x64/factorio --create ./saves/{{SAVE_NAME}}.zip '
    '--map-gen-settings data/map-gen-settings.json --map-settings data/map-settings.json; '
    './bin/x64/factorio --port {{SERVER_PORT}} --server-settings data/server-settings.json '
    '--start-server saves/{{SAVE_NAME}}.zip $( [ "$RCON_ENABLED" = "1" ] && echo "--rcon-port {{RCON_PORT}} '
    '--rcon-password {{RCON_PASSWORD}}" )'
)
FACTORIO_DLC = ("elevated-rails", "quality", "recycler", "space-age")   # "expansion_required" in data/*/info.json

# Replaces upstream's startup. The image runs `echo -e ${STARTUP}` then `eval` unquoted, so it
# avoids glob characters (* ? [ ]) and backslashes (awk builds [ ] with %c 91/93), and "}}",
# which the entrypoint rewrites. Order:
#  1. Space Age guard: a save that has run with Space Age is not started with it off (Factorio
#     would strip the DLC content from it). The marker file is written in step 6.
#  2. RCON: when on, RCON Port must be set and differ from the game port, password >= 8.
#  3. mods/mod-list.json: created if missing, DLC mods switched on/off to match Space Age.
#  4. Warn when there's no factorio.com login (the server then isn't in the public list).
#  5. Create the save on first start, now that the Space Age setting is applied.
#  6. Mark the save as played with Space Age, then start.
FACTORIO_STARTUP = (
    'if test "${SPACE_AGE}" != 1 && test -f "saves/${SAVE_NAME}.space-age" ; then '
    'echo "ERROR: The save ${SAVE_NAME} has been played with Space Age. Starting it with Space Age off removes the '
    'Space Age content (planets, buildings, items) from the save permanently. Turn Space Age back on in Startup. '
    'To remove it anyway, back up the save, delete saves/${SAVE_NAME}.space-age, then restart." ; exit 1 ; fi ; '
    'if test "${RCON_ENABLED}" = 1 ; then '
    'test -n "${RCON_PORT}" && test "${RCON_PORT}" != "${SERVER_PORT}" || { echo "ERROR: RCON is on, but RCON Port is '
    'empty or the same as the game port. Open the Network tab, click Create Allocation, enter the new port in Startup '
    'as RCON Port, then restart." ; exit 1 ; } ; '
    'test "${#RCON_PASSWORD}" -ge 8 || { echo "ERROR: RCON is on, so RCON Password must be at least 8 characters. '
    'Set it in Startup, then restart." ; exit 1 ; } ; '
    'set -- --rcon-port "${RCON_PORT}" --rcon-password "${RCON_PASSWORD}" ; '
    'echo "Ports: game ${SERVER_PORT} UDP, RCON ${RCON_PORT} TCP" ; '
    'else set -- ; echo "Ports: game ${SERVER_PORT} UDP" ; fi ; '
    'mkdir -p mods saves ; '
    'FDLC=$(test "${SPACE_AGE}" = 1 && echo true || echo false) ; '
    'test -f mods/mod-list.json || awk -v on=${FDLC} '
    "'function e(n, v) {printf \"%s{%sname%s: %s%s%s, %senabled%s: %s}%c\", s, q, q, q, n, q, q, q, v, 10 ; s = \", \"} "
    "BEGIN {q = sprintf(\"%c\", 34) ; printf \"{%smods%s: %c%c\", q, q, 91, 10 ; "
    + " ; ".join(['e("base", "true")'] + [f'e("{m}", on)' for m in FACTORIO_DLC]) +
    " ; printf \"%c}%c\", 93, 10}' > mods/mod-list.json ; "
    "awk -v on=${FDLC} '/\"name\"/ {d = ($0 ~ /\"(" + "|".join(FACTORIO_DLC) + ")\"/)} "
    "d && /\"enabled\"/ {sub(/true|false/, on) ; d = 0} {print}' mods/mod-list.json > mods/mod-list.json.new && "
    'mv -f mods/mod-list.json.new mods/mod-list.json ; '
    'if test "${FDLC}" = true ; then echo "Space Age: on. Players need the Space Age expansion to join." ; '
    'else echo "Space Age: off." ; fi ; '
    'test -n "${SERVER_USERNAME}" && test -n "${SERVER_TOKEN}" || echo "WARNING: No factorio.com username and token '
    'set, so the server is not in the public server list. Players can still join by address. Enter both in Startup '
    '(the token is on factorio.com/profile)." ; '
    'if test ! -f "saves/${SAVE_NAME}.zip" ; then ./bin/x64/factorio --create "saves/${SAVE_NAME}.zip" '
    '--map-gen-settings data/map-gen-settings.json --map-settings data/map-settings.json || exit 1 ; fi ; '
    'test "${FDLC}" = true && test -d data/space-age && touch "saves/${SAVE_NAME}.space-age" ; '
    './bin/x64/factorio --port ${SERVER_PORT} --server-settings data/server-settings.json '
    '--start-server "saves/${SAVE_NAME}.zip" "$@"'
)


def patch_factorio_install(egg, _upstream, egg_id):
    replace_install(egg, egg_id, FACTORIO_SCRIPT,
                    ("factorio.com/api/latest-releases", "get-download", "map-settings.example.json"))


def patch_factorio_variables(egg, _upstream, egg_id):
    update_var(egg, egg_id, "MAX_SLOTS", user_editable=True)
    update_var(egg, egg_id, "FACTORIO_VERSION", description=(
        "latest (newest stable), experimental, or an exact version such as 2.0.72. Changing this needs a reinstall."))
    update_var(egg, egg_id, "SERVER_USERNAME", default_value="", rules="nullable|string|max:40",
               description="Your factorio.com username. With the token below, it puts the server in the public "
                           "server list. Leave both empty for a server players join by address.")
    update_var(egg, egg_id, "SERVER_TOKEN", default_value="", rules="nullable|alpha_num|max:100",
               description="Your factorio.com token (on factorio.com/profile). Needed with the username for the "
                           "public server list.")
    update_var(egg, egg_id, "RCON_ENABLED", name="RCON Enabled",
               description="1 turns on RCON (remote console, TCP). Needs RCON Port and RCON Password.")
    update_var(egg, egg_id, "RCON_PORT", name="RCON Port", rules="nullable|integer|between:1024,65535",
               description="Only when RCON is on: add an allocation in the Network tab and enter its port here.")
    update_var(egg, egg_id, "RCON_PASSWORD", name="RCON Password", rules="nullable|string|max:64",
               description="Only when RCON is on: at least 8 characters. RCON is reachable from the internet on "
                           "the RCON Port, so use a strong password.")
    add_var(egg, egg_id, "SPACE_AGE", "Space Age",
            "1 turns on the Space Age expansion (with Quality and Elevated Rails); players then need Space Age "
            "to join. 0 turns it off so anyone with Factorio can join. Applied on restart. A save that has been "
            "played with Space Age won't start with it off, because that would remove the Space Age content.",
            "1", "required|boolean")


# --- 7 Days to Die --------------------------------------------------------------------

SDTD_UPSTREAM_STARTUP = (
    './7DaysToDieServer.x86_64 -configfile=serverconfig.xml -quit -batchmode -nographics -dedicated '
    '-ServerPort=${SERVER_PORT} -ServerDisabledNetworkProtocols=${SERVER_DISABLED_NETWORK_PROTOCOLS} '
    '-ServerMaxPlayerCount=${MAX_PLAYERS} -GameDifficulty=${GAME_DIFFICULTY} -ControlPanelEnabled=false '
    '-TelnetEnabled=true -TelnetPort=${TELNET_PORT} -TelnetPassword=${PASSWORD} -logfile logs/latest.log & '
    'echo -e "Checking on telnet connection" && until nc -z -v -w5 127.0.0.1 ${TELNET_PORT}; do echo "Waiting for '
    'telnet connection..."; sleep 5; done && $( [[ -z ${PASSWORD} ]] && printf %s "telnet -E 127.0.0.1 ${TELNET_PORT}" '
    '|| printf %s "rcon -t telnet -a 127.0.0.1:${TELNET_PORT} -p {{PASSWORD}}" )'
)
SDTD_CONFIG = "serverconfig.custom.xml"
SDTD_INSTALL_END = "## install end\n"
SDTD_INSTALL_CHECK = """## TeamCryptid eggs: fail the install when SteamCMD didn't install the game
## (upstream always printed "Installation completed").
if [ ! -f /mnt/server/7DaysToDieServer.x86_64 ] || [ ! -f /mnt/server/serverconfig.xml ]; then
    echo "-----------------------------------------"
    echo "Installation failed: SteamCMD did not install 7 Days to Die. Check the SteamCMD output above"
    echo "(disk space, a Steam outage, or a wrong Beta Branch name)."
    echo "-----------------------------------------"
    exit 1
fi

"""

# Replaces upstream's startup. The SteamCMD image runs `echo ${STARTUP}` then `eval` unquoted, so
# this avoids glob characters (* ? [ ]), backslashes, and "}}" (which the entrypoint rewrites).
#  1. Run from serverconfig.custom.xml, created from the game's serverconfig.xml on first start.
#     Steam replaces serverconfig.xml on reinstall (validate) and on updates that change it.
#  2. Port line: the game uses its port and the UDP ports up to +3 (staff assign the block).
#  3. Optional Web Dashboard on a customer-entered allocation, checked against the game ports.
#  4. Optional SandboxCode (V3 moved difficulty and ~30 gameplay settings into it).
#  5. Telnet stays on loopback: -TelnetPassword= is always empty (the game then listens on
#     127.0.0.1 only, whatever the config file says). The panel console is a telnet session.
#  6. If the game exits before its console opens, stop with an error instead of waiting forever.
#     If the console session ends while the game runs (someone typed exit), reconnect.
#     When the game exits (shutdown), exit with its code.
SDTD_STARTUP = (
    f'CFG={SDTD_CONFIG} ; '
    'if test ! -f "${CFG}" ; then '
    'test -f serverconfig.xml || { echo "ERROR: serverconfig.xml is missing. Reinstall the server." ; exit 1 ; } ; '
    'cp serverconfig.xml "${CFG}" && echo "Created ${CFG} from the game default. Edit ${CFG} for your settings: '
    'Steam replaces serverconfig.xml on updates and reinstalls." ; fi ; '
    'echo "Config: ${CFG}" ; '
    'echo "Ports: 7 Days to Die uses ${SERVER_PORT} (TCP and UDP) and UDP $(( SERVER_PORT + 1 )) to '
    '$(( SERVER_PORT + 3 )). All four must be allocated to this server." ; '
    'set -- ; '
    'if test -n "${WEB_DASHBOARD_PORT}" ; then '
    'if test "${WEB_DASHBOARD_PORT}" -ge "${SERVER_PORT}" && test "${WEB_DASHBOARD_PORT}" -le $(( SERVER_PORT + 3 )) || '
    'test "${WEB_DASHBOARD_PORT}" = "${TELNET_PORT}" ; then '
    'echo "ERROR: Web Dashboard Port ${WEB_DASHBOARD_PORT} clashes with the game ports ${SERVER_PORT} to '
    '$(( SERVER_PORT + 3 )). Open the Network tab, click Create Allocation, enter the new port as Web Dashboard '
    'Port, then restart." ; exit 1 ; fi ; '
    'set -- -WebDashboardEnabled=true -WebDashboardPort=${WEB_DASHBOARD_PORT} ; '
    'echo "Web Dashboard: on, TCP port ${WEB_DASHBOARD_PORT}" ; '
    'else set -- -WebDashboardEnabled=false ; fi ; '
    'if test -n "${SANDBOX_CODE}" ; then set -- "$@" -SandboxCode=${SANDBOX_CODE} ; echo "Sandbox Code: from Startup" ; '
    'else echo "Sandbox Code: from ${CFG}" ; fi ; '
    'mkdir -p logs ; '
    './7DaysToDieServer.x86_64 -configfile="${CFG}" -quit -batchmode -nographics -dedicated '
    '-ServerPort=${SERVER_PORT} -ServerDisabledNetworkProtocols=${SERVER_DISABLED_NETWORK_PROTOCOLS} '
    '-ServerMaxPlayerCount=${MAX_PLAYERS} -TelnetEnabled=true -TelnetPort=${TELNET_PORT} -TelnetPassword= '
    '"$@" -logfile logs/latest.log & '
    'GAME=$! ; '
    'echo "Waiting for the game console..." ; '
    'until nc -z 127.0.0.1 ${TELNET_PORT} 2>/dev/null ; do '
    'kill -0 ${GAME} 2>/dev/null || { wait ${GAME} ; echo "ERROR: 7 Days to Die exited before its '
    'console opened. See logs/latest.log in the file manager." ; exit 1 ; } ; sleep 2 ; done ; '
    'while kill -0 ${GAME} 2>/dev/null ; do '
    'nc -z 127.0.0.1 ${TELNET_PORT} 2>/dev/null && telnet -E 127.0.0.1 ${TELNET_PORT} ; sleep 1 ; done ; '
    'wait ${GAME}'
)


def patch_7dtd_install(egg, _upstream, egg_id):
    inst = egg["scripts"]["installation"]
    script = inst["script"].replace("\r\n", "\n")
    if script.count(SDTD_INSTALL_END) != 1 or "+app_update ${SRCDS_APPID}" not in script:
        sys.exit(f"{egg_id}: upstream install script changed; review the patch")
    inst["script"] = script.replace(SDTD_INSTALL_END, SDTD_INSTALL_CHECK + SDTD_INSTALL_END)


def patch_7dtd_variables(egg, _upstream, egg_id):
    update_var(egg, egg_id, "MAX_PLAYERS", user_editable=True, rules="required|integer|between:1,100",
               description="Maximum players at once.")
    # V3 moved GameDifficulty into SandboxCode; the telnet console stays on loopback (no password).
    remove_var(egg, egg_id, "GAME_DIFFICULTY")
    remove_var(egg, egg_id, "PASSWORD")
    update_var(egg, egg_id, "TELNET_PORT", user_editable=False, rules="required|integer|between:1024,65535",
               description="Internal port of the game's telnet console, which the panel console uses. It only "
                           "listens inside the server (no password), so it needs no allocation.")
    add_var(egg, egg_id, "SANDBOX_CODE", "Sandbox Code",
            "Game rules as a code from the in-game Sandbox Options menu (V3 replaced Game Difficulty and most "
            "gameplay settings with it). Leave empty to use SandboxCode from serverconfig.custom.xml. "
            "Applied on restart.", "", "nullable|regex:/^[A-Za-z0-9]*$/|max:1000")
    add_var(egg, egg_id, "WEB_DASHBOARD_PORT", "Web Dashboard Port",
            "Optional. To turn on the built-in Web Dashboard (admin pages and live map, TCP), add an allocation "
            "in the Network tab and enter its port here, then restart. Leave empty to keep it off.",
            "", "nullable|integer|between:1024,65535")


def patch_7dtd_startup(egg, _upstream, egg_id):
    if egg["startup"] != SDTD_UPSTREAM_STARTUP:
        sys.exit(f"{egg_id}: upstream startup changed; review the patch")
    bad = set(SDTD_STARTUP) & set("*?[]\\")
    if bad or "}}" in SDTD_STARTUP:
        sys.exit(f"{egg_id}: startup contains unsafe characters {sorted(bad)} or '}}}}'")
    egg["startup"] = SDTD_STARTUP


def patch_factorio_startup(egg, _upstream, egg_id):
    if egg["startup"] != FACTORIO_UPSTREAM_STARTUP:
        sys.exit(f"{egg_id}: upstream startup changed; review the patch")
    bad = set(FACTORIO_STARTUP) & set("*?[]\\")
    if bad or "}}" in FACTORIO_STARTUP:
        sys.exit(f"{egg_id}: startup contains unsafe characters {sorted(bad)} or '}}}}'")
    egg["startup"] = FACTORIO_STARTUP


PATCHES = {
    "java25": patch_java25,
    "modrinth_script": patch_modrinth_script,
    "fill_script": patch_fill_script,
    "server_properties_url": patch_server_properties_url,
    "forge_launch_detect": patch_forge_launch_detect,
    "zomboid_startup": patch_zomboid_startup,
    "zomboid_max_players": patch_zomboid_max_players,
    "zomboid_steam_port": patch_zomboid_steam_port,
    "valheim_startup": patch_valheim_startup,
    "valheim_password_text": patch_valheim_password_text,
    "valheim_bepinex_install": patch_valheim_bepinex_install,
    "valheim_modpack_text": patch_valheim_modpack_text,
    "valheim_plus_doorstop": patch_valheim_plus_doorstop,
    "valheim_plus_install": patch_valheim_plus_install,
    "hytale_keep_config": patch_hytale_keep_config,
    "hytale_heap": patch_hytale_heap,
    "rust_ports": patch_rust_ports,
    "rust_rcon_password": patch_rust_rcon_password,
    "rust_max_players": patch_rust_max_players,
    "rust_startup_checks": patch_rust_startup_checks,
    "unturned_install": patch_unturned_install,
    "unturned_variables": patch_unturned_variables,
    "unturned_startup": patch_unturned_startup,
    "vintagestory_install": patch_vintagestory_install,
    "vintagestory_variables": patch_vintagestory_variables,
    "vintagestory_startup": patch_vintagestory_startup,
    "terraria_install": patch_terraria_install,
    "terraria_variables": patch_terraria_variables,
    "tshock_install": patch_tshock_install,
    "tshock_images": patch_tshock_images,
    "tshock_variables": patch_tshock_variables,
    "tshock_startup": patch_tshock_startup,
    "tmodloader_install": patch_tmodloader_install,
    "tmodloader_images": patch_tmodloader_images,
    "tmodloader_variables": patch_tmodloader_variables,
    "tmodloader_startup": patch_tmodloader_startup,
    "factorio_install": patch_factorio_install,
    "factorio_variables": patch_factorio_variables,
    "factorio_startup": patch_factorio_startup,
    "7dtd_install": patch_7dtd_install,
    "7dtd_variables": patch_7dtd_variables,
    "7dtd_startup": patch_7dtd_startup,
}


def main():
    ap = argparse.ArgumentParser(description="build.py")
    for name, url in UPSTREAMS.items():
        ap.add_argument(f"--{name}", type=pathlib.Path, required=True, help=f"path to a {url} checkout")
    args = ap.parse_args()
    upstreams = {name: getattr(args, name).resolve() for name in UPSTREAMS}

    def git(path, *cmd):
        return subprocess.run(["git", "-C", str(path), *cmd],
                              capture_output=True, text=True, check=True).stdout.strip()

    lock_eggs = []
    for egg_id, up, src, dest, patches in EGGS:
        upstream = upstreams[up]
        src_path = upstream / src
        egg = json.loads(src_path.read_text())
        if egg.get("meta", {}).get("version") != "PTDL_v2":
            sys.exit(f"{egg_id}: upstream file is {egg.get('meta', {}).get('version')}, not PTDL_v2")

        for name in patches:
            PATCHES[name](egg, upstream, egg_id)

        egg["meta"]["update_url"] = f"{RAW_BASE}/{dest}"

        out = ROOT / dest
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(egg, indent=4, ensure_ascii=False) + "\n")
        lock_eggs.append({"id": egg_id, "upstream": up, "upstream_path": src, "upstream_sha256": sha256(src_path),
                          "path": dest, "patches": patches})
        print(f"built {dest}  patches={patches or 'none'}")

    for up, src, dest in ASSETS:
        out = ROOT / dest
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstreams[up] / src, out)
        print(f"copied {dest}")

    lock = {
        "upstreams": {
            name: {"repo": url, "commit": git(upstreams[name], "rev-parse", "HEAD"),
                   "commit_date": git(upstreams[name], "log", "-1", "--format=%cI")}
            for name, url in UPSTREAMS.items()
        },
        "built": datetime.date.today().isoformat(),
        "eggs": lock_eggs,
    }
    (ROOT / "upstream.lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    print("wrote upstream.lock.json (" + ", ".join(
        f"{n} {v['commit'][:7]}" for n, v in lock["upstreams"].items()) + ")")


if __name__ == "__main__":
    main()
