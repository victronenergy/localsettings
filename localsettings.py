#!/usr/bin/env python

## @package localsettings
# Dbus-service for local settings.
#
# The local-settings-dbus-service provides the local-settings storage in non-volatile-memory.
# The settings are stored in the settings.xml file. At startup the xml file is parsed and
# the dbus-service with his paths are created from the content of the xml file.
# <Settings></Settings> is the root of the xml file. A group of settings is a child of
# the root <Settings>. A setting is a child of a group and contains text.
# (e.g. <LogInterval>900</LogInterval>.
# Example 1:
# <Settings>
# 	<Logging>
#		<LogInterval>900</LogInterval>
#	</Logging>
# </Settings>
# This will be parsed as an dbus-object-path /Settings/Logging/LogInterval.
# A setting can have different types. The types are s (string), i (integer) and f (float).
# A setting can have a minimum, a maximum and a default value.
# These are set as an attribute of a (setting) element.
# Example 2: <Brigthness type="i" min="0" max="100" default="100">100</Brigthness>
# Example 3: <LogInterval type="i" min="5" default="900">900</LogInterval>
# Example 4: <LogPath type="s" default=".">.</LogPath>
# Settings or a group of settings can be set to default. A setting (and group) can be
# added by means of dbus. And of course a setting can be changed by means of dbus.
# By means of the file settingchanges.xml settings can be added or deleted. This file
# is processed at startup and then deleted.


# Python imports
from dbus.mainloop.glib import DBusGMainLoop
import dbus
import dbus.service
from gobject import timeout_add, source_remove, MainLoop
from os import system, path, getpid, remove
import sys
import signal
from lxml import etree
import getopt

# Local imports
import tracing
import platform

## Major version.
FIRMWARE_VERSION_MAJOR = 0x00
## Minor version.
FIRMWARE_VERSION_MINOR = 0x01
## Localsettings version.
version = (FIRMWARE_VERSION_MAJOR << 8) | FIRMWARE_VERSION_MINOR

## Traces (info / debug) setup
pathTraces = '/var/log/'
traceFileName = 'localsettingstraces'
tracingEnabled = False
traceToConsole = False
traceToFile = False
traceDebugOn = False

## The dbus bus and bus-name.
bus = None
busName = None

## Dbus service name and interface name(s).
dbusName = 'com.victronenergy.settings'
InterfaceBusItem = 'com.victronenergy.BusItem'
InterfaceSettings = 'com.victronenergy.Settings'

## The dictonary's containing the settings and the groups.
settings = {}
groups = []

## Index values for settings.
VALUE = 0
ATTRIB = 1

## ATTRIB keywords.
TYPE='type'
MIN='min'
MAX='max'
DEFAULT='default'

## Supported types for convert xml-text to value.
supportedTypes = {
		'i':int,
		's':str,
		'f':float,
}

## The list of MyDbusService(s).
myDbusServices = []
myDbusGroupServices = []

## File related stuff.
timeoutSaveSettingsEventId = None
timeoutSaveSettingsTime = 5 # Timeout value in seconds.
fileSettings = 'settings.xml'
fileSettingChanges = 'settingchanges.xml'

## Path(s) definitions.
pathSettings = '/conf/' 
pathTraces = '/var/log/'

