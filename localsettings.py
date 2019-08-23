#!/usr/bin/python -u

## @package localsettings
# Dbus-service for local settings.
#
# Below code needs a major check and cleanup. A not complete list would be:
# - get rid of the tracing, just use the standard logging modul, as also done in dbus_conversions for example
# - use argparse.ArgumentParser, so get rid of usage()

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
#
# These are set as an attribute of a (setting) element.
# Example 2: <Brigthness type="i" min="0" max="100" default="100">100</Brigthness>
# Example 3: <LogInterval type="i" min="5" default="900">900</LogInterval>
# Example 4: <LogPath type="s" default=".">.</LogPath>
# Settings or a group of settings can be set to default. A setting (and group) can be
# added by means of dbus. And of course a setting can be changed by means of dbus.

# Python imports
from dbus.mainloop.glib import DBusGMainLoop
import dbus
import dbus.service
from gobject import timeout_add, source_remove, MainLoop
from os import path, getpid, remove, rename, _exit, environ
import sys
import signal
from lxml import etree
import getopt
import errno
import platform
import os
import re
from collections import defaultdict
import migrate

# Victron imports
sys.path.insert(1, os.path.join(os.path.dirname(__file__), './ext/velib_python'))
import tracing

## Major version.
FIRMWARE_VERSION_MAJOR = 0x01
## Minor version.
FIRMWARE_VERSION_MINOR = 0x22
## Localsettings version.
version = (FIRMWARE_VERSION_MAJOR << 8) | FIRMWARE_VERSION_MINOR

## Dbus service name and interface name(s).
InterfaceBusItem = 'com.victronenergy.BusItem'
InterfaceSettings = 'com.victronenergy.Settings'

## Supported types for convert xml-text to value.
supportedTypes = {
	'i': int,
	's': str,
	'f': float,
}

## Settings file version tag, encoding and root-element.
settingsTag = 'version'
settingsVersion = '2'
settingsEncoding = 'UTF-8'
settingsRootName = 'Settings'

## The LocalSettings instance
localSettings = None

class SettingObject(dbus.service.Object):
	## Constructor of SettingObject
	#
	# Creates the dbus-object under the given bus-name (dbus-service-name).
	# @param busName Return value from dbus.service.BusName, see run()).
	# @param objectPath The dbus-object-path (e.g. '/Settings/Logging/LogInterval').
	def __init__(self, busName, objectPath):
		dbus.service.Object.__init__(self, busName, objectPath)
		self.group = None
		self.value = None
		self.min = None
		self.max = None
		self.default = None
		self.silent = False
		self.type = None

	def fromXml(self, element):
		elementType = element.attrib["type"]
		e = element.attrib

		self.value = convertToType(elementType, element.text if element.text else '')
		default = convertToType(elementType, e.get("default"))
		min = convertToType(elementType, e.get("min"))
		max = convertToType(elementType, e.get("max"))
		silent = toBool(e.get("silent"))
		self.setAttributes(default, elementType, min, max, silent)

	def storeAttribute(self, element, name):
		value = getattr(self, name)
		if value is None:
			return
		element.set(name, str(value))

	def toXml(self, element):
		self.storeAttribute(element, "type")
		self.storeAttribute(element, "min")
		self.storeAttribute(element, "max")
		self.storeAttribute(element, "default")
		self.storeAttribute(element, "silent")
		element.text = str(self.value)

	def id(self):
		return self._object_path.split("/")[-1]

	def setAttributes(self, default, type, min, max, silent):
		ret = self.default != default or self.type != type or self.min != min or \
				self.max != max or self.silent != silent

		self.default = default
		self.type = type
		self.min = min
		self.max = max
		self.silent = silent

		return ret

	## Dbus method GetValue
	# Returns the value of the dbus-object-path (the settings).
	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetValue(self):
		return self.value

	## Dbus method GetText
	# Returns the value as string of the dbus-object-path (the settings).
	@dbus.service.method(InterfaceBusItem, out_signature = 's')
	def GetText(self):
		return str(self.value)

	## Dbus method SetValue
	# Sets the value of a setting. When the type of the setting is a integer or float,
	# the new value is checked according to minimum and maximum.
	# @param value The new value for the setting.
	# @return completion-code When successful a 0 is return, and when not a -1 is returned.
	@dbus.service.method(InterfaceBusItem, in_signature = 'v', out_signature = 'i')
	def SetValue(self, value):
		v = convertToType(self.type, value)
		if v is None:
			return -1

		if self.min and v < self.min:
			return -1
		if self.max and v > self.max:
			return -1

		if v != self.value:
			self._setValue(v)

		return 0

	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetMin(self):
		if self.min is None:
			return 0
		return self.min

	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetMax(self):
		if self.max is None:
			return 0
		return self.max

	@dbus.service.method(InterfaceSettings, out_signature = 'b')
	def GetSilent(self):
		return self.silent

	## Sets the value and starts the time-out for saving to the settings-xml-file.
	# @param value The new value for the setting.
	def _setValue(self, value, printLog=True, sendAttributes=False):
		global localSettings

		if printLog and not self.silent:
			tracing.log.info('Setting %s changed. Old: %s, New: %s' % (self._object_path, self.value, value))

		self.value = value
		localSettings.startTimeoutSaveSettings()
		text = self.GetText()
		change = {'Value': value, 'Text': text}
		if sendAttributes:
			change.update({'Min': self.GetMin(), 'Max': self.GetMax(), 'Default': self.GetDefault()})
		self.PropertiesChanged(change)

	@dbus.service.signal(InterfaceBusItem, signature = 'a{sv}')
	def PropertiesChanged(self, changes):
		tracing.log.debug('signal PropertiesChanged')

	## Dbus method GetDefault.
	# Returns the default value of a setting.
	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetDefault(self):
		if self.default is None:
			return -1
		return self.default

	@dbus.service.method(InterfaceBusItem, out_signature = 'i')
	def SetDefault(self):
		if self.default is None:
			return -1
		self.SetValue(self.default())
		return 0

	@dbus.service.method(InterfaceSettings, out_signature = 'vvvi')
	def GetAttributes(self):
		return (self.GetDefault(), self.GetMin(), self.GetMax(), self.GetSilent())

