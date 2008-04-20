#!/usr/bin/env python

'''
    Porthole
    A graphical frontend to Portage

    Copyright (C) 2003 - 2005 Fredrik Arnerup and Daniel G. Taylor,
    Brian Dolbec, William F. Wheeler, Brian Bockelman, Tommy Iorns

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
'''

# proper way to enable threading.  Do this first before any other code
import gobject
gobject.threads_init()
# now for the rest

APP = 'porthole'

# setup our path so we can load our custom modules
import sys, os

# Add path to portage module if 
# missing from path (ref bug # 924100)
PORTAGE_MOD_PATH = '/usr/lib/portage/pym'
if PORTAGE_MOD_PATH not in sys.path:
    sys.path.append(PORTAGE_MOD_PATH)
#~ GENTOOLKIT_PATH = '/usr/lib/gentoolkit/pym'
#~ if GENTOOLKIT_PATH not in sys.path:
    #~ sys.path.append(GENTOOLKIT_PATH)
    
#while '' in sys.path: # we don't need the cwd in the path
#    sys.path.remove('')
while '/usr/bin' in sys.path: # this gets added when we run /usr/bin/porthole
    sys.path.remove('/usr/bin')

LOG_FILE_DIR = "/var/log/porthole"

Choices = {"portage": 'backends.portagelib', "pkgcore": 'backends.pkgcore_lib', "dbus": "backends.dbus_main" }
BACKEND = Choices["portage"]
DATA_PATH = "/usr/share/porthole/"
i18n_DIR = DATA_PATH + 'i18n'
RUN_LOCAL = False



import os
# check if directory exists, if not create it
if not os.access(LOG_FILE_DIR, os.F_OK):
    print LOG_FILE_DIR + " does not exist, creating..."
    try:
        os.mkdir(LOG_FILE_DIR)
    except OSError, (errnum, errmsg):
        print "Failed to create %s:" % LOG_FILE_DIR, errmsg

#from thread import *
import pygtk; pygtk.require("2.0") # make sure we have the right version
import gtk, time, pwd
while '/usr/bin' in sys.path: # and now importing gtk re-adds it! Grrrr, rude
    sys.path.remove('/usr/bin')
from getopt import getopt, GetoptError
import locale, gettext
from gettext import gettext as _

# it is recommended to init threads right after importing gtk just in case
#gtk.threads_init()
#gtk.gdk.threads_init()

import utils.debug

try:
    from pycrash.utils import *
    pycrash_found = True
    class MyCrash(HTMLPyCrash):
        def onExceptionRaised(self, time):
            save_file = LOG_FILE_DIR + "/crash_" + pwd.getpwuid(os.getuid())[0] + ".html"
            # saveToFile does not yet return a result: feature request submitted
            self.saveToFile(save_file)
            err = "*** PORTHOLE: Crash detected! ***\nPlease submit a bug report including\n"
            err = err + "all debug text from the terminal you ran porthole from.\n"
            err = err + ("Plus the the file: %s" %save_file)
            print err
            dialog = gtk.MessageDialog(None, gtk.DIALOG_MODAL,
                                       gtk.MESSAGE_ERROR,
                                       gtk.BUTTONS_OK, _(err));
            result = dialog.run()
            dialog.destroy()
            
except ImportError:
    pycrash_found = False


def import_error(e):
	print "*** Error loading porthole modules!\n*** If you are running a", \
		"local (not installed in python's site-packages) version, please use the '--local'", \
		"or '-l' flag.\n", \
		"*** Otherwise, verify that porthole was installed correctly and", \
		"that python's path includes the site-packages directory.\n",\
		"If you have recently updated python, then run 'python-updater'\n"
	print "Your sys.path: %s\n" % sys.path
	print "Your sys.version: %s\n" % sys.version
	print "Original exception was: ImportError: %s\n" % e
	sys.exit()

def local():
    global DATA_PATH, i18n_DIR, RUN_LOCAL
    # if opt in ("-l", "--local"):
    # running a local version (i.e. not installed in /usr/*)
    from os import getcwd
    print "STARTUP: local(); setting to local paths"
    DATA_PATH = getcwd() + "/"
    i18n_DIR = DATA_PATH + 'i18n'
    RUN_LOCAL = True

def set_debug(arg):
    utils.debug.set_debug(True)
    print("Debug printing is enabled = ", utils.debug.debug)
    utils.debug.debug_target = arg
    print("Debug print filter set to ", arg)
    if not pycrash_found:
        print("*** PYCRASH MODULE NOT FOUND ***\n*** For best debug info Please emerge >= dev-python/pycrash-0.4pre3 ***")

def print_version():
    # print version info
    print "Porthole " + version
    sys.exit(0)

def set_backend(arg):
    if arg in choices:
        BACKEND = choices[arg]
    else:
        useage()

def insert_path():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    print(sys.path)


def main():
    """star the porthole frontend"""
    try:
        print "STARTUP: main(); importing config"
        import config
        print "STARTUP: main(); importing config.preferences"
        import config.preferences
        # load prefs
        prefs_additions = [
            ["DATA_PATH",DATA_PATH],
            ["APP",APP],
            ["i18n_DIR",i18n_DIR],
            ["RUN_LOCAL",RUN_LOCAL],
            ["LOG_FILE_DIR",LOG_FILE_DIR],
            ["PORTAGE", BACKEND]
        ]
        print "STARTUP: main(); loading preferences"
        config.Prefs = config.preferences.PortholePreferences(prefs_additions)
        #print config.Prefs
        print "STARTUP: main(); importing version"
        from version import version
        print "STARTUP: main(); importing utils"
        import utils
        print "PORTHOLE: importing MainWindow"
        from mainwindow import MainWindow
    except ImportError, e:
        import_error(e)

    locale.setlocale (locale.LC_ALL, '')
    gettext.bindtextdomain (APP, i18n_DIR)
    gettext.textdomain (APP)
    gettext.install (APP, i18n_DIR, unicode=1)
    gtk.glade.bindtextdomain (APP, i18n_DIR)
    gtk.glade.textdomain (APP)

    if pycrash_found == True:
        utils.debug.dprint("pycrash module initializing")
        utils.debug.dprint("If a crash occurs check the " + LOG_FILE_DIR + "/crash_" + pwd.getpwuid(os.getuid())[0] + ".html file and post it to porthole bugs")
        p = MyCrash({'AppName': 'Porthole', 'Version': version, 'SendTo': 'porthole bugs'})
        p.enable() #New in PyCrash-0.4pre2
    # make sure gtk lets threads run
    #os.putenv("PYGTK_USE_GIL_STATE_API", "True")
    gtk.gdk.threads_init()

    utils.debug.dprint("PORTHOLE: process id = %d ****************" %os.getpid())
    # setup our app icon
    myicon = gtk.gdk.pixbuf_new_from_file(DATA_PATH + "pixmaps/porthole-icon.png")
    gtk.window_set_default_icon_list(myicon)
    # load config info
    config.Config.set_path(DATA_PATH)
    config.Config.load()
    config.Prefs.use_gladefile = "not assigned"
    # create the main window
    myapp = MainWindow() #config.Prefs, config.Config)
    # start the program loop
    gtk.main()
    # save the prefs to disk for next time
    config.Prefs.save()
