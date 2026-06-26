import sys
from .app import DocksApplication


def main() -> int:
    app = DocksApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

