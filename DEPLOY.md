# Deploy na Vercel

Este projeto está preparado para rodar como Flask na Vercel usando `app.py` como entrada. A Vercel detecta o app Flask e publica a aplicação como uma Function.

## Variáveis obrigatórias

Configure no painel da Vercel:

- `FLASK_SECRET_KEY`: chave grande e aleatória para proteger sessões.
- `PLANILHA_ID`: ID da planilha do Google Sheets.
- `GOOGLE_CREDENTIALS_JSON`: conteúdo completo do JSON da service account.

## Variáveis opcionais

- `WHATSAPP_NUM`: número usado no botão de compra, no formato internacional sem `+`.
- `SHEETS_CACHE_SECONDS`: cache curto da vitrine. Padrão: `30`.
- `ASSET_VERSION`: versão de cache do CSS. Padrão: `attack13`.

## Imagens de produto

Na Vercel, o filesystem da função não é persistente. Por isso, o painel compacta a foto no navegador antes do envio e salva a imagem como data URL na planilha, dentro do limite do Google Sheets. Links externos continuam funcionando normalmente.

Os arquivos em `public/static/` são servidos como assets públicos pela Vercel.

## Checklist rápido

1. Suba o repositório para o GitHub.
2. Importe o projeto na Vercel.
3. Cadastre as variáveis de ambiente acima.
4. Faça o deploy.
5. Acesse `/healthz` para confirmar que a aplicação respondeu.
