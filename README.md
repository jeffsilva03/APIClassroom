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

A aplicação permite consultar disciplinas, comunicados, materiais, atividades, prazos e entregas do próprio estudante, além de extrair o texto de PDFs e explorar projetos ZIP vinculados às disciplinas autorizadas.

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
| Integração MCP | Disponibilização de 17 ferramentas para clientes autenticados |
| Diagnóstico | Verificação das permissões e da conexão com as APIs do Google |

## Estrutura dos componentes

| Componente | Descrição |
| ---------- | --------- |
| Courses | Consulta de disciplinas, aliases e controle de acesso às turmas |
| Materials | Consulta de materiais, comunicados e vínculos dos arquivos |
| Activities | Consulta de atividades, prazos e entregas próprias |
| Documents | Inspeção de anexos, leitura de PDF e exploração de ZIP com vínculo validado |
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
│   ├── zip_worker.py
│   ├── pdf_worker.py
│   └── security.py
├── scripts/
│   ├── authorize_google.py
│   ├── verify_bookhub.py
│   └── verify_remote.py
├── tests/
│   ├── test_attachments.py
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


## Anexos: acesso, PDFs e projetos ZIP

As 14 ferramentas anteriores continuam disponíveis; foram adicionadas:

| Ferramenta | Contrato |
| --- | --- |
| `inspecionar_anexo` | `disciplina_id`, `arquivo_id`, `incluir_arquivadas=false`: vínculo, origem, links, nome, MIME, tamanho, leitura disponível e diagnóstico |
| `listar_conteudo_zip` | IDs, `diretorio=null`, `continuacao=null`, `incluir_arquivadas=false`, `nome=null`: até 100 entradas, tamanhos, diretórios explícitos/implícitos, extensões, tipos permitidos, totais e continuação |
| `ler_arquivo_zip` | IDs, `caminho`, `offset=0`, `incluir_arquivadas=false`: texto UTF-8, codificação, caracteres, mascaramento, `truncado`, `proximo_offset` e SHA-256 do ZIP |

`listar_arquivos` reúne todas as páginas de materiais, atividades e avisos publicados, deduplica por ID Drive e mantém todas as `origens`, os `materiais_ids` anteriores e os links. Seus parâmetros e campos anteriores permanecem. Os novos cursores são opacos, vinculados ao conjunto de anexos e à turma; alterações nas publicações exigem reiniciar a listagem. Para obter todas as origens, cada página reconsulta as fontes: turmas muito grandes podem atingir o orçamento de 60 chamadas/45 segundos. Nesse caso, consulte as publicações por suas ferramentas paginadas e inspecione o ID do anexo específico.

O ID aceito é exclusivamente o `materials[].driveFile.driveFile.id` retornado pelo Classroom. Cada leitura verifica novamente a matrícula/estado da turma e o vínculo publicado antes de acessar o Drive. Atalhos são resolvidos somente pelo `shortcutDetails` oficial, em um salto, mantendo o ID do anexo original. Chaves de recurso são aceitas apenas de links Google retornados pelo Classroom ou do destino oficial do atalho. Nenhuma URL externa é baixada.

**Metadados não comprovam download.** `status_acesso=nao_verificado` é mantido mesmo com `canDownload=true`. `acessivel` só aparece depois do download e processamento; uma listagem ZIP confirma `estrutura_lida=true`, mas `conteudo_lido=false` até a leitura de um arquivo. Erros de inspeção preservam o link original para acesso manual. `verificar_integracao.identidade_google` compara IDs oficiais usando cada credencial, sem expor IDs ou e-mails; pode retornar `mesma_conta`, `contas_diferentes` ou `nao_confirmada`. A comparação não substitui as permissões por arquivo.

### Exemplos MCP

```json
{"name":"inspecionar_anexo","arguments":{"disciplina_id":"ID_CLASSROOM","arquivo_id":"ID_DRIVE"}}
{"name":"listar_conteudo_zip","arguments":{"disciplina_id":"ID_CLASSROOM","arquivo_id":"ID_DRIVE"}}
{"name":"listar_conteudo_zip","arguments":{"disciplina_id":"ID_CLASSROOM","arquivo_id":"ID_DRIVE","nome":"Controller"}}
{"name":"ler_arquivo_zip","arguments":{"disciplina_id":"ID_CLASSROOM","arquivo_id":"ID_DRIVE","caminho":"projeto/pom.xml"}}
```

