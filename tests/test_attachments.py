import io
import json
import stat
import struct
import subprocess
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pypdf import PdfWriter

from classroom_app.activities import Activities
from classroom_app.app import create_app
from classroom_app.config import Settings
from classroom_app.documents import Documents
from classroom_app.errors import ServiceError
from classroom_app.google import GoogleClient, budget, google_error
from classroom_app.materials import Materials
from classroom_app.pdf_worker import extract
from classroom_app.zip_worker import inspect, redact
from test_business import signed, settings


@pytest.fixture(autouse=True)
def clean_budget():
    marker = budget.set(None)
    yield
    budget.reset(marker)


def packed(files=None, compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=compression) as archive:
        for path, data in (files or {'pom.xml': '<project/>', 'src/main/java/Book.java': 'class Book {}', 'src/main/resources/application.properties': 'spring.datasource.url=jdbc:h2:mem:books\nspring.datasource.password=secret-sentinel\n', 'README.md': 'A Maven project'}).items():
            archive.writestr(path, data)
    return stream.getvalue()


def options(**kw):
    return dict(operation='list', max_bytes=20*1024*1024, max_total=50*1024*1024, max_entries=2000, max_file=2*1024*1024, max_ratio=100, limit=18000, directory=None, continuation=None, path=None, name=None, offset=0) | kw


def documents(meta=None, data=None):
    google, materials = AsyncMock(), AsyncMock()
    materials.linked_file.return_value = ({'id': '1'}, {'link': 'https://drive.google.com/file/d/file/view'}, {'id': 'm', 'origem': 'material', 'link': 'https://classroom.google.com/m'})
    google.get.return_value = meta or {'id': 'file', 'mimeType': 'application/zip', 'name': 'project.zip', 'size': '100', 'capabilities': {'canDownload': True}}
    google.download.return_value = data if data is not None else packed()
    return Documents(google, materials, Settings()), google


def attachment(file_id='file', name='project.zip'):
    return {'driveFile': {'driveFile': {'id': file_id, 'title': name, 'alternateLink': 'https://drive.google.com/file/d/' + file_id + '/view'}}}


@pytest.mark.parametrize('kind,key,origin', [('courseWorkMaterials','courseWorkMaterial','material'), ('courseWork','courseWork','atividade'), ('announcements','announcements','aviso')])
async def test_binding_in_every_source(kind, key, origin):
    google, courses = AsyncMock(), AsyncMock()
    courses.detail.return_value = {'id': '1', 'nome': 'Java'}
    async def get(path, params=None):
        return {key: [{'id': 'publication-id', 'state': 'PUBLISHED', 'materials': [attachment()]}]} if path.endswith('/'+kind) else {}
    google.get.side_effect = get
    service = Materials(google, courses, Activities(google, courses))
    _, linked, publication = await service.linked_file('1','file')
    assert linked['id'] == 'file' and publication['id'] == 'publication-id'
    assert publication['origem'] == origin


async def test_all_pages_deduplicated_keep_every_origin():
    google, courses = AsyncMock(), AsyncMock()
    courses.detail.return_value = {'id': '1','nome':'Java'}
    async def get(path, params=None):
        key = {'courseWorkMaterials':'courseWorkMaterial','courseWork':'courseWork','announcements':'announcements'}[path.rsplit('/',1)[1]]
        if key == 'courseWorkMaterial':
            return {key:[{'id':'m2' if params.get('pageToken') else 'm1', 'materials':[attachment()]}], **({} if params.get('pageToken') else {'nextPageToken':'next'})}
        return {key:[{'id':key,'state':'PUBLISHED','materials':[attachment('file'),attachment('second')]}]}
    google.get.side_effect = get
    service = Materials(google,courses,Activities(google,courses))
    first = await service.files('1',1)
    second = await service.files('1',1,first['proxima_pagina'])
    assert first['total_arquivos'] == 2 and len(first['arquivos'][0]['origens']) == 4
    assert first['arquivos'][0]['materiais_ids'] == ['m1','m2']
    assert first['arquivos'][0]['status_acesso'] == 'nao_verificado'
    assert second['arquivos'][0]['id'] != first['arquivos'][0]['id']
    assert second['proxima_pagina'] is None
    with pytest.raises(ServiceError):
        await service.files('1',1,'bad cursor')