class GroupObject(dbus.service.Object):
	def __init__(self, busname, path, parent):
		dbus.service.Object.__init__(self, busname, path)
		self._parent = parent
		self._children = {}
		self._settings = {}
		self._busName = busname

	def toXml(self, element):
		for childId in self._children:
			subElement = etree.SubElement(element, tagForXml(childId))
			self._children[childId].toXml(subElement)

		for settingId in self._settings:
			subElement = etree.SubElement(element, tagForXml(settingId))
			self._settings[settingId].toXml(subElement)

	def _path(self):
		return "" if self._object_path == "/" else self._object_path

	def _split_path(self, path):
		list = path.split("/")
		if not list:
			return list
		# skip the leading /
		if list[0] == '':
			del list[0]
		return list

	def createGroups(self, path):
		list = self._split_path(path)
		if not list:
			return None
		return self.createGroupsFromList(list)

	# just to make it easy to overload
	def _newSubGroup(self, path):
		return GroupObject(self._busName, path, self)

	def _newSettingObject(self, tag):
		return SettingObject(self._busName, self._object_path + "/" + tag)

	def createGroupsFromList(self, list):
		if not list:
			return self
		subgroup = list.pop(0)
		if subgroup not in self._children:
			path = self._path() + "/" + subgroup
			self._children[subgroup] = self._newSubGroup(path)
		if len(list):
			return self._children[subgroup].createGroupsFromList(list)
		else:
			return self._children[subgroup]

	def getGroup(self, path):
		list = self._split_path(path)
		if not list:
			return None
		return self.getGroupFromList(list)

	def getGroupFromList(self, list):
		if not list:
			return self
		subgroup = list.pop(0)
		if subgroup not in self._children:
			return None
		return self._children[subgroup].getGroupFromList(list)

	def addSettingObject(self, setting):
		id = setting.id()
		if id in self._children:
			return False
		self._settings[id] = setting
		setting.group = self
		return True

	def addGroup(self, id, group):
		if self._settings:
			return False
		self._children[id] = group

	def createGroupsForObjectPath(self, path):
		list = self._split_path(path)
		if not list:
			return None
		del list[-1]
		return self.createGroupsFromList(list)

	def createSettingObjectAndGroups(self, path):
		group = self.createGroupsForObjectPath(path)
		if not group:
			return None
		setting = group._newSettingObject(path.split("/")[-1])
		if not group.addSettingObject(setting):
			return None
		return setting

	def getSettingObject(self, path):
		list = self._split_path(path)
		if not list:
			return None
		name = list[-1]
		del(list[-1])
		group = self.getGroupFromList(list)
		if not group:
			return None
		return group._settings.get(name)

	def addSettingObjectsToList(self, list):
		list.extend(self._settings.values())
		for child in self._children.values():
			child.addSettingObjectsToList(list)

	def getSettingObjects(self):
		list = []
		self.addSettingObjectsToList(list)
		return list

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
		return self._addSetting(group, name, defaultValue, itemType, minimum, maximum, silent=False)[0]

	@dbus.service.method(InterfaceSettings, in_signature = 'ssvsvv', out_signature = 'i')
	def AddSilentSetting(self, group, name, defaultValue, itemType, minimum, maximum):
		return self._addSetting(group, name, defaultValue, itemType, minimum, maximum, silent=True)[0]

	def _addSetting(self, group, name, defaultValue, itemType, minimum, maximum, silent):
		tracing.log.debug('AddSetting %s %s %s' % (self._object_path, group, name))

		if group.startswith('/') or group == '':
			groupPath = str(group)
		else:
			groupPath = '/' + str(group)

		if name.startswith('/'):
			relativePath = groupPath + str(name)
		else:
			relativePath = groupPath + '/' + str(name)

		return self.addSetting(relativePath, defaultValue, itemType, minimum, maximum, silent)

	def addSetting(self, relativePath, defaultValue, itemType, minimum, maximum, silent):
		# A prefixing underscore is an escape char: don't allow it in a normal path
		if "/_" in relativePath:
			return -2, None

		if itemType not in supportedTypes:
			return -3, None

		try:
			value = convertToType(itemType, defaultValue)
			if value is None:
				return -6, None
			defaultValue = value
			min = convertToType(itemType, minimum)
			max = convertToType(itemType, maximum)

			if type(value) != str:
				if min == 0 and max == 0:
					min = None
					max = None
				elif value < min or value > max:
					return -7, None
		except:
			return -4, None

		settingObject = self.getSettingObject(relativePath)
		if not settingObject:
			# New setting
			if self.getGroup(relativePath):
				return -8, None
			settingObject = self.createSettingObjectAndGroups(relativePath)
			settingObject.setAttributes(defaultValue, itemType, min, max, silent)
		else:
			# Existing setting
			if settingObject.type != itemType:
				return -5, None

			changed = settingObject.setAttributes(defaultValue, itemType, min, max, silent)
			if not changed:
				return 0, settingObject

			# There are changes, save them while keeping the current value.
			value = settingObject.value

		tracing.log.info('Added new setting %s. default:%s, type:%s, min:%s, max: %s, silent: %s' % \
						 (self._path() + relativePath, defaultValue, itemType, minimum, maximum, silent))
		settingObject._setValue(value, printLog=False, sendAttributes=True)

		return 0, settingObject

	def forAllSettings(self, function):
		prefixLength = len(self._path() + '/')
		ret = dbus.Dictionary(signature = dbus.Signature('sv'), variant_level=1)
		for setting in self.getSettingObjects():
			relPath = setting._object_path[prefixLength:]
			value = function(setting)
			if value is not None:
				ret[relPath] = value
		return ret

	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetValue(self):
		return self.forAllSettings(lambda x: x.GetValue())

	@dbus.service.method(InterfaceBusItem, out_signature = 'a{ss}')
	def GetText(self):
		return self.forAllSettings(lambda x: x.GetText())

	@dbus.service.method(InterfaceBusItem, out_signature = 'i')
	def SetDefault(self):
		self.forAllSettings(lambda x: x.SetDefault())
		return 0

