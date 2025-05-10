# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT

# This example shows using two TSL2491 light sensors attached to TCA9548A channels 0 and 1.
# Use with other I2C sensors would be similar.
import time
import board
#import adafruit_tsl2591
import adafruit_tca9548a
import adafruit_tlv493d

# Create I2C bus as normal
i2c = board.I2C()  # uses board.SCL and board.SDA
# i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller

# Create the TCA9548A object and give it the I2C bus
tca = adafruit_tca9548a.TCA9548A(i2c)

# For each sensor, create it using the TCA9548A channel instead of the I2C object
tlv1 = adafruit_tlv493d.TLV493D(tca[0])
tlv2 = adafruit_tlv493d.TLV493D(tca[1])

# After initial setup, can just use sensors as normal.
while True:
	print("TLV1 SENSOR: X: %s, Y: %s, Z: %s uT" % tlv1.magnetic)
	print("TLV2 SENSOR: X: %s, Y: %s, Z: %s uT" % tlv2.magnetic)
	time.sleep(1)
