#!/usr/bin/env python3
"""check_eggs.py - TeamCryptid eggs

Validates every egg (minecraft/, zomboid/, valheim/) before it is committed:
  - valid JSON in Pterodactyl PTDL_v2 format (imports into Jexactyl/Pterodactyl)
  - required fields present, variable rules in Pterodactyl's string form
  - the panel's own model rules (Jexactyl app/Models/Egg.php): author is an email,
    config.files/config.startup are JSON strings, config.stop <= 191 chars,
    at least one docker image, env variable names valid
  - update_url points at this repo, at the file's own path
  - install script passes a shell syntax check
  - every TeamCryptid URL a script downloads exists in this repo
Exit code 0 = all good, 1 = at least one problem.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build import RAW_BASE  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
EGG_DIRS = ["minecraft", "zomboid", "valheim"]
REQUIRED = ["name", "description", "docker_images", "startup", "config", "scripts", "variables"]


def shell_check(script, entrypoint):
    """Syntax-check with bash for bash eggs, POSIX sh otherwise (closest to ash)."""
    shell = "bash" if entrypoint == "bash" else ("dash" if shutil.which("dash") else "sh")
    r = subprocess.run([shell, "-n"], input=script.replace("\r", ""), capture_output=True, text=True)
    return r.returncode == 0, f"{shell}: {r.stderr.strip()}"


def check(path):
    rel = path.relative_to(ROOT).as_posix()
    problems = []
    try:
        egg = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]

    if egg.get("meta", {}).get("version") != "PTDL_v2":
        problems.append(f"format is {egg.get('meta', {}).get('version')}, expected PTDL_v2")
    for key in REQUIRED:
        if key not in egg:
            problems.append(f"missing field: {key}")
    for v in egg.get("variables", []):
        if not isinstance(v.get("rules"), str):
            problems.append(f"variable {v.get('env_variable')}: rules must be a string")

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", egg.get("author", "")):
        problems.append(f"author must be an email address, got {egg.get('author')!r}")
    cfg = egg.get("config", {})
    for key in ("files", "startup"):
        try:
            json.loads(cfg.get(key) or "null")
        except (TypeError, json.JSONDecodeError):
            problems.append(f"config.{key} must be a JSON string")
    if len(cfg.get("stop") or "") > 191:
        problems.append("config.stop longer than 191 characters")
    if not egg.get("docker_images"):
        problems.append("no docker images")
    for v in egg.get("variables", []):
        if not re.fullmatch(r"\w{1,191}", v.get("env_variable", "")):
            problems.append(f"invalid env variable name {v.get('env_variable')!r}")

    want_url = f"{RAW_BASE}/{rel}"
    if egg.get("meta", {}).get("update_url") != want_url:
        problems.append(f"update_url is {egg.get('meta', {}).get('update_url')}, expected {want_url}")

    inst = egg.get("scripts", {}).get("installation", {})
    script = inst.get("script", "")
    ok, msg = shell_check(script, inst.get("entrypoint"))
    if not ok:
        problems.append(f"install script syntax: {msg}")

    for url in re.findall(r"https://raw\.githubusercontent\.com/TeamCryptid/eggs/main/[^\s\"'}]+", script):
        target = url.replace(f"{RAW_BASE}/", "")
        if not (ROOT / target).exists():
            problems.append(f"script downloads {target}, which is not in this repo")
    if "CONFIG_BASE" in script:
        base = re.search(r'CONFIG_BASE="([^"]+)"', script).group(1)
        for sub in re.findall(r'\$\{CONFIG_BASE\}/([^"\s]+)', script):
            target = f"{base}/{sub}".replace(f"{RAW_BASE}/", "")
            if not (ROOT / target).exists():
                problems.append(f"script downloads {target}, which is not in this repo")

    imgs = list(egg.get("docker_images", {}))
    print(f"{'FAIL' if problems else 'ok  '}  {rel}  [{imgs[0] if imgs else 'no images'} first]")
    return problems


def main():
    eggs = sorted(p for d in EGG_DIRS for p in (ROOT / d).rglob("*.json"))
    if not eggs:
        sys.exit(f"no eggs found under {', '.join(EGG_DIRS)}")
    failed = 0
    for path in eggs:
        problems = check(path)
        for p in problems:
            print(f"      - {p}")
        failed += bool(problems)
    print(f"\ncheck_eggs.py: {len(eggs) - failed}/{len(eggs)} eggs passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
