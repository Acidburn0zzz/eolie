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

from gi.repository import Gio, GLib

from urllib.parse import urlparse
import sqlite3
import itertools
from gettext import gettext as _
from time import time

from eolie.helper_task import TaskHelper
from eolie.sqlcursor import SqlCursor
from eolie.define import EOLIE_DATA_PATH, ADBLOCK_JS, El
from eolie.utils import debug, remove_www


class DatabaseAdblock:
    """
        Eolie adblock db
    """
    DB_PATH = "%s/adblock2.db" % EOLIE_DATA_PATH

    __URIS = ["https://adaway.org/hosts.txt",
              "https://pgl.yoyo.org/adservers/serverlist.php?" +
              "hostformat=hosts&showintro=0&startdate%5Bday%5D=" +
              "&startdate%5Bmonth%5D=&startdate%5Byear%5D=",
              "http://winhelp2002.mvps.org/hosts.txt",
              "http://hosts-file.net/ad_servers.txt",
              "https://pgl.yoyo.org/adservers/serverlist.php?"
              "hostformat=hosts&showintro=0&mimetype=plaintext"]

    __CSS_URIS = ["https://easylist-downloads.adblockplus.org/easylist.txt"]

    __CSS_LOCALIZED_URIS = {
        "bg": "http://stanev.org/abp/adblock_bg.txt",
        "zh": "https://easylist-downloads.adblockplus.org/easylistchina.txt",
        "sk": "https://raw.github.com/tomasko126/" +
              "easylistczechandslovak/master/filters.txt",
        "cs": "https://raw.github.com/tomasko126/" +
              "easylistczechandslovak/master/filters.txt",
        "nl": "https://easylist-downloads.adblockplus.org/easylistdutch.txt",
        "de": "https://easylist-downloads.adblockplus.org/easylistgermany.txt",
        "he": "https://raw.githubusercontent.com/easylist/" +
              "EasyListHebrew/master/EasyListHebrew.txt",
        "it": "https://easylist-downloads.adblockplus.org/easylistitaly.txt",
        "lt": "http://margevicius.lt/easylistlithuania.txt",
        "es": "https://easylist-downloads.adblockplus.org/easylistspanish.txt",
        "lv": "https://notabug.org/latvian-list/" +
              "adblock-latvian/raw/master/lists/latvian-list.txt",
        "ar": "https://easylist-downloads.adblockplus.org/Liste_AR.txt",
        "fr": "https://easylist-downloads.adblockplus.org/liste_fr.txt",
        "ro": "http://www.zoso.ro/pages/rolist.txt",
        "ru": "https://easylist-downloads.adblockplus.org/advblock.txt",
        "ja": "http://bit.ly/11QrCfx",
        "fi": "https://adb.juvander.net/Finland_adb.txt",
        "cz": "http://adblock.dajbych.net/adblock.txt",
        "et": "http://gurud.ee/ab.txt",
        "hu": "https://raw.githubusercontent.com/szpeter80/" +
              "hufilter/master/hufilter.txt"}

    __UPDATE = 172800

    # SQLite documentation:
    # In SQLite, a column with type INTEGER PRIMARY KEY
    # is an alias for the ROWID.
    # Here, we define an id INT PRIMARY KEY but never feed it,
    # this make VACUUM not destroy rowids...
    __create_adblock = '''CREATE TABLE adblock (
                                               id INTEGER PRIMARY KEY,
                                               dns TEXT NOT NULL,
                                               mtime INT NOT NULL
                                               )'''
    __create_adblock_css = '''CREATE TABLE adblock_css (
                                               id INTEGER PRIMARY KEY,
                                               name TEXT NOT NULL,
                                               whitelist TEXT DEFAULT "",
                                               blacklist TEXT DEFAULT "",
                                               mtime INT NOT NULL
                                               )'''

    def __init__(self):
        """
            Create database tables or manage update if needed
        """
        self.__cancellable = Gio.Cancellable.new()
        self.__task_helper = TaskHelper()
        self.__adblock_mtime = int(time())

        # Lazy loading if not empty
        if not GLib.file_test(self.DB_PATH, GLib.FileTest.IS_REGULAR):
            try:
                if not GLib.file_test(EOLIE_DATA_PATH, GLib.FileTest.IS_DIR):
                    GLib.mkdir_with_parents(EOLIE_DATA_PATH, 0o0750)
                # Create db schema
                with SqlCursor(self) as sql:
                    sql.execute(self.__create_adblock)
                    sql.execute(self.__create_adblock_css)
                    sql.commit()
            except Exception as e:
                print("DatabaseAdblock::__init__(): %s" % e)

    def update(self):
        """
            Update database
        """
        if not Gio.NetworkMonitor.get_default().get_network_available():
            return
        # Update adblock_js repo
        git = GLib.find_program_in_path("git")
        if git is None:
            print(_("For stronger ad blocking, install git command"))
        else:
            if GLib.file_test(ADBLOCK_JS, GLib.FileTest.IS_DIR):
                argv = [git,
                        "-C",
                        ADBLOCK_JS,
                        "pull"]
            else:
                argv = [git,
                        "clone",
                        "https://gitlab.gnome.org/gnumdk/eolie-adblock.git",
                        ADBLOCK_JS]
            (pid, a1, a2, a3) = GLib.spawn_async(
                                    argv,
                                    flags=GLib.SpawnFlags.STDOUT_TO_DEV_NULL)
            GLib.spawn_close_pid(pid)

        # Check entries in DB, do we need to update?
        mtime = 0
        with SqlCursor(self) as sql:
            result = sql.execute("SELECT mtime FROM adblock\
                                  ORDER BY mtime LIMIT 1")
            v = result.fetchone()
            if v is not None:
                mtime = v[0]
        self.__cancellable.reset()
        if self.__adblock_mtime - mtime > self.__UPDATE:
            # Update host rules
            uris = list(self.__URIS)
            uri = uris.pop(0)
            self.__task_helper.load_uri_content(uri,
                                                self.__cancellable,
                                                self.__on_load_uri_content,
                                                uris)
        else:
            self.__on_save_rules()

    def stop(self):
        """
            Stop update
        """
        self.__cancellable.cancel()

    def get_default_css_rules(self):
        """
            Return default css rules
        """
        rules = ""
        with SqlCursor(self) as sql:
            request = "SELECT name FROM adblock_css WHERE\
                       blacklist='' AND whitelist=''"
            result = sql.execute(request)
            for name in list(itertools.chain(*result)):
                rules += "%s,\n" % name
        return rules[:-2] + "{display: none !important;}"

    def get_css_rules(self, uri):
        """
            Return css rules for uri
            @return str
        """
        rules = ""
        parsed = urlparse(uri)
        if parsed.scheme not in ["http", "https"]:
            return ""
        netloc = remove_www(parsed.netloc)
        with SqlCursor(self) as sql:
            request = "SELECT name FROM adblock_css WHERE\
                       (blacklist!='' AND blacklist!=?) OR whitelist=?"
            result = sql.execute(request, (netloc, netloc))
            for name in list(itertools.chain(*result)):
                rules += "%s,\n" % name
        return rules[:-2] + "{display: none !important;}"

    def is_blocked(self, uri):
        """
            Return True if uri is blocked
            @param uri as str
            @return bool
        """
        try:
            parsed = urlparse(uri)
            if parsed.scheme not in ["http", "https"] or\
                    El().adblock_exceptions.find_parsed(parsed):
                return False
            with SqlCursor(self) as sql:
                result = sql.execute("SELECT mtime FROM adblock\
                                      WHERE dns=?", (parsed.netloc,))
                v = result.fetchone()
                return v is not None
        except Exception as e:
            print("DatabaseAdblock::is_blocked():", e)
            return False

    def get_cursor(self):
        """
            Return a new sqlite cursor
        """
        try:
            c = sqlite3.connect(self.DB_PATH, 600.0)
            return c
        except Exception as e:
            print(e)
            exit(-1)

