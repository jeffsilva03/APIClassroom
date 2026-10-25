"""Extração isolada, sem acesso a credenciais ou persistência de documentos."""
import io
import json
import sys

from pypdf import PdfReader


def extract(data, start, end, offset, limit=18000):
    if not data:
        raise ValueError("pdf_vazio")
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise ValueError("pdf_criptografado")
    total = len(reader.pages)
    if total == 0:
        raise ValueError("pdf_vazio")
    if total > 1500:
        raise ValueError("pdf_paginas_demais")
    if start > total:
        raise ValueError("pagina_inexistente")
    pages, available, next_part = [], limit, None
    for number in range(start, min(end, total) + 1):
        text = reader.pages[number - 1].extract_text() or ""
        pos = offset if number == start else 0
        if pos > len(text):
            raise ValueError("offset_invalido")
        part = text[pos:pos + available]
        pages.append({"pagina": number, "offset": pos, "texto": part, "sem_texto_extraivel": not text.strip()})
        available -= len(part)
        if pos + len(part) < len(text):
            next_part = {"pagina_inicio": number, "offset": pos + len(part)}
            break
        if available == 0:
            next_part = {"pagina_inicio": number + 1, "offset": 0} if number < total else None
            break
    if next_part is None and min(end, total) < total:
        next_part = {"pagina_inicio": min(end, total) + 1, "offset": 0}
    return {"total_paginas": total, "paginas": pages, "continuacao": next_part, "truncado": next_part is not None, "caracteres_retornados": sum(len(p["texto"]) for p in pages), "observacao": "Páginas sem texto podem exigir OCR, não disponível nesta integração."}


if __name__ == "__main__":
    if sys.platform != "win32":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    try:
        result = extract(sys.stdin.buffer.read(20 * 1024 * 1024 + 1), *map(int, sys.argv[1:]))
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else "pdf_invalido"
        result = {"erro": code if code in {"pdf_vazio", "pdf_criptografado", "pdf_paginas_demais", "pagina_inexistente", "offset_invalido"} else "pdf_invalido"}
    print(json.dumps(result, ensure_ascii=True))
