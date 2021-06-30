#!/usr/bin/python3 -u

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
from os import path, remove, rename, environ
import sys
import signal
from lxml import etree
import errno
import os
import re
from collections import defaultdict
import migrate
import logging
from enum import IntEnum, unique
import argparse

from gi.repository import GLib

## Major version.
FIRMWARE_VERSION_MAJOR = 0x01
## Minor version.
FIRMWARE_VERSION_MINOR = 0x46
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

DBUS_OK = dbus.types.Int32(0)
DBUS_ERR = dbus.types.Int32(-1)

## Settings file version tag, encoding and root-element.
settingsTag = 'version'
settingsVersion = '9'
settingsEncoding = 'UTF-8'
settingsRootName = 'Settings'

## The LocalSettings instance
localSettings = None

@unique
class AddSettingError(IntEnum):
	NoError = dbus.types.Int32(0)
	UnderscorePrefix = dbus.types.Int32(-2)
	UnknownType = dbus.types.Int32(-3)
	InvalidPath = dbus.types.Int32(-4)
	TypeDiffer = dbus.types.Int32(-5)
	InvalidDefault = dbus.types.Int32(-6)
	DefaultOutOfRange = dbus.types.Int32(-7)
	IsGroup = dbus.types.Int32(-8)
	NotInSettings = dbus.types.Int32(-9)

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

	def remove(self):
		change = {'Value': dbus.Array([], signature=dbus.Signature('i'), variant_level=1), 'Text': ''}
		self.PropertiesChanged(change)
		self.remove_from_connection()
		if self.group:
			self.group._settings.pop(self.id())
		self.group.cleanup()

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
		return dbus_wrap(self.type, self.value)

	## Dbus method GetText
	# Returns the value as string of the dbus-object-path (the settings).
	@dbus.service.method(InterfaceBusItem, out_signature = 's')
	def GetText(self):
		return dbus.types.String(self.value)

	## Dbus method SetValue
	# Sets the value of a setting. When the type of the setting is a integer or float,
	# the new value is checked according to minimum and maximum.
	# @param value The new value for the setting.
	# @return completion-code When successful a 0 is return, and when not a -1 is returned.
	@dbus.service.method(InterfaceBusItem, in_signature = 'v', out_signature = 'i')
	def SetValue(self, value):
		v = convertToType(self.type, value)
		if v is None:
			return DBUS_ERR

		if self.min and v < self.min:
			return DBUS_ERR
		if self.max and v > self.max:
			return DBUS_ERR

		if v != self.value:
			if not self._setValue(v):
				return DBUS_ERR

		return DBUS_OK

	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetMin(self):
		if self.min is None:
			return dbus.types.Int32(0)
		return dbus_wrap(self.type, self.min)

	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetMax(self):
		if self.max is None:
			return dbus.types.Int32(0)
		return dbus_wrap(self.type, self.max)

	@dbus.service.method(InterfaceSettings, out_signature = 'b')
	def GetSilent(self):
		return dbus.types.Int32(self.silent)

	## Sets the value and starts the time-out for saving to the settings-xml-file.
	# @param value The new value for the setting.
	def _setValue(self, value, printLog=True, sendAttributes=False):
		global localSettings

		if printLog and not self.silent:
			logging.info('Setting %s changed. Old: %s, New: %s' % (self._object_path, self.value, value))

		self.value = value
		localSettings.startTimeoutSaveSettings()
		text = self.GetText()
		change = {'Value': value, 'Text': text}
		if sendAttributes:
			change.update({'Min': self.GetMin(), 'Max': self.GetMax(), 'Default': self.GetDefault()})
		self.PropertiesChanged(change)

		return True

	@dbus.service.signal(InterfaceBusItem, signature = 'a{sv}')
	def PropertiesChanged(self, changes):
		logging.debug('signal PropertiesChanged')

	## Dbus method GetDefault.
	# Returns the default value of a setting.
	@dbus.service.method(InterfaceBusItem, out_signature = 'v')
	def GetDefault(self):
		if self.default is None:
			return DBUS_ERR
		return dbus_wrap(self.type, self.default)

	@dbus.service.method(InterfaceBusItem, out_signature = 'i')
	def SetDefault(self):
		if self.default is None:
			return DBUS_ERR
		self.SetValue(self.default)
		return DBUS_OK

	@dbus.service.method(InterfaceSettings, out_signature = 'vvvi')
	def GetAttributes(self):
		return (self.GetDefault(), self.GetMin(), self.GetMax(), self.GetSilent())

