"""Etapa 1 - tabela de controle do levantamento (aba LevantamentoRegime) e a
regra de gravação do regime no cadastro do fornecedor.

A "migration" só cria a aba e acrescenta colunas que faltarem; nunca altera
dados existentes, nem do cadastro nem do controle.
"""
import datetime

import gspread

from . import config
from .log import obter_logger
from .planilha import ler_cadastro, planilha
from .validacao import cnpj_valido, digitos, extrair_emails, formatar_cnpj

log = obter_logger()

COLUNAS = [
    "ID", "CNPJ", "FORNECEDOR", "NOMES_NO_CADASTRO", "EMAILS", "STATUS",
    "REGIME_SUGERIDO_API", "REGIME_INFORMADO", "DATA_ENVIO", "QTD_LEMBRETES",
    "DATA_ULTIMO_LEMBRETE", "DATA_RESPOSTA", "DOCUMENTO_RECEBIDO", "CAMINHO_DOCUMENTO",
    "OUTLOOK_CONVERSA_ID", "OBSERVACOES", "REVISADO_POR", "ATUALIZADO_EM",
    # regime informado fora do e-mail (telefone, WhatsApp...) e cobrança só do documento
    "ORIGEM_REGIME", "QTD_COBRANCAS_DOC", "DATA_ULTIMA_COBRANCA_DOC",
]

CANAIS_MANUAIS = ["Telefone", "WhatsApp", "Presencial", "E-mail fora do agente", "Outro"]

# pendente -> enviado -> lembrete_1..N -> respondido/revisao_manual -> comprovado
# Os demais tiram o fornecedor do envio.
STATUS = [
    "pendente", "enviado", "lembrete_1", "lembrete_2", "lembrete_3",
    "respondido", "revisao_manual", "comprovado", "erro",
    "sem_email", "cnpj_invalido", "ignorado",
]

REGIMES = ["MEI", "Simples Nacional", "Lucro Presumido", "Lucro Real"]
SUFIXO_INFORMADO = " – informado (pendente de comprovação)"


# Horário de Manaus (UTC-4, sem horário de verão) - o Streamlit Cloud roda em UTC.
FUSO = datetime.timezone(datetime.timedelta(hours=-4), "America/Manaus")


def agora_dt() -> datetime.datetime:
    return datetime.datetime.now(FUSO).replace(tzinfo=None)


def agora() -> str:
    return agora_dt().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- migration
def migrar() -> gspread.Worksheet:
    """Cria a aba de controle se não existir; se existir, só acrescenta as
    colunas que faltarem no fim do cabeçalho."""
    sh = planilha()
    try:
        ws = sh.worksheet(config.ABA_CONTROLE)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(config.ABA_CONTROLE, rows=1000, cols=len(COLUNAS))
        ws.update([COLUNAS], "A1", value_input_option="RAW")
        ws.freeze(rows=1)
        log.info(f"Aba '{config.ABA_CONTROLE}' criada com {len(COLUNAS)} colunas")
        return ws
    cab = ws.row_values(1)
    faltando = [c for c in COLUNAS if c not in cab]
    if faltando:
        if ws.col_count < len(cab) + len(faltando):
            ws.add_cols(len(cab) + len(faltando) - ws.col_count)
        ws.update([faltando], gspread.utils.rowcol_to_a1(1, len(cab) + 1), value_input_option="RAW")
        log.info(f"Colunas acrescentadas em '{config.ABA_CONTROLE}': {faltando}")
    else:
        log.info(f"Aba '{config.ABA_CONTROLE}' já está no esquema atual")
    return ws


