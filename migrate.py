from lxml import etree
import os
import subprocess

VRM_PORTAL_OFF = 0
VRM_PORTAL_READ_ONLY = 1
VRM_PORTAL_FULL = 2

SECURITY_PROFILE_SECURED = 0
SECURITY_PROFILE_WEAK = 1
SECURITY_PROFILE_UNSECURED = 2
SECURITY_PROFILE_INDETERMINATE = 3

def create_empty_password_file():
	try:
		open('/data/conf/vncpassword.txt', 'w').close()
	except:
		print("writing password file failed")
		pass

def delete_from_tree(tree, path):
	obj = tree.xpath(path)
	if not obj:
		return
	obj[0].getparent().remove(obj[0])

def create_or_update_node(parent, tag, value, type = "i"):
	child = parent.find(tag)
	if child is None:
		child = etree.SubElement(parent, tag)
	child.text = str(value)
	child.set("type", type)

def create_node(parent, tag, value, type = "i"):
	child = parent.find(tag)
	if child is not None:
		return

	child = etree.SubElement(parent, tag)
	child.text = str(value)
	child.set("type", type)

def get_or_create_node_and_parents(parent, path):
	ids = path.split("/")
	node = parent
	for id in ids:
		if id == "":
			continue

		child = node.find(id)
		if child is None:
			node = etree.SubElement(node, id)
		else:
			node = child
	return node

def rename_node(node, new_name):
	if node == None:
		return
	parent = node.getparent()
	if parent == None:
		return
	delete_from_tree(parent, new_name)
	node.tag = new_name

# Change the class name and try to preserve the current instance.
# The next free one will be used if already taken.
def change_class(node, classname):
	try:
		old = node.text.split(":")
		instance = int(old[1])
		oldInstance = instance
		oldClass = old[0]
		node.set("default", node.get("default").replace(oldClass + ":", classname + ":"))

		while True:
			newValue = classname + ":" + str(instance)
			node.text = newValue
			result = int(node.xpath("count(/Settings/Devices/*/ClassAndVrmInstance[text() = '" + newValue + "'])"))
			if result == 1:
				break
			instance += 1

		if oldInstance != instance:
			print("WARNING: changing " + oldClass + ":" + str(oldInstance) + " to " + newValue)
	except:
		print("could not change the class")

## Migrate old canbus settings
def migrate_can_profile(localSettings, tree, version):
	if version != 1:
		return

	if not os.path.isfile("/etc/venus/canbus_ports"):
		return

	with open('/etc/venus/canbus_ports', 'r') as f:
		iflist = f.readline().split(None, 1)
		if not iflist:
			return
		interface = iflist[0]

	path = "/Settings/Canbus/" + interface + "/Profile"

	if tree.xpath(path):
		return

	# default to Ve.Can
	profile = 1

	if tree.xpath("/Settings/Services/LgResu/text()") == ["1"]:
		profile = 3
	elif tree.xpath("/Settings/Services/OceanvoltMotorDrive/text()") == ["1"] or \
		tree.xpath("/Settings/Services/OceanvoltValence/text()") == ["1"]:
		profile = 4
	elif tree.xpath("/Settings/Services/VeCan/text()") == ["0"]:
		profile = 0

	print("Setting " + path + " to " + str(profile))

	settings = tree.getroot()
	canbus = settings.find("Canbus")
	if canbus == None:
		canbus = etree.SubElement(settings, "Canbus")

	inter = canbus.find(interface)
	if inter == None:
		inter = etree.SubElement(canbus, interface)

	create_or_update_node(inter, "Profile", profile)

	delete_from_tree(tree, "/Settings/Services/LgResu")
	delete_from_tree(tree, "/Settings/Services/OceanvoltMotorDrive")
	delete_from_tree(tree, "/Settings/Services/OceanvoltValence")
	delete_from_tree(tree, "/Settings/Services/VeCan")

