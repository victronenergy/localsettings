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
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# Local
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
from settingsdevice import SettingsDevice
from vedbus import VeDbusItemImport

logger = logging.getLogger(__file__)

class LocalSettingsTest(unittest.TestCase):
	def setUp(self):
		# Always start with a fresh and running instance of localsettings
		os.remove('/data/conf/settings.xml')
		self._startLocalSettings()
		self._dbus = dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus()

	def tearDown(self):
		self._stopLocalSettings()

	def test_adding_new_setting_creates_signal(self):
		details = {'group': 'g', 'setting': 's', 'value': 100, 'type': 'i', 'min': 0, 'max': 0}

		monitor = VeDbusItemImport(
			self._dbus,
			'com.victronenergy.settings',
			'/Settings/' + details['group'] + '/' + details['setting'],
			eventCallback=self._call_me,
			createsignal=True)

		self._add_setting(details['group'], details['setting'], details['value'], details['type'], details['min'], details['max'])

		# wait 2.5 seconds, since local settings itself waits 2 seconds before it stores the data.
		time.sleep(2.5)

		# restart localsettings
		self._stopLocalSettings()
		time.sleep(2)
		self._startLocalSettings()

		# manually iterate the mainloop
		main_context = GLib.MainContext.default()
		while main_context.pending():
			main_context.iteration(False)

		self.assertEqual(self._called, ['com.victronenergy.settings', '/Settings/' + details['group'] + '/' + details['setting'], {'Text': '100', 'Value': 100}])

	def test_adding_new_settings_and_readback(self):
		testsets = {
			'int-no-min-max': {'group': 'g', 'setting': 's', 'value': 100, 'type': 'i', 'min': 0, 'max': 0},
			'start-group-with-digit': {'group': '0g', 'setting': 's', 'value': 100, 'type': 'i', 'min': 0, 'max': 0},
			'start-setting-with-digit': {'group': 'g', 'setting': '0s', 'value': 100, 'type': 'i', 'min': 0, 'max': 0}
		}

		for name, details in testsets.iteritems():
			print "\n\n===Testing %s===\n" % name
			self.assertEqual(0, self._add_setting(details['group'], details['setting'], details['value'], details['type'], details['min'], details['max']))

			# wait 2.5 seconds, since local settings itself waits 2 seconds before it stores the data.
			time.sleep(2.5)

			# restart localsettings
			self._stopLocalSettings()
			time.sleep(2)
			self._startLocalSettings()

			self.assertEqual(VeDbusItemImport(self._dbus, 'com.victronenergy.settings',
				'/Settings/' + details['group'] + '/' + details['setting']).get_value(), details['value'])

	def test_adding_new_settings_with_underscore_fails(self):
		testsets = {
			'start-group-with-underscore-fails': {'group': '_g', 'setting': 's', 'value': 100, 'type': 'i', 'min': 0, 'max': 0},
			'start-setting-with-underscore-fails': {'group': 'g', 'setting': '_s', 'value': 100, 'type': 'i', 'min': 0, 'max': 0}
		}

		for name, details in testsets.iteritems():
			print "\n\n===Testing %s===\n" % name
			self.assertEqual(-2, self._add_setting(details['group'], details['setting'], details['value'], details['type'], details['min'], details['max']))

	def _startLocalSettings(self):
		self.sp = subprocess.Popen([sys.executable, "../localsettings.py"], stdout=subprocess.PIPE)
		# wait for it to be up and running
		time.sleep(2)

	def _stopLocalSettings(self):
		self.sp.kill()
		self.sp.wait()

	def _add_setting(self, group, setting, value, type, minimum, maximum):
		return VeDbusItemImport(self._dbus, 'com.victronenergy.settings', '/Settings',
		createsignal=False)._proxy.AddSetting(group, setting, value, type, minimum, maximum)

	def _call_me(self, service, path, changes):
		self._called = [service, path, changes]

	def	handle_changed_setting(setting, oldvalue, newvalue):
		pass

if __name__ == "__main__":
	logging.basicConfig(stream=sys.stderr)
	logging.getLogger('').setLevel(logging.WARNING)
	DBusGMainLoop(set_as_default=True)
	unittest.main()
