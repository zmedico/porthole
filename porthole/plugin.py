import os
from glob import glob
import gtk
import utils
import imp
from utils import dprint

class PluginManager:
    """Handles all of our plugins"""
    def __init__( self, path_list, porthole_instance ):
	#Scan through the contents of the directories
	#Load any plugins it sees
	self.path_list = path_list
	self.porthole_instance = porthole_instance
	self.plugins = []
	for directory in path_list:
	    if directory == "cwd":
		directory = os.getcwd()
	    os.chdir(directory)
	    possible_plugins = glob("*_pplug.py")
	    for i in possible_plugins:
		new_pp = Plugin(i[:-3], directory, self )
		if new_pp.valid:
		    self.plugins.append( new_pp )
	self.event_all( "load", self )

    def event_all( self, event, *args ):
	for i in self.plugins:
	    i.event( event, *args )

    def plugin_list ( self ):
	return self.plugins

    #Later on, I'm hoping to be able to give the plugin itself a new view/tab
    def new_tab( plugin ):
	pass

    def new_menuitem( self, label ):
	menuitem = self.porthole_instance.new_plugin_menuitem( label )
	return menuitem

    def del_menuitem( self, menuitem ):
	self.porthole_instance.del_plugin_menuitem( menuitem )

    def new_package_tab( self, *args):
	#I separate the main window from the plugins in case if we ever want to execute the plugins in a separate thread
	return self.porthole_instance.new_plugin_package_tab( *args )

    def del_package_tab( self, *args):
	return self.porthole_instance.del_plugin_package_tab( *args )

    def destroy( self ):
	for i in self.plugins:
	    i.event("unload")

    def get_plugin( self, plugin_name ):
	for i in self.plugins:
	    if i.name == plugin_name:
		return i
	return None

class Plugin:
    """Class that defines all of our plugins"""
    def __init__( self, name, path, manager ):
	dprint("New plugin being made: "+ name + ", " + path)
	self.name = name
	self.path = path
	self.manager = manager
	initialized = self.initialize_plugin()
	self.enabled = False

    def initialize_plugin( self ):
	try:
		os.chdir(self.path)
		find_results = imp.find_module( self.name )
		self.module = imp.load_module( self.name, *find_results )
		self.valid = True
	except ImportError:
		dprint("Unable to find plugin " + self.name)
		self.valid = False
		return False
	find_results[0].close()

	self.event_table = self.module.event_table
	self.desc = self.module.desc

    def toggle_enabled( self ):
	if self.enabled == True:
	    self.enabled = False
	    self.event( "disable" )
	else:
	    self.enabled = True
	    self.event( "enable" )
	    

    def event( self, event, *args ):
	dprint("Event: " + event + ", Plugin: " + self.name )
	return self.event_table[event]( *args )

class PluginGUI( gtk.Window ):
    """Class to implement plugin architecture."""

    def __init__( self, prefs, plugin_manager ):
	""" Initialize Plugins Dialog Window """
        # Preserve passed parameters and manager
        self.prefs = prefs
	self.plugin_manager = plugin_manager
        self.gladefile = self.prefs.DATA_PATH + "porthole.glade"
	self.wtree = gtk.glade.XML(self.gladefile, "plugin_dialog", self.prefs.APP)

	# Connect Callbacks
	callbacks = {
		"on_okbutton_clicked": self.destroy_cb,
		"on_plugin_dialog_destroy": self.destroy_cb
	}
        self.wtree.signal_autoconnect(callbacks)

	self.create_plugin_list()
	
    def add_vbox_widgets( self ):
	return_button = gtk.Button("Return")
	return_button.connect( "clicked", self.destroy_cb )
	self.vbox.pack_end( return_button, TRUE, TRUE, 0)
	self.textbuffer = gtk.TextBuffer()	
	self.textbox = gtk.TextView( self.textbuffer )
	self.vbox.pack_start( self.textbox )
	
    def create_plugin_list( self ):
	"""Creates the list-view of the plugins"""
	self.plugin_view = self.wtree.get_widget("plugin_view")
	self.liststore = gtk.ListStore( bool, str )
	self.plugin_view.set_model( self.liststore )
	for i in self.plugin_manager.plugin_list(): 
		#We should really check our prefs here to see if they should automatically be enabled.
		self.liststore.append([i.enabled, i.name])
	cb_column = gtk.TreeViewColumn()
	text_column = gtk.TreeViewColumn()

	cell_tg = gtk.CellRendererToggle()
	cell_tx = gtk.CellRendererText()

	cb_column.pack_start(cell_tg)
	text_column.pack_start(cell_tx)

	self.plugin_view.append_column(cb_column)
	self.plugin_view.append_column(text_column)

	cb_column.add_attribute(cell_tg,"active",0)
	text_column.add_attribute(cell_tx,"text",1)
	cell_tg.connect( "toggled", self.cb_toggled )
	selection = self.plugin_view.get_selection()
	selection.set_mode(gtk.SELECTION_SINGLE)
	selection.connect( "changed", self.sel_changed )
	selection.select_iter(self.liststore.get_iter_first())
	selection.emit("changed")
		

    #Callbacks:
    def cb_toggled( self, widget, *args ):
	"""Handles the enabled/disabled checkbox"""
	selection = self.plugin_view.get_selection()
	treemodel, row = selection.get_selected()
	changed_plugin_name = treemodel.get(row, 1)
	if not row:
	    return
	changed_plugin = self.plugin_manager.get_plugin( *changed_plugin_name )
	changed_plugin.toggle_enabled()
	treemodel.set(row, 0, changed_plugin.enabled)

    def sel_changed( self, selection, *args ):
	treemodel, row = selection.get_selected()
	changed_plugin_name = treemodel.get(row, 1)
	if not row:
	    return
	changed_plugin = self.plugin_manager.get_plugin( *changed_plugin_name )
	plugin_desc = self.wtree.get_widget("plugin_desc")
	text_buffer = gtk.TextBuffer()
	text_buffer.set_text(changed_plugin.desc)
	plugin_desc.set_buffer(text_buffer)
	#Load a plugin's option screen here
    

    def destroy_cb( self, *args ):
	window = self.wtree.get_widget("plugin_dialog")
	if window:
		window.destroy()
	