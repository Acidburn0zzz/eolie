# Copyright (c) 2014-2016 Cedric Bellegarde <cedric.bellegarde@adishatz.org>
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.0')
gi.require_version('Soup', '2.4')
gi.require_version('Secret', '1')
from gi.repository import Gtk, Gio, GLib, Gdk, WebKit2

from gettext import gettext as _
from pickle import dump, load

from eolie.settings import Settings, SettingsDialog
from eolie.window import Window
from eolie.art import Art
from eolie.database_history import DatabaseHistory
from eolie.database_bookmarks import DatabaseBookmarks
from eolie.database_adblock import DatabaseAdblock
from eolie.sqlcursor import SqlCursor
from eolie.search import Search
from eolie.download_manager import DownloadManager


class Application(Gtk.Application):
    """
        Eolie application:
    """

    if GLib.getenv("XDG_DATA_HOME") is None:
        __LOCAL_PATH = GLib.get_home_dir() + "/.local/share/eolie"
    else:
        __LOCAL_PATH = GLib.getenv("XDG_DATA_HOME") + "/eolie"
    __COOKIES_PATH = "%s/cookies.db" % __LOCAL_PATH
    __FAVICONS_PATH = "%s/favicons" % __LOCAL_PATH

    def __init__(self, extension_dir):
        """
            Create application
            @param extension_dir as str
        """
        Gtk.Application.__init__(
                            self,
                            application_id='org.gnome.Eolie',
                            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.set_property('register-session', True)
        # Ideally, we will be able to delete this once Flatpak has a solution
        # for SSL certificate management inside of applications.
        if GLib.file_test("/app", GLib.FileTest.EXISTS):
            paths = ["/etc/ssl/certs/ca-certificates.crt",
                     "/etc/pki/tls/cert.pem",
                     "/etc/ssl/cert.pem"]
            for path in paths:
                if GLib.file_test(path, GLib.FileTest.EXISTS):
                    GLib.setenv('SSL_CERT_FILE', path, True)
                    break
        self.__extension_dir = extension_dir
        self.__windows = []
        self.debug = False
        self.cursors = {}
        GLib.set_application_name('Eolie')
        GLib.set_prgname('eolie')
        self.connect('activate', self.__on_activate)
        self.connect('command-line', self.__on_command_line)
        self.register(None)
        if self.get_is_remote():
            Gdk.notify_startup_complete()

    def init(self):
        """
            Init main application
        """
        self.__is_fs = False
        if Gtk.get_minor_version() > 18:
            cssProviderFile = Gio.File.new_for_uri(
                'resource:///org/gnome/Eolie/application.css')
        else:
            cssProviderFile = Gio.File.new_for_uri(
                'resource:///org/gnome/Eolie/application-legacy.css')
        cssProvider = Gtk.CssProvider()
        cssProvider.load_from_file(cssProviderFile)
        screen = Gdk.Screen.get_default()
        styleContext = Gtk.StyleContext()
        styleContext.add_provider_for_screen(screen, cssProvider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.settings = Settings.new()
        self.history = DatabaseHistory()
        self.bookmarks = DatabaseBookmarks()
        # We store cursors for main thread
        SqlCursor.add(self.history)
        SqlCursor.add(self.bookmarks)
        self.adblock = DatabaseAdblock()
        self.adblock.update()
        self.art = Art()
        self.search = Search()
        self.download_manager = DownloadManager()

        shortcut_action = Gio.SimpleAction.new('shortcut',
                                               GLib.VariantType.new('s'))
        shortcut_action.connect('activate', self.__on_shortcut_action)
        self.add_action(shortcut_action)
        self.set_accels_for_action("app.shortcut::uri", ["<Control>l"])
        self.set_accels_for_action("app.shortcut::new_page", ["<Control>t"])
        self.set_accels_for_action("app.shortcut::close_page", ["<Control>w"])
        self.set_accels_for_action("app.shortcut::filter", ["<Control>i"])
        self.set_accels_for_action("app.shortcut::reload", ["<Control>r"])
        self.set_accels_for_action("app.shortcut::find", ["<Control>f"])
        self.set_accels_for_action("app.shortcut::settings", ["<Control>e"])
        self.set_accels_for_action("app.shortcut::backward", ["<Alt>Left"])
        self.set_accels_for_action("app.shortcut::forward", ["<Alt>Right"])
        self.set_accels_for_action("app.shortcut::next", ["<Control>Tab"])
        self.set_accels_for_action("app.shortcut::previous",
                                   ["<Control><Shift>Tab"])

        # Set some WebKit defaults
        context = WebKit2.WebContext.get_default()
        GLib.setenv('PYTHONPATH', self.__extension_dir, True)
        context.set_web_extensions_directory(self.__extension_dir)

        data_manager = WebKit2.WebsiteDataManager()
        context.new_with_website_data_manager(data_manager)
        context.set_process_model(
                            WebKit2.ProcessModel.MULTIPLE_SECONDARY_PROCESSES)
        context.set_cache_model(WebKit2.CacheModel.WEB_BROWSER)
        d = Gio.File.new_for_path(self.__FAVICONS_PATH)
        if not d.query_exists():
            d.make_directory_with_parents()
        context.set_favicon_database_directory(self.__FAVICONS_PATH)
        self.set_cookie_manager(context)

    def do_startup(self):
        """
            Init application
        """
        Gtk.Application.do_startup(self)

        if not self.__windows:
            self.init()
            menu = self.__setup_app_menu()
            if self.prefers_app_menu():
                self.set_app_menu(menu)
                window = Window()
            else:
                window = Window()
                window.setup_menu(menu)
            window.connect('delete-event', self.__on_delete_event)
            window.show()
            self.__windows.append(window)

    def prepare_to_exit(self, action=None, param=None, exit=True):
        """
            Save window position and view
        """
        self.active_window.container.save_position()
        self.download_manager.cancel()
        try:
            session_states = []
            for window in self.__windows:
                for view in window.container.views:
                    uri = view.webview.get_uri()
                    state = view.webview.get_session_state().serialize()
                    session_states.append((uri, state.get_data()))
            dump(session_states,
                 open(self.__LOCAL_PATH + "/session_states.bin", "wb"))
        except Exception as e:
            print("Application::prepare_to_exit()", e)
        if exit:
            self.quit()

    def quit(self):
        """
            Quit Eolie
        """
        for window in self.__windows:
            window.destroy()

    def set_setting(self, key, value):
        """
            Set setting for all view
            @param key as str
            @param value as GLib.Variant
        """
        for window in self.__windows:
            for view in window.container.views:
                view.webview.set_setting(key, value)

    def set_cookie_manager(self, context):
        """
            Set default webkit cookie manager
            @param context as WebKit2.WebContext
        """
        cookie_manager = context.get_cookie_manager()
        cookie_manager.set_accept_policy(
                                     self.settings.get_enum("cookie-storage"))
        cookie_manager.set_persistent_storage(
                                        self.__COOKIES_PATH,
                                        WebKit2.CookiePersistentStorage.SQLITE)

    @property
    def start_page(self):
        """
            Get start page
            @return uri as str
        """
        value = self.settings.get_value('start-page').get_string()
        if value == 'search':
            value = self.search.uri
        elif value == 'popular':
            pass
        return value

    @property
    def active_window(self):
        """
            Get active window
            @return Window
        """
        for window in self.__windows:
            if window.is_active():
                return window
        # Fallback
        if self.__windows:
            return self.__windows[0]
        return None

    @property
    def windows(self):
        """
            Get windows
            @return [Window]
        """
        return self.__windows

    @property
    def cookies_path(self):
        """
            Cookies sqlite db path
        """
        return self.__COOKIES_PATH

#######################
# PRIVATE             #
#######################
    def __restore_state(self):
        """
            Restore saved state
            @return restored pages count as int
        """
        count = 0
        try:
            session_states = load(open(
                                     self.__LOCAL_PATH + "/session_states.bin",
                                     "rb"))
            for (uri, state) in session_states:
                webkit_state = WebKit2.WebViewSessionState(
                                                         GLib.Bytes.new(state))
                GLib.idle_add(self.active_window.container.add_web_view,
                              uri, count == 0, None, None, webkit_state)
                count += 1
        except Exception as e:
            print("Application::restore_state()", e)
        return count

    def __on_command_line(self, app, app_cmd_line):
        """
            Handle command line
            @param app as Gio.Application
            @param options as Gio.ApplicationCommandLine
        """
        self.__externals_count = 0
        args = app_cmd_line.get_arguments()
        options = app_cmd_line.get_options_dict()
        if options.contains('debug'):
            pass
        else:
            if self.settings.get_value("remember-session"):
                count = self.__restore_state()
            else:
                count = 0
            active_window = self.active_window
            if len(args) > 1:
                for uri in args[1:]:
                    active_window.container.add_web_view(uri, True)
                active_window.present()
            elif count == 0:
                active_window.container.add_web_view(self.start_page, True)
        return 0

    def __on_delete_event(self, widget, event):
        """
            Exit application
            @param widget as Gtk.Widget
            @param event as Gdk.Event
        """
        self.prepare_to_exit()

    def __on_settings_activate(self, action, param):
        """
            Show settings dialog
            @param action as Gio.SimpleAction
            @param param as GLib.Variant
        """
        dialog = SettingsDialog()
        dialog.show()

    def __on_about_activate(self, action, param):
        """
            Setup about dialog
            @param action as Gio.SimpleAction
            @param param as GLib.Variant
        """
        builder = Gtk.Builder()
        builder.add_from_resource('/org/gnome/Eolie/AboutDialog.ui')
        about = builder.get_object('about_dialog')
        window = self.active_window
        if window is not None:
            about.set_transient_for(window)
        about.connect("response", self.__on_about_activate_response)
        about.show()

    def __on_shortcuts_activate(self, action, param):
        """
            Show help in yelp
            @param action as Gio.SimpleAction
            @param param as GLib.Variant
        """
        try:
            builder = Gtk.Builder()
            builder.add_from_resource('/org/gnome/Eolie/Shortcuts.ui')
            shortcuts = builder.get_object('shortcuts')
            window = self.active_window
            if window is not None:
                shortcuts.set_transient_for(window)
            shortcuts.show()
        except:  # GTK < 3.20
            self.__on_help_activate(action, param)

    def __on_help_activate(self, action, param):
        """
            Show help in yelp
            @param action as Gio.SimpleAction
            @param param as GLib.Variant
        """
        try:
            Gtk.show_uri(None, "help:eolie", Gtk.get_current_event_time())
        except:
            print(_("Eolie: You need to install yelp."))

    def __on_about_activate_response(self, dialog, response_id):
        """
            Destroy about dialog when closed
            @param dialog as Gtk.Dialog
            @param response id as int
        """
        dialog.destroy()

    def __setup_app_menu(self):
        """
            Setup application menu
            @return menu as Gio.Menu
        """
        builder = Gtk.Builder()
        builder.add_from_resource('/org/gnome/Eolie/Appmenu.ui')
        menu = builder.get_object('app-menu')

        settings_action = Gio.SimpleAction.new('settings', None)
        settings_action.connect('activate', self.__on_settings_activate)
        self.add_action(settings_action)

        about_action = Gio.SimpleAction.new('about', None)
        about_action.connect('activate', self.__on_about_activate)
        self.add_action(about_action)

        shortcuts_action = Gio.SimpleAction.new('shortcuts', None)
        shortcuts_action.connect('activate', self.__on_shortcuts_activate)
        self.add_action(shortcuts_action)

        help_action = Gio.SimpleAction.new('help', None)
        help_action.connect('activate', self.__on_help_activate)
        self.add_action(help_action)

        quit_action = Gio.SimpleAction.new('quit', None)
        quit_action.connect('activate', self.prepare_to_exit)
        self.add_action(quit_action)

        return menu

    def __on_activate(self, application):
        """
            Call default handler, raise last window
            @param application as Gio.Application
        """
        if self.__windows:
            self.__windows[-1].present()

    def __on_shortcut_action(self, action, param):
        """
            Global shortcuts handler
            @param action as Gio.SimpleAction
            @param param as GLib.Variant
        """
        window = self.active_window
        if window is None:
            return
        string = param.get_string()
        if string == "uri":
            window.toolbar.title.focus_entry()
        elif string == "new_page":
            window.container.add_web_view(self.start_page, True)
        elif string == "close_page":
            window.container.sidebar.close_view(window.container.current)
        elif string == "reload":
            window.container.current.webview.reload()
        elif string == "find":
            find_widget = window.container.current.find_widget
            search_mode = find_widget.get_search_mode()
            find_widget.set_search_mode(not search_mode)
            if not search_mode:
                find_widget.grab_focus()
        elif string == "backward":
            window.toolbar.actions.backward()
        elif string == "forward":
            window.toolbar.actions.forward()
        elif string == "settings":
            dialog = SettingsDialog()
            dialog.show()
        elif string == "previous":
            window.container.sidebar.previous()
        elif string == "next":
            window.container.sidebar.next()
        elif string == "filter":
            button = window.toolbar.actions.filter_button
            button.set_active(not button.get_active())
