# Copyright (c) 2017 Cedric Bellegarde <cedric.bellegarde@adishatz.org>
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

from gi.repository import GLib, Gtk, Gio, WebKit2, Gdk

from urllib.parse import urlparse
from time import time

from eolie.define import El, ADBLOCK_JS, WindowType
from eolie.utils import get_ftp_cmd


class WebViewNavigation:
    """
        Implement WebView navigation (uri, title, readable, ...)
        Should be inherited by a WebView
    """

    __MIMES = ["text/html", "text/xml", "application/xhtml+xml",
               "x-scheme-handler/http", "x-scheme-handler/https",
               "multipart/related", "application/x-mimearchive"]

    def __init__(self):
        """
            Init navigation
        """
        self.__js_timeout = None
        self.__title = ""
        self.__popups = []
        self.__initial_uri = None
        self.__insecure_content_detected = False
        self.connect("decide-policy", self.__on_decide_policy)
        self.connect("insecure-content-detected",
                     self.__on_insecure_content_detected)
        self.connect("run-as-modal", self.__on_run_as_modal)
        self.connect("permission_request", self.__on_permission_request)
        self.connect("load-changed", self.__on_load_changed)
        self.connect("notify::favicon", self.__on_notify_favicon)
        self.connect("notify::title", self.__on_title_changed)
        self.connect("notify::uri", self.__on_uri_changed)

    def load_uri(self, uri):
        """
            Load uri
            @param uri as str
        """
        self._error = None
        # If not an URI, start a search
        parsed = urlparse(uri)
        is_uri = parsed.scheme in ["about", "http",
                                   "https", "file", "populars"]
        if not is_uri and\
                not uri.startswith("/") and\
                El().search.is_search(uri):
            uri = El().search.get_search_uri(uri)
        parsed = urlparse(uri)
        if uri == "about:blank":
            WebKit2.WebView.load_plain_text(self, "")
        # We are not a ftp browser, fall back to env
        elif parsed.scheme == "ftp":
            argv = [get_ftp_cmd(), uri, None]
            GLib.spawn_sync(None, argv, None,
                            GLib.SpawnFlags.SEARCH_PATH, None)
        else:
            if uri.startswith("/"):
                uri = "file://" + uri
            elif parsed.scheme == "javascript":
                # To bypass popup blocker
                self._last_click_time = time()
                uri = GLib.uri_unescape_string(uri, None)
                self.run_javascript(uri.replace("javascript:", ""), None, None)
            elif parsed.scheme not in ["http", "https", "file",
                                       "populars", "accept"]:
                uri = "http://" + uri
            # Reset bad tls certificate
            if parsed.scheme != "accept":
                self.reset_bad_tls()
                self.__insecure_content_detected = False
            WebKit2.WebView.load_uri(self, uri)

    def add_popup(self, webview):
        """
            Add webview to popups
            @webview as WebView
        """
        self.__popups.append(webview)

    def remove_popup(self, webview):
        """
            Remove webview to popups
            @webview as WebView
        """
        if webview in self.__popups:
            self.__popups.remove(webview)

    @property
    def initial_uri(self):
        """
            Initialy loaded URI
            When loading an URI, webkit may be redirected and we will
            be unable to set snapshot/favicon in cache.
            @return str
        """
        return self.__initial_uri

    @property
    def popups(self):
        """
            Get popups
            @return [WebView]
        """
        return self.__popups

