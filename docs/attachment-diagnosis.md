# Diagnóstico e validação de anexos — 24/10/2026

## 1. Causa-raiz

- `materials.attachments()` já extraía corretamente o ID de `materials[].driveFile.driveFile.id`; não foi necessário trocar esse identificador.
- `Materials.linked_file()` no HEAD original percorria materiais e atividades, mas ignorava avisos. Os três anexos BookHub estão em um aviso. A execução da classe original, obtida de `git show HEAD:classroom_app/materials.py`, contra o ID real do ZIP retornou `arquivo_nao_vinculado`; a implementação corrigida confirmou o aviso e baixou/leu o conteúdo.
- `Materials.files()` listava apenas uma página dos materiais. Anexos exclusivos de atividades/avisos não eram descobertos por essa ferramenta, e duplicações entre páginas não eram conciliadas.
- `GoogleClient.download()` chamava `google_error(status)` sem o corpo da resposta; causas estruturadas de 403 eram perdidas. Não foi possível atribuir com certeza o 403/404 histórico a uma política ou conta, pois esse erro não se reproduziu nas credenciais existentes usadas nesta validação.
- O leitor aceitava somente PDF. Mesmo autorizado pelo Google, um ZIP não tinha ferramenta para inspeção/leitura.

## 2. Alterações

`materials.py` agora percorre as três fontes e suas páginas; listagens deduplicam por ID e preservam todas as origens. `google.py` interpreta erros de download com corpo limitado, preserva o HTTP original sem mensagens privadas, aceita limites próprios de ZIP e parâmetros oficiais de Drives compartilhados/resource keys. `documents.py` compartilha a validação de vínculo/metadados entre as leituras, resolve um salto de atalho oficial, conserva links nas recusas e distingue metadados de conteúdo lido.

A comparação das contas usa `about.user.permissionId` com cada credencial e só devolve igualdade/divergência/incerteza. Não há escopos novos, nova autorização ou gravação de tokens.

## 3. Novas funcionalidades

Há 17 ferramentas MCP: as 14 anteriores e `inspecionar_anexo`, `listar_conteudo_zip`, `ler_arquivo_zip`. Permanecem wrapper de erros, schemas estruturados, `classroom:read` e anotações somente de leitura. O ZIP permite filtros por nome/diretório, diretórios implícitos, leitura UTF-8 individual, continuação, contagens e hash do ZIP. PDF preserva paginação e ganha identificação de vazio, erros mais específicos e indicação explícita de continuação/caracteres.

## 4. Segurança

ZIP: 20 MiB comprimidos, 50 MiB expandidos declarados, 2000 entradas, 2 MiB por arquivo, razão máxima 100, 10 segundos de subprocesso e 18000 caracteres por resposta, configuráveis. Linux limita memória/CPU do worker; Windows utiliza os controles de tamanho/tempo. Bloqueios: traversal, caminhos absolutos, caracteres de controle, nomes duplicados, symlinks, arquivos especiais, criptografia, compressões não permitidas e binários. No Windows é validado `ZipInfo.orig_filename`, pois `filename` já pode ter normalizado barras ou removido NUL.

Não há extração em disco, execução de código ou cache persistente. Arquivos de credenciais conhecidos são bloqueados; valores de configurações são omitidos e padrões sensíveis são mascarados antes de paginar. Essa detecção é conservadora/heurística, sem garantia universal para segredos arbitrários em código. A listagem ZIP valida cabeçalhos/limites, mas não descompacta todas as entradas; CRC é validado na leitura seletiva. Todo texto é marcado como não confiável.

## 5. Testes