class MyDbusObject(dbus.service.Object):
	global InterfaceBusItem

	## Constructor of MyDbusObject
	#
	# Creates the dbus-object under the given bus-name (dbus-service-name).
	# @param busName Return value from dbus.service.BusName, see run()).
	# @param objectPath The dbus-object-path (e.g. '/Settings/Logging/LogInterval').
	def __init__(self, busName, objectPath):
		dbus.service.Object.__init__(self, busName, objectPath)

	## Dbus method GetDescription
	#
	# Returns the a description. Currently not implemented.
	# Alwayes returns 'no description available'.
	# @param language A language code (e.g. ISO 639-1 en-US).
	# @param length Lenght of the language string. 
	# @return description Always returns 'no description available'
	@dbus.service.method(InterfaceBusItem, in_signature = 'si', out_signature = 's')
	def GetDescription(self, language, length):
		return 'no description available'
	
	## Dbus method GetValue
	# Returns the value of the dbus-object-path (the settings).
	# When the object-path is a group a -1 is returned.
	# @return setting A setting value or -1 (error)
	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetValue(self):
		global settings
		global groups
		if self._object_path in groups:
			return -1
		return settings[self._object_path][VALUE]
	
	## Dbus method GetText
	# Returns the value as string of the dbus-object-path (the settings).
	# When the object-path is a group a '' is returned.
	# @return setting A setting value or '' (error)
	@dbus.service.method(InterfaceBusItem, out_signature = 's')
	def GetText(self):
		global settings
		if self._object_path in groups:
			return ''
		return str(settings[self._object_path][VALUE])

	## Dbus method SetValue
	# Sets the value of a setting. When the type of the setting is a integer or float,
	# the new value is checked according to minimum and maximum.
	# @param value The new value for the setting.
	# @return completion-code When successful a 0 is return, and when not a -1 is returned.
	@dbus.service.method(InterfaceBusItem, in_signature = 'v', out_signature = 'i')
	def SetValue(self, value):
		global settings
		global supportedTypes
		
		if self._object_path in groups:
			return -1
		okToSave = True
		v = value
		path = self._object_path
		if TYPE in settings[path][ATTRIB]:
			itemType = settings[path][ATTRIB][TYPE]
			if itemType in supportedTypes:
				try:
					v = convertToType(itemType, value)
					if MIN in settings[path][ATTRIB]:
						if v < convertToType(itemType, settings[path][ATTRIB][MIN]):
							okToSave = False
					if MAX in settings[path][ATTRIB]:
						if v > convertToType(itemType, settings[path][ATTRIB][MAX]):
							okToSave = False
				except:
					okToSave = False
		if okToSave == True:
			if v != settings[path][VALUE]:
				self._setValue(v)
			return 0
		else:
			return -1

	## Sets the value and starts the time-out for saving to the settings-xml-file.
	# @param value The new value for the setting.
	def _setValue(self, value):
		global settings

		tracing.log.info('_setValue %s %s' % (self._object_path, value))
		settings[self._object_path][VALUE] = value
		self._startTimeoutSaveSettings()
		text = self.GetText()
		change = {'Value':value, 'Text':text}
		self.PropertiesChanged(change)

	@dbus.service.signal(InterfaceBusItem, signature = 'a{sv}')
	def PropertiesChanged(self, changes):
		tracing.log.debug('signal PropertiesChanged')

	## Method for starting the time-out for saving to the settings-xml-file.
	# (Re)Starts the time-out. When after x time no settings are changed,
	# the settings-xml-file is saved.
	def _startTimeoutSaveSettings(self):
		global timeoutSaveSettingsEventId
		global timeoutSaveSettingsTime

		if timeoutSaveSettingsEventId is not None:
			source_remove(timeoutSaveSettingsEventId)
			timeoutSaveSettingsEventId = None
		timeoutSaveSettingsEventId = timeout_add(timeoutSaveSettingsTime*1000, saveSettingsCallback)

	## Dbus method GetDefault.
	# Returns the default value of a setting.
	# @return value The default value or -1 (error or no default set)
	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetDefault(self):
		global settings
		path = self._object_path
		if path in groups:
			return -1
		try:
			type = settings[path][ATTRIB][TYPE]
			value = convertToType(type, settings[path][ATTRIB][DEFAULT])
			return value
		except:
			tracing.log.info('Could not get default for %s %s' % (path, settings[path][ATTRIB].items()))
			return -1

	## Dbus method SetDefault.
	# Sets the value of the setting to default. When the object-path is a group,
	# it sets the default for all the settings in that group.
	# @return completion-code When successful a 0 is return, and when not a -1 is returned.
	@dbus.service.method(InterfaceBusItem, out_signature = 'i')
	def SetDefault(self):
		global myDbusServices
		global settings
		
		try:
			path = self._object_path
			if path in groups:
				for service in myDbusServices:
					servicePath = service._object_path
					if path in servicePath:
						service.SetValue(settings[servicePath][ATTRIB][DEFAULT])
			else:
				self.SetValue(settings[path][ATTRIB][DEFAULT])
			return 0
		except:
			tracing.log.info('Could not set default for %s %s' % (path, settings[path][ATTRIB].items()))
			return -1

	## Dbus method AddSetting.
	# Add a new setting by the given parameters. The object-path must be a group.
	# Example 1: dbus /Settings AddSetting Groupname Settingname 100 i 0 100
	# Example 2: dbus /Settings AddSetting Groupname Settingname '/home/root' s 0 0 
	# When the new setting is of type string the minimum and maximum will be ignored.
	# @param group The group-name.
	# @param name The setting-name.
	# @param defaultValue The default value (and initial value) of the setting.
	# @param itemType Types 's' string, 'i' integer or 'f' float.
	# @param minimum The minimum value.
	# @param maximum The maximum value.
	# @return completion-code When successful a 0 is return, and when not a -1 is returned.
	@dbus.service.method(InterfaceSettings, in_signature = 'ssvsvv', out_signature = 'i')
	def AddSetting(self, group, name, defaultValue, itemType, minimum, maximum):
		global groups
		global settings
		global defaults
		global busName
		global myDbusGroupServices
		global myDbusServices

		okToSave = False
		if self._object_path in groups:
			groupPath = self._object_path + '/' + str(group)
			itemPath = groupPath + '/' + str(name)
			if not itemPath in settings:
				if itemType in supportedTypes:
					try:
						value = convertToType(itemType, defaultValue)
						if type(value) != str:
							min = convertToType(itemType, minimum)
							max = convertToType(itemType, maximum)
							if value >= min and value <= max:
								okToSave = True
								attributes = {TYPE:str(itemType), DEFAULT:str(value), MIN:str(min), MAX:str(max)}
						else:
							okToSave = True
							attributes = {TYPE:str(itemType), DEFAULT:str(value)}
					except:
						okToSave = False
		if okToSave == True:
			settings[itemPath] = [0, {}]
			settings[itemPath][VALUE] = value
			settings[itemPath][ATTRIB] = attributes
			if not groupPath in groups:
				groups.append(groupPath)
				myDbusObject = MyDbusObject(busName, groupPath)
				myDbusGroupServices.append(myDbusObject)
			myDbusObject = MyDbusObject(busName, itemPath)
			myDbusServices.append(myDbusObject)
			tracing.log.info('Add %s %s %s %s %s' % (itemPath, defaultValue, itemType, minimum, maximum))
			tracing.log.debug(settings.items())
			tracing.log.debug(groups)
			self._startTimeoutSaveSettings()
			return 0
		else:
			return -1

