import unittest
from types import SimpleNamespace
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docks.core.constants import (
    SECTION_CONTAINERS,
    SECTION_IMAGES,
    SECTION_NETWORKS,
    SECTION_VOLUMES,
)
from docks.models.container import Container
from docks.models.image import Image
from docks.ui.window import DocksWindow


class DocksWindowLogicTest(unittest.TestCase):
    def make_window_like(self):
        return SimpleNamespace(
            containers=[],
            images=[],
            networks=[],
            volumes=[],
            search_queries={},
            container_sort_key="created",
            container_sort_desc=True,
            image_sort_key="created",
            image_sort_desc=True,
            network_sort_key="name",
            network_sort_desc=False,
            volume_sort_key="created",
            volume_sort_desc=True,
            selected_container_ids=set(),
            selected_image_ids=set(),
            selected_network_ids=set(),
            selected_volume_ids=set(),
        )

    def test_sorted_containers_defaults_to_created_desc(self) -> None:
        window = self.make_window_like()
        window.containers = [
            Container("1", "db", "db", "postgres", "img1", "running", "2024-01-01 10:00"),
            Container("2", "api", "api", "backend", "img2", "running", "2024-01-02 10:00"),
        ]
        sorted_items = DocksWindow.sorted_containers(window)
        self.assertEqual([item.id for item in sorted_items], ["2", "1"])

    def test_sorted_images_can_sort_by_used(self) -> None:
        window = self.make_window_like()
        image_used = Image("1", "sha256:used", ["postgres:17"], "1 GB", "2024-01-01 10:00")
        image_unused = Image("2", "sha256:unused", ["redis:7"], "1 GB", "2024-01-02 10:00")
        window.images = [image_unused, image_used]
        window.containers = [
            Container("1", "db", "db", "postgres:17", "sha256:used", "running", "2024-01-01 10:00")
        ]
        window.image_sort_key = "used"
        window.image_sort_desc = False
        window.image_in_use = lambda image: DocksWindow.image_in_use(window, image)

        sorted_items = DocksWindow.sorted_images(window)
        self.assertEqual([item.full_id for item in sorted_items], ["sha256:used", "sha256:unused"])

    def test_bulk_section_label_uses_singular_and_plural(self) -> None:
        window = self.make_window_like()
        self.assertEqual(DocksWindow.bulk_section_label(window, SECTION_CONTAINERS, 1), "container")
        self.assertEqual(DocksWindow.bulk_section_label(window, SECTION_IMAGES, 2), "images")

    def test_bulk_success_message_is_specific(self) -> None:
        window = self.make_window_like()
        message = DocksWindow.bulk_success_message(window, SECTION_CONTAINERS, "restart", 3)
        self.assertEqual(message, "3 container(s) restarted.")

    def test_toggle_row_selection_reports_mode_change(self) -> None:
        window = self.make_window_like()
        calls = []
        window.update_selection_ui = lambda section_id, resource_id, was_visible: calls.append(
            (section_id, resource_id, was_visible)
        )
        window.selected_ids_for_section = lambda section_id: {
            SECTION_CONTAINERS: window.selected_container_ids,
            SECTION_IMAGES: window.selected_image_ids,
            SECTION_NETWORKS: window.selected_network_ids,
            SECTION_VOLUMES: window.selected_volume_ids,
        }[section_id]
        window.selection_column_visible = lambda section_id: bool(window.selected_ids_for_section(section_id))

        DocksWindow.toggle_row_selection(window, SECTION_IMAGES, "img-1")

        self.assertIn("img-1", window.selected_image_ids)
        self.assertEqual(calls, [(SECTION_IMAGES, "img-1", False)])

    def test_sorted_containers_applies_search_query(self) -> None:
        window = self.make_window_like()
        window.search_queries = {SECTION_CONTAINERS: "postgres"}
        window.containers = [
            Container("1", "db", "database", "postgres:17", "img1", "running", "2024-01-01 10:00"),
            Container("2", "cache", "cache", "redis:7", "img2", "running", "2024-01-02 10:00"),
        ]

        sorted_items = DocksWindow.sorted_containers(window)

        self.assertEqual([item.id for item in sorted_items], ["1"])

    def test_sorted_images_applies_search_query(self) -> None:
        window = self.make_window_like()
        window.search_queries = {SECTION_IMAGES: "redis"}
        window.images = [
            Image("1", "sha256:1", ["postgres:17"], "1 GB", "2024-01-01 10:00"),
            Image("2", "sha256:2", ["redis:7"], "1 GB", "2024-01-02 10:00"),
        ]

        sorted_items = DocksWindow.sorted_images(window)

        self.assertEqual([item.full_id for item in sorted_items], ["sha256:2"])

    def test_change_language_restores_current_section(self) -> None:
        config_values = {"last_view": SECTION_NETWORKS}

        class FakeConfig:
            def get(self, key, default=None):
                return config_values.get(key, default)

            def set(self, key, value):
                config_values[key] = value

        window = self.make_window_like()
        window.config = FakeConfig()
        window.current_language = "auto"
        window.selected_detail = None
        window.docker_available = True
        calls = []
        window.build_sidebar = lambda: "sidebar"
        window.build_content_area = lambda: "content"
        window.set_sidebar_widget = lambda widget: calls.append(("sidebar", widget))
        window.set_content_widget = lambda widget: calls.append(("content", widget))
        window.select_section = lambda section_id: calls.append(("select", section_id))
        window.show_toast = lambda message: calls.append(("toast", message))

        with patch("docks.ui.window.setup_locale") as setup_locale:
            DocksWindow.change_language(window, "es")

        setup_locale.assert_called_once_with("es")
        self.assertEqual(config_values["language"], "es")
        self.assertIn(("select", SECTION_NETWORKS), calls)

    def test_on_close_request_persists_current_window_size(self) -> None:
        saved = {}

        class FakeConfig:
            def set(self, key, value):
                saved[key] = value

        window = self.make_window_like()
        window.stop_logs_polling = lambda: saved.setdefault("stopped", True)
        window.stop_event_polling = lambda: saved.setdefault("events_stopped", True)
        window.get_width = lambda: 1440
        window.get_height = lambda: 900
        window.get_default_size = lambda: (1200, 760)
        window.config = FakeConfig()

        result = DocksWindow.on_close_request(window)

        self.assertFalse(result)
        self.assertEqual(saved["window_width"], 1440)
        self.assertEqual(saved["window_height"], 900)

    def test_select_section_clears_logs_when_leaving_containers(self) -> None:
        window = self.make_window_like()
        saved = {}

        class FakeConfig:
            def set(self, key, value):
                saved[key] = value

        window.docker_available = True
        window.selected_detail = None
        window.detail_history = []
        window.detail_loading = True
        window.detail_error = "boom"
        window.detail_payload = {"id": "x"}
        window.detail_title = "old"
        window.detail_subtitle = "old"
        window.expanded_logs_container_id = "abc"
        window.collapse_container_logs = lambda: saved.setdefault("logs_collapsed", True)
        window.stack = SimpleNamespace(set_visible_child_name=lambda section_id: saved.setdefault("section", section_id))
        window.config = FakeConfig()
        window.update_sidebar_selection = lambda section_id: saved.setdefault("sidebar", section_id)
        window.sync_search_ui_for_section = lambda section_id: saved.setdefault("search_section", section_id)

        DocksWindow.select_section(window, SECTION_IMAGES)

        self.assertTrue(saved["logs_collapsed"])
        self.assertEqual(saved["section"], SECTION_IMAGES)
        self.assertEqual(saved["sidebar"], SECTION_IMAGES)
        self.assertEqual(saved["search_section"], SECTION_IMAGES)
        self.assertEqual(window.detail_history, [])
        self.assertIsNone(window.selected_detail)
        self.assertFalse(window.detail_loading)
        self.assertEqual(window.detail_error, "")
        self.assertIsNone(window.detail_payload)


if __name__ == "__main__":
    unittest.main()
