# Development

## Requirements

- Python 3.10 or newer
- GTK 4
- libadwaita 1
- PyGObject
- A local Docker engine accessible to the current user

## Environment

Install the project in editable mode:

```bash
python3 -m pip install -e .
```

## Run the Application

```bash
PYTHONPATH=src python3 -m docks.main
```

Or, if the script is installed:

```bash
docks
```

## Main Working Areas

The most active parts of the project are:

- `src/docks/ui/window.py`
- `src/docks/services/docker_service.py`
- `src/docks/core/config.py`
- `tests/test_window_logic.py`
- `tests/test_docker_service.py`

## Practical Guidelines

- Keep the UI responsive; do not run blocking Docker calls on the main thread.
- Any Docker operation that may take noticeable time should run in the background.
- Any widget update must return to the GTK main thread.
- New features should respect the current product decision: local Docker only.
- Before exposing a capability in the UI, confirm that it fits the current product direction.

## Internationalization

The app supports runtime language changes from preferences. When adding new text:

- use the `_` translation helper,
- review placeholders, tooltips, and error messages,
- verify that UI recreation does not lose the active view.

## Persistence and Configuration

Do not write directly to `~/.config/docks/` from multiple places. The intended entry points are `ConfigManager` and the dedicated repositories.

## UI Changes

This application can regress visually when changing headers, overlays, or view rebuilds. If you touch:

- headers,
- sidebar,
- search bar,
- detail views,
- logs,

you should at least verify:

- buttons remain clickable,
- widgets are not duplicated after refresh,
- the active view and search state are preserved correctly.
