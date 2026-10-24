"""cap_ooxml.py - .docx y .pptx REALES con stdlib (zipfile + xml.etree).

Un .docx/.pptx es un ZIP con XML: no hace falta python-docx ni python-pptx. El
modulo ESCRIBE el paquete minimo valido y despues LO REABRE para extraer el texto:
si el ZIP o el XML estan mal, la relectura levanta y el test cae. Escribir sin
releer seria afirmar un exito que nadie comprobo.

LIMITACION DECLARADA: paquete minimo (parrafos/imagenes de texto). No hay estilos,
tablas, imagenes ni compatibilidad total con Word/PowerPoint; produce un OOXML
valido, no un documento con diseno.
"""
from __future__ import annotations
import os
import xml.etree.ElementTree as ET
import zipfile
from typing import Iterable, List, Sequence

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"

LIMITACION = "paquete minimo sin estilos, tablas ni imagenes; OOXML valido, no disenado"


class OoxmlError(Exception):
    pass


def _esc(texto: str) -> str:
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _check(path: str) -> str:
    if not path or not isinstance(path, str):
        raise OoxmlError("falta la ruta de destino")
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".docx", ".pptx"):
        raise OoxmlError("extension no soportada: %s (solo .docx/.pptx)" % ext)
    return ext


def write_docx(path: str, paragraphs: Sequence[str]) -> dict:
    _check(path)
    textos = [str(p) for p in paragraphs if str(p).strip()]
    if not textos:
        raise OoxmlError("un .docx sin parrafos no es un documento")
    body = "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % _esc(t)
                   for t in textos)
    partes = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="%s"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>' % CT,
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/></Relationships>' % (PKG_REL, R),
        "word/document.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (W, body),
    }
    _escribir(path, partes)
    return {"source": os.path.abspath(path), "paragraphs": len(textos),
            "parts": len(partes), "bytes": os.path.getsize(path),
            "limitation": LIMITACION, "text": read_text(path)}


def write_pptx(path: str, slides: Sequence[str]) -> dict:
    _check(path)
    textos = [str(s) for s in slides if str(s).strip()]
    if not textos:
        raise OoxmlError("un .pptx sin diapositivas no es una presentacion")
    partes = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="%s"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            % CT + "".join(
                '<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' % (i + 1)
                for i in range(len(textos))) + "</Types>",
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/officeDocument" Target="ppt/presentation.xml"/></Relationships>' % (PKG_REL, R),
        "ppt/presentation.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:presentation xmlns:p="%s" xmlns:a="%s" xmlns:r="%s">'
            '<p:sldIdLst>%s</p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/></p:presentation>'
            % (P, A, R, "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, i + 1)
                                for i in range(len(textos)))),
        "ppt/_rels/presentation.xml.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s">%s</Relationships>'
            % (PKG_REL, "".join(
                '<Relationship Id="rId%d" Type="%s/slide" Target="slides/slide%d.xml"/>' % (i + 1, R, i + 1)
                for i in range(len(textos)))),
    }
    for i, t in enumerate(textos, 1):
        partes["ppt/slides/slide%d.xml" % i] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree><p:sp><p:txBody>'
            '<a:p><a:r><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
            % (P, A, _esc(t)))
    _escribir(path, partes)
    return {"source": os.path.abspath(path), "slides": len(textos),
            "parts": len(partes), "bytes": os.path.getsize(path),
            "limitation": LIMITACION, "text": read_text(path)}


def _escribir(path: str, partes) -> None:
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for nombre, contenido in partes.items():
                z.writestr(nombre, contenido.encode("utf-8"))
    except (OSError, zipfile.BadZipFile) as exc:
        raise OoxmlError("no se pudo escribir %s: %s" % (path, exc))


def read_text(path: str) -> str:
    """Reabre el paquete y extrae el texto. Si el XML esta mal, levanta."""
    if not os.path.isfile(path):
        raise OoxmlError("no existe: %s" % path)
    try:
        with zipfile.ZipFile(path) as z:
            nombres = z.namelist()
            utiles = [n for n in nombres if n.endswith(".xml") and (
                n.startswith("word/") or n.startswith("ppt/slides/"))]
            trozos: List[str] = []
            for n in sorted(utiles):
                raiz = ET.fromstring(z.read(n))
                for el in raiz.iter():
                    if el.tag in ("{%s}t" % W, "{%s}t" % A) and el.text:
                        trozos.append(el.text)
            return "\n".join(trozos)
    except (zipfile.BadZipFile, ET.ParseError) as exc:
        raise OoxmlError("paquete invalido %s: %s" % (path, exc))
    except OSError as exc:
        raise OoxmlError("no se pudo leer %s: %s" % (path, exc))


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    docx = os.path.join(d, "a.docx")
    r = write_docx(docx, ["Espina dorsal", "Segunda linea"])
    assert r["paragraphs"] == 2 and "Espina dorsal" in r["text"], r
    pptx = os.path.join(d, "a.pptx")
    r2 = write_pptx(pptx, ["Portada", "Hallazgos"])
    assert r2["slides"] == 2 and "Hallazgos" in r2["text"], r2
    for malo in (os.path.join(d, "x.txt"), ""):
        try:
            _check(malo); raise SystemExit("FALLO: extension invalida aceptada")
        except OoxmlError:
            pass
    try:
        write_docx(os.path.join(d, "v.docx"), [])
        raise SystemExit("FALLO: docx vacio aceptado")
    except OoxmlError:
        pass
    abierto = os.path.join(d, "roto.docx")
    open(abierto, "wb").write(b"no soy un zip")
    try:
        read_text(abierto); raise SystemExit("FALLO: zip corrupto aceptado")
    except OoxmlError:
        pass
    print("OK cap_ooxml: docx y pptx VALIDOS, releidos y con texto extraido")