## The callback method for saving the settings-xml-file.
# Calls the parseDictonaryToXmlFile with the dictonary settings and settings-xml-filename.
def saveSettingsCallback():
	global timeoutSaveSettingsEventId
	global settings
	global fileSettings

	tracing.log.info('saveSettingsCallback')
	source_remove(timeoutSaveSettingsEventId)
	timeoutSaveSettingsEventId = None
	parseDictonaryToXmlFile(settings, fileSettings)

## Method for converting a value the the given type.
# When the type is not supported it simply returns the value as is.
# @param type The type to convert to.
# @param value The value to convert.
# @return value The converted value (if type is supported).
def convertToType(type, value):
	if type in supportedTypes:
		return supportedTypes[type](value)
	else:
		return value

## Method for parsing the file to the given dictonary.
# The dictonary will be in following format {dbus-object-path, [value, {attributes}]}.
# When a array is given for the groups, the found groups are appended.
# @param file The filename (path can be included, e.g. /home/root/localsettings/settings.xml).
# @param dictonaryItems The dictonary for the settings.
# @param arrayGroups The array for the groups.
# @param filter A filter used for filtering in settingchanges.xml for example "Add".
def parseXmlFileToDictonary(file, dictonaryItems, arrayGroups, filter):
	parser = etree.XMLParser(remove_blank_text=True)
	tree = etree.parse(file, parser)
	root = tree.getroot()
	tracing.log.debug('parseXmlFileToDictonary %s:' % file)
	tracing.log.debug(etree.tostring(root))
	parseXmlToDictonary(root, '/', dictonaryItems, arrayGroups, filter)

