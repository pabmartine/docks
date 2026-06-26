import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import json
import threading
import time

from gi.repository import Adw, Gio, GLib, Gdk, Gtk, Pango

from ..core.config import ConfigManager
from ..core.constants import (
    APP_NAME,
    DEFAULT_SIDEBAR_WIDTH_FRACTION,
    SECTION_CONTAINERS,
    SECTION_IMAGES,
    SECTION_NETWORKS,
    SECTION_VOLUMES,
)
from ..core.i18n import setup_locale, translate as _
from ..repositories.connection_repository import ConnectionRepository
from ..services.connection_service import ConnectionService
from ..services.docker_service import DockerConnectionError, DockerService
from .styles import apply_custom_css


class DocksWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.config = ConfigManager()
        self.docker_service = DockerService()
        self.connection_service = ConnectionService(
            self.config,
            ConnectionRepository(self.config),
            self.docker_service,
        )
        self.active_connection = self.connection_service.activate(
            self.config.get("last_connection_id", "local")
        )

        self.set_title(APP_NAME)
        self.set_default_size(
            self.config.get("window_width", 1200),
            self.config.get("window_height", 760),
        )
        self.set_size_request(360, 220)
        self.containers = []
        self.images = []
        self.volumes = []
        self.networks = []
        self.docker_available = False
        self.startup_message = ""
        self.container_sort_key = "status"
        self.container_sort_desc = False
        self.image_sort_key = "created"
        self.image_sort_desc = True
        self.network_sort_key = "name"
        self.network_sort_desc = False
        self.volume_sort_key = "created"
        self.volume_sort_desc = True
        self.selected_container_ids = set()
        self.selected_image_ids = set()
        self.selected_network_ids = set()
        self.selected_volume_ids = set()
        self.search_queries = {
            SECTION_CONTAINERS: "",
            SECTION_IMAGES: "",
            SECTION_NETWORKS: "",
            SECTION_VOLUMES: "",
        }
        self.selection_summary_labels = {}
        self.selection_checkbuttons = {}
        self.selected_detail = None
        self.detail_history = []
        self.detail_title = ""
        self.detail_subtitle = ""
        self.detail_payload = None
        self.detail_loading = False
        self.detail_error = ""
        self.detail_request_token = 0
        self.expanded_logs_container_id = None
        self.expanded_logs_text = ""
        self.logs_loading = False
        self.logs_fetch_in_progress = False
        self.logs_follow_enabled = True
        self.logs_tail_count = 200
        self.logs_request_token = 0
        self.logs_poll_source_id = None
        self.logs_text_view = None
        self.logs_scroller = None
        self.logs_since = None
        self.logs_follow_switch = None
        self.current_language = self.config.get("language", "auto")
        setup_locale(self.current_language if self.current_language != "auto" else None)
        self.is_refreshing = False
        self.pending_refresh = False
        self.has_loaded_state = False
        self.event_poll_source_id = None
        self.event_poll_in_progress = False
        self.events_since = int(time.time())
        self.header_start_buttons = []
        self.header_end_buttons = []

        self.setup_actions()
        self.setup_ui()
        self.connect("close-request", self.on_close_request)
        self.set_refreshing(True)
        self.set_content_widget(self.build_content_area())
        self.run_in_background(
            self.collect_docker_state,
            self.finish_refresh,
            self.finish_refresh_with_error,
        )
        self.start_event_polling()

    def setup_actions(self) -> None:
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", self.on_refresh)
        self.add_action(refresh_action)

        toggle_search_action = Gio.SimpleAction.new("toggle-search", None)
        toggle_search_action.connect("activate", self.on_toggle_search_action)
        self.add_action(toggle_search_action)

        app = self.get_application()
        if app is not None:
            app.set_accels_for_action("win.refresh", ["F5", "<Control>r"])
            app.set_accels_for_action("win.toggle-search", ["<Control>f"])

    def setup_ui(self) -> None:
        apply_custom_css()
        self.apply_color_scheme()

        self.toast_overlay = Adw.ToastOverlay()
        self.split_view = Adw.NavigationSplitView()
        self.split_view.set_sidebar_width_fraction(DEFAULT_SIDEBAR_WIDTH_FRACTION)
        self.split_view.set_min_sidebar_width(240)
        self.split_view.set_max_sidebar_width(320)

        self.sidebar_page = Adw.NavigationPage.new(self.build_sidebar(), _("Sections"))
        self.content_overlay = Gtk.Overlay()
        self.content_overlay.set_child(self.build_content_area())
        self.loading_revealer = Gtk.Revealer()
        self.loading_revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.loading_revealer.set_transition_duration(180)
        self.loading_revealer.set_halign(Gtk.Align.END)
        self.loading_revealer.set_valign(Gtk.Align.START)
        self.loading_revealer.set_margin_top(16)
        self.loading_revealer.set_margin_end(16)
        self.loading_revealer.set_child(self.build_loading_indicator())
        self.loading_revealer.set_reveal_child(False)
        self.content_overlay.add_overlay(self.loading_revealer)
        self.search_bar = self.create_search_bar()
        self.search_bar.set_vexpand(False)
        self.search_bar.set_valign(Gtk.Align.END)
        self.content_shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.content_shell.set_vexpand(True)
        self.content_shell.append(self.content_overlay)
        self.content_shell.append(self.search_bar)
        self.window_toolbar = Adw.ToolbarView()
        self.window_header = Adw.HeaderBar()
        self.window_toolbar.add_top_bar(self.window_header)
        self.window_toolbar.set_content(self.content_shell)
        self.content_page = Adw.NavigationPage.new(self.window_toolbar, _("Content"))

        self.split_view.set_sidebar(self.sidebar_page)
        self.split_view.set_content(self.content_page)
        self.split_view.set_vexpand(True)
        self.toast_overlay.set_vexpand(True)
        self.toast_overlay.set_child(self.split_view)
        self.set_content(self.toast_overlay)

        initial_view = self.config.get("last_view", SECTION_CONTAINERS)
        self.select_section(initial_view)

    def build_loading_indicator(self) -> Gtk.Widget:
        frame = Adw.Bin()
        frame.add_css_class("card")
        frame.add_css_class("loading-indicator")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)

        spinner = Gtk.Spinner()
        spinner.set_spinning(True)
        label = Gtk.Label(label=_("Refreshing Docker data…"), xalign=0)

        box.append(spinner)
        box.append(label)
        frame.set_child(box)
        return frame

    def set_content_widget(self, widget: Gtk.Widget) -> None:
        self.content_overlay.set_child(widget)
        self.content_overlay.add_overlay(self.loading_revealer)
        self.update_content_header()

    def set_sidebar_widget(self, widget: Gtk.Widget) -> None:
        self.sidebar_page.set_child(widget)

    def set_refreshing(self, refreshing: bool) -> None:
        self.is_refreshing = refreshing
        if hasattr(self, "loading_revealer"):
            self.loading_revealer.set_reveal_child(refreshing)
        if hasattr(self, "sidebar_page") and self.sidebar_page.get_child() is not None:
            self.sidebar_page.get_child().set_sensitive(not refreshing)

    def build_sidebar(self) -> Gtk.Widget:
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        header.set_title_widget(Adw.WindowTitle(title=APP_NAME))

        app_icon = Gtk.Image.new_from_icon_name("com.pabmartine.Docks")
        header.pack_start(app_icon)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_tooltip_text(_("Application menu"))
        menu_button.set_menu_model(self.build_app_menu())
        menu_button.add_css_class("flat")
        header.pack_end(menu_button)
        toolbar_view.add_top_bar(header)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar_box.set_margin_top(12)
        sidebar_box.set_margin_bottom(10)
        sidebar_box.set_margin_start(10)
        sidebar_box.set_margin_end(10)
        sidebar_box.set_vexpand(True)

        self.section_rows = {}
        running_count = sum(1 for container in self.containers if container.status == "running")

        nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        nav_box.set_margin_top(4)

        for section_id, title, icon_name, counts in (
            (SECTION_CONTAINERS, _("Containers"), "view-grid-symbolic", [running_count, len(self.containers) - running_count]),
            (SECTION_IMAGES, _("Images"), "image-x-generic-symbolic", [len(self.images)]),
            (SECTION_NETWORKS, _("Networks"), "network-wired-symbolic", [len(self.networks)]),
            (SECTION_VOLUMES, _("Volumes"), "drive-harddisk-symbolic", [len(self.volumes)]),
        ):
            row = self.build_sidebar_nav_row(title, icon_name, section_id, counts, enabled=self.docker_available)
            nav_box.append(row)
            self.section_rows[section_id] = row

        sidebar_box.append(nav_box)
        toolbar_view.set_content(sidebar_box)
        return toolbar_view

    def build_sidebar_nav_row(
        self,
        title: str,
        icon_name: str,
        section_id: str,
        counts: list[int],
        enabled: bool,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("sidebar-row")
        row.set_hexpand(True)
        row.set_valign(Gtk.Align.CENTER)
        row.set_sensitive(enabled)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("sidebar-row-label")
        label.set_hexpand(True)

        row.append(icon)
        row.append(label)

        for index, count in enumerate(counts):
            row.append(self.build_count_badge(str(count), muted=index > 0))

        if enabled:
            click = Gtk.GestureClick()
            click.connect("released", lambda *_args: self.on_section_activated(None, section_id))
            row.add_controller(click)
        return row

    def build_count_badge(self, text: str, muted: bool = False) -> Gtk.Widget:
        badge = Gtk.Label(label=text)
        badge.add_css_class("count-badge")
        if muted:
            badge.add_css_class("muted")
        badge.set_size_request(24, 24)
        badge.set_halign(Gtk.Align.CENTER)
        badge.set_valign(Gtk.Align.CENTER)
        badge.set_xalign(0.5)
        badge.set_yalign(0.5)
        return badge

    def build_content_area(self) -> Gtk.Widget:
        if not self.has_loaded_state and self.is_refreshing:
            return self.build_initial_loading_page()

        if not self.docker_available:
            return self.build_docker_unavailable_page()

        if self.selected_detail is not None:
            return self.build_detail_page()

        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.add_named(
            self.build_resource_page(
                SECTION_CONTAINERS,
                _("Containers"),
                _("Workloads running on the active Docker connection."),
                self.render_containers,
            ),
            SECTION_CONTAINERS,
        )
        self.stack.add_named(
            self.build_resource_page(
                SECTION_IMAGES,
                _("Images"),
                _("Pulled images and local build artifacts."),
                self.render_images,
            ),
            SECTION_IMAGES,
        )
        self.stack.add_named(
            self.build_resource_page(
                SECTION_NETWORKS,
                _("Networks"),
                _("Available Docker networks."),
                self.render_networks,
            ),
            SECTION_NETWORKS,
        )
        self.stack.add_named(
            self.build_resource_page(
                SECTION_VOLUMES,
                _("Volumes"),
                _("Persistent data attached to your containers."),
                self.render_volumes,
            ),
            SECTION_VOLUMES,
        )

        return self.stack

    def build_initial_loading_page(self) -> Gtk.Widget:
        status_page = Adw.StatusPage()
        status_page.set_icon_name("network-server-symbolic")
        status_page.set_title(_("Loading Docker data"))
        status_page.set_description(_("Checking the active Docker connection and fetching resources."))

        clamp = Adw.Clamp()
        clamp.set_maximum_size(680)
        clamp.set_child(status_page)
        return clamp

    def build_docker_unavailable_page(self) -> Gtk.Widget:
        status_page = Adw.StatusPage()
        status_page.set_icon_name("dialog-warning-symbolic")
        status_page.set_title(_("No local Docker instance was found"))
        status_page.set_description(self.startup_message)

        button = Gtk.Button(label=_("Retry"))
        button.add_css_class("suggested-action")
        button.connect("clicked", self.on_refresh)
        status_page.set_child(button)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(680)
        clamp.set_child(status_page)
        return clamp

    def build_app_menu(self) -> Gio.Menu:
        menu_model = Gio.Menu()
        language_menu = Gio.Menu()
        language_menu.append(_("Auto-detect"), "app.language::auto")
        language_menu.append(_("English"), "app.language::en")
        language_menu.append(_("Español"), "app.language::es")

        menu_model.append(_("Refresh"), "win.refresh")
        menu_model.append(_("Preferences"), "app.preferences")
        menu_model.append_submenu(_("Language"), language_menu)
        menu_model.append(_("About Docks"), "app.about")
        menu_model.append(_("Quit"), "app.quit")
        return menu_model

    def create_search_bar(self) -> Gtk.SearchBar:
        search_bar = Gtk.SearchBar()
        search_bar.set_search_mode(False)
        search_bar.set_show_close_button(False)

        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        search_box.set_margin_top(2)
        search_box.set_margin_bottom(2)
        search_box.set_margin_start(8)
        search_box.set_margin_end(8)
        search_box.set_valign(Gtk.Align.CENTER)

        self.global_search_entry = Gtk.SearchEntry()
        self.global_search_entry.set_hexpand(True)
        self.global_search_entry.set_placeholder_text(self.search_placeholder(self.current_search_section()))
        self.global_search_entry.add_css_class("compact-entry")
        self.global_search_entry.set_size_request(-1, 30)
        self.global_search_entry.connect("search-changed", self.on_global_search_changed)
        search_box.append(self.global_search_entry)

        close_button = self.build_icon_button("window-close-symbolic", _("Close search"), lambda *_args: self.hide_search())
        close_button.set_valign(Gtk.Align.CENTER)
        search_box.append(close_button)

        search_bar.set_child(search_box)
        search_bar.connect_entry(self.global_search_entry)
        return search_bar

    def build_resource_page(self, section_id: str, title: str, subtitle: str, renderer) -> Gtk.Widget:
        clamp = Adw.Clamp()
        clamp.set_maximum_size(960)
        clamp.set_tightening_threshold(640)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_margin_top(18)
        page.set_margin_bottom(24)
        page.set_margin_start(18)
        page.set_margin_end(18)
        renderer(page)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)

        clamp.set_child(page)
        scroller.set_child(clamp)
        return scroller

    def build_search_toggle_button(self) -> Gtk.Button:
        return self.build_icon_button(
            "system-search-symbolic",
            _("Search (Ctrl+F)"),
            lambda *_args: self.toggle_search(),
        )

    def clear_header_children(self, header: Gtk.HeaderBar) -> None:
        for button in self.header_start_buttons:
            header.remove(button)
        for button in self.header_end_buttons:
            header.remove(button)
        self.header_start_buttons = []
        self.header_end_buttons = []

    def current_header_state(self) -> tuple[str, str, list[Gtk.Button], list[Gtk.Button]]:
        if not self.has_loaded_state and self.is_refreshing:
            return (
                _("Loading Docker data"),
                _("Checking the active Docker connection and fetching resources."),
                [],
                [],
            )

        if not self.docker_available:
            return (
                _("Docker unavailable"),
                _("Local engine not detected"),
                [self.build_search_toggle_button(), self.build_icon_button("view-refresh-symbolic", _("Retry"), self.on_refresh)],
                [],
            )

        if self.selected_detail is not None:
            start_buttons = [
                self.build_icon_button("go-previous-symbolic", _("Back"), lambda *_args: self.close_detail()),
                self.build_search_toggle_button(),
            ]
            if not self.detail_loading:
                start_buttons.append(self.build_icon_button("view-refresh-symbolic", _("Refresh"), self.on_refresh))

            if self.detail_error:
                return (_("Resource unavailable"), _("Detail view"), start_buttons, [])
            if self.detail_loading or self.detail_payload is None:
                return (_("Loading details"), _("Detail view"), start_buttons, [])
            return (self.detail_title, self.detail_subtitle, start_buttons, [])

        section_id = self.config.get("last_view", SECTION_CONTAINERS)
        titles = {
            SECTION_CONTAINERS: (_("Containers"), _("Runtime workload on your local engine.")),
            SECTION_IMAGES: (_("Images"), _("Reusable filesystem snapshots available locally.")),
            SECTION_NETWORKS: (_("Networks"), _("Connectivity configuration for your containers.")),
            SECTION_VOLUMES: (_("Volumes"), _("Persistent data attached to your containers.")),
        }
        title, subtitle = titles.get(section_id, (APP_NAME, ""))
        start_buttons = [
            self.build_search_toggle_button(),
            self.build_icon_button("view-refresh-symbolic", _("Refresh"), self.on_refresh),
            *self.build_section_header_buttons(section_id),
        ]
        return (title, subtitle, start_buttons, [])

    def update_content_header(self) -> None:
        if not hasattr(self, "window_header"):
            return
        self.clear_header_children(self.window_header)
        title, subtitle, start_buttons, end_buttons = self.current_header_state()
        for button in start_buttons:
            self.window_header.pack_start(button)
        for button in end_buttons:
            self.window_header.pack_end(button)
        self.header_start_buttons = start_buttons
        self.header_end_buttons = end_buttons
        self.window_header.set_title_widget(Adw.WindowTitle(title=title, subtitle=subtitle))

    def build_section_header_buttons(self, section_id: str) -> list[Gtk.Button]:
        buttons = []
        if section_id == SECTION_IMAGES:
            buttons.append(self.build_header_action_button("edit-clear-history-symbolic", _("Prune unused images"), self.prune_unused_images))
        elif section_id == SECTION_NETWORKS:
            buttons.append(self.build_header_action_button("list-add-symbolic", _("Create network"), self.show_create_network_dialog))
            buttons.append(self.build_header_action_button("edit-clear-history-symbolic", _("Prune unused networks"), self.prune_unused_networks))
        elif section_id == SECTION_VOLUMES:
            buttons.append(self.build_header_action_button("list-add-symbolic", _("Create volume"), self.show_create_volume_dialog))
            buttons.append(self.build_header_action_button("edit-clear-history-symbolic", _("Prune unused volumes"), self.prune_unused_volumes))
        return buttons

    def build_header_action_button(self, icon_name: str, tooltip: str, callback) -> Gtk.Button:
        return self.build_icon_button(icon_name, tooltip, lambda *_args: callback())

    def build_icon_button(self, icon_name: str, tooltip: str, on_clicked) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("flat")
        button.set_tooltip_text(tooltip)
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_can_target(False)
        image.set_focusable(False)
        button.set_child(image)
        button.connect("clicked", on_clicked)
        return button

    def build_detail_page(self) -> Gtk.Widget:
        resource_type = self.selected_detail["type"]
        if self.detail_loading:
            return self.build_detail_loading_page()
        if self.detail_error:
            return self.build_detail_error_page(self.detail_error)
        if self.detail_payload is None:
            return self.build_detail_loading_page()

        title = self.detail_title
        subtitle = self.detail_subtitle
        payload = self.detail_payload

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_margin_top(18)
        page.set_margin_bottom(24)
        page.set_margin_start(18)
        page.set_margin_end(18)
        page.append(self.build_detail_content(resource_type, payload))

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(960)
        clamp.set_tightening_threshold(640)
        clamp.set_child(page)
        scroller.set_child(clamp)
        return scroller

    def build_detail_loading_page(self) -> Gtk.Widget:
        status_page = Adw.StatusPage()
        status_page.set_icon_name("network-server-symbolic")
        status_page.set_title(_("Loading resource details"))
        status_page.set_description(_("The selected Docker resource is being inspected."))

        clamp = Adw.Clamp()
        clamp.set_maximum_size(680)
        clamp.set_child(status_page)
        return clamp

    def build_detail_error_page(self, message: str) -> Gtk.Widget:
        status_page = Adw.StatusPage()
        status_page.set_icon_name("dialog-warning-symbolic")
        status_page.set_title(_("The selected resource is no longer available"))
        status_page.set_description(message)

        close_button = Gtk.Button(label=_("Back"))
        close_button.add_css_class("suggested-action")
        close_button.connect("clicked", lambda *_args: self.close_detail())
        status_page.set_child(close_button)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(680)
        clamp.set_child(status_page)
        return clamp

    def render_containers(self, parent: Gtk.Box) -> None:
        self.selection_checkbuttons[SECTION_CONTAINERS] = {}
        containers = self.sorted_containers()
        running_count = sum(1 for container in containers if container.status == "running")

        parent.append(
            self.build_metrics_row(
                [
                    (_("Total"), str(len(containers))),
                    (_("Running"), str(running_count)),
                    (_("Stopped"), str(len(containers) - running_count)),
                ]
            )
        )
        if self.selection_column_visible(SECTION_CONTAINERS):
            parent.append(self.build_selection_actions_bar(SECTION_CONTAINERS))
        if not containers:
            parent.append(
                self.build_empty_resource_state(
                    _("No containers found"),
                    _("The local Docker engine has no containers yet."),
                    "view-grid-symbolic",
                )
            )
            return
        parent.append(self.build_container_table(containers))

    def render_images(self, parent: Gtk.Box) -> None:
        self.selection_checkbuttons[SECTION_IMAGES] = {}
        images = self.sorted_images()
        parent.append(
            self.build_metrics_row(
                [
                    (_("Images"), str(len(images))),
                    (_("Used"), str(sum(1 for image in images if self.image_in_use(image)))),
                    (_("Unused"), str(sum(1 for image in images if not self.image_in_use(image)))),
                ]
            )
        )
        if self.selection_column_visible(SECTION_IMAGES):
            parent.append(self.build_selection_actions_bar(SECTION_IMAGES))
        if not images:
            parent.append(
                self.build_empty_resource_state(
                    _("No images found"),
                    _("Pull or build an image and it will appear here."),
                    "image-x-generic-symbolic",
                )
            )
            return
        parent.append(self.build_images_table(images))

    def render_networks(self, parent: Gtk.Box) -> None:
        self.selection_checkbuttons[SECTION_NETWORKS] = {}
        networks = self.sorted_networks()
        parent.append(
            self.build_metrics_row(
                [
                    (_("Networks"), str(len(networks))),
                    (_("Bridge"), str(sum(1 for network in networks if network.driver == "bridge"))),
                    (_("Other"), str(sum(1 for network in networks if network.driver != "bridge"))),
                ]
            )
        )
        if self.selection_column_visible(SECTION_NETWORKS):
            parent.append(self.build_selection_actions_bar(SECTION_NETWORKS))
        if not networks:
            parent.append(
                self.build_empty_resource_state(
                    _("No networks found"),
                    _("Create a Docker network and it will appear here."),
                    "network-wired-symbolic",
                )
            )
            return
        parent.append(self.build_networks_table(networks))

    def render_volumes(self, parent: Gtk.Box) -> None:
        self.selection_checkbuttons[SECTION_VOLUMES] = {}
        volumes = self.sorted_volumes()
        parent.append(
            self.build_metrics_row(
                [
                    (_("Volumes"), str(len(volumes))),
                    (_("Driver"), _("local")),
                    (_("Mounted"), str(sum(1 for volume in volumes if volume.mountpoint))),
                ]
            )
        )
        if self.selection_column_visible(SECTION_VOLUMES):
            parent.append(self.build_selection_actions_bar(SECTION_VOLUMES))
        if not volumes:
            parent.append(
                self.build_empty_resource_state(
                    _("No volumes found"),
                    _("Create a volume from Docker and it will appear here."),
                    "drive-harddisk-symbolic",
                )
            )
            return
        parent.append(self.build_volumes_table(volumes))

    def build_metrics_row(self, metrics: list[tuple[str, str]]) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_homogeneous(True)

        for label, value in metrics:
            card = Adw.Bin()
            card.add_css_class("metric-card")

            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            content.set_valign(Gtk.Align.CENTER)
            metric_value = Gtk.Label(label=value, xalign=0)
            metric_value.add_css_class("metric-value")
            metric_value.set_valign(Gtk.Align.CENTER)
            metric_label = Gtk.Label(label=label, xalign=0)
            metric_label.add_css_class("metric-label")
            metric_label.set_valign(Gtk.Align.CENTER)

            content.append(metric_value)
            content.append(metric_label)
            card.set_child(content)
            row.append(card)

        return row

    def search_placeholder(self, section_id: str) -> str:
        return {
            SECTION_CONTAINERS: _("Search containers"),
            SECTION_IMAGES: _("Search images"),
            SECTION_NETWORKS: _("Search networks"),
            SECTION_VOLUMES: _("Search volumes"),
        }[section_id]

    def on_search_changed(self, section_id: str, query: str) -> None:
        if self.search_queries.get(section_id, "") == query:
            return
        self.search_queries[section_id] = query
        self.rebuild_content_preserving_scroll(section_id)

    def current_search_section(self) -> str:
        return self.config.get("last_view", SECTION_CONTAINERS)

    def on_toggle_search_action(self, *_args) -> None:
        self.toggle_search()

    def toggle_search(self) -> None:
        if not hasattr(self, "search_bar"):
            return

        section_id = self.current_search_section()
        is_active = not self.search_bar.get_search_mode()
        self.search_bar.set_search_mode(is_active)
        if is_active:
            self.global_search_entry.set_placeholder_text(self.search_placeholder(section_id))
            self.global_search_entry.set_text(self.search_queries.get(section_id, ""))
            self.global_search_entry.grab_focus()
            self.global_search_entry.select_region(0, -1)
        else:
            self.hide_search()

    def hide_search(self) -> None:
        if not hasattr(self, "search_bar"):
            return
        section_id = self.current_search_section()
        had_query = bool(self.search_queries.get(section_id, ""))
        self.search_bar.set_search_mode(False)
        self.global_search_entry.set_text("")
        if had_query:
            self.on_search_changed(section_id, "")

    def on_global_search_changed(self, entry) -> None:
        self.on_search_changed(self.current_search_section(), entry.get_text())

    def build_empty_resource_state(self, title: str, description: str, icon_name: str) -> Gtk.Widget:
        page = Adw.StatusPage()
        page.set_icon_name(icon_name)
        page.set_title(title)
        page.set_description(description)

        shell = Adw.Bin()
        shell.add_css_class("card")
        shell.set_child(page)
        return shell

    def build_selection_actions_bar(self, section_id: str) -> Gtk.Widget:
        bar = Adw.Bin()
        bar.add_css_class("card")

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_margin_top(8)
        content.set_margin_bottom(8)
        content.set_margin_start(10)
        content.set_margin_end(10)

        count = len(self.selected_ids_for_section(section_id))
        summary = Gtk.Label(label=_("%(count)s selected") % {"count": count}, xalign=0)
        summary.set_hexpand(True)
        self.selection_summary_labels[section_id] = summary
        content.append(summary)

        for label, callback, suggested in self.selection_action_specs(section_id):
            button = Gtk.Button(label=label)
            if suggested:
                button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_args, callback=callback: callback())
            content.append(button)

        bar.set_child(content)
        return bar

    def build_container_table(self, containers) -> Gtk.Widget:
        shell = Adw.Bin()
        shell.add_css_class("card")
        shell.add_css_class("table-shell")

        table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        table.append(self.build_container_table_header())

        for container in containers:
            table.append(self.build_container_table_row(container))
            if self.expanded_logs_container_id == container.id:
                table.append(self.build_container_logs_row())

        shell.set_child(table)
        return shell

    def build_images_table(self, images) -> Gtk.Widget:
        show_selection = self.selection_column_visible(SECTION_IMAGES)
        shell = Adw.Bin()
        shell.add_css_class("card")
        shell.add_css_class("table-shell")

        table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        table.append(
            self.build_sortable_table_header(
                [
                    ("", None, 44, Gtk.Align.CENTER, False),
                    (_("Name"), "name", 260, Gtk.Align.CENTER, False),
                    (_("Used"), "used", 90, Gtk.Align.CENTER, False),
                    (_("Tags"), "tags", 280, Gtk.Align.CENTER, True),
                    (_("Created"), "created", 150, Gtk.Align.CENTER, False),
                    (_("Actions"), None, 150, Gtk.Align.CENTER, False),
                ],
                self.image_sort_key,
                self.image_sort_desc,
                self.on_image_sort_requested,
                show_selection,
            )
        )

        for image in images:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("table-row")
            if show_selection:
                row.append(self.build_selection_cell(SECTION_IMAGES, image.full_id))
            row.append(self.wrap_table_cell(self.build_truncated_label(image.title), 260, Gtk.Align.START, False))
            row.append(self.wrap_table_cell(self.build_image_usage_badge(self.image_in_use(image)), 90, Gtk.Align.CENTER, False))
            row.append(self.wrap_table_cell(self.build_truncated_label(image.tags_text), 280, Gtk.Align.START, True))
            row.append(self.wrap_table_cell(Gtk.Label(label=image.created_at), 150, Gtk.Align.CENTER, False))
            row.append(
                self.wrap_table_cell(
                    self.build_actions_box(
                        [
                            ("view-reveal-symbolic", _("View details"), lambda image_id=image.full_id: self.open_detail("image", image_id)),
                            ("folder-download-symbolic", _("Pull image"), lambda image_ref=image.title: self.pull_image_reference(image_ref)),
                            ("user-trash-symbolic", _("Delete image"), lambda image_id=image.full_id: self.on_image_action("delete", image_id)),
                        ]
                    ),
                    150,
                    Gtk.Align.CENTER,
                    False,
                )
            )
            self.make_row_clickable(row, lambda image_id=image.full_id: self.toggle_row_selection(SECTION_IMAGES, image_id))
            table.append(row)

        shell.set_child(table)
        return shell

    def build_image_usage_badge(self, in_use: bool) -> Gtk.Widget:
        badge = Gtk.Label(label=_("Used") if in_use else _("Unused"))
        self.apply_status_css(badge, "active" if in_use else "exited")
        return badge

    def build_volumes_table(self, volumes) -> Gtk.Widget:
        show_selection = self.selection_column_visible(SECTION_VOLUMES)
        shell = Adw.Bin()
        shell.add_css_class("card")
        shell.add_css_class("table-shell")

        table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        table.append(
            self.build_sortable_table_header(
                [
                    ("", None, 44, Gtk.Align.CENTER, False),
                    (_("Name"), "name", 220, Gtk.Align.CENTER, False),
                    (_("Mountpoint"), "mountpoint", 420, Gtk.Align.CENTER, True),
                    (_("Created"), "created", 150, Gtk.Align.CENTER, False),
                    (_("Actions"), None, 150, Gtk.Align.CENTER, False),
                ],
                self.volume_sort_key,
                self.volume_sort_desc,
                self.on_volume_sort_requested,
                show_selection,
            )
        )

        for volume in volumes:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("table-row")
            if show_selection:
                row.append(self.build_selection_cell(SECTION_VOLUMES, volume.name))
            row.append(self.wrap_table_cell(self.build_truncated_label(volume.name), 220, Gtk.Align.START, False))
            row.append(self.wrap_table_cell(self.build_truncated_label(volume.mountpoint), 420, Gtk.Align.START, True))
            row.append(self.wrap_table_cell(Gtk.Label(label=volume.created_at), 150, Gtk.Align.CENTER, False))
            row.append(
                self.wrap_table_cell(
                    self.build_actions_box(
                        [
                            ("view-reveal-symbolic", _("View details"), lambda volume_name=volume.name: self.open_detail("volume", volume_name)),
                            ("user-trash-symbolic", _("Delete volume"), lambda volume_name=volume.name: self.on_volume_action("delete", volume_name)),
                        ]
                    ),
                    150,
                    Gtk.Align.CENTER,
                    False,
                )
            )
            self.make_row_clickable(row, lambda volume_name=volume.name: self.toggle_row_selection(SECTION_VOLUMES, volume_name))
            table.append(row)

        shell.set_child(table)
        return shell

    def build_networks_table(self, networks) -> Gtk.Widget:
        show_selection = self.selection_column_visible(SECTION_NETWORKS)
        shell = Adw.Bin()
        shell.add_css_class("card")
        shell.add_css_class("table-shell")

        table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        table.append(
            self.build_sortable_table_header(
                [
                    ("", None, 44, Gtk.Align.CENTER, False),
                    (_("Name"), "name", 260, Gtk.Align.CENTER, False),
                    (_("Stack"), "stack", 160, Gtk.Align.CENTER, False),
                    (_("Driver"), "driver", 110, Gtk.Align.CENTER, False),
                    (_("IPv4"), "ipv4", 180, Gtk.Align.CENTER, False),
                    (_("IPv6"), "ipv6", 180, Gtk.Align.CENTER, False),
                    (_("Actions"), None, 150, Gtk.Align.CENTER, False),
                ],
                self.network_sort_key,
                self.network_sort_desc,
                self.on_network_sort_requested,
                show_selection,
            )
        )

        for network in networks:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("table-row")
            if show_selection:
                row.append(self.build_selection_cell(SECTION_NETWORKS, network.id))
            row.append(self.wrap_table_cell(self.build_truncated_label(network.name), 260, Gtk.Align.START, False))
            row.append(self.wrap_table_cell(self.build_truncated_label(network.stack), 160, Gtk.Align.START, False))
            row.append(self.wrap_table_cell(Gtk.Label(label=network.driver), 110, Gtk.Align.CENTER, False))
            row.append(self.wrap_table_cell(self.build_truncated_label(network.ipv4), 180, Gtk.Align.START, False))
            row.append(self.wrap_table_cell(self.build_truncated_label(network.ipv6), 180, Gtk.Align.START, False))
            row.append(
                self.wrap_table_cell(
                    self.build_actions_box(
                        [
                            ("view-reveal-symbolic", _("View details"), lambda network_id=network.id: self.open_detail("network", network_id)),
                            ("user-trash-symbolic", _("Delete network"), lambda network_id=network.id: self.on_network_action("delete", network_id)),
                        ]
                    ),
                    150,
                    Gtk.Align.CENTER,
                    False,
                )
            )
            self.make_row_clickable(row, lambda network_id=network.id: self.toggle_row_selection(SECTION_NETWORKS, network_id))
            table.append(row)

        shell.set_child(table)
        return shell

    def build_generic_table_header(self, columns: list[tuple[str, int, Gtk.Align, bool]]) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("table-header")
        for title, width, align, expand in columns:
            row.append(self.build_plain_header_cell(title, width, align if not expand else Gtk.Align.CENTER))
        return row

    def build_sortable_table_header(
        self,
        columns: list[tuple[str, str | None, int, Gtk.Align, bool]],
        active_sort_key: str,
        active_sort_desc: bool,
        on_sort_requested,
        show_selection: bool = True,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("table-header")
        for title, sort_key, width, align, expand in columns:
            if title == "" and not show_selection:
                continue
            if sort_key is None:
                row.append(self.build_plain_header_cell(title, width, align if not expand else Gtk.Align.CENTER))
                continue
            row.append(
                self.build_sort_header_cell(
                    title,
                    sort_key,
                    width,
                    align,
                    expand,
                    active_sort_key,
                    active_sort_desc,
                    on_sort_requested,
                )
            )
        return row

    def build_container_table_header(self) -> Gtk.Widget:
        show_selection = self.selection_column_visible(SECTION_CONTAINERS)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("table-header")

        if show_selection:
            row.append(self.build_plain_header_cell("", 44, Gtk.Align.CENTER))
        row.append(self.build_sort_header_cell(_("Name / Label"), "name", 250, Gtk.Align.CENTER, True))
        row.append(self.build_sort_header_cell(_("Status"), "status", 110, Gtk.Align.CENTER, False))
        row.append(self.build_sort_header_cell(_("Image"), "image", 290, Gtk.Align.CENTER, True))
        row.append(self.build_sort_header_cell(_("Created"), "created", 150, Gtk.Align.CENTER, False))
        row.append(self.build_plain_header_cell(_("Actions"), 226, Gtk.Align.CENTER))
        return row

    def build_container_table_row(self, container) -> Gtk.Widget:
        show_selection = self.selection_column_visible(SECTION_CONTAINERS)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("table-row")
        if show_selection:
            row.append(self.build_selection_cell(SECTION_CONTAINERS, container.id))

        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        primary = self.build_truncated_label(container.display_name)
        primary.add_css_class("table-primary")
        secondary = self.build_truncated_label(f"{container.name} · {container.short_id}")
        secondary.add_css_class("resource-subtitle")
        name_box.append(primary)
        name_box.append(secondary)
        row.append(self.wrap_table_cell(name_box, 250, Gtk.Align.START, True))

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        status_chip = Gtk.Label(label=_(container.status.capitalize()))
        self.apply_status_css(status_chip, container.status)
        status_box.append(status_chip)
        row.append(self.wrap_table_cell(status_box, 110, Gtk.Align.CENTER, False))

        image = self.build_truncated_label(container.image)
        row.append(self.wrap_table_cell(image, 290, Gtk.Align.START, True))

        created = Gtk.Label(label=container.created_at, xalign=0)
        row.append(self.wrap_table_cell(created, 150, Gtk.Align.CENTER, False))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for icon_name, tooltip, action_name in self.container_action_specs(container):
            button = Gtk.Button(icon_name=icon_name)
            button.add_css_class("flat")
            button.add_css_class("action-pill")
            button.set_tooltip_text(tooltip)
            if action_name == "detail":
                button.connect("clicked", lambda *_args, container_id=container.id: self.open_detail("container", container_id))
            elif action_name == "logs":
                button.connect("clicked", lambda *_args, container_id=container.id: self.toggle_container_logs(container_id))
            else:
                button.connect("clicked", lambda *_args, container_id=container.id, action_name=action_name: self.on_container_action(action_name, container_id))
            actions.append(button)
        row.append(self.wrap_table_cell(actions, 226, Gtk.Align.CENTER, False))
        self.make_row_clickable(row, lambda container_id=container.id: self.toggle_row_selection(SECTION_CONTAINERS, container_id))
        return row

    def build_container_logs_row(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("table-row")
        if self.selection_column_visible(SECTION_CONTAINERS):
            row.append(self.build_empty_selection_cell())

        shell = Adw.Bin()
        shell.add_css_class("card")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=_("Logs"), xalign=0)
        title.add_css_class("table-primary")
        title.set_hexpand(True)

        clear_button = Gtk.Button(label=_("Clear"))
        clear_button.add_css_class("flat")
        clear_button.connect("clicked", lambda *_args: self.clear_container_logs())

        copy_button = Gtk.Button(label=_("Copy"))
        copy_button.add_css_class("flat")
        copy_button.connect("clicked", lambda *_args: self.copy_container_logs())

        save_button = Gtk.Button(label=_("Save"))
        save_button.add_css_class("flat")
        save_button.connect("clicked", lambda *_args: self.save_container_logs())

        follow_switch = Gtk.Switch()
        follow_switch.set_active(self.logs_follow_enabled)
        follow_switch.connect("notify::active", self.on_logs_follow_toggled)
        self.logs_follow_switch = follow_switch

        follow_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        follow_box.append(Gtk.Label(label=_("Follow")))
        follow_box.append(follow_switch)

        tail_spin = Gtk.SpinButton.new_with_range(20, 2000, 20)
        tail_spin.set_value(self.logs_tail_count)
        tail_spin.connect("value-changed", self.on_logs_tail_changed)

        tail_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tail_box.append(Gtk.Label(label=_("Tail")))
        tail_box.append(tail_spin)

        close_button = Gtk.Button(label=_("Hide"))
        close_button.add_css_class("flat")
        close_button.connect("clicked", lambda *_args: self.toggle_container_logs(self.expanded_logs_container_id))

        top_bar.append(title)
        top_bar.append(clear_button)
        top_bar.append(copy_button)
        top_bar.append(save_button)
        top_bar.append(follow_box)
        top_bar.append(tail_box)
        top_bar.append(close_button)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.get_buffer().set_text(self.current_logs_text())
        self.logs_text_view = text_view

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(180)
        scroller.set_child(text_view)
        self.logs_scroller = scroller

        content.append(top_bar)
        content.append(scroller)
        shell.set_child(content)

        row.append(self.wrap_table_cell(shell, 1000, Gtk.Align.FILL, True))
        return row

    def build_truncated_label(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_single_line_mode(True)
        label.set_wrap(False)
        label.set_tooltip_text(text)
        return label

    def build_plain_header_cell(self, text: str, width: int, align: Gtk.Align) -> Gtk.Widget:
        button = Gtk.Button(label=text)
        button.add_css_class("flat")
        button.add_css_class("sort-header-button")
        button.set_focusable(False)
        button.set_can_target(False)
        return self.wrap_table_cell(button, width, align, False)

    def build_selection_cell(self, section_id: str, resource_id: str) -> Gtk.Widget:
        check = Gtk.CheckButton()
        check.set_active(self.is_row_selected(section_id, resource_id))
        check.set_halign(Gtk.Align.CENTER)
        check.set_valign(Gtk.Align.CENTER)
        self.selection_checkbuttons.setdefault(section_id, {})[resource_id] = check
        check.connect(
            "toggled",
            lambda button, section_id=section_id, resource_id=resource_id: self.set_row_selected(
                section_id,
                resource_id,
                button.get_active(),
            ),
        )
        return self.wrap_table_cell(check, 44, Gtk.Align.CENTER, False)

    def build_empty_selection_cell(self) -> Gtk.Widget:
        return self.wrap_table_cell(Gtk.Box(), 44, Gtk.Align.CENTER, False)

    def build_sort_header_cell(
        self,
        title: str,
        sort_key: str,
        width: int,
        align: Gtk.Align,
        expand: bool,
        active_sort_key: str | None = None,
        active_sort_desc: bool | None = None,
        on_sort_requested=None,
    ) -> Gtk.Widget:
        button = Gtk.Button(
            label=self.sort_header_title(
                title,
                sort_key,
                active_sort_key or self.container_sort_key,
                self.container_sort_desc if active_sort_desc is None else active_sort_desc,
            )
        )
        button.add_css_class("flat")
        button.add_css_class("sort-header-button")
        button.set_halign(align)
        button.connect("clicked", lambda _button: (on_sort_requested or self.on_container_sort_requested)(sort_key))
        return self.wrap_table_cell(button, width, align, expand)

    def sort_header_title(self, title: str, sort_key: str, active_sort_key: str, active_sort_desc: bool) -> str:
        if active_sort_key != sort_key:
            return title
        return f"{title} {'↓' if active_sort_desc else '↑'}"

    def wrap_table_cell(
        self,
        widget: Gtk.Widget,
        width: int,
        align: Gtk.Align,
        expand: bool,
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.set_hexpand(expand)
        box.set_halign(Gtk.Align.FILL if expand else align)
        box.set_valign(Gtk.Align.CENTER)
        if align == Gtk.Align.CENTER:
            box.set_homogeneous(True)
        widget.set_halign(align)
        box.append(widget)
        box.set_size_request(width, -1)
        return box

    def make_row_clickable(self, row: Gtk.Widget, handler) -> None:
        click = Gtk.GestureClick()
        click.connect("released", lambda _gesture, _n_press, x, y: self.on_row_released(row, x, y, handler))
        row.add_controller(click)

    def on_row_released(self, row: Gtk.Widget, x: float, y: float, handler) -> None:
        target = row.pick(x, y, Gtk.PickFlags.DEFAULT)
        while target is not None:
            if isinstance(target, (Gtk.Button, Gtk.CheckButton)):
                return
            target = target.get_parent()
        handler()

    def build_actions_box(self, actions: list[tuple[str, str, object]]) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for icon_name, tooltip, callback in actions:
            button = Gtk.Button(icon_name=icon_name)
            button.add_css_class("flat")
            button.add_css_class("action-pill")
            button.set_tooltip_text(tooltip)
            button.connect("clicked", lambda *_args, callback=callback: callback())
            box.append(button)
        return box

    def build_detail_content(self, resource_type: str, payload: dict) -> Gtk.Widget:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.append(self.build_detail_summary_card(resource_type, payload))
        if resource_type == "container":
            overview = self.build_detail_group_rows(_("Overview"))
            overview.add(self.build_detail_link_row(
                _("Image"),
                payload.get("Config", {}).get("Image") or "-",
                "image",
                payload.get("Image", ""),
            ))
            overview.add(self.build_detail_row(_("Command"), self.format_command(payload.get("Config", {}))))
            overview.add(self.build_detail_row(
                _("Restart policy"),
                payload.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") or _("none"),
            ))
            overview.add(self.build_detail_row(_("Labels"), self.format_labels(payload.get("Config", {}).get("Labels") or {})))
            root.append(overview)
            root.append(self.build_detail_group(_("Runtime"), [
                (_("Status"), payload.get("State", {}).get("Status")),
                (_("Started at"), payload.get("State", {}).get("StartedAt")),
                (_("Finished at"), payload.get("State", {}).get("FinishedAt")),
                (_("Exit code"), payload.get("State", {}).get("ExitCode")),
                (_("Platform"), payload.get("Platform") or "linux"),
                (_("User"), payload.get("Config", {}).get("User") or "root"),
                (_("Working dir"), payload.get("Config", {}).get("WorkingDir") or "-"),
            ]))
            networking = self.build_detail_group_rows(_("Networking"))
            networking.add(self.build_detail_row(_("Hostname"), payload.get("Config", {}).get("Hostname")))
            networking.add(self.build_detail_row(_("Ports"), self.format_ports(payload.get("NetworkSettings", {}).get("Ports"))))
            for network_name, network_data in (payload.get("NetworkSettings", {}).get("Networks") or {}).items():
                networking.add(self.build_detail_link_row(_("Network"), network_name, "network", network_data.get("NetworkID", "")))
            networking.add(self.build_detail_row(_("IP address"), self.first_network_ip(payload.get("NetworkSettings", {}).get("Networks") or {})))
            root.append(networking)
            storage = self.build_detail_group_rows(_("Storage"))
            for row in self.mount_rows(payload.get("Mounts") or []):
                storage.add(row)
            storage.add(self.build_detail_row(_("Mount count"), str(len(payload.get("Mounts") or []))))
            root.append(storage)
        elif resource_type == "image":
            overview = self.build_detail_group_rows(_("Overview"))
            overview.add(self.build_detail_row(_("Id"), payload.get("Id", "")[:24]))
            overview.add(self.build_detail_row(_("Tags"), ", ".join(payload.get("RepoTags") or []) or _("No tags")))
            overview.add(self.build_detail_row(_("Created"), self.format_detail_value(payload.get("Created"))))
            overview.add(self.build_detail_row(_("Size"), self.format_bytes_label(payload.get("Size"))))
            overview.add(self.build_detail_row(_("Used"), _("Yes") if self.image_payload_in_use(payload) else _("No")))
            root.append(overview)
            usage = self.build_detail_group_rows(_("Usage"))
            containers = self.containers_using_image(payload.get("Id", ""))
            if containers:
                for container in containers:
                    usage.add(
                        self.build_detail_link_row(
                            _("Container"),
                            self.container_display_name(container),
                            "container",
                            container.id,
                        )
                    )
            else:
                usage.add(self.build_detail_row(_("Containers"), _("Not used by any container")))
            root.append(usage)
            root.append(self.build_detail_group(_("Configuration"), [
                (_("Entrypoint"), self.format_detail_value((payload.get("Config") or {}).get("Entrypoint"))),
                (_("Cmd"), self.format_detail_value((payload.get("Config") or {}).get("Cmd"))),
                (_("User"), (payload.get("Config") or {}).get("User") or "root"),
                (_("Working dir"), (payload.get("Config") or {}).get("WorkingDir") or "-"),
            ]))
            root.append(self.build_detail_group(_("Platform"), [
                (_("OS"), payload.get("Os")),
                (_("Architecture"), payload.get("Architecture")),
                (_("Docker version"), payload.get("DockerVersion")),
            ]))
        elif resource_type == "volume":
            root.append(self.build_detail_group(_("Overview"), [
                (_("Driver"), payload.get("Driver")),
                (_("Created"), self.format_detail_value(payload.get("CreatedAt"))),
                (_("Mountpoint"), payload.get("Mountpoint")),
                (_("Scope"), payload.get("Scope")),
            ]))
            root.append(self.build_detail_group(_("Usage"), [
                (_("Labels"), self.format_labels(payload.get("Labels") or {})),
                (_("Options"), self.format_labels(payload.get("Options") or {})),
                (_("Usage data"), self.format_detail_value(payload.get("UsageData"))),
            ]))
        else:
            root.append(self.build_detail_group(_("Overview"), [
                (_("Id"), payload.get("Id", "")[:24]),
                (_("Driver"), payload.get("Driver")),
                (_("Scope"), payload.get("Scope")),
                (_("Stack"), self.format_stack_name(payload.get("Labels") or {})),
            ]))
            root.append(self.build_detail_group(_("Addressing"), [
                (_("IPv4"), self.format_network_family(payload.get("IPAM", {}).get("Config") or [], ipv6=False)),
                (_("IPv6"), self.format_network_family(payload.get("IPAM", {}).get("Config") or [], ipv6=True)),
                (_("Gateway"), self.format_gateways(payload.get("IPAM", {}).get("Config") or [])),
            ]))
            connectivity = self.build_detail_group_rows(_("Connectivity"))
            connectivity.add(self.build_detail_row(_("Internal"), _("Yes") if payload.get("Internal") else _("No")))
            connectivity.add(self.build_detail_row(_("Attachable"), _("Yes") if payload.get("Attachable") else _("No")))
            containers = payload.get("Containers") or {}
            if containers:
                for container_id, item in containers.items():
                    connectivity.add(self.build_detail_link_row(
                        _("Container"),
                        item.get("Name", item.get("EndpointID", "")[:12]),
                        "container",
                        container_id,
                    ))
            else:
                connectivity.add(self.build_detail_row(_("Containers"), "-"))
            root.append(connectivity)
        return root

    def build_detail_summary_card(self, resource_type: str, payload: dict) -> Gtk.Widget:
        card = Adw.Bin()
        card.add_css_class("card")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.add_css_class("detail-summary-card")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top.set_valign(Gtk.Align.CENTER)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_box.set_hexpand(True)

        title_label = Gtk.Label(xalign=0)
        title_label.add_css_class("detail-summary-title")
        subtitle_label = Gtk.Label(xalign=0)
        subtitle_label.add_css_class("detail-summary-subtitle")
        subtitle_label.set_wrap(True)

        title, subtitle, status = self.detail_summary_header(resource_type, payload)
        title_label.set_label(title)
        subtitle_label.set_label(subtitle)

        title_box.append(title_label)
        if subtitle and subtitle != "-":
            title_box.append(subtitle_label)

        top.append(title_box)
        if status:
            chip = Gtk.Label(label=status)
            self.apply_status_css(chip, status)
            top.append(chip)

        content.append(top)

        facts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        facts.add_css_class("detail-facts")
        for label, value in self.detail_summary_facts(resource_type, payload):
            facts.append(self.build_detail_fact(label, value))
        content.append(facts)

        card.set_child(content)
        return card

    def detail_summary_header(self, resource_type: str, payload: dict) -> tuple[str, str, str | None]:
        if resource_type == "container":
            return (
                payload.get("Name", "").lstrip("/") or "-",
                payload.get("Config", {}).get("Image") or "-",
                payload.get("State", {}).get("Status"),
            )
        if resource_type == "image":
            return (self.primary_image_tag(payload), payload.get("Id", "")[:24], None)
        if resource_type == "volume":
            return (payload.get("Name") or "-", payload.get("Mountpoint") or "-", None)
        return (payload.get("Name") or "-", self.format_stack_name(payload.get("Labels") or {}), None)

    def detail_summary_facts(self, resource_type: str, payload: dict) -> list[tuple[str, str]]:
        if resource_type == "container":
            return [
                (_("Created"), self.format_detail_value(payload.get("Created"))),
                (_("Ports"), self.format_ports(payload.get("NetworkSettings", {}).get("Ports"))),
                (_("Networks"), self.format_network_names(payload.get("NetworkSettings", {}).get("Networks") or {})),
                (_("Restart"), payload.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") or _("none")),
            ]
        if resource_type == "image":
            return [
                (_("Used"), _("Yes") if self.image_payload_in_use(payload) else _("No")),
                (_("Tags"), str(len(payload.get("RepoTags") or []))),
                (_("Size"), self.format_bytes_label(payload.get("Size"))),
                (_("Created"), self.format_detail_value(payload.get("Created"))),
            ]
        if resource_type == "volume":
            return [
                (_("Driver"), payload.get("Driver") or "-"),
                (_("Scope"), payload.get("Scope") or "-"),
                (_("Created"), self.format_detail_value(payload.get("CreatedAt"))),
            ]
        return [
            (_("Driver"), payload.get("Driver") or "-"),
            (_("IPv4"), self.format_network_family(payload.get("IPAM", {}).get("Config") or [], ipv6=False)),
            (_("IPv6"), self.format_network_family(payload.get("IPAM", {}).get("Config") or [], ipv6=True)),
            (_("Containers"), str(len(payload.get("Containers") or {}))),
        ]

    def build_detail_fact(self, title: str, value: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("detail-fact")
        box.set_hexpand(True)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("detail-fact-title")

        text = self.format_detail_value(value)
        value_label = self.build_truncated_label(text)
        value_label.add_css_class("detail-fact-value")
        value_label.set_xalign(0)
        value_label.set_tooltip_text(text)

        box.append(title_label)
        box.append(value_label)
        return box

    def build_detail_group(self, title: str, pairs: list[tuple[str, str]]) -> Gtk.Widget:
        group = self.build_detail_group_rows(title)
        for key, value in pairs:
            if value is None:
                continue
            group.add(self.build_detail_row(key, self.format_detail_value(value)))
        return group

    def build_detail_group_rows(self, title: str) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title(title)
        return group

    def build_detail_row(self, title: str, value: str) -> Gtk.Widget:
        row = Adw.ActionRow(title=title)
        value_label = self.build_truncated_label(value)
        value_label.set_selectable(True)
        row.add_suffix(value_label)
        row.set_activatable(False)
        return row

    def build_detail_link_row(self, title: str, value: str, resource_type: str, resource_id: str) -> Gtk.Widget:
        row = Adw.ActionRow(title=title)
        value_label = self.build_truncated_label(value)
        value_label.set_selectable(True)
        row.add_suffix(value_label)
        button = Gtk.Button(icon_name="go-next-symbolic")
        button.add_css_class("flat")
        button.set_tooltip_text(_("Open related resource"))
        button.connect("clicked", lambda *_args: self.open_detail(resource_type, resource_id))
        row.add_suffix(button)
        row.set_activatable(True)
        row.connect("activated", lambda *_args: self.open_detail(resource_type, resource_id))
        return row

    def format_detail_value(self, value) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if value is None:
            return "-"
        return str(value)

    def format_ports(self, ports: dict | None) -> str:
        if not ports:
            return "-"
        formatted = []
        for port, mappings in ports.items():
            if not mappings:
                formatted.append(port)
            else:
                targets = [f"{item.get('HostIp')}:{item.get('HostPort')}" for item in mappings]
                formatted.append(f"{port} -> {', '.join(targets)}")
        return "; ".join(formatted)

    def first_network_ip(self, networks: dict) -> str:
        for config in networks.values():
            ip_address = config.get("IPAddress")
            if ip_address:
                return ip_address
        return "-"

    def format_mounts(self, mounts: list[dict]) -> str:
        if not mounts:
            return "-"
        return "; ".join(
            f"{mount.get('Source', '-')}" f" -> {mount.get('Destination', '-')}"
            for mount in mounts
        )

    def mount_rows(self, mounts: list[dict]) -> list[Gtk.Widget]:
        if not mounts:
            return [self.build_detail_row(_("Mounts"), "-")]
        rows = []
        for mount in mounts:
            source = mount.get("Name") or mount.get("Source") or "-"
            destination = mount.get("Destination") or "-"
            mount_type = mount.get("Type") or "-"
            label = f"{source} -> {destination}"
            if mount_type == "volume" and mount.get("Name"):
                rows.append(self.build_detail_link_row(_("Volume"), label, "volume", mount.get("Name")))
            else:
                rows.append(self.build_detail_row(_("Mount"), f"{label} ({mount_type})"))
        return rows

    def format_labels(self, labels: dict) -> str:
        if not labels:
            return "-"
        return ", ".join(f"{key}={value}" for key, value in labels.items())

    def format_stack_name(self, labels: dict) -> str:
        if not labels:
            return "-"
        return (
            labels.get("com.docker.compose.project")
            or labels.get("io.podman.compose.project")
            or self.format_labels(labels)
        )

    def format_network_names(self, networks: dict) -> str:
        if not networks:
            return "-"
        return ", ".join(networks.keys())

    def format_network_family(self, config_list: list[dict], ipv6: bool) -> str:
        values = []
        for item in config_list:
            subnet = item.get("Subnet")
            if subnet and (":" in subnet) == ipv6:
                values.append(subnet)
        return ", ".join(values) or "-"

    def format_gateways(self, config_list: list[dict]) -> str:
        gateways = [item.get("Gateway") for item in config_list if item.get("Gateway")]
        return ", ".join(gateways) or "-"

    def format_network_containers(self, containers: dict) -> str:
        if not containers:
            return "-"
        return ", ".join(item.get("Name", key) for key, item in containers.items())

    def image_payload_in_use(self, payload: dict) -> bool:
        image_id = payload.get("Id")
        return any(container.image_id == image_id for container in self.containers)

    def containers_using_image(self, image_id: str) -> list:
        return [container for container in self.containers if container.image_id == image_id]

    def primary_image_tag(self, payload: dict) -> str:
        tags = payload.get("RepoTags") or []
        if tags:
            return tags[0]
        return payload.get("Id", "")[:24] or "-"

    def container_display_name(self, container) -> str:
        return getattr(container, "display_name", None) or container.name

    def format_command(self, config: dict) -> str:
        entrypoint = config.get("Entrypoint") or []
        cmd = config.get("Cmd") or []
        parts = []
        if isinstance(entrypoint, list):
            parts.extend(entrypoint)
        elif entrypoint:
            parts.append(str(entrypoint))
        if isinstance(cmd, list):
            parts.extend(cmd)
        elif cmd:
            parts.append(str(cmd))
        return " ".join(parts) or "-"

    def format_bytes_label(self, value) -> str:
        if value in (None, "-"):
            return "-"
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.0f} {unit}"
            size /= 1024
        return str(value)

    def build_resource_group(self, title: str, description: str, rows: list[Gtk.Widget]) -> Gtk.Widget:
        group = Adw.PreferencesGroup()
        group.set_title(title)
        group.set_description(description)
        for row in rows:
            group.add(row)
        return group

    def build_summary_card(self, title: str, body: str) -> Gtk.Widget:
        card = Adw.Bin()
        card.add_css_class("card")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("resource-title")
        body_label = Gtk.Label(label=body, xalign=0)
        body_label.set_wrap(True)
        body_label.add_css_class("resource-subtitle")

        content.append(title_label)
        content.append(body_label)
        card.set_child(content)
        return card

    def build_resource_row(self, title: str, subtitle: str, status: str) -> Gtk.Widget:
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        status_label = Gtk.Label(label=status)
        self.apply_status_css(status_label, status)
        row.add_suffix(status_label)
        row.set_activatable(False)
        return row

    def select_section(self, section_id: str) -> None:
        if not self.docker_available:
            return
        if section_id != SECTION_CONTAINERS:
            self.collapse_container_logs()
        was_in_detail = self.selected_detail is not None
        self.selected_detail = None
        self.detail_history = []
        self.detail_loading = False
        self.detail_error = ""
        self.detail_payload = None
        self.detail_title = ""
        self.detail_subtitle = ""
        if was_in_detail or not hasattr(self, "stack"):
            self.set_content_widget(self.build_content_area())
        self.stack.set_visible_child_name(section_id)
        self.config.set("last_view", section_id)
        self.update_sidebar_selection(section_id)
        if hasattr(self, "update_content_header"):
            self.update_content_header()
        self.sync_search_ui_for_section(section_id)

    def sync_search_ui_for_section(self, section_id: str) -> None:
        if not hasattr(self, "global_search_entry"):
            return
        self.global_search_entry.set_placeholder_text(self.search_placeholder(section_id))
        if hasattr(self, "search_bar") and self.search_bar.get_search_mode():
            desired_text = self.search_queries.get(section_id, "")
            if self.global_search_entry.get_text() != desired_text:
                self.global_search_entry.set_text(desired_text)

    def update_sidebar_selection(self, active_section_id: str) -> None:
        for section_id, row in self.section_rows.items():
            if section_id == active_section_id:
                row.add_css_class("nav-row-active")
            else:
                row.remove_css_class("nav-row-active")

    def on_section_activated(self, _row, section_id: str) -> None:
        self.select_section(section_id)
        if self.split_view.get_collapsed():
            self.split_view.set_show_content(True)

    def on_refresh(self, *_args) -> None:
        if self.is_refreshing:
            self.pending_refresh = True
            return
        self.set_refreshing(True)
        self.run_in_background(
            self.collect_docker_state,
            self.finish_refresh,
            self.finish_refresh_with_error,
        )

    def run_in_background(self, worker, on_success, on_error=None, on_done=None) -> None:
        def target() -> None:
            try:
                result = worker()
            except Exception as exc:
                if on_error is not None:
                    GLib.idle_add(on_error, exc)
            else:
                GLib.idle_add(on_success, result)
            finally:
                if on_done is not None:
                    GLib.idle_add(on_done)

        threading.Thread(target=target, daemon=True).start()

    def finish_refresh(self, state: dict) -> bool:
        self.apply_docker_state(state)
        self.events_since = int(time.time())
        self.has_loaded_state = True
        self.set_sidebar_widget(self.build_sidebar())
        self.set_content_widget(self.build_content_area())
        if self.selected_detail is None and self.docker_available:
            self.select_section(self.config.get("last_view", SECTION_CONTAINERS))
        elif self.selected_detail is not None and self.docker_available:
            self.load_selected_detail()

        self.set_refreshing(False)
        if self.pending_refresh:
            self.pending_refresh = False
            self.on_refresh()
        return False

    def finish_refresh_with_error(self, exc: Exception) -> bool:
        message = str(exc)
        self.apply_docker_state(
            {
                "docker_available": False,
                "startup_message": _("%(reason)s Start Docker locally and try again.") % {"reason": message},
                "containers": [],
                "images": [],
                "volumes": [],
                "networks": [],
                "active_connection_status": "failed",
            }
        )
        self.events_since = int(time.time())
        self.has_loaded_state = True
        self.set_sidebar_widget(self.build_sidebar())
        self.set_content_widget(self.build_content_area())
        self.set_refreshing(False)
        if self.pending_refresh:
            self.pending_refresh = False
            self.on_refresh()
        return False

    def current_scroll_value(self) -> float | None:
        scroller = self.find_active_scroller(self.content_page.get_child())
        if scroller is None:
            return None
        return scroller.get_vadjustment().get_value()

    def restore_scroll_value(self, value: float | None) -> None:
        if value is None:
            return

        def apply():
            scroller = self.find_active_scroller(self.content_page.get_child())
            if scroller is None:
                return False
            adjustment = scroller.get_vadjustment()
            upper = adjustment.get_upper()
            page_size = adjustment.get_page_size()
            adjustment.set_value(min(value, max(0.0, upper - page_size)))
            return False

        GLib.idle_add(apply)

    def find_active_scroller(self, widget: Gtk.Widget | None) -> Gtk.ScrolledWindow | None:
        if widget is None:
            return None
        if isinstance(widget, Gtk.ScrolledWindow):
            return widget
        if isinstance(widget, Gtk.Stack):
            return self.find_active_scroller(widget.get_visible_child())

        child = widget.get_first_child()
        while child is not None:
            found = self.find_active_scroller(child)
            if found is not None:
                return found
            child = child.get_next_sibling()
        return None

    def rebuild_content_preserving_scroll(self, section_id: str) -> None:
        scroll_value = self.current_scroll_value()
        self.set_content_widget(self.build_content_area())
        self.select_section(section_id)
        self.restore_scroll_value(scroll_value)

    def selected_ids_for_section(self, section_id: str) -> set[str]:
        return {
            SECTION_CONTAINERS: self.selected_container_ids,
            SECTION_IMAGES: self.selected_image_ids,
            SECTION_NETWORKS: self.selected_network_ids,
            SECTION_VOLUMES: self.selected_volume_ids,
        }[section_id]

    def selection_column_visible(self, section_id: str) -> bool:
        return bool(self.selected_ids_for_section(section_id))

    def is_row_selected(self, section_id: str, resource_id: str) -> bool:
        return resource_id in self.selected_ids_for_section(section_id)

    def toggle_row_selection(self, section_id: str, resource_id: str) -> None:
        was_visible = self.selection_column_visible(section_id)
        selected_ids = self.selected_ids_for_section(section_id)
        if resource_id in selected_ids:
            selected_ids.remove(resource_id)
        else:
            selected_ids.add(resource_id)
        self.update_selection_ui(section_id, resource_id, was_visible)

    def set_row_selected(self, section_id: str, resource_id: str, selected: bool) -> None:
        was_visible = self.selection_column_visible(section_id)
        selected_ids = self.selected_ids_for_section(section_id)
        already_selected = resource_id in selected_ids
        if selected == already_selected:
            return
        if selected:
            selected_ids.add(resource_id)
        else:
            selected_ids.discard(resource_id)
        self.update_selection_ui(section_id, resource_id, was_visible)

    def update_selection_ui(self, section_id: str, resource_id: str, was_visible: bool) -> None:
        is_visible = self.selection_column_visible(section_id)
        if was_visible != is_visible:
            self.rebuild_content_preserving_scroll(section_id)
            return

        summary = self.selection_summary_labels.get(section_id)
        if summary is not None:
            summary.set_label(
                _("%(count)s selected") % {"count": len(self.selected_ids_for_section(section_id))}
            )

        check = self.selection_checkbuttons.get(section_id, {}).get(resource_id)
        if check is not None:
            desired = self.is_row_selected(section_id, resource_id)
            if check.get_active() != desired:
                check.set_active(desired)

    def selection_action_specs(self, section_id: str) -> list[tuple[str, object, bool]]:
        actions = [
            (_("Select all"), lambda section_id=section_id: self.select_all_rows(section_id), False),
            (_("Clear selection"), lambda section_id=section_id: self.clear_selection(section_id), False),
        ]
        if section_id == SECTION_CONTAINERS:
            actions.extend(
                [
                    (_("Start"), lambda: self.run_bulk_container_action("start"), False),
                    (_("Stop"), lambda: self.run_bulk_container_action("stop"), False),
                    (_("Restart"), lambda: self.run_bulk_container_action("restart"), False),
                    (_("Pause"), lambda: self.run_bulk_container_action("pause"), False),
                ]
            )
        actions.append((_("Delete"), lambda section_id=section_id: self.delete_selected(section_id), True))
        return actions

    def select_all_rows(self, section_id: str) -> None:
        selected_ids = self.selected_ids_for_section(section_id)
        selected_ids.clear()
        if section_id == SECTION_CONTAINERS:
            selected_ids.update(container.id for container in self.containers)
        elif section_id == SECTION_IMAGES:
            selected_ids.update(image.full_id for image in self.images)
        elif section_id == SECTION_NETWORKS:
            selected_ids.update(network.id for network in self.networks)
        elif section_id == SECTION_VOLUMES:
            selected_ids.update(volume.name for volume in self.volumes)
        self.set_content_widget(self.build_content_area())
        self.select_section(section_id)

    def clear_selection(self, section_id: str) -> None:
        self.selected_ids_for_section(section_id).clear()
        self.set_content_widget(self.build_content_area())
        self.select_section(section_id)

    def delete_selected(self, section_id: str) -> None:
        count = len(self.selected_ids_for_section(section_id))
        if count == 0:
            return

        section_title = self.bulk_section_label(section_id, count)
        self.confirm_action(
            _("Delete selected items?"),
            _("This will delete %(count)s selected %(section)s.") % {
                "count": count,
                "section": section_title,
            },
            _("Delete"),
            lambda: self._delete_selected(section_id),
        )

    def _delete_selected(self, section_id: str) -> None:
        if section_id == SECTION_CONTAINERS:
            self.run_bulk_container_action("delete")
            return
        if section_id == SECTION_IMAGES:
            self.run_bulk_action(section_id, self.selected_image_ids, self.on_image_action)
            return
        if section_id == SECTION_NETWORKS:
            self.run_bulk_action(section_id, self.selected_network_ids, self.on_network_action)
            return
        if section_id == SECTION_VOLUMES:
            self.run_bulk_action(section_id, self.selected_volume_ids, self.on_volume_action)

    def run_bulk_container_action(self, action_name: str) -> None:
        count = len(self.selected_container_ids)
        if count == 0:
            return

        if action_name in {"start", "stop", "restart", "pause", "unpause"}:
            self.confirm_action(
                self.bulk_action_heading(action_name, count),
                self.bulk_action_body(action_name, count),
                self.bulk_action_confirm_label(action_name),
                lambda: self.run_bulk_action(
                    SECTION_CONTAINERS,
                    self.selected_container_ids,
                    self.on_container_action,
                    action_name,
                ),
            )
            return

        self.run_bulk_action(SECTION_CONTAINERS, self.selected_container_ids, self.on_container_action, action_name)

    def run_bulk_action(self, section_id: str, selected_ids: set[str], handler, action_name: str = "delete") -> None:
        resource_ids = list(selected_ids)
        if not resource_ids:
            return

        self.set_refreshing(True)

        def worker():
            success_count = 0
            failures: list[tuple[str, str]] = []
            for resource_id in resource_ids:
                try:
                    handler(
                        action_name,
                        resource_id,
                        refresh_ui=False,
                        require_confirmation=False,
                    )
                    success_count += 1
                except Exception as exc:
                    failures.append((self.bulk_resource_label(section_id, resource_id), str(exc)))
            return success_count, failures

        self.run_in_background(
            worker,
            lambda result: self.finish_bulk_action(section_id, action_name, result),
            lambda exc: self.finish_bulk_action_error(exc),
        )

    def finish_bulk_action(self, section_id: str, action_name: str, result: tuple[int, list[tuple[str, str]]]) -> bool:
        success_count, failures = result
        self.set_refreshing(False)
        self.show_bulk_action_summary(section_id, action_name, success_count, failures)
        self.selected_ids_for_section(section_id).clear()
        self.selected_detail = None
        self.detail_history = []
        self.on_refresh()
        return False

    def finish_bulk_action_error(self, exc: Exception) -> bool:
        self.set_refreshing(False)
        self.show_toast(str(exc))
        return False

    def bulk_resource_label(self, section_id: str, resource_id: str) -> str:
        if section_id == SECTION_CONTAINERS:
            for container in self.containers:
                if container.id == resource_id:
                    return container.display_name or container.name or container.short_id
        elif section_id == SECTION_IMAGES:
            for image in self.images:
                if image.full_id == resource_id:
                    return image.title
        elif section_id == SECTION_NETWORKS:
            for network in self.networks:
                if network.id == resource_id:
                    return network.name
        elif section_id == SECTION_VOLUMES:
            for volume in self.volumes:
                if volume.name == resource_id:
                    return volume.name
        return resource_id[:19]

    def bulk_section_label(self, section_id: str, count: int) -> str:
        labels = {
            SECTION_CONTAINERS: (_("container"), _("containers")),
            SECTION_IMAGES: (_("image"), _("images")),
            SECTION_NETWORKS: (_("network"), _("networks")),
            SECTION_VOLUMES: (_("volume"), _("volumes")),
        }
        singular, plural = labels[section_id]
        return singular if count == 1 else plural

    def bulk_action_heading(self, action_name: str, count: int) -> str:
        templates = {
            "start": _("Start selected containers?"),
            "stop": _("Stop selected containers?"),
            "restart": _("Restart selected containers?"),
            "pause": _("Pause selected containers?"),
            "unpause": _("Resume selected containers?"),
        }
        return templates.get(action_name, _("Apply action to selected containers?"))

    def bulk_action_body(self, action_name: str, count: int) -> str:
        templates = {
            "start": _("This will start %(count)s selected container(s)."),
            "stop": _("This will stop %(count)s selected container(s)."),
            "restart": _("This will restart %(count)s selected container(s)."),
            "pause": _("This will pause %(count)s selected container(s)."),
            "unpause": _("This will resume %(count)s selected container(s)."),
        }
        template = templates.get(action_name, _("This will apply the action to %(count)s selected container(s)."))
        return template % {"count": count}

    def bulk_action_confirm_label(self, action_name: str) -> str:
        labels = {
            "start": _("Start"),
            "stop": _("Stop"),
            "restart": _("Restart"),
            "pause": _("Pause"),
            "unpause": _("Resume"),
        }
        return labels.get(action_name, _("Confirm"))

    def show_bulk_action_summary(
        self,
        section_id: str,
        action_name: str,
        success_count: int,
        failures: list[tuple[str, str]],
    ) -> None:
        if not failures:
            self.show_toast(self.bulk_success_message(section_id, action_name, success_count))
            return

        failure_names = ", ".join(name for name, _error in failures[:2])
        if len(failures) > 2:
            failure_names = f"{failure_names}, ..."
        first_error = failures[0][1] if failures else ""
        if first_error:
            if ". " in first_error:
                first_error = first_error.split(". ", 1)[0]
            first_error = first_error.strip().rstrip(".")
        self.show_toast(
            _("%(success)s ok, %(failed)s failed: %(items)s. %(reason)s") % {
                "success": success_count,
                "failed": len(failures),
                "items": failure_names,
                "reason": first_error,
            }
        )
        self.show_bulk_failure_dialog(action_name, failures)

    def bulk_success_message(self, section_id: str, action_name: str, count: int) -> str:
        messages = {
            (SECTION_CONTAINERS, "start"): _("%(count)s container(s) started."),
            (SECTION_CONTAINERS, "stop"): _("%(count)s container(s) stopped."),
            (SECTION_CONTAINERS, "restart"): _("%(count)s container(s) restarted."),
            (SECTION_CONTAINERS, "pause"): _("%(count)s container(s) paused."),
            (SECTION_CONTAINERS, "unpause"): _("%(count)s container(s) resumed."),
            (SECTION_CONTAINERS, "delete"): _("%(count)s container(s) removed."),
            (SECTION_IMAGES, "delete"): _("%(count)s image(s) removed."),
            (SECTION_NETWORKS, "delete"): _("%(count)s network(s) removed."),
            (SECTION_VOLUMES, "delete"): _("%(count)s volume(s) removed."),
        }
        template = messages.get((section_id, action_name), _("%(count)s item(s) completed."))
        return template % {"count": count}

    def show_bulk_failure_dialog(self, action_name: str, failures: list[tuple[str, str]]) -> None:
        details = "\n".join(
            f"• {name}: {error}"
            for name, error in failures[:8]
        )
        if len(failures) > 8:
            details = f"{details}\n…"

        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Some actions failed"))
        dialog.set_body(
            _("%(count)s %(action)s operation(s) could not be completed.\n\n%(details)s") % {
                "count": len(failures),
                "action": self.bulk_action_label(action_name).lower(),
                "details": details,
            }
        )
        dialog.add_response("ok", _("Close"))
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.choose(self, None, lambda *_args: None, None)

    def bulk_action_label(self, action_name: str) -> str:
        return {
            "start": _("Start"),
            "stop": _("Stop"),
            "restart": _("Restart"),
            "pause": _("Pause"),
            "unpause": _("Resume"),
            "delete": _("Delete"),
        }.get(action_name, _("Action"))

    def confirm_action(self, heading: str, body: str, confirm_label: str, on_confirm) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading(heading)
        dialog.set_body(body)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("confirm", confirm_label)
        dialog.set_close_response("cancel")
        dialog.set_default_response("cancel")
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_choice(_dialog, result, _user_data):
            try:
                response = dialog.choose_finish(result)
            except GLib.Error:
                return
            if response == "confirm":
                on_confirm()

        dialog.choose(self, None, on_choice, None)

    def show_info_dialog(self, heading: str, body: str, close_label: str = "") -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading(heading)
        dialog.set_body(body)
        dialog.add_response("ok", close_label or _("Close"))
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.choose(self, None, lambda *_args: None, None)

    def build_dialog_content(self) -> Gtk.Box:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        return content

    def add_labeled_entry(self, parent: Gtk.Box, title: str, placeholder: str = "", text: str = "") -> Gtk.Entry:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("dialog-field-label")
        row.append(label)
        entry = Gtk.Entry()
        entry.set_placeholder_text(placeholder)
        entry.set_text(text)
        row.append(entry)
        parent.append(row)
        return entry

    def add_labeled_dropdown(
        self,
        parent: Gtk.Box,
        title: str,
        options: list[str],
        selected: int = 0,
    ) -> Gtk.DropDown:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("dialog-field-label")
        row.append(label)
        model = Gtk.StringList()
        for option in options:
            model.append(option)
        dropdown = Gtk.DropDown(model=model)
        dropdown.set_selected(selected)
        row.append(dropdown)
        parent.append(row)
        return dropdown

    def add_labeled_switch(self, parent: Gtk.Box, title: str, active: bool) -> Gtk.Switch:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("dialog-field-label")
        label.set_hexpand(True)
        switch = Gtk.Switch()
        switch.set_active(active)
        row.append(label)
        row.append(switch)
        parent.append(row)
        return switch

    def run_background_operation(self, worker, success_message: str, refresh_after: bool = True) -> None:
        self.set_refreshing(True)

        def on_success(_result) -> bool:
            self.set_refreshing(False)
            self.show_toast(success_message)
            if refresh_after:
                self.on_refresh()
            return False

        def on_error(exc: Exception) -> bool:
            self.set_refreshing(False)
            self.show_toast(str(exc))
            return False

        self.run_in_background(worker, on_success, on_error)

    def count_pruned_items(self, payload: dict, key: str) -> int:
        items = payload.get(key) or []
        return len(items)

    def prune_result_labels(self, resource_kind: str, count: int) -> tuple[str, str]:
        labels = {
            "images": (_("image"), _("images")),
            "volumes": (_("volume"), _("volumes")),
            "networks": (_("network"), _("networks")),
        }
        singular, plural = labels.get(resource_kind, (_("item"), _("items")))
        noun = singular if count == 1 else plural
        return noun, noun

    def prune_summary_text(self, resource_kind: str, count: int, space_reclaimed: int | None = None) -> str:
        noun, _ = self.prune_result_labels(resource_kind, count)
        message = _("%(count)s unused %(resource)s removed.") % {
            "count": count,
            "resource": noun,
        }
        if space_reclaimed:
            message = _("%(message)s %(space)s reclaimed.") % {
                "message": message,
                "space": self.format_bytes_label(space_reclaimed),
            }
        return message

    def prune_confirmation_body(self, resource_kind: str) -> str:
        messages = {
            "images": _("This will remove all images not currently used by any container. This action cannot be undone."),
            "volumes": _("This will remove all volumes not currently used by any container. This action cannot be undone."),
            "networks": _(
                "This will remove all networks not currently used by containers. Default system networks are preserved by Docker."
            ),
        }
        return messages.get(resource_kind, _("This action cannot be undone."))

    def run_prune_operation(self, worker, resource_kind: str, result_key: str) -> None:
        self.set_refreshing(True)

        def on_success(result: dict) -> bool:
            self.set_refreshing(False)
            count = self.count_pruned_items(result, result_key)
            summary = self.prune_summary_text(resource_kind, count, result.get("SpaceReclaimed"))
            if count == 0:
                self.show_toast(_("No unused %(resource)s found.") % {"resource": resource_kind})
            else:
                self.show_info_dialog(_("Prune completed"), summary)
            self.on_refresh()
            return False

        def on_error(exc: Exception) -> bool:
            self.set_refreshing(False)
            self.show_toast(str(exc))
            return False

        self.run_in_background(worker, on_success, on_error)

    def prune_unused_images(self) -> None:
        self.confirm_action(
            _("Prune unused images"),
            self.prune_confirmation_body("images"),
            _("Prune"),
            lambda: self.run_prune_operation(
                lambda: self.docker_service.prune_images(self.active_connection),
                "images",
                "ImagesDeleted",
            ),
        )

    def prune_unused_volumes(self) -> None:
        self.confirm_action(
            _("Prune unused volumes"),
            self.prune_confirmation_body("volumes"),
            _("Prune"),
            lambda: self.run_prune_operation(
                lambda: self.docker_service.prune_volumes(self.active_connection),
                "volumes",
                "VolumesDeleted",
            ),
        )

    def prune_unused_networks(self) -> None:
        self.confirm_action(
            _("Prune unused networks"),
            self.prune_confirmation_body("networks"),
            _("Prune"),
            lambda: self.run_prune_operation(
                lambda: self.docker_service.prune_networks(self.active_connection),
                "networks",
                "NetworksDeleted",
            ),
        )

    def show_pull_image_dialog(self) -> None:
        dialog = Gtk.Dialog(transient_for=self, modal=True, title=_("Pull image"))
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Pull"), Gtk.ResponseType.ACCEPT)
        content = self.build_dialog_content()
        entry = self.add_labeled_entry(content, _("Image reference"), _("nginx:latest"))
        dialog.get_content_area().append(content)

        def on_response(_dialog, response_id) -> None:
            try:
                if response_id != Gtk.ResponseType.ACCEPT:
                    return
                image_ref = entry.get_text().strip()
                if not image_ref:
                    self.show_toast(_("The image reference cannot be empty."))
                    return
                self.run_background_operation(
                    lambda: self.docker_service.pull_image(self.active_connection, image_ref),
                    _("Image pulled."),
                )
            finally:
                dialog.destroy()

        dialog.connect("response", on_response)
        dialog.present()

    def pull_image_reference(self, image_ref: str) -> None:
        if not image_ref or image_ref == "<none>":
            self.show_toast(_("This image has no pullable tag."))
            return
        self.run_background_operation(
            lambda: self.docker_service.pull_image(self.active_connection, image_ref),
            _("Image pulled."),
        )

    def show_create_volume_dialog(self) -> None:
        dialog = Gtk.Dialog(transient_for=self, modal=True, title=_("Create volume"))
        dialog.set_resizable(False)
        dialog.set_default_size(360, -1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        intro = Gtk.Label(
            label=_("Create a local Docker volume. The mount point is assigned automatically by Docker."),
            xalign=0,
        )
        intro.set_wrap(True)
        intro.add_css_class("resource-subtitle")
        content.append(intro)

        name_entry = self.add_labeled_entry(content, _("Volume name"), _("my-data"))
        name_entry.set_activates_default(True)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        actions.set_halign(Gtk.Align.END)
        actions.set_margin_top(4)

        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", lambda *_args: dialog.destroy())

        create_button = Gtk.Button(label=_("Create"))
        create_button.add_css_class("suggested-action")

        def submit() -> None:
            self.run_background_operation(
                lambda: self.docker_service.create_volume(
                    self.active_connection,
                    name_entry.get_text(),
                ),
                _("Volume created."),
            )
            dialog.destroy()

        create_button.connect("clicked", lambda *_args: submit())
        actions.append(cancel_button)
        actions.append(create_button)
        content.append(actions)

        dialog.set_default_widget(create_button)
        dialog.get_content_area().append(content)
        name_entry.grab_focus()
        dialog.present()

    def show_create_network_dialog(self) -> None:
        dialog = Gtk.Dialog(transient_for=self, modal=True, title=_("Create network"))
        dialog.set_resizable(False)
        dialog.set_default_size(400, -1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        intro = Gtk.Label(
            label=_("Create a local Docker network for container communication."),
            xalign=0,
        )
        intro.set_wrap(True)
        intro.add_css_class("resource-subtitle")
        content.append(intro)

        name_entry = self.add_labeled_entry(content, _("Network name"), _("my-network"))
        name_entry.set_activates_default(True)
        driver_options = ["bridge", "macvlan", "ipvlan"]
        driver_dropdown = self.add_labeled_dropdown(content, _("Driver"), driver_options, selected=0)
        internal_switch = self.add_labeled_switch(content, _("Internal"), False)
        attachable_switch = self.add_labeled_switch(content, _("Attachable"), False)
        ipv6_switch = self.add_labeled_switch(content, _("Enable IPv6"), False)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        actions.set_halign(Gtk.Align.END)
        actions.set_margin_top(4)

        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", lambda *_args: dialog.destroy())

        create_button = Gtk.Button(label=_("Create"))
        create_button.add_css_class("suggested-action")

        def submit() -> None:
            driver = driver_options[driver_dropdown.get_selected()]
            self.run_background_operation(
                lambda: self.docker_service.create_network(
                    self.active_connection,
                    name_entry.get_text(),
                    driver,
                    internal_switch.get_active(),
                    attachable_switch.get_active(),
                    ipv6_switch.get_active(),
                ),
                _("Network created."),
            )
            dialog.destroy()

        create_button.connect("clicked", lambda *_args: submit())
        actions.append(cancel_button)
        actions.append(create_button)
        content.append(actions)

        dialog.set_default_widget(create_button)
        dialog.get_content_area().append(content)
        name_entry.grab_focus()
        dialog.present()

    def on_container_sort_requested(self, sort_key: str) -> None:
        if self.container_sort_key == sort_key:
            self.container_sort_desc = not self.container_sort_desc
        else:
            self.container_sort_key = sort_key
            self.container_sort_desc = sort_key == "created"
        self.set_content_widget(self.build_content_area())
        self.select_section(SECTION_CONTAINERS)

    def on_image_sort_requested(self, sort_key: str) -> None:
        if self.image_sort_key == sort_key:
            self.image_sort_desc = not self.image_sort_desc
        else:
            self.image_sort_key = sort_key
            self.image_sort_desc = sort_key == "created"
        self.set_content_widget(self.build_content_area())
        self.select_section(SECTION_IMAGES)

    def on_network_sort_requested(self, sort_key: str) -> None:
        if self.network_sort_key == sort_key:
            self.network_sort_desc = not self.network_sort_desc
        else:
            self.network_sort_key = sort_key
            self.network_sort_desc = False
        self.set_content_widget(self.build_content_area())
        self.select_section(SECTION_NETWORKS)

    def on_volume_sort_requested(self, sort_key: str) -> None:
        if self.volume_sort_key == sort_key:
            self.volume_sort_desc = not self.volume_sort_desc
        else:
            self.volume_sort_key = sort_key
            self.volume_sort_desc = sort_key == "created"
        self.set_content_widget(self.build_content_area())
        self.select_section(SECTION_VOLUMES)

    def on_close_request(self, *_args) -> bool:
        self.stop_logs_polling()
        self.stop_event_polling()
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            width, height = self.get_default_size()
        self.config.set("window_width", width)
        self.config.set("window_height", height)
        return False

    def apply_color_scheme(self) -> None:
        style_manager = Adw.StyleManager.get_default()
        scheme = self.config.get("color_scheme", "system")
        if scheme == "light":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif scheme == "dark":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def change_theme(self, color_scheme: str) -> None:
        self.config.set("color_scheme", color_scheme)
        self.apply_color_scheme()

    def change_language(self, language_code: str) -> None:
        current_section = self.config.get("last_view", SECTION_CONTAINERS)
        setup_locale(language_code if language_code != "auto" else None)
        self.config.set("language", language_code)
        self.current_language = language_code
        self.set_sidebar_widget(self.build_sidebar())
        self.set_content_widget(self.build_content_area())
        if self.selected_detail is None and self.docker_available:
            self.select_section(current_section)
        self.show_toast(_("Language preference saved. Some interface strings may require a restart until full localization is added."))

    def apply_status_css(self, label: Gtk.Label, status: str) -> None:
        label.add_css_class("status-chip")
        label.add_css_class(status.lower().replace(" ", "-"))

    def current_section_title(self) -> str:
        section_id = self.config.get("last_view", SECTION_CONTAINERS)
        return {
            SECTION_CONTAINERS: _("Containers"),
            SECTION_IMAGES: _("Images"),
            SECTION_NETWORKS: _("Networks"),
            SECTION_VOLUMES: _("Volumes"),
        }.get(section_id, APP_NAME)

    def open_detail(self, resource_type: str, resource_id: str) -> None:
        self.show_detail(resource_type, resource_id, push_history=self.selected_detail is not None)

    def show_detail(self, resource_type: str, resource_id: str, push_history: bool = False) -> None:
        self.collapse_container_logs()
        if push_history and self.selected_detail is not None:
            self.detail_history.append(dict(self.selected_detail))
        self.selected_detail = {"type": resource_type, "id": resource_id}
        self.detail_loading = True
        self.detail_error = ""
        self.detail_payload = None
        self.detail_title = ""
        self.detail_subtitle = ""
        self.set_content_widget(self.build_content_area())
        self.load_selected_detail()

    def close_detail(self) -> None:
        if self.detail_history:
            previous = self.detail_history.pop()
            self.show_detail(previous["type"], previous["id"], push_history=False)
            return

        self.selected_detail = None
        self.detail_loading = False
        self.detail_error = ""
        self.detail_payload = None
        self.detail_title = ""
        self.detail_subtitle = ""
        self.set_content_widget(self.build_content_area())
        if hasattr(self, "stack"):
            self.stack.set_visible_child_name(self.config.get("last_view", SECTION_CONTAINERS))

    def load_selected_detail(self) -> None:
        if self.selected_detail is None:
            return

        resource_type = self.selected_detail["type"]
        resource_id = self.selected_detail["id"]
        self.detail_request_token += 1
        request_token = self.detail_request_token
        self.detail_loading = True
        self.detail_error = ""
        self.detail_payload = None
        self.set_content_widget(self.build_content_area())

        def worker():
            return self.load_detail_payload(resource_type, resource_id)

        self.run_in_background(
            worker,
            lambda result, request_token=request_token: self.finish_detail_load(request_token, result),
            lambda exc, request_token=request_token: self.finish_detail_error(request_token, exc),
        )

    def load_detail_payload(self, resource_type: str, resource_id: str) -> tuple[str, str, dict]:
        if resource_type == "container":
            payload = self.docker_service.inspect_container(self.active_connection, resource_id)
            return payload.get("Name", resource_id).lstrip("/"), _("Container details"), payload
        if resource_type == "image":
            payload = self.docker_service.inspect_image(self.active_connection, resource_id)
            tags = payload.get("RepoTags") or []
            return (tags[0] if tags else resource_id[:19]), _("Image details"), payload
        if resource_type == "volume":
            payload = self.docker_service.inspect_volume(self.active_connection, resource_id)
            return payload.get("Name", resource_id), _("Volume details"), payload
        payload = self.docker_service.inspect_network(self.active_connection, resource_id)
        return payload.get("Name", resource_id), _("Network details"), payload

    def finish_detail_load(self, request_token: int, result: tuple[str, str, dict]) -> bool:
        if request_token != self.detail_request_token or self.selected_detail is None:
            return False

        title, subtitle, payload = result
        self.detail_title = title
        self.detail_subtitle = subtitle
        self.detail_payload = payload
        self.detail_error = ""
        self.detail_loading = False
        self.set_content_widget(self.build_content_area())
        return False

    def finish_detail_error(self, request_token: int, exc: Exception) -> bool:
        if request_token != self.detail_request_token or self.selected_detail is None:
            return False

        self.detail_error = str(exc)
        self.detail_payload = None
        self.detail_loading = False
        self.set_content_widget(self.build_content_area())
        return False

    def container_status_icon(self, status: str) -> str:
        return {
            "running": "media-playback-start-symbolic",
            "exited": "media-playback-stop-symbolic",
            "paused": "media-playback-pause-symbolic",
        }.get(status, "media-record-symbolic")

    def container_action_specs(self, container) -> list[tuple[str, str, str]]:
        status = container.status
        if status == "running":
            return [
                ("view-reveal-symbolic", _("View details"), "detail"),
                ("text-x-log-symbolic", _("Logs"), "logs"),
                ("view-refresh-symbolic", _("Restart"), "restart"),
                ("media-playback-stop-symbolic", _("Stop"), "stop"),
                ("media-playback-pause-symbolic", _("Pause"), "pause"),
                ("user-trash-symbolic", _("Delete"), "delete"),
            ]
        if status == "paused":
            return [
                ("view-reveal-symbolic", _("View details"), "detail"),
                ("text-x-log-symbolic", _("Logs"), "logs"),
                ("view-refresh-symbolic", _("Restart"), "restart"),
                ("media-playback-start-symbolic", _("Resume"), "unpause"),
                ("media-playback-stop-symbolic", _("Stop"), "stop"),
                ("user-trash-symbolic", _("Delete"), "delete"),
            ]
        return [
            ("view-reveal-symbolic", _("View details"), "detail"),
            ("text-x-log-symbolic", _("Logs"), "logs"),
            ("view-refresh-symbolic", _("Restart"), "restart"),
            ("media-playback-start-symbolic", _("Start"), "start"),
            ("media-playback-pause-symbolic", _("Pause"), "pause"),
            ("user-trash-symbolic", _("Delete"), "delete"),
        ]

    def on_container_action(
        self,
        action_name: str,
        container_id: str,
        refresh_ui: bool = True,
        require_confirmation: bool = True,
    ) -> None:
        if action_name == "delete" and require_confirmation:
            container_label = self.bulk_resource_label(SECTION_CONTAINERS, container_id)
            self.confirm_action(
                _("Delete container?"),
                _("This action will permanently remove the container '%(name)s'.") % {
                    "name": container_label,
                },
                _("Delete"),
                lambda: self.on_container_action("delete", container_id, refresh_ui=refresh_ui, require_confirmation=False),
            )
            return
        if not refresh_ui:
            try:
                self.perform_container_action(action_name, container_id)
            except DockerConnectionError as exc:
                raise RuntimeError(str(exc)) from exc
            return

        self.run_resource_action(
            lambda: self.perform_container_action(action_name, container_id),
            self.container_success_message(action_name),
        )

    def perform_container_action(self, action_name: str, container_id: str) -> None:
        if action_name == "start":
            self.docker_service.start_container(self.active_connection, container_id)
        elif action_name == "stop":
            self.docker_service.stop_container(self.active_connection, container_id)
        elif action_name == "restart":
            self.docker_service.restart_container(self.active_connection, container_id)
        elif action_name == "pause":
            self.docker_service.pause_container(self.active_connection, container_id)
        elif action_name == "unpause":
            self.docker_service.unpause_container(self.active_connection, container_id)
        elif action_name == "delete":
            self.docker_service.remove_container(self.active_connection, container_id, force=True)
        else:
            raise RuntimeError(_("Action not supported."))

    def container_success_message(self, action_name: str) -> str:
        return {
            "start": _("Container started."),
            "stop": _("Container stopped."),
            "restart": _("Container restarted."),
            "pause": _("Container paused."),
            "unpause": _("Container resumed."),
            "delete": _("Container removed."),
        }.get(action_name, _("Action completed."))

    def run_resource_action(self, worker, success_message: str) -> None:
        self.set_refreshing(True)

        def on_success(_result) -> bool:
            self.set_refreshing(False)
            self.show_toast(success_message)
            self.selected_detail = None
            self.detail_history = []
            self.on_refresh()
            return False

        def on_error(exc: Exception) -> bool:
            self.set_refreshing(False)
            self.show_toast(str(exc))
            return False

        self.run_in_background(worker, on_success, on_error)

    def on_image_action(
        self,
        action_name: str,
        image_id: str,
        refresh_ui: bool = True,
        require_confirmation: bool = True,
    ) -> None:
        if action_name == "delete" and require_confirmation:
            image_label = self.bulk_resource_label(SECTION_IMAGES, image_id)
            self.confirm_action(
                _("Delete image?"),
                _("This action will permanently remove the image '%(name)s'.") % {
                    "name": image_label,
                },
                _("Delete"),
                lambda: self.on_image_action("delete", image_id, refresh_ui=refresh_ui, require_confirmation=False),
            )
            return
        if not refresh_ui:
            try:
                self.perform_image_action(action_name, image_id)
            except DockerConnectionError as exc:
                raise RuntimeError(str(exc)) from exc
            return

        self.run_resource_action(
            lambda: self.perform_image_action(action_name, image_id),
            _("Image removed."),
        )

    def perform_image_action(self, action_name: str, image_id: str) -> None:
        if action_name != "delete":
            raise RuntimeError(_("Action not supported."))
        self.docker_service.remove_image(self.active_connection, image_id, force=False)

    def on_volume_action(
        self,
        action_name: str,
        volume_name: str,
        refresh_ui: bool = True,
        require_confirmation: bool = True,
    ) -> None:
        if action_name == "delete" and require_confirmation:
            volume_label = self.bulk_resource_label(SECTION_VOLUMES, volume_name)
            self.confirm_action(
                _("Delete volume?"),
                _("This action will permanently remove the volume '%(name)s'.") % {
                    "name": volume_label,
                },
                _("Delete"),
                lambda: self.on_volume_action("delete", volume_name, refresh_ui=refresh_ui, require_confirmation=False),
            )
            return
        if not refresh_ui:
            try:
                self.perform_volume_action(action_name, volume_name)
            except DockerConnectionError as exc:
                raise RuntimeError(str(exc)) from exc
            return

        self.run_resource_action(
            lambda: self.perform_volume_action(action_name, volume_name),
            _("Volume removed."),
        )

    def perform_volume_action(self, action_name: str, volume_name: str) -> None:
        if action_name != "delete":
            raise RuntimeError(_("Action not supported."))
        self.docker_service.remove_volume(self.active_connection, volume_name, force=False)

    def on_network_action(
        self,
        action_name: str,
        network_id: str,
        refresh_ui: bool = True,
        require_confirmation: bool = True,
    ) -> None:
        if action_name == "delete" and require_confirmation:
            network_label = self.bulk_resource_label(SECTION_NETWORKS, network_id)
            self.confirm_action(
                _("Delete network?"),
                _("This action will permanently remove the network '%(name)s'.") % {
                    "name": network_label,
                },
                _("Delete"),
                lambda: self.on_network_action("delete", network_id, refresh_ui=refresh_ui, require_confirmation=False),
            )
            return
        if not refresh_ui:
            try:
                self.perform_network_action(action_name, network_id)
            except DockerConnectionError as exc:
                raise RuntimeError(str(exc)) from exc
            return

        self.run_resource_action(
            lambda: self.perform_network_action(action_name, network_id),
            _("Network removed."),
        )

    def perform_network_action(self, action_name: str, network_id: str) -> None:
        if action_name != "delete":
            raise RuntimeError(_("Action not supported."))
        self.docker_service.remove_network(self.active_connection, network_id)

    def toggle_container_logs(self, container_id: str | None) -> None:
        if not container_id:
            return
        if self.expanded_logs_container_id == container_id:
            self.collapse_container_logs()
            self.set_content_widget(self.build_content_area())
            self.select_section(SECTION_CONTAINERS)
            return

        self.expanded_logs_container_id = container_id
        self.expanded_logs_text = ""
        self.logs_loading = True
        self.logs_fetch_in_progress = False
        self.logs_since = None
        self.fetch_container_logs(initial=True)
        if self.logs_follow_enabled:
            self.start_logs_polling()
        self.set_content_widget(self.build_content_area())
        self.select_section(SECTION_CONTAINERS)

    def collapse_container_logs(self) -> None:
        self.expanded_logs_container_id = None
        self.expanded_logs_text = ""
        self.logs_loading = False
        self.logs_fetch_in_progress = False
        self.logs_text_view = None
        self.logs_scroller = None
        self.logs_since = None
        self.stop_logs_polling()

    def clear_container_logs(self) -> None:
        self.expanded_logs_text = ""
        self.logs_since = int(time.time())
        self.update_logs_view()

    def copy_container_logs(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            self.show_toast(_("Clipboard is not available."))
            return
        display.get_clipboard().set_text(self.expanded_logs_text or "")
        self.show_toast(_("Logs copied to the clipboard."))

    def save_container_logs(self) -> None:
        dialog = Gtk.FileChooserNative.new(
            _("Save logs"),
            self,
            Gtk.FileChooserAction.SAVE,
            _("Save"),
            _("Cancel"),
        )
        dialog.set_current_name("container-logs.txt")
        dialog.connect("response", self.on_save_logs_response)
        dialog.show()

    def on_save_logs_response(self, dialog, response_id) -> None:
        try:
            if response_id != Gtk.ResponseType.ACCEPT:
                return
            file_ = dialog.get_file()
            if file_ is None:
                return
            path = file_.get_path()
            if not path:
                self.show_toast(_("Unable to access the selected file path."))
                return
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.expanded_logs_text or "")
            self.show_toast(_("Logs saved."))
        except OSError as exc:
            self.show_toast(str(exc))
        finally:
            dialog.destroy()

    def on_logs_follow_toggled(self, switch, _param) -> None:
        self.logs_follow_enabled = switch.get_active()
        if self.logs_follow_enabled and self.expanded_logs_container_id:
            self.start_logs_polling()
        else:
            self.stop_logs_polling()

    def on_logs_tail_changed(self, spin_button) -> None:
        self.logs_tail_count = int(spin_button.get_value())

    def current_logs_text(self) -> str:
        if self.logs_loading and not self.expanded_logs_text:
            return _("Loading logs…")
        return self.expanded_logs_text or _("No logs available.")

    def fetch_container_logs(self, initial: bool = False) -> None:
        if not self.expanded_logs_container_id or self.logs_fetch_in_progress:
            return
        container_id = self.expanded_logs_container_id
        since_value = None if initial or self.logs_since is None else self.logs_since
        self.logs_fetch_in_progress = True
        self.logs_loading = initial
        self.logs_request_token += 1
        request_token = self.logs_request_token
        self.update_logs_view(replace=True)

        def worker():
            if since_value is None:
                return True, int(time.time()), self.docker_service.container_logs(
                    self.active_connection,
                    container_id,
                    tail=self.logs_tail_count,
                ).strip()

            return False, int(time.time()), self.docker_service.container_logs(
                self.active_connection,
                container_id,
                since=since_value,
            ).strip()

        self.run_in_background(
            worker,
            lambda result, request_token=request_token, container_id=container_id: self.finish_logs_fetch(
                request_token,
                container_id,
                result,
            ),
            lambda exc, request_token=request_token, container_id=container_id: self.finish_logs_error(
                request_token,
                container_id,
                exc,
            ),
        )

    def update_logs_view(self, replace: bool = True, appended_text: str = "") -> None:
        if not self.logs_text_view:
            return

        buffer_ = self.logs_text_view.get_buffer()
        vadjustment = self.logs_scroller.get_vadjustment() if self.logs_scroller else None
        should_autoscroll = False
        previous_value = 0.0

        if vadjustment is not None:
            previous_value = vadjustment.get_value()
            upper = vadjustment.get_upper()
            page_size = vadjustment.get_page_size()
            should_autoscroll = previous_value >= max(0.0, upper - page_size - 8.0)

        if replace:
            buffer_.set_text(self.current_logs_text())
        elif appended_text:
            end_iter = buffer_.get_end_iter()
            if buffer_.get_char_count() == 0:
                buffer_.insert(end_iter, appended_text.rstrip("\n"))
            else:
                buffer_.insert(end_iter, appended_text)

        if vadjustment is None:
            return

        def restore_scroll():
            upper = vadjustment.get_upper()
            page_size = vadjustment.get_page_size()
            if should_autoscroll:
                vadjustment.set_value(max(0.0, upper - page_size))
            else:
                vadjustment.set_value(min(previous_value, max(0.0, upper - page_size)))
            return False

        GLib.idle_add(restore_scroll)

    def start_logs_polling(self) -> None:
        self.stop_logs_polling()
        self.logs_poll_source_id = GLib.timeout_add_seconds(2, self.poll_container_logs)

    def stop_logs_polling(self) -> None:
        if self.logs_poll_source_id:
            GLib.source_remove(self.logs_poll_source_id)
            self.logs_poll_source_id = None

    def start_event_polling(self) -> None:
        self.stop_event_polling()
        self.event_poll_source_id = GLib.timeout_add_seconds(3, self.poll_docker_events)

    def stop_event_polling(self) -> None:
        if self.event_poll_source_id:
            GLib.source_remove(self.event_poll_source_id)
            self.event_poll_source_id = None

    def poll_docker_events(self) -> bool:
        if self.event_poll_in_progress or self.is_refreshing or not self.has_loaded_state or not self.docker_available:
            return True

        since = self.events_since
        until = int(time.time())
        if until <= since:
            return True

        self.event_poll_in_progress = True

        def worker():
            return until, self.docker_service.list_events(self.active_connection, since, until)

        self.run_in_background(
            worker,
            self.finish_event_poll,
            self.finish_event_poll_error,
        )
        return True

    def finish_event_poll(self, result: tuple[int, list[dict]]) -> bool:
        until, events = result
        self.event_poll_in_progress = False
        self.events_since = until
        if events:
            self.on_refresh()
        return False

    def finish_event_poll_error(self, _exc: Exception) -> bool:
        self.event_poll_in_progress = False
        return False

    def finish_logs_fetch(
        self,
        request_token: int,
        container_id: str,
        result: tuple[bool, int, str],
    ) -> bool:
        if request_token != self.logs_request_token or self.expanded_logs_container_id != container_id:
            return False

        initial, new_since, payload = result
        self.logs_fetch_in_progress = False
        self.logs_loading = False

        if initial:
            self.expanded_logs_text = payload
            self.logs_since = new_since
            self.update_logs_view(replace=True)
            return False

        self.logs_since = new_since
        if not payload:
            self.update_logs_view(replace=True)
            return False

        if self.expanded_logs_text:
            self.expanded_logs_text = f"{self.expanded_logs_text}\n{payload}".strip()
        else:
            self.expanded_logs_text = payload
        self.update_logs_view(replace=False, appended_text=f"{payload}\n")
        return False

    def finish_logs_error(self, request_token: int, container_id: str, exc: Exception) -> bool:
        if request_token != self.logs_request_token or self.expanded_logs_container_id != container_id:
            return False

        self.logs_fetch_in_progress = False
        self.logs_loading = False
        self.expanded_logs_text = str(exc)
        self.update_logs_view(replace=True)
        return False

    def poll_container_logs(self) -> bool:
        if not self.expanded_logs_container_id:
            self.logs_poll_source_id = None
            return False
        self.fetch_container_logs(initial=False)
        return True

    def show_toast(self, message: str) -> None:
        if hasattr(self, "toast_overlay"):
            self.toast_overlay.add_toast(Adw.Toast.new(message))

    @staticmethod
    def normalized_query(window_like, section_id: str) -> str:
        return getattr(window_like, "search_queries", {}).get(section_id, "").strip().lower()

    @staticmethod
    def matches_query(text_parts: list[str], query: str) -> bool:
        if not query:
            return True
        haystack = " ".join(part for part in text_parts if part).lower()
        return query in haystack

    def normalized_query_legacy(self, section_id: str) -> str:
        return getattr(self, "search_queries", {}).get(section_id, "").strip().lower()

    def sorted_containers(self):
        query = DocksWindow.normalized_query(self, SECTION_CONTAINERS)
        containers = [
            container
            for container in self.containers
            if DocksWindow.matches_query(
                [
                    container.name,
                    container.display_name,
                    container.image,
                    container.status,
                    container.short_id,
                ],
                query,
            )
        ]
        if self.container_sort_key == "name":
            containers.sort(key=lambda item: (item.display_name or item.name).lower(), reverse=self.container_sort_desc)
        elif self.container_sort_key == "status":
            order = {"running": 0, "paused": 1, "stopped": 2, "exited": 2}
            containers.sort(
                key=lambda item: (
                    order.get(item.status, 9),
                    -DocksWindow.created_sort_value(item.created_at),
                    (item.display_name or item.name).lower(),
                ),
                reverse=self.container_sort_desc,
            )
        elif self.container_sort_key == "image":
            containers.sort(key=lambda item: item.image.lower(), reverse=self.container_sort_desc)
        elif self.container_sort_key == "created":
            containers.sort(
                key=lambda item: DocksWindow.created_sort_value(item.created_at),
                reverse=self.container_sort_desc,
            )
        return containers

    @staticmethod
    def created_sort_value(created_at: str) -> int:
        try:
            return int(time.mktime(time.strptime(created_at, "%Y-%m-%d %H:%M")))
        except ValueError:
            return 0

    def sorted_images(self):
        query = DocksWindow.normalized_query(self, SECTION_IMAGES)
        images = [
            image
            for image in self.images
            if DocksWindow.matches_query(
                [
                    image.title,
                    image.tags_text,
                    image.full_id,
                    image.created_at,
                ],
                query,
            )
        ]
        if self.image_sort_key == "name":
            images.sort(key=lambda item: item.title.lower(), reverse=self.image_sort_desc)
        elif self.image_sort_key == "used":
            images.sort(
                key=lambda item: (0 if self.image_in_use(item) else 1, item.title.lower()),
                reverse=self.image_sort_desc,
            )
        elif self.image_sort_key == "tags":
            images.sort(key=lambda item: item.tags_text.lower(), reverse=self.image_sort_desc)
        elif self.image_sort_key == "created":
            images.sort(key=lambda item: item.created_at, reverse=self.image_sort_desc)
        return images

    def sorted_networks(self):
        query = DocksWindow.normalized_query(self, SECTION_NETWORKS)
        networks = [
            network
            for network in self.networks
            if DocksWindow.matches_query(
                [
                    network.name,
                    network.stack,
                    network.driver,
                    network.ipv4,
                    network.ipv6,
                ],
                query,
            )
        ]
        if self.network_sort_key == "name":
            networks.sort(key=lambda item: item.name.lower(), reverse=self.network_sort_desc)
        elif self.network_sort_key == "stack":
            networks.sort(key=lambda item: item.stack.lower(), reverse=self.network_sort_desc)
        elif self.network_sort_key == "driver":
            networks.sort(key=lambda item: item.driver.lower(), reverse=self.network_sort_desc)
        elif self.network_sort_key == "ipv4":
            networks.sort(key=lambda item: item.ipv4.lower(), reverse=self.network_sort_desc)
        elif self.network_sort_key == "ipv6":
            networks.sort(key=lambda item: item.ipv6.lower(), reverse=self.network_sort_desc)
        return networks

    def sorted_volumes(self):
        query = DocksWindow.normalized_query(self, SECTION_VOLUMES)
        volumes = [
            volume
            for volume in self.volumes
            if DocksWindow.matches_query(
                [
                    volume.name,
                    volume.driver,
                    volume.mountpoint,
                    volume.created_at,
                ],
                query,
            )
        ]
        if self.volume_sort_key == "name":
            volumes.sort(key=lambda item: item.name.lower(), reverse=self.volume_sort_desc)
        elif self.volume_sort_key == "mountpoint":
            volumes.sort(key=lambda item: item.mountpoint.lower(), reverse=self.volume_sort_desc)
        elif self.volume_sort_key == "created":
            volumes.sort(key=lambda item: item.created_at, reverse=self.volume_sort_desc)
        return volumes

    def image_in_use(self, image) -> bool:
        return any(container.image_id == image.full_id for container in self.containers)

    def collect_docker_state(self) -> dict:
        try:
            ok, message = self.docker_service.ping(self.active_connection)
            if not ok:
                raise DockerConnectionError(message)

            containers = self.docker_service.list_containers(self.active_connection)
            images = self.docker_service.list_images(self.active_connection)
            volumes = self.docker_service.list_volumes(self.active_connection)
            networks = self.docker_service.list_networks(self.active_connection)
            return {
                "docker_available": True,
                "startup_message": "",
                "containers": containers,
                "images": images,
                "volumes": volumes,
                "networks": networks,
                "active_connection_status": "active",
            }
        except DockerConnectionError as exc:
            return {
                "docker_available": False,
                "startup_message": _("%(reason)s Start Docker locally and try again.") % {
                    "reason": exc,
                },
                "containers": [],
                "images": [],
                "volumes": [],
                "networks": [],
                "active_connection_status": "failed",
            }

    def apply_docker_state(self, state: dict) -> None:
        self.containers = state["containers"]
        self.images = state["images"]
        self.volumes = state["volumes"]
        self.networks = state["networks"]
        self.selected_container_ids.intersection_update(container.id for container in self.containers)
        self.selected_image_ids.intersection_update(image.full_id for image in self.images)
        self.selected_volume_ids.intersection_update(volume.name for volume in self.volumes)
        self.selected_network_ids.intersection_update(network.id for network in self.networks)

        if self.expanded_logs_container_id and not any(
            container.id == self.expanded_logs_container_id for container in self.containers
        ):
            self.expanded_logs_container_id = None
            self.expanded_logs_text = ""
            self.logs_loading = False
            self.logs_fetch_in_progress = False
            self.logs_text_view = None
            self.logs_scroller = None
            self.logs_since = None
            self.stop_logs_polling()

        self.docker_available = state["docker_available"]
        self.startup_message = state["startup_message"]
        self.active_connection.status = state["active_connection_status"]
