#!/usr/bin/env python

"""
    ============
    | Terminal |
    -----------------------------------------------------------
    A graphical process output viewer/filter and emerge queue
    -----------------------------------------------------------
    Copyright (C) 2003 - 2004 Fredrik Arnerup, Brian Dolbec, 
    Daniel G. Taylor and Wm. F. Wheeler

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program; if not, write to the Free Software
    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

    -------------------------------------------------------------------------
    This program recognizes these run-time parameters:
        -d, --debug     Send debug messages to the screen
        -l, --local     Use the local path for data files (for cvs version)
        -v, --version   Print out the program version

    -------------------------------------------------------------------------
    To use this program as a module:
    
        from terminal import ProcessManager

        def callback():
            print "This is called when a process finishes"

        manager = ProcessManager(environment, preferences)
        manager.add_process(package_name, command_to_run, callback)
        ...
    -------------------------------------------------------------------------
    References & Notes
    
    1. Pygtk2 refs & tutorials - http://www.pygtk.org
    2. GTK2 text tags can use named colors (see /usr/X11R6/lib/X11/rgb.txt)
       or standard internet rgb values (e.g. #02FF80)
 
"""

# import external [system] modules
import pygtk; pygtk.require('2.0')
import gtk, gtk.glade, gobject
import signal, os, pty, threading, time, sre, portagelib
import datetime, pango, errno, string

if __name__ == "__main__":
    # setup our path so we can load our custom modules
    from sys import path
    path.append("/usr/lib/porthole")

# import custom modules
from utils import dprint, get_user_home_dir, SingleButtonDialog, \
                  get_treeview_selection, estimate, YesNoDialog
from version import version

from gettext import gettext as _

# some constants for the tabs
TAB_PROCESS = 0
TAB_WARNING = 1
TAB_CAUTION = 2
TAB_INFO = 3
TAB_QUEUE = 4

# A constant that represents the maximum distance from the
# bottom of the slider for the slider to stick.  Too small and
# you won't be able to make it stick when text is added rapidly
SLIDER_CLOSE_ENOUGH = 0.5 # of the page size

# some contant strings that may be internationalized later
KILLED_STRING = _("*** process killed ***\n")
TERMINATED_STRING = _("*** process completed ***\n")
TABS = [TAB_PROCESS, TAB_WARNING, TAB_CAUTION, TAB_INFO, TAB_QUEUE]
TAB_LABELS = [_("Process"), _("Warnings"), _("Cautions"), _("Summary"), _("Emerge queue")]

