import argparse
import sys

from collector_web.api.server import start_server


def main() -> int:
    parser = argparse.ArgumentParser(description="collector_web service")
    parser.add_argument("--start", action="store_true", help="start the web server")
    args = parser.parse_args()

    if not args.start:
        parser.print_help()
        return 1

    start_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
