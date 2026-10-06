from pathlib import Path

import pandas as pd
import pytest

from services.sandbox import run_code

ROOT = Path(__file__).resolve().parent.parent


def test_ejecuta_y_captura_stdout():
    res = run_code("print('hola')")
    assert res.ok and res.stdout.strip() == "hola"


def test_lee_los_parquet_copiados(tmp_path):
    src = tmp_path / "t.parquet"
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(src)
    res = run_code(
        "import pandas as pd\nprint(pd.read_parquet('datos.parquet')['a'].sum())",
        files={"datos.parquet": src},
    )
    assert res.ok, res.stderr
    assert res.stdout.strip() == "6"


def test_captura_errores():
    res = run_code("1 / 0")
    assert not res.ok
    assert "ZeroDivisionError" in res.stderr


def test_timeout():
    res = run_code("while True: pass", timeout=2)
    assert res.timed_out and not res.ok


@pytest.mark.parametrize(
    "code",
    [
        "import socket\nsocket.create_connection(('example.com', 80), timeout=2)",
        "import urllib.request\nurllib.request.urlopen('http://example.com', timeout=2)",
    ],
)
def test_red_bloqueada(code):
    res = run_code(code)
    assert not res.ok
    assert "bloqueado por el sandbox" in res.stderr


def test_no_lee_archivos_fuera_del_directorio_de_trabajo():
    res = run_code(f"open({str(ROOT / 'README.md')!r}).read()")
    assert not res.ok
    assert "bloqueado por el sandbox" in res.stderr


def test_no_escribe_fuera_del_directorio_de_trabajo(tmp_path):
    target = tmp_path / "x.txt"
    res = run_code(f"open({str(target)!r}, 'w').write('x')")
    assert not res.ok
    assert not target.exists()


def test_puede_escribir_en_su_directorio():
    res = run_code("open('salida.txt', 'w').write('ok')\nprint(open('salida.txt').read())")
    assert res.ok, res.stderr
    assert res.stdout.strip() == "ok"


@pytest.mark.parametrize(
    "code", ["import os\nos.system('echo hola')", "import subprocess\nsubprocess.run(['ls'])"]
)
def test_no_crea_procesos(code):
    res = run_code(code)
    assert not res.ok
    assert "bloqueado por el sandbox" in res.stderr


def test_entorno_sin_secretos(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "secreto")
    res = run_code("import os\nprint(os.environ.get('LLM_API_KEY'))")
    assert res.stdout.strip() == "None"