def migrate_remote_support(localSettings, tree, version):
	if version != 1:
		return

	if tree.xpath("/Settings/System/RemoteSupport/text()") != ["1"]:
		return

	print("Enable ssh on LAN since it was enabled by RemoteSupport")
	settings = tree.getroot()
	system = settings.find("System")
	if system == None:
		system = etree.SubElement(settings, "System")

	create_or_update_node(system, "SSHLocal", 1)

def migrate_mqtt(localSettings, tree, version):
	if version > 2:
		return

	settings = tree.getroot()
	services = settings.find("Services")

	if services == None:
		return

	mqtt_local = 0
	mqtt_local_insec = 0
	mqtt_vrm = 0

	if tree.xpath("/Settings/Services/Mqtt/text()") == ["1"]:
		mqtt_local = 1
		mqtt_local_insec = 1
		mqtt_vrm = 1

	if tree.xpath("/Settings/Services/Vrmpubnub/text()") == ["1"]:
		mqtt_vrm = 1

	create_or_update_node(services, "MqttLocal", mqtt_local)
	create_or_update_node(services, "MqttLocalInsecure", mqtt_local_insec)
	create_or_update_node(services, "MqttVrm", mqtt_vrm)

	delete_from_tree(tree, "/Settings/Services/Mqtt")
	delete_from_tree(tree, "/Settings/Services/Vrmpubnub")

def migrate_remotesupport2(localSettings, tree, version):
	if version > 3:
		return

	# moved, now stores ip and port
	delete_from_tree(tree, "/Settings/System/RemoteSupportPort")

def propFloatToInt(elem, name):
	try:
		elem.set(name, str(int(float(elem.get(name, "0.0")))))
	except Exception as e:
		print(e)
		return

def elemFloatToInt(elem):
	elem.set("type", "i")
	propFloatToInt(elem, "min")
	propFloatToInt(elem, "max")
	propFloatToInt(elem, "default")
	try:
		delete_from_tree(elem.getparent(), elem.tag + "2")
		elem.text = str(int(float(elem.text)))
		elem.tag = elem.tag + "2"
	except Exception as e:
		print(e)
		return

def elemsFloatToInt(elements):
	for elem in elements:
		elemFloatToInt(elem)

def migrate_adc(localSettings, tree, version):
	if version > 5:
		return

	# These integers were incorrectly stored as floats.
	elemsFloatToInt(tree.xpath("/Settings/AnalogInput/Resistive/*/Function"))
	elemsFloatToInt(tree.xpath("/Settings/AnalogInput/Temperature/*/Function"))
	elemsFloatToInt(tree.xpath("/Settings/Tank/*/FluidType"))
	elemsFloatToInt(tree.xpath("/Settings/Tank/*/Standard"))
	elemsFloatToInt(tree.xpath("/Settings/Temperature/*/TemperatureType"))


# In v2.60~13 the devices were not prefixed. So rename the nodes so that
# the kwh counters don't get lost. Skip the ones starting with a number,
# since that is an invalid xml tag and causes all settings to be lost. They
# cannot be present anyway, since v2.60~13 could not cope with them either.
#
# There is no need to keep this for a long time, since it only fixes a
# candidate version.
def migrate_fixup_cgwacs(localSettings, tree, version):
	if version >= 8:
		return

	elem = tree.xpath("/Settings/CGwacs/DeviceIds/text()")
	if len(elem) == 0:
		return
	ids = elem[0].split(",")
	for ident in ids:
		# tags cannot start with a number in xml. Hence they do not need a fixup,
		# since all settings would have be restored to default in an earlier update.
		if len(ident) == 0 or (ids[0] >= '0' and ids[0] <= '9'):
			continue

		dev = tree.xpath("/Settings/Devices/" + ident)
		if len(dev) == 0:
			continue
		rename_node(dev[0], "cgwacs_" + ident)

		dev = tree.xpath("/Settings/Devices/" + ident + "_S")
		if len(dev) == 0:
			continue
		rename_node(dev[0], "cgwacs_" + ident + "_S")

