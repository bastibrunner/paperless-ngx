from django.apps import AppConfig


class PaperlessMarkerConfig(AppConfig):
    name = "paperless_marker"

    def ready(self) -> None:
        from django.conf import settings

        from documents.signals import document_consumer_declaration
        from paperless_marker.signals import marker_consumer_declaration

        super().ready()
        if settings.MARKER_ENABLED:
            document_consumer_declaration.connect(marker_consumer_declaration)
