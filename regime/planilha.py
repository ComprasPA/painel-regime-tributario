"""Acesso à planilha Google (CadastroFornecedores + aba de controle)."""
import json
import tomllib
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials

from . import config

_ESCOPOS = ["https://www.googleapis.com/auth/spreadsheets"]


@lru_cache(maxsize=1)
def planilha() -> gspread.Spreadsheet:
    if config.GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.load(open(config.GOOGLE_SERVICE_ACCOUNT_JSON, encoding="utf-8"))
    elif config.GOOGLE_SECRETS_TOML:
        with open(config.GOOGLE_SECRETS_TOML, "rb") as f:
            info = tomllib.load(f)["gcp_service_account"]
    elif "gcp_service_account" in config.SECRETS:  # Streamlit Cloud
        info = dict(config.SECRETS["gcp_service_account"])
    else:
        raise SystemExit("Defina GOOGLE_SERVICE_ACCOUNT_JSON ou GOOGLE_SECRETS_TOML no .env")
    cliente = gspread.authorize(Credentials.from_service_account_info(info, scopes=_ESCOPOS))
    return cliente.open_by_key(config.SPREADSHEET_ID)


def ler_cadastro() -> tuple[gspread.Worksheet, list[str], list[dict]]:
    """Devolve (aba, cabeçalho, registros). Cada registro traz _linha (nº na planilha)."""
    ws = planilha().worksheet(config.ABA_CADASTRO)
    valores = ws.get_all_values()
    cab = valores[0]
    registros = []
    for n, linha in enumerate(valores[1:], start=2):
        linha = linha + [""] * (len(cab) - len(linha))
        registros.append({"_linha": n, **{c: linha[i].strip() for i, c in enumerate(cab)}})
    return ws, cab, registros