# ---------------------------------------------------------------- controle
class Controle:
    """Lê a aba uma vez, acumula alterações e grava tudo em salvar()."""

    def __init__(self):
        self.ws = planilha().worksheet(config.ABA_CONTROLE)
        valores = self.ws.get_all_values()
        self.cab = valores[0]
        self.col = {c: i for i, c in enumerate(self.cab)}
        self.linhas = {}  # ID -> (nº linha, dict)
        for n, v in enumerate(valores[1:], start=2):
            v = v + [""] * (len(self.cab) - len(v))
            reg = {c: v[i] for i, c in enumerate(self.cab)}
            if reg["ID"]:
                self.linhas[reg["ID"]] = (n, reg)
        self._celulas, self._novas = [], []

    def registros(self, *status) -> list[dict]:
        regs = [r for _, r in self.linhas.values()]
        return [r for r in regs if not status or r["STATUS"] in status]

    def atualizar(self, id_: str, **campos):
        n, reg = self.linhas[id_]
        campos["ATUALIZADO_EM"] = agora()
        for k, v in campos.items():
            if k == "STATUS":
                assert v in STATUS, v
            reg[k] = str(v)
            self._celulas.append(gspread.Cell(n, self.col[k] + 1, str(v)))

    def incluir(self, reg: dict):
        reg = {c: str(reg.get(c, "")) for c in self.cab} | {"ATUALIZADO_EM": agora()}
        self._novas.append([reg[c] for c in self.cab])
        self.linhas[reg["ID"]] = (None, reg)

    def salvar(self):
        if self._celulas:
            self.ws.update_cells(self._celulas, value_input_option="RAW")
        if self._novas:
            self.ws.append_rows(self._novas, value_input_option="RAW", table_range="A1")
        log.info(f"Controle salvo: {len(self._celulas)} célula(s) alterada(s), {len(self._novas)} linha(s) nova(s)")
        self._celulas, self._novas = [], []


def _id_fornecedor(reg: dict) -> str:
    d = digitos(reg["CNPJ"])
    return d if len(d) in (11, 14) else "SEMCNPJ-" + "".join(ch for ch in reg["FORNECEDOR"].upper() if ch.isalnum())[:40]


def sincronizar() -> dict:
    """Garante uma linha de controle por fornecedor (por CNPJ) do cadastro.
    Inclui quem ainda não está. Das linhas existentes, só reavalia as que estão
    fora do envio por falta de dado (sem_email / cnpj_invalido), para que entrem
    no envio depois que o cadastro for corrigido; as demais não são alteradas.
    CNPJ repetido no cadastro (mesma empresa com duas grafias) vira uma linha só."""
    _, _, cadastro = ler_cadastro()
    grupos = {}
    for reg in cadastro:
        if reg["FORNECEDOR"]:
            grupos.setdefault(_id_fornecedor(reg), []).append(reg)

    ctl = Controle()
    contagem = {}
    for id_, regs in grupos.items():
        existente = ctl.linhas.get(id_)
        if existente and existente[1]["STATUS"] not in ("sem_email", "cnpj_invalido"):
            continue
        emails = []
        for r in regs:
            emails += [e for e in extrair_emails(r["EMAIL"]) if e not in emails]
        d = digitos(regs[0]["CNPJ"])
        if len(d) == 11:
            status, obs = "ignorado", "Pessoa física (CPF): sem regime de empresa"
        elif not cnpj_valido(d):
            status, obs = "cnpj_invalido", "CNPJ vazio ou inválido no cadastro"
        elif not emails:
            status, obs = "sem_email", "Sem e-mail válido no cadastro"
        else:
            status, obs = "pendente", ""
        if existente:
            antes = existente[1]["STATUS"]
            if status != antes or "; ".join(emails) != existente[1]["EMAILS"]:
                ctl.atualizar(id_, STATUS=status, EMAILS="; ".join(emails), OBSERVACOES=obs)
                contagem[f"{antes}->{status}"] = contagem.get(f"{antes}->{status}", 0) + 1
            continue
        ctl.incluir({
            "ID": id_, "CNPJ": formatar_cnpj(d) if len(d) == 14 else regs[0]["CNPJ"],
            "FORNECEDOR": regs[0]["FORNECEDOR"],
            "NOMES_NO_CADASTRO": " | ".join(r["FORNECEDOR"] for r in regs) if len(regs) > 1 else "",
            "EMAILS": "; ".join(emails), "STATUS": status, "QTD_LEMBRETES": "0",
            "DOCUMENTO_RECEBIDO": "não", "OBSERVACOES": obs,
        })
        contagem[status] = contagem.get(status, 0) + 1
    # fornecedor que estava sem CNPJ e ganhou CNPJ no cadastro: a linha antiga fica órfã
    for id_, (_, reg) in list(ctl.linhas.items()):
        if id_.startswith("SEMCNPJ-") and id_ not in grupos and reg["STATUS"] == "cnpj_invalido":
            ctl.atualizar(id_, STATUS="ignorado", OBSERVACOES="Substituída: o fornecedor ganhou CNPJ no cadastro (nova linha)")
            contagem["cnpj_invalido->substituida"] = contagem.get("cnpj_invalido->substituida", 0) + 1
    ctl.salvar()
    log.info(f"Sincronização (novos por status / reavaliados 'antes->depois'): {contagem or 'nada a fazer'}")
    return contagem


