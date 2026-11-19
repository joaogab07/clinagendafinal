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
    dados = {"nome": "Ana Recepção", "login": "ana", "senha": "segredo1", "confirmacao": "segredo1"}
    r = client.post("/cadastro", data=dados, follow_redirects=True)
    texto = r.get_data(as_text=True)
    assert "Conta criada" in texto and "Olá, Ana Recepção" in texto
    client.get("/logout")
    assert "já está em uso" in client.post("/cadastro", data=dados, follow_redirects=True).get_data(as_text=True)
    r = client.post("/cadastro", follow_redirects=True,
                    data=dict(dados, login="ana2", confirmacao="outra"))
    assert "não conferem" in r.get_data(as_text=True)
    # nova conta entra com perfil Recepção (sem acesso à área do admin)
    entrar(client, "ana", "segredo1")
    assert client.get("/especialidades").status_code == 403


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


def test_login_nao_diferencia_maiusculas(client):
    client.post("/cadastro", data={"nome": "Maria Silva", "login": "Maria",
                                   "senha": "123456", "confirmacao": "123456"})
    client.get("/logout")
    assert "Olá, Maria Silva" in entrar(client, "MARIA", "123456").get_data(as_text=True)


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