## Method for parsing a xml-element to a dbus-object-path.
# The dbus-object-path can be a setting (contains a text-value) or 
# a group. Only for a setting attributes are added.
# @param element The lxml-Element from the ElementTree API.
# @param path The path of the element.
# @param dictonaryItems The dictonary for the settings.
# @param arrayGroups The array for the groups.
# @param filter A filter used for filtering in settingchanges.xml for example "Add".
def parseXmlToDictonary(element, path, dictonaryItems, arrayGroups, filter):
	if path != '/':
		path += '/'
	path += element.tag
	for child in element:
		parseXmlToDictonary(child, path, dictonaryItems, arrayGroups, filter)

	if filter == None or path.startswith(filter) == True:
		if filter != None:
			objectPath = path.replace(filter, '')
			if objectPath == '':
				return
		else:
			objectPath = path
		if element.get('type') != None:
			elementType = element.attrib[TYPE]
			text = element.text
			if not element.text:
				text = ''
			value = convertToType(elementType, text)
			dictonaryItems[objectPath] = [value, element.attrib]
		elif arrayGroups != None:
			if not objectPath in arrayGroups:
				arrayGroups.append(objectPath)

## Method for parsing a dictonary to a giving xml-file.
# The dictonary must be in following format {dbus-object-path, [value, {attributes}]}.
# @param dictonary The dictonary with the settings.
# @param file The filename.
def parseDictonaryToXmlFile(dictonary, file):
	tracing.log.debug('parseDictonaryToXmlFile %s' % file)
	root = None
	for key in list(dictonary):
		items = key.split('/')
		items.remove('')
		if root == None:
			root = etree.Element(items[0])
			doc = etree.ElementTree(root)
		items.remove(root.tag)
		elem = root
		for item in items:
			foundElem = elem.find(item)
			if foundElem == None:
				elem = etree.SubElement(elem, item)
			else:
				elem = foundElem
		elem.text = str(dictonary[key][VALUE])
		attributes = dictonary[key][ATTRIB]
		for attribute, value in attributes.iteritems():
			elem.set(attribute, str(value))
	doc.write(file, pretty_print = True)

## Handles the system (Linux / Windows) signals such as SIGTERM.
#
# Stops the logscript with an exit-code.
# @param signum the signal-number.
# @param stack the call-stack.
def handlerSignals(signum, stack):
	tracing.log.info('handlerSignals received: %d' % signum)
	exitCode = 0
	if signum == signal.SIGHUP:
		exitCode = 1
	exit(exitCode)

