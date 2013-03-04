#!/usr/bin/env python

## @package localsettings
# Dbus-service for local settings.
#
# The local-settings-dbus-service provides the local-settings storage in non-volatile-memory.

# Python imports
from dbus.mainloop.glib import DBusGMainLoop
import dbus
import dbus.service
from gobject import timeout_add, source_remove, MainLoop
from os import system, path, getpid
import sys
import signal
from lxml import etree

# Local imports
from host import isHostPC
import tracing
import platform

## Major version.
FIRMWARE_VERSION_MAJOR = 0x00
## Minor version.
FIRMWARE_VERSION_MINOR = 0x01
## Logscript version.
version = (FIRMWARE_VERSION_MAJOR << 8) | FIRMWARE_VERSION_MINOR

## Setting: the log file path
logPath = ''

## The dbus object
bus = None
busName = None

## Dbus service name
dbusName = 'com.victronenergy.settings'
InterfaceBusItem = 'com.victronenergy.BusItem'
InterfaceSettings = 'com.victronenergy.Settings'

## The dictonary's
settings = {}
defaults = {}
groups = []

## Index values for settings and defaults
VALUE = 0
ATTRIB = 1

## ATTRIB keywords.
TYPE='type'
MIN='min'
MAX='max'

## Dictonary for xml text to type x conversion.
types = {
		'i':int,
		's':str,
		'f':float,
		}

## The list of MyDbusService(s)
myDbusServices = []
myDbusGroupServices = []

## File related stuff
timeoutSaveSettingsEventId = None
timeoutSaveSettingsTime = 5
execPath = ''
fileSettings = ''
fileDefaults = ''

class MyDbusObject(dbus.service.Object):
	global InterfaceBusItem

	def __init__(self, busName, objectPath):
		dbus.service.Object.__init__(self, busName, objectPath)

	@dbus.service.method(InterfaceBusItem, in_signature = 'si', out_signature = 's')
	def GetDescription(self, language, length):
		return 'no description available'
	
	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetValue(self):
		global settings
		global groups
		if self._object_path in groups:
			return -1
		return settings[self._object_path][VALUE]
	
	@dbus.service.method(InterfaceBusItem, out_signature = 's')
	def GetText(self):
		global settings
		if self._object_path in groups:
			return ''
		return str(settings[self._object_path][VALUE])

	@dbus.service.method(InterfaceBusItem, in_signature = 'v', out_signature = 'i')
	def SetValue(self, value):
		global settings
		global types
		
		if self._object_path in groups:
			return -1
		okToSave = True
		v = value
		path = self._object_path
		if TYPE in settings[path][ATTRIB]:
			type = settings[path][ATTRIB][TYPE]
			if type in types:
				v = convertToType(type, value)
				if MIN in settings[path][ATTRIB]:
					if v < convertToType(type, settings[path][ATTRIB][MIN]):
						okToSave = False
				if MAX in settings[path][ATTRIB]:
					if v > convertToType(type, settings[path][ATTRIB][MAX]):
						okToSave = False
		if okToSave == True:
			if v != settings[path][VALUE]:
				self._setValue(v)
			return 0
		else:
			return -1

	@dbus.service.signal(InterfaceBusItem, signature = 'v')
	def _setValue(self, value):
		global settings

		tracing.log.info('_setValue %s %s' % (self._object_path, value))
		settings[self._object_path][VALUE] = value
		self._startTimeoutSaveSettings(True, False)

	def _startTimeoutSaveSettings(self, writeSettings, writeDefaults):
		global timeoutSaveSettingsEventId
		global timeoutSaveSettingsTime

		if timeoutSaveSettingsEventId:
			source_remove(timeoutSaveSettingsEventId)
			timeoutSaveSettingsEventId = None
		timeoutSaveSettingsEventId = timeout_add(timeoutSaveSettingsTime*1000, saveSettings, writeSettings, writeDefaults)

	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetDefault(self):
		global defaults
		if self._object_path in groups:
			return -1
		return defaults[self._object_path][VALUE]

	@dbus.service.method(InterfaceBusItem, out_signature = 'i')
	def SetDefault(self):
		global myDbusServices
		global defaults
		if self._object_path in groups:
			for service in myDbusServices:
				servicePath = service._object_path
				if self._object_path in servicePath:
					service._setValue(defaults[servicePath][VALUE])
		else:
			self._setValue(defaults[self._object_path][VALUE])
		return 0

	@dbus.service.method(InterfaceSettings, in_signature = 'ssv', out_signature = 'i')
	def AddSetting(self, group, name, defaultValue):
		global groups
		global settings
		global defaults
		global busName
		global myDbusGroupServices
		global myDbusServices

		if self._object_path in groups:
			pathGroup = self._object_path + '/' + str(group)
			pathItem = pathGroup + '/' + str(name)
			tracing.log.info('Add %s %s' % (pathItem, defaultValue))
			if not pathGroup in groups:
				groups.append(pathGroup)
				myDbusObject = MyDbusObject(busName, pathGroup)
				myDbusGroupServices.append(myDbusObject)
			if not pathItem in settings:
				settings[pathItem][VALUE] = str(defaultValue)
				defaults[pathItem][VALUE] = str(defaultValue)
				tracing.log.debug(settings.items())
				tracing.log.debug(defaults.items())
				tracing.log.debug(groups)
				self._startTimeoutSaveSettings(True, True)
				myDbusObject = MyDbusObject(busName, pathItem)
				myDbusServices.append(myDbusObject)
				return 0
			else:
				return -1
		else:
			return -1

