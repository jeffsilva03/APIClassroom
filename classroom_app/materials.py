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

    async def files(self, course_id, size=50, token=None, archived=False):
        data = await self.list(course_id, size, token, archived)
        files = {}
        for item in data["itens"]:
            for a in item["anexos"]:
                if a["tipo"] == "drive":
                    record = files.setdefault(a["id"], {**a, "materiais_ids": [], "disciplina_id": course_id})
                    record["materiais_ids"].append(item["id"])
        return {"disciplina": data["disciplina"], "arquivos": list(files.values()), "proxima_pagina": data["proxima_pagina"], "observacao": "Metadados de anexos; o conteúdo ainda não foi lido. O MIME é confirmado na leitura."}

    async def linked_file(self, course_id, file_id, archived=False):
        identifier(file_id)
        course = await self.courses.detail(course_id, archived)
        token, seen = None, set()
        while True:
            data = await self.list(course_id, 100, token, archived, checked=True)
            for item in data["itens"]:
                for a in item["anexos"]:
                    if a.get("tipo") == "drive" and a.get("id") == file_id:
                        return course, a, item
            token = data["proxima_pagina"]
            if not token:
                break
            if token in seen:
                raise ServiceError("paginacao_google", "O Google repetiu um cursor.")
            seen.add(token)
        if self.activities is not None:
            token, seen = None, set()
            while True:
                data = await self.activities.list(course_id, 50, token, archived, course=course)
                for item in data["itens"]:
                    for attachment in item["anexos"]:
                        if attachment.get("tipo") == "drive" and attachment.get("id") == file_id:
                            return course, attachment, item
                token = data["proxima_pagina"]
                if not token:
                    break
                if token in seen:
                    raise ServiceError("paginacao_google", "O Google repetiu um cursor de atividades.")
                seen.add(token)
        raise ServiceError("arquivo_nao_vinculado", "Arquivo não encontrado nos materiais ou atividades publicados desta turma.", 404)

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
