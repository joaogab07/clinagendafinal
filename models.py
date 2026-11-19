"""Entidades do sistema (espelham o Diagrama de Classes) e suas regras de validação."""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

STATUS_CONSULTA = ("agendada", "realizada", "cancelada")


def normalizar(texto) -> str:
    """Deixa o texto comparável: sem acentos, minúsculo e sem espaços sobrando.
    Ex.: "  JOSÉ   Antônio " -> "jose antonio". Usada nas buscas e para evitar nomes repetidos."""
    if texto is None:
        return ""
    sem_acento = "".join(ch for ch in unicodedata.normalize("NFKD", str(texto))
                         if not unicodedata.combining(ch))
    return " ".join(sem_acento.casefold().split())


def somente_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def cpf_valido(cpf: str) -> bool:
    """Aceita o CPF quando ele tem exatamente 11 números (com ou sem pontos e traço)."""
    return len(somente_digitos(cpf)) == 11


def telefone_valido(telefone: str) -> bool:
    """DDD + número: 10 dígitos (fixo) ou 11 (celular)."""
    return len(somente_digitos(telefone)) in (10, 11)


def formatar_cpf(cpf: str) -> str:
    n = somente_digitos(cpf)
    return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}" if len(n) == 11 else cpf


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


PERFIS = {"admin": "Administrador", "recepcao": "Recepção", "paciente": "Paciente"}


@dataclass
class Usuario:
    id: Optional[int]
    nome: str
    login: str
    perfil: str  # 'admin', 'recepcao' ou 'paciente'
    paciente_id: Optional[int] = None   # só para o perfil paciente

    def is_admin(self) -> bool:
        return self.perfil == "admin"

    def is_paciente(self) -> bool:
        return self.perfil == "paciente"

    def is_equipe(self) -> bool:
        """Administrador ou Recepção: quem trabalha na clínica."""
        return self.perfil in ("admin", "recepcao")

    @property
    def rotulo_perfil(self) -> str:
        return PERFIS.get(self.perfil, self.perfil)

    @staticmethod
    def login_valido(login: str) -> bool:
        # \w aceita letras com acento (João), números e _
        return re.fullmatch(r"[\w.]{3,30}", login) is not None

    @staticmethod
    def validar_nova_senha(senha: str, confirmacao: str) -> list:
        erros = []
        if len(senha) < 6:
            erros.append("A senha deve ter pelo menos 6 caracteres.")
        if senha != confirmacao:
            erros.append("As senhas não conferem.")
        return erros

    @staticmethod
    def validar_cadastro(nome: str, login: str, senha: str, confirmacao: str) -> list:
        """Regras para criar uma conta nova pela tela de cadastro."""
        erros = []
        if len(nome.strip()) < 3:
            erros.append("Informe seu nome completo.")
        if not Usuario.login_valido(login):
            erros.append("O login deve ter de 3 a 30 caracteres, sem espaços, usando letras, números, ponto ou _.")
        return erros + Usuario.validar_nova_senha(senha, confirmacao)


@dataclass
class Especialidade:
    id: Optional[int]
    nome: str
    descricao: str = ""

    def validar(self) -> list:
        return [] if self.nome.strip() else ["Informe o nome da especialidade."]


@dataclass
class Profissional:
    id: Optional[int]
    nome: str
    registro: str
    especialidade_id: Optional[int]
    telefone: str = ""
    email: str = ""
    ativo: bool = True

    def validar(self) -> list:
        erros = []
        if not self.nome.strip():
            erros.append("Informe o nome do profissional.")
        if not self.registro.strip():
            erros.append("Informe o registro profissional (CRM, CRO...).")
        if not self.especialidade_id:
            erros.append("Selecione a especialidade.")
        if self.telefone and not telefone_valido(self.telefone):
            erros.append("Telefone deve ter DDD e número (10 ou 11 números).")
        if self.email and not EMAIL_RE.match(self.email):
            erros.append("E-mail inválido.")
        return erros


@dataclass
class Paciente:
    id: Optional[int]
    nome: str
    cpf: str
    data_nascimento: str
    telefone: str
    email: str = ""
    endereco: str = ""

    def validar(self) -> list:
        erros = []
        if not self.nome.strip():
            erros.append("Informe o nome do paciente.")
        if not cpf_valido(self.cpf):
            erros.append("O CPF deve ter 11 números.")
        try:
            nasc = date.fromisoformat(self.data_nascimento)
            if nasc > date.today():
                erros.append("A data de nascimento não pode estar no futuro.")
            elif nasc.year < 1900:
                erros.append("Confira a data de nascimento (ano anterior a 1900).")
        except ValueError:
            erros.append("Data de nascimento inválida.")
        if not telefone_valido(self.telefone):
            erros.append("Telefone deve ter DDD e número (10 ou 11 números).")
        if self.email and not EMAIL_RE.match(self.email):
            erros.append("E-mail inválido.")
        return erros


@dataclass
class Consulta:
    id: Optional[int]
    paciente_id: Optional[int]
    profissional_id: Optional[int]
    data_hora: str
    duracao_min: int = 30
    status: str = "agendada"
    observacoes: str = ""
    usuario_id: Optional[int] = None

    @property
    def inicio(self) -> datetime:
        return datetime.fromisoformat(self.data_hora)

    @property
    def fim(self) -> datetime:
        return self.inicio + timedelta(minutes=self.duracao_min)

    def conflita_com(self, outra: "Consulta") -> bool:
        """Dois horários se sobrepõem quando um começa antes de o outro terminar."""
        return self.inicio < outra.fim and outra.inicio < self.fim

    def validar(self, nova: bool = True) -> list:
        erros = []
        if not self.paciente_id:
            erros.append("Selecione o paciente.")
        if not self.profissional_id:
            erros.append("Selecione o profissional.")
        try:
            inicio = self.inicio
            if nova and inicio < datetime.now():
                erros.append("Não é possível agendar no passado.")
            if not 7 <= inicio.hour < 20:
                erros.append("A clínica atende das 07h às 20h.")
            elif 10 <= int(self.duracao_min) <= 240 and self.fim > inicio.replace(hour=20, minute=0):
                erros.append("A consulta precisa terminar até as 20h. Diminua a duração ou "
                             "escolha um horário mais cedo.")
        except ValueError:
            erros.append("Data e hora inválidas.")
        if not 10 <= int(self.duracao_min) <= 240:
            erros.append("A duração deve ficar entre 10 e 240 minutos.")
        if self.status not in STATUS_CONSULTA:
            erros.append("Status inválido.")
        elif self.status == "realizada":
            try:
                if self.inicio > datetime.now():
                    erros.append("Só é possível marcar como realizada uma consulta cujo horário "
                                 "já começou.")
            except ValueError:
                pass
        return erros
