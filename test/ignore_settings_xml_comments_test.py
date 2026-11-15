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

class XmlCommentsTest(Base):
    def test_comments_do_not_prevent_settings_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.xml'
            path.write_text('<Settings><!-- operator note --><Demo>'
                '<!-- another note --><Value type="i" default="7">8</Value>'
                '</Demo></Settings>')
            ls.parseXmlFile(str(path), self.root)
        self.assertEqual(self.root.getSettingObject('Settings/Demo/Value').GetValue(), 8)

if __name__ == "__main__": unittest.main()
