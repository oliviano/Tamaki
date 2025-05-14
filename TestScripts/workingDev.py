# working dev code
# detects TLV sensor(s)
# Avoid Scan method from tca9548a 


import time
import board
import adafruit_tca9548a
import adafruit_tlv493d

def find_tlv493d_sensors(i2c_bus=None, max_channels=8):
	"""Scan all TCA9548A channels and return a list of detected TLV493D sensor objects."""
	# Create I2C bus as normal
	i2c = board.I2C()  # uses board.SCL and board.SDA
	# Create the TCA9548A object and give it the I2C bus
	tca = adafruit_tca9548a.TCA9548A(i2c)

	detected_sensors = []

	for channel in range(max_channels):
		try:
			print(f"Trying channel {channel}...")
			sensor = adafruit_tlv493d.TLV493D(tca[channel])
			# Access a property to force communication and confirm it's working
			_ = sensor.magnetic
			print(f"✅ TLV493D detected on channel {channel}")
			detected_sensors.append((channel, sensor))
		except Exception as e:
			print(f"❌ No TLV493D on channel {channel} (Error: {e})")

	return detected_sensors


find_tlv493d_sensors()

