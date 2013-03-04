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
groups = []

## Index values for settings
VALUE = 0
ATTRIB = 1

## ATTRIB keywords.
TYPE='type'
MIN='min'
MAX='max'
DEFAULT='default'

## Dictonary for xml text to type x conversion.
supportedTypes = {
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
fileSettings = 'settings.xml'
fileAddSettings = 'addsettings.xml'

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

	@dbus.service.signal(InterfaceBusItem, signature = 'v')
	def _setValue(self, value):
		global settings

		tracing.log.info('_setValue %s %s' % (self._object_path, value))
		settings[self._object_path][VALUE] = value
		self._startTimeoutSaveSettings()

	def _startTimeoutSaveSettings(self):
		global timeoutSaveSettingsEventId
		global timeoutSaveSettingsTime

		if timeoutSaveSettingsEventId:
			source_remove(timeoutSaveSettingsEventId)
			timeoutSaveSettingsEventId = None
		timeoutSaveSettingsEventId = timeout_add(timeoutSaveSettingsTime*1000, saveSettings)

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

def saveSettings():
	global timeoutSaveSettingsEventId
	global settings
	global fileSettings

	tracing.log.info('saveSettings')
	source_remove(timeoutSaveSettingsEventId)
	timeoutSaveSettingsEventId = None
	parseDictonaryToXmlFile(settings, fileSettings)

def convertToType(type, value):
	if type in supportedTypes:
		return supportedTypes[type](value)
	else:
		return value

def parseXmlFileToDictonary(file, dictonaryItems, arrayGroups):
	parser = etree.XMLParser(remove_blank_text=True)
	tree = etree.parse(file, parser)
	root = tree.getroot()
	tracing.log.debug('parseXmlFileToDictonary %s:' % file)
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
	global fileAddSettings
	global groups
	global busName

	DBusGMainLoop(set_as_default=True)

	# get the exec path
	execPath = path.dirname(sys.argv[0]) + '/'
	fileSettings = execPath + fileSettings
	fileAddSettings = execPath + fileAddSettings

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

	# read the settings.xml
	parseXmlFileToDictonary(fileSettings, settings, groups)
	tracing.log.debug('settings:')
	tracing.log.debug(settings.items())
	tracing.log.debug('groups:')
	tracing.log.debug(groups)

	# check if new settings must be added
	if path.isfile(fileAddSettings):
		addSettings = {}
		parseXmlFileToDictonary(fileAddSettings, addSettings, None)
		tracing.log.debug('addsettings:')
		tracing.log.debug(addSettings.items())
		saveChanges = False
		for item in addSettings:
			if not item in settings:
				settings[item] = addSettings[item]
				saveChanges = True
		if saveChanges == True:
			tracing.log.info('Added new settings')
			parseDictonaryToXmlFile(settings, fileSettings)
			tracing.log.debug('settings:')
			tracing.log.debug(settings.items())
			tracing.log.debug('groups:')
			tracing.log.debug(groups)

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
