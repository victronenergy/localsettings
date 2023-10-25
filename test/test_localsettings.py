#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Python
import logging
import os
import sys
import unittest
import subprocess
import time
import platform
import dbus
import copy
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import os

# Local
here = os.path.dirname(__file__)
sys.path.insert(1, os.path.join(here, '../ext/velib_python'))
from vedbus import VeDbusItemImport

logger = logging.getLogger(__file__)

class LocalSettingsTest(unittest.TestCase):
	def setUp(self):
		self._dataDir = os.path.join(here, "data/conf")
		if not os.path.exists(self._dataDir):
			os.makedirs(self._dataDir)
		self._settingsFile = self._dataDir + '/settings.xml'
		# Always start with a fresh and running instance of localsettings
		try:
			os.remove(self._settingsFile)
		except OSError:
			pass

		self._dbus = dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus()
		self._dbus.add_signal_receiver(self.dbus_name_owner_changed, signal_name='NameOwnerChanged')
		self._isUp = False
		self._startLocalSettings()

	def tearDown(self):
		self._stopLocalSettings()
		self._dbus.remove_signal_receiver(self.dbus_name_owner_changed, signal_name='NameOwnerChanged')

	def updateSettingsStamp(self):
		self._settingsStamp = os.path.getmtime(self._settingsFile)

	def waitForSettingsStored(self):
		for x in range(0, 50):
			if self._settingsStamp != os.path.getmtime(self._settingsFile):
				return
			time.sleep(0.01)

	def test_adding_new_setting_creates_signal(self):
		self.add_new_setting_creates_signal('AddSetting')

	def test_adding_new_silent_setting_creates_signal(self):
		self.add_new_setting_creates_signal('AddSilentSetting')

	def add_new_setting_creates_signal(self, rpc_name='AddSetting'):
		details = {'group': 'g', 'setting': 's', 'value': 100, 'type': 'i', 'min': 0, 'max': 0}

		monitor = VeDbusItemImport(
			self._dbus,
			'com.victronenergy.settings',
			'/Settings/' + details['group'] + '/' + details['setting'],
			eventCallback=self._call_me,
			createsignal=True)

		self.updateSettingsStamp()
		self._add_setting(details['group'], details['setting'], details['value'], details['type'], details['min'], details['max'])
		self.waitForSettingsStored()

		# restart localsettings
		self._stopLocalSettings()
		self._startLocalSettings()

		# manually iterate the mainloop
		main_context = GLib.MainContext.default()
		while main_context.pending():
			main_context.iteration(False)

		self.assertEqual(self._called, ['com.victronenergy.settings', '/Settings/' + details['group'] + '/' + details['setting'],
						{'Text': '100', 'Value': 100, 'Min': 0, 'Max': 0, 'Default': 100 }])

	def test_adding_new_settings_and_readback(self):
		self.add_new_settings_and_readback(rpc_name='AddSetting')

	def test_adding_new_silent_settings_and_readback(self):
		self.add_new_settings_and_readback(rpc_name='AddSilentSetting')

	def add_new_settings_and_readback(self, rpc_name='AddSetting'):
		from collections import OrderedDict
		testsets = OrderedDict()
		testsets['int-no-min-max'] = {'group': 'g', 'setting': 'in', 'default': 100, 'value': 100, 'type': 'i', 'min': 0, 'max': 0}
		testsets['int-with-min-max'] =  {'group': 'g', 'setting': 'iw', 'default': 101, 'value': 101, 'type': 'i', 'min': 0, 'max': 101}
		testsets['float-no-min-max'] = {'group': 'g', 'setting': 'f2', 'default': 102.0, 'value': 102.0, 'type': 'f', 'min': 0.0, 'max': 0.0}
		testsets['float-with-min-max'] = {'group': 'g', 'setting': 'f', 'default': 103.0, 'value': 103.0, 'type': 'f', 'min': 0.0, 'max': 1000.0}
		testsets['start-group-with-digit'] = {'group': '0g', 'setting': 's', 'default': 104, 'value': 104, 'type': 'i', 'min': 0, 'max': 0}
		testsets['start-setting-with-digit'] = {'group': 'g', 'setting': '0s', 'default': 105, 'value': 105, 'type': 'i', 'min': 0, 'max': 0}
		testsets['int-re-add-same-min-max'] = {'group': 'g', 'setting': 'in', 'default': 200, 'value': 100, 'type': 'i', 'min': 0, 'max': 0}
		testsets['int-re-add-other-min-max'] = {'group': 'g', 'setting': 'in', 'default': 201, 'value': 100, 'type': 'i', 'min': 10, 'max': 1000}
		testsets['float-re-add-other-min-max'] = {'group': 'g', 'setting': 'f', 'default': 103.0, 'value': 103.0, 'type': 'f', 'min': 1.0, 'max': 1001.0}
		# min / max is actually None, but the dbus specification has no representation for that, so 0 is used.
		testsets['string'] = {'group': 'g', 'setting': 'string', 'default': "test", 'value': "test", 'type': 's', 'min': 0, 'max': 0}

		for name, details in testsets.items():
			print ("\n\n===Testing %s===\n" % name)
			self.updateSettingsStamp()
			setting = details['setting'] + '/' + rpc_name
			self.assertEqual(0, self._add_setting(details['group'], setting, details['default'], details['type'], details['min'], details['max'], rpc_name=rpc_name))
			self.waitForSettingsStored()

			# restart localsettings
			self._stopLocalSettings()
			self._startLocalSettings()

			# read the results
			i = VeDbusItemImport(
				self._dbus,
				'com.victronenergy.settings',
				'/Settings/' + details['group'] + '/' + setting,
				eventCallback=None,
				createsignal=False)
			result = copy.deepcopy(details)

			try:
				result['value'] = i.get_value()
				result['default'] = i._proxy.GetDefault()
				result['min'] = i._proxy.GetMin()
				result['max'] = i._proxy.GetMax()
			except Exception as e:
				self.fail("FAILED: " + str(e))
				print(details)

			self.assertEqual(details, result)

	def test_change_max_creates_signal(self):
		details = {'group': 'g', 'setting': 'f', 'value': 103.0, 'type': 'f', 'min': 2.0, 'max': 1002.0}

		self._called = []
		monitor = VeDbusItemImport(
			self._dbus,
			'com.victronenergy.settings',
			'/Settings/' + details['group'] + '/' + details['setting'],
			eventCallback=self._call_me,
			createsignal=True)

		self._add_setting(details['group'], details['setting'], details['value'], details['type'], details['min'], details['max'])

		# manually iterate the mainloop
		main_context = GLib.MainContext.default()
		while main_context.pending():
			main_context.iteration(False)

		self.assertEqual(self._called, ['com.victronenergy.settings', '/Settings/' + details['group'] + '/' + details['setting'],
						{'Default': 103.0, 'Text': '103.0', 'Min': 2.0, 'Max': 1002.0, 'Value': 103}])

	def test_adding_new_settings_with_underscore_fails(self):
		testsets = {
			'start-group-with-underscore-fails': {'group': '_g', 'setting': 's', 'value': 100, 'type': 'i', 'min': 0, 'max': 0},
			'start-setting-with-underscore-fails': {'group': 'g', 'setting': '_s', 'value': 100, 'type': 'i', 'min': 0, 'max': 0}
		}

		for name, details in testsets.items():
			print ("\n\n===Testing %s===\n" % name)
			self.assertEqual(-2, self._add_setting(details['group'], details['setting'], details['value'], details['type'], details['min'], details['max']))

	def test_re_adding_setting_with_different_type_fails(self):
		self.assertEqual(0, self._add_setting('g', 's', 0, 'i', 0, 0))
		self.assertGreater(0, self._add_setting('g', 's', 0, 'f', 0, 0))

	def get_value(self, path):
		object = self._dbus.get_object("com.victronenergy.settings", os.path.join("/Settings", path))
		try:
			get_value_cmd = object.get_dbus_method("GetValue")
			return get_value_cmd()
		except:
			return None

	def set_value(self, path, value):
		object = self._dbus.get_object("com.victronenergy.settings", os.path.join("/Settings", path))
		set_value_cmd = object.get_dbus_method("SetValue")
		return set_value_cmd(value)

	def get_default(self, path):
		object = self._dbus.get_object("com.victronenergy.settings", os.path.join("/Settings", path))
		try:
			get_default_cmd = object.get_dbus_method("GetDefault")
			return get_default_cmd()
		except:
			return None

	def test_remove_setting(self):
		print("\n===Testing RemoveSettings ===\n")
		self.assertEqual(0, self._add_setting('g', 's', 0, 'i', 0, 0))
		object = self._dbus.get_object("com.victronenergy.settings", "/Settings")
		rm_settings = object.get_dbus_method("RemoveSettings")
		self.assertEqual(self.get_value("g/s"), 0)
		reply = rm_settings(["g/s"])
		self.assertEqual(reply[0], 0)
		self.assertEqual(self.get_value("g/s"), None)

	def test_multiple_settings(self):
		print("\n===Testing Multiple Settings ===\n")

		# note: _value is _not_ part of the dbus, but what the outcome should be.
		parameters = [
			{'path': 'g/in', 'default': 100, '_value': 100},
			{'path': 'g/iw', 'default': 101, 'min': 0, 'max': 101, '_value': 101},
			{'path': 'g/f2', 'default': 102.0, '_value': 102.0},
			{'path': 'g/f', 'default': 103.0, 'min': 0.0, 'max': 1000.0, '_value': 103.0},
			{'path': '0g/s', 'default': 104, '_value': 104},
			{'path': 'g/0s', 'default': 105, '_value': 105},
			{'path': 'g/in', 'default': 200, '_value': 100},
			{'path': 'g/in', 'default': 201, 'min': 10, 'max': 1000, '_value': 100},
			{'path': 'g/f', 'default': 103.0, 'min': 1.0, 'max': 1001.0, '_value': 103.0},
			{'path': 'g/f', 'default': 95.0, 'min': 1.0, 'max': 1001.0, '_value': 103.0},
			{'path': 'g/f', 'default': 95.0, 'min': 1.0, 'max': 1001.0, 'forceValue': 0, '_value': 103.0},
			{'path': 'g/string', 'default': "test", '_value': "test"}
		]

		# filter out the _value, that should be the result.
		values = []
		for i in range(len(parameters) - 1, -1, -1):
			values.insert(0, parameters[i]["_value"])
			del parameters[i]["_value"]

		result = self._add_settings(parameters)
		self.assertEqual(len(parameters), len(result))
		for n in range(len(parameters)):
			self.assertEqual(result[n]["error"], 0)
			self.assertEqual(result[n]["value"], values[n])

		# get the unique paths
		paths = set()
		for parameter in parameters:
			paths.add(parameter["path"])

		# verify getItems reports all the settings correctly.
		result = self._get_items()
		self.assertEqual(len(result), len(paths))
		for path, properties in result.items():
			found1 = found2 = False

			# Note: the properties like min/max etc should be the last one being set..
			for i in range(len(parameters) - 1, -1, -1):
				if path == "/Settings/" + parameters[i]["path"]:
					if "min" in parameters[i]:
						self.assertEqual(properties["Min"], parameters[i]["min"])
					if "max" in parameters[i]:
						self.assertEqual(properties["Max"], parameters[i]["max"])
					if "default" in parameters[i]:
						self.assertEqual(properties["Default"], parameters[i]["default"])
					found1 = True
					break

			# For the value it should be the first default, and the value should be kept
			for i in range(len(parameters)):
				if path == "/Settings/" + parameters[i]["path"]:
					self.assertEqual(properties["Value"], parameters[i]["default"])
					found2 = True
					break

			self.assertTrue(found1)
			self.assertTrue(found2)

		# verify that value is changed when forceValue = 1
		self._add_settings([{'path': 'g/f', 'default': 98.0, 'min': 1.0, 'max': 1001.0, 'forceValue': 1}])
		result = self._get_items()
		self.assertEqual(result["/Settings/g/f"]["Value"], 98.0)
		self.assertEqual(result["/Settings/g/f"]["Default"], 98.0)

		# verify that value is not changed when forceValue = 1, but the default stays the same
		self.set_value("g/f", 95.0)
		result = self._get_items()
		self.assertEqual(result["/Settings/g/f"]["Value"], 95.0)
		self.assertEqual(result["/Settings/g/f"]["Default"], 98.0)

		self._add_settings([{'path': 'g/f', 'default': 98.0, 'min': 1.0, 'max': 1001.0, 'forceValue': 1}])
		result = self._get_items()
		self.assertEqual(result["/Settings/g/f"]["Value"], 95.0)
		self.assertEqual(result["/Settings/g/f"]["Default"], 98.0)

	def test_vrm_instance(self):
		print("\n===Testing VRM Instances ===\n")
		definition = [
			{"path": "Devices/a/ClassAndVrmInstance", "default": "battery:1"},
			{"path": "Devices/b/ClassAndVrmInstance", "default": "battery:1"},
			{"path": "Devices/c/ClassAndVrmInstance", "default": "battery:00002"},
			{"path": "Devices/q/ClassAndVrmInstance", "default": "battery:3.5"},
			{"path": "Devices/b/ClassAndVrmInstance", "default": "battery:1.5"},
		]
		settings = self._add_settings(definition)
		self.assertEqual(len(settings), len(definition))

		self.assertEqual(settings[0]["error"], 0)
		self.assertEqual(settings[0]["path"], "Devices/a/ClassAndVrmInstance")
		self.assertEqual(settings[0]["value"], "battery:1")

		self.assertEqual(settings[1]["error"], 0)
		self.assertEqual(settings[1]["path"], "Devices/b/ClassAndVrmInstance")
		self.assertEqual(settings[1]["value"], "battery:2")

		self.assertEqual(settings[2]["error"], 0)
		self.assertEqual(settings[2]["path"], "Devices/c/ClassAndVrmInstance")
		self.assertEqual(settings[2]["value"], "battery:3")

		# error on new path
		self.assertEqual(settings[3]["path"], "Devices/q/ClassAndVrmInstance")
		self.assertEqual(settings[3]["error"], -6)

		# error on existing path
		self.assertEqual(settings[4]["path"], "Devices/b/ClassAndVrmInstance")
		self.assertEqual(settings[4]["error"], -6)

		# a: battery:1, battery:1
		# b: battery:1, battery:2
		# c: battery:2, battery:3

		# Check that the class type doesn't change when the default changes.
		definition = [ {"path": "Devices/b/ClassAndVrmInstance", "default": "tank:1" } ]
		settings = self._add_settings(definition)
		self.assertEqual(len(settings), 1)

		self.assertEqual(settings[0]["error"], 0)
		self.assertEqual(settings[0]["path"], "Devices/b/ClassAndVrmInstance")
		self.assertEqual(settings[0]["value"], "battery:2")
		self.assertEqual(self.get_default("Devices/b/ClassAndVrmInstance"), "tank:1")

		# a: battery:2, battery:1
		# b: tank:1, battery:2
		# c: battery:2, battery:3

		# A SetValue should change the class though.
		self.set_value("Devices/a/ClassAndVrmInstance", "tank:1")
		self.assertEqual(self.get_value("Devices/a/ClassAndVrmInstance"), "tank:1")
		self.assertEqual(self.get_default("Devices/a/ClassAndVrmInstance"), "battery:1")

		# a: battery:2, tank:1
		# b: tank:1, battery:2
		# c: battery:2, battery:3

		# Check that the class type does change when the default changes and forceValue is 1.
		definition = [ {"path": "Devices/c/ClassAndVrmInstance", "default": "tank:1", "forceValue": 1 } ]
		settings = self._add_settings(definition)
		self.assertEqual(len(settings), 1)

		self.assertEqual(settings[0]["error"], 0)
		self.assertEqual(settings[0]["path"], "Devices/c/ClassAndVrmInstance")
		self.assertEqual(settings[0]["value"], "tank:2")
		self.assertEqual(self.get_default("Devices/c/ClassAndVrmInstance"), "tank:1")

		# a: battery:2, tank:1
		# b: tank:1, battery:2
		# c: tank:1, tank:2

		# Check that the class type does not change when the default changes and forceValue is 0.
		definition = [ {"path": "Devices/c/ClassAndVrmInstance", "default": "solar:1", "forceValue": 0 } ]
		settings = self._add_settings(definition)
		self.assertEqual(len(settings), 1)

		self.assertEqual(settings[0]["error"], 0)
		self.assertEqual(settings[0]["path"], "Devices/c/ClassAndVrmInstance")
		self.assertEqual(settings[0]["value"], "tank:2")
		self.assertEqual(self.get_default("Devices/c/ClassAndVrmInstance"), "solar:1")

		# a: battery:2, tank:1
		# b: tank:1, battery:2
		# c: solar:1, tank:2

		# Check that the value does not change when the value is already the correct class
		# Setup for the test
		self.set_value("Devices/c/ClassAndVrmInstance", "tank:3")
		self.assertEqual(self.get_value("Devices/c/ClassAndVrmInstance"), "tank:3")
		self.assertEqual(self.get_default("Devices/c/ClassAndVrmInstance"), "solar:1")

		definition = [ {"path": "Devices/c/ClassAndVrmInstance", "default": "tank:1", "forceValue": 1 } ]
		settings = self._add_settings(definition)
		self.assertEqual(len(settings), 1)

		self.assertEqual(settings[0]["error"], 0)
		self.assertEqual(settings[0]["path"], "Devices/c/ClassAndVrmInstance")
		self.assertEqual(settings[0]["value"], "tank:3")
		self.assertEqual(self.get_default("Devices/c/ClassAndVrmInstance"), "tank:1")

		# a: battery:2, tank:1
		# b: tank:1, battery:2
		# c: tank:1, tank:3

		definition = [ {"path": "Devices/c/ClassAndVrmInstance", "default": "tank:2", "forceValue": 1 } ]
		settings = self._add_settings(definition)
		self.assertEqual(len(settings), 1)

		self.assertEqual(settings[0]["error"], 0)
		self.assertEqual(settings[0]["path"], "Devices/c/ClassAndVrmInstance")
		self.assertEqual(settings[0]["value"], "tank:3")
		self.assertEqual(self.get_default("Devices/c/ClassAndVrmInstance"), "tank:2")

		# a: battery:2, tank:1
		# b: tank:1, battery:2
		# c: tank:2, tank:3

	def _startLocalSettings(self):
		self._isUp = False
		self.sp = subprocess.Popen([sys.executable, os.path.join(here, "..", "localsettings.py"), "--path=" + self._dataDir, "--no-delay"], stdout=subprocess.PIPE)

		# wait for it to be up and running
		while not self._isUp:
			main_context = GLib.MainContext.default()
			while main_context.pending():
				main_context.iteration(False)


	def _stopLocalSettings(self):
		self.sp.stdout.close()
		self.sp.kill()
		self.sp.wait()

	def _add_setting(self, group, setting, value, type, minimum, maximum, rpc_name='AddSetting'):
		item = VeDbusItemImport(self._dbus, 'com.victronenergy.settings', '/Settings', createsignal=False)
		return item._proxy.get_dbus_method(rpc_name)(group, setting, value, type, minimum, maximum)

	def _add_settings(self, properties):
		object = self._dbus.get_object("com.victronenergy.settings", "/Settings")
		add_settings = object.get_dbus_method("AddSettings", dbus_interface="com.victronenergy.Settings")
		return add_settings(properties)

	def _get_items(self):
		object = self._dbus.get_object("com.victronenergy.settings", "/")
		get_items = object.get_dbus_method("GetItems", dbus_interface="com.victronenergy.BusItem")
		return get_items()

	def _call_me(self, service, path, changes):
		self._called = [service, path, changes]

	def	handle_changed_setting(setting, oldvalue, newvalue):
		pass

	def dbus_name_owner_changed(self, name, oldowner, newowner):
		if name == "com.victronenergy.settings" and newowner != "":
			self._isUp = True


if __name__ == "__main__":
	logging.basicConfig(stream=sys.stderr)
	logging.getLogger('').setLevel(logging.WARNING)
	DBusGMainLoop(set_as_default=True)
	unittest.main()
