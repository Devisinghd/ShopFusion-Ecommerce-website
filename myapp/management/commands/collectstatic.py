import os
import shutil

from django.apps import apps
from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Collect static files without Django's broken collectstatic wrapper."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--noinput", action="store_true")
        parser.add_argument("--no-post-process", action="store_true")

    def handle(self, *args, **options):
        static_root = os.path.abspath(settings.STATIC_ROOT)
        os.makedirs(static_root, exist_ok=True)

        if options["clear"]:
            shutil.rmtree(static_root, ignore_errors=True)
            os.makedirs(static_root, exist_ok=True)

        ignore_patterns = list(apps.get_app_config("staticfiles").ignore_patterns)
        collected = {}

        for finder in finders.get_finders():
            for relative_path, source_storage in finder.list(ignore_patterns):
                relative_path = relative_path.replace("\\", "/")
                if relative_path in collected:
                    continue

                destination = os.path.join(static_root, *relative_path.split("/"))
                os.makedirs(os.path.dirname(destination), exist_ok=True)

                with source_storage.open(relative_path.replace("/", "\\") if os.name == "nt" else relative_path, "rb") as source:
                    with open(destination, "wb") as target:
                        shutil.copyfileobj(source, target)

                collected[relative_path] = destination

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(collected)} static files copied to '{static_root}'."
            )
        )