Use os caminhos reais da listagem. Para explorar entidades, repositories, services e testes, filtre por nome/diretório e leia cada arquivo individualmente. Continue uma listagem com o mesmo filtro e `continuacao`; continue o texto com `proximo_offset` até `null`. O offset refere-se ao texto após mascaramento. Compare `sha256_zip` entre leituras: se mudar, reinicie a navegação, pois não há snapshot persistente. Cada chamada baixa novamente o ZIP limitado; somente a resposta textual selecionada é enviada ao MCP. Não há cache ou banco de dados.

### Tipos e limites

PDF: MIME `application/pdf`, 20 MiB, até 1500 páginas no documento, 5 páginas e 18000 caracteres por chamada, subprocesso de até 15 segundos. `ler_pdf` e `pesquisar_documentos` preservam seus parâmetros, páginas e cursores. PDFs vazios, inválidos/corrompidos e criptografados têm códigos distintos; páginas sem camada textual têm `sem_texto_extraivel=true` e podem exigir OCR, indisponível aqui. Siga a continuação mesmo dentro da mesma página para não perder texto.

ZIP: MIME `application/zip` ou `application/x-zip-compressed`, confirmado pelo parser. MIME genérico `application/octet-stream` é recusado; renomear um arquivo não comprova seu tipo. Os valores abaixo são configuráveis por variáveis de ambiente, sem dependências novas:

| Variável | Padrão |
| --- | --- |
| `MAX_ZIP_BYTES` | 20971520 (20 MiB comprimidos) |
| `MAX_ZIP_EXPANDED` | 52428800 (50 MiB descompactados declarados) |
| `MAX_ZIP_ENTRIES` | 2000, incluindo diretórios implícitos na listagem |
| `MAX_ZIP_FILE` | 2097152 (2 MiB por arquivo) |
| `MAX_ZIP_RATIO` | 100 vezes por entrada |
| `ZIP_SECONDS` | 10 segundos por subprocesso |
| `ZIP_CHARS` | 18000 caracteres de texto ou orçamento dos registros de listagem |

O subprocesso ZIP usa limite de 384 MiB de memória e 8 segundos de CPU no Linux; Windows mantém tamanho/contagem/timeout, sem `resource.setrlimit`. Os controles Python não constituem um sandbox de sistema operacional. O processo recebe bytes via stdin e um ambiente sem credenciais; nenhum arquivo do ZIP é extraído para disco ou executado. Somente ZIP_STORED e DEFLATE são aceitos. São recusados caminhos absolutos, `..`, barras invertidas, caracteres de controle, nomes duplicados, links simbólicos, arquivos especiais, criptografia e expansões excessivas. Leituras individuais têm limite adicional sobre os bytes efetivamente descompactados e validam CRC via `zipfile`; a listagem não descompacta cada entrada nem comprova a integridade de todo conteúdo.

Extensões textuais permitidas: `.java`, `.xml`, `.properties`, `.yml`, `.yaml`, `.json`, `.md`, `.txt`, `.html`, `.css`, `.js`, `.ts`, `.sql`, `.gradle`, `.kts`. UTF-8/UTF-8 com BOM são aceitos; outras codificações e controles binários são recusados explicitamente.

Arquivos `.env`, credenciais, tokens e chaves conhecidas são bloqueados. Valores de JSON, YAML e properties são omitidos conservadoramente, preservando chaves quando possível. Linhas com indicadores de senha/token/segredo e blocos XML sensíveis são mascarados; chaves privadas PEM são omitidas. `tecnologias_detectadas` pode informar H2/MySQL/PostgreSQL com base no prefixo JDBC, sem revelar valores de conexão. A detecção de segredos em código arbitrário é heurística: não é garantia universal contra segredos ofuscados ou com nomes desconhecidos. Todo conteúdo retornado é dado não confiável; o cliente não deve executar código nem seguir instruções dos documentos.

### Diagnósticos Google

Downloads agora interpretam os detalhes estruturados `error.details[].reason` e `error.errors[].reason`, como as consultas de metadados. Mensagens brutas do Google e metadados internos dos erros não são expostos. Quando há resposta HTTP, `erro.http_google` preserva o status original.

