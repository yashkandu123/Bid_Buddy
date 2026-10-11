from __future__ import annotations
import argparse
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 5173
UI_URL = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/"
API_DOCS_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}/docs"
HEALTH_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}/health"


def main() -> int:
    args = parse_args()
    log("Sprintd Tender Pricing launcher")
    log(f"Project: {PROJECT_ROOT}")

    errors = preflight()
    if errors:
        log("\nCannot start the application:")
        for error in errors:
            log(f"  - {error}")
        return 1

    processes: list[subprocess.Popen] = []
    try:
        backend = start_process(
            "backend",
            [sys.executable, "-m", "uvicorn", "src.tender_pricing.api:app", "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)],
            PROJECT_ROOT,
        )
        processes.append(backend)

        npm = shutil.which("npm.cmd") or shutil.which("npm")
        frontend = start_process(
            "frontend",
            [npm or "npm", "run", "dev", "--", "--host", FRONTEND_HOST, "--port", str(FRONTEND_PORT)],
            FRONTEND_DIR,
        )
        processes.append(frontend)

        wait_for_services(processes, args.startup_timeout)
        log("\nServices are ready:")
        log(f"  UI: {UI_URL}")
        log(f"  API documentation: {API_DOCS_URL}")

        if not args.no_browser:
            log("Opening UI in the default browser...")
            webbrowser.open(UI_URL)

        log("\nPress Ctrl+C to stop both services.")
        monitor(processes)
        return 0
    except KeyboardInterrupt:
        log("\nCtrl+C received. Stopping services...")
        return 0
    except RuntimeError as exc:
        log(f"\nStartup failed: {exc}")
        return 1
    finally:
        stop_processes(processes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the Sprintd Tender Pricing backend and frontend.")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the UI automatically after startup.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=45.0,
        help="Seconds to wait for both services to respond. Default: 45.",
    )
    return parser.parse_args()


def preflight() -> list[str]:
    errors: list[str] = []
    if not (PROJECT_ROOT / "src" / "tender_pricing" / "api.py").exists():
        errors.append("FastAPI app not found at src/tender_pricing/api.py.")

    if not FRONTEND_DIR.exists():
        errors.append("Frontend directory is missing.")
    elif not (FRONTEND_DIR / "package.json").exists():
        errors.append("frontend/package.json is missing.")
    elif not (FRONTEND_DIR / "node_modules").exists():
        errors.append("Frontend dependencies are missing. Run: cd frontend; npm install")

    if not python_module_available("uvicorn"):
        errors.append("Python dependency 'uvicorn' is missing. Install project requirements in the active Python environment.")
    if not python_module_available("fastapi"):
        errors.append("Python dependency 'fastapi' is missing. Install project requirements in the active Python environment.")

    if not shutil.which("node"):
        errors.append("Node.js is not available on PATH.")
    if not (shutil.which("npm.cmd") or shutil.which("npm")):
        errors.append("npm is not available on PATH.")

    if port_is_open(BACKEND_HOST, BACKEND_PORT):
        errors.append(f"Port {BACKEND_PORT} is already in use. Stop the existing backend or choose another port in the script.")
    if port_is_open(FRONTEND_HOST, FRONTEND_PORT):
        errors.append(f"Port {FRONTEND_PORT} is already in use. Stop the existing frontend or choose another port in the script.")
    return errors


def log(message: str) -> None:
    print(message, flush=True)


def python_module_available(module_name: str) -> bool:
    command = [sys.executable, "-c", f"import {module_name}"]
    result = subprocess.run(command, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def port_is_open(host: str, port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex((host, port)) == 0:
            return True
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        with contextlib.suppress(AttributeError, OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def start_process(name: str, command: list[str], cwd: Path) -> subprocess.Popen:
    log(f"Starting {name}: {' '.join(command)}")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(command, cwd=cwd, creationflags=creationflags)


def wait_for_services(processes: list[subprocess.Popen], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    backend_ready = False
    frontend_ready = False
    while time.monotonic() < deadline:
        check_unexpected_exit(processes)
        backend_ready = backend_ready or url_responds(HEALTH_URL)
        frontend_ready = frontend_ready or url_responds(UI_URL)
        if backend_ready and frontend_ready:
            return
        time.sleep(0.5)
    details = []
    if not backend_ready:
        details.append(f"backend did not respond at {HEALTH_URL}")
    if not frontend_ready:
        details.append(f"frontend did not respond at {UI_URL}")
    raise RuntimeError("; ".join(details))


def url_responds(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def monitor(processes: list[subprocess.Popen]) -> None:
    while True:
        check_unexpected_exit(processes)
        time.sleep(1)


def check_unexpected_exit(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        code = process.poll()
        if code is not None:
            raise RuntimeError(f"child process exited unexpectedly with code {code}.")


def stop_processes(processes: list[subprocess.Popen]) -> None:
    for process in reversed(processes):
        if process.poll() is not None:
            continue
        log(f"Stopping process {process.pid}...")
        if os.name == "nt":
            with contextlib.suppress(Exception):
                process.send_signal(signal.CTRL_BREAK_EVENT)
                process.wait(timeout=5)
                continue
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
            continue
        if process.poll() is None:
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
