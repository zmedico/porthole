#!/usr/bin/env python

"""
    PortageLib
    An interface library to Gentoo's Portage

    Copyright (C) 2003 Fredrik Arnerup and Daniel G. Taylor

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
"""

from sys import exit, stderr
try:    
    import portage
except ImportError:
    exit('Could not find portage module.\n'
         'Are you sure this is a Gentoo system?')

import threading, os, grp
from metadata import parse_metadata

version = '0.1'
debug = False

portdir = portage.config().environ()['PORTDIR']
# is PORTDIR_OVERLAY always defined?
try: portdir_overlay = portage.config().environ()['PORTDIR_OVERLAY']
except: portdir_overlay = None
    
# lower case is nicer
keys = [key.lower() for key in portage.auxdbkeys]

def write_access():
    """Returns true if process runs as root."""
    return os.geteuid() == 0

def read_access():
    """Return true if user is root or a member of the portage group."""
    # Note: you don't have to be a member of portage to read the database,
    # but portage caching will not work
    portage = 250  # is portage guaranteed to be 250?
    try: portage = grp.getgrnam("portage")[2]
    except: pass
    return write_access() or (portage in (os.getgroups() + [os.getegid()]))

def dprint(message):
    """Print debug message if debug is true."""
    if debug:
        print >>stderr, message

def get_name(full_name):
    """Extract name from full name."""
    return full_name.split('/')[1]

def get_category(full_name):
    """Extract category from full name."""
    return full_name.split('/')[0]

def get_installed(full_name):
    return portage.db['/']['vartree'].dep_match(full_name)

def get_version(ebuild):
    """Extract version number from ebuild name"""
    result = ''
    parts = portage.catpkgsplit(ebuild)
    if parts:
        result = parts[2]
        if parts[3] != 'r0':
            result += '-' + parts[3]
    return result

# this is obsolete
def get_property(ebuild, property):
    """Read a property of an ebuild. Returns a string."""
    # portage.auxdbkeys contains a list of properties
    try: return portage.portdb.aux_get(ebuild, [property])[0]
    except: return ''

class Properties:
    """Contains all variables in an ebuild."""
    def __init__(self, dict = None):
        self.__dict = dict
        
    def __getattr__(self, name):
        try: return self.__dict[name].decode('ascii')  # return unicode
        except: return u""  # always return something
        
    def get_slot(self):
        """Return slot number as an integer."""
        try: return int(self.slot)
        except ValueError: return 0   # ?

    def get_keywords(self):
        """Returns a list of strings."""
        return self.keywords.split()

    def get_use_flags(self):
        """Returns a list of strings."""
        return self.use_flags.split()

    def get_homepages(self):
        """Returns a list of strings."""
        return self.homepage.split()

def get_properties(ebuild):
    """Get all ebuild variables in one chunk."""
    return Properties(dict(zip(keys,
                               portage.portdb.aux_get(ebuild,
                                                      portage.auxdbkeys))))
    
def get_metadata(package):
    # we could check the overlay as well,
    # but we are unlikely to find any metadata files there
    try: return parse_metadata(portdir + "/" + package + "/metadata.xml")
    except: return None

class Package:
    """An entry in the package database"""

    def __init__(self, full_name):
        self.full_name = full_name
        self.is_installed = bool(self.get_installed())  # true if installed

    def get_installed(self):
        """Returns a list of all installed ebuilds."""
        return get_installed(self.full_name)
    
    def get_name(self):
        return get_name(self.full_name)

    def get_category(self):
        return get_category(self.full_name)

    def get_latest_ebuild(self, include_masked = 1):
        criterion = include_masked and 'match-all' or 'match-visible'
        return portage.best(portage.portdb.xmatch(criterion, self.full_name))

    def get_metadata(self):
        return get_metadata(self.full_name)

    def get_properties(self):
        """Returns properties of latest ebuild."""
        try:
            latest = self.get_latest_ebuild()
            if not latest:
                raise Exception('No ebuild found.')
            return get_properties(latest)
        except Exception, e:
            dprint(e)
            return Properties()

    def get_versions(self):
        """Returns all versions of the available ebuild"""
        return portage.db['/']['porttree'].dep_match(self.full_name)

def sort(list):
    """sort in alphabetic instead of ASCIIbetic order"""
    spam = [(x[0].upper(), x) for x in list]
    spam.sort()
    return [x[1] for x in spam]


class Database:
    def __init__(self):
        # category dictionary with sorted lists of packages
        self.categories = {}
        self.list = []  # all packages in a list sorted by package name
        
    def get_package(self, full_name):
        """Get a Package object based on full name."""
        try:
            category = get_category(full_name)
            name = get_name(full_name)
            if (category in self.categories
                and name in self.categories[category]):
                return self.categories[category][name]
            else:
                return None
        except:
            return None


class DatabaseReader(threading.Thread):
    """Builds the database in a separate thread."""

    def __init__(self):
        threading.Thread.__init__(self)
        self.setDaemon(1)     # quit even if this thread is still running
        self.db = Database()  # the database
        self.done = 0         # false if the thread is still working
        self.count = 0        # number of packages read so far
        self.error = ""       # may contain error message after completion

    def get_db(self):
        """Returns the database that was read."""
        return self.db

    def read_db(self):
        tree = portage.db['/']['porttree']
        try:
            allnodes = tree.getallnodes()
        except OSError, e:
            # I once forgot to give read permissions
            # to an ebuild I created in the portage overlay.
            self.error = str(e)
            return
        for entry in allnodes:
            category, name = entry.split('/')
            if name == 'timestamp.x':  # why does getallnodes()
                continue               # return timestamps?
            self.count += 1
            data = Package(entry)
            self.db.categories.setdefault(category, {})[name] = data;
            self.db.list.append((name, data))
        self.db.list = sort(self.db.list)

    def run(self):
        """The thread function."""
        self.read_db()
        self.done = 1   # tell main thread that this thread has finished




if __name__ == "__main__":
    # test program
    debug = True
    print (read_access() and "Read access" or "No read access")
    print (write_access() and "Write access" or "No write access")
    import time, sys
    db_thread = DatabaseReader(); db_thread.start()
    while not db_thread.done:
        print >>sys.stderr, db_thread.count,
        time.sleep(0.1)
    print
    db = db_thread.get_db()
    while 1:
        print; print "Enter full package name:"
        queries = sys.stdin.readline().split()
        for query in queries:
            print; print query
            package = db.get_package(query)
            if not package:
                print "--- unknown ---"
                continue
            props = package.get_properties()
            print "Homepages:", props.get_homepages()
            print "Description:", props.description
            print "License:", props.license
            print "Slot:", props.get_slot()
            print "Keywords:", props.get_keywords()
            print "USE flags:", props.get_use_flags()
            print "Installed:", package.get_installed()
            print "Latest:", get_version(package.get_latest_ebuild())
            print "Latest unmasked:", get_version(package.get_latest_ebuild(0))
