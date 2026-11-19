"""ClinAgenda - sistema de agendamento de consultas para clínicas.

Executar:  python app.py   (cria o banco na primeira vez e sobe em http://127.0.0.1:5000)
"""
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import database
from database import get_db
from models import (Consulta, Especialidade, Paciente, Profissional, Usuario,
                    formatar_cpf, normalizar, somente_digitos)


def carregar_chave_secreta(pasta):
    """A chave que assina o cookie de login não pode ficar no código (o repositório é público).
    Usa a variável de ambiente SECRET_KEY ou, se não houver, gera uma chave aleatória na
    primeira execução e guarda no arquivo .secret_key (que o .gitignore deixa fora do Git)."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    arquivo = os.path.join(pasta, ".secret_key")
    if not os.path.exists(arquivo):
        with open(arquivo, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(arquivo, encoding="utf-8") as f:
        return f.read().strip()


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=carregar_chave_secreta(app.root_path),
        DATABASE=os.path.join(app.root_path, "clinagenda.db"),
    )
    if config:
        app.config.update(config)
    database.init_app(app)
    with app.app_context():
        database.init_db()
    registrar_rotas(app)
    return app


# ---------------------------------------------------------------- segurança --
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.usuario is None:
            return redirect(url_for("login", proximo=request.path))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not g.usuario.is_admin():
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def equipe_required(view):
    """Telas da clínica (pacientes, profissionais, consultas): Administrador e Recepção.
    O paciente usa só a área dele."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not g.usuario.is_equipe():
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def paciente_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not g.usuario.is_paciente():
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def form_str(nome):
    return (request.form.get(nome) or "").strip()


def form_int(nome):
    valor = form_str(nome)
    return int(valor) if valor.isdigit() else None


