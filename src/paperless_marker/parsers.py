from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone
from paperless_tesseract.parsers import post_process_text
from PIL import Image

from documents.parsers import DocumentParser
from documents.parsers import ParseError
from documents.parsers import get_default_thumbnail
from documents.parsers import make_thumbnail_from_pdf
from documents.utils import copy_file_with_basic_stats
from paperless_marker.mime import MARKER_IMAGE_MIME_TYPES
from paperless_marker.mime import MARKER_OFFICE_MIME_TYPES

logger = logging.getLogger("paperless.parsing.marker")

_converter_cache: tuple[Any, str | None] | None = None


def reset_marker_converter_cache_for_testing() -> None:
    global _converter_cache
    _converter_cache = None


def _get_pdf_converter() -> Any:
    global _converter_cache
    config_path = getattr(settings, "MARKER_CONFIG_JSON", None) or None
    cache_key = config_path or ""

    if _converter_cache is not None and _converter_cache[1] == cache_key:
        return _converter_cache[0]

    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
    except ImportError as err:
        msg = (
            "marker-pdf is not installed. Install it in the same environment as Paperless "
            '(see "Marker" under Optional Services in the configuration documentation), '
            'for example: pip install "marker-pdf>=1.10.2,<2"'
        )
        raise ParseError(msg) from err

    if config_path:
        cfg_file = Path(config_path)
        if not cfg_file.is_file():
            msg = f"PAPERLESS_MARKER_CONFIG_JSON file not found: {config_path}"
            raise ParseError(msg)
        from marker.config.parser import ConfigParser

        with cfg_file.open(encoding="utf-8") as f:
            config_dict = json.load(f)
        config_parser = ConfigParser(config_dict)
        converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
            llm_service=config_parser.get_llm_service(),
        )
    else:
        converter = PdfConverter(artifact_dict=create_model_dict())

    _converter_cache = (converter, cache_key)
    return converter


def _extract_date_from_rendered(rendered: Any) -> datetime.datetime | None:
    meta = getattr(rendered, "metadata", None)
    if meta is None:
        return None
    if hasattr(meta, "model_dump"):
        meta = meta.model_dump()
    if not isinstance(meta, dict):
        return None
    for key in ("created", "modified", "date", "creation_date"):
        raw = meta.get(key)
        if raw is None:
            continue
        if isinstance(raw, datetime.datetime):
            dt = raw
        elif isinstance(raw, datetime.date):
            dt = datetime.datetime.combine(raw, datetime.time.min)
        else:
            continue
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    return None


class MarkerDocumentParser(DocumentParser):
    """
    Parse documents using datalab-to/marker (in-process PdfConverter).
    """

    logging_name = "paperless.parsing.marker"

    def get_settings(self) -> None:
        return None

    def get_page_count(self, document_path, mime_type):
        if mime_type == "application/pdf":
            try:
                import pikepdf

                with pikepdf.Pdf.open(document_path) as pdf:
                    return len(pdf.pages)
            except Exception:
                logger.debug("Could not read PDF page count", exc_info=True)
        return None

    def parse(self, document_path: Path, mime_type: str, file_name=None) -> None:
        self.progress(0, 1)
        try:
            from marker.output import text_from_rendered
        except ImportError as err:
            msg = (
                "marker-pdf is not installed. Install it in the same environment as Paperless "
                '(see "Marker" under Optional Services in the configuration documentation), '
                'for example: pip install "marker-pdf>=1.10.2,<2"'
            )
            raise ParseError(msg) from err

        try:
            converter = _get_pdf_converter()
            rendered = converter(str(document_path))
            text, _, _images = text_from_rendered(rendered)
        except ParseError:
            raise
        except Exception as err:
            logger.exception("Marker failed to parse %s", document_path)
            hint = ""
            if mime_type in MARKER_OFFICE_MIME_TYPES:
                hint = (
                    " For Office documents, install `marker-pdf[full]` and set "
                    "PAPERLESS_MARKER_OFFICE=YES."
                )
            raise ParseError(
                f"Marker failed to parse {document_path}: {err!s}.{hint}",
            ) from err

        raw = (text or "").strip()
        self.text = post_process_text(raw) or ""
        self.date = _extract_date_from_rendered(rendered)
        self.progress(1, 1)

    def get_thumbnail(
        self,
        document_path: Path,
        mime_type: str,
        file_name=None,
    ) -> Path:
        if mime_type == "application/pdf":
            return make_thumbnail_from_pdf(
                document_path,
                self.tempdir,
                self.logging_group,
            )
        if mime_type in MARKER_IMAGE_MIME_TYPES:
            return self._thumbnail_from_image(document_path)
        if mime_type in MARKER_OFFICE_MIME_TYPES:
            out_path = self.tempdir / "thumb.webp"
            copy_file_with_basic_stats(get_default_thumbnail(), out_path)
            return out_path
        out_path = self.tempdir / "thumb.webp"
        copy_file_with_basic_stats(get_default_thumbnail(), out_path)
        return out_path

    def _thumbnail_from_image(self, document_path: Path) -> Path:
        out_path = self.tempdir / "thumb.webp"
        try:
            with Image.open(document_path) as im:
                im = im.convert("RGB")
                im.thumbnail((500, 5000))
                im.save(out_path, format="WEBP")
        except Exception:
            logger.warning(
                "Could not build image thumbnail for %s, using default",
                document_path,
                exc_info=True,
            )
            copy_file_with_basic_stats(get_default_thumbnail(), out_path)
        return out_path

    def extract_metadata(self, document_path, mime_type):
        return []
