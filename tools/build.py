#!/usr/bin/env python3
"""build.py - TeamCryptid eggs

Builds the curated egg set from a pelican-eggs/minecraft checkout.
Every change we make to upstream eggs lives in this file, so a resync is:

    git clone https://github.com/pelican-eggs/minecraft.git /tmp/upstream
    python3 tools/build.py /tmp/upstream
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

UPSTREAM_REPO = "https://github.com/pelican-eggs/minecraft"
RAW_BASE = "https://raw.githubusercontent.com/TeamCryptid/eggs/main"
JAVA25_IMAGE = "ghcr.io/pelican-eggs/yolks:java_25"

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILL_SCRIPT = ROOT / "tools" / "scripts" / "fill-install.sh"

# id, upstream source path, destination path in this repo, patches applied
EGGS = [
    ("neoforge", "java/neoforge/egg-pterodactyl-neo-forge.json",
     "minecraft/java/neoforge/egg-pterodactyl-neo-forge.json", []),
    ("forge", "java/forge/pterodactyl-egg-forge-minecraft.json",
     "minecraft/java/forge/pterodactyl-egg-forge-minecraft.json", ["java25"]),
    ("fabric", "java/fabric/egg-pterodactyl-fabric.json",
     "minecraft/java/fabric/egg-pterodactyl-fabric.json", []),
    ("curseforge", "java/curseforge/egg-pterodactyl-curse-forge-generic.json",
     "minecraft/java/curseforge/egg-pterodactyl-curse-forge-generic.json", []),
    ("modrinth", "java/modrinth/egg-pterodactyl-modrinth-generic.json",
     "minecraft/java/modrinth/egg-pterodactyl-modrinth-generic.json", ["modrinth_script"]),
    ("ftb", "java/ftb/egg-pterodactyl-f-t-b-server.json",
     "minecraft/java/ftb/egg-pterodactyl-f-t-b-server.json", []),
    ("paper", "java/paper/pterodactyl-egg-paper.json",
     "minecraft/java/paper/pterodactyl-egg-paper.json", ["java25", "fill_script"]),
    ("purpur", "java/purpur/egg-pterodactyl-purpur.json",
     "minecraft/java/purpur/egg-pterodactyl-purpur.json", ["server_properties_url"]),
    ("velocity", "proxy/java/velocity/egg-pterodactyl-velocity.json",
     "minecraft/proxy/velocity/egg-pterodactyl-velocity.json", ["java25", "fill_script"]),
]

# Plain files the eggs download at install time, hosted here instead of upstream.
ASSETS = [
    ("java/server.properties", "minecraft/java/server.properties"),
    ("proxy/java/velocity/velocity.toml", "minecraft/proxy/velocity/velocity.toml"),
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


PATCHES = {
    "java25": patch_java25,
    "modrinth_script": patch_modrinth_script,
    "fill_script": patch_fill_script,
    "server_properties_url": patch_server_properties_url,
}


def main():
    ap = argparse.ArgumentParser(description="build.py")
    ap.add_argument("upstream", type=pathlib.Path, help="path to a pelican-eggs/minecraft checkout")
    args = ap.parse_args()
    upstream = args.upstream.resolve()

    commit = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    commit_date = subprocess.run(["git", "-C", str(upstream), "log", "-1", "--format=%cI"],
                                 capture_output=True, text=True, check=True).stdout.strip()

    lock_eggs = []
    for egg_id, src, dest, patches in EGGS:
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
        lock_eggs.append({"id": egg_id, "upstream_path": src, "upstream_sha256": sha256(src_path),
                          "path": dest, "patches": patches})
        print(f"built {dest}  patches={patches or 'none'}")

    for src, dest in ASSETS:
        out = ROOT / dest
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / src, out)
        print(f"copied {dest}")

    lock = {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": commit,
        "upstream_commit_date": commit_date,
        "built": datetime.date.today().isoformat(),
        "eggs": lock_eggs,
    }
    (ROOT / "upstream.lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    print(f"wrote upstream.lock.json (upstream {commit[:7]})")


if __name__ == "__main__":
    main()
