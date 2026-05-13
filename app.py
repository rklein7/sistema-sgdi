from flask import Flask, render_template, request, redirect, flash, session, make_response
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timezone
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

import csv
import io
import os

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_LEFT

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-fallback')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

PRIORIDADES_VALIDAS = ['Alta', 'Média', 'Baixa']
ORDEM_PRIORIDADE = {'Alta': 1, 'Média': 2, 'Baixa': 3}
DIAS_PARADA = 3  # configurável


# ---------------------------------------------------------------------------
# Helpers de domínio
# ---------------------------------------------------------------------------

def calcular_dias_parada(data_str):
    """Retorna quantos dias se passaram desde data_str."""
    try:
        data = datetime.fromisoformat(data_str.replace('Z', '+00:00'))
        agora = datetime.now(timezone.utc)
        return (agora - data).days
    except Exception:
        return 0


def preparar_demandas(demandas):
    dados = sorted(demandas or [], key=lambda d: (
        ORDEM_PRIORIDADE.get(d.get('prioridade', 'Média'), 2),
        d.get('data_criacao', '')
    ))
    for demanda in dados:
        demanda['dias_parada'] = calcular_dias_parada(demanda.get('data_criacao', ''))
    return dados


def listar_solicitantes(demandas):
    return sorted({
        demanda.get('solicitante')
        for demanda in demandas or []
        if demanda.get('solicitante')
    }, key=str.lower)


def gerar_relatorio_solicitantes(demandas):
    resumo = {}
    for demanda in demandas or []:
        chave = demanda.get('solicitante') or 'Sem solicitante'
        item = resumo.setdefault(chave, {
            'solicitante': chave,
            'total': 0,
            'alta': 0,
            'media': 0,
            'baixa': 0,
            'paradas': 0,
        })
        prioridade = demanda.get('prioridade')
        item['total'] += 1
        if prioridade == 'Alta':
            item['alta'] += 1
        elif prioridade == 'Média':
            item['media'] += 1
        elif prioridade == 'Baixa':
            item['baixa'] += 1
        if calcular_dias_parada(demanda.get('data_criacao', '')) >= DIAS_PARADA:
            item['paradas'] += 1

    return sorted(resumo.values(), key=lambda item: (-item['total'], item['solicitante'].lower()))


def usuario_pode_gerenciar(demanda):
    return demanda and demanda.get('usuario_id') == session.get('usuario_id')


def filtrar_criticas(demandas):
    """Retorna demandas de prioridade Alta E com dias_parada >= DIAS_PARADA."""
    return [
        d for d in (demandas or [])
        if d.get('prioridade') == 'Alta'
        and d.get('dias_parada', 0) >= DIAS_PARADA
    ]


def buscar_demanda(id):
    resposta = supabase.table('demandas').select('*').eq('id', id).execute()
    return resposta.data[0] if resposta.data else None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get('usuario_id'):
            flash('Faça login para continuar')
            return redirect('/login')
        return view_func(*args, **kwargs)
    return wrapped_view


@app.context_processor
def inject_usuario_logado():
    return {
        'usuario_logado': {
            'id': session.get('usuario_id'),
            'nome': session.get('usuario_nome'),
            'cargo': session.get('usuario_cargo'),
        }
    }


# ---------------------------------------------------------------------------
# Rotas de autenticação
# ---------------------------------------------------------------------------

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        confirmar_senha = request.form.get('confirmar_senha', '')
        cargo = request.form.get('cargo', '').strip()

        if senha != confirmar_senha:
            flash('As senhas não coincidem')
            return redirect('/cadastro')

        usuario_existente = (
            supabase.table('usuarios')
            .select('id')
            .eq('email', email)
            .execute()
        )

        if usuario_existente.data:
            flash('E-mail já cadastrado')
            return redirect('/cadastro')

        senha_hash = generate_password_hash(senha)
        dados = {
            'nome': nome,
            'email': email,
            'senha_hash': senha_hash,
            'cargo': cargo,
            'criado_em': datetime.now(timezone.utc).isoformat(),
        }
        supabase.table('usuarios').insert(dados).execute()
        flash('Cadastro realizado com sucesso!')
        return redirect('/login')

    return render_template('cadastro.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        resposta = (
            supabase.table('usuarios')
            .select('*')
            .eq('email', email)
            .execute()
        )

        usuario = resposta.data[0] if resposta.data else None
        if not usuario or not check_password_hash(usuario['senha_hash'], senha):
            flash('E-mail ou senha incorretos')
            return redirect('/login')

        session['usuario_id'] = usuario['id']
        session['usuario_nome'] = usuario['nome']
        session['usuario_cargo'] = usuario['cargo']

        flash(f"Bem-vindo, {usuario['nome']}!")
        return redirect('/')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ---------------------------------------------------------------------------
