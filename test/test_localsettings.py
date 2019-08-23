#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Python
import logging
import os
import sqlite3
import sys
import unittest
import subprocess
import time
import platform
import dbus
import threading
import fcntl
import copy
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import os

# Local
here = os.path.dirname(__file__)
sys.path.insert(1, os.path.join(here, '../ext/velib_python'))
from settingsdevice import SettingsDevice
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

		# float-no-min-max doesn't work, because localsettings does not recognize 0.0 and 0.0 as no min max, only 0 and 0 works.
		# testsets['float-no-min-max'] = {'group': 'g', 'setting': 'f', 'default': 102.0, 'value': 102.0, 'type': 'f', 'min': 0.0, 'max': 0.0}

		testsets['float-with-min-max'] = {'group': 'g', 'setting': 'f', 'default': 103.0, 'value': 103.0, 'type': 'f', 'min': 0.0, 'max': 1000.0}
		testsets['start-group-with-digit'] = {'group': '0g', 'setting': 's', 'default': 104, 'value': 104, 'type': 'i', 'min': 0, 'max': 0}
		testsets['start-setting-with-digit'] = {'group': 'g', 'setting': '0s', 'default': 105, 'value': 105, 'type': 'i', 'min': 0, 'max': 0}
		testsets['int-re-add-same-min-max'] = {'group': 'g', 'setting': 'in', 'default': 200, 'value': 100, 'type': 'i', 'min': 0, 'max': 0}
		testsets['int-re-add-other-min-max'] = {'group': 'g', 'setting': 'in', 'default': 201, 'value': 100, 'type': 'i', 'min': 10, 'max': 1000}
		testsets['float-re-add-other-min-max'] = {'group': 'g', 'setting': 'f', 'default': 103.0, 'value': 103.0, 'type': 'f', 'min': 1.0, 'max': 1001.0}

		for name, details in testsets.iteritems():
			print "\n\n===Testing %s===\n" % name
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
				result['value'] = i.get_value().real
				result['default'] = i._proxy.GetDefault().real

				# don't ask me why, but getMin() and getMax() return a string...
				result['min'] = int(i._proxy.GetMin()) if details['type'] == 'i' else float(i._proxy.GetMin())
				result['max'] = int(i._proxy.GetMax()) if details['type'] == 'i' else float(i._proxy.GetMax())

				# don't check the type, as there is no GetType() available
				# result['type'] = i._proxy.GetType()
			except Exception as e:
				print("FAILED: " + str(e))
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

		for name, details in testsets.iteritems():
			print "\n\n===Testing %s===\n" % name
			self.assertEqual(-2, self._add_setting(details['group'], details['setting'], details['value'], details['type'], details['min'], details['max']))

	def test_re_adding_setting_with_different_type_fails(self):
		self.assertEqual(0, self._add_setting('g', 's', 0, 'i', 0, 0))
		self.assertGreater(0, self._add_setting('g', 's', 0, 'f', 0, 0))

	def _startLocalSettings(self):
		self._isUp = False
		self.sp = subprocess.Popen([sys.executable, os.path.join(here, "..", "localsettings.py"), "--path=" + self._dataDir, "--no-delay"], stdout=subprocess.PIPE)

		# wait for it to be up and running
		while not self._isUp:
			main_context = GLib.MainContext.default()
			while main_context.pending():
				main_context.iteration(False)


	def _stopLocalSettings(self):
		self.sp.kill()
		self.sp.wait()

	def _add_setting(self, group, setting, value, type, minimum, maximum, rpc_name='AddSetting'):
		item = VeDbusItemImport(self._dbus, 'com.victronenergy.settings', '/Settings', createsignal=False)
		return item._proxy.get_dbus_method(rpc_name)(group, setting, value, type, minimum, maximum)

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
