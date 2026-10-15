"""Configuração lida do .env (credenciais e parâmetros nunca ficam no código).
No Streamlit Cloud (painel), os mesmos nomes vêm dos *secrets* do app."""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def _secrets():
    """st.secrets quando rodando no Streamlit (Cloud); {} fora dele."""
    try:
        import streamlit as st
        return dict(st.secrets)
    except Exception:
        return {}


SECRETS = _secrets() if not os.getenv("SPREADSHEET_ID") else {}


def _obrigatorio(nome: str) -> str:
    valor = (os.getenv(nome) or str(SECRETS.get(nome, ""))).strip()
    if not valor:
        raise RuntimeError(f"Configuração ausente no .env (ou nos secrets do Streamlit): {nome}")
    return valor


# Google Sheets: aceita o JSON da service account ou um secrets.toml do Streamlit
# com a seção [gcp_service_account] (o mesmo usado pelos outros apps).
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SECRETS_TOML = os.getenv("GOOGLE_SECRETS_TOML", "").strip()
SPREADSHEET_ID = _obrigatorio("SPREADSHEET_ID")
ABA_CADASTRO = os.getenv("ABA_CADASTRO", "CadastroFornecedores")
ABA_CONTROLE = os.getenv("ABA_CONTROLE", "LevantamentoRegime")

# E-mail (Outlook clássico via COM - usa a conta/assinatura já configuradas)
CONTA_REMETENTE = os.getenv("CONTA_REMETENTE", "").strip()  # vazio = conta padrão do Outlook
EMAIL_TESTE = os.getenv("EMAIL_TESTE", "").strip()
EMAILS_COPIA = os.getenv("EMAILS_COPIA", "").strip()  # CC em todos os e-mails ao fornecedor (separados por ;)
NOME_ASSINATURA =os.getenv("NOME_ASSINATURA", "Silvio").strip()  # nome da assinatura salva no Outlook

# Ritmo de envio e lembretes
TAMANHO_LOTE = int(os.getenv("TAMANHO_LOTE", "20"))
PAUSA_ENTRE_ENVIOS_SEG = float(os.getenv("PAUSA_ENTRE_ENVIOS_SEG", "8"))
DIAS_UTEIS_LEMBRETE = int(os.getenv("DIAS_UTEIS_LEMBRETE", "2"))
MAX_LEMBRETES = int(os.getenv("MAX_LEMBRETES", "3"))

# Pastas locais
PASTA_DOCUMENTOS = Path(os.getenv("PASTA_DOCUMENTOS", str(RAIZ / "documentos")))
PASTA_LOGS = RAIZ / "logs"
PASTA_SAIDA = RAIZ / "saida"