## The main function.
def run():
	global bus
	global dbusName
	global myDbusServices
	global myDbusGroupServices
	global settings
	global pathSettings
	global fileSettings
	global fileSettingChanges
	global groups
	global busName
	global tracingEnabled
	global pathTraces
	global traceToConsole
	global traceToFile
	global traceFileName
	global traceDebugOn

	DBusGMainLoop(set_as_default=True)

	# get the exec path
	fileSettings = pathSettings + fileSettings
	fileSettingChanges = pathSettings + fileSettingChanges

	# setup debug traces.
	tracing.setupTraces(tracingEnabled, pathTraces, traceFileName, traceToConsole, traceToFile, traceDebugOn)
	tracing.log.debug('tracingPath = %s' % pathTraces)

	# Print the logscript version
	tracing.log.info('Localsettings version is: 0x%04x' % version)
	tracing.log.info('Localsettings PID is: %d' % getpid())
	
	# Trace the python version.
	pythonVersion = platform.python_version()
	tracing.log.debug('Current python version: %s' % pythonVersion)

	# setup signal handling.
	signal.signal(signal.SIGHUP, handlerSignals) # 1: Hangup detected
	signal.signal(signal.SIGINT, handlerSignals) # 2: Ctrl-C
	signal.signal(signal.SIGUSR1, handlerSignals) # 10: kill -USR1 <logscript-pid>
	signal.signal(signal.SIGTERM, handlerSignals) # 15: Terminate

	# read the settings.xml
	parseXmlFileToDictonary(fileSettings, settings, groups, None)
	tracing.log.debug('settings:')
	tracing.log.debug(settings.items())
	tracing.log.debug('groups:')
	tracing.log.debug(groups)

	# check if new settings must be changed
	if path.isfile(fileSettingChanges):
		# process the settings which must be deleted.
		delSettings = {}
		parseXmlFileToDictonary(fileSettingChanges, delSettings, None, "/Change/Delete")
		tracing.log.debug('setting to delete:')
		tracing.log.debug(delSettings.items())
		for item in delSettings:
			if item in settings:
				tracing.log.debug('delete item %s' % item)
				del settings[item]
				saveChanges = True

		# process the settings which must be added.
		addSettings = {}
		parseXmlFileToDictonary(fileSettingChanges, addSettings, None, "/Change/Add")
		tracing.log.debug('setting to add:')
		tracing.log.debug(addSettings.items())
		saveChanges = False
		for item in addSettings:
			if not item in settings:
				tracing.log.debug('add item %s' % item)
				settings[item] = addSettings[item]
				saveChanges = True

		if saveChanges == True:
			tracing.log.info('Change settings according to %s' % fileSettingChanges)
			parseDictonaryToXmlFile(settings, fileSettings)
			# update settings and groups from file.
			settings = {}
			groups = []
			parseXmlFileToDictonary(fileSettings, settings, groups, None)
			tracing.log.debug('settings:')
			tracing.log.debug(settings.items())
			tracing.log.debug('groups:')
			tracing.log.debug(groups)
			remove(fileSettingChanges)

	# get on the bus
	bus = dbus.SystemBus()
	tracing.log.debug('SystemBus')
	busName = dbus.service.BusName(dbusName, bus)
	for setting in settings:
		myDbusObject = MyDbusObject(busName, setting)
		myDbusServices.append(myDbusObject)
	for group in groups:
		myDbusObject = MyDbusObject(busName, group)
		myDbusGroupServices.append(myDbusObject)

	MainLoop().run()

def usage():
	print("Usage: ./localsettings [OPTION]")
	print("-h\tdisplay this help and exit")
	print("-v\tenable tracing to console (standard off)")
	print("-f\tenable tracing to file (standard off)")
	print("-d\tset tracing level to debug (standard info)")
	
def main(argv):
	global tracingEnabled
	global traceToConsole
	global traceToFile
	global traceDebugOn
	
	try:
		opts, args = getopt.getopt(argv, "hvfd")
	except getopt.GetoptError:
		usage()
		sys.exit(2)
	for opt, arg in opts:
		if opt == '-h':
			usage()
			sys.exit()
		elif opt == '-v':
			tracingEnabled = True
			traceToConsole = True
		elif opt == '-f':
			tracingEnabled = True
			traceToFile = True
		elif opt == '-d':
			traceDebugOn = True

	run()
	
main(sys.argv[1:])