def convertToType(type, value):
	try:
		return supportedTypes[type](value)
	except:
		return None

def parseXmlFile(file, items):
	parser = etree.XMLParser(remove_blank_text=True)
	tree = etree.parse(file, parser)
	root = tree.getroot()
	tracing.log.debug("settings version %s" % root.attrib)

	parseXmlEntry(root, items)

def tagForXml(path):
	if len(path) == 0:
		return ""
	if path[0].isdigit():
		path = "_" + path
	return path

def tagFromXml(element):
	# Remove possible underscore prefix
	tag = element.tag
	if tag[0] == '_':
		tag = tag[1:]
	return tag

def parseXmlEntry(element, group):
	tag = tagFromXml(element)

	if element.get('type') != None:
		setting = group._newSettingObject(tag)
		setting.fromXml(element)
		group.addSettingObject(setting)
	else:
		subgroup = group.createGroups(tag)
		if subgroup:
			for child in element:
				parseXmlEntry(child, subgroup)

def writeToXmlFile(localSettings, settingsGroup):
	tracing.log.debug('parseDictionaryToXmlFile %s' % file)

	root = etree.Element("Settings")
	root.set(settingsTag, settingsVersion)
	tree = etree.ElementTree(root)
	settingsGroup.toXml(root)
	localSettings.save(tree)