#######################
# PRIVATE             #
#######################
    def __on_run_as_modal(self, webview):
        """
        """
        print("WebView::__on_run_as_modal(): TODO")

    def __on_insecure_content_detected(self, webview, event):
        """
            @param webview as WebView
            @param event as WebKit2.InsecureContentEvent
        """
        self.__insecure_content_detected = True

    def __on_permission_request(self, webview, request):
        """
            Handle Webkit permissions
            @param webview as WebKit2.WebView
            @param request as WebKit2.PermissionRequest
        """
        if isinstance(request, WebKit2.GeolocationPermissionRequest):
            if self.ephemeral:
                request.deny()
            else:
                uri = webview.get_uri()
                self._window.toolbar.title.show_geolocation(uri, request)
        elif isinstance(request, WebKit2.NotificationPermissionRequest):
            # Can use Gnome Shell notification policy
            request.allow()
        return True

    def __on_uri_changed(self, webview, uri):
        """
            Clear readable context and title
            @param webview as WebKit2.WebView
            @param uri as GParamSpec
        """
        uri = webview.get_uri()
        # JS bookmark (Bookmarklet)
        if not uri.startswith("javascript:"):
            self.__title = ""
            self.emit("uri-changed", uri)

    def __on_title_changed(self, webview, event):
        """
            We launch Readability.js at page loading finished.
            @param webview as WebKit2.WebView
            @param event as GParamSpec
        """
        if event.name != "title":
            return
        title = webview.get_title()
        if not title or title == self.__title:
            return
        self.__title = title
        self.emit("title-changed", title)
        # Js update, force favicon caching for current uri
        if not self.is_loading():
            self.__initial_uri = None
            self.set_favicon(self.get_uri())
        if self.__js_timeout is not None:
            GLib.source_remove(self.__js_timeout)
        self.__js_timeout = GLib.timeout_add(
                             2000,
                             self.__on_js_timeout,
                             "/org/gnome/Eolie/Readability.js")

    def __on_notify_favicon(self, webview, favicon):
        """
            Set favicon
            @param webview as WebView
            @param favicon as Gparam
        """
        self.set_favicon(self.get_uri())

    def __on_js_timeout(self, path):
        """
            Run js
            @param path as str
        """
        self.__js_timeout = None
        self.run_javascript_from_gresource(path, None, None)

    def __on_decide_policy(self, webview, decision, decision_type):
        """
            Navigation policy
            @param webview as WebKit2.WebView
            @param decision as WebKit2.NavigationPolicyDecision
            @param decision_type as WebKit2.PolicyDecisionType
            @return bool
        """
        # Always accept response
        if decision_type == WebKit2.PolicyDecisionType.RESPONSE:
            response = decision.get_response()
            mime_type = response.props.mime_type
            uri = response.get_uri()
            parsed = urlparse(uri)
            if mime_type in self.__MIMES:
                decision.use()
            elif parsed.scheme == "file":
                f = Gio.File.new_for_uri(uri)
                info = f.query_info("standard::type",
                                    Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                    None)
                if info.get_file_type() == Gio.FileType.REGULAR:
                    try:
                        Gtk.show_uri_on_window(self._window,
                                               uri,
                                               Gtk.get_current_event_time())
                    except Exception as e:
                        print("WebViewNavigation::__on_decide_policy()", e)
                    decision.ignore()
                else:
                    decision.use()
            elif self.can_show_mime_type(mime_type):
                decision.use()
            else:
                decision.download()
            return False

        navigation_action = decision.get_navigation_action()
        self._navigation_uri = navigation_action.get_request().get_uri()
        mouse_button = navigation_action.get_mouse_button()
        parsed = urlparse(self._navigation_uri)
        self.clear_text_entry()
        if parsed.scheme not in ["http", "https", "file", "about",
                                 "populars", "accept"]:
            try:
                Gtk.show_uri_on_window(self._window,
                                       self._navigation_uri,
                                       Gtk.get_current_event_time())
            except Exception as e:
                print("WebViewNavigation::__on_decide_policy()", e)
            decision.ignore()
        elif mouse_button == 0:
            # Prevent opening empty pages
            if self._navigation_uri == "about:blank":
                self.ignore_last_click_event()
                decision.use()
                return True
            elif decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                self.new_page(WindowType.FOREGROUND)
                decision.ignore()
                return True
            else:
                decision.use()
                return False
        elif mouse_button == 1:
            if decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                if navigation_action.get_modifiers() &\
                        Gdk.ModifierType.SHIFT_MASK:
                    window_type = WindowType.POPOVER
                else:
                    window_type = WindowType.FOREGROUND
                self.new_page(window_type)
                decision.ignore()
                return True
            elif navigation_action.get_modifiers() &\
                    Gdk.ModifierType.CONTROL_MASK:
                self.new_page(WindowType.BACKGROUND)
                decision.ignore()
                return True
            elif navigation_action.get_modifiers() &\
                    Gdk.ModifierType.SHIFT_MASK:
                self.new_page(WindowType.POPOVER)
                decision.ignore()
                return True
            else:
                El().history.set_page_state(webview.get_uri())
                decision.use()
                self._error = None
                return False
        else:
            self.new_page(WindowType.BACKGROUND)
            decision.ignore()
            return True

    def __on_load_changed(self, webview, event):
        """
            Update sidebar/urlbar
            @param webview as WebView
            @param event as WebKit2.LoadEvent
        """
        uri = webview.get_uri()
        parsed = urlparse(uri)
        if event == WebKit2.LoadEvent.STARTED:
            self.stop_snapshot()
            if self.view is not None and not self.view.subsurface:
                self._window.container.sites_manager.add_view_for_uri(
                                                          self.view,
                                                          uri)
            self.__initial_uri = uri.rstrip('/')
            self._cancelled = False
            # Destroy current popups
            for popup in self.__popups:
                popup.destroy()
            self.__popups = []
            self.__title = ""
            # Setup js blocker
            if El().settings.get_value("jsblock"):
                exception = El().js_exceptions.find_parsed(parsed)
                self.set_setting("enable_javascript", exception)
            elif not self.get_settings().get_enable_javascript():
                self.set_setting("enable_javascript", True)
        if event == WebKit2.LoadEvent.COMMITTED:
            if self.view is not None and not self.view.subsurface:
                self._window.container.sites_manager.add_view_for_uri(
                                                          self.view,
                                                          uri)
            if self._content_manager is not None:
                self._content_manager.remove_all_style_sheets()
            if El().phishing.is_phishing(uri):
                self._show_phishing_error(uri)
            else:
                # Can't find a way to block content for ephemeral views
                if El().settings.get_value("adblock") and\
                        not El().adblock_exceptions.find_parsed(parsed) and\
                        parsed.scheme in ["http", "https"] and\
                        self._content_manager is not None:
                    self._content_manager.add_style_sheet(
                                                      El().default_style_sheet)
                    rules = El().adblock.get_css_rules(uri)
                    user_style_sheet = WebKit2.UserStyleSheet(
                                 rules,
                                 WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                                 WebKit2.UserStyleLevel.USER,
                                 None,
                                 None)
                    self._content_manager.add_style_sheet(user_style_sheet)
                self.update_spell_checking()
                self.update_zoom_level()
                user_agent = El().websettings.get_user_agent(uri)
                settings = self.get_settings()
                if user_agent:
                    settings.set_user_agent(user_agent)
                else:
                    settings.set_user_agent_with_application_details("Eolie",
                                                                     None)
                # Setup image blocker
                if El().settings.get_value("imgblock"):
                    exception = El().image_exceptions.find_parsed(parsed)
                    self.set_setting("auto-load-images", exception)
                elif not self.get_settings().get_auto_load_images():
                    self.set_setting("auto-load-images", True)
                # Setup eolie internal adblocker
                if El().settings.get_value("adblock") and\
                        parsed.scheme in ["http", "https"]:
                    exception = El().adblock_exceptions.find_parsed(parsed)
                    if not exception:
                        noext = ".".join(parsed.netloc.split(".")[:-1])
                        javascripts = ["adblock_%s.js" % parsed.netloc,
                                       "adblock_%s.js" % noext]
                        for javascript in javascripts:
                            f = Gio.File.new_for_path("%s/%s" % (ADBLOCK_JS,
                                                                 javascript))
                            if f.query_exists():
                                (status, content, tag) = f.load_contents(None)
                                js = content.decode("utf-8")
                                self.run_javascript(js, None, None)
                                break
        elif event == WebKit2.LoadEvent.FINISHED:
            if parsed.scheme != "populars":
                self.set_snapshot()
            if El().show_tls:
                try:
                    from OpenSSL import crypto
                    from datetime import datetime
                    (valid, tls, errors) = webview.get_tls_info()
                    if tls is not None:
                        print("***************************************"
                              "***************************************")
                        cert_pem = tls.get_property("certificate-pem")
                        cert = crypto.load_certificate(crypto.FILETYPE_PEM,
                                                       cert_pem)
                        subject = cert.get_subject()
                        print("CN: %s" % subject.CN)
                        start_bytes = cert.get_notBefore()
                        end_bytes = cert.get_notAfter()
                        start = datetime.strptime(start_bytes.decode("utf-8"),
                                                  "%Y%m%d%H%M%SZ")
                        end = datetime.strptime(end_bytes.decode("utf-8"),
                                                "%Y%m%d%H%M%SZ")
                        print("Valid from %s to %s" % (start, end))
                        print("Serial number: %s" % cert.get_serial_number())
                        print(cert_pem)
                        print("***************************************"
                              "***************************************")
                except Exception as e:
                    print("Please install OpenSSL python support:", e)