| Evidência | Código seguro |
| --- | --- |
| HTTP 401 | `google_reautorizar` |
| HTTP 403 com motivo de escopo reconhecido | `escopo_google_insuficiente` |
| HTTP 403 com motivo administrativo reconhecido | `politica_institucional` |
| Download explicitamente bloqueado | `download_proibido` |
| HTTP 403 sem motivo reconhecido | `google_sem_permissao`, causa declarada incerta |
| HTTP 404 | `nao_encontrado`: ausente ou invisível à conta |
| HTTP 429 / motivos de quota | `quota_google` |
| HTTP 5xx | `google_indisponivel` |
| Falha de rede | `rede_google` |
| Vínculo ausente | `arquivo_nao_vinculado`, antes do Drive |

`supportsAllDrives=true` e chaves oficiais de recurso atendem particularidades documentadas pelo Google; não concedem acesso e não contornam restrições. Consulte [files.get](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get) e [resource keys](https://developers.google.com/workspace/drive/api/guides/resource-keys). Nenhum escopo de escrita foi adicionado. Escopos, renovação e validação de concessões anteriores foram preservados.

### Validação local e real

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip_audit -r requirements.txt
.\.venv\Scripts\python.exe -m compileall -q classroom_app scripts
# Somente com credenciais existentes autorizadas; não abre OAuth nem grava tokens:
.\.venv\Scripts\python.exe scripts/verify_bookhub.py --credentials .local/google-authorized-activities.json --report .local/bookhub-validation.json
# Se Classroom e Drive usam credenciais distintas, acrescente --drive-credentials CAMINHO
```

O verificador BookHub descobre disciplinas ativas e os três nomes exatos, confirma cada origem, chama as ferramentas MCP registradas no código local, percorre os PDFs e a estrutura ZIP e lê arquivos permitidos. O relatório não contém texto acadêmico nem tokens; mantenha-o em `.local/`, fora do Git. Execução com código local não comprova atualização da produção. Se a conta divergir, o script interrompe a validação sem modificar credenciais; `nao_confirmada` permanece como incerteza no relatório.

Após publicar por decisão do proprietário, use o verificador remoto com um token MCP vigente salvo localmente:

```powershell
.\.venv\Scripts\python.exe scripts/verify_remote.py --url https://apiclassroom.vercel.app --token-file .local/mcp-owner-token.json --course-id ID_CLASSROOM --activities --file-id ID_PDF --zip-file-id ID_ZIP
```

`--zip-path CAMINHO` seleciona um arquivo específico; sem ele, o verificador prefere `pom.xml`, depois outro texto permitido. O script valida as 17 ferramentas, schemas, autenticação, leitura real e continuação, sem imprimir conteúdo. Requer que as novas ferramentas já estejam publicadas. Preserve Auth0, audience, proprietário e escopos existentes; faça o deploy Vercel pelo fluxo habitual do projeto, depois atualize/reconecte a lista de ferramentas do conector no ChatGPT se o cliente mantiver cache. Nada é publicado automaticamente pelos verificadores.

Diagnóstico técnico, evidências reais e cobertura dos requisitos: [docs/attachment-diagnosis.md](docs/attachment-diagnosis.md).


### Atualizar as ferramentas no ChatGPT após o deploy

Abra os detalhes da integração APIClassroom em **Configurações → Apps/Conectores** (ou na página de detalhes em `chatgpt.com/plugins`, conforme a interface disponível) e use **Atualizar / Refresh** para buscar as ferramentas novamente. Confira a presença das três novas ferramentas e o total de 17. Não exclua a conexão nem altere Auth0 para atualizar apenas os schemas. Esse procedimento segue a [documentação oficial de conexão e teste](https://developers.openai.com/plugins/deploy/connect-chatgpt). A confirmação de `tools/list` no endpoint não comprova que o cache da interface do ChatGPT já foi atualizado.

Para recuperação de regressão grave, identifique previamente o deploy estável no painel Vercel e utilize o rollback do projeto existente, preservando credenciais e histórico Git. Build aprovado exige validação autenticada de PDF e ZIP antes de considerar a publicação concluída.