class GroupObject(dbus.service.Object):
	def __init__(self, busname, path, parent, removable = True):
		dbus.service.Object.__init__(self, busname, path)
		self._parent = parent
		self._children = {}
		self._settings = {}
		self._busName = busname
		self._removable = removable

	def toXml(self, element):
		for childId in self._children:
			subElement = etree.SubElement(element, tagForXml(childId))
			self._children[childId].toXml(subElement)

		for settingId in self._settings:
			subElement = etree.SubElement(element, tagForXml(settingId))
			self._settings[settingId].toXml(subElement)

	def cleanup(self):
		if not self._removable:
			return
		if not self._children and not self._settings:
			if self._parent:
				self._parent._children.pop(self._object_path.split("/")[-1])
				self._parent.cleanup()
			self.remove_from_connection()

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
	# @return completion-code When successful 0 is returned, negative otherwise.
	@dbus.service.method(InterfaceSettings, in_signature = 'ssvsvv', out_signature = 'i')
	def AddSetting(self, group, name, defaultValue, itemType, minimum, maximum):
		return self._addSetting(group, name, defaultValue, itemType, minimum, maximum, silent=False)[0]

	@dbus.service.method(InterfaceSettings, in_signature = 'ssvsvv', out_signature = 'i')
	def AddSilentSetting(self, group, name, defaultValue, itemType, minimum, maximum):
		return self._addSetting(group, name, defaultValue, itemType, minimum, maximum, silent=True)[0]

	def _addSetting(self, group, name, defaultValue, itemType, minimum, maximum, silent):
		if group.startswith('/') or group == '':
			groupPath = str(group)
		else:
			groupPath = '/' + str(group)

		if name.startswith('/'):
			relativePath = groupPath + str(name)
		else:
			relativePath = groupPath + '/' + str(name)

		return self.addSetting(relativePath, defaultValue, itemType, minimum, maximum, silent)

	def addSetting(self, relativePath, defaultValue, itemType, minimum, maximum, silent, replaces=None):
		# A prefixing underscore is an escape char: don't allow it in a normal path
		if "/_" in relativePath:
			return AddSettingError.UnderscorePrefix, None

		if itemType not in supportedTypes:
			return AddSettingError.UnknownType, None

		value = convertToType(itemType, defaultValue)
		if value is None:
			return AddSettingError.InvalidDefault, None
		defaultValue = value
		min = convertToType(itemType, minimum)
		max = convertToType(itemType, maximum)

		if not isinstance(value, str):
			if min == 0 and max == 0:
				min = None
				max = None

			if min is not None and value < min:
				return AddSettingError.DefaultOutOfRange, None

			if max is not None and value > max:
				return AddSettingError.DefaultOutOfRange, None
		else:
			min = None
			max = None

		if self._path() == "" and not relativePath.startswith("/Settings/"):
			return AddSettingError.NotInSettings, None

		newSetting = False
		settingObject = self.getSettingObject(relativePath)
		if not settingObject:
			# New setting
			newSetting = True
			if self.getGroup(relativePath):
				return AddSettingError.IsGroup, None

			# If a settings is being replaced, keep the old value and remove the old setting
			if replaces:
				for old in replaces:
					oldObject = self.getSettingObject(old)
					if oldObject:
						oldValue = oldObject.GetValue()
						if type(oldValue) == type(value):
							value = oldValue
						else:
							logging.warn("Ignoring old value of %s since it has a different type", old)
						oldObject.remove()

			settingObject = self.createSettingObjectAndGroups(relativePath)
			settingObject.setAttributes(defaultValue, itemType, min, max, silent)
		else:
			# Existing setting
			if settingObject.type != itemType:
				return AddSettingError.TypeDiffer, None

			changed = settingObject.setAttributes(defaultValue, itemType, min, max, silent)
			if not changed:
				return AddSettingError.NoError, settingObject

			# There are changes, save them while keeping the current value.
			value = settingObject.value

		if not settingObject._setValue(value, printLog=False, sendAttributes=True) and newSetting:
			settingObject.remove()
			return AddSettingError.InvalidDefault, None

		logging.info('Added new setting %s. default:%s, type:%s, min:%s, max: %s, silent: %s' % \
						 (self._path() + "/" + relativePath, defaultValue, itemType, minimum, maximum, silent))

		return AddSettingError.NoError, settingObject

	@dbus.service.method(InterfaceSettings, in_signature = 'aa{sv}', out_signature = 'aa{sv}')
	def AddSettings(self, definition):
		ret = []

		for props in definition:
			result = {}
			ret.append(result)

			path = props.get("path")
			if not isinstance(path, dbus.String):
				if path:
					result["path"] = path
				result["error"] = AddSettingError.InvalidPath
				continue

			result["path"] = path
			default = props.get("default")
			typeName = ""
			if isinstance(default, (dbus.Int32, dbus.Int64)):
				typeName = "i"
			elif isinstance(default, dbus.Double):
				typeName = "f"
			elif isinstance(default, dbus.String):
				typeName = "s"
			else:
				result["error"] = AddSettingError.UnknownType
				continue

			silent = False
			if props.get("silent"):
				silent = True

			replaces = props.get("replaces")

			result["error"], setting = self.addSetting(path, default, typeName, props.get("min"), props.get("max"), silent, replaces)
			if setting:
				result["value"] = setting.GetValue()

		return ret

	@dbus.service.method(InterfaceSettings, in_signature = 'as', out_signature = 'ai')
	def RemoveSettings(self, settings):
		global localSettings
		ret = []

		for setting in settings:
			settingObject = self.getSettingObject(setting)
			if settingObject:
				settingObject.remove()
				ret.append(0)
			else:
				ret.append(-1)

		localSettings.startTimeoutSaveSettings()

		return ret

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
		return DBUS_OK

