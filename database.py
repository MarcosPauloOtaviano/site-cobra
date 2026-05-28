"""
database.py — Os Cobra da Bola
Toda a lógica de conexão e manipulação do Google Sheets fica aqui.
O app.py importa apenas as funções de alto nível que precisar.
"""
import json
import logging
import os
import re
import time
import uuid
import unicodedata

import gspread
from dotenv import load_dotenv
from flask import g, has_request_context
from gspread.utils import InsertDataOption, ValueInputOption, rowcol_to_a1
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  CONFIGURAÇÃO GLOBAL
# ─────────────────────────────────────────────────────────────────
DIRETORIO_ATUAL    = os.path.dirname(os.path.abspath(__file__))
NOME_PLANILHA      = "site-cobra"
NOME_ABA_PRODUTOS  = "Loja"
_PRODUTOS_CACHE = {'expira_em': 0.0, 'produtos': None}


def _cache_segundos():
    try:
        return max(0, int(os.getenv('SHEETS_CACHE_SECONDS', '30') or 30))
    except (TypeError, ValueError):
        return 30

PRODUTO_HEADERS = [
    'id', 'nome do produto', 'categoria', 'preço de compra', 'preço', 'estoque',
    'url da imagem', 'tamanhos', 'disponibilidade', 'fornecedor',
]
PRODUTO_ALIASES = {
    'id':              ['id', 'codigo', 'código', 'sku'],
    'nome do produto': ['nome do produto', 'nome', 'produto'],
    'categoria':       ['categoria'],
    'preço':           ['preço', 'preco', 'valor'],
    'preço de compra': ['preço de compra', 'preco de compra', 'valor de compra', 'valor_compra', 'preco_compra', 'custo', 'custo_unitario'],
    'estoque':         ['estoque', 'qtd', 'quantidade'],
    'url da imagem':   ['url da imagem', 'imagem', 'foto', 'url_imagem', 'link da imagem', 'imagem_url', 'foto_url', 'arquivo_imagem', 'imagem_data'],
    'tamanhos':        ['tamanhos', 'tamanho'],
    'disponibilidade': ['disponibilidade', 'status'],
    'fornecedor':      ['fornecedor', 'nome_fornecedor'],
}
PONTOS_HEADERS = ['telefone', 'nome', 'total_pontos', 'total_gasto', 'cadastro']
PONTOS_ALIASES = {
    'telefone':     ['telefone', 'celular', 'whatsapp', 'whats'],
    'nome':         ['nome', 'nome_cliente', 'cliente'],
    'total_pontos': ['total_pontos', 'pontos', 'saldo'],
    'total_gasto':  ['total_gasto', 'gasto', 'valor_total'],
    'cadastro':     ['cadastro', 'data_cadastro', 'criado_em'],
}
VENDAS_HEADERS = [
    'data', 'telefone', 'nome_cliente', 'id_produto', 'valor', 'pontos',
    'fornecedor', 'obs', 'id_venda', 'quantidade', 'custo_unitario',
    'custo_total', 'lucro',
]
VENDAS_ALIASES = {
    'data':         ['data', 'data_venda', 'data da venda', 'dt_venda', 'vendido_em'],
    'telefone':     ['telefone', 'celular', 'whatsapp', 'whats'],
    'nome_cliente': ['nome_cliente', 'nome', 'cliente'],
    'id_produto':   ['id_produto', 'produto_id', 'id', 'produto', 'produto vendido'],
    'valor':        ['valor', 'preço', 'preco', 'total', 'valor_venda', 'valor da venda', 'entrada', 'receita', 'venda'],
    'pontos':       ['pontos', 'pts'],
    'fornecedor':   ['fornecedor', 'nome_fornecedor', 'vendedor', 'fornecedor responsável'],
    'obs':          ['obs', 'observacao', 'observação'],
    'id_venda':     ['id_venda', 'venda_id'],
    'quantidade':   ['quantidade', 'qtd'],
    'custo_unitario': ['custo_unitario', 'custo unitario', 'custo unitário', 'preco_compra', 'preço de compra', 'valor de compra', 'custo de compra'],
    'custo_total':    ['custo_total', 'custo total', 'saida', 'saída', 'valor_compra_total', 'valor de compra total', 'total compra'],
    'lucro':          ['lucro', 'saldo', 'resultado'],
}
USUARIO_HEADERS = ['usuario', 'senha_hash', 'nome_fornecedor']
USUARIO_ALIASES = {
    'usuario':         ['usuario', 'usuário', 'user', 'login', 'email'],
    'senha_hash':      ['senha_hash', 'hash_senha', 'password_hash', 'hash'],
    'senha':           ['senha', 'password', 'senha_legado'],
    'nome_fornecedor': ['nome_fornecedor', 'fornecedor', 'nome do fornecedor', 'nome'],
}

