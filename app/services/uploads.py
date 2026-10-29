"""사용자가 가진 DRM 없는 파일(EPUB · PDF · TXT)을 본문 텍스트로 바꾼다.

올린 파일의 본문은 올린 사람만 읽는다(공유되는 것은 위치·진행률·반응뿐). DRM 해제는 하지 않는다.
"""

import hashlib
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.sources.base import SourceError
from app.sources.wikisource import html_to_text

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# 압축 폭탄·거대 PDF로 서버를 멈추지 못하게 하는 상한
MAX_UNZIPPED_BYTES = 80 * 1024 * 1024
MAX_EPUB_ENTRIES = 3000
MAX_PDF_PAGES = 2000
MAX_TEXT_CHARS = 6_000_000
ALLOWED = (".epub", ".pdf", ".txt")


@dataclass(frozen=True)
class ParsedBook:
    title: str
    author: str | None
    language: str | None
    text: str


def fingerprint(text: str) -> str:
    """공백·문장부호 차이를 무시한 본문 지문. 같은 책의 다른 파일도 대개 같은 값이 나온다."""
    normalized = re.sub(r"[\W_]+", "", text).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SourceError("텍스트 인코딩을 알 수 없어요 (UTF-8 또는 CP949만 지원)")


def _guess_language(text: str) -> str | None:
    sample = text[:4000]
    hangul = len(re.findall(r"[가-힣]", sample))
    latin = len(re.findall(r"[A-Za-z]", sample))
    if hangul + latin == 0:
        return None
    return "ko" if hangul >= latin else "en"


def parse_txt(data: bytes) -> tuple[str, None, str]:
    text = _decode(data).replace("\r\n", "\n")
    # 하드랩된 줄은 잇고, 빈 줄은 문단 경계로 유지
    paragraphs = (" ".join(p.split()) for p in re.split(r"\n\s*\n", text))
    return "", None, "\n\n".join(p for p in paragraphs if p)


def parse_epub(data: bytes) -> tuple[str, str | None, str]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
        if len(infos) > MAX_EPUB_ENTRIES or sum(i.file_size for i in infos) > MAX_UNZIPPED_BYTES:
            raise SourceError("파일이 너무 커요 (압축을 풀면 80MB를 넘어요)")
        if any(n.endswith("encryption.xml") for n in z.namelist()):
            raise SourceError("DRM이 걸린 EPUB은 열 수 없어요")
        container = BeautifulSoup(z.read("META-INF/container.xml"), "xml")
        opf_path = container.find("rootfile")["full-path"]
        opf = BeautifulSoup(z.read(opf_path), "xml")
    except (zipfile.BadZipFile, KeyError, TypeError) as e:
        raise SourceError("올바른 EPUB 파일이 아니에요") from e

    title = opf.find("dc:title") or opf.find("title")
    author = opf.find("dc:creator") or opf.find("creator")
    base = posixpath.dirname(opf_path)
    manifest = {i["id"]: i["href"] for i in opf.find_all("item") if i.get("id") and i.get("href")}
    parts, seen = [], set()
    for ref in opf.find_all("itemref"):
        href = manifest.get(ref.get("idref", ""))
        if not href or href in seen:  # 같은 장을 여러 번 넣은 spine은 한 번만
            continue
        seen.add(href)
        try:
            html = z.read(posixpath.normpath(posixpath.join(base, href)))
        except KeyError:
            continue
        if body := html_to_text(html.decode("utf-8", errors="replace")):
            parts.append(body)
    return (
        title.get_text(strip=True) if title else "",
        author.get_text(strip=True) if author else None,
        "\n\n".join(parts),
    )


def parse_pdf(data: bytes) -> tuple[str, str | None, str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise SourceError("암호가 걸린 PDF는 열 수 없어요")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise SourceError(f"쪽수가 너무 많아요 (최대 {MAX_PDF_PAGES}쪽)")
        pages, size = [], 0
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            size += len(pages[-1])
            if size > MAX_TEXT_CHARS:
                raise SourceError("본문이 너무 길어요")
    except PdfReadError as e:
        raise SourceError("올바른 PDF 파일이 아니에요") from e
    meta = reader.metadata
    # PDF는 줄마다 끊겨 나오므로 빈 줄 기준 문단으로 다시 잇는다
    _, _, text = parse_txt("\n\n".join(pages).encode())
    return (meta.title or "") if meta else "", (meta.author if meta else None), text


def parse_upload(filename: str, data: bytes, max_bytes: int = MAX_UPLOAD_BYTES) -> ParsedBook:
    ext = posixpath.splitext(filename.lower())[1]
    if ext not in ALLOWED:
        raise SourceError("EPUB, PDF, TXT 파일만 올릴 수 있어요")
    if len(data) > max_bytes:
        raise SourceError(f"파일이 너무 커요 (최대 {max_bytes // (1024 * 1024)}MB)")
    title, author, text = {".epub": parse_epub, ".pdf": parse_pdf, ".txt": parse_txt}[ext](data)
    if len(text) > MAX_TEXT_CHARS:
        raise SourceError("본문이 너무 길어요")
    if len(text.strip()) < 50:
        raise SourceError("본문을 찾지 못했어요. 스캔한 이미지 PDF는 지원하지 않아요")
    fallback = posixpath.splitext(posixpath.basename(filename))[0]
    return ParsedBook(
        title=(title or fallback)[:500],
        author=(author or None) and author[:300],
        language=_guess_language(text),
        text=text,
    )
