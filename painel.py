"""Painel de acompanhamento do levantamento de regime tributário.

Lê a aba LevantamentoRegime (que o agente atualiza a cada envio, resposta e
documento) e se atualiza sozinho nos horários de ATUALIZACOES (dias úteis,
horário comercial). Fora deles não lê a planilha; o botão "Atualizar agora"
força a leitura a qualquer momento.

    streamlit run painel.py
"""
import datetime
import html
import io

import base64
from pathlib import Path

import pandas as pd
import streamlit as st


# Decisão do usuário (14-15/10/2026): de 2 em 2 horas no horário comercial, segunda a sexta.
ATUALIZACOES = [datetime.time(h, 15) for h in (8, 10, 12, 14, 16)]  # 15 min após a leitura do agente (08, 10, 12, 14, 16h)
VERIFICAR_HORARIO_SEG = 300  # só confere o relógio; a planilha é lida apenas quando muda o horário


def horario_vigente(agora: datetime.datetime) -> datetime.datetime:
    """Último horário de atualização já alcançado (dias úteis 08-16h, de 2 em 2 h)."""
    dia = agora
    while True:
        if dia.weekday() < 5:
            passados = [datetime.datetime.combine(dia.date(), t) for t in ATUALIZACOES
                        if datetime.datetime.combine(dia.date(), t) <= agora]
            if passados:
                return passados[-1]
        dia = datetime.datetime.combine(dia.date() - datetime.timedelta(days=1), datetime.time(23, 59))


def proximo_horario(agora: datetime.datetime) -> datetime.datetime:
    dia = agora.date()
    while True:
        if dia.weekday() < 5:
            for t in ATUALIZACOES:
                momento = datetime.datetime.combine(dia, t)
                if momento > agora:
                    return momento
        dia += datetime.timedelta(days=1)

st.set_page_config(page_title="Regime Tributário | Parente Andrade", page_icon="📋", layout="wide")

try:
    from regime.controle import CANAIS_MANUAIS, COLUNAS, Controle, agora_dt, registrar_regime_manual
except Exception as erro:  # ex.: secret ausente no Streamlit Cloud - mostra em vez de travar
    st.error(f"O painel não conseguiu iniciar: {erro}")
    st.info("Confira em Settings → Secrets: `SPREADSHEET_ID = \"...\"` na primeira linha (antes de qualquer "
            "[seção]) e o bloco `[gcp_service_account]` completo, igual ao dos outros apps.")
    st.stop()

ROTULO = {
    "pendente": "Pendente", "enviado": "Enviado", "lembrete_1": "Lembrete 1", "lembrete_2": "Lembrete 2",
    "lembrete_3": "Lembrete 3", "respondido": "Respondido", "revisao_manual": "Revisão manual",
    "comprovado": "Comprovado", "erro": "Erro no envio", "sem_email": "Sem e-mail",
    "cnpj_invalido": "CNPJ inválido", "ignorado": "Ignorado (PF)",
}
# ordem e cor da barra de andamento
ETAPAS = [
    ("Comprovado", ["comprovado"], "#1baf7a"),
    ("Respondido", ["respondido"], "#619935"),
    ("Revisão manual", ["revisao_manual"], "#eb6834"),
    ("Em lembrete", ["lembrete_1", "lembrete_2", "lembrete_3"], "#eda100"),
    ("Enviado", ["enviado"], "#C5DDA8"),
    ("Pendente", ["pendente"], "#b4b2a9"),
]
ENVIADOS = {"enviado", "lembrete_1", "lembrete_2", "lembrete_3", "respondido", "revisao_manual", "comprovado"}
RESPONDERAM = {"respondido", "revisao_manual", "comprovado"}
AGUARDANDO = {"enviado", "lembrete_1", "lembrete_2", "lembrete_3"}
FORA = {"sem_email", "cnpj_invalido", "erro"}
REGIMES = ["MEI", "Simples Nacional", "Lucro Presumido", "Lucro Real"]
# quem pode aparecer em "Registrado por" (Suprimentos)
USUARIOS = ["Silvio Silveira", "Ednilson Santos Brito", "Daiana Lima", "Fabio Ferreira", "Rosicleide Correa"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
/* Visual PA (Parente Andrade): verde e laranja do logo. Segue o claro/escuro do sistema. */
:root {
  --pa-bg: #F1F7EA; --pa-surface: #FFFFFF; --pa-border: #D5E4C6; --pa-text: #1E2B19; --pa-sub: #5B6A52;
  --pa-input: #FFFFFF; --pa-acento: #619935; --pa-acento-deep: #4C7D27; --pa-laranja: #E8A838;
  --pa-sombra: rgba(34, 56, 24, 0.10); --pa-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --pa-bg: #10150D; --pa-surface: #1A2116; --pa-border: #2C3827; --pa-text: #EDF3E6; --pa-sub: #9DB091;
    --pa-input: #222B1D; --pa-acento: #7DB84A; --pa-acento-deep: #619935; --pa-laranja: #F0B445;
    --pa-sombra: rgba(0, 0, 0, 0.45); --pa-scheme: dark;
  }
}
html, body, .stApp, [class*="st-"], button, input, textarea {font-family: 'Inter', 'Segoe UI', sans-serif;}
.stApp {background: var(--pa-bg); color: var(--pa-text);}
#MainMenu, footer, [data-testid='stToolbar'] {visibility: hidden;}
.block-container {padding-top: 3rem; max-width: 1500px;}
hr {border-color: var(--pa-border) !important;}