def migrate_cgwacs_deviceinstance(localSettings, tree, version):
	if version >= 8:
		return

	devices = tree.getroot().find("Devices")
	if devices is None:
		devices = etree.SubElement(tree.getroot(), 'Devices')

	for e in tree.xpath("/Settings/CGwacs/Devices/*"):
		device = 'cgwacs_' + e.tag[1:] # [1:] bc old numbers prefixed with D

		container = devices.find(device)
		if container is None:
			container = etree.SubElement(devices, device)

		# migrate device instance and phase support
		servicetype = e.xpath('ServiceType/text()')[0]
		deviceinstance = e.xpath('DeviceInstance/text()')[0]
		devicetype = int(e.xpath('DeviceType/text()')[0])
		create_node(container, 'ClassAndVrmInstance',
			'{}:{}'.format(servicetype, deviceinstance), 's')
		create_node(container, 'SupportMultiphase',
			int((71 <= devicetype <= 73) or (340 <= devicetype <= 345)), 'i')

		# Move these to the right location
		for setting, typ in (('CustomName', 's'), ('L1ReverseEnergy', 'f'),
				('L2ReverseEnergy', 'f'), ('L3ReverseEnergy', 'f'), 
				('Position', 'i')):
			old = e.xpath(setting + '/text()')
			if old:
				create_node(container, setting, old[0], typ)

		# This was renamed, because Multiphase is one word
		create_node(container, 'IsMultiphase',
			e.xpath('IsMultiPhase/text()')[0], 'i')

		# Migrate piggyback settings to secondary device
		piggy = '{}_S'.format(device)
		container = devices.find(piggy)
		if container is None:
			container = etree.SubElement(devices, piggy)

		create_node(container, 'ClassAndVrmInstance',
			'pvinverter:{}'.format(e.xpath('L2/DeviceInstance/text()')[0]), 's')
		create_node(container, 'Enabled',
			int(e.xpath('L2/ServiceType/text()') == ["pvinverter"]), 'i')
		create_node(container, 'Position', e.xpath('L2/Position/text()')[0], 'i')
		cn = e.xpath('L2/CustomName/text()')
		if cn:
			create_node(container, 'CustomName', cn[0], 's')

	delete_from_tree(tree, "/Settings/CGwacs/Devices")

def migrate_fronius_deviceinstance(localSettings, tree, version):
	if version > 7:
		return

	devices = tree.getroot().find("Devices")
	if devices is None:
		devices = etree.SubElement(tree.getroot(), 'Devices')

	inverters = tree.xpath("/Settings/Fronius/InverterIds/text()")
	if inverters:
		inverters = inverters[0].split(",")
		for idx, inverter in enumerate(inverters):
			container = devices.find(inverter)
			if container is None:
				container = etree.SubElement(devices, inverter)
			create_or_update_node(container, 'ClassAndVrmInstance',
				'pvinverter:{}'.format(20 + idx), 's')

def migrate_adc_settings(localSettings, tree, version):
	if version > 8:
		return

	tank = []
	temp = []

	try:
		f = open('/etc/venus/dbus-adc.conf', 'r')

		for line in f:
			w = line.split()

			if len(w) < 2:
				continue

			if w[0] == 'tank':
				tank.append(w[1])
				continue

			if w[0] == 'temp':
				temp.append(w[1])
				continue

		f.close()
	except:
		return

	tag_map = {
		'Function2':           ['Function', 'i'],
		'ResistanceWhenFull':  ['RawValueFull', 'f'],
		'ResistanceWhenEmpty': ['RawValueEmpty', 'f'],
	}

	devices = tree.getroot().find("Devices")
	if devices is None:
		devices = etree.SubElement(tree.getroot(), 'Devices')

	def getdev(pin):
		name = 'adc_builtin0_%s' % pin
		node = devices.find(name)
		if node is None:
			node = etree.SubElement(devices, name)
		return node

	def move_nodes(pins, paths):
		for p in range(len(pins)):
			num = p + 1
			pin = pins[p]
			dev = getdev(pin)

			for fmt in paths:
				path = fmt % {'num': num, 'pin': pin}
				nodes = tree.xpath(path + '/*')

				for n in nodes:
					n.getparent().remove(n)
					m = tag_map.get(n.tag)
					if m:
						n.tag = m[0]
						n.set('type', m[1])
					if dev.find(n.tag) is None:
						dev.append(n)

				delete_from_tree(tree, path)

	move_nodes(tank, ['/Settings/AnalogInput/Resistive/_%(num)s',
					  '/Settings/Devices/adc_iio_device0_%(pin)s',
					  '/Settings/Tank/_%(num)s'])
	move_nodes(temp, ['/Settings/AnalogInput/Temperature/_%(num)s',
					  '/Settings/Devices/adc_iio_device0_%(pin)s',
					  '/Settings/Temperature/_%(num)s'])

	delete_from_tree(tree, '/Settings/AnalogInput')
	delete_from_tree(tree, '/Settings/Tank')
	delete_from_tree(tree, '/Settings/Temperature')

