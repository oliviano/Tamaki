import time
import board
import busio
import adafruit_tca9548a
import adafruit_tlv493d

# Constants
SENSOR_ADDRESS = 0x5E
NUM_CHANNELS = 8

# I2C + TCA init
i2c = board.I2C()
# init mux
tca = adafruit_tca9548a.TCA9548A(i2c)
# init directly connected tlv sensor
tlv = adafruit_tlv493d.TLV493D(i2c)

# --- Safe Ping ---
def safe_ping(i2c_obj, address):
    try:
        i2c_obj.writeto(address, b'')  # Empty write = probe
        return True
    except Exception:
        return False

# --- Safe Scan ---
def safe_scan():
    print("Performing safe scan of all channels...")
    for ch in range(NUM_CHANNELS):
        if tca[ch].try_lock():
            try:
                present = safe_ping(tca[ch], SENSOR_ADDRESS)
                print(f"Channel {ch}: {'Sensor found' if present else 'No sensor'}")
            finally:
                tca[ch].unlock()
        else:
            print(f"Channel {ch}: Could not acquire I2C lock")

# --- Read Sensor ---
def read_sensor(channel):
    try:
        sensor = adafruit_tlv493d.TLV493D(tca[channel])
        x, y, z = sensor.magnetic
        print(f"Read from channel {channel}: x={x:.3f}, y={y:.3f}, z={z:.3f}")
        time.sleep(1)
        print(f"Read2 from channel {channel}: x={x:.3f}, y={y:.3f}, z={z:.3f}")
        return True
    except Exception as e:
        print(f"Read failed on channel {channel}: {e}")
        return False




# --- Main Routine ---
def main():
    safe_scan()
    print("\n--- Reading all sensors ---")
    while True:
        print("Sensor TLV NATIVE X: %s, Y: %s, Z: %s uT" % tlv.magnetic)
        sensor = adafruit_tlv493d.TLV493D(tca[0])
        x, y, z = sensor.magnetic
        print(f"Sensor TCA0: x={x:.3f}, y={y:.3f}, z={z:.3f}") 
        time.sleep(0.5)

if __name__ == "__main__":
    main()
