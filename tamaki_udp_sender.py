# SPDX-FileCopyrightText: 2025 Olivier Jean for Artifical Imagination
# SPDX-License-Identifier: MIT

import time
import board
import socket
import adafruit_tca9548a
import adafruit_tlv493d
import json

# --- Configuration ---
HOST_IP = "192.168.6.51"  # IP address of the PC running TouchDesigner
HOST_PORT = 8000          # Port TouchDesigner is listening on
NUM_SENSORS = 2           # Number of TLV493D sensors connected to the TCA9548A
                          # (Ensure they are on channels 0, 1, ..., NUM_SENSORS-1)
SEND_FREQUENCY_HZ = 10     # Desired send frequency in Hz. 0 for max speed.
                          # If > 0, a delay will be introduced.

# --- Initialize I2C and Multiplexer ---
try:
    i2c = board.I2C()  # Uses board.SCL and board.SDA
    # For STEMMA QT connector on some boards:
    # i2c = board.STEMMA_I2C()
except RuntimeError as e:
    print(f"Error initializing I2C: {e}")
    print("Ensure I2C is enabled on your Raspberry Pi (sudo raspi-config).")
    exit(1)

try:
    tca = adafruit_tca9548a.TCA9548A(i2c)
except ValueError as e:
    print(f"Error initializing TCA9548A multiplexer: {e}")
    print(f"Is the multiplexer connected and address correct (default 0x70)?")
    # You can check connected I2C devices with `i2cdetect -y 1`
    exit(1)


# --- Initialize Sensors ---
sensor_configs = []
initialized_sensor_count = 0
print(f"Attempting to initialize up to {NUM_SENSORS} TLV493D sensor(s)...")

for i in range(NUM_SENSORS):
    sensor_id_str = f"Sensor_{i}" # e.g., Sensor_0, Sensor_1
    sensor_obj = None
    try:
        print(f"  Initializing sensor for TCA channel {i} (to be ID'd as '{sensor_id_str}')...")

        sensor_obj = adafruit_tlv493d.TLV493D(tca[i])
        initialized_sensor_count += 1
        print(f"  Sensor on channel {i} ('{sensor_id_str}') initialized successfully.")

        # Test read
        mag_x, mag_y, mag_z = sensor_obj.magnetic
        print(f"    Initial reading '{sensor_id_str}': X={mag_x:.2f} Y={mag_y:.2f} Z={mag_z:.2f} uT")

    except ValueError as e:
        print(f"  Error initializing sensor on TCA channel {i} ('{sensor_id_str}'): {e}")
        print(f"  Data for '{sensor_id_str}' will be sent as 0.0.")

    except Exception as e:
        print(f"  An unexpected error occurred initializing sensor on TCA channel {i} ('{sensor_id_str}'): {e}")
        print(f"  Data for '{sensor_id_str}' will be sent as 0.0.")
    
    # Store the intended ID string and the object
    sensor_configs.append({'id_str': sensor_id_str, 'obj': sensor_obj, 'channel': i})

if initialized_sensor_count == 0 and NUM_SENSORS > 0:
    print("\nWarning: No sensors were successfully initialized. Will send 0s for all.")
elif initialized_sensor_count < NUM_SENSORS :
    print(f"\nSuccessfully initialized {initialized_sensor_count} out of {NUM_SENSORS} configured sensor slots.")
    print("Data for uninitialized/failed sensors will be sent as 0.0.")
else:
    print(f"\nSuccessfully initialized all {initialized_sensor_count} configured sensors.")

# --- Initialize UDP Socket ---
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"\nSending UDP data as JSON to {HOST_IP}:{HOST_PORT}")
# Example: {'Sensor': {'Sensor_0': [{'axis': 'x', 'val': 0.0}, ...], ...}}

# --- Calculate delay for target frequency ---
if SEND_FREQUENCY_HZ > 0:
    desired_delay_s = 1.0 / SEND_FREQUENCY_HZ
else:
    desired_delay_s = 0 # Max speed

# --- Main Loop ---
packet_count = 0
start_time = time.monotonic()

try:
    while True:
        loop_start_time = time.monotonic()
        
        # --- Construct the Python dictionary for JSON ---
        payload_dict = {
            "Sensor": {}
        }

        for config in sensor_configs:
            sensor_obj = config['obj']
            sensor_id_str = config['id_str'] # e.g., "Sensor_0"
            
            sensor_data_list = []
            
            mag_x, mag_y, mag_z = 0.0, 0.0, 0.0 # Default to 0.0

            if sensor_obj: # If sensor was initialized successfully
                try:
                    mag_x, mag_y, mag_z = sensor_obj.magnetic
                except OSError as e: # Broad for I2C errors
                    print(f"Error reading {sensor_id_str} on channel {config['channel']}: {e}. Sending 0s.")
                    # Values remain 0.0
                except Exception as e:
                    print(f"Unexpected error reading {sensor_id_str} on channel {config['channel']}: {e}. Sending 0s.")
                    # Values remain 0.0
            # else: Sensor not initialized, values remain 0.0

            # Append axis data in the specified list format
            sensor_data_list.append({"axis": "x", "val": round(mag_x, 3)})
            sensor_data_list.append({"axis": "y", "val": round(mag_y, 3)})
            sensor_data_list.append({"axis": "z", "val": round(mag_z, 3)})
            
            payload_dict["Sensor"][sensor_id_str] = sensor_data_list
        
        # Convert the dictionary to a JSON string
        try:
            udp_payload = json.dumps(payload_dict)
        except TypeError as e:
            print(f"Error serializing data to JSON: {e}")
            print(f"Problematic data: {payload_dict}")
            continue # Skip sending this packet


        udp_socket.sendto(udp_payload.encode('utf-8'), (HOST_IP, HOST_PORT))
        packet_count += 1

        loop_time_taken = time.monotonic() - loop_start_time
        
        if desired_delay_s > 0:
            sleep_duration = desired_delay_s - loop_time_taken
            if sleep_duration > 0:
                time.sleep(sleep_duration)

        if packet_count % 100 == 0 and packet_count > 0: # Print stats every 100 packets
            current_run_time = time.monotonic() - start_time
            if current_run_time > 0:
                actual_freq = packet_count / current_run_time
                print(f"Sent {packet_count} JSON packets. Avg Freq: {actual_freq:.2f} Hz. Last loop: {loop_time_taken*1000:.3f} ms")

except KeyboardInterrupt:
    print("\nProgram interrupted by user. Exiting.")
except Exception as e:
    print(f"An unhandled exception occurred in the main loop: {e}")
finally:
    print("Closing UDP socket.")
    udp_socket.close()
    current_run_time = time.monotonic() - start_time
    if current_run_time > 0 and packet_count > 0:
        actual_freq = packet_count / current_run_time
        print(f"Total packets sent: {packet_count}")
        print(f"Total runtime: {current_run_time:.2f} seconds")
        print(f"Average frequency: {actual_freq:.2f} Hz")
    print("Done.")