async def test_repeated_publication_cursor_rejected():
    google,courses = AsyncMock(),AsyncMock()
    google.get.return_value = {'nextPageToken':'same'}
    with pytest.raises(ServiceError) as err:
        await Materials(google,courses).files('1')
    assert err.value.code == 'paginacao_google'


@pytest.mark.parametrize('bad', ['https://drive.google.com/file/x','../file','a/b','x?alt=media',''])
async def test_invalid_ids_never_reach_google(bad):
    google,courses = AsyncMock(),AsyncMock()
    with pytest.raises(ServiceError):
        await Materials(google,courses).linked_file('1',bad)
    google.get.assert_not_called()


async def test_inaccessible_course_blocks_all_sources():
    google,courses = AsyncMock(),AsyncMock()
    courses.detail.side_effect = ServiceError('disciplina_inacessivel','Denied',403)
    with pytest.raises(ServiceError):
        await Materials(google,courses).linked_file('1','file')
    google.get.assert_not_called()


@pytest.mark.parametrize('status,reason,code', [(401,None,'google_reautorizar'),(403,'ACCESS_TOKEN_SCOPE_INSUFFICIENT','escopo_google_insuficiente'),(403,'ADMIN_POLICY_ENFORCED','politica_institucional'),(403,'cannotDownloadFile','download_proibido'),(403,None,'google_sem_permissao'),(404,None,'nao_encontrado'),(429,None,'quota_google'),(503,None,'google_indisponivel')])
async def test_streamed_google_errors_are_structured_and_private(settings,monkeypatch,status,reason,code):
    original=httpx.AsyncClient
    def handler(request):
        assert request.url.params['supportsAllDrives'] == 'true'
        return httpx.Response(status,json={'error':{'message':'secret-sentinel','details':[{'reason':reason,'metadata':{'token':'private'}}]}})
    monkeypatch.setattr('classroom_app.google.httpx.AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    google=GoogleClient(settings);google.token=AsyncMock(return_value='private-token')
    with pytest.raises(ServiceError) as err:
        await google.download('file')
    assert err.value.code == code and err.value.payload()['erro']['http_google'] == status
    assert 'secret-sentinel' not in json.dumps(err.value.payload()) and 'private-token' not in str(err.value)


@pytest.mark.parametrize('payload',[{'error':{'details':None,'errors':'malformed'}},{'error':'secret-sentinel'},{'error':{'details':[{'reason':{}}]}}])
def test_malformed_google_errors_fail_safely(payload):
    assert google_error(403,payload).code == 'google_sem_permissao'


async def test_download_network_failure(settings,monkeypatch):
    original=httpx.AsyncClient
    def handler(request):
        raise httpx.ConnectError('secret-sentinel',request=request)
    monkeypatch.setattr('classroom_app.google.httpx.AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    google=GoogleClient(settings);google.token=AsyncMock(return_value='private-token')
    with pytest.raises(ServiceError) as err:
        await google.download('file')
    assert err.value.code == 'rede_google' and 'secret-sentinel' not in str(err.value)


@pytest.mark.parametrize('can_download,status',[(True,'nao_verificado'),(False,'download_proibido')])
async def test_inspect_metadata_is_not_content(can_download,status):
    doc,google=documents()
    google.get.return_value['capabilities']['canDownload']=can_download
    result=await doc.inspect('1','file')
    assert result['status_acesso'] == status and result['conteudo_lido'] is False
    assert result['link_original'].startswith('https://drive.google.com/')
    google.download.assert_not_called()


@pytest.mark.parametrize('status,expected',[(404,'indisponivel'),(429,'falha_temporaria'),(503,'falha_temporaria'),(403,'indisponivel')])
async def test_inspect_denial_retains_original_link(status,expected):
    doc,google=documents();google.get.side_effect=google_error(status)
    result=await doc.inspect('1','file')
    assert result['status_acesso'] == expected and result['link_original']
    assert not result['conteudo_lido']


async def test_metadata_allowed_download_denied():
    doc,google=documents();google.download.side_effect=google_error(403)
    with pytest.raises(ServiceError) as err:
        await doc.zip('1','file','list')
    assert err.value.code == 'google_sem_permissao'


async def test_shortcut_target_only_from_google():
    doc,google=documents()
    google.get.side_effect=[{'mimeType':'application/vnd.google-apps.shortcut','shortcutDetails':{'targetId':'official-target','targetResourceKey':'key'}},{'mimeType':'application/zip','capabilities':{'canDownload':True}}]
    await doc.zip('1','file','list')
    google.download.assert_awaited_once_with('official-target',max_bytes=doc.settings.max_zip_bytes,resource_key='key')


async def test_nested_shortcut_refused():
    doc,google=documents();google.get.return_value={'mimeType':'application/vnd.google-apps.shortcut','shortcutDetails':{'targetId':'file'}}
    with pytest.raises(ServiceError) as err:
        await doc.zip('1','file','list')
    assert err.value.code == 'atalho_indisponivel'
    google.download.assert_not_called()


@pytest.mark.parametrize('left,right,expected',[('same','same','mesma_conta'),('left','right','contas_diferentes'),(None,None,'nao_confirmada')])
async def test_account_comparison_does_not_expose_identity(settings,left,right,expected):
    google=GoogleClient(settings);google.get=AsyncMock(side_effect=[{'user':{'permissionId':left}},{'user':{'permissionId':right}}])
    assert await google.identity_status() == expected
    assert google.get.call_args_list[0].kwargs['credential_kind'] == 'classroom'


@pytest.mark.parametrize('path',['pom.xml','src/main/java/Book.java','README.md','src/main/resources/application.properties'])
def test_maven_text_files(path):
    result=inspect(packed(),options(operation='read',path=path))
    assert result['texto'] and result['conteudo_lido'] and result['codificacao']=='UTF-8'
    assert 'secret-sentinel' not in result['texto']


def test_tree_and_directory_name_filters():
    result=inspect(packed(),options())
    assert result['total_arquivos']==4
    assert any(e['caminho']=='src/main/java/' and e['diretorio'] for e in result['entradas'])
    filtered=inspect(packed(),options(directory='src/main',name='.java'))
    assert [e['caminho'] for e in filtered['entradas']]==['src/main/java/Book.java']


def test_zip_listing_pagination_bound_to_filters_and_bytes():
    data=packed({f'{n}.java':'class A {}' for n in range(210)})
    rows=[];cursor=None
    while True:
        result=inspect(data,options(continuation=cursor))
        rows.extend(result['entradas']);cursor=result['continuacao']
        if not cursor:break
    assert len(rows)==210 and len({e['caminho'] for e in rows})==210
    first=inspect(data,options())
    for changed,opt in [(data,options(name='java',continuation=first['continuacao'])),(packed(),options(continuation=first['continuacao']))]:
        with pytest.raises(ValueError,match='zip_cursor_invalido'):inspect(changed,opt)


def test_zip_text_pagination_without_loss():
    text='class Book {}\n'*2500; data=packed({'Book.java':text})
    result=inspect(data,options(operation='read',path='Book.java'))
    assert result['truncado'] and len(result['texto'])==18000
    second=inspect(data,options(operation='read',path='Book.java',offset=result['proximo_offset']))
    assert result['texto']+second['texto']==text and not second['truncado']


@pytest.mark.parametrize('path,content,code',[('a.java',b'\x00binary','zip_arquivo_binario'),('image.png',b'PNG','zip_texto_nao_permitido'),('a.txt',b'\xff','zip_codificacao_invalida'),('.env',b'PASSWORD=secret-sentinel','zip_texto_nao_permitido'),('credentials.json',b'{}','zip_texto_nao_permitido'),('private.key',b'key','zip_texto_nao_permitido')])
def test_zip_binary_encoding_and_sensitive_files(path,content,code):
    with pytest.raises(ValueError,match=code):inspect(packed({path:content}),options(operation='read',path=path))


@pytest.mark.parametrize('path',['../Book.java','/root/Book.java','C:/Book.java','src/../../x','src\\x','./pom.xml','a//b','a\x00b'])
def test_zip_unsafe_paths(path):
    # zipfile truncates names at NUL, so exercise validator directly for that case.
    from classroom_app.zip_worker import safe_path
    with pytest.raises(ValueError,match='zip_caminho_inseguro'):safe_path(path)
    if '\x00' not in path:
        data = packed({path:'data'})
        if '\\' in path:
            data = data.replace(path.replace('\\','/').encode(), path.encode())
        with pytest.raises(ValueError,match='zip_caminho_inseguro'):inspect(data,options())


@pytest.mark.parametrize('kw,files',[({'max_entries':1},{'a.java':'a','b.java':'b'}),({'max_file':4},{'a.java':'12345'}),({'max_total':5},{'a.java':'123','b.java':'456'}),({'max_ratio':2},{'a.java':'A'*10000}),({'max_bytes':10},{'a.java':'12345'})])
def test_zip_limits(kw,files):
    with pytest.raises(ValueError,match='zip_'):inspect(packed(files,zipfile.ZIP_DEFLATED),options(**kw))


def test_symlink_and_encrypted_entries():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        info=zipfile.ZipInfo('link.java');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
        archive.writestr(info,'/etc/passwd')
    with pytest.raises(ValueError,match='zip_link_inseguro'):inspect(stream.getvalue(),options())
    data=bytearray(packed({'a.java':'class A {}'}))
    for marker,delta in [(b'PK\x03\x04',6),(b'PK\x01\x02',8)]:
        pos=data.find(marker)+delta
        struct.pack_into('<H',data,pos,struct.unpack_from('<H',data,pos)[0]|1)
    with pytest.raises(ValueError,match='zip_criptografado'):inspect(bytes(data),options())


@pytest.mark.parametrize('path,text',[('application.properties','spring.datasource.password=secret-sentinel\nurl=jdbc:mysql://user:secret-sentinel@host/db\n'),('config.yaml','anything: |\n  secret-sentinel\n'),('config.json','{"anything":"secret-sentinel"}'),('config.xml','<password>\nsecret-sentinel\n</password>'),('Book.java','String token = "secret-sentinel";\n'),('a.txt','-----BEGIN PRIVATE KEY-----\nsecret-sentinel\n')])
def test_sensitive_configuration_is_masked_before_pagination(path,text):
    masked,changed=redact(text,path)
    assert changed and 'secret-sentinel' not in masked


async def test_zip_worker_integration_and_preflight():
    doc,google=documents()
    assert (await doc.zip('1','file','list'))['total_arquivos']==4
    assert (await doc.zip('1','file','read',path='pom.xml'))['texto']=='<project/>'
    google.get.return_value['mimeType']='image/png'
    with pytest.raises(ServiceError) as err:await doc.zip('1','file','list')
    assert err.value.code=='tipo_invalido'


async def test_corrupt_zip_sanitized():
    doc,_=documents(data=b'private-sentinel')
    with pytest.raises(ServiceError) as err:await doc.zip('1','file','list')
    assert err.value.code=='zip_invalido' and 'private-sentinel' not in str(err.value)


async def test_worker_timeout_and_no_secrets(monkeypatch):
    doc,_=documents()
    monkeypatch.setenv('PRIVATE_SENTINEL','secret')
    def run(*args,**kwargs):
        assert 'PRIVATE_SENTINEL' not in kwargs['env']
        assert kwargs['timeout']==doc.settings.zip_seconds
        raise subprocess.TimeoutExpired('worker',1)
    monkeypatch.setattr('classroom_app.documents.subprocess.run',run)
    with pytest.raises(ServiceError) as err:await doc.zip('1','file','list')
    assert err.value.code=='zip_limite_processamento'


@pytest.mark.parametrize('empty,encrypted,code',[(True,False,'pdf_vazio'),(False,True,'pdf_criptografado')])
async def test_pdf_empty_and_encrypted_worker(empty,encrypted,code):
    writer=PdfWriter()
    if not empty:writer.add_blank_page(width=100,height=100)
    if encrypted:writer.encrypt('secret')
    stream=io.BytesIO();writer.write(stream)
    doc,_=documents(meta={'mimeType':'application/pdf'},data=stream.getvalue())
    with pytest.raises(ServiceError) as err:await doc.read('1','file')
    assert err.value.code==code


def test_zero_bytes_pdf_and_scanned_pages():
    with pytest.raises(ValueError,match='pdf_vazio'):extract(b'',1,5,0)
    writer=PdfWriter()
    for _ in range(11):writer.add_blank_page(width=100,height=100)
    stream=io.BytesIO();writer.write(stream)
    cursor={'start':1,'offset':0};seen=[]
    while cursor:
        result=extract(stream.getvalue(),cursor['start'],cursor['start']+4,cursor['offset'])
        seen.extend(p['pagina'] for p in result['paginas'])
        assert all(p['sem_texto_extraivel'] for p in result['paginas'])
        more=result['continuacao'];cursor={'start':more['pagina_inicio'],'offset':more['offset']} if more else None
    assert seen==list(range(1,12))


def test_new_mcp_tools_wire_schemas_calls_and_error_wrapper(settings,signed):
    verifier,make=signed
    google=AsyncMock()
    async def get(path,params=None,**kwargs):
        if path=='courses':return {'courses':[{'id':'1','name':'Java','courseState':'ACTIVE'}]}
        if path=='files/file':return {'id':'file','mimeType':'application/zip','name':'project.zip','capabilities':{'canDownload':True}}
        if path.endswith('courseWorkMaterials'):return {'courseWorkMaterial':[{'id':'m','materials':[attachment()]}]}
        return {}
    google.get.side_effect=get;google.download.return_value=packed()
    with TestClient(create_app(settings,google,verifier)) as client:
        headers={'Authorization':'Bearer '+make(),'Accept':'application/json, text/event-stream'}
        def rpc(method,params):
            response=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
            assert response.status_code==200
            return response.json()['result']
        tools=rpc('tools/list',{})['tools']
        assert len(tools)==17
        for tool in tools:
            Draft202012Validator.check_schema(tool['inputSchema'])
            if tool.get('outputSchema'):Draft202012Validator.check_schema(tool['outputSchema'])
            assert tool['annotations']['readOnlyHint']
            assert tool['_meta']['securitySchemes']==[{'type':'oauth2','scopes':['classroom:read']}]
        for name,extra in [('inspecionar_anexo',{}),('listar_conteudo_zip',{}),('ler_arquivo_zip',{'caminho':'pom.xml'})]:
            result=rpc('tools/call',{'name':name,'arguments':{'disciplina_id':'1','arquivo_id':'file',**extra}})
            assert not result.get('isError')
            schema=next(t['outputSchema'] for t in tools if t['name']==name)
            Draft202012Validator(schema).validate(result['structuredContent'])
        failure=rpc('tools/call',{'name':'ler_arquivo_zip','arguments':{'disciplina_id':'1','arquivo_id':'file','caminho':'../x'}})
        assert failure['isError'] and failure['structuredContent']['erro']['codigo']=='caminho_zip_invalido'

async def test_zip_download_uses_its_own_byte_limit(settings, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr('classroom_app.google.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'12345678')), **kw))
    google = GoogleClient(settings)
    google.token = AsyncMock(return_value='private-token')
    with pytest.raises(ServiceError) as err:
        await google.download('file', max_bytes=4)
    assert err.value.code == 'arquivo_grande'


def test_duplicate_zip_names_and_bad_crc_are_refused():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('a.java', 'class A {}')
        with pytest.warns(UserWarning):
            archive.writestr('a.java', 'class B {}')
    with pytest.raises(ValueError, match='zip_entrada_duplicada'):
        inspect(stream.getvalue(), options())
    data = packed({'a.java': 'class A {}'}).replace(b'class A {}', b'class B {}')
    with pytest.raises(zipfile.BadZipFile):
        inspect(data, options(operation='read', path='a.java'))


async def test_google_link_resource_key_never_becomes_external_download():
    doc, google = documents()
    doc.materials.linked_file.return_value[1]['link'] = 'https://drive.google.com/file/d/file/view?resourcekey=official-key'
    await doc.zip('1', 'file', 'list')
    assert google.get.call_args.kwargs['resource_key'] == 'official-key'
    google.download.assert_awaited_once_with('file', max_bytes=doc.settings.max_zip_bytes, resource_key='official-key')


def test_configuration_keeps_safe_database_detection():
    result = inspect(packed(), options(operation='read', path='src/main/resources/application.properties'))
    assert result['tecnologias_detectadas'] == ['H2']
    assert 'secret-sentinel' not in result['texto']


@pytest.mark.parametrize('name', ['inspecionar_anexo', 'listar_conteudo_zip', 'ler_arquivo_zip'])
@pytest.mark.parametrize('identity,status', [('anonymous', 401), ('other', 403), ('missing_scope', 403)])
def test_new_tools_cannot_bypass_mcp_authorization(settings, signed, name, identity, status):
    verifier, make = signed
    google = AsyncMock()
    token = None if identity == 'anonymous' else make(sub='other') if identity == 'other' else make(scope='')
    with TestClient(create_app(settings, google, verifier)) as client:
        headers = {'Accept': 'application/json, text/event-stream'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        response = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': {'disciplina_id': '1', 'arquivo_id': 'file', 'caminho': 'pom.xml'}}})
        assert response.status_code == status
    google.get.assert_not_called()
    google.download.assert_not_called()