def migrate_fischerpanda_autostart(localSettings, tree, version):
	if version >= 11:
		return
	autostart = int(tree.xpath("/Settings/Services/FischerPandaAutoStartStop/text()") == ["1"])
	try:
		tree.xpath('/Settings/FischerPanda0/AutoStartEnabled')[0].text = str(autostart)
	except (IndexError, AttributeError):
		pass
	else:
		delete_from_tree(tree, "/Settings/Services/FischerPandaAutoStartStop")

def migrate_fischerpanda_to_generic_genset(localSettings, tree, version):
	if version >= 12:
		return

	dev = tree.xpath("/Settings/FischerPanda0")
	if dev:
		rename_node(dev[0], "Generator1")

def migrate_analog_sensors_classes(localSettings, tree, version):
	if version >= 13:
		return

	for dev in tree.xpath("/Settings/Devices/*/ClassAndVrmInstance[starts-with(text(),'analog:')]/.."):
		# TemperatureType is used by mopeka, TemperatureType2 by dbus-adc.
		if dev.find("FluidType") is not None or dev.find("FluidType2") is not None:
			newClass = "tank"
		# TemperatureType is used by ruuvi, TemperatureType2 by dbus-adc.
		elif dev.find("TemperatureType") is not None or dev.find("TemperatureType2") is not None:
			newClass = "temperature"
		else:
			print("WARN:could not determine the class of " + dev.tag)
			continue

		change_class(dev.find('ClassAndVrmInstance'), newClass)

def migrate_vedirect_classes(localsettings, tree, version):
	if version >= 13:
		return

	classAndVrmInstances = tree.xpath('/Settings/Devices/*/ClassAndVrmInstance')
	for e in classAndVrmInstances:
		try:
			if e.text.startswith('com.victronenergy.'):
				newClass = e.text.split(":")[0][len('com.victronenergy.'):]
				change_class(e, newClass)
		except:
			pass

