# ClinAgenda — Sistema de Agendamento de Consultas

Projeto da disciplina **Projeto de Desenvolvimento de Software I e II** — UniFil.

**Dupla:**
- Joao Gabriel Ferreira Baptista — RA 232072019
- Jorge Maluf Neto — RA 261466541

## Sobre o sistema

O ClinAgenda é uma aplicação web para a recepção de uma clínica organizar pacientes, profissionais, especialidades e a agenda de consultas. O sistema impede que um profissional ou um paciente tenha duas consultas no mesmo horário, não deixa agendar no passado nem fora do expediente e protege registros que ainda estão em uso (por exemplo, um paciente que já tem consultas não pode ser excluído).

Funcionalidades (CRUD completo):

- **Autenticação** com três perfis: Administrador, Recepção e Paciente. Cada perfil só acessa as telas permitidas a ele
- **Criar conta (paciente)**: o paciente se cadastra pela tela de login informando nome, CPF, data de nascimento, telefone, login e senha. Se a clínica já tiver o cadastro daquele CPF e a data de nascimento conferir, a conta é ligada a ele. O sistema avisa, enquanto a pessoa digita, se o login já pertence a outro usuário
- **Área do paciente**: o paciente vê as próprias consultas, agenda uma nova escolhendo o profissional, o dia e um horário livre numa grade de 30 em 30 minutos (os horários já ocupados aparecem riscados com a palavra "Ocupado" e não podem ser escolhidos), cancela as suas que ainda não começaram e atualiza telefone, e-mail e endereço. Ele não acessa nenhuma tela da clínica
- **Usuários** (somente administrador): lista as contas, cria contas de Recepção e exclui contas
- **Minha conta**: qualquer usuário logado troca a própria senha informando a atual
- **Esqueceu a senha?** (simulado): na tela de login, o usuário informa o login ou e-mail e vê a confirmação de que um link foi enviado. Como o projeto não tem servidor de e-mail, nada é enviado de verdade
- **Pacientes**: cadastrar, listar (em páginas de 50), buscar por nome ou CPF, editar e excluir. A busca por nome não diferencia acentos nem maiúsculas ("joao" encontra "João"), e CPF e telefone ganham pontos, traço e parênteses automaticamente durante a digitação
- **Profissionais**: cadastrar, listar, editar, inativar e excluir (somente administrador)
- **Especialidades**: cadastrar, listar, editar e excluir (somente administrador)
- **Consultas**: agendar, listar com filtros (data, profissional, status) em páginas de 50, editar, cancelar, excluir (somente administrador) e **marcar como realizada** com um clique quando o horário da consulta já chegou

Regras de negócio:

- um profissional, ou um paciente, não pode ter duas consultas agendadas no mesmo horário; consultas canceladas liberam o horário
- a consulta precisa começar e terminar dentro do expediente (07h às 20h) e durar de 10 a 240 minutos, com horário de 5 em 5 minutos; os campos de data só aceitam ano com 4 dígitos
- não é possível agendar no passado nem marcar como realizada uma consulta que ainda não começou; só consultas agendadas podem ser canceladas
- profissionais inativos não recebem novas consultas, mas continuam aparecendo nas consultas que já eram deles
- o CPF deve ter 11 números e não pode se repetir; o telefone deve ter DDD e número (10 ou 11 números)
- especialidades e registros profissionais não podem se repetir, nem com acentos, maiúsculas ou espaços diferentes ("Clínica Geral" e "CLINICA GERAL" são a mesma especialidade)
- o login é exato: para entrar, é preciso digitá-lo exatamente como foi cadastrado, e ele só é recusado na criação de conta se já existir um login idêntico ("João" e "joao" são logins diferentes)
- registros em uso não podem ser excluídos (paciente ou profissional com consultas, especialidade com profissionais, paciente com conta de acesso, usuário que registrou consultas)
- cada CPF tem no máximo uma conta de paciente; o administrador não exclui a própria conta nem outras de administrador

## Tecnologias

- Python 3.10 ou mais novo
- Flask 3 (rotas, templates Jinja2, sessões)
- SQLite (banco relacional, acessado com o módulo `sqlite3` e SQL puro)
- HTML5, CSS3 e um pouco de JavaScript (máscaras e aviso de login)
- Pytest (testes automatizados)

## Como executar

```bash
git clone https://github.com/joaogab07/clinagenda.git
cd clinagenda
python -m pip install -r requirements.txt
python app.py
```

Acesse **http://127.0.0.1:5000**. Na primeira execução o banco `clinagenda.db` é criado automaticamente com dois usuários, três especialidades e três profissionais de exemplo. Pacientes e consultas começam vazios.

Usuários de exemplo (o login deve ser digitado em minúsculas, exatamente assim). Para testar o perfil Paciente, use **Criar conta** na tela de login:

- **Administrador:** login `admin`, senha `admin123`
- **Recepção:** login `recepcao`, senha `recepcao123`

Bancos criados por versões anteriores (sem o perfil Paciente) são atualizados automaticamente na primeira execução, sem perder usuários nem consultas.

Para começar com o banco zerado, desligue o sistema (Ctrl + C), apague o arquivo `clinagenda.db` e rode `python app.py` de novo.

Se preferir usar um ambiente virtual (opcional), rode antes da instalação: `python -m venv .venv` e ative com `.venv\Scripts\Activate.ps1` no Windows (PowerShell) ou `source .venv/bin/activate` no Linux/macOS.

## Testes

```bash
python -m pytest
```

São 30 testes automatizados que cobrem o CRUD de todas as entidades, a criação de conta do paciente e a ligação pelo CPF, a área do paciente e a grade de horários livres, a tela de usuários, a atualização de bancos antigos, a troca de senha, a tela de "Esqueceu a senha", o controle de acesso por perfil, as regras de negócio acima, a paginação e a segurança da sessão.

## Segurança

- as senhas são guardadas apenas como hash (`generate_password_hash` do Werkzeug), nunca em texto puro
- todas as consultas SQL usam parâmetros, o que evita injeção de SQL
- os formulários são protegidos por token CSRF
- a chave que assina o cookie de login é gerada aleatoriamente na primeira execução e fica no arquivo `.secret_key`, que não vai para o GitHub (está no `.gitignore`). Também pode ser definida pela variável de ambiente `SECRET_KEY`

## Estrutura

```
clinagenda/
├── app.py              # rotas Flask (controladores) e regras de acesso
├── models.py           # entidades (Paciente, Profissional, Especialidade, Consulta, Usuario) e validações
├── database.py         # conexão SQLite, criação do esquema e dados iniciais
├── schema.sql          # DDL do banco (tabelas, chaves e restrições)
├── requirements.txt    # dependências (Flask e Pytest)
├── templates/          # telas em Jinja2 (login, cadastro, minha conta e o CRUD de cada entidade)
│   ├── area/           # área do paciente (minhas consultas, agendar, meus dados)
│   └── usuarios/       # tela de usuários do administrador
├── static/
│   ├── style.css       # estilos
│   └── mascaras.js     # máscaras de CPF e telefone
└── tests/              # testes automatizados
```

## Banco de dados

Cinco tabelas relacionadas: `usuario`, `especialidade`, `profissional`, `paciente` e `consulta`. A coluna `usuario.paciente_id` liga a conta de um paciente ao cadastro dele (no máximo uma conta por paciente). As chaves estrangeiras usam `ON DELETE RESTRICT`, de modo que o banco recusa excluir uma especialidade com profissionais ou um paciente com consultas. O diagrama entidade-relacionamento e os demais diagramas estão na documentação (PDF).
