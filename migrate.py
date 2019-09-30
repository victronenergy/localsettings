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

	localSettings.save(tree)

def migrate_remote_support(localSettings, tree, version):
	if version != 1:
		return

	if tree.xpath("/Settings/System/RemoteSupport/text()") != ["1"]:
		return

	print("Enable ssh on LAN since it was enabled by RemoteSupport")
	settings = tree.getroot()
	system = settings.find("System")
	if system == None:
		system = system.SubElement(settings, "System")

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

	localSettings.save(tree)

def migrate(localSettings, tree, version):
	migrate_can_profile(localSettings, tree, version)
	migrate_remote_support(localSettings, tree, version)
	migrate_mqtt(localSettings, tree, version)
