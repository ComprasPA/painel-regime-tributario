"""Acesso à planilha Google (CadastroFornecedores + aba de controle)."""
import json
import tomllib
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials

from . import config

_ESCOPOS = ["https://www.googleapis.com/auth/spreadsheets"]


def _credencial_streamlit() -> tuple[dict | None, list[str]]:
    """Credencial da service account nos secrets do Streamlit (lidos na hora, não
    no import). Aceita [gcp_service_account], [connections.gsheets] ou os campos
    soltos no topo. Devolve (credencial, nomes das chaves encontradas)."""
    try:
        import streamlit as st
        s = st.secrets
        chaves = list(s.keys())
    except Exception:
        return None, []
    if "gcp_service_account" in s:
        return dict(s["gcp_service_account"]), chaves
    conexoes = s.get("connections", {})
    if "gsheets" in conexoes:
        return {k: v for k, v in dict(conexoes["gsheets"]).items() if k != "spreadsheet"}, chaves
    if "private_key" in s and "client_email" in s:
        return {k: s[k] for k in chaves if k != "SPREADSHEET_ID"}, chaves
    return None, chaves


@lru_cache(maxsize=1)
def planilha() -> gspread.Spreadsheet:
    if config.GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.load(open(config.GOOGLE_SERVICE_ACCOUNT_JSON, encoding="utf-8"))
    elif config.GOOGLE_SECRETS_TOML:
        with open(config.GOOGLE_SECRETS_TOML, "rb") as f:
            info = tomllib.load(f)["gcp_service_account"]
    else:
        info, chaves = _credencial_streamlit()
        if not info:
            raise RuntimeError("Credencial do Google ausente: falta o bloco [gcp_service_account] nos secrets do "
                               f"Streamlit (chaves encontradas: {', '.join(chaves) or 'nenhuma'})")
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