# Rotas principais
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def index():
    filtro = request.args.get('prioridade', 'Todas')
    solicitante = request.args.get('solicitante', '').strip()
    query = supabase.table('demandas').select('*')
    if filtro in PRIORIDADES_VALIDAS:
        query = query.eq('prioridade', filtro)
    if solicitante:
        query = query.eq('solicitante', solicitante)
    res = query.execute()

    todos = supabase.table('demandas').select('*').execute()
    todos_preparados = preparar_demandas(todos.data)
    solicitantes = listar_solicitantes(todos.data)
    dados = preparar_demandas(res.data)
    criticas = filtrar_criticas(todos_preparados)

    return render_template(
        'index.html',
        demandas=dados,
        filtro=filtro,
        solicitante=solicitante,
        solicitantes=solicitantes,
        prioridades=PRIORIDADES_VALIDAS,
        dias_parada_limite=DIAS_PARADA,
        criticas=criticas,
    )


@app.route('/nova_demanda', methods=['GET', 'POST'])
@login_required
def nova_demanda():
    if request.method == 'POST':
        prioridade = request.form.get('prioridade', 'Média')
        if prioridade not in PRIORIDADES_VALIDAS:
            flash('Prioridade inválida.')
            return redirect('/nova_demanda')

        dados = {
            'titulo':      request.form['titulo'],
            'descricao':   request.form['descricao'],
            'solicitante': session['usuario_nome'],
            'prioridade':  prioridade,
            'usuario_id':  session['usuario_id'],
        }
        supabase.table('demandas').insert(dados).execute()
        flash('Demanda criada com sucesso!')
        return redirect('/')
    return render_template('nova_demanda.html', prioridades=PRIORIDADES_VALIDAS)


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    demanda_atual = buscar_demanda(id)
    if not demanda_atual:
        flash('Demanda não encontrada.')
        return redirect('/')

    if not usuario_pode_gerenciar(demanda_atual):
        flash('Você não tem permissão para editar esta demanda.')
        return redirect('/')

    if request.method == 'POST':
        nova_prioridade = request.form.get('prioridade', demanda_atual['prioridade'])

        if ORDEM_PRIORIDADE.get(nova_prioridade, 2) < ORDEM_PRIORIDADE.get(demanda_atual['prioridade'], 2):
            flash('Não é permitido aumentar a prioridade.')
            return redirect(f'/editar/{id}')

        if nova_prioridade not in PRIORIDADES_VALIDAS:
            flash('Prioridade inválida.')
            return redirect(f'/editar/{id}')

        dados = {
            'titulo':      request.form['titulo'],
            'descricao':   request.form['descricao'],
            'solicitante': request.form['solicitante'],
            'prioridade':  nova_prioridade,
        }
        supabase.table('demandas').update(dados).eq('id', id).execute()
        flash('Demanda atualizada!')
        return redirect('/')

    return render_template('editar.html', demanda=demanda_atual, prioridades=PRIORIDADES_VALIDAS)


@app.route('/deletar/<int:id>', methods=['POST'])
@login_required
def deletar(id):
    demanda = buscar_demanda(id)
    if not demanda:
        flash('Demanda não encontrada.')
        return redirect('/')

    if not usuario_pode_gerenciar(demanda):
        flash('Você não tem permissão para deletar esta demanda.')
        return redirect('/')

    supabase.table('demandas').delete().eq('id', id).execute()
    flash('Demanda deletada!')
    return redirect('/')


@app.route('/buscar')
@login_required
def buscar():
    termo = request.args.get('q', '')
    res = supabase.table('demandas').select('*').ilike('titulo', f'%{termo}%').execute()
    todos = supabase.table('demandas').select('solicitante').execute()

    dados = preparar_demandas(res.data)

    return render_template(
        'index.html',
        demandas=dados,
        filtro='Todas',
        solicitante='',
        solicitantes=listar_solicitantes(todos.data),
        prioridades=PRIORIDADES_VALIDAS,
        dias_parada_limite=DIAS_PARADA
    )


# ---------------------------------------------------------------------------
# Relatórios — visualização + exportação
# ---------------------------------------------------------------------------