def migrate_security_settings(localsettings, tree, version):
	if version >= 14:
		return

	# defaults, just in case an unexpected exception is thrown
	vrmPortal = VRM_PORTAL_FULL
	securityProfile = SECURITY_PROFILE_SECURED

	# is there currently a password set?
	try:
		with open('/data/conf/vncpassword.txt') as f:
			passwordSet = f.readline().strip() != ""
	except:
		passwordSet = False # doubtful: VNC e.g. won't allow logins if the password file is missing

	# Convert VRM Logmode
	try:
		node = tree.xpath("/Settings/Vrmlogger/Logmode")
		if node:
			logMode = int(node[0].text)

			# if logging to VRM was off, it remains off
			if logMode == 0:
				vrmPortal = VRM_PORTAL_OFF
			else:
				# Check VRM two-communication / MqttVrm
				twoWay = False
				try:
					node = tree.xpath("/Settings/Services/MqttVrm")
					if node and int(node[0].text) == 1:
						twoWay = True
				except:
					pass

				# two-way communication enabled -> Full Mode
				if twoWay:
					vrmPortal = VRM_PORTAL_FULL
				else:
					vrmPortal = VRM_PORTAL_READ_ONLY #### doesn't correspond with the document
	except:
		pass

	delete_from_tree(tree, '/Settings/Vrmlogger/Logmode')
	delete_from_tree(tree, '/Settings/Services/MqttVrm')

	# Set Security Profile for Remote Console on LAN
	node = tree.xpath("/Settings/System/VncLocal")
	if node and int(node[0].text) == 1:
		if passwordSet:
			securityProfile = SECURITY_PROFILE_WEAK
		else:
			securityProfile = SECURITY_PROFILE_UNSECURED
	else:
		# note: Secured without a password disables Remote Console on LAN like VncLocal == 0 used to do.
		# Since VRM will not check the password file, make sure it is actually removed.
		if not passwordSet:
			try:
				os.remove("/data/conf/vncpassword.txt")
			except OSError:
				pass
		securityProfile = SECURITY_PROFILE_INDETERMINATE

	# Merge VncInternet and VncLocal and set VRM Portal accordingly
	try:
		node = tree.xpath("/Settings/System/VncInternet")
		if node and int(node[0].text) == 1:
			# Remote Console v1 on VRM / VncInternet is merged with VncLocal, but on VRM it is
			# only enabled when VRM portal is set to full.
			create_or_update_node(tree.xpath("/Settings/System")[0], "VncLocal", 1)
			vrmPortal = VRM_PORTAL_FULL
	except:
		pass

	# XXX: keep VncInternet around for now, since venus-access depends on it, remote support /
	# the ssh server won't be started after downgrading if gui-v2 is running, since gui-v1 adds
	# this setting.
	#
	# delete_from_tree(tree, '/Settings/System/VncInternet')

	# Handle the MQTT settings
	mqttLocal = False
	mqttLocalInsecure = False
	try:
		node = tree.xpath("/Settings/Services/MqttLocal")
		if node and int(node[0].text) == 1:
			mqttLocal = True
		node = tree.xpath("/Settings/Services/MqttLocalInsecure")
		if node and int(node[0].text) == 1:
			mqttLocalInsecure = True
	except:
		pass

	# The local mqtt broker didn't support authentication, so forcefully allow
	# unauthorized access to be backwards compatible.
	if mqttLocal or mqttLocalInsecure:
		securityProfile = SECURITY_PROFILE_UNSECURED
		create_empty_password_file()

	delete_from_tree(tree, '/Settings/Services/MqttLocalInsecure')

	# Add the converted settings
	system = tree.getroot().find("System")
	if system == None:
		system = etree.SubElement(tree.getroot(), "System")
	create_or_update_node(system, "SecurityProfile", securityProfile)

	network = tree.getroot().find("Network")
	if network == None:
		network = etree.SubElement(tree.getroot(), "Network")
	create_or_update_node(network, "VrmPortal", vrmPortal)


# In Venus 3.20, a change in localsettings inadvertently made the default
# attribute required on ClassAndVrmInstance tags. That causes settings files
# migrated from before settingsVersion 8 to be corrupted, since the migration
# did not add a default attribute.
#
# This is particularly bad, since it leaves the hardware inaccessible and the
# only way to recover is a factory reset.  This is fixed in Venus 3.50, but to
# ensure that old broken files are recovered, delete the ClassAndVrmInstance
# tag if it has no attributes at all, since no information can be lost anyway
# and that allows recovering the lost devices.
def fix_broken_vrm_instance_tags(localsettings, tree, version):
	if version >= 15:
		return
	nodes = tree.xpath("/Settings/Devices/*/ClassAndVrmInstance")
	for node in nodes:
		# If the node has no attributes, delete it. Nothing can be lost
		# that isn't already lost.
		if len(node.attrib) == 0:
			parent = node.getparent()
			print ("Cleaning ClassAndVrmInstance for " + parent.tag)
			parent.remove(node)

def migrate_dess_limits(localSettings, tree, version):
	if version >= 18:
		return

	dess = tree.getroot().find("DynamicEss")
	if dess is not None:
		for elem in dess.xpath("GridImportLimit|GridExportLimit|BatteryDischargeLimit|BatteryChargeLimit"):
			elem.set("type", "f")

