# Testing

## Current Test Suite

The automated baseline uses `unittest`.

Main files:

- `tests/test_docker_service.py`
- `tests/test_window_logic.py`

## Run the Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Syntax Validation

```bash
python3 -m py_compile src/docks/ui/window.py src/docks/services/docker_service.py
```

## Current Coverage

The suite mainly covers:

- sorting and search logic,
- messages and bulk selection behavior,
- window size persistence,
- section restoration after language changes,
- log cleanup when switching views,
- Docker client error handling,
- log and network formatting helpers.

## Current Gaps

There is no automated coverage for:

- real GTK interaction,
- header click areas,
- dialogs,
- file chooser behavior,
- full integration against a real Docker daemon.

## Recommended Manual Checklist

Before closing major UI or Docker-operation changes, verify:

- startup with Docker available,
- startup with Docker unavailable,
- manual refresh,
- automatic updates from events,
- per-section search,
- detail view and back navigation,
- logs with follow enabled and disabled,
- network and volume creation,
- image pull,
- language and color scheme changes.
