"""Ejecución aislada del código generado por el LLM.

Capas de aislamiento:
- subproceso aparte (``python -I``: sin variables PYTHON*, sin site del usuario), con timeout
  y límite de CPU;
- directorio de trabajo temporal con solo los archivos de datos necesarios;
- entorno vacío (el proceso no ve las API keys del .env);
- un audit hook (PEP 578) que bloquea red, creación de procesos y acceso a archivos
  fuera del directorio de trabajo y de la instalación de Python.

No es un sandbox fuerte (no es un contenedor): las extensiones nativas pueden abrir
archivos sin pasar por el audit hook.
"""
from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 20
CHART_FILE = "chart.png"
MAX_CHART_BYTES = 2_000_000

# Solo si el código usa matplotlib: cargarlo cuesta ~1 s y abre fuentes y librerías nativas.
MATPLOTLIB_PRELOAD = """import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot
"""

PRELUDE = r'''
import os as _os
import sys as _sys

# Se importan antes del hook porque cargan librerías nativas (ctypes) al inicializarse.
import json, math  # noqa: E401
import numpy
import pandas
import pyarrow.parquet
{matplotlib}
def _sandbox():
    real = _os.path.realpath
    workdir = real(_os.getcwd())
    read_roots = {workdir}
    for p in (_sys.prefix, _sys.base_prefix, _sys.exec_prefix, _sys.base_exec_prefix):
        read_roots.add(real(p))
    read_roots = tuple(read_roots) + (
        "/usr/", "/System/", "/Library/", "/dev/null", "/dev/urandom",
        "/private/var/db/timezone/", "/etc/", "/private/etc/",
    )
    write_flags = _os.O_WRONLY | _os.O_RDWR | _os.O_CREAT | _os.O_APPEND | _os.O_TRUNC
    blocked = (
        "socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
        "os.fork", "os.forkpty", "os.kill", "ctypes.dlopen", "webbrowser.",
    )

    def deny(what):
        raise PermissionError(f"{what}: bloqueado por el sandbox")

    def under(path, roots):
        return any(path == r.rstrip("/") or path.startswith(r.rstrip("/") + "/") for r in roots)

    def hook(event, args):
        if event == "open":
            path, mode, flags = args
            if not isinstance(path, (str, bytes)):
                return
            path = real(_os.fsdecode(path))
            writing = (mode and any(c in mode for c in "wax+")) or (
                not mode and isinstance(flags, int) and flags & write_flags
            )
            if not under(path, (workdir,) if writing else read_roots):
                deny(f"open {path}")
        elif event in ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "shutil.rmtree"):
            path = args[0]
            if isinstance(path, (str, bytes)) and not under(real(_os.fsdecode(path)), (workdir,)):
                deny(f"{event} {path}")
        elif event.startswith(blocked):
            deny(event)

    _sys.addaudithook(hook)

_sandbox()
del _sandbox
'''


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool = False
    chart: bytes | None = None

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0


def _limit_cpu(seconds: int):
    def apply():
        import resource

        # Límite blando: SIGXCPU. El duro queda 1 s después: si se alcanza, Linux manda SIGKILL.
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))

    return apply


def run_code(
    code: str, files: dict[str, Path] | None = None, timeout: int = DEFAULT_TIMEOUT
) -> ExecResult:
    """Ejecuta ``code`` en un subproceso aislado. ``files`` se copian al directorio de trabajo."""
    with tempfile.TemporaryDirectory(prefix="sandbox_") as tmp:
        workdir = Path(tmp)
        for name, src in (files or {}).items():
            shutil.copy(src, workdir / name)
        prelude = PRELUDE.replace(
            "{matplotlib}", MATPLOTLIB_PRELOAD if "matplotlib" in code else ""
        )
        (workdir / "main.py").write_text(prelude + "\n" + code, encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "TMPDIR": tmp, "MPLCONFIGDIR": tmp}
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "main.py"],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=_limit_cpu(timeout),
            )
        except subprocess.TimeoutExpired as exc:
            return _timeout(_text(exc.stdout), _text(exc.stderr), timeout)
        if proc.returncode in (-signal.SIGXCPU, -signal.SIGKILL):
            return _timeout(proc.stdout, proc.stderr, timeout)
        return ExecResult(proc.stdout, proc.stderr, proc.returncode, chart=_read_chart(workdir))


def _read_chart(workdir: Path) -> bytes | None:
    """El gráfico que el programa haya guardado en chart.png, si es un PNG de tamaño razonable."""
    path = workdir / CHART_FILE
    if not path.is_file() or path.stat().st_size > MAX_CHART_BYTES:
        return None
    data = path.read_bytes()
    return data if data.startswith(b"\x89PNG") else None


def _timeout(stdout: str, stderr: str, timeout: int) -> ExecResult:
    msg = f"\nTimeout: la ejecución superó {timeout} s."
    return ExecResult(stdout=stdout, stderr=stderr + msg, returncode=None, timed_out=True)


def _text(data: str | bytes | None) -> str:
    if data is None:
        return ""
    return data.decode(errors="replace") if isinstance(data, bytes) else data
