import builtins
from pathlib import Path
from unittest import mock

import pytest

from documents.parsers import ParseError
from paperless_marker.parsers import MarkerDocumentParser
from paperless_marker.parsers import reset_marker_converter_cache_for_testing

_real_import = builtins.__import__


@pytest.mark.django_db()
class TestMarkerParser:
    def test_parse_success(
        self,
        marker_parser: MarkerDocumentParser,
        tmp_path: Path,
    ) -> None:
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 minimal")

        rendered = object()
        with (
            mock.patch(
                "paperless_marker.parsers._get_pdf_converter",
            ) as mock_get_conv,
            mock.patch("marker.output.text_from_rendered") as mock_tfr,
        ):
            mock_get_conv.return_value = mock.Mock(return_value=rendered)
            mock_tfr.return_value = ("Line one\nLine two", [], [])

            marker_parser.parse(pdf, "application/pdf")

        assert marker_parser.text == "Line one\nLine two"
        mock_get_conv.return_value.assert_called_once_with(str(pdf))
        mock_tfr.assert_called_once_with(rendered)

    def test_parse_empty_text(
        self,
        marker_parser: MarkerDocumentParser,
        tmp_path: Path,
    ) -> None:
        pdf = tmp_path / "empty.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        rendered = object()
        with (
            mock.patch("paperless_marker.parsers._get_pdf_converter") as mock_get_conv,
            mock.patch("marker.output.text_from_rendered") as mock_tfr,
        ):
            mock_get_conv.return_value = mock.Mock(return_value=rendered)
            mock_tfr.return_value = (None, [], [])

            marker_parser.parse(pdf, "application/pdf")

        assert marker_parser.text == ""

    def test_parse_marker_failure(
        self,
        marker_parser: MarkerDocumentParser,
        tmp_path: Path,
    ) -> None:
        pdf = tmp_path / "bad.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with mock.patch("paperless_marker.parsers._get_pdf_converter") as mock_get_conv:
            mock_get_conv.return_value = mock.Mock(
                side_effect=RuntimeError("model OOM"),
            )

            with pytest.raises(ParseError, match="Marker failed"):
                marker_parser.parse(pdf, "application/pdf")

    def test_parse_import_error(
        self,
        marker_parser: MarkerDocumentParser,
        tmp_path: Path,
    ) -> None:
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "marker.output":
                raise ImportError("no marker")
            return _real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ParseError, match="marker-pdf is not installed"):
                marker_parser.parse(pdf, "application/pdf")

    def test_converter_cached(
        self,
        tmp_path: Path,
    ) -> None:
        pytest.importorskip("marker.converters.pdf")

        reset_marker_converter_cache_for_testing()
        pdf = tmp_path / "c.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        rendered = object()

        with (
            mock.patch("marker.converters.pdf.PdfConverter") as mock_pdf_cls,
            mock.patch("marker.models.create_model_dict", return_value={}),
            mock.patch("marker.output.text_from_rendered") as mock_tfr,
        ):
            mock_inst = mock.Mock(return_value=rendered)
            mock_pdf_cls.return_value = mock_inst
            mock_tfr.return_value = ("x", [], [])

            p1 = MarkerDocumentParser(logging_group=None)
            p2 = MarkerDocumentParser(logging_group=None)
            try:
                p1.parse(pdf, "application/pdf")
                p2.parse(pdf, "application/pdf")
            finally:
                p1.cleanup()
                p2.cleanup()

            mock_pdf_cls.assert_called_once()
        reset_marker_converter_cache_for_testing()

    def test_office_parse_error_includes_hint(
        self,
        marker_parser: MarkerDocumentParser,
        tmp_path: Path,
    ) -> None:
        docx = tmp_path / "a.docx"
        docx.write_bytes(b"PK\x03\x04fake")

        with mock.patch("paperless_marker.parsers._get_pdf_converter") as mock_get_conv:
            mock_get_conv.return_value = mock.Mock(
                side_effect=RuntimeError("unsupported"),
            )

            with pytest.raises(ParseError, match="marker-full"):
                marker_parser.parse(
                    docx,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )

    def test_thumbnail_office_uses_default(
        self,
        marker_parser: MarkerDocumentParser,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "x.docx"
        f.write_bytes(b"x")
        thumb = marker_parser.get_thumbnail(
            f,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert thumb.suffix == ".webp"
        assert thumb.is_file()