# Special settings with contains class + instance. It is special since it
# disallows duplicate values and will be set to the next free one instead
# when attempting to set an already taken combination.
class ClassAndVrmInstance(SettingObject):
	def _setValue(self, value, printLog=True, sendAttributes=False):
		valid, value = self.group._parent.assureFreeInstance(value, self)
		if not valid:
			return False
		return SettingObject._setValue(self, value, printLog, sendAttributes)

	def SetDefault(self):
		return DBUS_ERR

## Unique VRM instances
# Just a normal group, except for ClassAndInstance which is a special setting
class DeviceGroup(GroupObject):
	def _newSettingObject(self, tag):
		if tag == "ClassAndVrmInstance":
			return ClassAndVrmInstance(self._busName, self._object_path + "/" + tag)
		return SettingObject(self._busName, self._object_path + "/" + tag)

# Assure unique instances per class. The value of ClassAndVrmInstance is e.g.
# battery:1 / battery:2 etc. The instances are stored under per device unique
# strings, so e.g.:
#
# /unique1/ClassAndVrmInstance
# /unique2/ClassAndVrmInstance
#
# When adding or attempting to change the ClassAndVrmInstance which is already
# taken, it will be set to the next free one.
class DevicesGroup(GroupObject):
	def _newSubGroup(self, path):
		return DeviceGroup(self._busName, path, self)

	# Make sure classInstanceStr is updated to a free one.
	# returns False if the string cannot be parsed.
	def assureFreeInstance(self, classInstanceStr, settingObject):
		if not isinstance(classInstanceStr, (dbus.String, str)):
			return False, None
		parts = classInstanceStr.split(":")
		if len(parts) != 2:
			return False, None
		devClass = parts[0]
		try:
			instance = int(parts[1])
		except:
			return False, None

		taken = list(self.forAllSettings(lambda x: x.GetValue() if x is not settingObject and \
									x.id() == "ClassAndVrmInstance" and \
									x.GetValue().startswith(devClass + ":") else None).values())

		while True:
			if classInstanceStr not in taken:
				return True, classInstanceStr
			instance += 1
			classInstanceStr = devClass + ":" + str(instance)

# Helpers
def convertToType(type, value):
	if value is None:
		return None
	try:
		return supportedTypes[type](value)
	except:
		return None

def _int(x):
	""" 64-bit aware conversion. """
	x = int(x)
	return dbus.types.Int64(x) if x > 0x7FFFFFFF else dbus.types.Int32(x)

def dbus_wrap(typ, value):
	if value is None:
		return None
	try:
		return {
			'i': _int,
			's': dbus.types.String,
			'f': dbus.types.Double
		}[typ](value)
	except KeyError:
		return None

def parseXmlFile(file, items):
	parser = etree.XMLParser(remove_blank_text=True)
	tree = etree.parse(file, parser)
	root = tree.getroot()
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
	root = etree.Element("Settings")
	root.set(settingsTag, settingsVersion)
	tree = etree.ElementTree(root)
	settingsGroup.toXml(root)
	localSettings.save(tree)

