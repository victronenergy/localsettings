## @package tracing
# The tracing module for debug-purpose.

import logging
import logging.handlers

log = None
level = logging.DEBUG

## Setup the debug traces.
# The traces can be logged to console and/or file.
# When logged to file a logrotate is used.
# @param path the path for the traces_settings.txt file. 
def setupDebugTraces(path):
	global log
	global level
	log = logging.getLogger("localsettings_app")
	log.setLevel(level)
	log.disabled = False
	sth = logging.StreamHandler()
	sth.setLevel(level)
	log.addHandler(sth)
	fd = logging.handlers.RotatingFileHandler(path + 'traces_settings.txt', maxBytes=1048576, backupCount=5)
	fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
	fd.setFormatter(fmt)
	fd.setLevel(level)
	log.addHandler(fd)

