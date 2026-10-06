from pathlib import Path

import pandas as pd
import pytest

from agents.ingestion.graph import build_graph
from agents.ingestion.nodes import IngestionDeps, route_after_validate
from agents.ingestion.records import make_table_id
from agents.ingestion.validation import validate_metadata
from tests.fakes import FakeEmbeddings, FakeIndex, FakeLLM, good_metadata

PDFS = Path(__file__).resolve().parent.parent / "data" / "sample_pdfs"
MEMORIA = PDFS / "memoria_andina_tech_2024.pdf"
ANUARIO = PDFS / "anuario_valdoria_2023.pdf"


def make_deps(tmp_path, llm=None, max_attempts=3):
    return IngestionDeps(
        llm=llm or FakeLLM(),
        embeddings=FakeEmbeddings(),
        index=FakeIndex(),
        tables_dir=tmp_path / "tables",
        max_attempts=max_attempts,
    )


# ------------------------------------------------------------------ unitarios
DF = pd.DataFrame(
    {"Región": ["Capital", "Litoral"], "2021": [1.0, 2.0], "2022": [3.0, 4.0]}
)


def test_validate_metadata_ok():
    meta = good_metadata(["Región", "2021", "2022"], row_headers=["Capital", "Litoral"])
    assert validate_metadata(meta, DF) == []


@pytest.mark.parametrize(
    "returned, expected_error",
    [
        (["Región", "2021"], "La tabla tiene 3 columnas y devolviste 2."),
        (["Región", "2021", "2023"], "no existen en la tabla: ['2023']"),
        (["Región", "2021", "2021"], "Faltan estas columnas: ['2022']"),
    ],
)
def test_validate_metadata_errores(returned, expected_error):
    errors = validate_metadata(good_metadata(returned), DF)
    assert any(expected_error in e for e in errors)


def test_validate_metadata_row_headers_inexistentes():
    meta = good_metadata(["Región", "2021", "2022"], row_headers=["Capital", "Nacional"])
    errors = validate_metadata(meta, DF)
    assert any("no aparecen en la tabla: ['Nacional']" in e for e in errors)
    assert any("'Capital', 'Litoral'" in e for e in errors)


def test_validate_metadata_row_headers_repetidos():
    meta = good_metadata(["Región", "2021", "2022"], row_headers=["Capital", "Capital"])
    errors = validate_metadata(meta, DF)
    assert any("repetidos: ['Capital']" in e for e in errors)


def test_prompt_incluye_todas_las_etiquetas_de_fila():
    from agents.ingestion.prompts import enrich_user_prompt
    from services.pdf_context import TableContext
    from services.pdf_extract import extract_tables

    cuadro1 = extract_tables(MEMORIA).get("Cuadro 1")
    prompt = enrich_user_prompt(cuadro1, TableContext(above="", below=""))
    assert "Resultado neto" in prompt  # 9.ª fila, fuera de la vista previa de 5


def test_table_id_es_determinista():
    a = make_table_id("memoria.pdf", 1, 0)
    assert a == make_table_id("memoria.pdf", 1, 0)
    assert a != make_table_id("memoria.pdf", 1, 1)
    assert a != make_table_id("anuario.pdf", 1, 0)


@pytest.mark.parametrize(
    "feedback, attempts, expected",
    [({}, 1, "index"), ({0: "x"}, 1, "enrich"), ({0: "x"}, 3, "index")],
)
def test_route_after_validate(feedback, attempts, expected):
    state = {"feedback": feedback, "attempts": attempts}
    assert route_after_validate(state, max_attempts=3) == expected


# ------------------------------------------------------------------ grafo
def test_ingesta_doble_es_idempotente(tmp_path):
    deps = make_deps(tmp_path)
    graph = build_graph(deps)
    for _ in range(2):
        states = [graph.invoke({"pdf_path": str(p)}) for p in (MEMORIA, ANUARIO)]
        assert deps.index.describe_index_stats().total_vector_count == 6

    memoria, anuario = states
    assert len(memoria["indexed"]) == 3 and memoria["skipped"] == []
    assert len(anuario["indexed"]) == 3
    assert [s.caption for s in anuario["skipped"]] == ["Cuadro 4.1"]
    assert len(list((tmp_path / "tables").glob("*.parquet"))) == 6


