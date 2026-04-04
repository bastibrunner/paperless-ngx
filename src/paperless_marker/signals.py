from paperless_marker.mime import MARKER_IMAGE_MIME_TYPES
from paperless_marker.mime import MARKER_OFFICE_MIME_TYPES


def get_parser(*args, **kwargs):
    from paperless_marker.parsers import MarkerDocumentParser

    return MarkerDocumentParser(*args, **kwargs)


def marker_consumer_declaration(sender, **kwargs):
    from django.conf import settings

    mime_types: dict[str, str] = {"application/pdf": ".pdf"}
    if settings.MARKER_EXTENDED:
        mime_types.update(MARKER_IMAGE_MIME_TYPES)
    if settings.MARKER_OFFICE:
        mime_types.update(MARKER_OFFICE_MIME_TYPES)

    return {
        "parser": get_parser,
        "weight": 15,
        "mime_types": mime_types,
    }
