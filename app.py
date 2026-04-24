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
    query = supabase.table('demandas').select('*')
    if filtro in PRIORIDADES_VALIDAS:
        query = query.eq('prioridade', filtro)
    res = query.execute()

    # Ordenar: prioridade (Alta > Média > Baixa) e depois FIFO por data_criacao
    dados = sorted(res.data, key=lambda d: (
        ORDEM_PRIORIDADE.get(d.get('prioridade', 'Média'), 2),
        d.get('data_criacao', '')
    ))

    # Anotar dias parado em cada demanda
    for d in dados:
        d['dias_parada'] = calcular_dias_parada(d.get('data_criacao', ''))

    return render_template('index.html', demandas=dados, filtro=filtro, dias_parada_limite=DIAS_PARADA)


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
            'solicitante': request.form['solicitante'],
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
    res = supabase.table('demandas').select('*').eq('id', id).single().execute()
    demanda_atual = res.data

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


@app.route('/deletar/<int:id>')
@login_required
def deletar(id):
    supabase.table('demandas').delete().eq('id', id).execute()
    flash('Demanda deletada!')
    return redirect('/')


@app.route('/buscar')
@login_required
def buscar():
    termo = request.args.get('q', '')
    res = supabase.table('demandas').select('*').ilike('titulo', f'%{termo}%').execute()

    dados = sorted(res.data, key=lambda d: (
        ORDEM_PRIORIDADE.get(d.get('prioridade', 'Média'), 2),
        d.get('data_criacao', '')
    ))
    for d in dados:
        d['dias_parada'] = calcular_dias_parada(d.get('data_criacao', ''))

    return render_template('index.html', demandas=dados, filtro='Todas', dias_parada_limite=DIAS_PARADA)


@app.route('/detalhes/<int:id>')
@login_required
def detalhes(id):
    demanda = supabase.table('demandas').select('*').eq('id', id).single().execute()
    comentarios = supabase.table('comentarios').select('*').eq('demanda_id', id).order('data').execute()
    return render_template('detalhes.html', demanda=demanda.data, comentarios=comentarios.data)


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
