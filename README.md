# localsettings

D-Bus settings manager that interfaces between xml file on disk and D-Bus. It is a
part of [Venus](https://github.com/victronenergy/venus/wiki). All programs that need
non-volatile settings use this dbus service. And all code that changes settings from
other processes, for example the GUI, do that via the D-Bus service of
com.victronenergy.settings as well. Some reasons for doing it this way are:
- one place to see all the settings
- one log to see changes in the settings (/log/localsettings/*)
- one place to reset all settings to factory-default

## D-Bus API
#### AddSetting
Call this function on the /Settings path.

Parameters:
- Groupname
- Setting name (can contain subpaths, for example display/brightness.
  /display/brightness will work as well and has the same effect)
- Default value
- Type ('i' - integer, 'f' - float, 's' - string)
- Min value
- Max value

Return code:
*  0 = OK
* -1 = Error, see code for details
* -2 = Error, one of the sections starts with an underscore, and that is not
  allowed. For example /_GUI/Brightness.
* -3 = Error, unsupport type
* -4 = Error, error converting value and min/max to the specified type
* -5 = Error, See code for details

Notes:
* Set both min and max to 0 to work without a min and max value
* Executing AddSetting for a path that already exists will not cause the existing
  value to be changed. In other words, it is safe to call AddSetting without first
  checking if that setting, aka path, is already there.

#### GetValue
Returns the value. Call this function on the path of which you want to read the
value. No parameters.

#### GetText
Same as GetValue, but then returns str(value).

#### SetValue
Call this function on the path of with you want to write a new value.

Return code:
*  0 = OK
* -1 = Error

#### GetMin
See source code

#### GetMax
See source code

#### SetDefault
See source code

## Usage examples and libraries
### Command line
Typical implementation in your code in case you want some settings would be:

1. Always do an AddSetting in the start of your code. This will make sure the setting
exists, and will not overwrite an existing value. Example with commandline tool:

    dbus -y com.victronenergy.settings /Settings AddSetting GUI Brightness 50 i 0 100

    In which 50 is the default value, i the type, 0 the minimum value and 100 the maximum value.
2. Then read it:

    dbus -y com.victronenergy.settings /Settings/GUI/Brightness GetValue

3. Or write it:

    dbus -y com.victronenergy.settings /Settings/GUI/Brightness SetValue 50

Obviously you won't be calling dbus -y everytime, but implement some straight dbus
interface in your code. Below are some examples for different languages.

### Python

To do this from Python, see import settingsdevice.py from velib_python. Below code gives a good example:

Somewhere in your init code, make the settings:

    from settingsdevice import SettingsDevice  # available in the velib_python repository
    settings = SettingsDevice(
        bus=dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus(),
        supportedSettings={
            'loggingenabled': ['/Settings/Logscript/Enabled', 1, 0, 1],
            'proxyaddress': ['/Settings/Logscript/Http/Proxy', '', 0, 0],
            'proxyport': ['/Settings/Logscript/Http/ProxyPort', '', 0, 0],
            'backlogenabled': ['/Settings/Logscript/LogFlash/Enabled', 1, 0, 1],
            'backlogpath': ['/Settings/Logscript/LogFlash/Path', '', 0, 0],  # When empty, default path will be used.
            'interval': ['/Settings/Logscript/LogInterval', 900, 0, 0],
            'url': ['/Settings/Logscript/Url', '', 0, 0]  # When empty, the default url will be used.
            },
        eventCallback=handle_changed_setting)

Have a callback some where, in above code it is handle_changed_setting. That is how
you'ĺl be informed that someone, for example the GUI, has changed a setting. Above
function has this definition:

    def handle_changed_setting(setting, oldvalue, newvalue):
        print 'setting changed, setting: %s, old: %s, new: %s' % (setting, oldvalue, newvalue)


To read or write a setting yourself, do:

    settings['url'] = ''


Or read from it:

    print(settings['url'])

### QT / C++
todo.

### C
todo.

## Running on a linux PC
It is also possible to run localsettings on a linux PC, which may be convenient for testing other
CCGX services.

The localsettings script requires python dbus, gobject and xml support (for python 2.7). On a
debian system install the packages python-dbus, python-gobject and python-lxml.

Note that localsettings assumes that a writable directory /data/conf exists on your system, which is
not available on most (all) linux systems, so you have to create it manually. Make sure the user
running the localsettings script has write access to this directory. Alternatively, you can also
adjust the script in order to set a different directory. In localsettings.py look for:

pathSettings = '/data/conf/'
