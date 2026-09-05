#!/usr/bin/env python3
"""Ripple's single task runner (PRD section 5.2).

    python run.py install    # create the venv, install Python and npm dependencies
    python run.py dev        # start API and web together; Ctrl+C stops both
    python run.py seed       # load the reference demo corpus from section 15
    python run.py test       # run the pytest suite
    python run.py reindex    # rebuild the vec_* and fts_* mirror tables

Standard library only (argparse, subprocess, venv, pathlib, os, signal). No
Makefile, no shell scripts, no .ps1  -  see PRD section 5.2 for why: GNU make
is not present on a default Windows machine, and a Makefile plus a
PowerShell equivalent means writing every task twice and letting them
drift. This file is the one place task automation lives, and it runs
identically on Windows, macOS, and Linux.

Every command prints what it is about to do before doing it. Failures
produce a readable message naming the fix  -  never a bare traceback as the
primary error surface.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
REQUIREMENTS = ROOT / "requirements.txt"


def announce(message: str) -> None:
    print(f"-> {message}")


def fail(message: str, fix: str | None = None) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    if fix:
        print(f"  Fix: {fix}", file=sys.stderr)
    sys.exit(1)


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def require_venv() -> Path:
    py = venv_python()
    if not py.exists():
        fail(
            "No virtual environment found at .venv.",
            "Run 'python run.py install' first.",
        )
    return py


def run_checked(cmd: list[str], cwd: Path | None = None, fix: str | None = None) -> None:
    """subprocess.run wrapped so a missing binary or a nonzero exit becomes
    a one-line, actionable message instead of a raw traceback."""
    printable = " ".join(cmd)
    try:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)
    except FileNotFoundError:
        fail(f"Could not find '{cmd[0]}' on PATH.", fix or f"Install '{cmd[0]}' and make sure it's on PATH.")
    except subprocess.CalledProcessError as exc:
        fail(f"Command failed (exit code {exc.returncode}): {printable}", fix)


# ---------------------------------------------------------------- install --

def cmd_install(args: argparse.Namespace) -> None:
    announce("Checking for a Python virtual environment at .venv ...")
    if not venv_python().exists():
        announce("Creating .venv ...")
        run_checked([sys.executable, "-m", "venv", str(VENV_DIR)])
    else:
        announce(".venv already exists, reusing it.")

    if not REQUIREMENTS.exists():
        fail("requirements.txt not found at the repo root.", "Restore requirements.txt and re-run.")

    announce("Installing Python dependencies from requirements.txt ...")
    run_checked([str(venv_python()), "-m", "pip", "install", "-r", str(REQUIREMENTS)])

    if (WEB_DIR / "package.json").exists():
        npm = shutil.which("npm")
        if npm is None:
            fail(
                "npm not found on PATH.",
                "Install Node.js (https://nodejs.org) and re-run 'python run.py install'.",
            )
        announce("Installing npm dependencies in web/ ...")
        run_checked([npm, "install"], cwd=WEB_DIR)
    else:
        announce("web/ has no package.json yet  -  it arrives in a later wave. Skipping npm install.")

    announce("Install complete.")


# --------------------------------------------------------------------- dev --

def _read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader for the root .env file.

    Deliberately not python-dotenv: this file's docstring promises
    "standard library only." Only used to let `dev` pick RIPPLE_API_PORT
    and NEXT_PUBLIC_API_BASE_URL out of .env and thread them into both
    child processes; api/main.py still does its own (python-dotenv) load
    for everything else the API reads.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#", 1)[0].strip()
        if key:
            values[key] = value
    return values


def _dev_env() -> dict[str, str]:
    """os.environ, filled in from .env for keys not already set (real
    environment variables always win, matching python-dotenv's default)."""
    merged = dict(os.environ)
    for key, value in _read_env_file(ROOT / ".env").items():
        merged.setdefault(key, value)
    return merged


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Terminate `proc` and everything it spawned.

    On Windows, `npm run dev` runs through a `cmd.exe` wrapper that starts
    node, which (with Turbopack) starts further worker processes — none of
    them in `proc`'s own process handle. `Popen.terminate()` only signals
    the immediate process, so the web dev server survives its parent being
    killed and keeps the port bound after `dev` exits. `taskkill /T` walks
    the whole tree by PID instead, which is what "still tears both down on
    Ctrl+C" actually requires here.
    """
    if platform.system() == "Windows":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        try:
            proc.terminate()
        except OSError:
            pass


def _shutdown(procs: list[subprocess.Popen], exit_code: int) -> None:
    for proc in procs:
        if proc.poll() is None:
            _terminate_tree(proc)
    deadline = time.time() + 5
    for proc in procs:
        remaining = max(0.0, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    sys.exit(exit_code)


def supervise(procs: list[subprocess.Popen]) -> None:
    """Watch every child process; terminate all of them the moment any one
    exits, or the moment Ctrl+C arrives (PRD section 5.2: "dev supervises
    both child processes and terminates both on Ctrl+C or on either one
    exiting")."""
    try:
        while True:
            for proc in procs:
                ret = proc.poll()
                if ret is not None:
                    announce(f"A supervised process exited (code {ret}); stopping the rest ...")
                    _shutdown(procs, ret if ret else 1)
                    return
            time.sleep(0.5)
    except KeyboardInterrupt:
        announce("Ctrl+C received, stopping ...")
        _shutdown(procs, 0)


def cmd_dev(args: argparse.Namespace) -> None:
    py = require_venv()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not (ROOT / ".env").exists():
        announce("No .env found  -  copy .env.example to .env and add an OpenAI key when you need OpenAI features.")

    env = _dev_env()
    # RIPPLE_API_PORT lets `dev` move off 8000 when something else on the
    # machine already holds it, without editing this file  -  set it in
    # .env (or the shell) and both processes pick it up from here.
    api_port = env.get("RIPPLE_API_PORT", "8000")
    api_base_url = env.get("NEXT_PUBLIC_API_BASE_URL", f"http://localhost:{api_port}/api/v1")

    announce(f"Starting the API on http://127.0.0.1:{api_port} ...")
    api_proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", api_port],
        cwd=str(ROOT),
        env=env,
    )
    procs = [api_proc]

    if (WEB_DIR / "package.json").exists():
        npm = shutil.which("npm")
        if npm is None:
            _shutdown(procs, 1)
            fail("npm not found on PATH.", "Install Node.js, then run 'python run.py install'.")

        # Keep web/.env.local in sync with the port actually used this run,
        # so a moved RIPPLE_API_PORT never has to be hand-copied into two
        # places (PRD section 9 preamble: this is the value every fetch in
        # the web app is built from).
        env_local = WEB_DIR / ".env.local"
        env_local.write_text(f"NEXT_PUBLIC_API_BASE_URL={api_base_url}\n", encoding="utf-8")

        announce(f"Starting the web app on http://localhost:3000 (API base {api_base_url}) ...")
        web_env = dict(env)
        web_env["NEXT_PUBLIC_API_BASE_URL"] = api_base_url
        web_proc = subprocess.Popen([npm, "run", "dev"], cwd=str(WEB_DIR), env=web_env)
        procs.append(web_proc)
    else:
        announce("NOTE: web/ has no package.json  -  run 'python run.py install' to set it up.")
        announce("Running the API alone. Press Ctrl+C to stop.")

    supervise(procs)


# -------------------------------------------------------------------- seed --

def cmd_seed(args: argparse.Namespace) -> None:
    py = require_venv()
    seed_script = ROOT / "scripts" / "seed_demo.py"
    if not seed_script.exists():
        announce(
            "scripts/seed_demo.py does not exist yet  -  the reference demo corpus "
            "(PRD section 15) arrives with the ingestion & extraction wave."
        )
        announce(
            "There is nothing to seed yet. The three default accounts (Priya Menon, "
            "Alex Tan, Sam Rahim) are created automatically the first time the API boots."
        )
        return
    announce("Running scripts/seed_demo.py ...")
    run_checked([str(py), str(seed_script)])


# -------------------------------------------------------------------- test --

def cmd_test(args: argparse.Namespace) -> None:
    py = require_venv()
    announce("Running pytest ...")
    cmd = [str(py), "-m", "pytest", "-v", *args.pytest_args]
    result = subprocess.run(cmd, cwd=str(ROOT))
    sys.exit(result.returncode)


# ----------------------------------------------------------------- reindex --

def cmd_reindex(args: argparse.Namespace) -> None:
    py = require_venv()
    script = ROOT / "scripts" / "reindex.py"
    if not script.exists():
        announce(
            "scripts/reindex.py does not exist yet  -  rebuilding vec_*/fts_* mirror "
            "tables arrives with the embeddings & search wave (PRD build order step 4)."
        )
        return
    announce("Running scripts/reindex.py ...")
    cmd = [str(py), str(script)]
    if args.dims:
        cmd += ["--dims", str(args.dims)]
    run_checked(cmd)


# --------------------------------------------------------------------- cli --

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Ripple's single task runner. See PRD section 5.2.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="Create the venv, install Python and npm dependencies.")
    p_install.set_defaults(func=cmd_install)

    p_dev = sub.add_parser("dev", help="Start the API (and web, once it exists). Ctrl+C stops everything.")
    p_dev.set_defaults(func=cmd_dev)

    p_seed = sub.add_parser("seed", help="Load the reference demo corpus (PRD section 15).")
    p_seed.set_defaults(func=cmd_seed)

    p_test = sub.add_parser("test", help="Run the pytest suite.")
    p_test.add_argument("pytest_args", nargs=argparse.REMAINDER, help="Extra args passed through to pytest.")
    p_test.set_defaults(func=cmd_test)

    p_reindex = sub.add_parser("reindex", help="Rebuild the vec_* and fts_* mirror tables.")
    p_reindex.add_argument("--dims", type=int, default=None, help="Rebuild at this embedding dimensionality.")
    p_reindex.set_defaults(func=cmd_reindex)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        announce("Interrupted.")
        sys.exit(130)
    except Exception as exc:  # last resort: still readable, never a bare traceback
        fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