def _coletar_dados_relatorio(filtro_prioridade, filtro_solicitante):
    """Busca e filtra demandas para o relatório. Retorna um dict com tudo."""
    todas_res = supabase.table('demandas').select('*').execute()
    todas_demandas = todas_res.data or []
    solicitantes = listar_solicitantes(todas_demandas)
    resumo_solicitantes = gerar_relatorio_solicitantes(todas_demandas)

    demandas_filtradas = todas_demandas
    if filtro_prioridade in PRIORIDADES_VALIDAS:
        demandas_filtradas = [
            d for d in demandas_filtradas if d.get('prioridade') == filtro_prioridade
        ]
    if filtro_solicitante:
        demandas_filtradas = [
            d for d in demandas_filtradas if d.get('solicitante') == filtro_solicitante
        ]

    total_paradas = sum(
        1 for d in todas_demandas
        if calcular_dias_parada(d.get('data_criacao', '')) >= DIAS_PARADA
    )

    todos_preparados = preparar_demandas(todas_demandas)
    criticas = filtrar_criticas(todos_preparados)

    return {
        'todas_demandas': todas_demandas,
        'demandas_filtradas': preparar_demandas(demandas_filtradas),
        'resumo_solicitantes': resumo_solicitantes,
        'solicitantes': solicitantes,
        'total_demandas': len(todas_demandas),
        'total_solicitantes': len(solicitantes),
        'total_paradas': total_paradas,
        'criticas': criticas,
        'total_criticas': len(criticas),
    }


@app.route('/relatorios')
@login_required
def relatorios():
    filtro_prioridade  = request.args.get('prioridade', 'Todas')
    filtro_solicitante = request.args.get('solicitante', '').strip()

    dados = _coletar_dados_relatorio(filtro_prioridade, filtro_solicitante)

    return render_template(
        'relatorios.html',
        resumo_solicitantes=dados['resumo_solicitantes'],
        demandas=dados['demandas_filtradas'],
        solicitantes=dados['solicitantes'],
        prioridades=PRIORIDADES_VALIDAS,
        filtro_prioridade=filtro_prioridade,
        filtro_solicitante=filtro_solicitante,
        total_demandas=dados['total_demandas'],
        total_solicitantes=dados['total_solicitantes'],
        total_paradas=dados['total_paradas'],
        dias_parada_limite=DIAS_PARADA,
        criticas=dados['criticas'],
        total_criticas=dados['total_criticas'],
    )


# ── Exportar CSV ─────────────────────────────────────────────────────────────

@app.route('/relatorios/exportar/csv')
@login_required
def exportar_csv():
    filtro_prioridade  = request.args.get('prioridade', 'Todas')
    filtro_solicitante = request.args.get('solicitante', '').strip()
    dados = _coletar_dados_relatorio(filtro_prioridade, filtro_solicitante)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # --- Seção 1: Resumo geral ---
    writer.writerow(['RELATÓRIO DE DEMANDAS'])
    writer.writerow([f'Gerado em: {datetime.now().strftime("%d/%m/%Y %H:%M")}'])
    writer.writerow([])
    writer.writerow(['RESUMO GERAL'])
    writer.writerow(['Total de demandas', dados['total_demandas']])
    writer.writerow(['Total de solicitantes', dados['total_solicitantes']])
    writer.writerow(['Demandas paradas (≥ 3 dias)', dados['total_paradas']])
    writer.writerow([])

    # --- Seção 2: Resumo por solicitante ---
    writer.writerow(['RESUMO POR SOLICITANTE'])
    writer.writerow(['Solicitante', 'Total', 'Alta', 'Média', 'Baixa', 'Paradas'])
    for item in dados['resumo_solicitantes']:
        writer.writerow([
            item['solicitante'],
            item['total'],
            item['alta'],
            item['media'],
            item['baixa'],
            item['paradas'],
        ])
    writer.writerow([])

    # --- Seção 3: Demandas detalhadas ---
    writer.writerow(['DEMANDAS DETALHADAS'])
    if filtro_prioridade != 'Todas' or filtro_solicitante:
        filtros_ativos = []
        if filtro_prioridade != 'Todas':
            filtros_ativos.append(f'Prioridade: {filtro_prioridade}')
        if filtro_solicitante:
            filtros_ativos.append(f'Solicitante: {filtro_solicitante}')
        writer.writerow([f'Filtros aplicados: {" | ".join(filtros_ativos)}'])

    writer.writerow(['ID', 'Título', 'Descrição', 'Solicitante', 'Prioridade',
                     'Data de Criação', 'Dias Parada'])
    for d in dados['demandas_filtradas']:
        data_criacao = d.get('data_criacao', '')
        try:
            dt = datetime.fromisoformat(data_criacao.replace('Z', '+00:00'))
            data_fmt = dt.strftime('%d/%m/%Y %H:%M')
        except Exception:
            data_fmt = data_criacao

        writer.writerow([
            d.get('id', ''),
            d.get('titulo', ''),
            d.get('descricao', ''),
            d.get('solicitante', ''),
            d.get('prioridade', ''),
            data_fmt,
            d.get('dias_parada', 0),
        ])

    # Resposta com BOM UTF-8 para o Excel abrir corretamente
    csv_bytes = '\ufeff' + output.getvalue()
    response = make_response(csv_bytes.encode('utf-8'))
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = (
        f'attachment; filename="relatorio_demandas_{datetime.now().strftime("%Y%m%d_%H%M")}.csv"'
    )
    return response


