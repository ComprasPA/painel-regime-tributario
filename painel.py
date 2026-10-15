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


# Decisão do usuário (14/10/2026): de 2 em 2 horas, das 08:00 às 16:00, de segunda a sexta.
ATUALIZACOES = [datetime.time(h) for h in (8, 10, 12, 14, 16)]
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
    ("Respondido", ["respondido"], "#2a78d6"),
    ("Revisão manual", ["revisao_manual"], "#eb6834"),
    ("Em lembrete", ["lembrete_1", "lembrete_2", "lembrete_3"], "#eda100"),
    ("Enviado", ["enviado"], "#8fb8e8"),
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
#MainMenu, footer, [data-testid='stToolbar'] {visibility: hidden;}
.block-container {padding-top: 3rem;}
.kpi {background: var(--secondary-background-color); border-radius: 8px; padding: 10px 14px;}
.kpi .r {font-size: 13px; opacity: .75; margin: 0;}
.kpi .v {font-size: 28px; font-weight: 600; margin: 0; line-height: 1.2;}
.kpi .s {font-size: 12px; opacity: .65; margin: 0;}
.barra {display: flex; height: 24px; border-radius: 4px; overflow: hidden; gap: 2px; margin: 4px 0 6px;}
.leg {display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; opacity: .85;}
.leg span i {display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px;}
.reg {display: grid; grid-template-columns: 130px 1fr 40px; gap: 6px 10px; align-items: center; font-size: 14px;}
.reg b {display: block; height: 10px; background: #2a78d6; border-radius: 0 3px 3px 0;}
.feed {font-size: 13px; line-height: 1.9;}
.feed small {opacity: .6; margin-right: 6px;}
.aovivo {font-size: 13px; opacity: .8;}
.aovivo i {display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #0ca30c; margin-right: 6px;}
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;700&family=Sora:wght@700&display=swap');
:root {--pa-laranja-deep: #CE6E10; --pa-slate: #5B6459;}
.cabecalho {display: flex; align-items: center; gap: 22px; margin-bottom: 4px;}
.cabecalho img {width: 150px; height: auto;}
.brand-eyebrow {font-family: 'Public Sans', sans-serif; font-weight: 700; font-size: 14px; letter-spacing: .12em;
  text-transform: uppercase; color: var(--pa-laranja-deep); display: block;}
.brand-subtitle {font-family: 'Sora', sans-serif; font-weight: 700; font-size: 24px; color: var(--text-color); display: block; line-height: 1.25;}
.brand-sub2 {font-size: 13px; opacity: .7; display: block;}
.signature-fixed { position: fixed; bottom: 12px; left: 20px; color: #7a8a8a; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; z-index: 999999; pointer-events: none; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(max_entries=3, show_spinner=False)
def carregar(horario: str) -> tuple[pd.DataFrame, datetime.datetime]:
    """Uma leitura por horário de atualização (o argumento é a chave do cache)."""
    df = pd.DataFrame(Controle().registros())
    return df.reindex(columns=list(dict.fromkeys(list(df.columns) + COLUNAS)), fill_value="").fillna(""), \
        agora_dt()


@st.cache_data
def logo_base64(nome: str) -> str:
    arq = Path(__file__).parent / "assets" / f"{nome}.png"
    return base64.b64encode(arq.read_bytes()).decode() if arq.exists() else ""


def cabecalho(col, universo: int):
    """Mesma identidade do Portal Gestão de Compras: logo (versão escura no tema escuro) + texto da marca."""
    # segue o tema que o Streamlit está usando de fato (pode diferir do sistema, se escolhido no menu)
    tema = getattr(getattr(st.context, "theme", None), "type", None)
    escuro = tema == "dark"
    # logo original sempre; no tema escuro vai sobre um fundo branco arredondado, para o texto
    # "PARENTE ANDRADE" (preto) ficar legível mesmo se a detecção do tema divergir do fundo real
    logo = logo_base64("logo")
    estilo = ' style="background:#fff;border-radius:10px;padding:6px 10px"' if escuro else ""
    img = f'<img src="data:image/png;base64,{logo}" alt="Parente Andrade"{estilo}>' if logo else ""
    laranja = "#F2951D" if escuro else "#CE6E10"
    col.markdown(f'''<div class="cabecalho">{img}<div>
        <span class="brand-eyebrow" style="color:{laranja}">Gestão de Compras | Parente Andrade</span>
        <span class="brand-subtitle">Levantamento de regime tributário</span>
        <span class="brand-sub2">{universo} fornecedores no envio</span></div></div>''', unsafe_allow_html=True)


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

    c = st.columns(6)
    kpi(c[0], "Enviados", enviados, f"de {universo}")
    kpi(c[1], "Responderam", responderam, f"{responderam / enviados:.0%} dos enviados" if enviados else "—")
    kpi(c[2], "Documento recebido", doc, "comprovados")
    kpi(c[3], "Aguardando resposta", n(AGUARDANDO), f"{em_lembrete} em lembrete")
    kpi(c[4], "Revisão manual", n({"revisao_manual"}), "resposta ambígua ou conflito")
    kpi(c[5], "Fora do envio", n(FORA), "sem e-mail, CNPJ inválido ou erro")

    st.markdown(f"<p style='margin:18px 0 0;font-size:14px;opacity:.8'>Andamento dos {universo} fornecedores no envio</p>",
                unsafe_allow_html=True)
    partes, legenda = [], []
    for rotulo, sts, cor in ETAPAS:
        q = n(set(sts))
        if q:
            partes.append(f'<div style="flex:{q};background:{cor}" title="{rotulo}: {q}"></div>')
        legenda.append(f'<span><i style="background:{cor}"></i>{rotulo} {q}</span>')
    st.markdown(f'<div class="barra">{"".join(partes)}</div><div class="leg">{"".join(legenda)}</div>',
                unsafe_allow_html=True)

    st.write("")
    e, d = st.columns(2)
    with e.container(border=True):
        st.markdown("**Regime informado pelos fornecedores**")
        inf = base["REGIME_INFORMADO"].value_counts()
        maior = max([int(inf.get(r, 0)) for r in REGIMES] + [1])
        linhas = "".join(f'<span>{r}</span><b style="width:{int(inf.get(r, 0)) / maior:.0%}"></b>'
                         f'<span style="text-align:right">{int(inf.get(r, 0))}</span>' for r in REGIMES)
        st.markdown(f'<div class="reg">{linhas}</div>', unsafe_allow_html=True)
        div = int(base.apply(lambda r: diverge(r["REGIME_INFORMADO"], r["REGIME_SUGERIDO_API"]), axis=1).sum())
        st.caption(f"Divergências entre o informado e a consulta de CNPJ: {div}")
    with d.container(border=True):
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
    f1, f2, f3 = st.columns([3, 2, 2])
    busca = f1.text_input("Buscar fornecedor ou CNPJ", placeholder="Nome ou CNPJ", key="busca")
    status_sel = f2.multiselect("Status", list(ROTULO.values()), key="status_sel")
    regime_sel = f3.selectbox("Regime informado", ["Todos"] + REGIMES + ["Sem resposta"], key="regime_sel")

    tab = df.copy()
    tab["Status"] = tab["STATUS"].map(ROTULO).fillna(tab["STATUS"])
    tab["Divergência"] = tab.apply(lambda r: "Sim" if diverge(r["REGIME_INFORMADO"], r["REGIME_SUGERIDO_API"]) else "", axis=1)
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

    tab["Origem do regime"] = tab["ORIGEM_REGIME"].where(tab["ORIGEM_REGIME"] != "",
                                                          tab["REGIME_INFORMADO"].map(lambda x: "e-mail" if x else ""))
    vis = tab[["FORNECEDOR", "CNPJ", "Status", "REGIME_INFORMADO", "Origem do regime", "REGIME_SUGERIDO_API", "Divergência",
               "DOCUMENTO_RECEBIDO", "DATA_ENVIO", "QTD_LEMBRETES", "DATA_RESPOSTA", "EMAILS", "OBSERVACOES"]].rename(columns={
        "FORNECEDOR": "Fornecedor", "REGIME_INFORMADO": "Regime informado", "REGIME_SUGERIDO_API": "Sugerido (API)",
        "DOCUMENTO_RECEBIDO": "Documento", "DATA_ENVIO": "Enviado em", "QTD_LEMBRETES": "Lembretes",
        "DATA_RESPOSTA": "Respondeu em", "EMAILS": "E-mails", "OBSERVACOES": "Observações"})
    cab, bt = st.columns([4, 1])
    cab.caption(f"{len(vis)} fornecedor(es) na lista")
    bt.download_button("Baixar Excel", excel(vis), file_name=f"levantamento_regime_{datetime.date.today():%Y%m%d}.xlsx",
                       width="stretch")
    st.dataframe(vis, hide_index=True, width="stretch", height=460)


painel()
st.markdown('<div class="signature-fixed">Created by SS.</div>', unsafe_allow_html=True)
