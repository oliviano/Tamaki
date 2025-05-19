import board
import busio
import adafruit_tca9548a
from adafruit_bus_device.i2c_device import I2CDevice

# Set up I2C and multiplexer
i2c = busio.I2C(board.SCL, board.SDA)
tca = adafruit_tca9548a.TCA9548A(i2c)

def safe_scan(tca_channel):
    found = []
    for addr in range(0x03, 0x78):
        try:
            device = I2CDevice(tca_channel, addr)
            with device:
                pass  # If this succeeds, the device is present
            found.append(addr)
        except Exception:
            pass
    return found

# Scan all channels
for ch in range(8):
    channel = tca[ch]
    print(f"Channel {ch}: {[hex(addr) for addr in safe_scan(channel)]}")