def toBool(val):
	if type(val) != str:
		return bool(val)

	try:
		return bool(int(val))
	except:
		pass

	return val.lower() == 'true'

## Load settings from text file
def loadSettingsFile(name, settingsGroup):
	with open(name, 'r') as f:
		for line in f:
			v = re.sub('#.*', '', line).strip().split()
			if not v:
				continue

			try:
				path = v[0]
				defVal = v[1]
				itemType = v[2]
			except:
				raise Exception('syntax error: ' + line)

			minVal = v[3] if len(v) > 3 else None
			maxVal = v[4] if len(v) > 4 else None
			silent = v[5] if len(v) > 5 else False

			if itemType not in supportedTypes:
				raise Exception('invalid type')

			defVal = convertToType(itemType, defVal)

			if type(defVal) != str:
				minVal = convertToType(itemType, minVal)
				maxVal = convertToType(itemType, maxVal)

				if minVal or maxVal:
					if defVal < minVal or defVal > maxVal:
						raise Exception('default value out of range')

			silent = toBool(silent)
			path = path.lstrip('/')

			settingsGroup.addSetting(path, defVal, itemType, minVal, maxVal, silent)

## Load settings from each file in dir
def loadSettingsDir(path, dictionary):
	try:
		names = os.listdir(path)
	except:
		return

	for name in names:
		filename = os.path.join(path, name)
		try:
			loadSettingsFile(filename, dictionary)
		except Exception as ex:
			tracing.log.error('error loading %s: %s' %
					  (filename, str(ex)))

## The main function.
class LocalSettings:
	dbusName = 'com.victronenergy.settings'
	fileSettings = 'settings.xml'
	newFileExtension = '.new'
	sysSettingsDir = '/etc/venus/settings.d'

	def __init__(self, pathSettings, timeoutSaveSettingsTime):
		# set the settings path
		self.fileSettings = pathSettings + self.fileSettings
		self.newFileSettings = self.fileSettings + self.newFileExtension
		self.timeoutSaveSettingsTime = timeoutSaveSettingsTime
		self.timeoutSaveSettingsEventId = None
		self.rootGroup = None
		self.settingsGroup = None

		# Print the logscript version
		tracing.log.info('Localsettings version is: 0x%04x' % version)
		tracing.log.info('Localsettings PID is: %d' % getpid())

		# Trace the python version.
		pythonVersion = platform.python_version()
		tracing.log.debug('Current python version: %s' % pythonVersion)

		if not path.isdir(pathSettings):
			print('Error path %s does not exist!' % pathSettings)
			sys.exit(errno.ENOENT)

		if path.isfile(self.newFileSettings):
			tracing.log.info('New settings file exist')
			try:
				tree = etree.parse(self.newFileSettings)
				root = tree.getroot()
				tracing.log.info('New settings file %s validated' % self.newFileSettings)
				rename(self.newFileSettings, self.fileSettings)
				tracing.log.info('renamed new settings file to settings file')
			except:
				tracing.log.error('New settings file %s invalid' % self.newFileSettings)
				remove(self.newFileSettings)
				tracing.log.error('%s removed' % self.newFileSettings)

		if path.isfile(self.fileSettings):
			# Try to validate the settings file.
			try:
				tree = etree.parse(self.fileSettings)
				root = tree.getroot()
				# NOTE: there used to be a 1.0 version once upon a time an no version at all
				# in really old version. Since it is easier to compare integers only use the
				# major part.
				loadedVersionTxt = tree.xpath("string(/Settings/@version)") or "1"
				loadedVersion = [int(i) for i in loadedVersionTxt.split('.')][0]

				migrate.migrate(self, tree, loadedVersion)

				tracing.log.info('Settings file %s validated' % self.fileSettings)

				if loadedVersionTxt != settingsVersion:
					print("Updating version to " + settingsVersion)
					root.set(settingsTag, settingsVersion)
					self.save(tree)

			except:
				tracing.log.error('Settings file %s invalid' % self.fileSettings)
				remove(self.fileSettings)
				tracing.log.error('%s removed' % self.fileSettings)

		# check if settings file is present, if not exit create a "empty" settings file.
		if not path.isfile(self.fileSettings):
			tracing.log.warning('Settings file %s not found' % self.fileSettings)
			root = etree.Element(settingsRootName)
			root.set(settingsTag, settingsVersion)
			tree = etree.ElementTree(root)
			self.save(tree)
			tracing.log.warning('Created settings file %s' % self.fileSettings)

		# connect to the SessionBus if there is one. System otherwise
		bus = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in environ else dbus.SystemBus()
		busName = dbus.service.BusName(self.dbusName, bus)

		self.rootGroup = GroupObject(busName, "/", None)
		self.settingsGroup = self.rootGroup.createGroups("/Settings")
		parseXmlFile(self.fileSettings, self.rootGroup)

	def save(self, tree):
		with open(self.newFileSettings, 'wb') as fp:
			tree.write(fp, encoding = settingsEncoding, pretty_print = True, xml_declaration = True)
			fp.flush()
			os.fsync(fp.fileno())
			rename(self.newFileSettings, self.fileSettings)

	## The callback method for saving the settings-xml-file.
	# Calls the parseDictionaryToXmlFile with the dictionary settings and settings-xml-filename.
	def saveSettingsCallback(self):
		tracing.log.debug('Saving settings to file')
		source_remove(self.timeoutSaveSettingsEventId)
		self.timeoutSaveSettingsEventId = None
		writeToXmlFile(self, self.settingsGroup)

	## Method for starting the time-out for saving to the settings-xml-file.
	# (Re)Starts the time-out. When after x time no settings are changed,
	# the settings-xml-file is saved.
	def startTimeoutSaveSettings(self):
		if self.timeoutSaveSettingsEventId is not None:
			source_remove(self.timeoutSaveSettingsEventId)
			self.timeoutSaveSettingsEventId = None
		self.timeoutSaveSettingsEventId = timeout_add(self.timeoutSaveSettingsTime * 1000,
														self.saveSettingsCallback)

