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
tca = adafruit_tca9548a.TCA9548A(i2c)

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

def recover_channel(channel, sensor_address=0x5E):
    try:
        # Disable all channels
        tca.i2c.writeto(tca.i2c_device.device_address, bytes([0x00]))
        time.sleep(0.05)

        # Enable only the channel in question
        tca.i2c.writeto(tca.i2c_device.device_address, bytes([1 << channel]))
        time.sleep(0.05)

        if tca[channel].try_lock():
            try:
                tca[channel].writeto(sensor_address, b'')
                print(f"Recover attempt: Sensor on channel {channel} responded after reselection.")
                return True
            except Exception as e:
                print(f"Recover attempt failed on channel {channel}: {e}")
            finally:
                tca[channel].unlock()
    except Exception as e:
        print(f"Recover exception on channel {channel}: {e}")
    return False

# --- Recover Channel --- NotWorking
def recover_channel_NotWokring(channel, sensor_address=0x5E):
    try:
        # Disable all channels
        tca.i2c.writeto(tca._address, bytes([0x00]))
        time.sleep(0.05)

        # Enable only the channel in question
        tca.i2c.writeto(tca._address, bytes([1 << channel]))
        time.sleep(0.05)

        if tca[channel].try_lock():
            try:
                tca[channel].writeto(sensor_address, b'')
                print(f"Recover attempt: Sensor on channel {channel} responded after reselection.")
                return True
            except Exception as e:
                print(f"Recover attempt failed on channel {channel}: {e}")
            finally:
                tca[channel].unlock()
    except Exception as e:
        print(f"Recover exception on channel {channel}: {e}")
    return False

# --- Main Routine ---
def main():
    safe_scan()
    print("\n--- Reading all sensors ---")
    for ch in [0,1,2,3,4,5,6]:
        success = read_sensor(ch)
        if not success:
            print(f"Attempting recovery on channel {ch}...")
#            if recover_channel(ch):
#                read_sensor(ch)
    recover_channel(6, sensor_address=0x5E)
if __name__ == "__main__":
    main()