# -------------------------------------------------------------------- rotas --
def registrar_rotas(app):

    @app.before_request
    def carregar_usuario():
        g.usuario = None
        uid = session.get("usuario_id")
        if uid:
            row = get_db().execute("SELECT * FROM usuario WHERE id = ?", (uid,)).fetchone()
            if row:
                g.usuario = Usuario(row["id"], row["nome"], row["login"], row["perfil"],
                                    row["paciente_id"])
        # proteção CSRF simples: todo POST precisa trazer o token da sessão
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        if request.method == "POST" and not app.config.get("TESTING_SEM_CSRF"):
            if request.form.get("csrf") != session["csrf"]:
                abort(400, "Token CSRF inválido.")

    @app.context_processor
    def contexto():
        return {"csrf": session.get("csrf", ""), "formatar_cpf": formatar_cpf,
                "agora": datetime.now().strftime("%Y-%m-%dT%H:%M"),
                "hoje_iso": date.today().isoformat()}

    @app.template_filter("dt")
    def filtro_data_hora(valor):
        if not valor:
            return ""
        d, _, h = valor.partition("T")
        a, m, dia = d.split("-")
        return f"{dia}/{m}/{a}" + (f" {h[:5]}" if h else "")

    @app.errorhandler(400)
    def requisicao_invalida(_e):
        return render_template("erro.html", codigo=400,
                               msg="Sua sessão expirou ou o formulário está desatualizado. "
                                   "Volte, recarregue a página e tente de novo."), 400

    @app.errorhandler(403)
    def proibido(_e):
        return render_template("erro.html", codigo=403,
                               msg="Você não tem permissão para acessar esta página."), 403

    @app.errorhandler(404)
    def nao_encontrado(_e):
        return render_template("erro.html", codigo=404, msg="Página ou registro não encontrado."), 404

    @app.errorhandler(405)
    def metodo_nao_permitido(_e):
        return render_template("erro.html", codigo=405,
                               msg="Essa ação só pode ser feita pelos botões do sistema."), 405

    @app.errorhandler(500)
    def erro_interno(_e):
        return render_template("erro.html", codigo=500,
                               msg="Ocorreu um erro inesperado. Tente novamente."), 500

    # ------------------------------------------------------- UC01 Autenticar --
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            row = get_db().execute("SELECT * FROM usuario WHERE login = ?",
                                   (form_str("login"),)).fetchone()
            if row and check_password_hash(row["senha_hash"], request.form.get("senha", "")):
                session.clear()
                session["usuario_id"] = row["id"]
                proximo = request.args.get("proximo", "")
                seguro = proximo.startswith("/") and not proximo.startswith("//") and "\\" not in proximo
                return redirect(proximo if seguro else url_for("inicio"))
            flash("Login ou senha incorretos.", "erro")
        return render_template("login.html")

    @app.route("/cadastro", methods=["GET", "POST"])
    def cadastro():
        """Criação de conta pelo próprio paciente. Ele informa seus dados e o CPF; se a clínica já
        tiver um cadastro com esse CPF, a conta é ligada a ele (desde que a data de nascimento
        confira), senão o cadastro do paciente é criado junto com a conta."""
        if g.usuario:
            return redirect(url_for("inicio"))
        if request.method == "POST":
            db = get_db()
            login_ = form_str("login")
            senha, confirmacao = request.form.get("senha", ""), request.form.get("confirmacao", "")
            p = Paciente(None, form_str("nome"), somente_digitos(form_str("cpf")),
                         form_str("data_nascimento"), form_str("telefone"), form_str("email"),
                         form_str("endereco"))
            erros = p.validar() + Usuario.validar_cadastro(p.nome, login_, senha, confirmacao)
            if not erros and login_existe(login_):
                erros.append(MSG_LOGIN_EM_USO)
            existente = None
            if not erros:
                existente = db.execute("SELECT * FROM paciente WHERE cpf = ?", (p.cpf,)).fetchone()
                if existente and db.execute("SELECT 1 FROM usuario WHERE paciente_id = ?",
                                            (existente["id"],)).fetchone():
                    erros.append("Já existe uma conta para este CPF. Entre com o seu login ou "
                                 "procure a recepção.")
                elif existente and existente["data_nascimento"] != p.data_nascimento:
                    # impede que alguém que só saiba o CPF de outra pessoa veja as consultas dela
                    erros.append("O CPF já está cadastrado na clínica com outra data de nascimento. "
                                 "Confira os dados ou procure a recepção.")
            if not erros:
                try:
                    if existente:
                        paciente_id = existente["id"]
                    else:
                        paciente_id = db.execute(
                            "INSERT INTO paciente (nome, cpf, data_nascimento, telefone, email, endereco) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (p.nome, p.cpf, p.data_nascimento, p.telefone, p.email, p.endereco)).lastrowid
                    cur = db.execute("INSERT INTO usuario (nome, login, senha_hash, perfil, paciente_id) "
                                     "VALUES (?, ?, ?, 'paciente', ?)",
                                     (existente["nome"] if existente else p.nome, login_,
                                      generate_password_hash(senha), paciente_id))
                    db.commit()
                    session.clear()
                    session["usuario_id"] = cur.lastrowid
                    flash("Conta criada com sucesso. Bem-vindo(a)!" if not existente else
                          "Conta criada e ligada ao seu cadastro na clínica. Bem-vindo(a)!", "ok")
                    return redirect(url_for("area_consultas"))
                except sqlite3.IntegrityError:
                    db.rollback()
                    erros.append(MSG_LOGIN_EM_USO)
            for e in erros:
                flash(e, "erro")
        return render_template("cadastro.html")

    @app.route("/esqueci-senha", methods=["GET", "POST"])
    def esqueci_senha():
        """Tela SIMULADA de recuperação de senha: o projeto não tem servidor de e-mail, então nada
        é enviado de verdade. A tela só confirma o pedido, sempre com a mesma mensagem, para não
        revelar quais logins ou e-mails estão cadastrados."""
        if g.usuario:
            return redirect(url_for("inicio"))
        return render_template("esqueci_senha.html", enviado=request.method == "POST")

    @app.route("/cadastro/verificar-login")
    def verificar_login():
        """Usado pela tela de cadastro para avisar, enquanto a pessoa digita,
        se o login escolhido é válido e se já pertence a outro usuário."""
        login_ = request.args.get("login", "").strip()
        if not Usuario.login_valido(login_):
            return jsonify(disponivel=False, mensagem=MSG_LOGIN_FORMATO)
        if login_existe(login_):
            return jsonify(disponivel=False, mensagem=MSG_LOGIN_EM_USO)
        return jsonify(disponivel=True, mensagem="Login disponível.")

    @app.route("/conta", methods=["GET", "POST"])
    @login_required
    def conta():
        """Minha conta: o próprio usuário troca a senha informando a atual."""
        if request.method == "POST":
            db = get_db()
            hash_atual = db.execute("SELECT senha_hash FROM usuario WHERE id = ?",
                                    (g.usuario.id,)).fetchone()[0]
            nova = request.form.get("nova_senha", "")
            erros = []
            if not check_password_hash(hash_atual, request.form.get("senha_atual", "")):
                erros.append("A senha atual está incorreta.")
            erros += Usuario.validar_nova_senha(nova, request.form.get("confirmacao", ""))
            if not erros and check_password_hash(hash_atual, nova):
                erros.append("A nova senha precisa ser diferente da atual.")
            if not erros:
                db.execute("UPDATE usuario SET senha_hash = ? WHERE id = ?",
                           (generate_password_hash(nova), g.usuario.id))
                db.commit()
                flash("Senha alterada com sucesso.", "ok")
                return redirect(url_for("conta"))
            for e in erros:
                flash(e, "erro")
        return render_template("conta.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def inicio():
        if g.usuario.is_paciente():
            return redirect(url_for("area_consultas"))
        db = get_db()
        hoje = date.today().isoformat()
        consultas = db.execute(SQL_CONSULTAS + " WHERE date(c.data_hora) = ? "
                               "ORDER BY c.data_hora", (hoje,)).fetchall()
        totais = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("paciente", "profissional", "consulta")}
        return render_template("inicio.html", consultas=consultas, totais=totais)

    # ------------------------------------------------- UC02 Manter pacientes --
    @app.route("/pacientes")
    @equipe_required
    def pacientes():
        busca = request.args.get("q", "").strip()
        sql, params = "SELECT * FROM paciente", ()
        if busca:
            sql += " WHERE normalizar(nome) LIKE ? OR cpf LIKE ?"
            params = (f"%{normalizar(busca)}%", f"%{somente_digitos(busca) or busca}%")
        rows, pag = paginar(sql, params, "ORDER BY nome")
        return render_template("pacientes/lista.html", pacientes=rows, busca=busca, pag=pag)

    @app.route("/pacientes/novo", methods=["GET", "POST"])
    @app.route("/pacientes/<int:id>/editar", methods=["GET", "POST"])
    @equipe_required
    def paciente_form(id=None):
        db = get_db()
        row = None
        if id:
            row = db.execute("SELECT * FROM paciente WHERE id = ?", (id,)).fetchone() or abort(404)
        if request.method == "POST":
            p = Paciente(id, form_str("nome"), somente_digitos(form_str("cpf")),
                         form_str("data_nascimento"), form_str("telefone"),
                         form_str("email"), form_str("endereco"))
            erros = p.validar()
            if not erros:
                try:
                    if id:
                        db.execute("UPDATE paciente SET nome=?, cpf=?, data_nascimento=?, "
                                   "telefone=?, email=?, endereco=? WHERE id=?",
                                   (p.nome, p.cpf, p.data_nascimento, p.telefone,
                                    p.email, p.endereco, id))
                    else:
                        db.execute("INSERT INTO paciente (nome, cpf, data_nascimento, "
                                   "telefone, email, endereco) VALUES (?, ?, ?, ?, ?, ?)",
                                   (p.nome, p.cpf, p.data_nascimento, p.telefone,
                                    p.email, p.endereco))
                    db.commit()
                    flash("Paciente salvo com sucesso.", "ok")
                    return redirect(url_for("pacientes"))
                except sqlite3.IntegrityError:
                    erros.append("Já existe um paciente com este CPF.")
            for e in erros:
                flash(e, "erro")
            row = request.form
        return render_template("pacientes/form.html", p=row, id=id)

    @app.route("/pacientes/<int:id>/excluir", methods=["POST"])
    @equipe_required
    def paciente_excluir(id):
        if get_db().execute("SELECT 1 FROM usuario WHERE paciente_id = ?", (id,)).fetchone():
            flash("Este paciente tem conta de acesso ao sistema. Exclua a conta em Usuários antes.", "erro")
        else:
            excluir_registro("paciente", id, "Paciente possui consultas e não pode ser excluído.")
        return redirect(url_for("pacientes"))

    # --------------------------------------------- UC03 Manter profissionais --
    @app.route("/profissionais")
    @equipe_required
    def profissionais():
        rows = get_db().execute(
            "SELECT p.*, e.nome AS especialidade FROM profissional p "
            "JOIN especialidade e ON e.id = p.especialidade_id ORDER BY p.nome").fetchall()
        return render_template("profissionais/lista.html", profissionais=rows)

    @app.route("/profissionais/novo", methods=["GET", "POST"])
    @app.route("/profissionais/<int:id>/editar", methods=["GET", "POST"])
    @admin_required
    def profissional_form(id=None):
        db = get_db()
        row = None
        if id:
            row = db.execute("SELECT * FROM profissional WHERE id = ?", (id,)).fetchone() or abort(404)
        if request.method == "POST":
            p = Profissional(id, form_str("nome"), form_str("registro"),
                             form_int("especialidade_id"), form_str("telefone"),
                             form_str("email"), request.form.get("ativo") == "1")
            erros = p.validar()
            if p.especialidade_id and not db.execute("SELECT 1 FROM especialidade WHERE id = ?",
                                                     (p.especialidade_id,)).fetchone():
                erros.append("Especialidade não encontrada.")
            if not erros and db.execute("SELECT 1 FROM profissional WHERE normalizar(replace(registro, ' ', '')) "
                                        "= normalizar(replace(?, ' ', '')) AND id IS NOT ?",
                                        (p.registro, id)).fetchone():
                erros.append("Já existe um profissional com este registro.")
            if not erros:
                try:
                    dados = (p.nome, p.registro, p.telefone, p.email, int(p.ativo),
                             p.especialidade_id)
                    if id:
                        db.execute("UPDATE profissional SET nome=?, registro=?, telefone=?, "
                                   "email=?, ativo=?, especialidade_id=? WHERE id=?", dados + (id,))
                    else:
                        db.execute("INSERT INTO profissional (nome, registro, telefone, email, "
                                   "ativo, especialidade_id) VALUES (?, ?, ?, ?, ?, ?)", dados)
                    db.commit()
                    flash("Profissional salvo com sucesso.", "ok")
                    return redirect(url_for("profissionais"))
                except sqlite3.IntegrityError:
                    erros.append("Já existe um profissional com este registro.")
            for e in erros:
                flash(e, "erro")
            row = request.form
        especialidades = db.execute("SELECT * FROM especialidade ORDER BY nome").fetchall()
        return render_template("profissionais/form.html", p=row, id=id,
                               especialidades=especialidades)

    @app.route("/profissionais/<int:id>/excluir", methods=["POST"])
    @admin_required
    def profissional_excluir(id):
        excluir_registro("profissional", id,
                         "Profissional possui consultas. Marque-o como inativo em vez de excluir.")
        return redirect(url_for("profissionais"))

    # -------------------------------------------- UC04 Manter especialidades --
    @app.route("/especialidades")
    @admin_required
    def especialidades():
        rows = get_db().execute(
            "SELECT e.*, COUNT(p.id) AS qtd FROM especialidade e "
            "LEFT JOIN profissional p ON p.especialidade_id = e.id "
            "GROUP BY e.id ORDER BY e.nome").fetchall()
        return render_template("especialidades/lista.html", especialidades=rows)

    @app.route("/especialidades/nova", methods=["GET", "POST"])
    @app.route("/especialidades/<int:id>/editar", methods=["GET", "POST"])
    @admin_required
    def especialidade_form(id=None):
        db = get_db()
        row = None
        if id:
            row = db.execute("SELECT * FROM especialidade WHERE id = ?", (id,)).fetchone() or abort(404)
        if request.method == "POST":
            e = Especialidade(id, form_str("nome"), form_str("descricao"))
            erros = e.validar()
            if not erros and db.execute("SELECT 1 FROM especialidade WHERE normalizar(nome) = normalizar(?) "
                                        "AND id IS NOT ?", (e.nome, id)).fetchone():
                erros.append("Já existe uma especialidade com este nome.")
            if not erros:
                try:
                    if id:
                        db.execute("UPDATE especialidade SET nome=?, descricao=? WHERE id=?",
                                   (e.nome, e.descricao, id))
                    else:
                        db.execute("INSERT INTO especialidade (nome, descricao) VALUES (?, ?)",
                                   (e.nome, e.descricao))
                    db.commit()
                    flash("Especialidade salva com sucesso.", "ok")
                    return redirect(url_for("especialidades"))
                except sqlite3.IntegrityError:
                    erros.append("Já existe uma especialidade com este nome.")
            for msg in erros:
                flash(msg, "erro")
            row = request.form
        return render_template("especialidades/form.html", e=row, id=id)

    @app.route("/especialidades/<int:id>/excluir", methods=["POST"])
    @admin_required
    def especialidade_excluir(id):
        excluir_registro("especialidade", id,
                         "Há profissionais nesta especialidade; ela não pode ser excluída.")
        return redirect(url_for("especialidades"))

    # ------------------------------------------------ UC05 Agendar consultas --
    @app.route("/consultas")
    @equipe_required
    def consultas():
        filtros, params = [], []
        data = request.args.get("data", "")
        prof = request.args.get("profissional", "")
        status = request.args.get("status", "")
        if data:
            filtros.append("date(c.data_hora) = ?"); params.append(data)
        if prof.isdigit():
            filtros.append("c.profissional_id = ?"); params.append(int(prof))
        if status:
            filtros.append("c.status = ?"); params.append(status)
        where = (" WHERE " + " AND ".join(filtros)) if filtros else ""
        db = get_db()
        rows, pag = paginar(SQL_CONSULTAS + where, params, "ORDER BY c.data_hora DESC")
        profs = db.execute("SELECT id, nome FROM profissional ORDER BY nome").fetchall()
        return render_template("consultas/lista.html", consultas=rows, profissionais=profs, pag=pag,
                               filtro={"data": data, "profissional": prof, "status": status})

    @app.route("/consultas/nova", methods=["GET", "POST"])
    @app.route("/consultas/<int:id>/editar", methods=["GET", "POST"])
    @equipe_required
    def consulta_form(id=None):
        db = get_db()
        row = None
        if id:
            row = db.execute("SELECT * FROM consulta WHERE id = ?", (id,)).fetchone() or abort(404)
        if request.method == "POST":
            bruto = form_str("duracao_min")
            duracao = None if bruto == "" else (int(bruto) if bruto.isdigit() else -1)
            # a tela manda o dia e a hora em campos separados; data_hora inteiro também é aceito
            data_hora = form_str("data_hora") or (
                f'{form_str("data")}T{form_str("hora")}' if form_str("data") and form_str("hora") else "")
            c = Consulta(id, form_int("paciente_id"), form_int("profissional_id"),
                         data_hora, duracao if duracao is not None else 30,
                         form_str("status") or "agendada", form_str("observacoes"),
                         g.usuario.id)
            mudou_horario = (not id or row["data_hora"] != c.data_hora
                             or row["profissional_id"] != c.profissional_id
                             or (row["status"] != "agendada" and c.status == "agendada"))
            prof_atual = row["profissional_id"] if id else None
            erros = validar_agendamento(c, mudou_horario, prof_atual)
            if not erros:
                dados = (c.paciente_id, c.profissional_id, c.data_hora, c.duracao_min,
                         c.status, c.observacoes)
                if id:
                    db.execute("UPDATE consulta SET paciente_id=?, profissional_id=?, data_hora=?, "
                               "duracao_min=?, status=?, observacoes=? WHERE id=?", dados + (id,))
                else:
                    db.execute("INSERT INTO consulta (paciente_id, profissional_id, data_hora, "
                               "duracao_min, status, observacoes, usuario_id) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?)", dados + (c.usuario_id,))
                db.commit()
                flash("Consulta salva com sucesso.", "ok")
                return redirect(url_for("consultas"))
            for e in erros:
                flash(e, "erro")
            row = request.form
        pacs = db.execute("SELECT id, nome, cpf FROM paciente ORDER BY nome").fetchall()
        atual = id and db.execute("SELECT profissional_id FROM consulta WHERE id = ?",
                                  (id,)).fetchone()[0]
        profs = db.execute("SELECT p.id, p.nome, p.ativo, e.nome AS especialidade FROM profissional p "
                           "JOIN especialidade e ON e.id = p.especialidade_id "
                           "WHERE p.ativo = 1 OR p.id = ? ORDER BY p.nome", (atual or 0,)).fetchall()
        # valores da tela: do banco (edição), da escolha feita em "Ver horários" (GET) ou do
        # formulário que voltou com erro (POST)
        v = {"paciente_id": "", "profissional_id": "", "data": "", "hora": "", "duracao_min": "30",
             "status": "agendada", "observacoes": ""}
        banco = get_db().execute("SELECT * FROM consulta WHERE id = ?", (id,)).fetchone() if id else None
        if banco:
            dia_b, _, hora_b = banco["data_hora"].partition("T")
            v.update({k: str(banco[k] if banco[k] is not None else "")
                      for k in ("paciente_id", "profissional_id", "duracao_min", "status", "observacoes")},
                     data=dia_b, hora=hora_b)
        fonte = request.form if request.method == "POST" else request.args
        for k in v:
            if k in fonte:
                v[k] = fonte.get(k, "").strip()
        horarios = aviso = None
        if v["profissional_id"].isdigit() and v["data"]:
            dur = int(v["duracao_min"]) if v["duracao_min"].isdigit() else 0
            horarios, aviso = horarios_do_dia(
                int(v["profissional_id"]), v["data"],
                int(v["paciente_id"]) if v["paciente_id"].isdigit() else None,
                duracao=dur, passo=PASSO_RECEPCAO, consulta_atual=banco, do_paciente=False,
                checar_atual=bool(banco) and banco["status"] != "agendada" and v["status"] == "agendada")
        return render_template("consultas/form.html", v=v, id=id, pacientes=pacs,
                               profissionais=profs, horarios=horarios, aviso=aviso,
                               limite=(date.today() + timedelta(days=LIMITE_DIAS)).isoformat())

    @app.route("/consultas/<int:id>/cancelar", methods=["POST"])
    @equipe_required
    def consulta_cancelar(id):
        db = get_db()
        if db.execute("UPDATE consulta SET status = 'cancelada' "
                      "WHERE id = ? AND status = 'agendada'", (id,)).rowcount:
            db.commit()
            flash("Consulta cancelada.", "ok")
        else:
            flash("Só é possível cancelar consultas que ainda estão agendadas.", "erro")
        return redirect(url_for("consultas"))

    @app.route("/consultas/<int:id>/realizar", methods=["POST"])
    @equipe_required
    def consulta_realizar(id):
        """Atalho da lista: marca como realizada uma consulta agendada cujo horário já chegou."""
        db = get_db()
        agora = datetime.now().strftime("%Y-%m-%dT%H:%M")
        if db.execute("UPDATE consulta SET status = 'realizada' WHERE id = ? "
                      "AND status = 'agendada' AND data_hora <= ?", (id, agora)).rowcount:
            db.commit()
            flash("Consulta marcada como realizada.", "ok")
        else:
            flash("Só é possível marcar como realizada uma consulta agendada cujo horário "
                  "já começou.", "erro")
        return redirect(request.referrer if (request.referrer or "").startswith(request.host_url)
                        else url_for("consultas"))

    @app.route("/consultas/<int:id>/excluir", methods=["POST"])
    @admin_required
    def consulta_excluir(id):
        excluir_registro("consulta", id, "")
        return redirect(url_for("consultas"))

    # ---------------------------------------------- UC06 Área do paciente --
    @app.route("/minha-area")
    @paciente_required
    def area_consultas():
        """O paciente vê somente as próprias consultas."""
        rows, pag = paginar(SQL_CONSULTAS + " WHERE c.paciente_id = ?", (g.usuario.paciente_id,),
                            "ORDER BY c.data_hora DESC")
        return render_template("area/consultas.html", consultas=rows, pag=pag)

    @app.route("/minha-area/agendar", methods=["GET", "POST"])
    @paciente_required
    def area_agendar():
        """O paciente escolhe o profissional e o dia e vê a grade de horários (de 30 em 30 minutos)
        com os ocupados marcados; só os livres podem ser escolhidos. Ao salvar, as regras são
        conferidas de novo, porque outra pessoa pode ter marcado o mesmo horário nesse meio tempo."""
        fonte = request.form if request.method == "POST" else request.args
        prof_id = form_int("profissional_id") if request.method == "POST" else (
            int(fonte.get("profissional_id")) if (fonte.get("profissional_id") or "").isdigit() else None)
        dia = (fonte.get("data") or "").strip()
        if request.method == "POST":
            c = Consulta(None, g.usuario.paciente_id, prof_id, form_str("data_hora"), 30,
                         "agendada", form_str("observacoes"), g.usuario.id)
            erros = validar_agendamento(c, nova=True)
            if not erros:
                db = get_db()
                db.execute("INSERT INTO consulta (paciente_id, profissional_id, data_hora, duracao_min, "
                           "status, observacoes, usuario_id) VALUES (?, ?, ?, ?, 'agendada', ?, ?)",
                           (c.paciente_id, c.profissional_id, c.data_hora, c.duracao_min,
                            c.observacoes, c.usuario_id))
                db.commit()
                flash("Consulta agendada com sucesso.", "ok")
                return redirect(url_for("area_consultas"))
            for e in erros:
                flash(e, "erro")
            dia = dia or form_str("data_hora")[:10]
        horarios, aviso = (horarios_do_dia(prof_id, dia, g.usuario.paciente_id)
                           if prof_id and dia else (None, None))
        return render_template("area/agendar.html", profissionais=profissionais_ativos(),
                               prof_id=prof_id, dia=dia, horarios=horarios, aviso=aviso,
                               hoje=date.today().isoformat(),
                               limite=(date.today() + timedelta(days=LIMITE_DIAS)).isoformat(),
                               observacoes=request.form.get("observacoes", ""))

    @app.route("/minha-area/consultas/<int:id>/cancelar", methods=["POST"])
    @paciente_required
    def area_cancelar(id):
        """O paciente só cancela as próprias consultas, agendadas e que ainda não começaram."""
        db = get_db()
        agora = datetime.now().strftime("%Y-%m-%dT%H:%M")
        if db.execute("UPDATE consulta SET status = 'cancelada' WHERE id = ? AND paciente_id = ? "
                      "AND status = 'agendada' AND data_hora > ?",
                      (id, g.usuario.paciente_id, agora)).rowcount:
            db.commit()
            flash("Consulta cancelada.", "ok")
        else:
            flash("Só é possível cancelar as suas consultas agendadas que ainda não começaram.", "erro")
        return redirect(url_for("area_consultas"))

    @app.route("/minha-area/dados", methods=["GET", "POST"])
    @paciente_required
    def area_dados():
        """O paciente atualiza telefone, e-mail e endereço. Nome, CPF e nascimento só a recepção muda."""
        db = get_db()
        atual = db.execute("SELECT * FROM paciente WHERE id = ?", (g.usuario.paciente_id,)).fetchone()
        dados = atual
        if request.method == "POST":
            p = Paciente(atual["id"], atual["nome"], atual["cpf"], atual["data_nascimento"],
                         form_str("telefone"), form_str("email"), form_str("endereco"))
            erros = p.validar()
            if not erros:
                db.execute("UPDATE paciente SET telefone = ?, email = ?, endereco = ? WHERE id = ?",
                           (p.telefone, p.email, p.endereco, p.id))
                db.commit()
                flash("Dados atualizados.", "ok")
                return redirect(url_for("area_dados"))
            for e in erros:
                flash(e, "erro")
            dados = dict(atual, telefone=p.telefone, email=p.email, endereco=p.endereco)
        return render_template("area/dados.html", p=dados)

    # ---------------------------------------------- UC07 Manter usuários --
    @app.route("/usuarios")
    @admin_required
    def usuarios():
        rows, pag = paginar("SELECT u.*, pa.cpf FROM usuario u LEFT JOIN paciente pa ON pa.id = u.paciente_id",
                            (), "ORDER BY u.perfil, u.nome")
        return render_template("usuarios/lista.html", usuarios=rows, pag=pag)

    @app.route("/usuarios/novo", methods=["GET", "POST"])
    @admin_required
    def usuario_novo():
        """O administrador cria as contas de Recepção (pacientes se cadastram sozinhos)."""
        if request.method == "POST":
            nome, login_ = form_str("nome"), form_str("login")
            senha, confirmacao = request.form.get("senha", ""), request.form.get("confirmacao", "")
            erros = Usuario.validar_cadastro(nome, login_, senha, confirmacao)
            if not erros and login_existe(login_):
                erros.append(MSG_LOGIN_EM_USO)
            if not erros:
                db = get_db()
                db.execute("INSERT INTO usuario (nome, login, senha_hash, perfil) VALUES (?, ?, ?, 'recepcao')",
                           (nome, login_, generate_password_hash(senha)))
                db.commit()
                flash("Conta de Recepção criada.", "ok")
                return redirect(url_for("usuarios"))
            for e in erros:
                flash(e, "erro")
        return render_template("usuarios/form.html")

    @app.route("/usuarios/<int:id>/excluir", methods=["POST"])
    @admin_required
    def usuario_excluir(id):
        db = get_db()
        alvo = db.execute("SELECT perfil FROM usuario WHERE id = ?", (id,)).fetchone() or abort(404)
        if id == g.usuario.id:
            flash("Você não pode excluir a sua própria conta.", "erro")
        elif alvo["perfil"] == "admin":
            flash("Contas de administrador não podem ser excluídas por esta tela.", "erro")
        else:
            excluir_registro("usuario", id, "Este usuário registrou consultas e não pode ser excluído.")
        return redirect(url_for("usuarios"))


MSG_LOGIN_EM_USO = "Esse login já pertence a outro usuário. Escolha outro."
MSG_LOGIN_FORMATO = "O login deve ter de 3 a 30 caracteres, sem espaços, usando letras, números, ponto ou _."

SQL_CONSULTAS = (
    "SELECT c.*, pa.nome AS paciente, pr.nome AS profissional, e.nome AS especialidade "
    "FROM consulta c "
    "JOIN paciente pa ON pa.id = c.paciente_id "
    "JOIN profissional pr ON pr.id = c.profissional_id "
    "JOIN especialidade e ON e.id = pr.especialidade_id"
)


POR_PAGINA = 50


def paginar(sql: str, params, ordem: str):
    """Divide uma listagem em páginas de POR_PAGINA itens (RNF09: listas leves mesmo com
    milhares de registros). Lê o número da página de ?pagina= e devolve os itens e os dados
    usados pelo template _paginacao.html."""
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
    paginas = max(1, -(-total // POR_PAGINA))          # arredonda para cima
    pagina = request.args.get("pagina", "1")
    pagina = min(max(int(pagina) if pagina.isdigit() else 1, 1), paginas)
    itens = db.execute(f"{sql} {ordem} LIMIT ? OFFSET ?",
                       list(params) + [POR_PAGINA, (pagina - 1) * POR_PAGINA]).fetchall()
    args = {k: v for k, v in request.args.items() if k != "pagina"}
    return itens, {"pagina": pagina, "paginas": paginas, "total": total, "args": args,
                   "inicio": (pagina - 1) * POR_PAGINA + 1 if total else 0,
                   "fim": min(pagina * POR_PAGINA, total)}


def login_existe(login_: str) -> bool:
    """O login é exato: só conta como repetido se for idêntico, letra por letra.
    "João", "joao" e "JOAO" são logins diferentes."""
    return get_db().execute("SELECT 1 FROM usuario WHERE login = ?",
                            (login_,)).fetchone() is not None


def validar_agendamento(c: Consulta, nova: bool, profissional_atual=None) -> list:
    """Regras de uma consulta, usadas tanto pela recepção quanto pelo próprio paciente:
    campos (RN02, RN03, RN08), paciente e profissional existentes, profissional ativo (RN05)
    e conflito de horário do profissional e do paciente (RN04)."""
    db = get_db()
    erros = c.validar(nova=nova)
    try:
        if nova and c.inicio.date() > date.today() + timedelta(days=LIMITE_DIAS):
            erros.append("A consulta pode ser marcada com no máximo 2 anos de antecedência.")
    except ValueError:
        pass
    if c.paciente_id and not db.execute("SELECT 1 FROM paciente WHERE id = ?",
                                        (c.paciente_id,)).fetchone():
        erros.append("Paciente não encontrado.")
    if c.profissional_id:
        prof = db.execute("SELECT ativo FROM profissional WHERE id = ?", (c.profissional_id,)).fetchone()
        if not prof:
            erros.append("Profissional não encontrado.")
        elif not prof["ativo"] and profissional_atual != c.profissional_id:
            erros.append("Este profissional está inativo e não pode receber novas consultas.")
    if not erros and c.status == "agendada":
        conflito = buscar_conflito(c, "profissional_id")
        if conflito:
            erros.append(f"O profissional já tem consulta às "
                         f"{conflito.inicio:%H:%M} nesse dia (até {conflito.fim:%H:%M}).")
        conflito = buscar_conflito(c, "paciente_id")
        if conflito:
            erros.append(f"O paciente já tem outra consulta às "
                         f"{conflito.inicio:%H:%M} nesse dia (até {conflito.fim:%H:%M}).")
    return erros


LIMITE_DIAS = 730       # consultas novas podem ser marcadas com até 2 anos de antecedência
DURACAO_PACIENTE = 30   # consultas marcadas pelo próprio paciente duram 30 minutos


def horarios_do_dia(profissional_id: int, dia: str, paciente_id, duracao: int = None,
                    passo: int = None, consulta_atual=None, do_paciente: bool = True,
                    checar_atual: bool = False):
    """Monta a grade do dia, das 07:00 até o último horário em que a consulta ainda termina
    às 20:00. O paciente vê de 30 em 30 minutos (consultas de 30 min); a recepção vê de 15 em 15
    com a duração que escolheu. Cada horário vem como {"hora", "valor", "livre", "motivo"}: fica
    ocupado se já passou, se o profissional tem consulta agendada que se sobrepõe (inclusive
    consultas mais longas) ou se o paciente já tem consulta nesse horário.
    Na edição, `consulta_atual` (linha do banco) é ignorada nos conflitos e o horário dela
    continua disponível, mesmo que já tenha passado. Com `checar_atual` (consulta cancelada que
    está voltando a ser agendada), esse horário também é conferido contra as outras consultas."""
    duracao = duracao or DURACAO_PACIENTE
    passo = passo or DURACAO_PACIENTE
    try:
        d = date.fromisoformat(dia)
    except ValueError:
        return None, "Data inválida."
    atual_valor = consulta_atual["data_hora"] if consulta_atual else None
    mesmo_dia = bool(atual_valor) and atual_valor.startswith(dia)
    if not mesmo_dia:
        if d < date.today():
            return None, "Escolha uma data a partir de hoje."
        if d > date.today() + timedelta(days=LIMITE_DIAS):
            return None, "A consulta pode ser marcada com no máximo 2 anos de antecedência."
    if not 10 <= duracao <= 240:
        return None, "A duração deve ficar entre 10 e 240 minutos."
    db = get_db()
    ignorar = consulta_atual["id"] if consulta_atual else None
    ocupadas = [Consulta(r["id"], r["paciente_id"], r["profissional_id"], r["data_hora"], r["duracao_min"])
                for r in db.execute("SELECT * FROM consulta WHERE status = 'agendada' AND date(data_hora) = ? "
                                    "AND (profissional_id = ? OR paciente_id = ?) AND id IS NOT ?",
                                    (dia, profissional_id, paciente_id or 0, ignorar))]
    agora = datetime.now()
    fim_expediente = datetime.combine(d, datetime.min.time()).replace(hour=20)
    inicios = []
    t = fim_expediente.replace(hour=7)
    while t + timedelta(minutes=duracao) <= fim_expediente:
        inicios.append(t)
        t += timedelta(minutes=passo)
    if mesmo_dia:                    # horário da consulta que está sendo editada, mesmo fora da grade
        atual = datetime.fromisoformat(atual_valor)
        if atual not in inicios:
            inicios = sorted(inicios + [atual])
    horarios = []
    for inicio in inicios:
        valor = inicio.strftime("%Y-%m-%dT%H:%M")
        teste = Consulta(None, paciente_id, profissional_id, valor, duracao)
        motivo = ""
        if valor == atual_valor and not checar_atual:
            pass                     # horário que a consulta já tem: continua disponível
        elif inicio <= agora and (valor != atual_valor or checar_atual):
            motivo = "Já passou"
        elif teste.fim > fim_expediente:
            motivo = "Passa das 20h"
        else:
            for o in ocupadas:
                if teste.conflita_com(o):
                    if o.profissional_id == profissional_id:
                        motivo = "Ocupado"
                    else:
                        motivo = "Você já tem consulta" if do_paciente else "Paciente ocupado"
                    break
        horarios.append({"hora": inicio.strftime("%H:%M"), "valor": valor, "livre": not motivo,
                         "motivo": motivo, "atual": valor == atual_valor})
    if not any(h["livre"] for h in horarios):
        return horarios, "Não há horários livres nesse dia. Escolha outra data."
    return horarios, None


PASSO_RECEPCAO = 15     # a grade da recepção mostra horários de 15 em 15 minutos


def profissionais_ativos():
    return get_db().execute("SELECT p.id, p.nome, p.ativo, e.nome AS especialidade FROM profissional p "
                            "JOIN especialidade e ON e.id = p.especialidade_id "
                            "WHERE p.ativo = 1 ORDER BY p.nome").fetchall()


def buscar_conflito(nova: Consulta, campo: str):
    """Procura outra consulta agendada no mesmo dia, do mesmo profissional ou do mesmo
    paciente (conforme `campo`), cujo horário se sobreponha ao da nova consulta."""
    assert campo in ("profissional_id", "paciente_id")
    rows = get_db().execute(
        f"SELECT * FROM consulta WHERE {campo} = ? AND status = 'agendada' "
        "AND date(data_hora) = date(?) AND id IS NOT ?",
        (getattr(nova, campo), nova.data_hora, nova.id)).fetchall()
    for r in rows:
        existente = Consulta(r["id"], r["paciente_id"], r["profissional_id"],
                             r["data_hora"], r["duracao_min"], r["status"])
        if nova.conflita_com(existente):
            return existente
    return None


def excluir_registro(tabela, id, msg_bloqueio):
    db = get_db()
    try:
        if db.execute(f"DELETE FROM {tabela} WHERE id = ?", (id,)).rowcount == 0:
            abort(404)
        db.commit()
        flash("Registro excluído.", "ok")
    except sqlite3.IntegrityError:
        db.rollback()
        flash(msg_bloqueio, "erro")


if __name__ == "__main__":
    create_app().run(debug=True)
