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

from gi.repository import Gtk, GLib

from locale import strcoll
from time import time

from eolie.define import El
from eolie.widget_bookmark_rating import BookmarkRatingWidget


class MyEntry(Gtk.Entry):
    """
        Limited width Gtk Entry
    """
    def __init__(self):
        """
            Init entry
        """
        Gtk.Entry.__init__(self)
        self.get_style_context().add_class("tag-content")

    def do_get_preferred_width(self):
        """
            Max width to 100
        """
        return (75, 75)


class TagWidget(Gtk.FlowBoxChild):
    """
        Tag widget with some visual effects
    """

    def __init__(self, title, bookmark_id):
        """
            Init widget
            @param title as str
            @param bookmark_id as int
        """
        Gtk.FlowBoxChild.__init__(self)
        self.__bookmark_id = bookmark_id
        self.get_style_context().add_class("tag")
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/Eolie/TagWidget.ui")
        builder.connect_signals(self)
        self.__label = builder.get_object("label")
        self.__entry = MyEntry()
        self.__entry.set_has_frame(False)
        self.__entry.connect("activate", self.__on_entry_activate)
        self.__entry.show()
        self.__stack = builder.get_object("stack")
        self.__stack.add(self.__entry)
        self.__close_button = builder.get_object("close_button")
        self.set_property("halign", Gtk.Align.START)
        self.set_property("valign", Gtk.Align.START)
        self.__widget = builder.get_object("widget")
        self.add(self.__widget)
        self.__label.set_text(title)
        self.__entry.set_text(title)

    @property
    def label(self):
        """
            Get label
            @return str
        """
        return self.__label.get_text()

#######################
# PROTECTED           #
#######################
    def _on_close_button_press(self, eventbox, event):
        """
            Remove tag
            @param eventbox as Gtk.EventBox
            @param event as Gtk.Event
        """
        El().bookmarks.thread_lock.acquire()
        tag_title = self.__entry.get_text()
        tag_id = El().bookmarks.get_tag_id(tag_title)
        if tag_id is not None:
            El().bookmarks.del_tag_from(tag_id, self.__bookmark_id)
        El().bookmarks.thread_lock.release()
        self.destroy()
        return True

    def _on_button_press_event(self, eventbox, event):
        """
            Show entry
            @param eventbox as Gtk.EventBox
            @param event as Gdk.event
        """
        self.__stack.set_visible_child(self.__entry)

    def _on_enter_notify_event(self, eventbox, event):
        """
            Show buttons
            @param eventbox as Gtk.EventBox
            @param event as Gdk.event
        """
        self.__close_button.set_opacity(0.9)
        eventbox.get_style_context().add_class("tag-hover")

    def _on_leave_notify_event(self, eventbox, event):
        """
            Hide buttons
            @param eventbox as Gtk.EventBox
            @param event as Gdk.event
        """
        allocation = eventbox.get_allocation()
        if event.x <= 0 or\
           event.x >= allocation.width or\
           event.y <= 0 or\
           event.y >= allocation.height:
            eventbox.get_style_context().remove_class("tag-hover")
            self.__close_button.set_opacity(0.2)


#######################
# PRIVATE             #
#######################
    def __on_entry_activate(self, entry):
        """
            Save tag name based on entry content
            @param entry as Gtk.Entry
        """
        title = self.__entry.get_text()
        previous = self.__label.get_text()
        if previous == title:
            return
        # We do not handle tag fusion TODO
        tag_id = El().bookmarks.get_tag_id(title)
        if tag_id is not None:
            return
        # Update mtime for all tagged bookmarks
        if El().sync_worker is not None:
            mtimes = El().sync_worker.mtimes
            if mtimes["bookmarks"] == 0:
                mtime = round(time(), 2)
            else:
                mtime = mtimes["bookmarks"]
            tag_id = El().bookmarks.get_tag_id(previous)
            if tag_id is None:
                return
            for (bookmark_id, bookmark_uri, bookmark_title) in\
                    El().bookmarks.get_bookmarks(tag_id):
                El().bookmarks.set_mtime(bookmark_id, mtime + 1)
        El().bookmarks.rename_tag(previous, title)
        self.__label.set_text(title)
        self.__stack.set_visible_child(self.__label)


