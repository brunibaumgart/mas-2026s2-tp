"""Clientes del proxy LiteLLM (chat y embeddings), configurados desde .env.

Acepta los nombres de variables del enunciado (LITELLM_BASE_URL / LITELLM_API_KEY) o los
del proxy de la materia (LLM_SERVICE_URL / LLM_API_KEY).
"""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings


def _env(*names: str) -> str:
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    raise KeyError(f"Falta la variable de entorno {' o '.join(names)}")


def _proxy_kwargs() -> dict:
    return dict(
        base_url=_env("LITELLM_BASE_URL", "LLM_SERVICE_URL"),
        api_key=_env("LITELLM_API_KEY", "LLM_API_KEY"),
    )


def get_chat_model(temperature: float = 0) -> ChatOpenAI:
    """Modelo principal (LLM_MODEL): tareas donde un error es caro (selección, código, verificación)."""
    load_dotenv()
    return ChatOpenAI(model=_env("LLM_MODEL"), temperature=temperature, **_proxy_kwargs())


def get_fast_chat_model(temperature: float = 0) -> ChatOpenAI:
    """Modelo rápido (LLM_MODEL_FAST): reescribir la consulta y redactar la respuesta.

    Si LLM_MODEL_FAST no está definido, usa LLM_MODEL.
    """
    load_dotenv()
    model = os.environ.get("LLM_MODEL_FAST") or _env("LLM_MODEL")
    return ChatOpenAI(model=model, temperature=temperature, **_proxy_kwargs())


def get_embeddings() -> OpenAIEmbeddings:
    load_dotenv()
    return OpenAIEmbeddings(
        model=_env("EMBEDDING_MODEL"), check_embedding_ctx_length=False, **_proxy_kwargs()
    )
