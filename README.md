# APIClassroom

<div align="center">

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Status](https://img.shields.io/badge/Status-Conclu%C3%ADdo-brightgreen?style=for-the-badge)

**Integração pessoal com Google Classroom e Google Drive, focada na consulta de disciplinas, materiais, atividades e prazos pelo ChatGPT, com autenticação OAuth e acesso somente de leitura.**

</div>

---

## Sobre o projeto

O **APIClassroom** é um projeto desenvolvido com foco na integração do Google Classroom e do Google Drive com clientes compatíveis com o Model Context Protocol (MCP), como o ChatGPT.

A aplicação permite consultar disciplinas, comunicados, materiais, atividades, prazos e entregas do próprio estudante, além de extrair o texto de PDFs vinculados às disciplinas autorizadas.

O projeto utiliza FastAPI, autenticação OAuth com Auth0 e hospedagem na Vercel. O acesso é restrito à identidade configurada pelo proprietário, com credenciais mantidas fora do código e documentos processados em memória.

## Objetivos

* Integrar **Google Classroom e Google Drive**
* Consultar **atividades, trabalhos e prazos**
* Disponibilizar **ferramentas MCP para o ChatGPT**
* Permitir **leitura e pesquisa de PDFs**
* Aplicar **autenticação e controle de acesso**
* Manter uma integração **somente de leitura**

## Funcionalidades do sistema

| Funcionalidade | Descrição |
| -------------- | --------- |
| Disciplinas | Listagem, busca por nome ou alias e consulta de detalhes |
| Materiais | Consulta de materiais publicados e anexos das disciplinas |
| Comunicados | Leitura dos avisos publicados no Classroom |
| Atividades e trabalhos | Listagem, pesquisa e consulta dos detalhes das atividades |
| Prazos | Filtros por intervalo de datas e conversão para o horário de São Paulo |
| Entregas próprias | Consulta de estado, atraso e nota disponível do próprio estudante |
| Leitura de PDFs | Extração paginada e pesquisa de texto em arquivos vinculados às disciplinas |
| Integração MCP | Disponibilização de 14 ferramentas para clientes autenticados |
| Diagnóstico | Verificação das permissões e da conexão com as APIs do Google |

## Estrutura dos componentes

| Componente | Descrição |
| ---------- | --------- |
| Courses | Consulta de disciplinas, aliases e controle de acesso às turmas |
| Materials | Consulta de materiais, comunicados e vínculos dos arquivos |
| Activities | Consulta de atividades, prazos e entregas próprias |
| Documents | Leitura e pesquisa paginada de PDFs |
| GoogleClient | Comunicação com as APIs e renovação das credenciais Google |
| TokenVerifier e SecurityMiddleware | Validação OAuth, identidade autorizada e limites de acesso |
| MCP Server | Exposição das ferramentas pelo protocolo MCP |

## Conceitos aplicados

```txt
1. APIs REST              — integração com Classroom e Drive
2. Model Context Protocol — ferramentas para clientes como o ChatGPT
3. OAuth 2.0 e JWT        — autenticação e validação de identidade
4. Separação de serviços — organização por responsabilidade
5. Paginação e filtros   — consultas com continuidade e limites
6. Fusos horários        — conversão dos prazos das atividades
7. Processamento de PDFs — extração de texto em memória
8. Testes automatizados  — validação de regras e controles de acesso
9. Integração contínua   — testes e auditoria de dependências no GitHub
```

## Tecnologias

* **Python 3.12+** — linguagem utilizada no projeto
* **FastAPI e Uvicorn** — API HTTP e servidor de aplicação
* **MCP SDK** — implementação do protocolo de ferramentas
* **Google Classroom API e Google Drive API** — consulta dos dados acadêmicos
* **Google Auth e HTTPX** — autenticação Google e comunicação HTTP
* **Auth0, PyJWT e Cryptography** — autenticação OAuth e validação de tokens
* **pypdf** — extração de texto dos PDFs
* **pytest, GitHub Actions e pip-audit** — testes e auditoria de dependências
* **Vercel** — hospedagem da aplicação

Aplicação backend, podendo ser executada localmente ou hospedada na Vercel. O endpoint publicado é [apiclassroom.vercel.app/mcp](https://apiclassroom.vercel.app/mcp), com acesso restrito ao proprietário autorizado.

## Estrutura do projeto

```txt
APIClassroom/
├── .github/
│   └── workflows/
│       └── checks.yml
├── classroom_app/
│   ├── activities.py
│   ├── aliases.json
│   ├── app.py
│   ├── config.py
│   ├── courses.py
│   ├── diagnostics.py
│   ├── documents.py
│   ├── errors.py
│   ├── google.py
│   ├── google_authorization.py
│   ├── materials.py
│   ├── mcp_server.py
│   ├── pdf_worker.py
│   └── security.py
├── scripts/
│   ├── authorize_google.py
│   └── verify_remote.py
├── tests/
│   ├── test_activities.py
│   └── test_business.py
├── .env.example
├── .gitignore
├── .vercelignore
├── api.py
├── main.py
├── pyproject.toml
├── requirements-dev.txt
├── requirements.txt
├── vercel.json
└── README.md
```

## Como usar

### Pré-requisitos

* Python 3.12 ou superior e Git instalados
* Projeto no Google Cloud com as APIs do Classroom e Drive habilitadas
* Cliente OAuth do tipo aplicativo para computador, salvo localmente como `credentials.json`
* Conta Google com acesso às disciplinas e consentimento para os escopos de leitura
* Provedor Auth0 configurado com assinatura RS256, escopo `classroom:read` e audience igual a `PUBLIC_URL/mcp`
* Cliente OAuth compatível com o provedor e identidade do proprietário definida pelo `sub` do token

### Execução

```powershell
# Clone o repositório
git clone https://github.com/jeffsilva03/APIClassroom.git

# Acesse a pasta
cd APIClassroom

# Crie o ambiente virtual
py -3.12 -m venv .venv

# Instale as dependências de execução e desenvolvimento
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Com credentials.json na pasta, autorize sua conta Google
# Substitua o e-mail de exemplo pelo da conta que acessa o Classroom
.\.venv\Scripts\python.exe scripts/authorize_google.py --expected-email "aluno@example.com"

# Configure o endereço local e os valores da sua aplicação Auth0
$env:PUBLIC_URL = "http://127.0.0.1:8000"
$env:MCP_OAUTH_ISSUER = "https://seu-tenant.us.auth0.com/"
$env:MCP_OWNER_SUB = "provider|seu-identificador"
$env:MCP_DIAGNOSTICS = "0"

# Carregue a credencial Google validada, mantida fora do Git
$env:GOOGLE_CLASSROOM_CREDENTIALS = Get-Content .local/google-authorized-activities.json -Raw
$env:GOOGLE_DRIVE_CREDENTIALS = $env:GOOGLE_CLASSROOM_CREDENTIALS

# Execute a aplicação
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Os comandos usam PowerShell no Windows. Substitua os exemplos pelos valores da sua configuração; o identificador `sub` deve corresponder à identidade autorizada no Auth0. O arquivo `.env.example` documenta as variáveis, mas não é carregado automaticamente pela aplicação.

A rota `http://127.0.0.1:8000/health` permite conferir a execução. As consultas exigem um token Bearer válido para a audience configurada e o escopo `classroom:read`. No ChatGPT, configure o endpoint HTTPS `/mcp` da sua implantação e conclua o OAuth; o endereço local serve para desenvolvimento.

As credenciais e os tokens ficam em arquivos ignorados pelo Git ou nas variáveis protegidas da hospedagem. Nenhuma credencial real é necessária para executar os testes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip_audit -r requirements.txt
```

## Exemplos de uso

**Consulta de disciplinas e materiais:**

```txt
Liste minhas disciplinas ativas
Busque a disciplina de Computação em Nuvem
Mostre os materiais publicados nessa disciplina
```

**Consulta de atividades e prazos:**

```txt
Quais atividades têm prazo nesta semana?
Mostre os detalhes de uma atividade da disciplina selecionada
Consulte o estado das minhas entregas e as notas disponíveis
```

**Leitura e pesquisa de PDFs:**

```txt
Liste os PDFs vinculados aos materiais da disciplina
Leia o documento selecionado, continuando as páginas quando necessário
Pesquise um termo no PDF e informe em qual página aparece
```

## Limitações conhecidas

| Limitação | Descrição |
| --------- | --------- |
| Somente leitura | Não cria atividades, envia trabalhos ou altera notas |
| Uso pessoal | A identidade autorizada é definida pelo proprietário; não há gerenciamento de múltiplos usuários |
| Permissões Google | O acesso depende do consentimento, dos escopos concedidos e das políticas institucionais |
| Entregas próprias | A consulta é limitada ao estudante autenticado, sem acesso às entregas de outros alunos |
| Paginação | É necessário seguir os cursores para concluir buscas em todas as páginas e disciplinas |
| PDFs e OCR | Arquivos de até 20 MB; PDFs digitalizados sem camada de texto precisam de OCR externo |
| Limites de resposta | A leitura de PDF retorna até 5 páginas e 18 mil caracteres por chamada, com continuação |
| Data de publicação | A API informa criação e atualização, sem um campo específico de publicação da atividade |
| Disponibilidade | As consultas dependem das APIs do Google e dos limites da hospedagem |

> Essas limitações fazem parte do escopo do projeto. Futuras melhorias podem incluir OCR, novos filtros e mais opções de consulta, preservando o acesso somente de leitura e a proteção das credenciais.

---

<div align="center">

Desenvolvido como aplicação pessoal de integração com Google Classroom, Google Drive e ferramentas MCP.

</div>
