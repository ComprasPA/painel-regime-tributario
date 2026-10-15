# Painel – Levantamento de Regime Tributário

Painel de acompanhamento do levantamento de regime tributário dos fornecedores da
Parente Andrade Ltda. Lê a aba `LevantamentoRegime` da planilha de suprimentos e
permite registrar o regime informado por telefone, WhatsApp etc. (o agente então
passa a cobrar só o documento comprobatório).

- Atualiza sozinho às 08, 10, 12, 14 e 16h (segunda a sexta) e pelo botão "Atualizar agora".
- O agente que envia os e-mails e lê as respostas fica em outro repositório (privado).
- `regime/` é uma cópia dos módulos de controle do agente: ao mudar a regra de
  gravação lá, atualizar aqui também.

## Streamlit Cloud

Arquivo principal: `painel.py`. Em **Settings → Secrets**:

```toml
SPREADSHEET_ID = "id-da-planilha"

[gcp_service_account]
# bloco da service account do Google (o mesmo dos outros apps)
```

## Rodar localmente

```bash
pip install -r requirements.txt
streamlit run painel.py
```

Localmente as credenciais vêm de um `.env` (ver `GOOGLE_SECRETS_TOML` / `SPREADSHEET_ID`)
ou de `.streamlit/secrets.toml` – nunca do código.

Created by SS.
