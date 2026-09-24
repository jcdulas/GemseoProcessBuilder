"""Entry point of the ``gemseo-process-builder`` command."""

import argparse
import logging
import sys

from gemseo_process_builder import __version__


def main() -> None:
    """Parse the command line and start the application."""
    parser = argparse.ArgumentParser(
        prog="gemseo-process-builder",
        description="Build, run and analyze GEMSEO processes graphically.",
    )
    parser.add_argument("--dev", action="store_true", help="open the DevTools")
    parser.add_argument("--version", action="version", version=__version__)
    arguments = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if arguments.dev else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Qt is imported here so that --help and --version answer instantly.
    from gemseo_process_builder.app.application import run

    sys.exit(run(dev_mode=arguments.dev))


if __name__ == "__main__":
    main()
