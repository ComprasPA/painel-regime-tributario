"""Validação de CNPJ e extração de e-mails dos campos do cadastro."""
import re

_RX_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _dv(base: str, pesos) -> str:
    resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(texto) -> bool:
    n = digitos(texto)
    if len(n) != 14 or len(set(n)) == 1:
        return False
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = _dv(n[:12], p1)
    return n[12:] == d1 + _dv(n[:12] + d1, [6] + p1)


def formatar_cnpj(texto) -> str:
    n = digitos(texto)
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}" if len(n) == 14 else str(texto or "")


def extrair_emails(texto) -> list[str]:
    """Aceita células com vários endereços, '"Nome" <email>', ';', ',' etc.
    Corrige o erro comum 'gmail. com'."""
    t = re.sub(r"\.\s+(com|br|net|org)\b", r".\1", str(texto or ""), flags=re.I)
    vistos = []
    for e in _RX_EMAIL.findall(t):
        e = e.lower().rstrip(".")
        if e not in vistos:
            vistos.append(e)
    return vistos