# ─────────────────────────────────────────────────────────────────
#  CONEXÃO
# ─────────────────────────────────────────────────────────────────

def _credenciais_env():
    for nome in ('GOOGLE_CREDENTIALS_JSON', 'GOOGLE_SERVICE_ACCOUNT_JSON', 'CREDENCIAIS_JSON'):
        conteudo = os.getenv(nome)
        if not conteudo:
            continue
        try:
            credenciais = json.loads(conteudo)
        except json.JSONDecodeError as exc:
            raise ValueError(f"A variável {nome} não contém um JSON válido.") from exc
        if not isinstance(credenciais, dict) or not credenciais.get('client_email') or not credenciais.get('private_key'):
            raise ValueError(f"A variável {nome} não parece ser uma service account válida.")
        return credenciais
    return None


def conectar_sheets():
    """Retorna um cliente gspread autenticado via service account."""
    escopos = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    credenciais_env = _credenciais_env()
    if credenciais_env:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(credenciais_env, escopos)
        return gspread.authorize(creds)

    arquivo_json = (
        os.getenv('ARQUIVO_CREDENCIAIS')
        or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        or 'credenciais.json'
    )
    if not os.path.isabs(arquivo_json):
        arquivo_json = os.path.join(DIRETORIO_ATUAL, arquivo_json)
    if not os.path.exists(arquivo_json):
        raise FileNotFoundError(
            "Credenciais do Google não encontradas. No deploy, configure "
            "GOOGLE_CREDENTIALS_JSON com o JSON da service account."
        )
    creds = ServiceAccountCredentials.from_json_keyfile_name(arquivo_json, escopos)
    return gspread.authorize(creds)


def abrir_planilha():
    planilha_id = (
        os.getenv('PLANILHA_ID')
        or os.getenv('GOOGLE_SHEET_ID')
        or os.getenv('SPREADSHEET_ID')
    )
    cliente = conectar_sheets()
    if planilha_id:
        return cliente.open_by_key(planilha_id)
    return cliente.open(NOME_PLANILHA)


def obter_aba_produtos(planilha):
    try:
        return planilha.worksheet(NOME_ABA_PRODUTOS)
    except gspread.exceptions.WorksheetNotFound:
        return garantir_aba(planilha, NOME_ABA_PRODUTOS, PRODUTO_HEADERS)


def garantir_aba(planilha, nome, cabecalho, aliases=None):
    try:
        aba = planilha.worksheet(nome)
    except gspread.exceptions.WorksheetNotFound:
        aba = planilha.add_worksheet(title=nome, rows=1000, cols=len(cabecalho))
        aba.append_row(cabecalho)
    garantir_cabecalhos(aba, cabecalho, aliases)
    return aba

# ─────────────────────────────────────────────────────────────────
#  CACHE POR REQUISIÇÃO (usa Flask g)
# ─────────────────────────────────────────────────────────────────

def _cache_planilha():
    if not has_request_context():
        return None
    if not hasattr(g, 'sheet_cache'):
        g.sheet_cache = {}
    return g.sheet_cache


def _chave_cache(aba):
    return f'{getattr(aba, "spreadsheet_id", "")}:{getattr(aba, "id", "")}:{aba.title}'


def _invalidar_cache(aba):
    cache = _cache_planilha()
    if cache is not None:
        cache.pop(_chave_cache(aba), None)
    if getattr(aba, 'title', '') == NOME_ABA_PRODUTOS:
        limpar_cache_produtos()


def valores_da_aba(aba):
    cache = _cache_planilha()
    chave = _chave_cache(aba)
    if cache is not None and chave in cache:
        return cache[chave]
    valores = aba.get_all_values()
    if cache is not None:
        cache[chave] = valores
    return valores