class ProcessManager:
    """ Manages queued and running processes """
    def __init__(self, env = {}, prefs = None, config = None, log_mode = False):
        """ Initialize """
        if log_mode:
            self.title = _("Porthole Log Viewer")
        else:
            self.title = _("Porthole-Terminal")
        self.log_mode = log_mode
        self.Semaphore = threading.Semaphore()
        # copy the environment and preferences
        self.env = env
        self.prefs = prefs
        self.config = config
        self.killed = 0
        self.pid = None
        self.Failed = False
        self.isPretend = False
        self.file_input = False
        # process list to store pending processes
        self.process_list = []
        # the window is not visible until a process is added
        self.window_visible = False
        # filename and serial #
        self.directory = None
        self.filename = None
        self.untitled_serial = -1
        # create the process reader
        self.reader = ProcessOutputReader(self.process_done)
        # start the reader
        self.reader.start()
        gtk.timeout_add(100, self.update)

    def set_tags(self):
        """ set the text formatting tags from prefs object """
        # NOTE: for ease of maintenance, all tabs have every tag
        #       defined for use.  Currently the code determines
        #       when & where to use the tags
        for key in self.prefs.TAG_DICT:
            for process_tab in [TAB_PROCESS, TAB_WARNING, TAB_CAUTION, TAB_INFO]:
                text_tag = self.prefs.TAG_DICT[key] 
                if text_tag[0] == '':
                    self.term.buffer[process_tab].create_tag(key,\
                        background=text_tag[1],\
                        weight=text_tag[2])
                elif text_tag[1] == '':
                    self.term.buffer[process_tab].create_tag(key,\
                        foreground=text_tag[0],\
                        weight=text_tag[2])
                else:
                    self.term.buffer[process_tab].create_tag(key,\
                        foreground=text_tag[0],\
                        background=text_tag[1],\
                        weight=text_tag[2])

    def show_window(self):
        """ Show the process window """
        # load the glade file
        self.wtree = gtk.glade.XML(self.prefs.DATA_PATH + "porthole.glade",
                                   "process_window")
        # these need to be before the callbacks
        # setup some aliases for easier access
        self.window = self.wtree.get_widget("process_window")
        self.notebook = self.wtree.get_widget("notebook1")
        self.queue_tree = self.wtree.get_widget("queue_treeview")
        self.queue_menu = self.wtree.get_widget("queue1")
        self.statusbar = self.wtree.get_widget("statusbar")
        self.resume_menu = self.wtree.get_widget("resume")
        self.skip_first_menu = self.wtree.get_widget("skip_first1")
        self.skip_queue_menu = self.wtree.get_widget("skip_queue")
        self.save_menu = self.wtree.get_widget("save1")
        self.save_as_menu = self.wtree.get_widget("save_as")
        self.open_menu = self.wtree.get_widget("open")
        self.move_up = self.wtree.get_widget("move_up1")
        self.move_down = self.wtree.get_widget("move_down1")
        self.queue_remove = self.wtree.get_widget("remove1")
        # Initialize event widget source
        self.event_src = None
        # setup the callbacks
        callbacks = {"on_process_window_destroy" : self.on_process_window_destroy,
                     "on_kill" : self.kill_process,
                     "on_resume_normal" : self.resume_normal,
                     "on_resume_skip_first" : self.resume_skip_first,
                     "on_skip_queue" : self.start_queue,
                     "on_save_log" : self.do_save,
                     "on_save_log_as" : self.do_save_as,
                     "on_open_log" : self.do_open,
                     "on_copy" : self.copy_selected,
                     "on_clear" : self.clear_buffer,
                     "on_move_up" : self.move_queue_item_up,
                     "on_move_down" : self.move_queue_item_down,
                     "on_remove" : self.remove_queue_item,
                     "on_quit" : self.destroy_window}
        self.wtree.signal_autoconnect(callbacks)
        # get a mostly blank structure to hold a number of widgets & settings
        self.term = terminal_notebook()
        # get the buffer & view widgets and assign them to their arrays
        widget_labels = ["process_text", "warnings_text", "cautions_text", "info_text"]
        for x in widget_labels:
            buffer = self.wtree.get_widget(x).get_buffer()
            self.term.buffer += [buffer]
            view = self.wtree.get_widget(x)
            self.term.view += [view]
        widget_labels = ["scrolledwindow2", "scrolledwindow8", "scrolledwindow7",
                         "scrolledwindow5", "scrolledwindow4"]
        for x in widget_labels:
            window = self.wtree.get_widget(x)
            self.term.scrolled_window += [window]
        # Catch button events on info, caution & warning tabs
        # Following a double click on a line, bring that line
        # in the process window into focus near center screen
        self.term.view[TAB_INFO].connect("button_press_event", self.button_event)
        self.term.view[TAB_CAUTION].connect("button_press_event", self.button_event)
        self.term.view[TAB_WARNING].connect("button_press_event", self.button_event)        
        self.term.view[TAB_INFO].connect("button_release_event", self.button_event)
        self.term.view[TAB_CAUTION].connect("button_release_event", self.button_event)
        self.term.view[TAB_WARNING].connect("button_release_event", self.button_event)
        # catch clicks to the queue tree
        self.queue_tree.connect("cursor_changed", self.queue_clicked)
        # process output buffer
        self.process_buffer = ''
        # set some persistent variables for text capture
        self.catch_seq = False
        self.escape_seq = "" # to catch the escape sequence in
        self.first_cr = True  # first time cr is detected for a line
        self.overwrite_till_nl = False  # overwrite until after a '\n' detected for this line
        self.resume_line = None
        # setup the queue treeview
        column = gtk.TreeViewColumn(_("Packages to be merged      "))
        pixbuf = gtk.CellRendererPixbuf()
        column.pack_start(pixbuf, expand = False)
        column.add_attribute(pixbuf, "pixbuf", 0)
        text = gtk.CellRendererText()
        column.pack_start(text, expand = False)
        column.add_attribute(text, "text", 1)
        self.queue_tree.append_column(column)
        column = gtk.TreeViewColumn("Command")
        text = gtk.CellRendererText()
        column.pack_start(text, expand = True)
        column.add_attribute(text, "text", 2)
        self.queue_tree.append_column(column)
        self.queue_model = gtk.TreeStore(gtk.gdk.Pixbuf,
                                        gobject.TYPE_STRING,
                                        gobject.TYPE_STRING)
        self.queue_tree.set_model(self.queue_model)
        # save the tab contents and remove them until we need em
        self.warning_tab = self.notebook.get_nth_page(TAB_WARNING)
        self.caution_tab = self.notebook.get_nth_page(TAB_CAUTION)
        self.info_tab = self.notebook.get_nth_page(TAB_INFO)
        self.queue_tab = self.notebook.get_nth_page(TAB_QUEUE)
        self.notebook.remove_page(TAB_QUEUE)
        self.notebook.remove_page(TAB_INFO)
        self.notebook.remove_page(TAB_CAUTION)
        self.notebook.remove_page(TAB_WARNING)
        # initialize to None
        self.pid = None
        # Set formatting tags now that tabs are established
        self.set_tags()
        # text mark to mark the start of the current command
        self.command_start = None
        # used to skip a killed queue item if killed
        self.resume_available = False
        # set the window title
        self.window.set_title(self.title)
        # flag that the window is now visible
        self.window_visible = True
        dprint("TERMINAL: get & connect to vadjustments")
        #dprint(TABS[:-1])
        for x in TABS[:-1]:
            #dprint(x)
            adj = self.term.scrolled_window[x].get_vadjustment()
            self.term.vadjustment +=  [adj]
            id = self.term.vadjustment[x].connect("value_changed", self.set_scroll)
            self.term.vhandler_id += [id]
            #self.term.auto_scroll[x] = False  # already initialized to True
        #dprint("TERMINAL: show_window() -- self.term.vadjustment[]," +
        #       "self.term.vhandler_id[], self.term.autoscroll")
        #dprint(self.term.vadjustment)
        #dprint(self.term.vhandler_id)
        #dprint(self.term.auto_scroll)
        self.notebook.connect("switch-page", self.switch_page)
        if self.prefs:
            self.window.resize((self.prefs.emerge.verbose and
                                self.prefs.terminal.width_verbose or
                                self.prefs.terminal.width), 
                                self.prefs.terminal.height)
            # MUST! do this command last, or nothing else will _init__
            # after it until emerge is finished.
            # Also causes runaway recursion.
            self.window.connect("size_request", self.on_size_request)

    def button_event(self, widget, event):
        """ Catch button events.  When a dbl-click occurs save the widget
            as the source.  When a corresponding button release from the same
            widget occurs, move to the process window and jump to the line
            number clicked on.
        """
        if event.type == gtk.gdk._2BUTTON_PRESS:
            # Capture the source of the dbl-click event
            # but do nothing else
            self.event_src = widget

        elif event.type == gtk.gdk.BUTTON_RELEASE and \
            self.event_src == widget:
            # clear the event source to prevent false restarts
            self.event_src = None
            # The button release event following the dbl-click
            # from the same widget, go ahead and process now
            # Convert x,y window coords to buffer coords and get line text
            x = int(event.x)
            y = int(event.y)
            bufcoords = widget.window_to_buffer_coords(gtk.TEXT_WINDOW_TEXT,x,y)
            # Set start iter at beginning of line (0)
            iStart = widget.get_iter_at_location(0,bufcoords[1])
            # Set end iter far enough right to grab number (100)
            iEnd = widget.get_iter_at_location(100,bufcoords[1])
            try:
                # get line number from textbuffer (0 based)
                # we'll do this inside a try clause in case the user
                # clicks on a line without a number or anything else
                # goes wrong!
                line = int(iStart.get_text(iEnd)[0:6]) - 1 
                # Get the iter based on the line number index
                iter = self.term.buffer[TAB_PROCESS].get_iter_at_line_index(line,0)
                # Scroll to the line, try to position mid-screen
                self.term.view[TAB_PROCESS].scroll_to_iter(iter, 0.0, True, 0, 0.5)
                # Turn off auto scroll
                self.term.auto_scroll[TAB_PROCESS] = False
                # Display the tab
                self.notebook.set_current_page(TAB_PROCESS)
            except: pass
        return gtk.FALSE  # Always return false for proper handling

    def switch_page(self, notebook, page, page_num):
        """callback function changes the current_page setting in the term structure"""
        dprint("TERMINAL: switch_page; page_num = %d" %page_num)
        self.term.current_tab = self.term.visible_tablist[page_num]
        if self.term.auto_scroll[self.term.current_tab]:
            #dprint("TERMINAL: append() -- self.term.vadjustment[], self.term.vhandler_id[]")
            #dprint(self.term.vadjustment)
            #dprint(self.term.vhandler_id)
            num = self.term.current_tab
            self.term.vadjustment[num].handler_block(self.term.vhandler_id[num])
            #result = self.term.view[num].scroll_to_iter(self.term.buffer[num].get_end_iter(),0.0, True, 0, 0.9)
            self.term.view[num].scroll_mark_onscreen(self.term.buffer[num].get_insert())
            self.term.vadjustment[num].handler_unblock(self.term.vhandler_id[num])
        return

    def set_scroll(self,  vadjustment):
        """Sets autoscrolling on when moved to bottom of scrollbar"""
        #dprint("TERMINAL: set_scroll -- vadjustment")
        #dprint(vadjustment)
        #dprint(vadjustment.get_value())
        #dprint(vadjustment.upper)
        #dprint(vadjustment.page_size)
        #dprint(self.term.buffer[self.term.current_tab].get_line_count())
        self.term.auto_scroll[self.term.current_tab] = ((vadjustment.upper - \
                                                        vadjustment.get_value()) - \
                                                        vadjustment.page_size < \
                                                         (SLIDER_CLOSE_ENOUGH * vadjustment.page_size))
        #dprint(self.term.auto_scroll[self.term.current_tab])
        return

    def on_size_request(self, window, gbox):
        """ Store new size in prefs """
        # get the width and height of the window
        width, height = window.get_size()
        # set the preferences
        if self.prefs.emerge.verbose:
            self.prefs.terminal.width_verbose = width
        else:
            self.prefs.terminal.width = width
        self.prefs.terminal.height = height

    def show_tab(self, tab):
        """ Create the label for the tab and show it """
        # this hbox will hold the icon and label
        hbox = gtk.HBox()
        icon = gtk.Image()
        # set the icon, label, tab, and position of the tab
        if tab == TAB_WARNING:
            icon.set_from_stock(gtk.STOCK_DIALOG_WARNING, gtk.ICON_SIZE_MENU)
            label, tab, pos = TAB_LABELS[TAB_WARNING], self.warning_tab, 1
            self.term.tab_showing[TAB_WARNING] = True
        elif tab == TAB_CAUTION:
            icon.set_from_stock(gtk.STOCK_DIALOG_WARNING, gtk.ICON_SIZE_MENU)
            label, tab = TAB_LABELS[TAB_CAUTION], self.caution_tab
            # quick hack to make it always show before info & queue tabs
            pos = self.notebook.page_num(self.info_tab)
            if pos == -1:
                pos = self.notebook.page_num(self.queue_tab)
                if pos == -1:
                    pos = 2
            self.term.tab_showing[TAB_CAUTION] = True
        elif tab == TAB_INFO:
            icon.set_from_stock(gtk.STOCK_DIALOG_INFO, gtk.ICON_SIZE_MENU)
            label, tab = TAB_LABELS[TAB_INFO], self.info_tab
            pos = self.notebook.page_num(self.queue_tab)
            # set to show before queue tab
            if pos == -1: pos = 3
            self.term.tab_showing[TAB_INFO] = True
        elif tab == TAB_QUEUE:
            icon.set_from_stock(gtk.STOCK_INDEX, gtk.ICON_SIZE_MENU)
            label, tab, pos = TAB_LABELS[TAB_QUEUE], self.queue_tab, 4
            self.term.tab_showing[TAB_QUEUE] = True
        # pack the icon and label onto the hbox
        hbox.pack_start(icon)
        hbox.pack_start(gtk.Label(label))
        hbox.show_all()
        # insert the tab
        self.notebook.insert_page(tab, hbox, pos)
        # reset the visible_tablist
        self.term.get_tab_list()
        dprint("TERMINAL: self.term.visible_tablist")
        dprint(self.term.visible_tablist)
        

    def resume_dialog(self, message):
        """ Handle response when user tries to re-add killed process to queue """
        dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                    gtk.MESSAGE_QUESTION,
                                    gtk.BUTTONS_CANCEL, message);
        dialog.add_button(gtk.STOCK_EXECUTE, gtk.RESPONSE_ACCEPT)
        dialog.add_button("Resume", gtk.RESPONSE_YES)
        result = dialog.run()
        dialog.destroy()
        return result

    def add_process(self, package_name, command_string, callback):
        """ Add a process to the queue """
        # Prevent conflicts while changing process queue
        self.Semaphore.acquire()
        dprint("TERMINAL: add_process; Semaphore acquired")

        # if it's already in the queue, don't add it!
        for data in self.process_list:
            if package_name == data[0]:
                if command_string == data[1]:
                    # Let the user know it's already in the list
                    if data == self.process_list[0]:
                        if self.killed:
                            # The process has been killed, so help the user out a bit
                            message = _("The package you selected is already in the emerge queue,\n" \
                                      "but it has been killed. Would you like to resume the emerge?")
                            result = self.resume_dialog(message)
                            if result == gtk.RESPONSE_ACCEPT: # Execute
                                break
                            elif result == gtk.RESPONSE_YES: # Resume
                                self.resume_normal(None)
                            else: # Cancel
                                # Clear semaphore, we're done
                                self.Semaphore.release()
                                dprint("TERMINAL: add_process; Semaphore released")
                                return gtk.FALSE
                        else:
                            message = _("The package you selected is already in the emerge queue!")
                            SingleButtonDialog(_("Error Adding Package To Queue!"), None,
                                           message, None, "Ok")
                            # Clear semaphore, we're done
                            self.Semaphore.release()
                            dprint("TERMINAL: add_process; Semaphore released")
                            return
                # remove process from list
                dprint(self.process_list)
                dprint(data)
                self.process_list = self.process_list[1:]

        # show the window if it isn't yet
        if not self.window_visible:
            self.show_window()
        # add to the queue
        iter = self.queue_model.insert_before(None, None)
        self.queue_model.set_value(iter, 0, None)
        self.queue_model.set_value(iter, 1, str(package_name))
        self.queue_model.set_value(iter, 2, str(command_string))
        # add to our process list
        self.process_list.append((package_name, command_string,
                                                iter, callback))

        if len(self.process_list) == 2:
            # if this is the 2nd process in the list
            # show the queue tab!
            if not self.term.tab_showing[TAB_QUEUE]:
                self.show_tab(TAB_QUEUE)
                self.queue_menu.set_sensitive(gtk.TRUE)
        # if no process is running, let's start one!
        if not self.reader.process_running:
            if self.resume_available:
                self.start_queue(True)
            else:
                # pending processes, run the next one in the list
                self.start_queue(False)

        # Clear semaphore, we're done
        self.Semaphore.release()
        dprint("TERMINAL: add_process; Semaphore released")

    def _run(self, command_string, iter = None):
        """ Run a given command string """
        # we can't be killed anymore
        self.killed = 0
        # reset back to terminal mode in case it is not
        self.log_mode = False
        self.warning_count = 0
        self.caution_count = 0
        self.Failed = False
        self.isPretend = (sre.search("--pretend", command_string) != None)
        if not self.isPretend:
            tmpcmdline = command_string.split()
            #dprint(tmpcmdline)
            for x in tmpcmdline:
                if x[0:1]=="-"and x[1:2]!="-":
                    for y in x[1:]:
                        #dprint(y)    
                        if y == "p":
                            #dprint("found it")
                            self.isPretend = True

        start_iter = self.term.buffer[TAB_PROCESS].get_end_iter()
        if self.command_start:
            # move the start mark
            self.term.buffer[TAB_PROCESS].move_mark_by_name("command_start",start_iter)
        else:
            # create the mark
            self.command_start = self.term.buffer[TAB_PROCESS].create_mark( \
                "command_start",start_iter, gtk.TRUE)
        # set the resume buttons to not be sensitive
        self.resume_menu.set_sensitive(gtk.FALSE)
        self.save_menu.set_sensitive(gtk.FALSE)
        self.save_as_menu.set_sensitive(gtk.FALSE)
        self.open_menu.set_sensitive(gtk.FALSE)
        if iter:
            self.queue_model.set_value(iter, 0, 
                             self.render_icon(gtk.STOCK_EXECUTE))
        # set process_running so the reader thread reads it's output
        self.reader.process_running = True
        # show a message that the process is starting
        self.append_all("*** " + command_string + " ***\n", True, 'command')
        self.set_statusbar("*** " + command_string + " ***")
        # pty.fork() creates a new process group
        self.pid, self.reader.fd = pty.fork()
        if self.pid == pty.CHILD:  # child
            try:
                # run the commandbuffer.tag_table.lookup(tagname)
                shell = "/bin/sh"
                os.execve(shell, [shell, '-c', command_string],
                          self.env)
                
            except Exception, e:
                # print out the exception
                dprint("TERMINAL: Error in child" + e)
                #print "Error in child:"
                #print e
                os._exit(1)

    def destroy_window(self, widget):
        """ Destroy the window when the close button is pressed """
        dprint("TERMINAL: close button clicked... destroying now")
        self.window.destroy()

    def on_process_window_destroy(self, widget, data = None):
        """Window was closed"""
        # kill any running processes
        self.kill()
        # make sure to reset the process list
        self.process_list = []
        # the window is no longer showing
        self.window_visible = False
        self.wtree = None
        if __name__ == "__main__":
            # if running standalone, quit
            gtk.main_quit()

    def kill(self):
        """Kill process."""
        if self.log_mode:
            self.reader.file_input = False
            dprint("LOG: kill() wait for reader to notice")
            # wait for ProcessOutputReader to notice
            time.sleep(.5)
            dprint("LOG: kill() -- self.reader.f.close()")
            self.reader.f.close()
            self.file_input = False
            dprint("LOG: leaving kill()")
            return
        # If started and still running
        if self.pid and not self.killed:
            try:
                if self.reader.fd:
                    os.write(self.reader.fd, "\003")
                    dprint("TERMINAL: cntrl-C sent to process")
                    self.resume_available = True
                    # make sure the thread notices
                    #os.close(self.reader.fd)
                else: # just in case there is anything left
                    # negative pid kills process group
                    os.kill(-self.pid, signal.SIGKILL)
            except OSError:
                dprint("TERMINAL: kill(), OSError")
                pass
            self.killed = 1
            if self.term.tab_showing[TAB_QUEUE]:
                # update the queue tree
                self.queue_clicked(self.queue_tree)
        dprint("TERMINAL: leaving kill()")
        return

    def overwrite(self, num, text, tagname = None):
        """ Overwrite text to a text buffer.  Line numbering based on
            the process window line count is automatically added.
            BUT -- if multiple text buffers are going to be updated,
            always update the process buffer LAST to guarantee the
            line numbering is correct.
            Optionally, text formatting can be applied as well
        """
        #dprint("TERMINAL: overwrite() -- num= %d:" %num)
        #dprint(self.term.current_tab)
        line_number = self.term.buffer[TAB_PROCESS].get_line_count() 
        iter = self.term.buffer[num].get_iter_at_line(line_number)
        iter.set_line_offset(7)
        end = iter.copy()
        end.forward_line()
        self.term.buffer[num].delete(iter, end)
        if tagname == None:
           self.term.buffer[num].insert(iter, text)
        else:
           self.term.buffer[num].insert_with_tags_by_name(iter, text, tagname)

    def append(self, num, text, tagname = None):
        """ Append text to a text buffer.  Line numbering based on
            the process window line count is automatically added.
            BUT -- if multiple text buffers are going to be updated,
            always update the process buffer LAST to guarantee the
            line numbering is correct.
            Optionally, text formatting can be applied as well
        """
        #dprint("TERMINAL: append() -- num= %d:" %num)
        #dprint(self.term.current_tab)
        line_number = self.term.buffer[TAB_PROCESS].get_line_count() 
        iter = self.term.buffer[num].get_end_iter()
        lntext = '000000' + str(line_number) + ' '
        self.term.buffer[num].insert_with_tags_by_name(iter, lntext[-7:] , 'linenumber')
        if tagname == None:
           self.term.buffer[num].insert(iter, text)
        else:
           self.term.buffer[num].insert_with_tags_by_name(iter, text, tagname)
        if self.term.auto_scroll[num] and num == self.term.current_tab:
            #dprint("TERMINAL: append() -- self.term.vadjustment[], self.term.vhandler_id[]")
            #dprint(self.term.vadjustment)
            #dprint(self.term.vhandler_id)
            #self.term.vadjustment[num].handler_block(self.term.vhandler_id[num])
            #result = self.term.view[num].scroll_to_iter(self.term.buffer[num].get_end_iter(),0.0, True, 0, 0.9)
            self.term.view[num].scroll_mark_onscreen(self.term.buffer[num].get_insert())
            #self.term.vadjustment[num].handler_unblock(self.term.vhandler_id[num])

    def append_all(self, text, all = False, tag = None):
        """ Append text to all buffers """
        # we need certain info in all tabs to know where
        # tab messages came from
        self.append(TAB_WARNING, text, tag)
        self.append(TAB_CAUTION, text, tag)
        self.append(TAB_INFO, text, tag)
        # NOTE: always write to the process_text buffer LAST to keep the
        # line numbers correct - see self.append above
        if all: # otherwise skip the process_text buffer
            self.append(TAB_PROCESS, text, tag)


    def update(self):
        """ Add text to the buffer """
        # stores line of text in buffer
        # if the string is locked, we'll get it on the next round
        cr_flag = False   # Carriage Return flag
        if self.reader.string_locked or not self.window_visible:
            return gtk.TRUE
        # lock the string
        self.reader.string_locked = True
        for char in self.reader.string:
            if char:
                # if we find a CR without a LF, switch to overwrite mode
                if cr_flag:
                    if char != '\n':
                        tag = None
                        if self.first_cr:
                            #dprint("TERMINAL: self.first_cr = True")
                            self.append(TAB_PROCESS, self.process_buffer, tag)
                            self.first_cr = False
                            self.overwrite_till_nl = True
                            self.process_buffer = ''
                        # overwrite until after a '\n' detected for this line
                        else:
                            #dprint("TERMINAL: self.first_cr = False")
                            self.overwrite(TAB_PROCESS, self.process_buffer, tag)
                            self.process_buffer = ''
                    else:
                        # reset for next time
                        self.first_cr = True
                    cr_flag = False
                # catch portage escape sequence NOCOLOR bugs
                if ord(char) == 27 or self.catch_seq:
                        self.catch_seq = True
                        if ord(char) != 27:
                            self.escape_seq += char
                        if char == 'm':
                            self.catch_seq = False
                            #dprint('escape_seq='+escape_seq)
                            self.escape_seq = ""
                elif char == '\b' : # backspace
                    self.process_buffer = self.process_buffer[:-1]
                elif ord(char) == 13:  # carriage return
                    cr_flag = True
                elif 32 <= ord(char) <= 127 or char == '\n': # no unprintable
                    self.process_buffer += char
                    if char == '\n': # newline
                        tag = None
                        
                        if self.config.isEmerge(self.process_buffer):
                            # add the pkg info to all other tabs to identify fom what
                            # pkg messages came from but no need to show it if it isn't
                            tag = 'emerge'
                            self.append(TAB_INFO, self.process_buffer, tag)
                            self.append(TAB_WARNING, self.process_buffer, tag)
                            if not self.file_input:
                                self.set_file_name(self.process_buffer)
                                self.set_statusbar(self.process_buffer[:-1])
                                self.resume_line = self.process_buffer

                        elif self.config.isInfo(self.process_buffer):
                            # Info string has been found, show info tab if needed
                            if not self.term.tab_showing[TAB_INFO]:
                                self.show_tab(TAB_INFO)
                                self.term.buffer[TAB_INFO].set_modified(gtk.TRUE)

                            # Check for fatal error
                            if self.config.isError(self.process_buffer):
                                self.Failed = True
                                tag = 'error'
                                self.append(TAB_INFO, self.process_buffer,'error')
                            else:
                                tag = 'info'
                                self.append(TAB_INFO, self.process_buffer)

                        elif self.config.isWarning(self.process_buffer):
                            # warning string has been found, show info tab if needed
                            if not self.term.tab_showing[TAB_WARNING]:
                                self.show_tab(TAB_WARNING)
                                self.term.buffer[TAB_WARNING].set_modified(gtk.TRUE)
                            # insert the line into the info text buffer
                            tag = 'warning'
                            self.append(TAB_WARNING, self.process_buffer)
                            self.warning_count += 1

                        elif self.config.isCaution(self.process_buffer):
                            # warning string has been found, show info tab if needed
                            if not self.term.tab_showing[TAB_CAUTION]:
                                self.show_tab(TAB_CAUTION)
                                self.term.buffer[TAB_CAUTION].set_modified(gtk.TRUE)
                            # insert the line into the info text buffer
                            tag = 'caution'
                            self.append(TAB_CAUTION, self.process_buffer)
                            self.caution_count += 1

                        if self.overwrite_till_nl:
                            #dprint("TERMINAL: '\\n' detected in overwrite mode")
                            self.overwrite(TAB_PROCESS, self.process_buffer, tag)
                            self.overwrite_till_nl = False
                        else:
                            self.append(TAB_PROCESS, self.process_buffer, tag)
                        self.process_buffer = ''  # reset buffer
                elif ord(char) == 13: # carriage return?
                    pass
            elif self.process_buffer == ">>> Updating Portage cache...":
                # print it to screen so the user knows what is happening
                self.append(TAB_PROCESS, self.process_buffer, tag)
                self.process_buffer = ''  # reset buffer
        self.reader.string = ""
        #dprint("TERMINAL: update() checking file input/reader finished")
        if self.file_input and not self.reader.file_input: # reading file finished
            dprint("LOG: update()... end of file input... cleaning up")
            self.term.buffer[TAB_PROCESS].set_modified(gtk.FALSE)
            self.finish_update()
            self.set_statusbar(_("*** Log loading complete : %s") % self.filename)
            self.reader.f.close()
            self.file_input = False
        # unlock the string
        self.reader.string_locked = False
        return gtk.TRUE

    def set_file_name(self, line):
        """extracts the ebuild name and assigns it to self.filename"""
        x = line.split("/")
        y = x[1].split(" ")
        name = y[0]
        self.filename = name + "." + self.term.buffer_types[TAB_PROCESS]
        dprint("TERMINAL: New ebuild detected, new filename: " + self.filename)
        return

    def set_statusbar(self, string):
        """Update the statusbar without having to use push and pop."""
        self.statusbar.pop(0)
        self.statusbar.push(0, string)

    def finish_update(self):
        if self.warning_count != 0:
            self.append(TAB_INFO, _("*** Total warnings count for merge = %d \n")\
                        %self.warning_count, 'note')
            if not self.term.tab_showing[TAB_INFO]:
                self.show_tab(TAB_INFO)
                self.term.buffer[TAB_INFO].set_modified(gtk.TRUE)
        if self.caution_count != 0:
            self.append(TAB_INFO, _("*** Total cautions count for merge = %d \n")\
                        %self.caution_count, 'note')
            if not self.term.tab_showing[TAB_INFO]:
                self.show_tab(TAB_INFO)
                self.term.buffer[TAB_INFO].set_modified(gtk.TRUE)
        return

    def process_done(self):
        """ Remove the finished process from the queue, and
        start the next one if there are any more to be run"""
        # Prevent conflicts while changing process queue
        self.Semaphore.acquire()
        dprint("TERMINAL: process_done; Semaphore acquired")
        
        # reset to None, so next one starts properly
        self.reader.fd = None
        # if the last process was killed, stop until the user does something
        if self.killed:
            # display message that process has been killed
            self.append_all(KILLED_STRING,True)
            self.set_statusbar(KILLED_STRING[:-1])
            # Clear semaphore, we're done
            self.Semaphore.release()
            dprint("TERMINAL: process_done; Semaphore released")
            return
            
        # If the user did an emerge --pretend, we print out
        # estimated build times on the output window
        if self.isPretend:
            self.estimate_build_time()
        self.finish_update()
        # display message that process finished
        self.append_all(TERMINATED_STRING,True)
        self.set_statusbar(TERMINATED_STRING[:-1])
        # try to get a callback
        try:
            callback = self.process_list[0][3]
        except:
            callback = None
        # set queue icon to done
        try:
            iter = self.process_list[0][2]
        	# set icon according to success or failure
            if self.Failed:
                self.queue_model.set_value(iter, 0, self.render_icon(gtk.STOCK_STOP))
            else:
                self.queue_model.set_value(iter, 0, self.render_icon(gtk.STOCK_APPLY))
        except: pass
        # remove process from list
        self.process_list = self.process_list[1:]
        # check for pending processes, and run them
        self.start_queue(False)
        # if there is a callback set, call it
        if callback:
            callback()
        if self.term.tab_showing[TAB_QUEUE]:
            # update the queue tree
            self.queue_clicked(self.queue_tree)

        # We're finished, release semaphore
        self.Semaphore.release()
        dprint("TERMINAL: process_done; Semaphore released")

    def render_icon(self, icon):
        """ Render an icon for the queue tree """
        return self.queue_tree.render_icon(icon,
                    size = gtk.ICON_SIZE_MENU, detail = None)

    def kill_process(self, widget):
        """ Kill currently running process """
        # Prevent conflicts while changing process queue
        self.Semaphore.acquire()
        dprint("TERMINAL: kill_process; Semaphore acquired")

        if not self.reader.process_running and not self.file_input:
            dprint("TERMINAL: No running process to kill!")
            # We're finished, release semaphore
            self.Semaphore.release()
            dprint("TERMINAL: kill_process; Semaphore released")
            return
        self.kill()
        if self.log_mode:
            dprint("LOG: set statusbar -- log killed")
            self.set_statusbar(_("***Log Process Killed!"))
        else:
            # set the queue icon to killed
            iter = self.process_list[0][2]
            self.queue_model.set_value(iter, 0, self.render_icon(gtk.STOCK_CANCEL))
            # set the resume buttons to sensitive
            self.set_resume(True)
        dprint("TERMINAL: leaving kill_process")

        # We're finished, release semaphore
        self.Semaphore.release()
        dprint("TERMINAL: kill_process; Semaphore released")
        return

    def extract_num(self, line):
        """extracts the number of packages from the 'emerge (x of y) cat/package
        for setting the resume menu entries"""
        first = string.index(line, "(") + 1
        last = string.index(line, ")")
        num = string.split(line[first:last], " ")
        return string.atoi(num[2]) - string.atoi(num[0])

    def set_resume(self, active):
        """sets the resume menu to the desired state,
        checking and setting the individual entries to their correct state
        at the time """
        if active:
            if self.resume_line:
                remaining = self.extract_num(self.resume_line)
            else:
                remaining = 0
                
            if remaining:  # > 0
                self.skip_first_menu.set_sensitive(gtk.TRUE)
            else:
                self.skip_first_menu.set_sensitive(gtk.FALSE)
            self.resume_menu.set_sensitive(gtk.TRUE)
            # check if there are more queue entries to process
            if len(self.process_list)> 1:
                self.skip_queue_menu.set_sensitive(gtk.TRUE)
            else:
                self.skip_queue_menu.set_sensitive(gtk.FALSE)
        else:
            self.resume_menu.set_sensitive(gtk.FALSE)
    
    def resume_normal(self, widget):
        """ Resume killed process """
        # pass the normal command along with --resume
        name, command, iter, callback = self.process_list[0]
        command += " --resume"
        self._run(command, iter)

    def resume_skip_first(self, widget):
        """ Resume killed process, skipping first package """

        # pass the normal command along with --resume --skipfirst
        name, command, iter, callback = self.process_list[0]
        command += " --resume --skipfirst"
        self._run(command, iter)

    # skip_first needs to be true for the menu callback
    def start_queue(self, skip_first = True):
        """skips the first item in the process_list"""
        dprint("TERMINAL: start_queue()")
        if skip_first:
            dprint("         ==> skipping killed process")
            self.resume_available = False
            # try to get a callback
            callback = self.process_list[0][3]
            # if there is a callback set, call it
            if callback:
                callback()
            if self.term.tab_showing[TAB_QUEUE]:
                # update the queue tree
                self.queue_clicked(self.queue_tree)
                # remove process from list
                self.process_list = self.process_list[1:]
        # check for pending processes, and run them
        #dprint(self.process_list)
        if len(self.process_list):
            dprint("TERMINAL: There are pending processes, running now... [" + \
                    self.process_list[0][0] + "]")
            self._run(self.process_list[0][1], self.process_list[0][2])
        else: # re-activate the open/save menu items
            self.save_menu.set_sensitive(gtk.TRUE)
            self.save_as_menu.set_sensitive(gtk.TRUE)
            self.open_menu.set_sensitive(gtk.TRUE)


    def copy_selected(self, widget):
        """ Copy selected text to clipboard """
        pass

    def clear_buffer(self, widget):
        """ Clear the text buffer """
        self.term.buffer[TAB_PROCESS].set_text('')
        self.term.buffer[TAB_WARNING].set_text('')
        self.term.buffer[TAB_CAUTION].set_text('')
        self.term.buffer[TAB_INFO].set_text('')
        self.term.buffer[TAB_PROCESS].set_modified(gtk.FALSE)
        self.term.buffer[TAB_WARNING].set_modified(gtk.FALSE)
        self.term.buffer[TAB_CAUTION].set_modified(gtk.FALSE)
        self.term.buffer[TAB_INFO].set_modified(gtk.FALSE)
        self.filename = None

    def queue_items_switch(self, direction):
        """ Switch two adjacent queue items;
            direction is either 1 [down] or -1 [up] """
        dprint("TERMINAL: Switching queue items.")
        # Prevent conflicts while changing process queue
        self.Semaphore.acquire()
        dprint("TERMINAL: queue_items_switch; Semaphore acquired")

        # get the selected iter
        iter = get_treeview_selection(self.queue_tree)
        # get its path
        path = self.queue_model.get_path(iter)[0]
        # only move up if it's not the first entry,
        # only move down if it's not the last entry
        if (not direction and path > 0) or \
           (direction and path < len(self.queue_model)):
            # get the selected value
            selected = self.queue_model[path]
            # get the adjacent value
            prev = self.queue_model[path + direction]
            # store selected temporarily so it's not overwritten
            temp = (selected[0], selected[1], selected[2])
            # switch sides and make sure the original is still selected
            self.queue_model[path] = prev
            self.queue_model[path + direction] = temp
            self.queue_tree.get_selection().select_path(path + direction)
            # switch the process list entries
            # basically similar to above, except that the iters are _not_ switched
            for pos in range(len(self.process_list)):
                if self.process_list[pos][0] == temp[1] and pos > 0:
                    sel = self.process_list[pos][0], self.process_list[pos][1],\
                          self.process_list[pos + direction][2], \
                          self.process_list[pos][3]
                    prev = self.process_list[pos + direction][0],\
                          self.process_list[pos + direction][1],\
                          self.process_list[pos][2],\
                          self.process_list[pos + direction][3]
                    self.process_list[pos] = prev
                    self.process_list[pos + direction] = sel
                    break
        else:
            dprint("TERMINAL: cannot move first or last item")
        self.queue_clicked(self.queue_tree)

        # We're done, release semaphore
        self.Semaphore.release()
        dprint("TERMINAL: queue_items_switch; Semaphore released")

    def move_queue_item_up(self, widget):
        """ Move selected queue item up in the queue """
        self.queue_items_switch(-1)

    def move_queue_item_down(self, widget):
        """ Move selected queue item down in the queue """
        self.queue_items_switch(1)

    def remove_queue_item(self, widget):
        """ Remove the selected item from the queue """
        # Prevent conflicts while changing process queue
        self.Semaphore.acquire()
        dprint("TERMINAL: remove_queue_item; Semaphore acquired")

        # get the selected iter
        iter = get_treeview_selection(self.queue_tree)
        # find if this item is still in our process list
        name = get_treeview_selection(self.queue_tree, 1)
        for pos in range(len(self.process_list)):
            if name == self.process_list[pos][0]:
                # remove the item from the list
                self.process_list = self.process_list[:pos] + \
                                    self.process_list[pos + 1:]
                break
        self.queue_model.remove(iter)

        # We're done, release semaphore
        self.Semaphore.release()
        dprint("TERMINAL: remove_queue_item; Semaphore released")

    def estimate_build_time(self):
        """Estimates build times based on emerge --pretend output"""
        start_iter = self.term.buffer[TAB_PROCESS].get_iter_at_mark(self.command_start)
        output = self.term.buffer[TAB_PROCESS].get_text(start_iter,
                                 self.term.buffer[TAB_PROCESS].get_end_iter(), gtk.FALSE)
        package_list = []
        total = datetime.timedelta()        
        for line in output.split("\n"):
            if self.config.ebuild_re.match(line):
                tokens = line.split(']')
                tokens = tokens[1].split()
                tmp_name = portagelib.get_name(tokens[0])
                name = ""
                # We want to get rid of the version number in the package name
                # because if a user is upgrading from, for instance, mozilla 1.4 to
                # 1.5, there's a good chance the build times will be pretty close.
                # So, we want to match only on the name
                for j in range(0, len(tmp_name)):
                    if tmp_name[j] == "-" and tmp_name[j+1].isdigit():
                        break
                    else:
                        name += tmp_name[j]        
                package_list.append(name)
        if len(package_list) > 0:  
            for package in package_list:
                try:
                    curr_estimate = estimate(package)
                except:
                    return None
                if curr_estimate != None:
                    total += curr_estimate
                else:
                    self.append(TAB_PROCESS,
                            "*** Unfortunately, you don't have enough " +
                            "logged information about the listed packages, " +
                            "so I can't calculate estimated build times " +
                            "accurately.\n", 'note')
                    return None
            self.append(TAB_PROCESS,
                        "*** Based on the build history of these packages " +
                        "on your system, I can estimate that emerging them " +
                        "usually takes, on average, " + 
                        "%d days, %d hrs, %d mins, and %d secs.\n" %
                        (total.seconds // (24 * 3600),\
                         (total.seconds % (24 * 3600)) // 3600,\
                         ((total.seconds % (24 * 3600))  % 3600) //  60,\
                         ((total.seconds % (24 * 3600))  % 3600) %  60), 'note')
            self.append(TAB_PROCESS,
                        "*** Note: If you have a lot of programs running on " +
                        "your system while porthole is emerging packages, " +
                        "or if you have changed your hardware since the " +
                        "last time you built some of these packages, the " +
                        "estimates I calculate may be inaccurate.\n", 'note')

    def queue_clicked(self, widget):
        """Handle clicks to the queue treeview"""
        # get the selected iter
        iter = get_treeview_selection(self.queue_tree)
        # get its path
        try:
            path = self.queue_model.get_path(iter)[0]
        except:
            dprint("TERMINAL: Couldn't get queue view treeiter path, " \
                   "there is probably nothing selected.")
            return
        # if the item is not in the process list
        # don't make the controls sensitive and return
        name = get_treeview_selection(self.queue_tree, 1)
        in_list = 0
        for pos in range(len(self.process_list)):
            if self.process_list[pos][0] == name:
                # set the position in the list (+1 so it's not 0)
                in_list = pos + 1
        if not in_list or in_list == 1:
            self.move_up.set_sensitive(gtk.FALSE)
            self.move_down.set_sensitive(gtk.FALSE)
            if not self.killed and in_list == 1:
                self.queue_remove.set_sensitive(gtk.FALSE)
            else:
                self.queue_remove.set_sensitive(gtk.TRUE)
            return
        # if we reach here it's still in the process list
        # activate the delete item
        self.queue_remove.set_sensitive(gtk.TRUE)
        # set the correct directions sensitive
        # shouldn't be able to move the top item up, etc...
        if in_list == 2 or path == 0:
            self.move_up.set_sensitive(gtk.FALSE)
            if path == len(self.queue_model) - 1:
                self.move_down.set_sensitive(gtk.FALSE)
            else:
                self.move_down.set_sensitive(gtk.TRUE)
        elif path == len(self.queue_model) - 1:
            self.move_up.set_sensitive(gtk.TRUE)
            self.move_down.set_sensitive(gtk.FALSE)
        else:
            # enable moving the item
            self.move_up.set_sensitive(gtk.TRUE)
            self.move_down.set_sensitive(gtk.TRUE)

    def set_save_buffer(self):
        """Sets the save info for the notebook tab's visible buffer"""
        dprint("TERMINAL: Entering set_save_buffer")
        self.buffer_num = self.term.current_tab
        self.buffer_to_save = self.term.buffer[self.buffer_num]
        self.buffer_type = self.term.buffer_types[self.buffer_num]
        dprint("TERMINAL: set_save_buffer: " + str(self.buffer_num) + " type: " + self.buffer_type)
        return (self.buffer_num != None)

    def open_ok_func(self, filename):
        """callback function from file selector"""
        dprint("LOG: Entering callback open_ok_func")
        # set terminal to log mode if not already
        self.log_mode = True
        if not self.window_visible: self.show_window()
        if not self.fill_buffer(filename):
            self.set_statusbar(_("*** Unknown File Loading error"))
            return gtk.FALSE
        else:
            self.filename = filename
            self.set_statusbar(_("*** File Loading... Processing...")) 
            return gtk.TRUE;

    def do_open(self, widget):
        """opens the file selector for file to open"""
        dprint("LOG: Entering do_open")
        if not self.directory:
            self.set_directory()
        try:
            FileSel(self.title + _(": Open log File")).run(self.window,
                                                        self.directory+"*.log",
                                                        self.open_ok_func)
        except:
            FileSel(self.title + _(": Open log File")).run(None,
                                                        self.directory+"*.log",
                                                        self.open_ok_func)
        dprint("LOG: leaving do_open")

    def do_save_as(self, widget):
        """determine buffer to save as and saves it"""
        dprint("LOG: Entering do_save_as")
        if not self.directory:
            self.set_directory()
        if self.set_save_buffer():
            result = self.check_buffer_saved(self.buffer_to_save, False)
        else:
            dprint("TERMINAL: Error: buffer is already saved")

    def do_save(self, widget):
        """determine buffer to save and proceed"""
        dprint("LOG: Entering do_save")
        if not self.directory:
            self.set_directory()
        if not self.filename:
            self.do_save_as(widget)
        else:
            if self.set_save_buffer():
                result = self.check_buffer_saved(self.buffer_to_save, True)
            else:
                dprint("LOG: set_save_buffer error")

    def save_as_buffer(self):
        dprint("LOG: Entering save_as_buffer")
        return FileSel(self.title + ": Save File").run(self.window,
                                                           self.filename,
                                                           self.save_as_ok_func)

    def save_as_ok_func(self, filename):
        """file selector callback function"""
        dprint("LOG: Entering save_as_ok_func")
        old_filename = self.filename

        if (not self.filename or filename != self.filename):
            if os.path.exists(filename):
                err = _("Ovewrite existing file '%s'?")  % filename
                dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                           gtk.MESSAGE_QUESTION,
                                           gtk.BUTTONS_YES_NO, err);
                result = dialog.run()
                dialog.destroy()
                if result != gtk.RESPONSE_YES:
                    return gtk.FALSE

        self.filename = filename

        if self.save_buffer():
            return gtk.TRUE
        else:
            self.filename = old_filename
            return gtk.FALSE

    def set_directory(self):
        """sets the starting directory for file selection"""
        if not self.directory:
            # no directory was specified, so we are making one up
            dprint("LOG: directory not specified, setting to ~/.porthole/logs")
            self.directory = get_user_home_dir()
            if os.access(self.directory + "/.porthole", os.F_OK):
                if not os.access(self.directory + "/.porthole/logs", os.F_OK):
                    dprint("LOG: Creating logs directory in " + self.directory +
                           "/.porthole/logs")
                    os.mkdir(self.directory + "/.porthole/logs")
                self.directory += "/.porthole/logs/"
                #os.chdir(self.directory)
 
    def pretty_name(self):
        """pre-assigns generic filename & serial #"""
        dprint("LOG: Entering pretty_name")
        # check if filename set and set the extension to the correct buffer type 
        if self.filename and self.filename[:7] != "Untitled":
            filename = os.path.basename(self.filename)
            filename = filename.split(".")
            newname = filename[0]
            for x in filename[1:-1]:
                newname += ("." + x)
            self.filename = newname + "." + self.buffer_type
            dprint(self.filename)
            return self.filename
        else: # Untitlted filename
            if not self.directory: # just in case it is not set
                self.set_directory()
            if self.untitled_serial == -1:
                self.untitled_serial = 1
            else:
                self.untitled_serial += 1
            filename = ("Untitled-%d.%s" % (self.untitled_serial, self.buffer_type))
            while os.path.exists(filename): # find the next available filename
                self.untitled_serial += 1
                filename = ("Untitled-%d.%s" % (self.untitled_serial, self.buffer_type))
            return filename

    def fill_buffer(self, filename):
        """loads a file into the reader.string"""
        dprint("LOG: Entering fill_buffer")
        self.clear_buffer(None)
        self.warning_count = 0
        self.caution_count = 0
        self.set_statusbar(_("*** Loading File : %s") % self.filename)
        try:
            self.reader.f = open(filename, "r")
        except IOError, (errnum, errmsg):
            err = _("Cannot open file '%s': %s") % (filename, errmsg)
            dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                       gtk.MESSAGE_INFO,
                                       gtk.BUTTONS_OK, err);
            result = dialog.run()
            dialog.destroy()
            return gtk.FALSE

        self.file_input = True
        self.reader.file_input = True
        return gtk.TRUE

    def save_buffer(self):
        """save the contents of the buffer"""
        dprint("LOG: Entering save_buffer")
        result = gtk.FALSE
        have_backup = gtk.FALSE
        if not self.filename:
            return gtk.FALSE

        bak_filename = self.filename + "~"
        try:
            os.rename(self.filename, bak_filename)
        except (OSError, IOError), (errnum, errmsg):
            if errnum != errno.ENOENT:
                err = _("Cannot back up '%s' to '%s': %s") % (self.filename,
                                                           bak_filename,
                                                           errmsg)
                dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                           gtk.MESSAGE_INFO,
                                           gtk.BUTTONS_OK, err);
                dialog.run()
                dialog.destroy()
                return gtk.FALSE

        have_backup = gtk.TRUE
        self.set_statusbar(_("*** saving file: %s") % self.filename)
        try:
            file = open(self.filename, "w")
            # if buffer is "Process" strip line numbers
            if self.buffer_num == TAB_PROCESS:
                start = self.buffer_to_save.get_start_iter()
                while not start.is_end():
                    end = start.copy(); end.forward_line()
                    chars = self.buffer_to_save.get_text(start, end, gtk.FALSE)
                    file.write(chars[7:])
                    chars = ""
                    start.forward_line()
                    
            else: # save the entire buffer
                start, end = self.buffer_to_save.get_bounds()
                chars = self.buffer_to_save.get_text(start, end, gtk.FALSE)
                file.write(chars)

            file.close()
            self.buffer_to_save.set_modified(gtk.FALSE)
            result = gtk.TRUE
        except IOError, (errnum, errmsg):
            err = ("Error writing to '%s': %s") % (self.filename, errmsg)
            dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                       gtk.MESSAGE_INFO,
                                       gtk.BUTTONS_OK, err);
            dialog.run()
            dialog.destroy()

        if not result and have_backup:
            try:
                os.rename(bak_filename, self.filename)
            except OSError, (errnum, errmsg):
                err = _("Can't restore backup file '%s' to '%s': %s\nBackup left as '%s'") % (
                    self.filename, bak_filename, errmsg, bak_filename)
                dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                           gtk.MESSAGE_INFO,
                                           gtk.BUTTONS_OK, err);
                dialog.run()
                dialog.destroy()

        self.set_statusbar(_("*** File saved : %s") % self.filename)
        dprint("LOG: Buffer saved, exiting")
        return result

    def check_buffer_saved(self, buffer, save = False):
        """checks if buffer has been modified before saving again"""
        dprint("LOG: Entering check_buffer_saved")
        self.filename = self.pretty_name()
        if buffer.get_modified():
            if save:
                msg = _("Save log to '%s'?") % self.filename
                dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                           gtk.MESSAGE_QUESTION,
                                           gtk.BUTTONS_YES_NO, msg);
                dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
                result = dialog.run()
                dialog.destroy()
                if result == gtk.RESPONSE_YES:
                    if self.filename:
                        return self.save_buffer()
                    return self.save_as_buffer()
                elif result == gtk.RESPONSE_NO:
                    return self.save_as_buffer()
                else:
                    return gtk.FALSE
            else: # save_as
                    return self.save_as_buffer()
        else:
            msg = "Buffer already saved &/or has not been modified: Proceed?"
            dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                       gtk.MESSAGE_QUESTION,
                                       gtk.BUTTONS_YES_NO, msg);
            dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
            result = dialog.run()
            dialog.destroy()
            if result == gtk.RESPONSE_YES:
                return self.save_as_buffer()
            elif result == gtk.RESPONSE_NO:
                return gtk.FALSE
            else:
                return gtk.FALSE

