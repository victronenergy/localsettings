## @package tracing
# The tracing module for debug-purpose.

import logging
import logging.handlers

log = None

## Setup the debug traces.
# The traces can be logged to console and/or file.
# When logged to file a logrotate is used.
# @param path the path for the traces_settings.txt file. 
def setupDebugTraces(path):
	global log
	log = logging.getLogger("localsettings_app")
	log.setLevel(logging.DEBUG)
	log.disabled = False
	sth = logging.StreamHandler()
	sth.setLevel(logging.DEBUG)
	log.addHandler(sth)
	fd = logging.handlers.RotatingFileHandler(path + 'traces_settings.txt', maxBytes=1048576, backupCount=5)
	fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
	fd.setFormatter(fmt)
	fd.setLevel(logging.DEBUG)
	#log.addHandler(fd)

