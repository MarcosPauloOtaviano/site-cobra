# Deploy na Vercel

Este projeto está preparado para rodar como Flask na Vercel usando `api/index.py` como entrada serverless, importando o app Flask definido em `app.py`.

## Variáveis obrigatórias

Configure no painel da Vercel:

- `FLASK_SECRET_KEY`: chave grande e aleatória para proteger sessões.
- `PLANILHA_ID`: ID da planilha do Google Sheets.
- `GOOGLE_CREDENTIALS_JSON`: conteúdo completo do JSON da service account.

## Variáveis opcionais

- `WHATSAPP_NUM`: número usado no botão de compra, no formato internacional sem `+`.
- `SHEETS_CACHE_SECONDS`: cache curto da vitrine. Padrão: `30`.
- `ASSET_VERSION`: versão de cache do CSS. Padrão: `attack9`.

## Imagens de produto

Na Vercel, o filesystem da função não é persistente. Por isso, em produção use o campo **Link da Imagem** no cadastro/edição do produto. O upload local continua funcionando para desenvolvimento local.

Os arquivos em `public/static/` são servidos como assets públicos pela Vercel.

## Checklist rápido

1. Suba o repositório para o GitHub.
2. Importe o projeto na Vercel.
3. Cadastre as variáveis de ambiente acima.
4. Faça o deploy.
5. Acesse `/healthz` para confirmar que a aplicação respondeu.
