#!/usr/bin/python3

import sys
import os
import logging
from glob import glob
from argparse import ArgumentParser
import tarfile
import struct
from time import sleep
from io import BytesIO
from lxml import etree

# Files to backup relative to root (/data)
BACKUP = ('conf/settings.xml', )

def svstat(service):
	""" Simple python implementation of svstat, because the
	    daemontools version doesn't return useful exit statuses
		and this is less insane than parsing output. """
	f = os.path.join(service, 'supervise', 'status')
	try:
		fd = os.open(f, os.O_RDONLY | os.O_NONBLOCK)
	except OSError:
		return False
	else:
		status = os.read(fd, 18)
		if len(status) == 18:
			pid = struct.unpack('<i', status[12:16])[0]
			return pid > 0
		return False

def svc(service, ops):
	""" Simple python implementation of svc, because it is easy and we already
	    did svstat. """
	f = os.path.join(service, 'supervise', 'control')
	fd = os.open(f, os.O_WRONLY | os.O_NONBLOCK)
	try:
		os.write(fd, ops)
	finally:
		os.close(fd)

def reboot():
	""" Reboot by killing init. """
	os.kill(1, 2) # SIGINT

def setting_files(members, files):
	for info in members:
		if info.name in files:
			yield info

def backup(root, media, files):
	target = os.path.join(media[0], 'venus-cfg.tar')
	with tarfile.open(target, 'w') as tar:
		for name in files:
			tar.add(os.path.join(root, name), name)

def restore(root, media, files):
	# Iterate through all possible media to find a backup to restore
	for m in media:
		target = os.path.join(m, 'venus-cfg.tar')
		if os.path.exists(target):
			# Stop localsettings while doing this, otherwise it will just
			# overwrite the file again on shutdown later.
			svc("/service/localsettings", b"d")

			# Wait for it to stop
			for _ in range(3):
				if not svstat("/service/localsettings"):
					break # range(3)
				sleep(1)
			else:
				logging.error("localsettings failed to stop")
				reboot()
				break # m in media

			# Restore the settings
			with tarfile.open(target, 'r') as tar:
				tar.extractall(path=root, members=setting_files(tar, files))

			# Then reboot as some processes don't survive a localsettings
			# outage.
			reboot()
			break # m in media

def delete_from_tree(tree, path):
	obj = tree.xpath(path)
	if obj:
		obj[0].getparent().remove(obj[0])

def sanitize_settings(fp):
	parser = etree.XMLParser(remove_blank_text=True)
	tree = etree.parse(fp, parser)

	# Remove device-specific settings (based on serial number)
	delete_from_tree(tree, "/Settings/Devices")
	delete_from_tree(tree, "/Settings/CanBms")
	delete_from_tree(tree, "/Settings/Fronius/InverterIds")
	delete_from_tree(tree, "/Settings/Fronius/Inverters")
	delete_from_tree(tree, "/Settings/Victron/Products")

	# Return result
	return etree.tostring(tree, encoding='UTF-8', pretty_print=True, xml_declaration=True)

def export(root, media, files):
	with open(os.path.join(root, 'conf/settings.xml'), encoding='UTF-8') as fp:
		buf = sanitize_settings(fp)

	target = os.path.join(media[0], 'venus-cfg.tar')
	with tarfile.open(target, 'w') as tar:
		info = tarfile.TarInfo('conf/settings.xml')
		info.size = len(buf)
		tar.addfile(info, BytesIO(buf)) 
		for name in files:
			tar.add(os.path.join(root, name), name)
	
def main():
	# Parse arguments
	parser = ArgumentParser(description=sys.argv[0])
	parser.add_argument('--backup', help='Perform a backup of settings',
		default=False, action="store_true")
	parser.add_argument('--restore', help='Perform a restore of settings',
		default=False, action="store_true")
	parser.add_argument('--export',
		help='Export settings to be imported on another GX device',
		default=False, action="store_true")
	parser.add_argument('--target',
		help='Optional path to backup to, if omitted /media will be scanned',
		default=None)
	parser.add_argument('--root',
		help='Optional partition where settings are stored, defaults to /data',
		default='/data')
	args = parser.parse_args()

	if not (args.backup or args.restore or args.export):
		parser.print_help()
		sys.exit(1)

	# Logging
	logging.basicConfig(level=logging.INFO)

	# Find suitable place to put the backup
	if args.target is not None:
		media = [args.target]
	else:
		media = [x for x in glob('/media/*') if os.path.ismount(x)]
		media.sort()

	if not media:
		logging.info("Could not find suitable location for backup")
		sys.exit(1)

	if args.backup:
		backup(args.root, media, BACKUP)
	elif args.restore:
		restore(args.root, media, BACKUP)
	elif args.export:
		export(args.root, media, ())

if __name__ == "__main__":
	main()
