from flask import Flask, render_template, request, redirect, flash
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timezone
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


@app.route('/')
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
        }
        supabase.table('demandas').insert(dados).execute()
        flash('Demanda criada com sucesso!')
        return redirect('/')
    return render_template('nova_demanda.html', prioridades=PRIORIDADES_VALIDAS)


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
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
def deletar(id):
    supabase.table('demandas').delete().eq('id', id).execute()
    flash('Demanda deletada!')
    return redirect('/')


@app.route('/buscar')
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
def detalhes(id):
    demanda = supabase.table('demandas').select('*').eq('id', id).single().execute()
    comentarios = supabase.table('comentarios').select('*').eq('demanda_id', id).order('data').execute()
    return render_template('detalhes.html', demanda=demanda.data, comentarios=comentarios.data)


@app.route('/adicionar_comentario/<int:demanda_id>', methods=['POST'])
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