def usage():
	print("Usage: ./localsettings [OPTION]")
	print("-h, --help\tdisplay this help and exit")
	print("-t\t\tenable tracing to file (standard off)")
	print("-d\t\tset tracing level to debug (standard info)")
	print("-v, --version\treturns the program version")
	print("--banner\tshows program-name and version at startup")
	print("--path=dir\tuse given dir as data directory instead of /data")
	print("")
	print("NOTE FOR DEBUGGING ON DESKTOP")
	print("This code expects a path /data/conf or --path to be set, and")
	print("permissions in that path to write/read.")

def main(argv):
	global localSettings

	pathSettings = 'conf/'
	timeoutSaveSettingsTime = 2

	## Traces (info / debug) setup
	pathTraces = '/log/'
	traceFileName = 'localsettingstraces'
	traceToConsole = True
	tracingEnabled = True
	traceToFile = False
	traceDebugOn = False

	try:
		opts, args = getopt.getopt(argv, "vhctd", ["help", "version", "banner", "path=", "no-delay"])
	except getopt.GetoptError:
		usage()
		sys.exit(errno.EINVAL)
	for opt, arg in opts:
		if opt == '-h' or opt == '--help':
			usage()
			sys.exit()
		elif opt == '-t':
			tracingEnabled = True
			traceToFile = True
		elif opt == '-d':
			traceDebugOn = True
		elif opt == '-v' or opt == '--version':
			print(version)
			sys.exit()
		elif opt == '--path':
			pathSettings = arg
			if pathSettings[-1] != '/':
				pathSettings += "/"
		elif opt == '--no-delay':
			print("no delay")
			timeoutSaveSettingsTime = 0

	# setup debug traces.
	tracing.setupTraces(tracingEnabled, pathTraces, traceFileName, traceToConsole, traceToFile, traceDebugOn)
	tracing.log.debug('tracingPath = %s' % pathTraces)

	print("localsettings v%01x.%02x starting up " % (FIRMWARE_VERSION_MAJOR, FIRMWARE_VERSION_MINOR))

	DBusGMainLoop(set_as_default=True)

	localSettings = LocalSettings(pathSettings, timeoutSaveSettingsTime)

	# load system default settings, note need localSettings to be ready
	loadSettingsDir(localSettings.sysSettingsDir, localSettings.settingsGroup)

	MainLoop().run()

main(sys.argv[1:])