/* textos */
label, div[data-testid="stWidgetLabel"] p, div[data-testid="stMarkdownContainer"] p,
div[data-testid="stMarkdownContainer"] li, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {color: var(--pa-text) !important;}
div[data-testid="stWidgetLabel"] p {font-weight: 600; font-size: 13px;}
div[data-testid="stCaptionContainer"], div[data-testid="stCaptionContainer"] p,
div[data-testid="stCaptionContainer"] * {color: var(--pa-sub) !important;}
div[data-testid="stHeading"] h3 {font-weight: 700; letter-spacing: -0.2px; border-left: 5px solid var(--pa-laranja); padding-left: 12px;}

/* faixa de topo com o logo (igual nos dois temas) */
.cabecalho {display: flex; flex-wrap: wrap; align-items: center; gap: 22px; padding: 16px 28px;
  border-radius: 18px; border-bottom: 4px solid var(--pa-laranja);
  background: linear-gradient(120deg, #162610 0%, #2A4A1A 55%, #3F6E26 100%); box-shadow: 0 8px 24px var(--pa-sombra);}
.cabecalho img {height: 54px; width: auto;}
.cabecalho > div {min-width: 0;}
.brand-eyebrow {font-weight: 600; font-size: 13.5px; letter-spacing: .04em; color: #CFE3BE; display: block; margin-top: 3px;}
.brand-subtitle {font-weight: 800; font-size: 26px; letter-spacing: -0.3px; color: #FFFFFF !important; display: block; line-height: 1.15;}

/* cartões: KPIs, blocos com borda, expansor, tabela */
.kpi {background: var(--pa-surface); border: 1px solid var(--pa-border); border-radius: 16px; padding: 12px 16px;
  box-shadow: 0 6px 20px var(--pa-sombra); color: var(--pa-text);}
.kpi .r {font-size: 13px; opacity: .8; margin: 0; color: var(--pa-sub);}
.kpi .v {font-size: 28px; font-weight: 700; margin: 0; line-height: 1.2;}
.kpi .s {font-size: 12px; opacity: .75; margin: 0; color: var(--pa-sub);}
.st-key-card_regime, .st-key-card_agente {background: var(--pa-surface); border-color: var(--pa-border) !important; border-radius: 16px; box-shadow: 0 6px 20px var(--pa-sombra);}
div[data-testid="stExpander"] details {background: var(--pa-surface); border: 1px solid var(--pa-border) !important; border-radius: 16px; box-shadow: 0 6px 20px var(--pa-sombra);}
div[data-testid="stExpander"] summary, div[data-testid="stExpander"] summary * {color: var(--pa-text) !important; font-weight: 600;}
div[data-testid="stDataFrame"] {color-scheme: var(--pa-scheme); border: 1px solid var(--pa-border); border-radius: 14px; overflow: hidden; box-shadow: 0 6px 20px var(--pa-sombra);}
div[data-testid="stDialog"] > div {border-radius: 20px !important; border-top: 5px solid var(--pa-laranja); background-color: var(--pa-surface) !important;}

/* campos */
div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-baseweb="base-input"] {
  border-radius: 10px !important; background-color: var(--pa-input) !important; border-color: var(--pa-border) !important;}
div[data-baseweb="select"] div, div[data-baseweb="select"] span {color: var(--pa-text);}
div[data-testid="stTextInput"] input {background-color: var(--pa-input) !important; color: var(--pa-text) !important;}
div[data-testid="stTextInput"] input::placeholder {color: var(--pa-sub); opacity: .75;}
ul[role="listbox"] {background-color: var(--pa-surface) !important;}
li[role="option"] {color: var(--pa-text) !important;}
div[data-baseweb="input"]:focus-within, div[data-baseweb="select"]:focus-within > div {
  border-color: var(--pa-acento) !important; box-shadow: 0 0 0 3px color-mix(in srgb, var(--pa-acento) 20%, transparent) !important;}
span[data-baseweb="tag"] {background-color: var(--pa-acento) !important; color: #FFFFFF !important; border-radius: 8px !important;}
input[type="radio"], input[type="checkbox"] {accent-color: var(--pa-acento);}

/* botões */
div.stButton button, div.stFormSubmitButton button, div.stDownloadButton button {border-radius: 10px; font-weight: 600; transition: all .15s ease;}
div.stFormSubmitButton button[kind^="primary"], div.stButton button[kind^="primary"], div.stDownloadButton button[kind^="primary"] {
  background: linear-gradient(135deg, var(--pa-acento), var(--pa-acento-deep)) !important; border: none !important; color: #FFFFFF !important;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--pa-acento) 33%, transparent);}
div.stFormSubmitButton button[kind^="primary"]:hover, div.stButton button[kind^="primary"]:hover, div.stDownloadButton button[kind^="primary"]:hover {
  transform: translateY(-1px); box-shadow: 0 6px 16px color-mix(in srgb, var(--pa-acento) 47%, transparent);}
div.stFormSubmitButton button[kind^="secondary"], div.stButton button[kind^="secondary"], div.stDownloadButton button[kind^="secondary"] {
  background-color: var(--pa-surface) !important; border: 1.5px solid var(--pa-laranja) !important; color: var(--pa-text) !important;}
div.stFormSubmitButton button[kind^="secondary"]:hover, div.stButton button[kind^="secondary"]:hover, div.stDownloadButton button[kind^="secondary"]:hover {
  background-color: var(--pa-laranja) !important; border-color: var(--pa-laranja) !important; color: #20170A !important; transform: translateY(-1px);}

/* andamento, regimes e atualizações */
.barra {display: flex; height: 24px; border-radius: 6px; overflow: hidden; gap: 2px; flex: 1; min-width: 0;}
.barra-linha {display: flex; align-items: center; gap: 14px; margin: 4px 0 6px;}
.pct {text-align: right; line-height: 1.1; white-space: nowrap;}
.pct b {font-size: 22px; font-weight: 700; display: block;}
.pct small {font-size: 11.5px; opacity: .7;}
.leg {display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; opacity: .85;}
.leg span i {display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px;}
.reg {display: grid; grid-template-columns: 130px 1fr 40px; gap: 6px 10px; align-items: center; font-size: 14px;}
.reg b {display: block; height: 10px; background: var(--pa-acento); border-radius: 0 3px 3px 0;}
.feed {font-size: 13px; line-height: 1.9;}
.feed small {opacity: .6; margin-right: 6px;}
.aovivo {font-size: 13px; opacity: .8;}
.aovivo i {display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #0ca30c; margin-right: 6px;}
/* celular: cabeçalho empilhado e compacto */
@media (max-width: 640px) {
  .block-container {padding-top: 3.6rem;}
  .cabecalho {padding: 12px 16px; gap: 12px;}
  .cabecalho img {height: 40px;}
  .brand-eyebrow {font-size: 11px;}
  .brand-subtitle {font-size: 19px;}
  .aovivo {text-align: left !important; font-size: 12px; margin: 4px 0 !important;}
  .signature-fixed {display: none;}
}
.signature-fixed { position: fixed; bottom: 12px; left: 20px; color: var(--pa-sub); font-size: 11px; font-weight: 700; letter-spacing: 0.5px; z-index: 999999; pointer-events: none; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(max_entries=3, show_spinner=False)
def carregar(horario: str) -> tuple[pd.DataFrame, datetime.datetime]:
    """Uma leitura por horário de atualização (o argumento é a chave do cache)."""
    df = pd.DataFrame(Controle().registros())
    return df.reindex(columns=list(dict.fromkeys(list(df.columns) + COLUNAS)), fill_value="").fillna(""), \
        agora_dt()


@st.cache_data(max_entries=3, show_spinner=False)
def abc_fornecedores(horario: str) -> pd.DataFrame:
    """Ranking ABC por CNPJ (notas de entrada 2024-2026), lido da aba ABC_Fornecedores da planilha.
    Uma leitura por horário de atualização. Se a aba não puder ser lida, usa o CSV local."""
    try:
        from regime.planilha import planilha
        valores = planilha().worksheet("ABC_Fornecedores").get_all_values(value_render_option="UNFORMATTED_VALUE")
        df = pd.DataFrame(valores[1:], columns=valores[0])
    except Exception:
        arq = Path(__file__).parent / "dados" / "abc_fornecedores.csv"
        if not arq.exists():
            return pd.DataFrame(columns=["CNPJ", "QTD_NOTAS", "VALOR_TOTAL", "ABC_QTD", "ABC_VALOR"])
        df = pd.read_csv(arq, sep=";", dtype=str, keep_default_na=False)
    df["CNPJ"] = df["CNPJ"].astype(str).str.zfill(14)
    return df


@st.cache_data
def logo_base64(nome: str) -> str:
    arq = Path(__file__).parent / "assets" / f"{nome}.png"
    return base64.b64encode(arq.read_bytes()).decode() if arq.exists() else ""


def cabecalho(col, universo: int):
    """Faixa de topo no visual PA: logo de texto claro sobre o gradiente verde escuro (igual nos dois temas)."""
    logo = logo_base64("logo_escuro") or logo_base64("logo")
    img = f'<img src="data:image/png;base64,{logo}" alt="Parente Andrade">' if logo else ""
    col.markdown(f'''<div class="cabecalho">{img}<div>
        <span class="brand-subtitle">Levantamento de regime tributário</span>
        <span class="brand-eyebrow">Gestão de Compras | Parente Andrade</span></div></div>''', unsafe_allow_html=True)


def diverge(informado: str, api: str) -> bool:
    if not informado or not api or api.startswith("CNPJ não encontrado"):
        return False
    if informado == "MEI":
        return not api.startswith("MEI")
    if informado == "Simples Nacional":
        return not api.startswith("Simples Nacional")
    return api.startswith(("MEI", "Simples Nacional"))


def kpi(col, rotulo, valor, sub=""):
    col.markdown(f'<div class="kpi"><p class="r">{rotulo}</p><p class="v">{valor}</p><p class="s">{sub}</p></div>',
                 unsafe_allow_html=True)


def frase_evento(r) -> str:
    nome = html.escape(r["FORNECEDOR"][:45])
    st_ = r["STATUS"]
    if r["ORIGEM_REGIME"].startswith("manual") and st_ in ("respondido", "comprovado"):
        canal = html.escape(r["ORIGEM_REGIME"].split("–")[-1].strip().lower())
        extra = " e comprovante recebido" if st_ == "comprovado" else "; cobrando só o documento"
        return f"{nome}: {html.escape(r['REGIME_INFORMADO'])} registrado à mão ({canal}){extra}"
    if st_ == "comprovado":
        return f"{nome} enviou o comprovante ({html.escape(r['REGIME_INFORMADO'])})"
    if st_ == "respondido":
        return f"{nome} respondeu: {html.escape(r['REGIME_INFORMADO'])}"
    if st_ == "revisao_manual":
        return f"{nome}: resposta para revisão manual"
    if st_.startswith("lembrete_"):
        return f"{nome}: {ROTULO[st_].lower()} enviado"
    if st_ == "enviado":
        envio = r["DATA_ENVIO"]
        if envio and envio > agora_dt().strftime("%Y-%m-%d %H:%M:%S"):
            return f"{nome}: e-mail agendado para {envio[8:10]}/{envio[5:7]} {envio[11:16]}"
        return f"{nome}: e-mail enviado"
    if st_ == "erro":
        return f"{nome}: erro no envio"
    return f"{nome}: {ROTULO.get(st_, st_).lower()}"


def excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Levantamento")
    return buf.getvalue()


def formulario_manual(df: pd.DataFrame):
    """Regime informado pelo fornecedor fora do e-mail (telefone, WhatsApp...).
    Fica marcado como manual e o agente passa a cobrar só o documento."""
    if msg := st.session_state.pop("msg_manual", None):
        (st.success if msg[0] == "ok" else st.warning)(msg[1])
    with st.expander("Registrar regime informado por outro canal (telefone, WhatsApp...)"):
        opcoes = df.sort_values("FORNECEDOR")
        rotulos = {r["ID"]: f"{r['FORNECEDOR']} — {r['CNPJ']}" for _, r in opcoes.iterrows()}
        conflito = st.session_state.get("conflito_manual")
        with st.form("form_manual", clear_on_submit=False):
            id_ = st.selectbox("Fornecedor", list(rotulos), format_func=rotulos.get, index=None,
                               placeholder="Digite o nome ou o CNPJ")
            c1, c2 = st.columns(2)
            regime = c1.radio("Regime informado", ["MEI", "Simples Nacional", "Lucro Presumido", "Lucro Real"],
                              index=None, horizontal=True)
            canal = c2.selectbox("Como o fornecedor informou", CANAIS_MANUAIS, index=None, placeholder="Selecione")
            c3, c4 = st.columns(2)
            por = c3.selectbox("Registrado por", USUARIOS + ["Outro"], index=None, placeholder="Seu nome")
            outro = c3.text_input("Seu nome (se escolheu Outro)", label_visibility="collapsed",
                                  placeholder="Seu nome, se escolheu Outro")
            por = (outro.strip() if por == "Outro" else por) or ""
            doc = c4.checkbox("O documento comprobatório também já chegou")
            obs = st.text_input("Observação (opcional)", placeholder="Ex.: falou com Maria do financeiro em 15/10")
            forcar = False
            if conflito:
                forcar = st.checkbox(f"Substituir o regime que já está no cadastro de {rotulos.get(conflito, '')}")
            enviar = st.form_submit_button("Registrar regime", type="primary")
        if enviar:
            faltando = [n for n, v in (("fornecedor", id_), ("regime", regime), ("canal", canal), ("quem registrou", por.strip())) if not v]
            if faltando:
                st.warning("Preencha: " + ", ".join(faltando) + ".")
                return
            res = registrar_regime_manual(id_, regime, canal, por.strip(), documento_recebido=doc, observacao=obs,
                                          forcar=forcar and conflito == id_)
            nome = rotulos[id_].split(" — ")[0]
            if res == "conflito":
                st.session_state["conflito_manual"] = id_
                st.session_state["msg_manual"] = ("aviso", f"{nome}: o cadastro já tem outro regime. Confira e, se for o "
                                                  "caso, marque “Substituir” e registre de novo.")
            elif res == "ja_comprovado":
                st.session_state["msg_manual"] = ("aviso", f"{nome} já está comprovado. Nada foi alterado.")
            else:
                st.session_state.pop("conflito_manual", None)
                st.session_state["msg_manual"] = ("ok", f"{nome}: {regime} registrado ({canal.lower()}). " + (
                    "Fornecedor comprovado." if doc else "A partir de agora o agente cobra só o documento."))
            carregar.clear()
            st.rerun()


@st.fragment(run_every=VERIFICAR_HORARIO_SEG)
def painel():
    agora = agora_dt()
    try:
        df, lido_em = carregar(horario_vigente(agora).isoformat())
    except Exception as e:  # planilha fora do ar não derruba o painel (erro não fica em cache)
        st.error(f"Não foi possível ler a planilha agora ({e}). Nova tentativa em {VERIFICAR_HORARIO_SEG // 60} min.")
        return
    base = df[df["STATUS"] != "ignorado"]
    cont = base["STATUS"].value_counts()
    n = lambda grupo: int(cont[cont.index.isin(grupo)].sum())
    universo = len(base) - n(FORA)
    enviados, responderam = n(ENVIADOS), n(RESPONDERAM)
    doc = int((base["DOCUMENTO_RECEBIDO"].str.lower() == "sim").sum())
    em_lembrete = n({"lembrete_1", "lembrete_2", "lembrete_3"})

    topo_esq, topo_dir = st.columns([3, 1], vertical_alignment="center")
    cabecalho(topo_esq, universo)
    prox = proximo_horario(agora)
    quando = f"{prox:%H:%M}" if prox.date() == agora.date() else f"{prox:%d/%m} às {prox:%H:%M}"
    lido = f"{lido_em:%H:%M}" if lido_em.date() == agora.date() else f"{lido_em:%d/%m %H:%M}"
    topo_dir.markdown(f'<p class="aovivo" style="text-align:right;margin:0 0 6px"><i></i>Atualizado às {lido} · '
                      f'próxima: {quando}</p>', unsafe_allow_html=True)
    if topo_dir.button("Atualizar agora", width="stretch"):
        carregar.clear()
        st.rerun()

    c = st.columns(7)
    kpi(c[0], "Enviados", enviados, f"de {universo}")
    kpi(c[1], "Responderam", responderam, f"{responderam / enviados:.0%} dos enviados" if enviados else "—")
    kpi(c[2], "Documento recebido", doc, "comprovados")
    kpi(c[3], "Aguardando resposta", n(AGUARDANDO), f"{em_lembrete} em lembrete")
    kpi(c[4], "Revisão manual", n({"revisao_manual"}), "resposta ambígua ou conflito")
    kpi(c[5], "Fora do envio", n(FORA), "sem e-mail, CNPJ inválido ou erro")
    acrescimos = int((df.get("ORIGEM_CADASTRO", pd.Series(dtype=str)) == "acréscimo manual").sum())
    kpi(c[6], "Acréscimo manual", acrescimos, "fornecedores fora da base")

    st.markdown(f"<p style='margin:18px 0 0;font-size:14px;opacity:.8'>Andamento dos {universo} fornecedores no envio</p>",
                unsafe_allow_html=True)
    partes, legenda = [], []
    for rotulo, sts, cor in ETAPAS:
        q = n(set(sts))
        if q:
            partes.append(f'<div style="flex:{q};background:{cor}" title="{rotulo}: {q}"></div>')
        legenda.append(f'<span><i style="background:{cor}"></i>{rotulo} {q}</span>')
    # progresso = fornecedores que responderam ao levantamento (respondido + comprovado) sobre os que estão no envio
    informaram = n(RESPONDERAM)  # mesma conta do card "Responderam" (respondido + revisão manual + comprovado)
    pct = informaram / universo if universo else 0
    pct_comp = n({"comprovado"}) / universo if universo else 0
    st.markdown(f'<div class="barra-linha"><div class="barra">{"".join(partes)}</div>'
                f'<div class="pct" title="{informaram} de {universo} já informaram o regime"><b>{pct:.0%}</b>'
                f'<small>responderam · {pct_comp:.0%} comprovados</small></div></div>'
                f'<div class="leg">{"".join(legenda)}</div>', unsafe_allow_html=True)

    st.write("")
    e, d = st.columns(2)
    with e.container(border=True, key="card_regime"):
        st.markdown("**Regime informado pelos fornecedores**")
        inf = base["REGIME_INFORMADO"].value_counts()
        maior = max([int(inf.get(r, 0)) for r in REGIMES] + [1])
        linhas = "".join(f'<span>{r}</span><b style="width:{int(inf.get(r, 0)) / maior:.0%}"></b>'
                         f'<span style="text-align:right">{int(inf.get(r, 0))}</span>' for r in REGIMES)
        st.markdown(f'<div class="reg">{linhas}</div>', unsafe_allow_html=True)
        div = int(base.apply(lambda r: diverge(r["REGIME_INFORMADO"], r["REGIME_SUGERIDO_API"]), axis=1).sum())
        st.caption(f"Divergências entre o informado e a consulta de CNPJ: {div}")
    with d.container(border=True, key="card_agente"):
        st.markdown("**Últimas atualizações do agente**")
        mov = base[base["STATUS"].isin(ENVIADOS | {"erro"})].sort_values("ATUALIZADO_EM", ascending=False).head(8)
        if mov.empty:
            st.caption("Nenhum envio ainda. As respostas aparecem aqui assim que o agente as ler.")
        else:
            itens = "".join(f"<div><small>{r['ATUALIZADO_EM'][8:10]}/{r['ATUALIZADO_EM'][5:7]} "
                            f"{r['ATUALIZADO_EM'][11:16]}</small>{frase_evento(r)}</div>"
                            for _, r in mov.iterrows())
            st.markdown(f'<div class="feed">{itens}</div>', unsafe_allow_html=True)

    st.write("")
    formulario_manual(df)

    st.write("")
    f1, f2, f3, f4, f5 = st.columns([3, 2, 2, 1.5, 1.5])
    busca = f1.text_input("Buscar fornecedor ou CNPJ", placeholder="Nome ou CNPJ", key="busca")
    status_sel = f2.multiselect("Status", list(ROTULO.values()), key="status_sel")
    regime_sel = f3.selectbox("Regime informado", ["Todos"] + REGIMES + ["Sem resposta"], key="regime_sel")
    abc_qtd_sel = f4.selectbox("ABC qtd.", ["Todas", "A", "B", "C"], key="abc_qtd_sel")
    abc_valor_sel = f5.selectbox("ABC valor", ["Todas", "A", "B", "C"], key="abc_valor_sel")

    tab = df.copy()
    tab["Status"] = tab["STATUS"].map(ROTULO).fillna(tab["STATUS"])
    tab["Divergência"] = tab.apply(lambda r: "Sim" if diverge(r["REGIME_INFORMADO"], r["REGIME_SUGERIDO_API"]) else "", axis=1)
    abc = abc_fornecedores(horario_vigente(agora).isoformat()).set_index("CNPJ")
    tab["ABC qtd."] = tab["ID"].map(abc["ABC_QTD"]).fillna("")
    tab["ABC valor"] = tab["ID"].map(abc["ABC_VALOR"]).fillna("")
    if busca:
        b = busca.strip().upper()
        dig = "".join(ch for ch in b if ch.isdigit())
        tab = tab[tab["FORNECEDOR"].str.upper().str.contains(b, regex=False)
                  | (tab["ID"].str.contains(dig, regex=False) if dig else False)]
    if status_sel:
        tab = tab[tab["Status"].isin(status_sel)]
    if regime_sel == "Sem resposta":
        tab = tab[tab["REGIME_INFORMADO"] == ""]
    elif regime_sel != "Todos":
        tab = tab[tab["REGIME_INFORMADO"] == regime_sel]
    if abc_qtd_sel != "Todas":
        tab = tab[tab["ABC qtd."] == abc_qtd_sel]
    if abc_valor_sel != "Todas":
        tab = tab[tab["ABC valor"] == abc_valor_sel]

    tab["Origem do regime"] = tab["ORIGEM_REGIME"].where(tab["ORIGEM_REGIME"] != "",
                                                          tab["REGIME_INFORMADO"].map(lambda x: "e-mail" if x else ""))
    vis = tab[["FORNECEDOR", "CNPJ", "Status", "REGIME_INFORMADO", "Origem do regime", "REGIME_SUGERIDO_API", "Divergência", "ABC qtd.", "ABC valor",
               "DOCUMENTO_RECEBIDO", "DATA_ENVIO", "QTD_LEMBRETES", "DATA_RESPOSTA", "EMAILS", "OBSERVACOES"]].rename(columns={
        "FORNECEDOR": "Fornecedor", "REGIME_INFORMADO": "Regime informado", "REGIME_SUGERIDO_API": "Sugerido (API)",
        "DOCUMENTO_RECEBIDO": "Documento", "DATA_ENVIO": "Enviado em", "QTD_LEMBRETES": "Lembretes",
        "DATA_RESPOSTA": "Respondeu em", "EMAILS": "E-mails", "OBSERVACOES": "Observações"})
    cab, bt = st.columns([4, 1])
    cab.caption(f"{len(vis)} fornecedor(es) na lista · classe ABC pela quantidade de notas e pelo valor comprado")
    bt.download_button("Baixar Excel", excel(vis), file_name=f"levantamento_regime_{datetime.date.today():%Y%m%d}.xlsx",
                       width="stretch")
    st.dataframe(vis, hide_index=True, width="stretch", height=460)


painel()
st.markdown('<div class="signature-fixed">Created by SS.</div>', unsafe_allow_html=True)
st.markdown('<style>@media (min-width: 641px) {.assinatura-mobile {display:none;}}</style><p class="assinatura-mobile" style="font-size:11px;font-weight:700;color:var(--pa-sub);margin-top:24px">Created by SS.</p>', unsafe_allow_html=True)