# ---------------------------------------------------------------- regra do regime no cadastro
def regime_base(valor: str) -> str:
    """'Simples Nacional – informado (...)' -> 'Simples Nacional'; 'MEI – Microempreendedor...' -> 'MEI'."""
    v = str(valor or "").replace(SUFIXO_INFORMADO, "").strip()
    return "MEI" if v.upper().startswith("MEI") else v



def gravar_regime_no_cadastro(cnpj: str, regime: str, comprovado: bool, forcar: bool = False,
                              lote: dict | None = None) -> str:
    # lote = {"cadastro": ler_cadastro(), "celulas": []}: lê a planilha uma vez e grava tudo no fim
    # (o Google limita leituras por minuto - incidente de 15/10/2026 com dezenas de respostas)
    """Grava REGIME_TRIBUTARIO em todas as linhas do cadastro com esse CNPJ.

    Só o regime ("MEI", "Simples Nacional", "Lucro Presumido", "Lucro Real" - mesma lista do
    app de dados bancários), sem status: decisão do usuário em 15/10/2026. Se o documento
    chegou ou não fica no controle (STATUS/DOCUMENTO_RECEBIDO). `comprovado` não muda o valor.
    Valores antigos com o sufixo " – informado (...)" são tratados como o mesmo regime.

    Não sobrescreve um regime diferente que já esteja no cadastro (gravado à mão
    ou pelo Painel): devolve 'conflito' para o caso ir para revisão manual.
    forcar=True (só no registro manual, confirmado pelo usuário) substitui.
    Devolve 'gravado', 'sem_alteracao' ou 'conflito'.
    """
    assert regime in REGIMES, regime
    novo = regime  # sem " – informado (pendente de comprovação)" (decisão de 15/10/2026)
    ws, cab, cadastro = lote["cadastro"] if lote else ler_cadastro()
    col = cab.index("REGIME_TRIBUTARIO") + 1
    alvo = [r for r in cadastro if digitos(r["CNPJ"]) == digitos(cnpj)]
    celulas = []
    for r in alvo:
        atual = r["REGIME_TRIBUTARIO"]
        base_atual = regime_base(atual)
        if atual == novo:
            continue
        if atual and base_atual != regime and forcar:
            log.warning(f"Regime substituído no cadastro por decisão do usuário (linha {r['_linha']}, CNPJ {cnpj}): '{atual}' -> '{novo}'")
        elif atual and base_atual != regime:
            log.warning(f"Conflito de regime no cadastro (linha {r['_linha']}, CNPJ {cnpj}): '{atual}' x '{novo}'")
            return "conflito"
        celulas.append(gspread.Cell(r["_linha"], col, novo))  # vazio, ou mesmo regime em formato antigo
    if celulas and lote is not None:  # em lote: acumula e atualiza a cópia local (sem ler/gravar a planilha agora)
        lote["celulas"].extend(celulas)
        for r in alvo:
            r["REGIME_TRIBUTARIO"] = novo
        log.info(f"Regime a gravar no cadastro (CNPJ {cnpj}, {len(celulas)} linha(s)): {novo}")
        return "gravado"
    if celulas:
        ws.update_cells(celulas, value_input_option="RAW")
        log.info(f"Regime gravado no cadastro (CNPJ {cnpj}, {len(celulas)} linha(s)): {novo}")
        return "gravado"
    return "sem_alteracao"