#######################
# PRIVATE             #
#######################
    def __save_rules(self, rules, uris):
        """
            Save rules to db
            @param rules bytes
            @param uris as [str]
        """
        SqlCursor.add(self)
        result = rules.decode('utf-8')
        count = 0
        for line in result.split('\n'):
            if self.__cancellable.is_cancelled():
                raise IOError("Cancelled")
            if line.startswith('#'):
                continue
            array = line.replace(
                         ' ', '\t', 1).replace('\t', '@', 1).split('@')
            if len(array) <= 1:
                continue
            dns = array[1].replace(
                               ' ', '').replace('\r', '').split('#')[0]
            # Update entry if exists, create else
            with SqlCursor(self) as sql:
                debug("Add filter: %s" % dns)
                sql.execute("INSERT INTO adblock\
                            (dns, mtime) VALUES (?, ?)",
                            (dns, self.__adblock_mtime))
                count += 1
                if count == 1000:
                    sql.commit()
                    count = 0
        # We are the last call to save_rules()?
        # Delete removed entries and commit
        if not uris:
            with SqlCursor(self) as sql:
                sql.execute("DELETE FROM adblock\
                             WHERE mtime!=?", (self.__adblock_mtime,))
                sql.commit()
        SqlCursor.remove(self)

    def __save_css_default_rule(self, line):
        """
            Save default (without blacklist, whitelist) rule to db
            @param line as str
        """
        name = line[2:]
        # Update entry if exists, create else
        with SqlCursor(self) as sql:
            debug("Add filter: %s" % name)
            sql.execute("INSERT INTO adblock_css\
                        (name, mtime) VALUES (?, ?)",
                        (name, self.__adblock_mtime))

    def __save_css_domain_rule(self, line):
        """
            Save domain rule to db
            @param line as str
        """
        whitelist = ""
        blacklist = ""
        (domains, name) = line.split("##")
        for domain in domains.split(","):
            if domain.startswith("~"):
                blacklist += "@%s@" % domain[1:]
            else:
                whitelist += domain
        with SqlCursor(self) as sql:
            debug("Add filter: %s" % name)
            sql.execute("INSERT INTO adblock_css\
                         (name, whitelist, blacklist, mtime)\
                         VALUES (?, ?, ?, ?)",
                        (name, whitelist, blacklist, self.__adblock_mtime))

    def __save_css_rules(self, rules, uris):
        """
            Save rules to db
            @param rules as bytes
            @param uris as [str]
        """
        SqlCursor.add(self)
        result = rules.decode("utf-8")
        count = 0
        for line in result.split('\n'):
            if self.__cancellable.is_cancelled():
                raise IOError("Cancelled")
            if line.find("-abp-") != -1:
                continue
            elif line.startswith("##"):
                self.__save_css_default_rule(line)
            elif line.find("##") != -1:
                self.__save_css_domain_rule(line)
            count += 1
            if count == 1000:
                with SqlCursor(self) as sql:
                    sql.commit()
                count = 0
        # We are the last rule
        # Delete old entries
        if not uris:
            with SqlCursor(self) as sql:
                sql.execute("DELETE FROM adblock_css\
                             WHERE mtime!=?", (self.__adblock_mtime,))
                sql.commit()
        SqlCursor.remove(self)

    def __on_save_css_rules(self, result, uris):
        """
            Load next uri
            @param result as ??
            @param uris as [str]
        """
        if uris:
            uri = uris.pop(0)
            self.__task_helper.load_uri_content(uri,
                                                self.__cancellable,
                                                self.__on_load_uri_css_content,
                                                uris)

    def __on_load_uri_css_content(self, uri, status, content, uris):
        """
            Load pending uris
            @param uri as str
            @param status as bool
            @param content as bytes
            @param uris as [str]
        """
        if status:
            self.__task_helper.run(self.__save_css_rules, content, uris,
                                   callback=(self.__on_save_css_rules, uris))

    def __on_save_rules(self, result=None, uris=[]):
        """
            Load next uri, if finished, load CSS rules
            @param result as None
            @param uris as [str]
        """
        if uris:
            uri = uris.pop(0)
            self.__task_helper.load_uri_content(uri,
                                                self.__cancellable,
                                                self.__on_load_uri_content,
                                                uris)
        else:
            # Check entries in DB, do we need to update?
            mtime = 0
            with SqlCursor(self) as sql:
                result = sql.execute("SELECT mtime FROM adblock_css\
                                      ORDER BY mtime LIMIT 1")
                v = result.fetchone()
                if v is not None:
                    mtime = v[0]
            # We ignore update value from rules file
            if self.__adblock_mtime - mtime < self.__UPDATE:
                return
            locales = GLib.get_language_names()
            user_locale = locales[0].split("_")[0]
            try:
                uris = [self.__CSS_LOCALIZED_URIS[user_locale]]
            except:
                uris = []
            uris += list(self.__CSS_URIS)
            uri = uris.pop(0)
            self.__task_helper.load_uri_content(uri,
                                                self.__cancellable,
                                                self.__on_load_uri_css_content,
                                                uris)

    def __on_load_uri_content(self, uri, status, content, uris):
        """
            Save loaded values
            @param uri as str
            @param status as bool
            @param content as bytes
            @param uris as [str]
        """
        if status:
            self.__task_helper.run(self.__save_rules, content, uris,
                                   callback=(self.__on_save_rules, uris))
