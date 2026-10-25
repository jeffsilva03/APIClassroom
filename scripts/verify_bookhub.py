"""Validação BookHub com credenciais existentes; não autoriza nem grava tokens.

Relatório contém metadados e contagens, nunca texto dos documentos ou segredos.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classroom_app.app import create_app
from classroom_app.config import Settings
from classroom_app.google import GoogleClient, budget
from classroom_app.errors import ServiceError

TARGETS = ['BookHub_Codigo_Inicial.zip', 'BookHub_Laboratorio_Guiado_JPA.pdf', 'Relacionamentos-entre-Entidades-com-JPA-Hibernate-e-Spring-Boot.pdf']


async def verify(args):
    classroom = args.credentials.read_text(encoding='utf-8-sig')
    drive = args.drive_credentials.read_text(encoding='utf-8-sig') if args.drive_credentials else classroom
    settings = Settings(classroom_credentials=classroom, drive_credentials=drive)
    google = GoogleClient(settings)
    app = create_app(settings, google)
    server = app.state.mcp
    report = {'ambiente': 'codigo_local_com_APIs_Google_reais', 'publicado': False, 'arquivos': {name: {'status': 'nao_localizado'} for name in TARGETS}}

    async def call(name, arguments):
        marker = budget.set(None)
        try:
            result = await server.call_tool(name, arguments)
            return result.structured_content or {}, result.is_error
        finally:
            budget.reset(marker)

    try:
        marker = budget.set(None)
        try:
            report['identidade_google'] = await google.identity_status()
        finally:
            budget.reset(marker)
        if report['identidade_google'] == 'contas_diferentes':
            raise ServiceError('contas_google_diferentes', 'Credenciais Classroom e Drive correspondem a contas diferentes; preserve-as e revise a configuração.', 403)
        courses, token, seen = [], None, set()
        while True:
            data, failed = await call('listar_disciplinas', {'pagina': token})
            if failed:
                report['diagnostico'] = data
                break
            courses.extend(data['disciplinas'])
            token = data['proxima_pagina']
            if not token: break
            if token in seen: raise ServiceError('paginacao_google', 'Cursor repetido.')
            seen.add(token)
        # A busca pelo nome só prioriza turmas; não presume ID nem exclui outras.
        courses.sort(key=lambda c: (args.course_query.casefold() not in c['nome'].casefold(), not any(term in c['nome'].casefold() for term in ('java', 'backend', 'desenvolvimento'))))
        for course in courses:
            token, seen = None, set()
            while True:
                page, failed = await call('listar_arquivos', {'disciplina_id': course['id'], 'pagina': token})
                if failed:
                    report.setdefault('falhas_descoberta', []).append({'disciplina_id': course['id'], **page})
                    break
                for file in page['arquivos']:
                    name = file.get('nome')
                    if name not in TARGETS or report['arquivos'][name]['status'] != 'nao_localizado': continue
                    base = {'disciplina_id': course['id'], 'arquivo_id': file['id']}
                    inspection, failed = await call('inspecionar_anexo', base)
                    row = {'status': 'localizado', 'disciplina': course['nome'], **base, 'origens': file['origens'], 'inspecao': inspection}
                    report['arquivos'][name] = row
                    if failed or inspection.get('status_acesso') in {'download_proibido', 'indisponivel', 'falha_temporaria'}:
                        row['status'] = 'acesso_bloqueado'
                        continue
                    if name.lower().endswith('.pdf'):
                        cursor, pages, chars, hashes, count = {'pagina_inicio': 1, 'offset': 0}, set(), 0, set(), 0
                        while cursor:
                            data, failed = await call('ler_pdf', base | cursor)
                            if failed:
                                row.update(status='leitura_bloqueada', diagnostico=data)
                                break
                            pages.update(p['pagina'] for p in data['paginas'])
                            chars += sum(len(p['texto']) for p in data['paginas'])
                            cursor = data['continuacao']
                            count += 1
                            if cursor:
                                key = json.dumps(cursor, sort_keys=True)
                                if key in hashes or count >= 500: raise ServiceError('limite_validacao', 'Limite de continuação atingido.')
                                hashes.add(key)
                        else:
                            row.update(status='conteudo_lido' if chars else 'sem_texto_extraivel', paginas_lidas=len(pages), total_paginas=data['total_paginas'], caracteres_lidos=chars, chamadas=count, continuacao_validada=True)
                    else:
                        token, entries, zip_seen = None, [], set()
                        while True:
                            data, failed = await call('listar_conteudo_zip', base | {'continuacao': token})
                            if failed:
                                row.update(status='leitura_bloqueada', diagnostico=data)
                                break
                            entries.extend(data['entradas'])
                            token = data['continuacao']
                            if not token:
                                row.update(status='estrutura_lida', total_arquivos=data['total_arquivos'], estrutura=[e['caminho'] for e in entries], sha256_zip=data['sha256_zip'])
                                candidates = [e for e in entries if e['leitura_permitida'] and (e['caminho'].endswith('pom.xml') or e['caminho'].endswith('.java'))]
                                row['leituras'] = []
                                for entry in candidates[:3]:
                                    cursor, chars, count = 0, 0, 0
                                    while cursor is not None:
                                        text, denied = await call('ler_arquivo_zip', base | {'caminho': entry['caminho'], 'offset': cursor})
                                        if denied:
                                            row['leituras'].append({'caminho': entry['caminho'], 'diagnostico': text})
                                            break
                                        assert text['sha256_zip'] == row['sha256_zip']
                                        chars += text['caracteres_retornados']
                                        cursor = text['proximo_offset']
                                        count += 1
                                        if count > 500: raise ServiceError('limite_validacao', 'Limite de leitura atingido.')
                                    else:
                                        row['leituras'].append({'caminho': entry['caminho'], 'caracteres_lidos': chars, 'chamadas': count, 'conteudo_lido': True})
                                if any(r.get('conteudo_lido') for r in row['leituras']): row['status'] = 'conteudo_lido'
                                break
                            if token in zip_seen: raise ServiceError('paginacao_google', 'Cursor ZIP repetido.')
                            zip_seen.add(token)
                token = page['proxima_pagina']
                if not token: break
                if token in seen: raise ServiceError('paginacao_google', 'Cursor arquivos repetido.')
                seen.add(token)
            if all(r['status'] != 'nao_localizado' for r in report['arquivos'].values()): break
    except ServiceError as exc:
        report['diagnostico'] = exc.payload()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--drive-credentials', type=Path)
    parser.add_argument('--course-query', default='Java')
    parser.add_argument('--report', type=Path)
    asyncio.run(verify(parser.parse_args()))