class BookmarkEditWidget(Gtk.Bin):
    """
        Widget allowing to edit a bookmark
    """

    def __init__(self, bookmark_id, back_enabled=True):
        """
            Init widget
            @param bookmark id as int
            @param enable back button as bool
        """
        Gtk.Bin.__init__(self)
        self.__bookmark_id = bookmark_id
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/Eolie/BookmarkEdit.ui")
        builder.connect_signals(self)
        self.__flowbox = builder.get_object("flowbox")
        self.__flowbox.set_sort_func(self.__sort_tags)
        self.__add_tag_button = builder.get_object("add_tag_button")
        self.__rename_tag_button = builder.get_object("rename_tag_button")
        self.__remove_tag_button = builder.get_object("remove_tag_button")
        self.__title_entry = builder.get_object("title_entry")
        self.__uri_entry = builder.get_object("uri_entry")
        self.__title_entry.set_text(El().bookmarks.get_title(bookmark_id))
        self.__uri_entry.set_text(El().bookmarks.get_uri(bookmark_id))

        self.__new_tag_entry = builder.get_object("new_tag_entry")
        # Init new tag completion model
        self.__completion_model = Gtk.ListStore(str)
        self.__completion = Gtk.EntryCompletion.new()
        self.__completion.set_model(self.__completion_model)
        self.__completion.set_text_column(0)
        self.__completion.set_inline_completion(False)
        self.__completion.set_popup_completion(True)
        self.__new_tag_entry.set_completion(self.__completion)
        for (tag_id, title) in El().bookmarks.get_all_tags():
            self.__completion_model.append([title])

        for title in El().bookmarks.get_tags(bookmark_id):
            tag = TagWidget(title, bookmark_id)
            tag.show()
            self.__flowbox.add(tag)
        if not back_enabled:
            builder.get_object("back_button").hide()
        widget = builder.get_object("widget")
        bookmark_rating = BookmarkRatingWidget(bookmark_id)
        bookmark_rating.show()
        widget.attach(bookmark_rating, 4, 1, 1, 1)
        self.add(widget)
        self.connect("unmap", self.__on_unmap)

#######################
# PROTECTED           #
#######################
    def _on_back_clicked(self, button):
        """
            Destroy self
            @param button as Gtk.Button
        """
        El().bookmarks.thread_lock.acquire()
        self.disconnect_by_func(self.__on_unmap)
        El().bookmarks.set_title(self.__bookmark_id,
                                 self.__title_entry.get_text())
        El().bookmarks.set_uri(self.__bookmark_id,
                               self.__uri_entry.get_text())
        self.get_parent().set_visible_child_name("bookmarks")
        if El().sync_worker is not None:
            mtimes = El().sync_worker.mtimes
            if mtimes["bookmarks"] == 0:
                El().bookmarks.set_mtime(self.__bookmark_id,
                                         round(time(), 2) + 1)
            else:
                El().bookmarks.set_mtime(self.__bookmark_id,
                                         mtimes["bookmarks"] + 1)
            El().bookmarks.clean_tags()
            if El().sync_worker is not None:
                El().sync_worker.stop()
                # To be sure stop is done
                GLib.timeout_add(1000, El().sync_worker.sync)
        GLib.timeout_add(1000, self.destroy)
        El().bookmarks.thread_lock.release()

    def _on_del_clicked(self, button):
        """
            Remove item
            @param button as Gtk.Button
        """
        El().bookmarks.thread_lock.acquire()
        self.disconnect_by_func(self.__on_unmap)
        if El().sync_worker is not None:
            guid = El().bookmarks.get_guid(self.__bookmark_id)
            El().sync_worker.remove_from_bookmarks(guid)
        El().bookmarks.delete(self.__bookmark_id)
        if isinstance(self.get_parent(), Gtk.Popover):
            self.get_parent().hide()
        else:
            self.get_parent().set_visible_child_name("bookmarks")
        El().bookmarks.thread_lock.release()

    def _on_new_tag_entry_activate(self, entry, ignore1=None, ignore2=None):
        """
            Add new tag
            @param entry as Gtk.Entry
        """
        tag_title = self.__new_tag_entry.get_text()
        if not tag_title:
            return
        El().bookmarks.thread_lock.acquire()
        if not El().bookmarks.has_tag(self.__bookmark_id, tag_title):
            tag_id = El().bookmarks.get_tag_id(tag_title)
            if tag_id is None:
                tag_id = El().bookmarks.add_tag(tag_title, True)
            El().bookmarks.add_tag_to(tag_id, self.__bookmark_id)
            tag = TagWidget(tag_title, self.__bookmark_id)
            tag.show()
            self.__flowbox.add(tag)
        entry.set_text("")
        El().bookmarks.thread_lock.release()

    def _on_flowbox_size_allocate(self, scrolled, allocation):
        """
            Set scrolled size allocation based on viewport allocation
            @param scrolled as Gtk.ScrolledWindow
            @param flowbox allocation as Gtk.Allocation
        """
        height = allocation.height
        if height > 300:
            height = 300
        scrolled.set_size_request(-1, height)

#######################
# PRIVATE             #
#######################
    def __sort_tags(self, child1, child2):
        """
            Sort tags
            @param child1 as TagWidget
            @param child2 as TagWidget
        """
        return strcoll(child1.label, child2.label)

    def __on_unmap(self, widget):
        """
            Save uri and title
            @param widget as Gtk.Widget
        """
        El().bookmarks.thread_lock.acquire()
        El().bookmarks.set_title(self.__bookmark_id,
                                 self.__title_entry.get_text())
        El().bookmarks.set_uri(self.__bookmark_id,
                               self.__uri_entry.get_text())
        if El().sync_worker is not None:
            mtimes = El().sync_worker.mtimes
            if mtimes["bookmarks"] == 0:
                El().bookmarks.set_mtime(self.__bookmark_id,
                                         round(time(), 2) + 1)
            else:
                El().bookmarks.set_mtime(self.__bookmark_id,
                                         mtimes["bookmarks"] + 1)
            El().bookmarks.clean_tags()
            if El().sync_worker is not None:
                El().sync_worker.stop()
                # To be sure stop is done
                GLib.timeout_add(1000, El().sync_worker.sync)
        El().bookmarks.thread_lock.release()