# ---------------------------------------------------------------- regime informado por outro canal
def registrar_regime_manual(id_: str, regime: str, canal: str, registrado_por: str,
                            documento_recebido: bool = False, caminho_documento: str = "",
                            observacao: str = "", forcar: bool = False) -> str:
    """O fornecedor informou o regime fora do e-mail (telefone, WhatsApp...).

    Grava no controle com ORIGEM_REGIME = "manual – <canal>" e no cadastro com a
    mesma regra da resposta por e-mail. A partir daí o fornecedor sai do envio do
    e-mail completo e passa a ser cobrado só do documento (ver tipo_cobranca).

    Devolve 'ok', 'conflito' (cadastro já tem outro regime; repetir com forcar=True
    após o usuário confirmar) ou 'ja_comprovado'.
    """
    assert regime in REGIMES, regime
    assert canal in CANAIS_MANUAIS, canal
    migrar()  # garante as colunas novas
    ctl = Controle()
    reg = ctl.linhas[id_][1]
    if reg["STATUS"] == "comprovado" and not forcar:
        return "ja_comprovado"
    if cnpj_valido(id_):
        res = gravar_regime_no_cadastro(id_, regime, comprovado=documento_recebido, forcar=forcar)
        if res == "conflito":
            return "conflito"
    quando = agora_dt()
    nota = f"{quando:%d/%m/%Y} regime informado por {canal.lower()} (registro manual de {registrado_por})"
    if observacao.strip():
        nota += f": {observacao.strip()}"
    campos = {
        "STATUS": "comprovado" if documento_recebido else "respondido",
        "REGIME_INFORMADO": regime, "ORIGEM_REGIME": f"manual – {canal}",
        "DATA_RESPOSTA": quando.strftime("%Y-%m-%d %H:%M:%S"),
        "DOCUMENTO_RECEBIDO": "sim" if documento_recebido else "não",
        "REVISADO_POR": registrado_por,
        "OBSERVACOES": " | ".join(x for x in (reg.get("OBSERVACOES", ""), nota) if x),
    }
    if caminho_documento:
        campos["CAMINHO_DOCUMENTO"] = caminho_documento
    ctl.atualizar(id_, **campos)
    ctl.salvar()
    log.info(f"Regime registrado manualmente: {reg['FORNECEDOR']} (CNPJ {reg['CNPJ']}) = {regime} via {canal}, "
             f"documento {'recebido' if documento_recebido else 'pendente'}, por {registrado_por}")
    return "ok"


def tipo_cobranca(reg: dict) -> str | None:
    """O que ainda falta pedir ao fornecedor:
    'regime_e_documento' – ainda não informou o regime (e-mail completo);
    'documento'          – já informou (por e-mail ou por outro canal) e falta o comprovante;
    None                 – nada a cobrar (comprovado, fora do envio, revisão manual)."""
    if reg["STATUS"] in ("pendente", "enviado", "lembrete_1", "lembrete_2", "lembrete_3"):
        return "regime_e_documento"
    if reg["STATUS"] == "respondido" and reg.get("DOCUMENTO_RECEBIDO", "").lower() != "sim" and reg.get("EMAILS"):
        return "documento"
    return None