class FileSel(gtk.FileSelection):
    def __init__(self, title):
        gtk.FileSelection.__init__(self, title)
        self.result = gtk.FALSE

    def ok_cb(self, button):
        self.hide()
        if self.ok_func(self.get_filename()):
            self.destroy()
            self.result = gtk.TRUE
        else:
            self.show()

    def run(self, parent, start_file, func):
        if start_file:
            self.set_filename(start_file)

        self.ok_func = func
        self.ok_button.connect("clicked", self.ok_cb)
        self.cancel_button.connect("clicked", lambda x: self.destroy())
        self.connect("destroy", lambda x: gtk.main_quit())
        self.set_modal(gtk.TRUE)
        self.show()
        gtk.main()
        return self.result

class terminal_notebook:
    """generates a terminal notebook structure containing all needed views,
    buffers,handler id's, etc."""

    def __init__(self): # all arays follow the same TABS order
        self.view = [] #[None, None, None, None]
        self.scrolled_window = [] #[None, None, None, None, None]
        self.buffer = [] #[None, None, None, None]
        self.buffer_types = {TAB_PROCESS:"log",
                             TAB_WARNING:"warning",
                             TAB_CAUTION:"caution",
                             TAB_INFO:"info",
                             TAB_QUEUE:None}
        self.tab = [] #[None, None, None, None]
        self.visible_tablist = []
        self.tab_showing = [True, False, False, False, False] # initialize to default state
        self.current_tab = 0
        self.vadjustment = [] #[None, None, None, None, None]
        self.vhandler_id = [] #[None, None, None, None, None]
        self.auto_scroll = [True, False, False, False, False]
        self.get_tab_list() # initialize to default state


    def scroll_current_view(self):
        """scrolls the current_tab"""
        if self.current_tab != TAB_QUEUE:
            self.vadjustment[self.current_tab].handler_block(self.vhandler_id[self.current_tab])
            self.view[self.current_tab].scroll_mark_onscreen(self.buffer[self.current_tab].get_insert())
            self.vadjustment[self.current_tab].handler_unblock(self.vhandler_id[self.current_tab])

    def get_tab_list(self):
        """creates the current notebook tab list"""
        #tabs_showing = 0
        self.visible_tablist = []
        tab_num = 0
        #dprint("TERMINAL: get_tab_list -- self.tab_showing")
        #dprint(self.tab_showing)
        for tab in self.tab_showing:
            #dprint(tab_num)
            #dprint(tab)
            if tab:
                self.visible_tablist += [tab_num]
            tab_num += 1
        dprint("TERMINAL: terminal_notebook() new self.visible_tablist:")
        dprint(self.visible_tablist)
        return

    def get_current_vadjustment_value(self):
        """gets the value for the currently showing tab"""
        return self.vadjustment[self.current_tab].get_value()


