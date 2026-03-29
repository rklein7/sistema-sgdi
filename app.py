from flask import Flask, render_template, request, redirect, flash
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-fallback')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.route('/')
def index():
    res = supabase.table('demandas').select('*').order('id', desc=True).execute()
    return render_template('index.html', demandas=res.data)


@app.route('/nova_demanda', methods=['GET', 'POST'])
def nova_demanda():
    if request.method == 'POST':
        dados = {
            'titulo':      request.form['titulo'],
            'descricao':   request.form['descricao'],
            'solicitante': request.form['solicitante'],
        }
        supabase.table('demandas').insert(dados).execute()
        flash('Demanda criada com sucesso!')
        return redirect('/')
    return render_template('nova_demanda.html')


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar(id):
    if request.method == 'POST':
        dados = {
            'titulo':      request.form['titulo'],
            'descricao':   request.form['descricao'],
            'solicitante': request.form['solicitante'],
        }
        supabase.table('demandas').update(dados).eq('id', id).execute()
        flash('Demanda atualizada!')
        return redirect('/')

    res = supabase.table('demandas').select('*').eq('id', id).single().execute()
    return render_template('editar.html', demanda=res.data)


@app.route('/deletar/<int:id>')
def deletar(id):
    supabase.table('demandas').delete().eq('id', id).execute()
    flash('Demanda deletada!')
    return redirect('/')


@app.route('/buscar')
def buscar():
    termo = request.args.get('q', '')
    # Supabase suporta busca por ilike (case-insensitive)
    res = supabase.table('demandas').select('*').ilike('titulo', f'%{termo}%').execute()
    return render_template('index.html', demandas=res.data)


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