# ─────────────────────────────────────────────────────────────────
#  NORMALIZAÇÃO / ALIAS
# ─────────────────────────────────────────────────────────────────

def normalizar_chave(valor):
    txt = unicodedata.normalize('NFKD', str(valor or ''))
    txt = ''.join(ch for ch in txt if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', txt.strip().lower())


def mesmo_texto(a, b):
    return normalizar_chave(a) == normalizar_chave(b)


def aliases_para(campo, aliases=None):
    return (aliases or {}).get(campo, [campo])


def valor_por_alias(registro, campo, padrao='', aliases=None):
    normalizados = {normalizar_chave(k): v for k, v in registro.items()}
    for nome in aliases_para(campo, aliases):
        chave = normalizar_chave(nome)
        if chave in normalizados:
            return normalizados[chave]
    return padrao

# ─────────────────────────────────────────────────────────────────
#  CABEÇALHOS
# ─────────────────────────────────────────────────────────────────

def _garantir_tamanho_aba(aba, min_linhas=1, min_colunas=1):
    linhas  = max(int(getattr(aba, 'row_count', 1) or 1), min_linhas)
    colunas = max(int(getattr(aba, 'col_count', 1) or 1), min_colunas)
    if linhas != getattr(aba, 'row_count', None) or colunas != getattr(aba, 'col_count', None):
        aba.resize(rows=linhas, cols=colunas)


def garantir_cabecalhos(aba, cabecalhos, aliases=None):
    _garantir_tamanho_aba(aba, min_linhas=1, min_colunas=len(cabecalhos))
    valores = valores_da_aba(aba)
    headers = [str(h).strip() for h in valores[0]] if valores else []
    if not headers:
        aba.update([cabecalhos], range_name='A1',
                   value_input_option=ValueInputOption.user_entered)
        _invalidar_cache(aba)
        return cabecalhos[:]
    normalizados = {normalizar_chave(h) for h in headers if h}
    for campo in cabecalhos:
        if not any(normalizar_chave(a) in normalizados for a in aliases_para(campo, aliases)):
            headers.append(campo)
            _garantir_tamanho_aba(aba, min_linhas=1, min_colunas=len(headers))
            aba.update_cell(1, len(headers), campo)
            _invalidar_cache(aba)
            normalizados.add(normalizar_chave(campo))
    return headers


def cabecalho_real(headers, campo, aliases=None):
    mapa = {normalizar_chave(h): h for h in headers if h}
    for nome in aliases_para(campo, aliases):
        if normalizar_chave(nome) in mapa:
            return mapa[normalizar_chave(nome)]
    return campo


def indice_coluna(headers, campo, aliases=None):
    header = cabecalho_real(headers, campo, aliases)
    try:
        return headers.index(header) + 1
    except ValueError:
        return None

# ─────────────────────────────────────────────────────────────────
#  LEITURA / ESCRITA
# ─────────────────────────────────────────────────────────────────

def registros_da_aba(aba):
    valores = valores_da_aba(aba)
    if not valores:
        return []
    headers = [str(h).strip() for h in valores[0]]
    registros = []
    for linha in valores[1:]:
        registro = {}
        for idx, header in enumerate(headers):
            if not header:
                continue
            chave = header if header not in registro else f'{header}_{idx + 1}'
            registro[chave] = linha[idx] if idx < len(linha) else ''
        registros.append(registro)
    return registros


def append_dict_row(aba, dados, cabecalhos, aliases=None):
    headers = garantir_cabecalhos(aba, cabecalhos, aliases)
    linha = [''] * len(headers)
    for campo, valor in dados.items():
        col = indice_coluna(headers, campo, aliases)
        if col:
            linha[col - 1] = valor
    aba.append_row(
        linha,
        value_input_option=ValueInputOption.user_entered,
        insert_data_option=InsertDataOption.insert_rows,
        table_range=f'A1:{rowcol_to_a1(1, len(headers))}',
    )
    _invalidar_cache(aba)


def update_dict_row(aba, numero_linha, dados, cabecalhos, aliases=None):
    headers = garantir_cabecalhos(aba, cabecalhos, aliases)
    updates = []
    for campo, valor in dados.items():
        col = indice_coluna(headers, campo, aliases)
        if col:
            updates.append({
                'range': rowcol_to_a1(numero_linha, col),
                'values': [[valor]],
            })
    if updates:
        aba.batch_update(
            updates,
            value_input_option=ValueInputOption.user_entered,
        )
        _invalidar_cache(aba)

# ─────────────────────────────────────────────────────────────────
#  FORMATAÇÃO DE PREÇO
# ─────────────────────────────────────────────────────────────────

def parse_preco(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor or '').strip()
    if not txt:
        return 0.0
    txt = unicodedata.normalize('NFKD', txt).replace('\xa0', ' ')
    txt = re.sub(r'[^\d,.\-]', '', txt)
    if not txt or txt in {'-', ',', '.'}:
        return 0.0

    negativo = txt.startswith('-')
    txt = txt.replace('-', '')
    ultima_virgula = txt.rfind(',')
    ultimo_ponto = txt.rfind('.')

    if ultima_virgula >= 0 and ultimo_ponto >= 0:
        decimal = ',' if ultima_virgula > ultimo_ponto else '.'
        milhar = '.' if decimal == ',' else ','
        txt = txt.replace(milhar, '').replace(decimal, '.')
    elif ultima_virgula >= 0:
        partes = txt.split(',')
        if len(partes[-1]) in (1, 2):
            txt = ''.join(partes[:-1]).replace(',', '') + '.' + partes[-1]
        else:
            txt = txt.replace(',', '')
    elif ultimo_ponto >= 0:
        partes = txt.split('.')
        if len(partes[-1]) in (1, 2):
            txt = ''.join(partes[:-1]).replace('.', '') + '.' + partes[-1]
        else:
            txt = txt.replace('.', '')

    if negativo:
        txt = f'-{txt}'
    try:
        return float(txt)
    except Exception:
        return 0.0


def formatar_preco(valor):
    try:
        return "{:,.2f}".format(parse_preco(valor)).replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return str(valor)


def parse_int(valor, padrao=0):
    try:
        if valor in (None, ''):
            return padrao
        return max(0, int(float(str(valor).replace(',', '.'))))
    except Exception:
        return padrao

# ─────────────────────────────────────────────────────────────────
#  FORNECEDOR / PRODUTO
# ─────────────────────────────────────────────────────────────────

def fornecedor_permitido(produto_fornecedor, fornecedor_logado):
    if not fornecedor_logado:
        return False
    if not produto_fornecedor:
        return True  # produtos legados sem fornecedor ficam visíveis
    return mesmo_texto(produto_fornecedor, fornecedor_logado)


def normalizar_produto(raw):
    preco_float = parse_preco(valor_por_alias(raw, 'preço', 0, PRODUTO_ALIASES))
    preco_compra_float = parse_preco(valor_por_alias(raw, 'preço de compra', 0, PRODUTO_ALIASES))
    return {
        'id':             str(valor_por_alias(raw, 'id', '', PRODUTO_ALIASES)),
        'nome':           valor_por_alias(raw, 'nome do produto', '', PRODUTO_ALIASES),
        'categoria':      valor_por_alias(raw, 'categoria', '', PRODUTO_ALIASES),
        'preco':          formatar_preco(preco_float),
        'preco_raw':      preco_float,
        'preco_compra':     formatar_preco(preco_compra_float),
        'preco_compra_raw': preco_compra_float,
        'estoque':        parse_int(valor_por_alias(raw, 'estoque', 0, PRODUTO_ALIASES)),
        'imagem':         valor_por_alias(raw, 'url da imagem', '', PRODUTO_ALIASES),
        'tamanhos':       valor_por_alias(raw, 'tamanhos', '', PRODUTO_ALIASES),
        'disponibilidade': valor_por_alias(raw, 'disponibilidade', '', PRODUTO_ALIASES),
        'fornecedor':     valor_por_alias(raw, 'fornecedor', '', PRODUTO_ALIASES),
    }


def limpar_cache_produtos():
    _PRODUTOS_CACHE['expira_em'] = 0.0
    _PRODUTOS_CACHE['produtos'] = None


def _copiar_produtos(produtos):
    return [dict(produto) for produto in produtos]


def buscar_produtos(fornecedor=None):
    """Retorna lista de produtos normalizados, opcionalmente filtrados por fornecedor."""
    try:
        agora = time.monotonic()
        produtos_cache = _PRODUTOS_CACHE.get('produtos')
        if produtos_cache is not None and agora < _PRODUTOS_CACHE.get('expira_em', 0):
            produtos = _copiar_produtos(produtos_cache)
        else:
            plan = abrir_planilha()
            aba  = obter_aba_produtos(plan)
            garantir_cabecalhos(aba, PRODUTO_HEADERS, PRODUTO_ALIASES)
            registros = registros_da_aba(aba)
            produtos  = [normalizar_produto(r) for r in registros if any(str(v).strip() for v in r.values())]
            cache_segundos = _cache_segundos()
            if cache_segundos > 0:
                _PRODUTOS_CACHE['produtos'] = _copiar_produtos(produtos)
                _PRODUTOS_CACHE['expira_em'] = agora + cache_segundos
        if fornecedor:
            produtos = [p for p in produtos if fornecedor_permitido(p['fornecedor'], fornecedor)]
        return produtos
    except Exception as e:
        logger.exception("Erro ao buscar produtos")
        return []


def encontrar_produto(aba, produto_id, fornecedor=None):
    """Retorna (numero_linha, raw, produto_normalizado) ou (None, None, None)."""
    garantir_cabecalhos(aba, PRODUTO_HEADERS, PRODUTO_ALIASES)
    for i, row in enumerate(registros_da_aba(aba)):
        produto = normalizar_produto(row)
        if produto['id'] == str(produto_id):
            if fornecedor is None or fornecedor_permitido(produto['fornecedor'], fornecedor):
                return i + 2, row, produto
    return None, None, None


def produto_id_existe(aba, produto_id):
    garantir_cabecalhos(aba, PRODUTO_HEADERS, PRODUTO_ALIASES)
    for row in registros_da_aba(aba):
        if str(valor_por_alias(row, 'id', '', PRODUTO_ALIASES)) == str(produto_id):
            return True
    return False


def gerar_id_produto(aba):
    for _ in range(20):
        novo_id = f"cb-{uuid.uuid4().hex[:6]}"
        if not produto_id_existe(aba, novo_id):
            return novo_id
    return f"cb-{uuid.uuid4().hex[:10]}"

# ─────────────────────────────────────────────────────────────────
#  USUÁRIOS
# ─────────────────────────────────────────────────────────────────

def buscar_usuario(usuario):
    """
    Retorna o dict do usuário encontrado na aba 'usuarios' ou None.
    Campos esperados na planilha: usuario | senha_hash | nome_fornecedor
    """
    try:
        plan  = abrir_planilha()
        aba_u = garantir_aba(plan, 'usuarios', USUARIO_HEADERS)
        garantir_cabecalhos(aba_u, USUARIO_HEADERS, USUARIO_ALIASES)
        for u in registros_da_aba(aba_u):
            usuario_planilha = valor_por_alias(u, 'usuario', '', USUARIO_ALIASES)
            if mesmo_texto(usuario_planilha, usuario):
                return {
                    **u,
                    'usuario': usuario_planilha,
                    'senha_hash': valor_por_alias(u, 'senha_hash', '', USUARIO_ALIASES),
                    'senha': valor_por_alias(u, 'senha', '', USUARIO_ALIASES),
                    'nome_fornecedor': valor_por_alias(u, 'nome_fornecedor', '', USUARIO_ALIASES),
                }
    except Exception as e:
        logger.exception("Erro ao buscar usuário")
    return None

# ─────────────────────────────────────────────────────────────────
#  MENSAGENS DE ERRO
# ─────────────────────────────────────────────────────────────────

def mensagem_erro_planilha(erro, acao):
    texto = str(erro)
    if '429' in texto or 'Quota exceeded' in texto:
        return (f'Limite temporário do Google Sheets atingido ao {acao}. '
                f'Aguarde cerca de 1 minuto e tente novamente.')
    if os.getenv('VERCEL') or os.getenv('VERCEL_ENV') or os.getenv('FLASK_ENV') == 'production':
        return f'Não foi possível {acao} agora. Tente novamente em instantes.'
    return f'Erro ao {acao}: {erro}'
