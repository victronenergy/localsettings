# localsettings

[![Build Status](https://travis-ci.org/victronenergy/localsettings.svg?branch=master)](https://travis-ci.org/victronenergy/localsettings)

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
This method can be called on any path, which is not a setting. For example
on `com.victronenergy.settings /`.

Parameters:
- Groupname
- Setting name (can contain subpaths, for example display/brightness.
  /display/brightness will work as well and has the same effect)
- Default value
- Type ('i' - integer, 'f' - float, 's' - string)
- Min value
- Max value

Return code:
* 0 = OK
* Negative, see AddSettingError in the source for details

Notes:
* Set both min and max to 0 to work without a min and max value
* Executing AddSetting for a path that already exists will not cause the existing
  value to be changed. In other words, it is safe to call AddSetting without first
  checking if that setting, aka path, is already there.

Vrm Device Instances: 

Localsettings can assign a unique number (instance) per device class to
a device. The path for that is `/Settings/Devices/[UniqueID]/ClassAndVrmInstance`.

The device class for which to reserve an instance, as well as the prefered instance,
are passed, combined into a tuple, as the default value. For example `("battery", 1)`.

The instance will automatically be set to an unique number (for the given class). So
if the supplied parameter was `("battery", 1)`, and instance 1 already existed for the
`battery` class, then it will get the next free unique number, and get set to `("battery":2)`
for example. Or `("battery", 3)` if 2 was already taken.

The `UniqueID` in the path can, for example, be the serial number of said device.

Clearly, if there already was a record for that combination of class and UniqueID, then
it won't reserve a new instamce number, and instead do nothing.

To get the (then reserved) instance, add a GetValue call after the AddSettings call.

More info about this also in the [dbus-api doc](https://github.com/victronenergy/venus/wiki/dbus-api#vrm-device-instances).

#### AddSettings
This dbus method call allows to add multiple settings at once which
saves some roundtrips if there are many settings like the gui has.

Unlike the AddSetting, it doesn't make a distinction between groups
and setting and only accepts a single path. The type is based on the
(mandatory) default value and doesn't need to be passed. min, max and silent
are optional.

Required parameters:
- "path" the (relative) path for the setting. /Settings/Display/Brightness when called \
  on / or /Display/Brightness when called on /Settings etc.
- "default" the default value of the setting. The type of the default values determines \
  the setting type.

Optional parameters:
- "min"
- "max"
- "silent" don't log changes

For each entry, at least error and path are returned (unless it
wasn't passed). The actual value is returned when no error occured.

Commandline examples:

```
dbus com.victronenergy.settings / AddSettings \
'%[{"path": "/Settings/Test", "default": 5}, {"path": "/Settings/Float", "default": 5.0}]'

[{'error': 0, 'path': '/Settings/Test', 'value': 1},
 {'error': 0, 'path': '/Settings/Float', 'value': 5.0}]

or on /Settings:

dbus com.victronenergy.settings /Settings AddSettings \
'%[{"path": "Test", "default": 5}, {"path": "Float", "default": 5.0}]'

[{'error': 0, 'path': 'Test', 'value': 1},
 {'error': 0, 'path': 'Float', 'value': 5.0}]

or for testing:

dbus com.victronenergy.settings /Settings/Devices AddSettings '%[{"path": "a/ClassAndVrmInstance", "default": "battery:1"}, {"path": "b/ClassAndVrmInstance", "default": "battery:1"}]'
[{'error': 0, 'path': 'a/ClassAndVrmInstance', 'value': 'battery:1'},
 {'error': 0, 'path': 'b/ClassAndVrmInstance', 'value': 'battery:2'}

In case the unique identifier changes, the following can be used to keep the original instance:
dbus com.victronenergy.settings /Settings/Devices AddSettings '%[{"path": "c/ClassAndVrmInstance", "default": "battery:2", "replaces": ["a/ClassAndVrmInstance"]}]'
[{'error': 0, 'path': 'c/ClassAndVrmInstance', 'value': 'battery:1'}]
```

#### RemoveSettings
Removes all settings for a given array with paths

returns an array with 0 for success and -1 for failure.

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

4. dbus com.victronenergy.settings /Settings AddSettings \
'%[{"path": "Int", "default": 5}, {"path": "Float", "default": 5.0}, {"path": "String", "default": "string"}]'

5. dbus com.victronenergy.settings /Settings RemoveSettings '%["Int", "Float", "String"]'

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
