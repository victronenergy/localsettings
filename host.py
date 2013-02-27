## @package host
# Indicates if host is pc or embedded-device.
#
# On the embedded-device the system-dbus is used.
# On the pc the session-dbus is used.

## True host is pc, False host is an embedded-device.
# The return value is set manually ;-).
def isHostPC():
	return False