class ProcessOutputReader(threading.Thread):
    """ Reads output from processes """
    def __init__(self, finished_callback):
        """ Initialize """
        threading.Thread.__init__(self)
        # set callback
        self.finished_callback = finished_callback
        self.setDaemon(1)  # quit even if this thread is still running
        self.process_running = False
        # initialize only, self.fd set by ProcessManager._run()
        self.fd = None
        # initialize only, both set by Processmanager.fill_buffer()
        self.file_input = False
        self.f = None
        # string to store input from process
        self.string = ""
        # lock to prevent loosing characters from simultaneous accesses
        self.string_locked = False

    def run(self):
        """ Watch for process output """
        char = None
        while True:
            if self.process_running or self.file_input:
                # get the output and pass it to self.callback()
                if self.process_running and (self.fd != None):
                    try:
                        char = os.read(self.fd, 1)
                    except OSError:
                        # maybe the process died?
                        char = None
                elif self.file_input:
                    try:
                        # keep read(number) small so as to not cripple the 
                        # system reading large files.  even 2 can hinder gui response
                        char = self.f.read(1)
                    except OSError:
                        # maybe the process died?
                        char = None
                if char:
                    # if the string is currently being accessed
                    while(self.string_locked):
                        # wait 50 ms and check again
                        time.sleep(0.05)
                    # lock the string
                    self.string_locked = True
                    # add the character to the string
                    self.string += char
                    # unlock the string
                    self.string_locked = False
                else:
                    # clean up, process is terminated
                    self.process_running = False
                    while self.string != "":
                        dprint("TERMINAL ProcessOutputReader: waiting for update to finish")
                        # wait for update_callback to finish
                        time.sleep(.5)
                    if self.file_input:
                        self.file_input = False
                    else:
                        gtk.threads_enter()
                        self.finished_callback()
                        gtk.threads_leave()
            else:
                # sleep for .5 seconds before we check again
                time.sleep(.5)


