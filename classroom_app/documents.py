import asyncio
import json
import os
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from .courses import identifier, normalize
from .errors import ServiceError


ZIP_MIMES = {"application/zip", "application/x-zip-compressed"}


class Documents:
    def __init__(self, google, materials, settings):
        self.google, self.materials, self.settings = google, materials, settings
        self.semaphore = asyncio.Semaphore(2)

    async def resolve(self, course_id, file_id, archived=False, binding=None):
        course, attachment, publication = binding or await self.materials.linked_file(course_id, file_id, archived)
        target, key = file_id, None
        url = urlsplit(attachment.get("link") or "")
        if url.scheme == "https" and url.hostname in {"drive.google.com", "docs.google.com"}:
            candidate = parse_qs(url.query).get("resourcekey", [""])[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{1,180}", candidate):
                key = candidate
        for depth in range(2):
            kwargs = {"resource_key": key} if key else {}
            try:
                meta = await self.google.get(f"files/{target}", {"fields": "id,name,mimeType,size,webViewLink,capabilities(canDownload),shortcutDetails,version,md5Checksum", "supportsAllDrives": "true"}, kind="drive", **kwargs)
            except ServiceError as exc:
                exc.context.update(link_original=attachment.get("link"), publicacao_link=publication.get("link"))
                raise
            if meta.get("mimeType") != "application/vnd.google-apps.shortcut":
                return course, attachment, publication, meta, target, key
            if depth:
                raise ServiceError("atalho_indisponivel", "Destino do atalho não pode ser resolvido com segurança.", 403)
            details = meta.get("shortcutDetails", {})
            target = identifier(details.get("targetId", ""))
            key = details.get("targetResourceKey")
            if key and not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", key):
                raise ServiceError("atalho_indisponivel", "Chave de recurso inválida.", 422)

    def preflight(self, meta, mimes, limit, code="arquivo_grande", source=None):
        error = None
        if meta.get("mimeType") not in mimes:
            error = ServiceError("tipo_invalido", "Tipo MIME não suportado para esta leitura.", 415)
        elif meta.get("capabilities", {}).get("canDownload") is False:
            error = ServiceError("download_proibido", "A conta pode consultar metadados, mas não baixar este arquivo. Use o link original.", 403)
        elif int(meta.get("size", 0)) > limit:
            error = ServiceError(code, "Arquivo excede o limite de tamanho.", 413)
        if error:
            error.context.update(source or {})
            raise error

    async def download(self, target, key, source, limit=None):
        try:
            kwargs = {"resource_key": key} if key else {}
            if limit is not None:
                kwargs["max_bytes"] = limit
            return await self.google.download(target, **kwargs)
        except ServiceError as exc:
            exc.context.update(source)
            raise

    async def inspect(self, course_id, file_id, archived=False):
        course, attachment, publication = await self.materials.linked_file(course_id, file_id, archived)
        result = {"arquivo_id": file_id, "nome": attachment.get("nome"), "disciplina_id": course_id, "origem": publication.get("origem"), "publicacao_id": publication["id"], "link_original": attachment.get("link"), "publicacao_link": publication.get("link"), "conteudo_lido": False, "status_acesso": "nao_verificado"}
        try:
            _, _, _, meta, target, _ = await self.resolve(course_id, file_id, archived, (course, attachment, publication))
            mime = meta.get("mimeType")
            result.update(nome=meta.get("name"), tipo=mime, tamanho=meta.get("size"), destino_id=target, leitura_disponivel="pdf" if mime == "application/pdf" else "zip" if mime in ZIP_MIMES else None)
            if meta.get("capabilities", {}).get("canDownload") is False:
                raise ServiceError("download_proibido", "Metadados acessíveis; download proibido para esta conta.", 403)
            result["observacao"] = "Metadados consultados; download ainda não verificado."
        except ServiceError as exc:
            result.update(status_acesso="falha_temporaria" if exc.status >= 500 or exc.status == 429 else "download_proibido" if exc.code == "download_proibido" else "indisponivel", diagnostico=exc.payload()["erro"])
        return result

    async def zip(self, course_id, file_id, operation, directory=None, continuation=None, path=None, offset=0, archived=False, name=None):
        from .zip_worker import safe_path
        if offset < 0 or offset > self.settings.max_zip_file or (directory and len(directory) > 1024) or (name and len(name) > 180) or len(continuation or "") > 2048:
            raise ServiceError("parametro_zip", "Filtro ou offset inválido.", 422)
        if path:
            try:
                safe_path(path)
            except ValueError:
                raise ServiceError("caminho_zip_invalido", "Caminho relativo inválido.", 422) from None
        course, attachment, publication, meta, target, key = await self.resolve(course_id, file_id, archived)
        source = {"link_original": attachment.get("link"), "publicacao_link": publication.get("link")}
        self.preflight(meta, ZIP_MIMES, self.settings.max_zip_bytes, source=source)
        options = {"operation": operation, "directory": directory, "continuation": continuation, "path": path, "offset": offset, "name": name, "limit": self.settings.zip_chars, "max_bytes": self.settings.max_zip_bytes, "max_total": self.settings.max_zip_expanded, "max_entries": self.settings.max_zip_entries, "max_file": self.settings.max_zip_file, "max_ratio": self.settings.max_zip_ratio}
        async with self.semaphore:
            data = await self.download(target, key, source, self.settings.max_zip_bytes)
            env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG"}}
            env["PYTHONPATH"] = os.pathsep.join(sys.path)
            try:
                worker = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "classroom_app.zip_worker", json.dumps(options)], input=data, capture_output=True, timeout=self.settings.zip_seconds, env=env)
                result = json.loads(worker.stdout) if worker.returncode == 0 else {"erro": "zip_limite_processamento"}
            except (subprocess.TimeoutExpired, ValueError):
                raise ServiceError("zip_limite_processamento", "ZIP excedeu o tempo ou recursos disponíveis.", 422) from None
        if "erro" in result:
            raise ServiceError(result["erro"], "ZIP recusado: " + result["erro"] + ". Consulte os limites e tipos suportados.", 422)
        return {**result, "arquivo_id": file_id, "arquivo": meta.get("name"), "disciplina": course, **source, "status_acesso": "acessivel", "conteudo_nao_confiavel": True}

    async def read(self, course_id, file_id, start=1, end=None, offset=0, archived=False):
        end = end if end is not None else start + self.settings.max_pages - 1
        if start < 1 or end < start or end - start + 1 > self.settings.max_pages or not 0 <= offset <= 2000000:
            raise ServiceError("paginas_invalidas", "Solicite de 1 a 5 páginas por leitura e offset entre 0 e 2000000.", 422)
        course, attachment, material, meta, target, key = await self.resolve(course_id, file_id, archived)
        source = {"link_original": attachment.get("link"), "publicacao_link": material.get("link")}
        self.preflight(meta, {"application/pdf"}, self.settings.max_pdf_bytes, "pdf_grande", source)
        async with self.semaphore:
            data = await self.download(target, key, source)
            if len(data) > self.settings.max_pdf_bytes:
                raise ServiceError("pdf_grande", "PDF excede o limite de download.", 413)
            try:
                # O processo recebe somente o PDF por stdin e um ambiente sem segredos.
                env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG"}}
                env["PYTHONPATH"] = os.pathsep.join(sys.path)
                worker = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "classroom_app.pdf_worker", str(start), str(end), str(offset), str(self.settings.max_chars)], input=data, capture_output=True, timeout=15, env=env)
                result = json.loads(worker.stdout) if worker.returncode == 0 else {"erro": "pdf_limite_processamento"}
            except (subprocess.TimeoutExpired, ValueError):
                raise ServiceError("pdf_limite_processamento", "PDF excedeu o limite de processamento ou não pôde ser interpretado.", 422) from None
        if "erro" in result:
            messages = {"pdf_vazio": "PDF vazio, sem páginas.", "pdf_invalido": "PDF corrompido ou inválido.", "pdf_criptografado": "PDF criptografado; leitura indisponível.", "pagina_inexistente": "Página solicitada não existe.", "offset_invalido": "Offset excede o texto da página.", "pdf_paginas_demais": "PDF excede 1500 páginas."}
            raise ServiceError(result["erro"], messages.get(result["erro"], "PDF excedeu o limite de processamento."), 422)
        return {**result, "disciplina": course, "arquivo_id": file_id, "arquivo": meta.get("name"), "link": meta.get("webViewLink") or attachment.get("link"), "material_link": material.get("link"), "status_acesso": "acessivel", "conteudo_lido": True, "conteudo_nao_confiavel": True}

    async def search(self, course_id, file_id, query, start=1, offset=0, archived=False):
        if not normalize(query) or len(query) > 180:
            raise ServiceError("busca_invalida", "Informe uma palavra-chave de até 180 caracteres.", 422)
        data = await self.read(course_id, file_id, start, None, offset, archived)
        matches = []
        for page in data["paginas"]:
            # Blocos sobrepostos preservam contexto; o cursor permite varrer todo o documento.
            text = page["texto"]
            for index in range(0, len(text), 600):
                excerpt = text[max(0, index - 180):index + 780]
                if normalize(query) in normalize(excerpt):
                    matches.append({"pagina": page["pagina"], "trecho": excerpt})
                    if len(matches) >= 12:
                        break
        return {k: v for k, v in data.items() if k != "paginas"} | {"resultados": matches, "paginas_consultadas": [p["pagina"] for p in data["paginas"]], "observacao": "Busca apenas nas páginas consultadas. Siga a continuação para pesquisar o restante do PDF."}
