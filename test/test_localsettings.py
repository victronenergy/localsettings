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

class CreateLocalSettingsTest(unittest.TestCase):
	# The actual code calling VeDbusItemExport is in fixture_vedbus.py, which is ran as a subprocess. That
	# code exports several values to the dbus. And then below test cases check if the exported values are
	# what the should be, by using the bare dbus import objects and functions.

	def _startLocalSettings(self):
		self.sp = subprocess.Popen([sys.executable, "../localsettings.py"], stdout=subprocess.PIPE)
		# wait for it to be up and running
		time.sleep(2)

		#while (self.sp.stdout.readline().rstrip().endswith('Created settings file /data/conf/settings.xml')):
		#	time.sleep(0.1)
		#	pass

	def _stopLocalSettings(self):
		self.sp.kill()
		self.sp.wait()

	def setUp(self):
		# Always start with a fresh and running instance of localsettings
		os.remove('/data/conf/settings.xml')
		self._startLocalSettings()
		self._dbus = dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus()

		self.testsets = {
				'int-no-min-max': {'group': 'g', 'setting': 's', 'value': 100, 'type': 'i', 'min': 0, 'max': 0}
			}


	def tearDown(self):
		self._stopLocalSettings()

	def _add_setting(self, group, setting, value, type, minimum, maximum):
		VeDbusItemImport(self._dbus, 'com.victronenergy.settings', '/Settings',
			createsignal=False)._proxy.AddSetting(group, setting, value, type, minimum, maximum)

	def test_adding_new_settings_and_readback(self):
		details = self.testsets['int-no-min-max']
		self._add_setting(details['group'], details['setting'], details['value'], details['type'], details['min'], details['max'])

		# wait 2.5 seconds, since local settings itself waits 2 seconds before it stores the data.
		time.sleep(2.5)

		# restart localsettings
		self._stopLocalSettings()
		time.sleep(2)
		self._startLocalSettings()

		self.assertEqual(VeDbusItemImport(self._dbus,
			'com.victronenergy.settings', '/Settings/' + details['group'] + '/' + details['setting']).get_value(), details['value'])

	def _call_me(self, service, path, changes):
		self._called = [service, path, changes]

	def test_adding_new_setting_creates_signal(self):
		details = self.testsets['int-no-min-max']

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

	def handle_changed_setting(setting, oldvalue, newvalue):
		pass

if __name__ == "__main__":
	logging.basicConfig(stream=sys.stderr)
	logging.getLogger('').setLevel(logging.WARNING)
	DBusGMainLoop(set_as_default=True)
	unittest.main()