if __name__ == "__main__":

    def callback():
        """ Print a message to display that callbacks are working"""
        dprint("TERMINAL: Callback caught...")
    
    DATA_PATH = "/usr/share/porthole/"

    from sys import argv, exit, stderr
    from getopt import getopt, GetoptError
    import utils

    try:
        opts, args = getopt(argv[1:], "lvd", ["local", "version", "debug"])
    except GetoptError, e:
        print >>stderr, e.msg
        exit(1)

    for opt, arg in opts:
        if opt in ('-l', "--local"):
            # running a local version (i.e. not installed in /usr/*)
            DATA_PATH = ""
        elif opt in ('-v', "--version"):
            # print version info
            print "Porthole-Terminal " + version
            exit(0)
        elif opt in ('-d', "--debug"):
            utils.debug = True
            utils.dprint("Debug printing is enabled")
    # change dir to your data path
    if DATA_PATH:
        from os import chdir
        chdir(DATA_PATH)
    # make sure gtk lets threads run
    gtk.threads_init()
    # setup our app icon
    myicon = gtk.gdk.pixbuf_new_from_file("pixmaps/porthole-icon.png")
    gtk.window_set_default_icon_list(myicon)
    # load prefs
    prefs = utils.PortholePreferences()
    env = utils.environment()
    # to test the above classes when run standalone
    test = ProcessManager(env, prefs)
    test.title = "Porthole-Terminal"
    test.add_process("kde (-vp)", "emerge -vp kde", callback)
    # un-comment the next line to get the queue to show up
    test.add_process("gnome (-vp)", "emerge -vp gnome", callback)
    test.add_process("gtk+ (-vp)", "emerge -vp gtk+", callback)
    test.add_process("bzip2 (-v)", "emerge -v bzip2", callback)
    # start the program loop
    gtk.mainloop()
    # save the prefs to disk for next time
    prefs.save()
