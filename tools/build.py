#!/usr/bin/env python3
"""build.py - TeamCryptid eggs

Builds the curated egg set from upstream pelican-eggs checkouts.
Every change we make to upstream eggs lives in this file, so a resync is:

    git clone https://github.com/pelican-eggs/minecraft.git /tmp/minecraft
    git clone https://github.com/pelican-eggs/games-steamcmd.git /tmp/steamcmd
    python3 tools/build.py --minecraft /tmp/minecraft --steamcmd /tmp/steamcmd
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
}
RAW_BASE = "https://raw.githubusercontent.com/TeamCryptid/eggs/main"
JAVA25_IMAGE = "ghcr.io/pelican-eggs/yolks:java_25"

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILL_SCRIPT = ROOT / "tools" / "scripts" / "fill-install.sh"

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
ZOMBOID_UDPPORT = "-udpport $(( SERVER_PORT + 1 ))"
# Printed on every boot. The container can't see which allocations exist, so this is a reminder.
ZOMBOID_PORT_NOTICE = (
    'echo "Ports: UDP ${SERVER_PORT} and UDP $(( SERVER_PORT + 1 )). '
    'Both must be allocations on this server or players cannot connect." ; '
)


def patch_zomboid_steam_port(egg, _upstream, egg_id):
    """Ports come from allocations only: second UDP port = primary allocation + 1, no variable."""
    find_var(egg, "STEAM_PORT", egg_id)
    if egg["startup"].count(ZOMBOID_UPSTREAM_UDPPORT) != 1 or egg["startup"].count(ZOMBOID_UPSTREAM_START) != 1:
        sys.exit(f"{egg_id}: upstream startup port arguments changed; review the patch")
    bad = set(ZOMBOID_PORT_NOTICE + ZOMBOID_UDPPORT) & set("*?[]")
    if bad:
        sys.exit(f"{egg_id}: port patch contains glob characters {sorted(bad)}")
    egg["startup"] = (egg["startup"]
                      .replace(ZOMBOID_UPSTREAM_UDPPORT, ZOMBOID_UDPPORT)
                      .replace(ZOMBOID_UPSTREAM_START, ZOMBOID_PORT_NOTICE + ZOMBOID_UPSTREAM_START))
    egg["variables"] = [v for v in egg["variables"] if v["env_variable"] != "STEAM_PORT"]
    if "STEAM_PORT" in egg["startup"]:
        sys.exit(f"{egg_id}: STEAM_PORT still referenced in startup")


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


PATCHES = {
    "java25": patch_java25,
    "modrinth_script": patch_modrinth_script,
    "fill_script": patch_fill_script,
    "server_properties_url": patch_server_properties_url,
    "forge_launch_detect": patch_forge_launch_detect,
    "zomboid_startup": patch_zomboid_startup,
    "zomboid_max_players": patch_zomboid_max_players,
    "zomboid_steam_port": patch_zomboid_steam_port,
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
