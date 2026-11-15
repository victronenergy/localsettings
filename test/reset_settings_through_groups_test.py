from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import dbus
from dbus.mainloop.glib import DBusGMainLoop
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ast
import types
source = Path(__file__).resolve().parents[1] / 'localsettings.py'
tree = ast.parse(source.read_text())
assert isinstance(tree.body[-1], ast.Expr)
assert isinstance(tree.body[-1].value, ast.Call)
assert isinstance(tree.body[-1].value.func, ast.Name)
assert tree.body[-1].value.func.id == 'main'
# Load definitions without launching the command-line service.
tree.body.pop()
ls = types.ModuleType('localsettings_under_test')
ls.__file__ = str(source)
sys.modules[ls.__name__] = ls
exec(compile(tree, str(source), 'exec'), ls.__dict__)

DBusGMainLoop(set_as_default=True)

class Base(unittest.TestCase):
    def setUp(self):
        self.bus = dbus.SessionBus(private=True)
        self.previous = ls.localSettings
        ls.localSettings = SimpleNamespace(startTimeoutSaveSettings=lambda: None)
        self.root = ls.GroupObject(self.bus, '/Settings', None, removable=False)

    def tearDown(self):
        self.bus.close()
        ls.localSettings = self.previous

    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'defaults.conf'
            path.write_text(text)
            ls.loadSettingsFile(str(path), self.root)

from unittest.mock import patch

class ResetGroupTest(Base):
    def test_group_reset_forwards_caller_and_restores_values(self):
        self.root.AddSetting('Demo', 'First', 5, 'i', 0, 20)
        self.root.AddSetting('Demo', 'Nested/Second', 6, 'i', 0, 20)
        first = self.root.getSettingObject('Demo/First')
        second = self.root.getSettingObject('Demo/Nested/Second')
        first.SetValue(10, ':1.0')
        second.SetValue(12, ':1.0')
        group = self.root.getGroup('Demo')
        self.assertEqual(group.SetDefault(':1.0'), 0)
        self.assertEqual((first.GetValue(), second.GetValue()), (5, 6))

    def test_rejected_reset_is_reported(self):
        self.root.AddSetting('Demo', 'First', 5, 'i', 0, 20)
        setting = self.root.getSettingObject('Demo/First')
        with patch.object(setting, 'SetValue', return_value=ls.DBUS_ERR):
            self.assertEqual(setting.SetDefault(':1.0'), ls.DBUS_ERR)

if __name__ == "__main__": unittest.main()
