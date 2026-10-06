"""Las preguntas de data/preguntas_prueba.md con su estado, valores y tablas esperados."""
from __future__ import annotations

from dataclasses import dataclass, field

M = "memoria_andina_tech_2024.pdf"
A = "anuario_valdoria_2023.pdf"


@dataclass
class Case:
    id: int
    question: str
    status: str
    # Cada elemento es un conjunto de alternativas aceptables; tienen que aparecer todos.
    numbers: list[tuple[float, ...]] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    # Tablas que hacen falta, como (archivo, rótulo). Vacío si ninguna tabla responde la pregunta.
    tables: list[tuple[str, str]] = field(default_factory=list)


CASES = [
    Case(1, "¿Cuál fue el crecimiento interanual promedio de los ingresos entre 2020 y 2024?",
         "answered", [(11.51, 11.48)], tables=[(M, "Cuadro 1")]),
    Case(2, "¿Qué proporción de los gastos operativos totales representó I+D en cada año?",
         "answered", [(21.75,), (22.26,), (24.25,), (27.18,), (29.09,)], tables=[(M, "Cuadro 2")]),
    Case(3, "¿Qué porcentaje de los ingresos por ventas representó el gasto en I+D en 2024?",
         "answered", [(9.17,)], tables=[(M, "Cuadro 1"), (M, "Cuadro 2")]),
    Case(4, "¿Cuánto crecieron las ventas de la región Sur en 2024 respecto de 2023?",
         "answered", [(11.32,)], tables=[(M, "Cuadro 3")]),
    Case(5, "¿Qué mes de 2024 tuvo las mayores ventas totales y cuánto vendió?",
         "answered", [(12033,)], ["Diciembre"], tables=[(M, "Cuadro 3")]),
    Case(6, "¿Cuáles fueron las exportaciones per cápita de la región Litoral en 2023?",
         "answered", [(2858.80,)], tables=[(A, "Cuadro 3.1"), (A, "Cuadro 2.1")]),
    Case(7, "¿Qué región tuvo la tasa de desocupación más alta en 2023, y por cuánto superó "
            "al promedio nacional?", "partial", [(10.6,)], ["Desierto"], tables=[(A, "Cuadro 1.1")]),
    # 8, 9 y 11: hay una tabla relacionada (la recuperación tiene que encontrarla), pero no alcanza.
    Case(8, "¿Cuáles fueron las exportaciones per cápita de Montaña en 2020?", "cannot_answer",
         tables=[(A, "Cuadro 3.1"), (A, "Cuadro 2.1")]),
    Case(9, "¿A cuántos pesos equivalen las exportaciones de Litoral en 2023?", "cannot_answer",
         tables=[(A, "Cuadro 3.1")]),
    Case(10, "¿Cuál fue la inflación de Argentina en 2023?", "cannot_answer"),
    Case(11, "¿Cuáles fueron los ingresos por ventas de Andina Tech en 2025?", "cannot_answer",
         tables=[(M, "Cuadro 1")]),
]