# ── Exportar Excel (.xlsx) ───────────────────────────────────────────────────

@app.route('/relatorios/exportar/excel')
@login_required
def exportar_excel():
    filtro_prioridade  = request.args.get('prioridade', 'Todas')
    filtro_solicitante = request.args.get('solicitante', '').strip()
    dados = _coletar_dados_relatorio(filtro_prioridade, filtro_solicitante)

    wb = Workbook()

    # Estilos reutilizáveis
    cor_cabecalho   = '2563EB'   # azul
    cor_alta        = 'FEE2E2'   # vermelho claro
    cor_media       = 'FEF9C3'   # amarelo claro
    cor_baixa       = 'DCFCE7'   # verde claro
    cor_parada      = 'FCA5A5'   # vermelho mais forte (paradas)
    cor_resumo_bg   = 'EFF6FF'   # azul muito claro

    fonte_titulo  = Font(name='Arial', bold=True, size=14, color='FFFFFF')
    fonte_sub     = Font(name='Arial', bold=True, size=11)
    fonte_cabecalho = Font(name='Arial', bold=True, size=10, color='FFFFFF')
    fonte_normal  = Font(name='Arial', size=10)
    fonte_negrito = Font(name='Arial', bold=True, size=10)

    fill_cabecalho = PatternFill('solid', start_color=cor_cabecalho)
    fill_resumo    = PatternFill('solid', start_color=cor_resumo_bg)

    borda_fina = Border(
        left=Side(style='thin', color='D1D5DB'),
        right=Side(style='thin', color='D1D5DB'),
        top=Side(style='thin', color='D1D5DB'),
        bottom=Side(style='thin', color='D1D5DB'),
    )

    centro = Alignment(horizontal='center', vertical='center', wrap_text=True)
    esquerda = Alignment(horizontal='left', vertical='center', wrap_text=True)

    # ── Aba 1: Resumo ──────────────────────────────────────────────────────
    ws_resumo = wb.active
    ws_resumo.title = 'Resumo'
    ws_resumo.sheet_view.showGridLines = False

    # Título principal
    ws_resumo.merge_cells('A1:F1')
    ws_resumo['A1'] = 'RELATÓRIO DE DEMANDAS'
    ws_resumo['A1'].font = fonte_titulo
    ws_resumo['A1'].fill = fill_cabecalho
    ws_resumo['A1'].alignment = centro
    ws_resumo.row_dimensions[1].height = 30

    # Data de geração
    ws_resumo.merge_cells('A2:F2')
    ws_resumo['A2'] = f'Gerado em: {datetime.now().strftime("%d/%m/%Y às %H:%M")}'
    ws_resumo['A2'].font = Font(name='Arial', italic=True, size=9, color='6B7280')
    ws_resumo['A2'].alignment = centro
    ws_resumo.row_dimensions[2].height = 16

    ws_resumo.append([])  # linha vazia (linha 3)

    # Cards de resumo geral (linha 4-5)
    ws_resumo.merge_cells('A4:B5')
    ws_resumo['A4'] = 'Total de Demandas'
    ws_resumo['A4'].font = fonte_negrito
    ws_resumo['A4'].alignment = centro
    ws_resumo['A4'].fill = fill_resumo
    ws_resumo['A4'].border = borda_fina

    ws_resumo.merge_cells('C4:D5')
    ws_resumo['C4'] = 'Total de Solicitantes'
    ws_resumo['C4'].font = fonte_negrito
    ws_resumo['C4'].alignment = centro
    ws_resumo['C4'].fill = fill_resumo
    ws_resumo['C4'].border = borda_fina

    ws_resumo.merge_cells('E4:F5')
    ws_resumo['E4'] = 'Demandas Paradas'
    ws_resumo['E4'].font = fonte_negrito
    ws_resumo['E4'].alignment = centro
    ws_resumo['E4'].fill = fill_resumo
    ws_resumo['E4'].border = borda_fina

    ws_resumo.merge_cells('A6:B7')
    ws_resumo['A6'] = dados['total_demandas']
    ws_resumo['A6'].font = Font(name='Arial', bold=True, size=22, color=cor_cabecalho)
    ws_resumo['A6'].alignment = centro
    ws_resumo['A6'].border = borda_fina

    ws_resumo.merge_cells('C6:D7')
    ws_resumo['C6'] = dados['total_solicitantes']
    ws_resumo['C6'].font = Font(name='Arial', bold=True, size=22, color='059669')
    ws_resumo['C6'].alignment = centro
    ws_resumo['C6'].border = borda_fina

    ws_resumo.merge_cells('E6:F7')
    ws_resumo['E6'] = dados['total_paradas']
    ws_resumo['E6'].font = Font(name='Arial', bold=True, size=22, color='DC2626')
    ws_resumo['E6'].alignment = centro
    ws_resumo['E6'].border = borda_fina

    ws_resumo.row_dimensions[4].height = 20
    ws_resumo.row_dimensions[5].height = 20
    ws_resumo.row_dimensions[6].height = 28
    ws_resumo.row_dimensions[7].height = 28

    ws_resumo.append([])  # linha 8 vazia

    # Tabela de resumo por solicitante
    linha_sub = 9
    ws_resumo.merge_cells(f'A{linha_sub}:F{linha_sub}')
    ws_resumo[f'A{linha_sub}'] = 'RESUMO POR SOLICITANTE'
    ws_resumo[f'A{linha_sub}'].font = fonte_sub
    ws_resumo[f'A{linha_sub}'].alignment = esquerda
    ws_resumo.row_dimensions[linha_sub].height = 20

    linha_cab = linha_sub + 1
    cabecalhos_resumo = ['Solicitante', 'Total', 'Alta', 'Média', 'Baixa', 'Paradas (≥3 dias)']
    for col, titulo in enumerate(cabecalhos_resumo, start=1):
        cel = ws_resumo.cell(row=linha_cab, column=col, value=titulo)
        cel.font = fonte_cabecalho
        cel.fill = fill_cabecalho
        cel.alignment = centro
        cel.border = borda_fina
    ws_resumo.row_dimensions[linha_cab].height = 22

    for item in dados['resumo_solicitantes']:
        linha_cab += 1
        valores = [
            item['solicitante'], item['total'], item['alta'],
            item['media'], item['baixa'], item['paradas']
        ]
        for col, val in enumerate(valores, start=1):
            cel = ws_resumo.cell(row=linha_cab, column=col, value=val)
            cel.font = fonte_normal
            cel.alignment = centro if col > 1 else esquerda
            cel.border = borda_fina
        ws_resumo.row_dimensions[linha_cab].height = 18

    # Larguras das colunas — aba Resumo
    larguras_resumo = [30, 10, 10, 10, 10, 18]
    for i, larg in enumerate(larguras_resumo, start=1):
        ws_resumo.column_dimensions[get_column_letter(i)].width = larg

    # ── Aba 2: Demandas detalhadas ─────────────────────────────────────────
    ws_det = wb.create_sheet('Demandas Detalhadas')
    ws_det.sheet_view.showGridLines = False

    # Título
    ws_det.merge_cells('A1:G1')
    ws_det['A1'] = 'DEMANDAS DETALHADAS'
    ws_det['A1'].font = fonte_titulo
    ws_det['A1'].fill = fill_cabecalho
    ws_det['A1'].alignment = centro
    ws_det.row_dimensions[1].height = 30

    # Filtros ativos
    filtros_txt = []
    if filtro_prioridade != 'Todas':
        filtros_txt.append(f'Prioridade: {filtro_prioridade}')
    if filtro_solicitante:
        filtros_txt.append(f'Solicitante: {filtro_solicitante}')

    ws_det.merge_cells('A2:G2')
    ws_det['A2'] = ('Filtros: ' + ' | '.join(filtros_txt)) if filtros_txt else 'Sem filtros aplicados'
    ws_det['A2'].font = Font(name='Arial', italic=True, size=9, color='6B7280')
    ws_det['A2'].alignment = centro
    ws_det.row_dimensions[2].height = 16

    ws_det.append([])  # linha 3

    # Cabeçalhos
    cabecalhos_det = ['ID', 'Título', 'Descrição', 'Solicitante', 'Prioridade',
                      'Data de Criação', 'Dias Parada']
    for col, titulo in enumerate(cabecalhos_det, start=1):
        cel = ws_det.cell(row=4, column=col, value=titulo)
        cel.font = fonte_cabecalho
        cel.fill = fill_cabecalho
        cel.alignment = centro
        cel.border = borda_fina
    ws_det.row_dimensions[4].height = 22

    # Mapa de cores de prioridade
    fill_alta  = PatternFill('solid', start_color=cor_alta)
    fill_media = PatternFill('solid', start_color=cor_media)
    fill_baixa = PatternFill('solid', start_color=cor_baixa)
    fill_parada = PatternFill('solid', start_color=cor_parada)

    for idx, d in enumerate(dados['demandas_filtradas'], start=5):
        data_criacao = d.get('data_criacao', '')
        try:
            dt = datetime.fromisoformat(data_criacao.replace('Z', '+00:00'))
            data_fmt = dt.strftime('%d/%m/%Y %H:%M')
        except Exception:
            data_fmt = data_criacao

        prioridade = d.get('prioridade', '')
        dias_parada = d.get('dias_parada', 0)

        # Escolhe fill de linha conforme prioridade (vermelho mais forte se parada há 3+ dias)
        if dias_parada >= DIAS_PARADA:
            fill_linha = fill_parada
        elif prioridade == 'Alta':
            fill_linha = fill_alta
        elif prioridade == 'Média':
            fill_linha = fill_media
        else:
            fill_linha = fill_baixa

        valores = [
            d.get('id', ''),
            d.get('titulo', ''),
            d.get('descricao', ''),
            d.get('solicitante', ''),
            prioridade,
            data_fmt,
            dias_parada,
        ]
        for col, val in enumerate(valores, start=1):
            cel = ws_det.cell(row=idx, column=col, value=val)
            cel.font = fonte_normal
            cel.fill = fill_linha
            cel.border = borda_fina
            cel.alignment = centro if col in (1, 5, 6, 7) else esquerda
        ws_det.row_dimensions[idx].height = 18

    # Larguras das colunas — aba Demandas
    larguras_det = [8, 35, 50, 20, 12, 18, 12]
    for i, larg in enumerate(larguras_det, start=1):
        ws_det.column_dimensions[get_column_letter(i)].width = larg

    # ── Salvar em buffer ───────────────────────────────────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers['Content-Type'] = (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response.headers['Content-Disposition'] = (
        f'attachment; filename="relatorio_demandas_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx"'
    )
    return response