Comandos executados:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip_audit -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q classroom_app scripts tests
git diff --check
```

A suíte contém 190 testes (102 regressões existentes e 88 casos novos parametrizados). A auditoria não encontrou vulnerabilidades conhecidas e `pip check` não encontrou dependências quebradas. Não há dependências novas.

Cobertura dos requisitos de teste:

| Casos solicitados | Evidências na suíte |
| --- | --- |
| 1–8: descoberta, paginação, IDs, vínculo e duplicações | `test_binding_in_every_source`, `test_all_pages_deduplicated_keep_every_origin`, `test_invalid_ids_never_reach_google`, `test_inaccessible_course_blocks_all_sources`, testes de vínculo/PDF anteriores |
| 9–17: download, HTTP, rede, MIME e metadados sem conteúdo | `test_streamed_google_errors_are_structured_and_private`, `test_download_network_failure`, `test_inspect_metadata_is_not_content`, `test_inspect_denial_retains_original_link`, `test_metadata_allowed_download_denied`, `test_pdf_preflight` |
| 18–25: PDF válido, vazio, sem texto, inválido, criptografia, tamanho e continuação | testes anteriores de PDF e `test_pdf_empty_and_encrypted_worker`, `test_zero_bytes_pdf_and_scanned_pages`; PDFs reais também lidos integralmente |
| 26–32: Maven, árvore, Java/XML/properties, filtros e paginação | `test_maven_text_files`, `test_tree_and_directory_name_filters`, `test_zip_listing_pagination_bound_to_filters_and_bytes`, `test_zip_text_pagination_without_loss`, `test_zip_worker_integration_and_preflight` |
| 33–42: binário, corrupção, expansão, caminhos, contagem, tamanho, criptografia, links e segredos | `test_zip_binary_encoding_and_sensitive_files`, `test_corrupt_zip_sanitized`, `test_zip_limits`, `test_zip_unsafe_paths`, `test_symlink_and_encrypted_entries`, `test_sensitive_configuration_is_masked_before_pagination`, `test_duplicate_zip_names_and_bad_crc_are_refused` |
| 43–52: registro, schemas, wire MCP, autenticação, regressões e ausência de segredos | `test_new_mcp_tools_wire_schemas_calls_and_error_wrapper`, `test_new_tools_cannot_bypass_mcp_authorization`, suíte anterior de JWT/MCP/atividades/entregas/diagnósticos, `test_worker_timeout_and_no_secrets` |

## 6. Validação BookHub

Validação real com APIs Google e ferramentas MCP registradas do código local, usando credencial existente autorizada. A comparação oficial indicou a mesma conta. Os três anexos foram encontrados na turma Backend 2026.2 e vinculados a um aviso. Nenhum conteúdo acadêmico foi versionado.

| Anexo | Resultado real |
| --- | --- |
| `BookHub_Codigo_Inicial.zip` | 11016 bytes, MIME `application/x-zip-compressed`, 17 arquivos; estrutura percorrida e texto de `pom.xml`, `BookHubApplication.java` e `model/Autor.java` efetivamente lido |
| `BookHub_Laboratorio_Guiado_JPA.pdf` | 31594 bytes, 3 páginas, 4544 caracteres extraídos, 1 chamada, fim de continuação confirmado |
| `Relacionamentos-entre-Entidades-com-JPA-Hibernate-e-Spring-Boot.pdf` | 798756 bytes, 31 páginas, 12764 caracteres extraídos, 7 chamadas, continuação concluída |

A estrutura real inclui `bookhub-base/pom.xml`, `src/main/java`, `model`, `repository`, `service` e `src/main/resources/application.properties`. Não foi inferida a presença de controllers ou testes. O relatório local completo, com IDs e origens, está em `.local/bookhub-validation.json`, ignorado pelo Git; não contém texto dos arquivos nem tokens. Esses resultados são distintos dos testes com mocks e não representam deploy em produção.

## 7. Compatibilidade

Auth0, JWT RS256, issuer/audience, PKCE/CIMD, proprietário, origens, escopos Google, concessões e renovação não foram alterados. `activities.py`, `courses.py`, `security.py`, `google_authorization.py` e os aliases permanecem intactos. Ferramentas antigas e contratos de atividades/entregas utilizados pelo AgendaJeff foram preservados. O campo de diagnóstico de conta é aditivo. A listagem de arquivos mantém parâmetros/campos antigos, acrescenta origens e usa cursores opacos novos; cursores antigos já emitidos devem ser reiniciados.

## 8. Pendências e limitações

Não houve impedimento de permissão nos três anexos durante esta execução. O antigo 403/404 permanece sem causa histórica comprovada. Produção ainda precisa receber o código. Turmas muito grandes podem exceder os limites de chamadas ao reunir todas as origens; o README descreve a navegação paginada por fonte. ZIPs são baixados novamente por chamada, sem snapshot persistente; hash diferente requer reiniciar a leitura. Não há OCR nem garantia universal de detecção de segredos ofuscados.

## 9. Publicação

O projeto está preparado para publicação pelo fluxo Vercel existente. Revise as alterações, publique o código mantendo as variáveis Auth0/Google atuais e execute `scripts/verify_remote.py` com IDs autorizados de PDF/ZIP, token MCP vigente e `--activities`. O script espera 17 ferramentas e valida schemas/transporte/leitura. Depois atualize a lista de ferramentas do conector ChatGPT caso haja cache. Não foi realizado push, deploy ou atualização de credenciais.

## 10. Git

Branch original `main`; alterações locais sem commit. Modificados: `README.md`, `classroom_app/app.py`, `config.py`, `documents.py`, `errors.py`, `google.py`, `materials.py`, `mcp_server.py`, `pdf_worker.py`, `scripts/verify_remote.py`, `tests/test_business.py`. Novos: `classroom_app/zip_worker.py`, `scripts/verify_bookhub.py`, `tests/test_attachments.py` e este relatório. Arquivos privados permanecem ignorados.