def toBool(val):
	if not isinstance(val, str):
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

			if not isinstance(defVal, str):
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
			logging.error('error loading %s: %s' % (filename, str(ex)))

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
		logging.info('Localsettings version is: 0x%04x' % version)

		if not path.isdir(pathSettings):
			print('Error path %s does not exist!' % pathSettings)
			sys.exit(errno.ENOENT)

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

				logging.info('Settings file %s validated' % self.fileSettings)

				if loadedVersionTxt != settingsVersion:
					print("Updating version to " + settingsVersion)
					root.set(settingsTag, settingsVersion)
					self.save(tree)

			except Exception as e:
				print(e)
				logging.error('Settings file %s invalid' % self.fileSettings)
				remove(self.fileSettings)
				logging.error('%s removed' % self.fileSettings)

		# check if settings file is present, if not exit create a "empty" settings file.
		if not path.isfile(self.fileSettings):
			logging.warning('Settings file %s not found' % self.fileSettings)
			root = etree.Element(settingsRootName)
			root.set(settingsTag, settingsVersion)
			tree = etree.ElementTree(root)
			self.save(tree)
			logging.warning('Created settings file %s' % self.fileSettings)

		# connect to the SessionBus if there is one. System otherwise
		bus = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in environ else dbus.SystemBus()
		busName = dbus.service.BusName(self.dbusName, bus)

		self.rootGroup = GroupObject(busName, "/", None, removable = False)
		self.settingsGroup = self.rootGroup.createGroups("/Settings")
		self.settingsGroup._removable = False
		devices = DevicesGroup(busName, "/Settings/Devices", self.settingsGroup, removable = False)
		self.settingsGroup.addGroup("Devices", devices)
		parseXmlFile(self.fileSettings, self.rootGroup)

	def save(self, tree):

		def recursive_sort(root):
			for t in root:
				recursive_sort(t)
			root[:] = sorted(root, key=lambda c: c.tag)
		recursive_sort(tree.getroot())

		with open(self.newFileSettings, 'wb') as fp:
			tree.write(fp, encoding = settingsEncoding, pretty_print = True, xml_declaration = True)
			fp.flush()
			os.fsync(fp.fileno())
			rename(self.newFileSettings, self.fileSettings)

			dst_dir = os.path.normpath(os.path.dirname(self.fileSettings))
			fd = os.open(dst_dir, 0)
			os.fsync(fd)
			os.close(fd)

	## The callback method for saving the settings-xml-file.
	# Calls the parseDictionaryToXmlFile with the dictionary settings and settings-xml-filename.
	def saveSettingsCallback(self):
		GLib.source_remove(self.timeoutSaveSettingsEventId)
		self.timeoutSaveSettingsEventId = None
		writeToXmlFile(self, self.settingsGroup)

	## Method for starting the time-out for saving to the settings-xml-file.
	# (Re)Starts the time-out. When after x time no settings are changed,
	# the settings-xml-file is saved.
	def startTimeoutSaveSettings(self):
		if self.timeoutSaveSettingsEventId is not None:
			GLib.source_remove(self.timeoutSaveSettingsEventId)
			self.timeoutSaveSettingsEventId = None
		self.timeoutSaveSettingsEventId = GLib.timeout_add(self.timeoutSaveSettingsTime * 1000,
														self.saveSettingsCallback)

def main(argv):
	global localSettings

	logging.getLogger().setLevel(logging.INFO)

	parser = argparse.ArgumentParser()
	parser.add_argument('--path', help = 'use given dir as data directory', default = ".")
	parser.add_argument('--no-delay', action = 'store_true',
							help = "don't delay storing the settings (used by the test script)")
	parser.add_argument('-v', '--version', action = 'store_true',
							help = "returns the program version")
	args = parser.parse_args(argv)

	if args.version:
		print("v%01x.%02x" % (FIRMWARE_VERSION_MAJOR, FIRMWARE_VERSION_MINOR))
		sys.exit()

	if args.path[-1] != '/':
		args.path += "/"

	print("localsettings v%01x.%02x starting up " % (FIRMWARE_VERSION_MAJOR, FIRMWARE_VERSION_MINOR))

	DBusGMainLoop(set_as_default=True)

	localSettings = LocalSettings(args.path, 0 if args.no_delay else 2)

	# load system default settings, note need localSettings to be ready
	loadSettingsDir(localSettings.sysSettingsDir, localSettings.settingsGroup)

	GLib.MainLoop().run()

main(sys.argv[1:])
