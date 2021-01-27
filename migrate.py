from lxml import etree
import os

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

def rename_node(node, new_name):
	if node == None:
		return
	parent = node.getparent()
	if parent == None:
		return
	delete_from_tree(parent, new_name)
	node.tag = new_name

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
