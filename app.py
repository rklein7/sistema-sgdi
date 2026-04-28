from flask import Flask, render_template, request, redirect, flash, session
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timezone
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-fallback')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

PRIORIDADES_VALIDAS = ['Alta', 'Média', 'Baixa']
ORDEM_PRIORIDADE = {'Alta': 1, 'Média': 2, 'Baixa': 3}
DIAS_PARADA = 3  # configurável


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


def buscar_demanda(id):
    resposta = supabase.table('demandas').select('*').eq('id', id).execute()
    return resposta.data[0] if resposta.data else None


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

    todos = supabase.table('demandas').select('solicitante').execute()
    solicitantes = listar_solicitantes(todos.data)
    dados = preparar_demandas(res.data)

    return render_template(
        'index.html',
        demandas=dados,
        filtro=filtro,
        solicitante=solicitante,
        solicitantes=solicitantes,
        prioridades=PRIORIDADES_VALIDAS,
        dias_parada_limite=DIAS_PARADA
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

        # Bloquear aumento de prioridade
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


@app.route('/relatorios')
@login_required
def relatorios():
    filtro_prioridade = request.args.get('prioridade', 'Todas')
    filtro_solicitante = request.args.get('solicitante', '').strip()

    todas_res = supabase.table('demandas').select('*').execute()
    todas_demandas = todas_res.data or []
    solicitantes = listar_solicitantes(todas_demandas)
    resumo_solicitantes = gerar_relatorio_solicitantes(todas_demandas)

    demandas_filtradas = todas_demandas
    if filtro_prioridade in PRIORIDADES_VALIDAS:
        demandas_filtradas = [
            demanda for demanda in demandas_filtradas
            if demanda.get('prioridade') == filtro_prioridade
        ]
    if filtro_solicitante:
        demandas_filtradas = [
            demanda for demanda in demandas_filtradas
            if demanda.get('solicitante') == filtro_solicitante
        ]

    total_demandas = len(todas_demandas)
    total_solicitantes = len(solicitantes)
    total_paradas = sum(
        1
        for demanda in todas_demandas
        if calcular_dias_parada(demanda.get('data_criacao', '')) >= DIAS_PARADA
    )

    return render_template(
        'relatorios.html',
        resumo_solicitantes=resumo_solicitantes,
        demandas=preparar_demandas(demandas_filtradas),
        solicitantes=solicitantes,
        prioridades=PRIORIDADES_VALIDAS,
        filtro_prioridade=filtro_prioridade,
        filtro_solicitante=filtro_solicitante,
        total_demandas=total_demandas,
        total_solicitantes=total_solicitantes,
        total_paradas=total_paradas,
        dias_parada_limite=DIAS_PARADA
    )


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