def saveSettings(writeSettings, writeDefaults):
	global timeoutSaveSettingsEventId
	global settings
	global fileSettings
	global fileDefaults

	tracing.log.info('saveSettings %d %d' % (writeSettings, writeDefaults))
	source_remove(timeoutSaveSettingsEventId)
	timeoutSaveSettingsEventId = None
	if writeSettings:
		parseDictonaryToXmlFile(settings, fileSettings)
	if writeDefaults:
		parseDictonaryToXmlFile(defaults, fileDefaults)

def convertToType(type, value):
	if type in types:
		return types[type](value)
	else:
		return value

def parseXmlFileToDictonary(file, dictonaryItems, arrayGroups):
	parser = etree.XMLParser(remove_blank_text=True)
	tree = etree.parse(file, parser)
	root = tree.getroot()
	tracing.log.debug('XML %s:' % file)
	tracing.log.debug(etree.tostring(root))
	parseXmlToDictonary(root, '/', dictonaryItems, arrayGroups)

def parseXmlToDictonary(element, path, dictonaryItems, arrayGroups):
	if path != '/':
		path += '/'
	path += element.tag
	for child in element:
		parseXmlToDictonary(child, path, dictonaryItems, arrayGroups)

	if element.text:
		elementType = element.attrib[TYPE]
		value = convertToType(elementType, element.text)
		dictonaryItems[path] = [value, element.attrib]
	elif arrayGroups != None:
		if not path in arrayGroups:
			arrayGroups.append(path)

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
	global execPath
	global fileSettings
	global fileDefaults
	global groups
	global busName

	DBusGMainLoop(set_as_default=True)

	# get the exec path
	execPath = path.dirname(sys.argv[0]) + '/'
	fileSettings = execPath + 'settings.xml'
	fileDefaults = execPath + 'defaults.xml'

	# setup debug traces.
	tracing.setupDebugTraces(execPath)
	tracing.log.debug('tracingPath = %s' % execPath)

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

	# read the settings.xml and defaults.xml
	parseXmlFileToDictonary(fileSettings, settings, groups)
	tracing.log.debug('settings:')
	tracing.log.debug(settings.items())
	tracing.log.debug('groups:')
	tracing.log.debug(groups)
	parseXmlFileToDictonary(fileDefaults, defaults, None)
	tracing.log.debug('defaults:')
	tracing.log.debug(defaults.items())

	# check if a default is added.
	saveChanges = False
	for key in defaults:
		if not key in settings:
			settings[key] = defaults[key]
			saveChanges = True
		if  settings[key][ATTRIB] != defaults[key][ATTRIB]:
			settings[key][ATTRIB] = defaults[key][ATTRIB]
			saveChanges = True
	if saveChanges == True:
		tracing.log.info('Added new default items or attributes to settings')
		parseDictonaryToXmlFile(settings, fileSettings)

	# get on the bus
	if isHostPC():
		bus = dbus.SessionBus()
		tracing.log.debug('SessionBus')
	else:
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

run()
