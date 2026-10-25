import base64
import hashlib
import json

from .courses import identifier, normalize, page_params
from .errors import ServiceError


def attachments(item):
    result = []
    for entry in item.get("materials", []):
        drive = entry.get("driveFile", {}).get("driveFile")
        if drive and drive.get("id"):
            result.append({"tipo": "drive", "id": drive["id"], "nome": drive.get("title"), "link": drive.get("alternateLink"), "possivel_pdf": drive.get("title", "").lower().endswith(".pdf")})
        for key, url in (("link", "url"), ("youtubeVideo", "alternateLink"), ("form", "formUrl")):
            if key in entry:
                value = entry[key]
                result.append({"tipo": key, "nome": value.get("title"), "link": value.get(url), "id": value.get("id")})
    return result


class Materials:
    def __init__(self, google, courses, activities=None):
        self.google, self.courses = google, courses
        self.activities = activities

    async def list(self, course_id, size=50, token=None, archived=False, kind="courseWorkMaterials", checked=False):
        identifier(course_id)
        page_params(size, token)
        course = None if checked else await self.courses.detail(course_id, archived)
        if kind == "courseWork" and self.activities is not None:
            return await self.activities.list(course_id, size, token, archived)
        params = {"pageSize": size, "orderBy": "updateTime desc"}
        if token:
            params["pageToken"] = token
        state = {"courseWorkMaterials": "courseWorkMaterialStates", "announcements": "announcementStates", "courseWork": "courseWorkStates"}[kind]
        params[state] = "PUBLISHED"
        data = await self.google.get(f"courses/{course_id}/{kind}", params)
        key = {"courseWorkMaterials": "courseWorkMaterial", "announcements": "announcements", "courseWork": "courseWork"}[kind]
        items = [{"id": i["id"], "disciplina_id": course_id, "titulo": i.get("title"), "descricao": i.get("description", ""), "texto": i.get("text", ""), "criado_em": i.get("creationTime"), "atualizado_em": i.get("updateTime"), "link": i.get("alternateLink"), "anexos": attachments(i), "prazo_data": i.get("dueDate"), "prazo_hora_utc": i.get("dueTime")} for i in data.get(key, [])]
        return {"disciplina": course, "itens": items, "proxima_pagina": data.get("nextPageToken"), "conteudo_nao_confiavel": True}

    async def publications(self, course_id, archived=False, course=None):
        course = course or await self.courses.detail(course_id, archived)
        for kind, origin in (("courseWorkMaterials", "material"), ("courseWork", "atividade"), ("announcements", "aviso")):
            token, seen = None, set()
            while True:
                if kind == "courseWork" and self.activities is not None:
                    data = await self.activities.list(course_id, 50, token, archived, course=course)
                else:
                    data = await self.list(course_id, 50, token, archived, kind=kind, checked=True)
                for item in data["itens"]:
                    yield course, {**item, "origem": origin}
                token = data["proxima_pagina"]
                if not token:
                    break
                if token in seen:
                    raise ServiceError("paginacao_google", "O Google repetiu um cursor.")
                seen.add(token)

    async def files(self, course_id, size=50, token=None, archived=False):
        page_params(size, token)
        files = {}
        course = await self.courses.detail(course_id, archived)
        async for _, item in self.publications(course_id, archived, course):
            for a in item["anexos"]:
                if a["tipo"] == "drive":
                    record = files.setdefault(a["id"], {**a, "arquivo_id": a["id"], "materiais_ids": [], "disciplina_id": course_id, "origens": [], "status_acesso": "nao_verificado", "conteudo_lido": False})
                    origin = {"origem": item["origem"], "publicacao_id": item["id"], "link_original": item.get("link")}
                    if origin not in record["origens"]:
                        record["origens"].append(origin)
                    if item["origem"] == "material" and item["id"] not in record["materiais_ids"]:
                        record["materiais_ids"].append(item["id"])
        rows = sorted(files.values(), key=lambda a: a["id"])
        fingerprint = hashlib.sha256(json.dumps([course_id, archived, rows], sort_keys=True).encode()).hexdigest()
        offset = 0
        if token:
            try:
                cursor = json.loads(base64.urlsafe_b64decode(token))
                offset = cursor["offset"]
                if cursor["hash"] != fingerprint or type(offset) is not int or not 0 <= offset <= len(rows):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise ServiceError("paginacao_invalida", "Cursor inválido ou publicações alteradas; reinicie a listagem.", 422) from None
        more = base64.urlsafe_b64encode(json.dumps({"offset": offset + size, "hash": fingerprint}).encode()).decode() if offset + size < len(rows) else None
        return {"disciplina": course, "arquivos": rows[offset:offset + size], "proxima_pagina": more, "total_arquivos": len(rows), "observacao": "Anexos de materiais, atividades e avisos, sem duplicações; metadados não comprovam download. A listagem reconsulta as fontes a cada página."}

    async def linked_file(self, course_id, file_id, archived=False):
        identifier(file_id)
        async for course, item in self.publications(course_id, archived):
            for a in item["anexos"]:
                if a.get("tipo") == "drive" and a.get("id") == file_id:
                    return course, a, item
        raise ServiceError("arquivo_nao_vinculado", "Arquivo não encontrado nos materiais, atividades ou avisos publicados desta turma.", 404)

    async def search(self, query, course_id=None, course_offset=0, token=None, archived=False):
        if not normalize(query) or len(query) > 180 or course_offset < 0:
            raise ServiceError("busca_invalida", "Informe palavra-chave de até 180 caracteres e um deslocamento válido.", 422)
        courses = [await self.courses.detail(course_id, archived)] if course_id else sorted(await self.courses.all(archived), key=lambda c: c["id"])
        if course_offset >= len(courses):
            return {"resultados": [], "continuacao": None, "escopo": "títulos e descrições; PDFs ainda não lidos"}
        course = courses[course_offset]
        data = await self.list(course["id"], 50, token, archived, checked=True)
        results = [{**i, "disciplina": course} for i in data["itens"] if normalize(query) in normalize((i["titulo"] or "") + " " + i["descricao"])]
        more = {"disciplina_offset": course_offset, "pagina": data["proxima_pagina"]} if data["proxima_pagina"] else ({"disciplina_offset": course_offset + 1, "pagina": None} if course_offset + 1 < len(courses) else None)
        return {"resultados": results, "disciplina_consultada": course, "continuacao": more, "escopo": "títulos e descrições; PDFs ainda não lidos"}
