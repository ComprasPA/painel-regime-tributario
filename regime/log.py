"""Log de todas as ações em arquivo, com e-mails mascarados (LGPD)."""
import logging
import re
import sys

from . import config

_RX_EMAIL = re.compile(r"([\w.+-]{1,2})[\w.+-]*@([\w-]+(?:\.[\w-]+)+)")


def mascarar(texto) -> str:
    """fulano@empresa.com.br -> fu***@empresa.com.br"""
    return _RX_EMAIL.sub(r"\1***@\2", str(texto))


class _FiltroMascara(logging.Filter):
    def filter(self, record):
        record.msg = mascarar(record.getMessage())
        record.args = ()
        return True


def obter_logger() -> logging.Logger:
    logger = logging.getLogger("regime")
    if logger.handlers:
        return logger
    config.PASTA_LOGS.mkdir(exist_ok=True)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    arq = logging.FileHandler(config.PASTA_LOGS / "agente.log", encoding="utf-8")
    tela = logging.StreamHandler(sys.stdout)
    for h in (arq, tela):
        h.setFormatter(fmt)
        h.addFilter(_FiltroMascara())
        logger.addHandler(h)
    return logger
