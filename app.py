"""
app.py — Os Cobra da Bola
Apenas rotas Flask. Toda lógica de banco de dados está em database.py.

MIGRAÇÃO DE SENHAS:
  Para gerar o hash de uma senha e salvar na planilha rode no terminal:
      python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('SUA_SENHA'))"
  Cole o resultado na coluna 'senha_hash' da aba 'usuarios'.
"""
import os
import uuid
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import (Flask, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

# ── Importa tudo do módulo de banco de dados ──────────────────────
from database import (
    PRODUTO_ALIASES, PRODUTO_HEADERS, PONTOS_ALIASES, PONTOS_HEADERS,
    VENDAS_ALIASES, VENDAS_HEADERS,
    abrir_planilha, obter_aba_produtos, garantir_aba,
    append_dict_row, update_dict_row,
    registros_da_aba, buscar_produtos,
    limpar_cache_produtos,
    encontrar_produto, produto_id_existe, gerar_id_produto,
    parse_preco, parse_int, formatar_preco,
    buscar_usuario,
    fornecedor_permitido, valor_por_alias,
    mensagem_erro_planilha,
)

# ─────────────────────────────────────────────────────────────────
#  CONFIGURAÇÃO DA APLICAÇÃO
# ─────────────────────────────────────────────────────────────────
load_dotenv()
logger = logging.getLogger(__name__)

AMBIENTE_VERCEL = bool(os.getenv('VERCEL') or os.getenv('VERCEL_ENV'))
PRODUCAO = AMBIENTE_VERCEL or os.getenv('FLASK_ENV') == 'production'

app = Flask(__name__)
secret_key = os.getenv('FLASK_SECRET_KEY')
if PRODUCAO and not secret_key:
    raise RuntimeError('Configure FLASK_SECRET_KEY antes de publicar em produção.')
app.secret_key = secret_key or 'cobra_secreta_mude_em_producao'

DIRETORIO_ATUAL  = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER    = os.path.join(DIRETORIO_ATUAL, 'static', 'uploads')
EXTENSOES_OK     = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

app.config['UPLOAD_FOLDER']      = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8 MB
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = PRODUCAO
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

if not AMBIENTE_VERCEL:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────────────────────────
#  HELPERS LOCAIS
# ─────────────────────────────────────────────────────────────────

def _extensao_ok(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in EXTENSOES_OK


def _salvar_imagem(img_file):
    """Salva upload e retorna o path relativo, ou '' se não houver arquivo."""
    if not img_file or not img_file.filename:
        return ''
    if not _extensao_ok(img_file.filename):
        raise ValueError('Use uma imagem nos formatos PNG, JPG, JPEG, GIF ou WEBP.')
    if AMBIENTE_VERCEL:
        raise ValueError('No deploy da Vercel, use o campo "Link da Imagem". Upload local não fica salvo de forma permanente.')

    nome = f"{uuid.uuid4().hex[:8]}_{secure_filename(img_file.filename)}"
    img_file.save(os.path.join(app.config['UPLOAD_FOLDER'], nome))
    return f"/static/uploads/{nome}"


def _login_requerido():
    """Redireciona para login se a sessão não estiver autenticada."""
    if not session.get('logado'):
        return redirect(url_for('login'))
    return None


def _fornecedor_sessao():
    fornecedor = session.get('fornecedor') or session.get('usuario')
    if not fornecedor:
        session.clear()
        return None
    return fornecedor


def _senha_confere(senha_armazenada, senha_digitada):
    senha_armazenada = str(senha_armazenada or '').strip()
    senha_digitada = str(senha_digitada or '').strip()
    if not senha_armazenada or not senha_digitada:
        return False

    parece_hash = (
        senha_armazenada.startswith(('scrypt:', 'pbkdf2:', 'argon2:', 'bcrypt:'))
        or senha_armazenada.count('$') >= 2
    )
    if parece_hash:
        try:
            if check_password_hash(senha_armazenada, senha_digitada):
                return True
        except Exception:
            pass

    return senha_armazenada == senha_digitada


def _telefone_limpo(valor):
    telefone = ''.join(filter(str.isdigit, str(valor or '')))
    if telefone.startswith('55') and len(telefone) in (12, 13):
        telefone = telefone[2:]
    return telefone


def _telefone_valido(telefone):
    return len(_telefone_limpo(telefone)) in (10, 11)


def _calcular_pontos(valor):
    faixas = int((max(0, float(valor or 0)) + 0.000001) // 89)
    return faixas * 20


def _parse_data_planilha(valor):
    if isinstance(valor, datetime):
        return valor
    texto = str(valor or '').strip()
    if not texto:
        return None
    for formato in (
        '%d/%m/%Y %H:%M',
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
    ):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            pass
    return None


def _parse_data_filtro(valor):
    try:
        return datetime.strptime(str(valor or ''), '%Y-%m-%d').date()
    except ValueError:
        return None


@app.after_request
def aplicar_headers_basicos(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    if request.path.startswith('/static/'):
        response.headers.setdefault('Cache-Control', 'public, max-age=31536000, immutable')
    elif request.path.startswith('/admin') or request.path in ('/login', '/meus-pontos'):
        response.headers.setdefault('Cache-Control', 'no-store')
    return response


@app.context_processor
def variaveis_globais():
    return {
        'whatsapp_num': os.getenv('WHATSAPP_NUM', '5535999014589'),
        'cache_bust': os.getenv('ASSET_VERSION', 'attack9'),
        'ambiente_vercel': AMBIENTE_VERCEL,
    }


# ═══════════════════════════════════════════════════════════════
#  ÁREA PÚBLICA
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def home():
    produtos   = buscar_produtos()
    categorias = sorted({p['categoria'] for p in produtos if p['categoria']}, key=str.lower)
    return render_template('index.html', produtos=produtos, categorias=categorias)


@app.route('/healthz')
def healthz():
    return {'status': 'ok', 'app': 'os-cobra-da-bola'}, 200


@app.route('/meus-pontos', methods=['GET', 'POST'])
def consultar_pontos():
    resultado, vendas, telefone_buscado = None, [], ''

    if request.method == 'POST':
        telefone_buscado = request.form.get('telefone', '').strip()
        telefone_limpo = _telefone_limpo(telefone_buscado)
        if not _telefone_valido(telefone_limpo):
            flash('Informe um celular/WhatsApp válido com DDD.', 'error')
            return render_template('pontos.html',
                                   resultado=resultado,
                                   vendas=vendas,
                                   telefone_buscado=telefone_buscado)
        try:
            plan  = abrir_planilha()
            aba_p = garantir_aba(plan, 'pontos', PONTOS_HEADERS, PONTOS_ALIASES)
            aba_v = garantir_aba(plan, 'vendas',  VENDAS_HEADERS, VENDAS_ALIASES)

            for r in registros_da_aba(aba_p):
                telefone_registro = valor_por_alias(r, 'telefone', '', PONTOS_ALIASES)
                if _telefone_limpo(telefone_registro) == telefone_limpo:
                    resultado = r
                    break
            for v in registros_da_aba(aba_v):
                telefone_venda = valor_por_alias(v, 'telefone', '', VENDAS_ALIASES)
                if _telefone_limpo(telefone_venda) == telefone_limpo:
                    vendas.append(v)
        except Exception as e:
            flash(f'Erro ao consultar pontos: {e}', 'error')

    return render_template('pontos.html',
                           resultado=resultado,
                           vendas=vendas[-10:],
                           telefone_buscado=telefone_buscado)


# ═══════════════════════════════════════════════════════════════
#  AUTENTICAÇÃO
# ═══════════════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logado'):
        return redirect(url_for('painel'))

    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha   = request.form.get('senha', '').strip()

        try:
            u = buscar_usuario(usuario)
            if u:
                senha_armazenada = u.get('senha_hash') or u.get('senha', '')
                autenticado = _senha_confere(senha_armazenada, senha)

                if autenticado:
                    session.permanent     = True
                    session['logado']     = True
                    session['usuario']    = usuario
                    session['fornecedor'] = u.get('nome_fornecedor') or usuario
                    flash('Bem-vindo ao painel! ✓', 'success')
                    return redirect(url_for('painel'))

            flash('Usuário ou senha incorretos.', 'error')

        except Exception as e:
            flash(f'Erro de conexão: {e}', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


# ═══════════════════════════════════════════════════════════════
#  ÁREA DO FORNECEDOR (PROTEGIDA)
# ═══════════════════════════════════════════════════════════════

@app.route('/admin/painel')
def painel():
    redir = _login_requerido()
    if redir: return redir

    fornecedor = _fornecedor_sessao()
    if not fornecedor:
        return redirect(url_for('login'))
    produtos   = buscar_produtos(fornecedor=fornecedor)
    stats = {
        'total':     len(produtos),
        'estoque':   sum(p['estoque'] for p in produtos),
        'pronta':    sum(1 for p in produtos if p['disponibilidade'] == 'Pronta Entrega'),
        'encomenda': sum(1 for p in produtos if p['disponibilidade'] == 'Sob Encomenda'),
    }
    return render_template('painel.html', produtos=produtos,
                           fornecedor=fornecedor, stats=stats)


@app.route('/admin/cadastrar', methods=['GET', 'POST'])
def cadastrar():
    redir = _login_requerido()
    if redir: return redir

    if request.method == 'POST':
        nome_produto    = request.form.get('nome_produto', '').strip()
        categoria       = request.form.get('categoria', '').strip()
        preco           = parse_preco(request.form.get('preco', ''))
        estoque         = parse_int(request.form.get('estoque', '0'))
        tamanhos        = request.form.get('tamanhos', '').strip()
        disponibilidade = request.form.get('disponibilidade', 'Pronta Entrega')
        p_id_digitado   = request.form.get('id', '').strip()
        fornecedor      = _fornecedor_sessao()
        if not fornecedor:
            return redirect(url_for('login'))

        if not nome_produto or not categoria:
            flash('Preencha nome e categoria do produto.', 'error')
            return render_template('cadastro.html', form=request.form)
        if preco <= 0:
            flash('Informe um preço válido maior que zero.', 'error')
            return render_template('cadastro.html', form=request.form)

        try:
            plan = abrir_planilha()
            aba  = obter_aba_produtos(plan)

            caminho_imagem = (_salvar_imagem(request.files.get('imagem'))
                              or request.form.get('url_imagem', '').strip())
            p_id = p_id_digitado or gerar_id_produto(aba)

            if produto_id_existe(aba, p_id):
                flash('Já existe um produto com esse ID. Deixe em branco para gerar.', 'error')
                return render_template('cadastro.html', form=request.form)

            append_dict_row(aba, {
                'id':              p_id,
                'nome do produto': nome_produto,
                'categoria':       categoria,
                'preço':           round(preco, 2),
                'estoque':         estoque,
                'url da imagem':   caminho_imagem,
                'tamanhos':        tamanhos,
                'disponibilidade': disponibilidade,
                'fornecedor':      fornecedor,
            }, PRODUTO_HEADERS, PRODUTO_ALIASES)

            flash('Produto cadastrado com sucesso! ✓', 'success')
            return redirect(url_for('painel'))

        except ValueError as e:
            flash(str(e), 'error')
            return render_template('cadastro.html', form=request.form)
        except Exception as e:
            logger.exception("Erro ao cadastrar produto")
            flash(mensagem_erro_planilha(e, 'cadastrar produto'), 'error')

    return render_template('cadastro.html')


@app.route('/admin/editar/<produto_id>', methods=['GET', 'POST'])
def editar(produto_id):
    redir = _login_requerido()
    if redir: return redir
    fornecedor = _fornecedor_sessao()
    if not fornecedor:
        return redirect(url_for('login'))

    try:
        plan = abrir_planilha()
        aba  = obter_aba_produtos(plan)
        linha_idx, _, produto = encontrar_produto(aba, produto_id, fornecedor)

        if not produto:
            flash('Produto não encontrado.', 'error')
            return redirect(url_for('painel'))

        if request.method == 'POST':
            nome_produto    = request.form.get('nome_produto', '').strip()
            categoria       = request.form.get('categoria', '').strip()
            preco           = parse_preco(request.form.get('preco', ''))
            estoque         = parse_int(request.form.get('estoque', '0'))
            tamanhos        = request.form.get('tamanhos', '').strip()
            disponibilidade = request.form.get('disponibilidade', 'Pronta Entrega')

            if not nome_produto or not categoria:
                flash('Preencha nome e categoria.', 'error')
                return render_template('editar.html', produto=produto)
            if preco <= 0:
                flash('Preço inválido.', 'error')
                return render_template('editar.html', produto=produto)

            caminho_imagem = (request.form.get('url_imagem', '').strip()
                              or produto['imagem'])
            try:
                caminho_imagem = _salvar_imagem(request.files.get('imagem')) or caminho_imagem
            except ValueError as e:
                flash(str(e), 'error')
                return render_template('editar.html', produto=produto)

            update_dict_row(aba, linha_idx, {
                'nome do produto': nome_produto,
                'categoria':       categoria,
                'preço':           round(preco, 2),
                'estoque':         estoque,
                'url da imagem':   caminho_imagem,
                'tamanhos':        tamanhos,
                'disponibilidade': disponibilidade,
                'fornecedor':      fornecedor,
            }, PRODUTO_HEADERS, PRODUTO_ALIASES)

            flash('Produto atualizado! ✓', 'success')
            return redirect(url_for('painel'))

    except Exception as e:
        logger.exception("Erro ao editar produto")
        flash(mensagem_erro_planilha(e, 'editar produto'), 'error')
        return redirect(url_for('painel'))

    return render_template('editar.html', produto=produto)


@app.route('/admin/deletar/<produto_id>', methods=['POST'])
def deletar(produto_id):
    redir = _login_requerido()
    if redir: return redir
    fornecedor = _fornecedor_sessao()
    if not fornecedor:
        return redirect(url_for('login'))
    try:
        plan = abrir_planilha()
        aba  = obter_aba_produtos(plan)
        linha_idx, _, _ = encontrar_produto(aba, produto_id, fornecedor)
        if linha_idx:
            aba.delete_rows(linha_idx)
            limpar_cache_produtos()
            flash('Produto removido.', 'success')
        else:
            flash('Produto não encontrado.', 'error')
    except Exception as e:
        logger.exception("Erro ao deletar produto")
        flash(mensagem_erro_planilha(e, 'deletar produto'), 'error')
    return redirect(url_for('painel'))


@app.route('/admin/lancar-venda', methods=['GET', 'POST'])
def registrar_venda():
    redir = _login_requerido()
    if redir: return redir
    fornecedor = _fornecedor_sessao()
    if not fornecedor:
        return redirect(url_for('login'))

    if request.method == 'POST':
        nome_cliente = request.form.get('nome_cliente', '').strip()
        telefone     = _telefone_limpo(request.form.get('telefone', ''))
        id_produto   = request.form.get('id_produto', '').strip()
        quantidade   = max(1, parse_int(request.form.get('quantidade', '1'), 1))
        valor        = parse_preco(request.form.get('valor', '0'))
        obs          = request.form.get('obs', '').strip()

        if not _telefone_valido(telefone):
            flash('Informe um celular/WhatsApp válido com DDD.', 'error')
            return redirect(url_for('registrar_venda'))
        if not nome_cliente:
            flash('Informe o nome do cliente.', 'error')
            return redirect(url_for('registrar_venda'))
        if not id_produto:
            flash('Selecione o produto vendido.', 'error')
            return redirect(url_for('registrar_venda'))

        try:
            plan         = abrir_planilha()
            aba_produtos = obter_aba_produtos(plan)
            aba_p        = garantir_aba(plan, 'pontos', PONTOS_HEADERS, PONTOS_ALIASES)
            aba_v        = garantir_aba(plan, 'vendas',  VENDAS_HEADERS, VENDAS_ALIASES)

            produto_vendido = None
            linha_produto   = None

            if id_produto and id_produto != 'OUTRO':
                linha_produto, _, produto_vendido = encontrar_produto(
                    aba_produtos, id_produto, fornecedor)
                if not produto_vendido:
                    flash('Produto não encontrado para este fornecedor.', 'error')
                    return redirect(url_for('registrar_venda'))
                if produto_vendido['estoque'] < quantidade:
                    flash(f'Estoque insuficiente. Disponível: {produto_vendido["estoque"]} un.', 'error')
                    return redirect(url_for('registrar_venda'))
                if valor <= 0:
                    valor = produto_vendido['preco_raw'] * quantidade

            if valor <= 0:
                flash('Informe um valor de venda válido.', 'error')
                return redirect(url_for('registrar_venda'))

            # Regra de pontos: a cada R$ 89 em compra, soma 20 pontos.
            pontos_ganhos = _calcular_pontos(valor)

            # Atualiza ou cria registro de pontos
            encontrado = False
            for i, r in enumerate(registros_da_aba(aba_p)):
                telefone_registro = valor_por_alias(r, 'telefone', '', PONTOS_ALIASES)
                if _telefone_limpo(telefone_registro) == telefone:
                    novo_pts   = parse_int(r.get('total_pontos', 0)) + pontos_ganhos
                    novo_gasto = parse_preco(r.get('total_gasto', 0)) + valor
                    update_dict_row(aba_p, i + 2, {
                        'nome':        nome_cliente or r.get('nome', ''),
                        'telefone':    telefone,
                        'total_pontos': novo_pts,
                        'total_gasto':  round(novo_gasto, 2),
                    }, PONTOS_HEADERS, PONTOS_ALIASES)
                    encontrado = True
                    break

            if not encontrado:
                append_dict_row(aba_p, {
                    'telefone':     telefone,
                    'nome':         nome_cliente,
                    'total_pontos': pontos_ganhos,
                    'total_gasto':  round(valor, 2),
                    'cadastro':     datetime.now().strftime('%d/%m/%Y'),
                }, PONTOS_HEADERS, PONTOS_ALIASES)

            # Baixa no estoque
            if produto_vendido and linha_produto:
                update_dict_row(aba_produtos, linha_produto, {
                    'estoque':    produto_vendido['estoque'] - quantidade,
                    'fornecedor': fornecedor,
                }, PRODUTO_HEADERS, PRODUTO_ALIASES)

            # Registro da venda
            append_dict_row(aba_v, {
                'data':         datetime.now().strftime('%d/%m/%Y %H:%M'),
                'telefone':     telefone,
                'nome_cliente': nome_cliente,
                'id_produto':   id_produto,
                'valor':        round(valor, 2),
                'pontos':       pontos_ganhos,
                'fornecedor':   fornecedor,
                'obs':          obs,
                'id_venda':     uuid.uuid4().hex[:8],
                'quantidade':   quantidade,
            }, VENDAS_HEADERS, VENDAS_ALIASES)

            flash(f'Venda registrada! +{pontos_ganhos} pontos para {nome_cliente or telefone}. ✓', 'success')
            return redirect(url_for('registrar_venda'))

        except Exception as e:
            logger.exception("Erro ao registrar venda")
            flash(mensagem_erro_planilha(e, 'registrar venda'), 'error')
            return redirect(url_for('registrar_venda'))

    produtos = buscar_produtos(fornecedor=fornecedor)
    return render_template('registrar_venda.html', produtos=produtos, fornecedor=fornecedor)


@app.route('/admin/relatorio', methods=['GET', 'POST'])
def relatorio():
    redir = _login_requerido()
    if redir: return redir

    fornecedor = _fornecedor_sessao()
    if not fornecedor:
        return redirect(url_for('login'))
    hoje = datetime.now().date()
    inicio_padrao = hoje.replace(day=1)
    inicio_str = request.values.get('inicio', inicio_padrao.isoformat())
    fim_str = request.values.get('fim', hoje.isoformat())

    inicio = _parse_data_filtro(inicio_str)
    fim = _parse_data_filtro(fim_str)

    vendas_filtradas = []
    produtos_resumo = {}
    stats = {
        'entradas': 0.0,
        'entradas_fmt': '0,00',
        'saidas': 0,
        'vendas': 0,
        'pontos': 0,
        'ticket_medio': '0,00',
    }

    if not inicio or not fim:
        flash('Informe datas válidas para gerar o relatório.', 'error')
    elif inicio > fim:
        flash('A data de início não pode ser maior que a data final.', 'error')
    else:
        try:
            plan = abrir_planilha()
            aba_v = garantir_aba(plan, 'vendas', VENDAS_HEADERS, VENDAS_ALIASES)
            produtos = buscar_produtos(fornecedor=fornecedor)
            produtos_por_id = {p['id']: p['nome'] for p in produtos}

            for venda in registros_da_aba(aba_v):
                fornecedor_venda = valor_por_alias(venda, 'fornecedor', '', VENDAS_ALIASES)
                if not fornecedor_permitido(fornecedor_venda, fornecedor):
                    continue

                data_bruta = valor_por_alias(venda, 'data', '', VENDAS_ALIASES)
                data_venda = _parse_data_planilha(data_bruta)
                if not data_venda or not (inicio <= data_venda.date() <= fim):
                    continue

                id_produto = str(valor_por_alias(venda, 'id_produto', '', VENDAS_ALIASES) or 'OUTRO')
                valor = parse_preco(valor_por_alias(venda, 'valor', 0, VENDAS_ALIASES))
                quantidade = max(1, parse_int(valor_por_alias(venda, 'quantidade', 1, VENDAS_ALIASES), 1))
                pontos = parse_int(valor_por_alias(venda, 'pontos', 0, VENDAS_ALIASES), 0)
                produto_nome = produtos_por_id.get(id_produto, 'Outro / Serviço' if id_produto == 'OUTRO' else id_produto)

                item = {
                    'data_dt': data_venda,
                    'data': data_venda.strftime('%d/%m/%Y %H:%M'),
                    'telefone': valor_por_alias(venda, 'telefone', '', VENDAS_ALIASES),
                    'cliente': valor_por_alias(venda, 'nome_cliente', '', VENDAS_ALIASES),
                    'produto_id': id_produto,
                    'produto': produto_nome,
                    'valor': valor,
                    'valor_fmt': formatar_preco(valor),
                    'pontos': pontos,
                    'quantidade': quantidade,
                    'id_venda': valor_por_alias(venda, 'id_venda', '', VENDAS_ALIASES),
                }
                vendas_filtradas.append(item)

                stats['entradas'] += valor
                stats['saidas'] += quantidade
                stats['pontos'] += pontos

                resumo = produtos_resumo.setdefault(id_produto, {
                    'produto': produto_nome,
                    'quantidade': 0,
                    'receita': 0.0,
                    'vendas': 0,
                })
                resumo['quantidade'] += quantidade
                resumo['receita'] += valor
                resumo['vendas'] += 1

            vendas_filtradas.sort(key=lambda v: v['data_dt'], reverse=True)
            stats['vendas'] = len(vendas_filtradas)
            stats['entradas_fmt'] = formatar_preco(stats['entradas'])
            stats['ticket_medio'] = formatar_preco(stats['entradas'] / stats['vendas']) if stats['vendas'] else '0,00'

            for resumo in produtos_resumo.values():
                resumo['receita_fmt'] = formatar_preco(resumo['receita'])

        except Exception as e:
            logger.exception("Erro ao gerar relatório")
            flash(mensagem_erro_planilha(e, 'gerar relatório'), 'error')

    resumo_produtos = sorted(
        produtos_resumo.values(),
        key=lambda item: (item['receita'], item['quantidade']),
        reverse=True,
    )

    return render_template(
        'relatorio.html',
        fornecedor=fornecedor,
        inicio=inicio_str,
        fim=fim_str,
        stats=stats,
        vendas=vendas_filtradas,
        resumo_produtos=resumo_produtos,
    )


# ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, port=5000)
