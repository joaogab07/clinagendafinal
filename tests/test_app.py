"""Testes automatizados do CRUD e das regras de negócio.  Executar:  python -m pytest"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app  # noqa: E402
from models import Consulta, cpf_valido  # noqa: E402

CPF_OK = "529.982.247-25"


@pytest.fixture
def client(tmp_path):
    app = create_app({"TESTING": True, "TESTING_SEM_CSRF": True,
                      "DATABASE": str(tmp_path / "teste.db")})
    return app.test_client()


def entrar(client, login="admin", senha="admin123"):
    return client.post("/login", data={"login": login, "senha": senha}, follow_redirects=True)


def amanha(hora="10:00"):
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") + "T" + hora


def conta_paciente(login="ana", senha="segredo1", **extra):
    """Dados do formulário de Criar conta (paciente). CPF e nascimento podem ser trocados."""
    dados = {"nome": "Ana Paciente", "cpf": "111.222.333-44", "data_nascimento": "1995-04-20",
             "telefone": "(43) 98888-7777", "email": "", "login": login,
             "senha": senha, "confirmacao": senha}
    dados.update(extra)
    return dados


def novo_paciente(client, cpf=CPF_OK):
    return client.post("/pacientes/novo", follow_redirects=True, data={
        "nome": "Maria Teste", "cpf": cpf, "data_nascimento": "1990-05-10",
        "telefone": "(43) 99999-1234", "email": "maria@teste.com", "endereco": "Rua A"})


def test_cpf():
    assert cpf_valido(CPF_OK)
    assert cpf_valido("123.456.789-00")      # qualquer CPF com 11 números é aceito
    assert cpf_valido("12345678900")
    assert not cpf_valido("123.456.789")      # faltando números
    assert not cpf_valido("")


def test_cadastro_de_conta(client):
    r = client.post("/cadastro", data=conta_paciente(), follow_redirects=True)
    texto = r.get_data(as_text=True)
    assert "Conta criada" in texto and "Ana Paciente (Paciente)" in texto and "Minhas consultas" in texto
    client.get("/logout")
    # login repetido, senhas diferentes e CPF incompleto
    r = client.post("/cadastro", data=conta_paciente(cpf="555.666.777-88"), follow_redirects=True)
    assert "pertence a outro usuário" in r.get_data(as_text=True)
    r = client.post("/cadastro", follow_redirects=True, data=conta_paciente("ana2", confirmacao="outra"))
    assert "não conferem" in r.get_data(as_text=True)
    r = client.post("/cadastro", follow_redirects=True, data=conta_paciente("ana3", cpf="123"))
    assert "11 números" in r.get_data(as_text=True)
    # a conta criada é de paciente: não entra nas telas da clínica
    entrar(client, "ana", "segredo1")
    for url in ("/", "/pacientes", "/pacientes/novo", "/consultas", "/consultas/nova",
                "/profissionais", "/especialidades", "/usuarios"):
        r = client.get(url)
        assert r.status_code in (302, 403), url
        if r.status_code == 302:
            assert r.headers["Location"].endswith("/minha-area"), url


def test_conflito_de_horario():
    a = Consulta(1, 1, 1, "2030-01-01T10:00", 30)
    assert a.conflita_com(Consulta(2, 2, 1, "2030-01-01T10:15", 30))
    assert not a.conflita_com(Consulta(3, 2, 1, "2030-01-01T10:30", 30))


def test_login_obrigatorio_e_senha_errada(client):
    assert client.get("/pacientes").status_code == 302
    assert "incorretos" in entrar(client, senha="errada").get_data(as_text=True)
    assert "Olá, Administrador" in entrar(client).get_data(as_text=True)


def test_crud_paciente(client):
    entrar(client)
    assert "Maria Teste" in novo_paciente(client).get_data(as_text=True)
    assert "Já existe" in novo_paciente(client).get_data(as_text=True)      # CPF único
    assert "11 números" in novo_paciente(client, "123").get_data(as_text=True)
    assert "Paciente salvo" in novo_paciente(client, "123.456.789-00").get_data(as_text=True)
    r = client.post("/pacientes/1/editar", follow_redirects=True, data={
        "nome": "Maria Alterada", "cpf": CPF_OK, "data_nascimento": "1990-05-10",
        "telefone": "(43) 99999-1234"})
    assert "Maria Alterada" in r.get_data(as_text=True)
    assert "Maria Alterada" in client.get("/pacientes?q=alter").get_data(as_text=True)
    r = client.post("/pacientes/1/excluir", follow_redirects=True)
    assert "Maria Alterada" not in r.get_data(as_text=True)


def test_crud_especialidade_e_profissional(client):
    entrar(client)
    client.post("/especialidades/nova", data={"nome": "Cardiologia", "descricao": "Coração"})
    assert "Cardiologia" in client.get("/especialidades").get_data(as_text=True)
    r = client.post("/profissionais/novo", follow_redirects=True, data={
        "nome": "Dr. Novo", "registro": "CRM-PR 99999", "especialidade_id": "4", "ativo": "1"})
    assert "Dr. Novo" in r.get_data(as_text=True)
    # especialidade com profissional vinculado não pode ser excluída
    r = client.post("/especialidades/4/excluir", follow_redirects=True)
    assert "não pode ser excluída" in r.get_data(as_text=True)
    client.post("/profissionais/4/excluir")
    r = client.post("/especialidades/4/excluir", follow_redirects=True)
    assert "Registro excluído" in r.get_data(as_text=True)


def test_recepcao_nao_acessa_area_admin(client):
    entrar(client, "recepcao", "recepcao123")
    assert client.get("/especialidades").status_code == 403
    assert client.get("/profissionais/novo").status_code == 403
    assert client.get("/profissionais").status_code == 200


def test_crud_consulta_com_regras(client):
    entrar(client)
    novo_paciente(client)
    dados = {"paciente_id": "1", "profissional_id": "1", "data_hora": amanha("10:00"),
             "duracao_min": "30", "observacoes": "Retorno"}
    r = client.post("/consultas/nova", data=dados, follow_redirects=True)
    assert "Consulta salva" in r.get_data(as_text=True)
    # mesmo profissional, horário sobreposto -> bloqueado
    r = client.post("/consultas/nova", follow_redirects=True,
                    data=dict(dados, data_hora=amanha("10:15")))
    assert "já tem consulta" in r.get_data(as_text=True)
    # horário no passado -> bloqueado
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
    r = client.post("/consultas/nova", follow_redirects=True, data=dict(dados, data_hora=ontem))
    assert "passado" in r.get_data(as_text=True)
    # paciente com consulta não pode ser excluído
    r = client.post("/pacientes/1/excluir", follow_redirects=True)
    assert "possui consultas" in r.get_data(as_text=True)
    # cancelar libera o horário
    client.post("/consultas/1/cancelar")
    assert "Cancelada" in client.get("/consultas?status=cancelada").get_data(as_text=True)
    r = client.post("/consultas/nova", follow_redirects=True,
                    data=dict(dados, data_hora=amanha("10:15")))
    assert "Consulta salva" in r.get_data(as_text=True)
    # editar e excluir
    r = client.post("/consultas/2/editar", follow_redirects=True,
                    data=dict(dados, data_hora=amanha("14:00"), status="agendada"))
    assert "Consulta salva" in r.get_data(as_text=True)
    client.post("/consultas/1/excluir")
    assert client.get("/consultas/1/editar").status_code == 404


def test_login_tem_que_ser_digitado_igual(client):
    client.post("/cadastro", data=conta_paciente("João", "123456", nome="João Silva"))
    client.get("/logout")
    for errado in ("joão", "JOÃO", "Joao", "joao"):
        assert "incorretos" in entrar(client, errado, "123456").get_data(as_text=True)
    assert "João Silva (Paciente)" in entrar(client, "João", "123456").get_data(as_text=True)
    client.get("/logout")
    # login só é repetido se for exatamente igual: "joao" e "JOÃO" podem ser outras contas
    assert client.get("/cadastro/verificar-login",
                      query_string={"login": "João"}).get_json()["disponivel"] is False
    r = client.post("/cadastro", follow_redirects=True,
                    data=conta_paciente("João", "123456", nome="Outra Pessoa", cpf="999.888.777-66"))
    assert "pertence a outro usuário" in r.get_data(as_text=True)
    for diferente, cpf in (("joao", "999.888.777-66"), ("JOÃO", "999.888.777-55")):
        assert client.get("/cadastro/verificar-login",
                          query_string={"login": diferente}).get_json()["disponivel"] is True
        r = client.post("/cadastro", follow_redirects=True,
                        data=conta_paciente(diferente, "654321", nome="Outra Pessoa", cpf=cpf))
        assert "Conta criada" in r.get_data(as_text=True)
        client.get("/logout")
    # cada um entra com a sua própria senha
    assert "João Silva (Paciente)" in entrar(client, "João", "123456").get_data(as_text=True)


def test_login_nao_redireciona_para_outro_site(client):
    r = client.post("/login?proximo=//exemplo.com", data={"login": "admin", "senha": "admin123"})
    assert r.headers["Location"] == "/"


def test_regras_extras_de_consulta(client):
    entrar(client)
    novo_paciente(client)
    base = {"paciente_id": "1", "profissional_id": "1", "duracao_min": "30"}
    # precisa terminar até as 20h
    r = client.post("/consultas/nova", follow_redirects=True,
                    data=dict(base, data_hora=amanha("19:45"), duracao_min="60"))
    assert "terminar até as 20h" in r.get_data(as_text=True)
    # mesmo paciente não pode estar em dois atendimentos ao mesmo tempo
    client.post("/consultas/nova", data=dict(base, data_hora=amanha("10:00")))
    r = client.post("/consultas/nova", follow_redirects=True,
                    data=dict(base, profissional_id="2", data_hora=amanha("10:15")))
    assert "paciente já tem outra consulta" in r.get_data(as_text=True)
    # profissional inativado continua aparecendo na consulta que já era dele
    client.post("/profissionais/1/editar", data={"nome": "Dra. Ana Souza", "registro": "CRM-PR 12345",
                                                 "especialidade_id": "1"})
    assert "inativo" in client.get("/consultas/1/editar").get_data(as_text=True)
    assert "inativo" not in client.get("/consultas/nova").get_data(as_text=True)
    # consulta futura não pode ser marcada como realizada
    r = client.post("/consultas/1/editar", follow_redirects=True,
                    data=dict(base, data_hora=amanha("10:00"), status="realizada"))
    assert "Só é possível marcar como realizada" in r.get_data(as_text=True)
    # consulta que já aconteceu pode ser marcada como realizada e, depois, não pode ser cancelada
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
    with client.application.app_context():
        from database import get_db
        db = get_db()
        db.execute("UPDATE consulta SET data_hora = ? WHERE id = 1", (ontem,))
        db.commit()
    r = client.post("/consultas/1/editar", follow_redirects=True,
                    data=dict(base, data_hora=ontem, status="realizada"))
    assert "Consulta salva" in r.get_data(as_text=True)
    r = client.post("/consultas/1/cancelar", follow_redirects=True)
    assert "Só é possível cancelar" in r.get_data(as_text=True)


def test_nascimento_muito_antigo(client):
    entrar(client)
    r = client.post("/pacientes/novo", follow_redirects=True, data={
        "nome": "Teste", "cpf": "98765432100", "data_nascimento": "1800-01-01",
        "telefone": "(43) 99999-0000"})
    assert "anterior a 1900" in r.get_data(as_text=True)


def test_alterar_senha(client):
    entrar(client)
    def trocar(atual, nova, conf):
        return client.post("/conta", follow_redirects=True, data={
            "senha_atual": atual, "nova_senha": nova, "confirmacao": conf}).get_data(as_text=True)
    assert "senha atual está incorreta" in trocar("errada", "nova123", "nova123")
    assert "não conferem" in trocar("admin123", "nova123", "outra12")
    assert "diferente da atual" in trocar("admin123", "admin123", "admin123")
    assert "Senha alterada" in trocar("admin123", "nova123", "nova123")
    client.get("/logout")
    assert "incorretos" in entrar(client, "admin", "admin123").get_data(as_text=True)
    assert "Olá, Administrador" in entrar(client, "admin", "nova123").get_data(as_text=True)


def test_verificar_login_enquanto_digita(client):
    def checar(login):
        return client.get("/cadastro/verificar-login", query_string={"login": login}).get_json()
    assert checar("pedro")["disponivel"] is True
    assert checar("admin") == {"disponivel": False,
                               "mensagem": "Esse login já pertence a outro usuário. Escolha outro."}
    assert checar("ADMIN")["disponivel"] is True           # só bloqueia o login idêntico
    assert checar("ab")["disponivel"] is False          # curto demais
    assert checar("nome com espaço")["disponivel"] is False


def test_chave_secreta_nao_e_a_do_codigo(client):
    chave = client.application.config["SECRET_KEY"]
    assert chave != "troque-esta-chave-em-producao" and len(chave) >= 32


def test_paginas_de_erro_em_portugues(client):
    entrar(client)
    r = client.get("/pacientes/1/excluir")
    assert r.status_code == 405 and "botões do sistema" in r.get_data(as_text=True)


def test_validacoes_finas(client):
    entrar(client)
    novo_paciente(client)
    # duração 0 é recusada (antes virava 30 sem avisar)
    r = client.post("/consultas/nova", follow_redirects=True, data={
        "paciente_id": "1", "profissional_id": "1", "data_hora": amanha("10:00"), "duracao_min": "0"})
    assert "entre 10 e 240" in r.get_data(as_text=True)
    # telefone com números demais
    r = client.post("/pacientes/novo", follow_redirects=True, data={
        "nome": "X", "cpf": "11122233344", "data_nascimento": "1990-01-01", "telefone": "439999912345678"})
    assert "10 ou 11 números" in r.get_data(as_text=True)
    # especialidade e registro repetidos com outra caixa/espaços
    r = client.post("/especialidades/nova", data={"nome": "PEDIATRIA"}, follow_redirects=True)
    assert "Já existe uma especialidade" in r.get_data(as_text=True)
    r = client.post("/profissionais/novo", follow_redirects=True, data={
        "nome": "Outro", "registro": "crm-pr12345", "especialidade_id": "1", "ativo": "1"})
    assert "Já existe um profissional" in r.get_data(as_text=True)
    # editar a própria especialidade sem mudar o nome continua funcionando
    r = client.post("/especialidades/2/editar", data={"nome": "Pediatria", "descricao": "Crianças"},
                    follow_redirects=True)
    assert "Especialidade salva" in r.get_data(as_text=True)


def test_reagendar_cancelada_no_passado(client):
    entrar(client)
    novo_paciente(client)
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
    with client.application.app_context():
        from database import get_db
        db = get_db()
        db.execute("INSERT INTO consulta (paciente_id, profissional_id, usuario_id, data_hora, status) "
                   "VALUES (1, 1, 1, ?, 'cancelada')", (ontem,))
        db.commit()
    r = client.post("/consultas/1/editar", follow_redirects=True, data={
        "paciente_id": "1", "profissional_id": "1", "data_hora": ontem, "duracao_min": "30",
        "status": "agendada"})
    assert "passado" in r.get_data(as_text=True)


def test_botao_marcar_realizada(client):
    entrar(client)
    novo_paciente(client)
    client.post("/consultas/nova", data={"paciente_id": "1", "profissional_id": "1",
                                         "data_hora": amanha("10:00"), "duracao_min": "30"})
    # consulta de amanhã: botão não aparece e o atalho é recusado
    assert "Marcar realizada" not in client.get("/consultas").get_data(as_text=True)
    r = client.post("/consultas/1/realizar", follow_redirects=True)
    assert "Só é possível marcar como realizada" in r.get_data(as_text=True)
    # consulta que já começou: botão aparece e funciona
    passado = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    with client.application.app_context():
        from database import get_db
        db = get_db()
        db.execute("UPDATE consulta SET data_hora = ? WHERE id = 1", (passado,))
        db.commit()
    assert "Marcar realizada" in client.get("/consultas").get_data(as_text=True)
    r = client.post("/consultas/1/realizar", follow_redirects=True)
    texto = r.get_data(as_text=True)
    assert "marcada como realizada" in texto and "Marcar realizada" not in texto


def test_busca_e_nomes_sem_diferenciar_acentos(client):
    entrar(client)
    client.post("/pacientes/novo", data={"nome": "José Antônio", "cpf": "12345678900",
                                         "data_nascimento": "1990-01-01", "telefone": "43999990000"})
    client.post("/pacientes/novo", data={"nome": "JOÃO PEREIRA", "cpf": "22233344455",
                                         "data_nascimento": "1990-01-01", "telefone": "43999990000"})
    assert "José Antônio" in client.get("/pacientes?q=jose antonio").get_data(as_text=True)
    assert "JOÃO PEREIRA" in client.get("/pacientes?q=joão").get_data(as_text=True)
    assert "JOÃO PEREIRA" in client.get("/pacientes?q=Joao").get_data(as_text=True)
    assert "JOÃO PEREIRA" not in client.get("/pacientes?q=jose").get_data(as_text=True)
    for nome in ("CLÍNICA GERAL", "Clinica Geral", "  clínica   geral "):
        r = client.post("/especialidades/nova", data={"nome": nome}, follow_redirects=True)
        assert "Já existe uma especialidade" in r.get_data(as_text=True)


def test_consulta_com_dados_forjados(client):
    """Valores que a tela não deixa escolher, mas alguém pode mandar alterando a página."""
    entrar(client)
    novo_paciente(client)
    base = {"paciente_id": "1", "profissional_id": "1", "data_hora": amanha("10:00"), "duracao_min": "30"}
    def msg(dados):
        return client.post("/consultas/nova", data=dados, follow_redirects=True).get_data(as_text=True)
    assert "Paciente não encontrado" in msg(dict(base, paciente_id="999"))
    assert "Profissional não encontrado" in msg(dict(base, profissional_id="999"))
    assert "entre 10 e 240" in msg(dict(base, duracao_min="abc"))
    client.post("/profissionais/1/editar", data={"nome": "Dra. Ana Souza", "registro": "CRM-PR 12345",
                                                 "especialidade_id": "1"})
    assert "inativo" in msg(base)
    r = client.post("/profissionais/novo", follow_redirects=True, data={
        "nome": "X", "registro": "CRM 1", "especialidade_id": "999", "ativo": "1"})
    assert "Especialidade não encontrada" in r.get_data(as_text=True)


def test_listas_paginadas(client):
    entrar(client)
    with client.application.app_context():
        from database import get_db
        db = get_db()
        db.executemany("INSERT INTO paciente (nome, cpf, data_nascimento, telefone) VALUES (?, ?, ?, ?)",
                       [(f"Paciente {i:03d}", f"{i:011d}", "1990-01-01", "43999990000") for i in range(1, 121)])
        db.commit()
    p1 = client.get("/pacientes").get_data(as_text=True)
    assert "Mostrando 1–50 de 120" in p1 and "Paciente 001" in p1 and "Paciente 051" not in p1
    p3 = client.get("/pacientes?pagina=3").get_data(as_text=True)
    assert "Mostrando 101–120 de 120" in p3 and "Paciente 120" in p3 and "Próxima" not in p3
    # página inválida ou além do fim não quebra
    assert "Mostrando 101–120" in client.get("/pacientes?pagina=99").get_data(as_text=True)
    assert "Mostrando 1–50" in client.get("/pacientes?pagina=abc").get_data(as_text=True)
    # o filtro é mantido nos links de página
    filtrado = client.get("/pacientes?q=paciente&pagina=2").get_data(as_text=True)
    assert "q=paciente" in filtrado and "Mostrando 51–100 de 120" in filtrado



# ------------------------------------------------------- perfil Paciente --
def test_conta_liga_ao_cadastro_existente_pelo_cpf(client):
    entrar(client)
    novo_paciente(client)                       # recepção já cadastrou CPF 529.982.247-25 (Maria Teste)
    client.get("/logout")
    # data de nascimento diferente: não deixa "pegar" o cadastro de outra pessoa
    r = client.post("/cadastro", follow_redirects=True,
                    data=conta_paciente("maria", cpf=CPF_OK, data_nascimento="2000-01-01"))
    assert "outra data de nascimento" in r.get_data(as_text=True)
    # mesmo CPF e mesma data: liga a conta ao cadastro que já existe (sem duplicar)
    r = client.post("/cadastro", follow_redirects=True,
                    data=conta_paciente("maria", cpf=CPF_OK, data_nascimento="1990-05-10"))
    assert "ligada ao seu cadastro" in r.get_data(as_text=True)
    with client.application.app_context():
        from database import get_db
        assert get_db().execute("SELECT COUNT(*) FROM paciente").fetchone()[0] == 1
    client.get("/logout")
    # uma segunda conta para o mesmo CPF não é aceita
    r = client.post("/cadastro", follow_redirects=True,
                    data=conta_paciente("maria2", cpf=CPF_OK, data_nascimento="1990-05-10"))
    assert "Já existe uma conta para este CPF" in r.get_data(as_text=True)


def test_area_do_paciente(client):
    # a recepção agenda uma consulta para outro paciente
    entrar(client)
    novo_paciente(client)
    client.post("/consultas/nova", data={"paciente_id": "1", "profissional_id": "1",
                                         "data_hora": amanha("09:00"), "duracao_min": "30"})
    client.get("/logout")
    # paciente cria conta e agenda a própria consulta
    client.post("/cadastro", data=conta_paciente())
    r = client.post("/minha-area/agendar", follow_redirects=True,
                    data={"profissional_id": "2", "data_hora": amanha("10:00"), "observacoes": "Retorno"})
    texto = r.get_data(as_text=True)
    assert "Consulta agendada" in texto and "Dr. Bruno Lima" in texto
    assert "Maria Teste" not in texto                     # não vê consulta de outro paciente
    # regras valem para o paciente também
    r = client.post("/minha-area/agendar", follow_redirects=True,
                    data={"profissional_id": "1", "data_hora": amanha("09:15")})
    assert "profissional já tem consulta" in r.get_data(as_text=True)
    r = client.post("/minha-area/agendar", follow_redirects=True,
                    data={"profissional_id": "3", "data_hora": amanha("10:15")})
    assert "paciente já tem outra consulta" in r.get_data(as_text=True)
    r = client.post("/minha-area/agendar", follow_redirects=True,
                    data={"profissional_id": "3", "data_hora": amanha("21:00")})
    assert "07h às 20h" in r.get_data(as_text=True)
    # não consegue cancelar a consulta de outro paciente (id 1), só a própria (id 2)
    r = client.post("/minha-area/consultas/1/cancelar", follow_redirects=True)
    assert "Só é possível cancelar as suas" in r.get_data(as_text=True)
    r = client.post("/minha-area/consultas/2/cancelar", follow_redirects=True)
    assert "Consulta cancelada" in r.get_data(as_text=True)
    with client.application.app_context():
        from database import get_db
        status = dict(get_db().execute("SELECT id, status FROM consulta").fetchall())
    assert status == {1: "agendada", 2: "cancelada"}
    # não usa as rotas da recepção para mexer em consultas
    assert client.post("/consultas/1/cancelar").status_code == 403
    assert client.get("/consultas/1/editar").status_code == 403
    # edita só telefone, e-mail e endereço
    r = client.post("/minha-area/dados", follow_redirects=True, data={
        "telefone": "(43) 3333-2222", "email": "ana@exemplo.com", "endereco": "Rua Nova, 10",
        "nome": "Nome Trocado", "cpf": "000.000.000-00"})
    texto = r.get_data(as_text=True)
    assert "Dados atualizados" in texto and "(43) 3333-2222" in texto
    assert "Ana Paciente" in texto and "Nome Trocado" not in texto and "111.222.333-44" in texto
    r = client.post("/minha-area/dados", follow_redirects=True, data={"telefone": "123"})
    assert "10 ou 11 números" in r.get_data(as_text=True)


def test_recepcao_e_admin_nao_usam_area_do_paciente(client):
    entrar(client)
    assert client.get("/minha-area").status_code == 403
    assert client.get("/minha-area/agendar").status_code == 403


def test_usuarios_do_admin(client):
    entrar(client)
    r = client.post("/usuarios/novo", follow_redirects=True, data={
        "nome": "Carla Recepção", "login": "carla", "senha": "123456", "confirmacao": "123456"})
    texto = r.get_data(as_text=True)
    assert "Conta de Recepção criada" in texto and "carla" in texto
    r = client.post("/usuarios/novo", follow_redirects=True, data={
        "nome": "Outra", "login": "carla", "senha": "123456", "confirmacao": "123456"})
    assert "pertence a outro usuário" in r.get_data(as_text=True)
    # a nova recepcionista entra e usa as telas da clínica, mas não a de usuários
    client.get("/logout")
    entrar(client, "carla", "123456")
    assert client.get("/pacientes").status_code == 200
    assert client.get("/usuarios").status_code == 403
    novo_paciente(client)
    client.post("/consultas/nova", data={"paciente_id": "1", "profissional_id": "1",
                                         "data_hora": amanha("10:00"), "duracao_min": "30"})
    client.get("/logout")
    entrar(client)
    with client.application.app_context():
        from database import get_db
        carla = get_db().execute("SELECT id FROM usuario WHERE login = 'carla'").fetchone()[0]
    # registrou consulta: não pode ser excluída; o admin não exclui a si mesmo
    r = client.post(f"/usuarios/{carla}/excluir", follow_redirects=True)
    assert "registrou consultas" in r.get_data(as_text=True)
    r = client.post("/usuarios/1/excluir", follow_redirects=True)
    assert "sua própria conta" in r.get_data(as_text=True)
    # conta de paciente pode ser excluída; o cadastro do paciente continua
    client.get("/logout")
    client.post("/cadastro", data=conta_paciente())
    client.get("/logout")
    entrar(client)
    with client.application.app_context():
        from database import get_db
        db = get_db()
        conta, pac = db.execute("SELECT id, paciente_id FROM usuario WHERE login = 'ana'").fetchone()
    r = client.post(f"/pacientes/{pac}/excluir", follow_redirects=True)
    assert "tem conta de acesso" in r.get_data(as_text=True)
    r = client.post(f"/usuarios/{conta}/excluir", follow_redirects=True)
    assert "Registro excluído" in r.get_data(as_text=True)
    assert "Ana Paciente" in client.get("/pacientes").get_data(as_text=True)


def test_migracao_de_banco_antigo(tmp_path):
    """Banco criado antes do perfil Paciente continua funcionando, com os usuários preservados."""
    import sqlite3
    caminho = tmp_path / "antigo.db"
    db = sqlite3.connect(caminho)
    db.executescript("""
        CREATE TABLE usuario (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
            login TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL,
            perfil TEXT NOT NULL CHECK (perfil IN ('admin', 'recepcao')));
    """)
    from werkzeug.security import generate_password_hash
    db.execute("INSERT INTO usuario (nome, login, senha_hash, perfil) VALUES ('Velho Admin', 'velho', ?, 'admin')",
               (generate_password_hash("abc123"),))
    db.commit(); db.close()
    app = create_app({"TESTING": True, "TESTING_SEM_CSRF": True, "DATABASE": str(caminho)})
    c = app.test_client()
    assert "Olá, Velho Admin" in entrar(c, "velho", "abc123").get_data(as_text=True)
    c.get("/logout")
    r = c.post("/cadastro", data=conta_paciente(), follow_redirects=True)
    assert "Conta criada" in r.get_data(as_text=True)



# ---------------------------------------------------- Esqueceu a senha --
def test_esqueceu_a_senha_simulado(client):
    assert "Esqueceu a senha?" in client.get("/login").get_data(as_text=True)
    assert "Enviar link" in client.get("/esqueci-senha").get_data(as_text=True)
    # a resposta é a mesma, exista ou não o login (não revela quem está cadastrado)
    for login in ("admin", "ninguem"):
        r = client.post("/esqueci-senha", data={"login": login})
        assert "enviamos um link" in r.get_data(as_text=True)
    # a senha não muda: é só uma simulação
    assert "Olá, Administrador" in entrar(client).get_data(as_text=True)



def test_grade_de_horarios_do_paciente(client):
    # a recepção marca o Dr. Bruno (id 2) amanhã das 10:00 às 10:45 para outro paciente
    entrar(client)
    novo_paciente(client)
    client.post("/consultas/nova", data={"paciente_id": "1", "profissional_id": "2",
                                         "data_hora": amanha("10:00"), "duracao_min": "45"})
    client.get("/logout")
    client.post("/cadastro", data=conta_paciente())
    dia = amanha("00:00")[:10]
    h = client.get("/minha-area/agendar", query_string={"profissional_id": "2", "data": dia}).get_data(as_text=True)
    # 10:00 e 10:30 aparecem ocupados (a consulta de 45 min avança sobre 10:30); 11:00 está livre
    assert f'value="{dia}T10:00"' not in h and f'value="{dia}T10:30"' not in h
    assert f'value="{dia}T11:00"' in h and "Ocupado" in h
    # primeiro e último horários do expediente (a última consulta termina às 20:00)
    assert f'value="{dia}T07:00"' in h and f'value="{dia}T19:30"' in h and f'value="{dia}T20:00"' not in h
    # outro profissional no mesmo dia: 10:00 livre
    h3 = client.get("/minha-area/agendar", query_string={"profissional_id": "3", "data": dia}).get_data(as_text=True)
    assert f'value="{dia}T10:00"' in h3
    # agenda um horário livre e ele passa a aparecer como "Você já tem consulta" com outro profissional
    r = client.post("/minha-area/agendar", follow_redirects=True,
                    data={"profissional_id": "3", "data": dia, "data_hora": f"{dia}T11:00"})
    assert "Consulta agendada" in r.get_data(as_text=True)
    h = client.get("/minha-area/agendar", query_string={"profissional_id": "2", "data": dia}).get_data(as_text=True)
    assert f'value="{dia}T11:00"' not in h and "Você já tem consulta" in h
    # mesmo mandando um horário ocupado por fora da tela, o sistema recusa
    r = client.post("/minha-area/agendar", follow_redirects=True,
                    data={"profissional_id": "2", "data": dia, "data_hora": f"{dia}T10:30"})
    assert "profissional já tem consulta" in r.get_data(as_text=True)
    # data passada ou inválida
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert "a partir de hoje" in client.get("/minha-area/agendar", query_string={
        "profissional_id": "2", "data": ontem}).get_data(as_text=True)
    assert "Data inválida" in client.get("/minha-area/agendar", query_string={
        "profissional_id": "2", "data": "abc"}).get_data(as_text=True)