def migrate_guiv2_brief_level(localSettings, tree, version):
	if version >= 17:
		return

	try:
		newlevels = get_or_create_node_and_parents(tree.getroot(), "Gui2/BriefView/Level")

		nodes = tree.xpath("/Settings/Gui/BriefView/Level/*")
		all_default = True
		for node in nodes:
			value = node.text
			default = node.get("default")
			if value != default:
				all_default = False
				break

		if not all_default:
			for node in nodes:
				value = node.text
				create_or_update_node(newlevels, node.tag, str(value), "s")

		delete_from_tree(tree, "/Settings/Gui/BriefView/Level")

	except Exception as e:
		print(e)
		pass

def migrate_relay_manual_polarity(localSettings, tree, version):
	if version >= 19:
		return
	# For all relays configured as manual, ensure that the polarity
	# is unchanged. This is to avoid relays suddenly flipping logic
	# when we start also using the polarity for the manual function.
	for p in ("Relay", "Relay/_1"):
		try:
			if tree.xpath(f"string(/Settings/{p}/Function)") == "2":
				tree.xpath(f"/Settings/{p}/Polarity")[0].text = "0"
		except Exception as e:
			print (e)

def migrate(localSettings, tree, version):
	migrate_can_profile(localSettings, tree, version)
	migrate_remote_support(localSettings, tree, version)
	migrate_mqtt(localSettings, tree, version)
	migrate_remotesupport2(localSettings, tree, version)
	migrate_adc(localSettings, tree, version)
	migrate_fronius_deviceinstance(localSettings, tree, version)
	migrate_fixup_cgwacs(localSettings, tree, version)
	migrate_cgwacs_deviceinstance(localSettings, tree, version)
	migrate_adc_settings(localSettings, tree, version)
	migrate_fischerpanda_autostart(localSettings, tree, version)
	migrate_fischerpanda_to_generic_genset(localSettings, tree, version)
	migrate_analog_sensors_classes(localSettings, tree, version)
	migrate_vedirect_classes(localSettings, tree, version)
	migrate_security_settings(localSettings, tree, version)
	fix_broken_vrm_instance_tags(localSettings, tree, version)
	migrate_dess_limits(localSettings, tree, version)
	migrate_guiv2_brief_level(localSettings, tree, version)
	migrate_relay_manual_polarity(localSettings, tree, version)

def cleanup_settings(tree):
	""" Clean up device-specific settings. Used when restoring settings
	    from another GX-device. """
	delete_from_tree(tree, "/Settings/Devices")
	delete_from_tree(tree, "/Settings/CanBms")
	delete_from_tree(tree, "/Settings/Fronius/InverterIds")
	delete_from_tree(tree, "/Settings/Fronius/Inverters")
	delete_from_tree(tree, "/Settings/Victron/Products")

def check_security(localSettings):
	# check if the password file should be restored. e.g. restore to defaults can
	# remove the password file...
	if os.path.isfile("/data/conf/vncpassword.txt"):
		return

	try:
		# if the device was shipped with a password, restore it..
		result = subprocess.run(["ve-is-passwd-set-by-default"])
		if result.returncode == 0:
			result = subprocess.run("ve-set-passwd-to-pincode")
			if result.returncode != 0:
				print("error: ve-set-passwd-to-pincode failed")
		else:
			# For older device, drop the default authentication, so an UI on LAN
			# is available to configure the device and allow to set a password e.g.
			securityProfile = localSettings.settingsGroup.getSettingObject("System/SecurityProfile")
			if securityProfile is None:
				print("error: System/SecurityProfile is missing")
				return

			if not os.path.exists("/dev/fb0") or os.path.exists("/etc/venus/headless"):
				securityProfile.SetValue(SECURITY_PROFILE_UNSECURED)
				create_empty_password_file()
			else:
				securityProfile.SetValue(SECURITY_PROFILE_INDETERMINATE)

	except:
		print("check_security: failed")