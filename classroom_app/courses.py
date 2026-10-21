import re
import unicodedata

from .errors import ServiceError


def normalize(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()).split())


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", value):
        raise ServiceError("identificador_invalido", "Identificador inválido.", 422)
    return value


def page_params(size, token):
    if not 1 <= size <= 100 or len(token or "") > 2048:
        raise ServiceError("paginacao_invalida", "Use tamanho de página de 1 a 100 e um cursor válido.", 422)


class Courses:
    def __init__(self, google, settings):
        self.google, self.settings = google, settings

    def decorate(self, item):
        aliases = list(self.settings.aliases["course_ids"].get(item["id"], []))
        name = normalize(item["name"])
        for pattern, values in self.settings.aliases["name_patterns"].items():
            if pattern in name:
                aliases.extend(values)
        return {"id": item["id"], "nome": item["name"], "status": item.get("courseState"), "aliases": sorted(set(aliases)), "link": item.get("alternateLink"), "descricao": item.get("description", ""), "atualizado_em": item.get("updateTime")}

    async def list(self, archived=False, size=50, token=None):
        page_params(size, token)
        params = {"pageSize": size, "courseStates": ["ACTIVE", "ARCHIVED"] if archived else "ACTIVE"}
        if token:
            params["pageToken"] = token
        data = await self.google.get("courses", params)
        items = {c["id"]: self.decorate(c) for c in data.get("courses", []) if c.get("courseState") in (("ACTIVE", "ARCHIVED") if archived else ("ACTIVE",))}
        return {"disciplinas": list(items.values()), "proxima_pagina": data.get("nextPageToken"), "inclui_arquivadas": archived}

    async def all(self, archived=False):
        items, token, seen = {}, None, set()
        while True:
            data = await self.list(archived, 100, token)
            items.update({c["id"]: c for c in data["disciplinas"]})
            token = data["proxima_pagina"]
            if not token:
                return list(items.values())
            if token in seen:
                raise ServiceError("paginacao_google", "O Google repetiu um cursor de paginação.")
            seen.add(token)

    async def search(self, query, archived=False):
        key = normalize(query)
        if not key or len(query) > 180:
            raise ServiceError("busca_invalida", "Informe o nome ou alias da disciplina (até 180 caracteres).", 422)
        matches = []
        for c in await self.all(archived):
            names = [c["nome"], *c["aliases"]]
            if query == c["id"] or any(key in normalize(n) for n in names):
                matches.append(c)
        matches.sort(key=lambda c: (c["status"] != "ACTIVE", normalize(c["nome"])))
        return {"disciplinas": matches, "ambigua": len(matches) > 1, "orientacao": "Se houver mais de uma turma, peça ao usuário para escolher pelo ID."}

    async def detail(self, course_id, archived=False):
        identifier(course_id)
        # A listagem confirma matrícula e estado, inclusive se courses.get permitir outro vínculo.
        for c in await self.all(archived):
            if c["id"] == course_id:
                return c
        raise ServiceError("disciplina_indisponivel", "Disciplina não encontrada entre as turmas permitidas. Para arquivadas, solicite inclusão explícita.", 404)