def test_index_guarda_parquet_y_metadatos(tmp_path):
    deps = make_deps(tmp_path)
    state = build_graph(deps).invoke({"pdf_path": str(MEMORIA)})

    ventas_id = make_table_id("memoria_andina_tech_2024.pdf", 1, 1)
    assert ventas_id in state["indexed"]
    df = pd.read_parquet(tmp_path / "tables" / f"{ventas_id}.parquet")
    assert len(df) == 24 and list(df.columns) == ["Año", "Mes", "Norte", "Centro", "Sur"]

    md = deps.index.vectors[ventas_id]["metadata"]
    assert md["caption"] == "Cuadro 3"
    assert md["name"] == "Tabla de prueba"
    assert md["source"] == "memoria_andina_tech_2024.pdf, pp. 1–2"
    assert md["pages"] == ["1", "2"]
    assert md["preview"].count("\n") == 6  # encabezado + 5 filas
    assert md["context_below"].startswith("Fuente: sistema comercial interno")
    assert None not in md.values()


def test_reintenta_enrich_con_feedback(tmp_path):
    def answer(caption, columns, attempt):
        if caption == "Cuadro 1" and attempt == 1:
            return good_metadata(columns[:-1])
        return good_metadata(columns)

    llm = FakeLLM(answer)
    deps = make_deps(tmp_path, llm=llm)
    state = build_graph(deps).invoke({"pdf_path": str(MEMORIA)})

    assert state["attempts"] == 2
    assert len(llm.prompts) == 4  # 3 tablas + 1 reintento solo del Cuadro 1
    retry = llm.prompts[-1]
    assert retry.startswith("Rótulo: Cuadro 1")
    assert "Tu respuesta anterior no pasó la validación" in retry
    assert "Faltan estas columnas: ['2024']" in retry
    assert len(state["indexed"]) == 3


def test_respuesta_fuera_de_schema_se_reintenta(tmp_path):
    def answer(caption, columns, attempt):
        if caption == "Cuadro 2" and attempt == 1:
            raise ValueError("JSON inválido")
        return good_metadata(columns)

    state = build_graph(make_deps(tmp_path, llm=FakeLLM(answer))).invoke(
        {"pdf_path": str(MEMORIA)}
    )
    assert state["attempts"] == 2
    assert len(state["indexed"]) == 3


def test_reintentos_agotados_saltea_la_tabla(tmp_path):
    def answer(caption, columns, attempt):
        return good_metadata(columns[:-1] if caption == "Cuadro 1" else columns)

    llm = FakeLLM(answer)
    deps = make_deps(tmp_path, llm=llm, max_attempts=2)
    state = build_graph(deps).invoke({"pdf_path": str(MEMORIA)})

    assert state["attempts"] == 2
    assert len(state["indexed"]) == 2
    assert deps.index.describe_index_stats().total_vector_count == 2
    [skipped] = state["skipped"]
    assert skipped.caption == "Cuadro 1"
    assert "metadatos inválidos tras 2 intentos" in skipped.reason


def test_load_pdf_conserva_el_texto_de_las_paginas(tmp_path):
    state = build_graph(make_deps(tmp_path)).invoke({"pdf_path": str(MEMORIA)})
    assert len(state["page_texts"]) == 2
    assert "Andina Tech S.A." in state["page_texts"][0]


def test_reingesta_borra_vectores_huerfanos_del_mismo_archivo(tmp_path):
    deps = make_deps(tmp_path)
    viejo = {"file": "memoria_andina_tech_2024.pdf"}
    otro = {"file": "otro.pdf"}
    deps.index.upsert([
        {"id": "viejo", "values": [1.0, 0.0, 0.0], "metadata": viejo},
        {"id": "ajeno", "values": [1.0, 0.0, 0.0], "metadata": otro},
    ])
    build_graph(deps).invoke({"pdf_path": str(MEMORIA)})
    assert "viejo" not in deps.index.vectors
    assert "ajeno" in deps.index.vectors
    assert deps.index.describe_index_stats().total_vector_count == 4


def test_pdf_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_graph(make_deps(tmp_path)).invoke({"pdf_path": str(tmp_path / "no.pdf")})
