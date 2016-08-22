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

# Local
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
from settingsdevice import SettingsDevice
from vedbus import VeDbusItemImport

logger = logging.getLogger(__file__)

class LocalSettingsTest(unittest.TestCase):
	def setUp(self):
		# Always start with a fresh and running instance of localsettings
		try:
			os.remove('/data/conf/settings.xml')
		except OSError:
			pass

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
			self.assertEqual(0, self._add_setting(details['group'], details['setting'], details['default'], details['type'], details['min'], details['max']))

			# wait 2.5 seconds, since local settings itself waits 2 seconds before it stores the data.
			time.sleep(2.5)

			# restart localsettings
			self._stopLocalSettings()
			time.sleep(2)
			self._startLocalSettings()

			# read the results
			i = VeDbusItemImport(
				self._dbus,
				'com.victronenergy.settings',
				'/Settings/' + details['group'] + '/' + details['setting'],
				eventCallback=None,
				createsignal=False)
			result = copy.deepcopy(details)
			result['value'] = i.get_value().real
			result['default'] = i._proxy.GetDefault().real

			# don't ask me why, but getMin() and getMax() return a string...
			result['min'] = int(i._proxy.GetMin()) if details['type'] == 'i' else float(i._proxy.GetMin())
			result['max'] = int(i._proxy.GetMax()) if details['type'] == 'i' else float(i._proxy.GetMax())

			# don't check the type, as there is no GetType() available
			# result['type'] = i._proxy.GetType()

			self.assertEqual(details, result)

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