# ── Exportar PDF ─────────────────────────────────────────────────────────────

@app.route('/relatorios/exportar/pdf')
@login_required
def exportar_pdf():
    filtro_prioridade  = request.args.get('prioridade', 'Todas')
    filtro_solicitante = request.args.get('solicitante', '').strip()
    dados = _coletar_dados_relatorio(filtro_prioridade, filtro_solicitante)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    cor_azul = colors.HexColor('#2563EB')
    cor_cinza = colors.HexColor('#6B7280')

    estilo_titulo = ParagraphStyle(
        'Titulo',
        parent=styles['Title'],
        fontSize=16,
        textColor=colors.white,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    estilo_sub = ParagraphStyle(
        'Sub',
        parent=styles['Normal'],
        fontSize=11,
        textColor=cor_azul,
        fontName='Helvetica-Bold',
        spaceBefore=12,
        spaceAfter=4,
    )
    estilo_meta = ParagraphStyle(
        'Meta',
        parent=styles['Normal'],
        fontSize=8,
        textColor=cor_cinza,
        alignment=TA_CENTER,
    )

    elementos = []

    # ── Cabeçalho ──────────────────────────────────────────────────────────
    titulo_tabela = Table(
        [[Paragraph('RELATÓRIO DE DEMANDAS', estilo_titulo)]],
        colWidths=[doc.width],
    )
    titulo_tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), cor_azul),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('ROUNDEDCORNERS', [4]),
    ]))
    elementos.append(titulo_tabela)
    elementos.append(Spacer(1, 0.2 * cm))
    elementos.append(Paragraph(
        f'Gerado em {datetime.now().strftime("%d/%m/%Y às %H:%M")}', estilo_meta
    ))

    # Filtros ativos
    filtros_txt = []
    if filtro_prioridade != 'Todas':
        filtros_txt.append(f'Prioridade: {filtro_prioridade}')
    if filtro_solicitante:
        filtros_txt.append(f'Solicitante: {filtro_solicitante}')
    if filtros_txt:
        elementos.append(Paragraph(
            f'Filtros aplicados: {" | ".join(filtros_txt)}', estilo_meta
        ))

    elementos.append(Spacer(1, 0.4 * cm))

    # ── Cards de resumo ────────────────────────────────────────────────────
    estilo_card_label = ParagraphStyle('CardLabel', parent=styles['Normal'],
                                       fontSize=9, textColor=cor_cinza,
                                       alignment=TA_CENTER)
    estilo_card_valor = ParagraphStyle('CardValor', parent=styles['Normal'],
                                       fontSize=20, fontName='Helvetica-Bold',
                                       alignment=TA_CENTER)

    cards_data = [[
        Paragraph('Total de Demandas', estilo_card_label),
        Paragraph('Total de Solicitantes', estilo_card_label),
        Paragraph('Demandas Paradas', estilo_card_label),
    ], [
        Paragraph(str(dados['total_demandas']), estilo_card_valor),
        Paragraph(str(dados['total_solicitantes']), estilo_card_valor),
        Paragraph(str(dados['total_paradas']), estilo_card_valor),
    ]]

    larg_card = doc.width / 3
    tabela_cards = Table(cards_data, colWidths=[larg_card] * 3, rowHeights=[16, 32])
    tabela_cards.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EFF6FF')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#BFDBFE')),
        ('LINEAFTER', (0, 0), (1, -1), 0.5, colors.HexColor('#BFDBFE')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TEXTCOLOR', (0, 1), (0, 1), cor_azul),
        ('TEXTCOLOR', (1, 1), (1, 1), colors.HexColor('#059669')),
        ('TEXTCOLOR', (2, 1), (2, 1), colors.HexColor('#DC2626')),
    ]))
    elementos.append(tabela_cards)
    elementos.append(Spacer(1, 0.5 * cm))

    # ── Tabela: Resumo por solicitante ─────────────────────────────────────
    elementos.append(Paragraph('Resumo por Solicitante', estilo_sub))

    cab_resumo = [['Solicitante', 'Total', 'Alta', 'Média', 'Baixa', 'Paradas (≥3 dias)']]
    linhas_resumo = cab_resumo + [
        [item['solicitante'], item['total'], item['alta'],
         item['media'], item['baixa'], item['paradas']]
        for item in dados['resumo_solicitantes']
    ]

    col_widths_resumo = [
        doc.width * 0.35, doc.width * 0.12, doc.width * 0.12,
        doc.width * 0.12, doc.width * 0.12, doc.width * 0.17,
    ]
    tabela_resumo = Table(linhas_resumo, colWidths=col_widths_resumo, repeatRows=1)
    style_resumo = [
        ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
    ]
    tabela_resumo.setStyle(TableStyle(style_resumo))
    elementos.append(tabela_resumo)
    elementos.append(Spacer(1, 0.5 * cm))

    # ── Tabela: Demandas detalhadas ────────────────────────────────────────
    elementos.append(Paragraph('Demandas Detalhadas', estilo_sub))

    estilo_cel = ParagraphStyle('Cel', parent=styles['Normal'], fontSize=7,
                                leading=9, wordWrap='LTR')

    cab_det = [['ID', 'Título', 'Solicitante', 'Prioridade', 'Data Criação', 'Dias Parada']]

    linhas_det = cab_det.copy()
    for d in dados['demandas_filtradas']:
        data_criacao = d.get('data_criacao', '')
        try:
            dt = datetime.fromisoformat(data_criacao.replace('Z', '+00:00'))
            data_fmt = dt.strftime('%d/%m/%Y\n%H:%M')
        except Exception:
            data_fmt = data_criacao

        linhas_det.append([
            str(d.get('id', '')),
            Paragraph(d.get('titulo', ''), estilo_cel),
            d.get('solicitante', ''),
            d.get('prioridade', ''),
            data_fmt,
            str(d.get('dias_parada', 0)),
        ])

    col_widths_det = [
        doc.width * 0.06,
        doc.width * 0.35,
        doc.width * 0.18,
        doc.width * 0.12,
        doc.width * 0.15,
        doc.width * 0.14,
    ]
    tabela_det = Table(linhas_det, colWidths=col_widths_det, repeatRows=1)

    style_det = [
        ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (3, 0), (5, -1), 'CENTER'),
        ('ALIGN', (1, 0), (2, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
    ]

    # Colorir linhas por prioridade / parada
    for row_idx, d in enumerate(dados['demandas_filtradas'], start=1):
        prioridade = d.get('prioridade', '')
        dias_parada = d.get('dias_parada', 0)
        if dias_parada >= DIAS_PARADA:
            bg = colors.HexColor('#FCA5A5')
        elif prioridade == 'Alta':
            bg = colors.HexColor('#FEE2E2')
        elif prioridade == 'Média':
            bg = colors.HexColor('#FEF9C3')
        else:
            bg = colors.HexColor('#DCFCE7')
        style_det.append(('BACKGROUND', (0, row_idx), (-1, row_idx), bg))

    tabela_det.setStyle(TableStyle(style_det))
    elementos.append(tabela_det)

    # ── Rodapé via onLaterPages ────────────────────────────────────────────
    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(cor_cinza)
        canvas.drawCentredString(
            doc.pagesize[0] / 2,
            0.8 * cm,
            f'Página {doc.page} — Relatório gerado automaticamente pelo sistema de demandas'
        )
        canvas.restoreState()

    doc.build(elementos, onFirstPage=rodape, onLaterPages=rodape)

    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = (
        f'attachment; filename="relatorio_demandas_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf"'
    )
    return response


# ── Exportar Críticas (Alta + Paradas) — Excel ───────────────────────────────

@app.route('/relatorios/exportar/criticas')
@login_required
def exportar_criticas():
    """Exporta em Excel apenas as demandas de prioridade Alta com dias_parada >= DIAS_PARADA."""
    todas_res = supabase.table('demandas').select('*').execute()
    todas_preparadas = preparar_demandas(todas_res.data or [])
    criticas = filtrar_criticas(todas_preparadas)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Demandas Críticas'
    ws.sheet_view.showGridLines = False

    cor_vermelho   = 'DC2626'
    cor_vermelho_bg = 'FEF2F2'
    cor_laranja_bg  = 'FCA5A5'

    fonte_titulo   = Font(name='Arial', bold=True, size=14, color='FFFFFF')
    fonte_cab      = Font(name='Arial', bold=True, size=10, color='FFFFFF')
    fonte_normal   = Font(name='Arial', size=10)
    fonte_negrito  = Font(name='Arial', bold=True, size=10)

    fill_header  = PatternFill('solid', start_color=cor_vermelho)
    fill_linha   = PatternFill('solid', start_color=cor_vermelho_bg)
    fill_urgente = PatternFill('solid', start_color=cor_laranja_bg)

    borda = Border(
        left=Side(style='thin', color='FECACA'),
        right=Side(style='thin', color='FECACA'),
        top=Side(style='thin', color='FECACA'),
        bottom=Side(style='thin', color='FECACA'),
    )
    centro   = Alignment(horizontal='center', vertical='center', wrap_text=True)
    esquerda = Alignment(horizontal='left', vertical='center', wrap_text=True)

    # Título
    ws.merge_cells('A1:G1')
    ws['A1'] = '⚠ DEMANDAS CRÍTICAS — Alta Prioridade + Paradas'
    ws['A1'].font = fonte_titulo
    ws['A1'].fill = fill_header
    ws['A1'].alignment = centro
    ws.row_dimensions[1].height = 30

    # Subtítulo
    ws.merge_cells('A2:G2')
    ws['A2'] = (
        f'Gerado em {datetime.now().strftime("%d/%m/%Y às %H:%M")}  |  '
        f'Critério: Prioridade Alta + Paradas há ≥ {DIAS_PARADA} dias  |  '
        f'Total: {len(criticas)} demanda(s)'
    )
    ws['A2'].font = Font(name='Arial', italic=True, size=9, color='7F1D1D')
    ws['A2'].alignment = centro
    ws.row_dimensions[2].height = 16

    ws.append([])  # linha 3 vazia

    # Cabeçalhos
    cabecalhos = ['ID', 'Título', 'Descrição', 'Solicitante', 'Prioridade',
                  'Data de Criação', 'Dias Parada']
    for col, titulo in enumerate(cabecalhos, start=1):
        cel = ws.cell(row=4, column=col, value=titulo)
        cel.font = fonte_cab
        cel.fill = fill_header
        cel.alignment = centro
        cel.border = borda
    ws.row_dimensions[4].height = 22

    if not criticas:
        ws.merge_cells('A5:G5')
        ws['A5'] = 'Nenhuma demanda crítica encontrada no momento.'
        ws['A5'].font = Font(name='Arial', italic=True, size=10, color='6B7280')
        ws['A5'].alignment = centro
    else:
        for idx, d in enumerate(criticas, start=5):
            data_str = d.get('data_criacao', '')
            try:
                dt = datetime.fromisoformat(data_str.replace('Z', '+00:00'))
                data_fmt = dt.strftime('%d/%m/%Y %H:%M')
            except Exception:
                data_fmt = data_str

            dias = d.get('dias_parada', 0)
            # Mais de 7 dias: destaque laranja mais forte
            fill_row = fill_urgente if dias >= 7 else fill_linha

            valores = [
                d.get('id', ''), d.get('titulo', ''), d.get('descricao', ''),
                d.get('solicitante', ''), d.get('prioridade', ''), data_fmt, dias,
            ]
            for col, val in enumerate(valores, start=1):
                cel = ws.cell(row=idx, column=col, value=val)
                cel.font = fonte_negrito if col == 7 else fonte_normal
                cel.fill = fill_row
                cel.border = borda
                cel.alignment = centro if col in (1, 5, 6, 7) else esquerda
            ws.row_dimensions[idx].height = 18

    larguras = [8, 35, 50, 20, 12, 18, 12]
    for i, larg in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = larg

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers['Content-Type'] = (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response.headers['Content-Disposition'] = (
        f'attachment; filename="criticas_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx"'
    )
    return response


# ---------------------------------------------------------------------------
# Detalhes e comentários
# ---------------------------------------------------------------------------

@app.route('/detalhes/<int:id>')
@login_required
def detalhes(id):
    demanda = supabase.table('demandas').select('*').eq('id', id).single().execute()
    comentarios = supabase.table('comentarios').select('*').eq('demanda_id', id).order('data').execute()
    return render_template(
        'detalhes.html',
        demanda=demanda.data,
        comentarios=comentarios.data,
        pode_gerenciar=usuario_pode_gerenciar(demanda.data)
    )


@app.route('/adicionar_comentario/<int:demanda_id>', methods=['POST'])
@login_required
def adicionar_comentario(demanda_id):
    dados = {
        'demanda_id': demanda_id,
        'comentario': request.form['comentario'],
        'autor':      request.form['autor'],
    }
    supabase.table('comentarios').insert(dados).execute()
    return redirect(f'/detalhes/{demanda_id}')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')