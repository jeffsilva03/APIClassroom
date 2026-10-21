import asyncio
import json
import os
import subprocess
import sys

from .courses import normalize
from .errors import ServiceError


class Documents:
    def __init__(self, google, materials, settings):
        self.google, self.materials, self.settings = google, materials, settings
        self.semaphore = asyncio.Semaphore(2)

    async def read(self, course_id, file_id, start=1, end=None, offset=0, archived=False):
        end = end if end is not None else start + self.settings.max_pages - 1
        if start < 1 or end < start or end - start + 1 > self.settings.max_pages or not 0 <= offset <= 2000000:
            raise ServiceError("paginas_invalidas", "Solicite de 1 a 5 páginas por leitura e offset entre 0 e 2000000.", 422)
        course, attachment, material = await self.materials.linked_file(course_id, file_id, archived)
        meta = await self.google.get(f"files/{file_id}", {"fields": "id,name,mimeType,size,webViewLink,capabilities(canDownload)"}, kind="drive")
        if meta.get("mimeType") != "application/pdf":
            raise ServiceError("tipo_invalido", "O arquivo selecionado não é um PDF.", 415)
        if meta.get("capabilities", {}).get("canDownload") is False:
            raise ServiceError("download_proibido", "A conta não tem permissão para baixar este arquivo.", 403)
        if int(meta.get("size", 0)) > self.settings.max_pdf_bytes:
            raise ServiceError("pdf_grande", "PDF excede o limite de 20 MB.", 413)
        async with self.semaphore:
            data = await self.google.download(file_id)
            try:
                # O processo recebe somente o PDF por stdin e um ambiente sem segredos.
                env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG"}}
                worker = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "classroom_app.pdf_worker", str(start), str(end), str(offset), str(self.settings.max_chars)], input=data, capture_output=True, timeout=15, env=env)
                result = json.loads(worker.stdout) if worker.returncode == 0 else {"erro": "pdf_limite_processamento"}
            except (subprocess.TimeoutExpired, ValueError):
                raise ServiceError("pdf_limite_processamento", "PDF excedeu o limite de processamento ou não pôde ser interpretado.", 422) from None
        if "erro" in result:
            raise ServiceError(result["erro"], "Não foi possível ler o intervalo solicitado. Verifique páginas, criptografia ou integridade do PDF.", 422)
        return {**result, "disciplina": course, "arquivo_id": file_id, "arquivo": meta.get("name"), "link": meta.get("webViewLink") or attachment.get("link"), "material_link": material.get("link"), "conteudo_nao_confiavel": True}

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
