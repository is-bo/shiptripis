#!/usr/bin/env python
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Activate the venv or rebuild the docker image."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
