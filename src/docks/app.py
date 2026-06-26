import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from .core.constants import APP_COPYRIGHT, APP_ID, APP_NAME, APP_VERSION, APP_WEBSITE
from .core.i18n import get_available_languages, translate as _
from .ui.window import DocksWindow


class DocksApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self.on_activate)
        self._window = None
        self.setup_actions()

    def setup_actions(self) -> None:
        language_action = Gio.SimpleAction.new_stateful(
            "language", GLib.VariantType.new("s"), GLib.Variant("s", "auto")
        )
        language_action.connect("activate", self.on_language_changed)
        self.add_action(language_action)

        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self.on_preferences)
        self.add_action(preferences_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about)
        self.add_action(about_action)

    def on_activate(self, _app) -> None:
        from pathlib import Path
        from gi.repository import Gdk
        
        display = Gdk.Display.get_default()
        if display is not None:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            data_dir = Path(__file__).resolve().parents[2] / "data"
            icon_theme.add_search_path(str(data_dir))

        if self._window is None:
            self._window = DocksWindow(application=self)
            language_action = self.lookup_action("language")
            if language_action is not None:
                language_action.set_state(GLib.Variant("s", self._window.current_language))
        self._window.present()

    def on_quit(self, *_args) -> None:
        if self._window is not None:
            self._window.close()
        self.quit()

    def on_language_changed(self, action, parameter) -> None:
        language_code = parameter.get_string()
        action.set_state(parameter)
        if self._window is not None:
            self._window.change_language(language_code)

    def on_preferences(self, *_args) -> None:
        if self._window is None:
            return
        self.show_preferences_dialog()

    def show_preferences_dialog(self) -> None:
        dialog = Adw.PreferencesWindow()
        dialog.set_title(_("Preferences"))
        dialog.set_modal(True)
        dialog.set_transient_for(self._window)

        page = Adw.PreferencesPage()
        page.set_title(_("General"))

        language_group = Adw.PreferencesGroup()
        language_group.set_title(_("Language"))
        language_row = Adw.ComboRow()
        language_row.set_title(_("Interface Language"))
        language_row.set_subtitle(_("Save the preferred application language"))
        language_model = Gtk.StringList()
        available_languages = get_available_languages()
        for _code, label in available_languages:
            language_model.append(label)
        language_row.set_model(language_model)
        lang_codes = [code for code, _label in available_languages]
        current_lang = self._window.current_language
        language_row.set_selected(lang_codes.index(current_lang) if current_lang in lang_codes else 0)
        language_row.connect("notify::selected", self.on_language_row_changed)
        language_group.add(language_row)
        page.add(language_group)

        appearance_group = Adw.PreferencesGroup()
        appearance_group.set_title(_("Appearance"))
        theme_row = Adw.ComboRow()
        theme_row.set_title(_("Color Scheme"))
        theme_row.set_subtitle(_("Choose how Docks follows the desktop theme"))
        theme_model = Gtk.StringList()
        for label in (_("Follow system"), _("Light"), _("Dark")):
            theme_model.append(label)
        theme_row.set_model(theme_model)
        theme_codes = ["system", "light", "dark"]
        current_scheme = self._window.config.get("color_scheme", "system")
        theme_row.set_selected(theme_codes.index(current_scheme) if current_scheme in theme_codes else 0)
        theme_row.connect("notify::selected", self.on_theme_row_changed)
        appearance_group.add(theme_row)
        page.add(appearance_group)

        dialog.add(page)
        dialog.present()

    def on_language_row_changed(self, combo_row, _param) -> None:
        available_languages = get_available_languages()
        selected = combo_row.get_selected()
        if selected < len(available_languages):
            action = self.lookup_action("language")
            if action is not None:
                action.activate(GLib.Variant("s", available_languages[selected][0]))

    def on_theme_row_changed(self, combo_row, _param) -> None:
        theme_codes = ["system", "light", "dark"]
        selected = combo_row.get_selected()
        if self._window is not None and selected < len(theme_codes):
            self._window.change_theme(theme_codes[selected])

    def on_about(self, *_args) -> None:
        if self._window is None:
            return

        dialog = Adw.AboutWindow()
        dialog.set_transient_for(self._window)
        dialog.set_modal(True)
        dialog.set_application_name(_(APP_NAME))
        dialog.set_application_icon(APP_ID)
        dialog.set_version(APP_VERSION)
        dialog.set_developer_name("pabmartine")
        dialog.set_copyright(APP_COPYRIGHT)
        dialog.set_comments(_("Docker desktop client for GNOME built with GTK4 and libadwaita."))
        dialog.set_license_type(Gtk.License.GPL_3_0)
        dialog.set_developers(["pabmartine"])
        dialog.set_website(APP_WEBSITE)
        dialog.present()
