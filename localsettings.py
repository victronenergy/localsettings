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

## Dbus service name
dbusName = 'com.victronenergy.settings'
InterfaceBusItem = 'com.victronenergy.BusItem'
InterfaceDefault = 'com.victronenergy.Default'

## The setttings
settings = {}
defaults = {}

## The list of MyDbusService(s)
myDbusServices = []

## File related stuff
timeoutSaveSettingsStarted = False
timeoutSaveSettingsEventId = 0
timeoutSaveSettingsTime = 5
execPath = ''
fileSettings = ''

class MyDbusObject(dbus.service.Object):
	global InterfaceBusItem

	def __init__(self, busName, objectPath):
		dbus.service.Object.__init__(self, busName, objectPath)

	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetValue(self):
		return settings[self._object_path]

	@dbus.service.method(InterfaceBusItem, out_signature = 's')
	def GetText(self):
		return str(settings[self._object_path])

	@dbus.service.method(InterfaceBusItem, in_signature = 'v', out_signature = 'i')
	def SetValue(self, value):
		self._setValue(value)
		return 0

	@dbus.service.signal(InterfaceBusItem, signature = 'v')
	def _setValue(self, value):
		global timeoutSaveSettingsStarted
		global timeoutSaveSettingsEventId
		global timeoutSaveSettingsTime
		global settings

		tracing.log.info('_setValue %s %s' % (self._object_path, value))
		settings[self._object_path] = value
		if not timeoutSaveSettingsStarted:
			timeoutSaveSettingsEventId = timeout_add(timeoutSaveSettingsTime*1000, saveSettings)
			timeoutSaveSettingsStarted = True


	@dbus.service.method(InterfaceDefault, out_signature = 'v')
	def GetDefault(self):
		global defaults
		return defaults[self._object_path]

	@dbus.service.method(InterfaceDefault, out_signature = 'i')
	def SetDefault(self):
		global defaults
		global settings
		self._setValue(defaults[self._object_path])
		return 0

def saveSettings():
	global timeoutSaveSettingsStarted
	global timeoutSaveSettingsEventId
	global settings
	global fileSettings

	tracing.log.info('saveSettings')
	source_remove(timeoutSaveSettingsEventId)
	timeoutSaveSettingsStarted = False
	parseDictonaryToXmlFile(settings, fileSettings)

def parseXmlFileToDictonary(file, dictonary):
	parser = etree.XMLParser(remove_blank_text=True)
	tree = etree.parse(file, parser)
	root = tree.getroot()
	tracing.log.info(etree.tostring(root))
	parseXmlToDictonary(root, '/', dictonary)

def parseXmlToDictonary(element, path, dictonary):
	path += element.tag
	if len(element):
		path += '/'
	for child in element:
		parseXmlToDictonary(child, path, dictonary)

	if element.text:
		path.strip('/')
		dictonary[path] = element.text

def parseDictonaryToXmlFile(dictonary, file):
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
			foundElem = root.find(item)
			if foundElem == None:
				elem = etree.SubElement(elem, item)
			else:
				elem = foundElem
		elem.text = dictonary[key]
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
	global settings
	global execPath
	global fileSettings

	DBusGMainLoop(set_as_default=True)

	# get the exec path
	execPath = path.dirname(sys.argv[0]) + '/'
	fileSettings = execPath + 'settings.xml'
	fileDefaults = execPath + 'defaults.xml'

	# setup debug traces.
	tracing.setupDebugTraces(execPath)
	tracing.log.info('tracingPath = %s' % execPath)

	# Print the logscript version
	tracing.log.info('Localsettings version is: 0x%04x' % version)
	tracing.log.info('Localsettings PID is: %d' % getpid())
	
	# Trace the python version.
	pythonVersion = platform.python_version()
	tracing.log.info('Current python version: %s' % pythonVersion)

	# setup signal handling.
	signal.signal(signal.SIGHUP, handlerSignals) # 1: Hangup detected
	signal.signal(signal.SIGINT, handlerSignals) # 2: Ctrl-C
	signal.signal(signal.SIGUSR1, handlerSignals) # 10: kill -USR1 <logscript-pid>
	signal.signal(signal.SIGTERM, handlerSignals) # 15: Terminate

	# read the settings.xml and defaults.xml
	parseXmlFileToDictonary(fileSettings, settings)
	tracing.log.info(settings.items())
	parseXmlFileToDictonary(fileDefaults, defaults)
	tracing.log.info(defaults.items())

	# get on the bus
	if isHostPC():
		bus = dbus.SessionBus()
		tracing.log.info('SessionBus')
	else:
		bus = dbus.SystemBus()
		tracing.log.info('SystemBus')
	busName = dbus.service.BusName(dbusName, bus)
	for setting in settings:
		myDbusObject = MyDbusObject(busName, setting)
		myDbusServices.append(myDbusObject)

	MainLoop().run()

run()
