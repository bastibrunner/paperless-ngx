from collections.abc import Generator

import pytest

from paperless_marker.parsers import MarkerDocumentParser
from paperless_marker.parsers import reset_marker_converter_cache_for_testing


@pytest.fixture()
def marker_parser() -> Generator[MarkerDocumentParser, None, None]:
    reset_marker_converter_cache_for_testing()
    parser = MarkerDocumentParser(logging_group=None)
    try:
        yield parser
    finally:
        parser.cleanup()
        reset_marker_converter_cache_for_testing()
