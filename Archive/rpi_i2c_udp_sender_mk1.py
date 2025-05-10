# SPDX-FileCopyrightText: 2025 Olivier Jean for Artifical Imagination
# SPDX-License-Identifier: MIT

import time
import board
import socket
import adafruit_tca9548a
import adafruit_tlv493d

# --- Configuration ---
HOST_IP = "192.168.1.101"  # IP address of the PC running TouchDesigner
HOST_PORT = 8000          # Port TouchDesigner is listening on
NUM_SENSORS = 2           # Number of TLV493D sensors connected to the TCA9548A
                          # (Ensure they are on channels 0, 1, ..., NUM_SENSORS-1)
SEND_FREQUENCY_HZ = 0     # Desired send frequency in Hz. 0 for max speed.
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
sensors = []
print(f"Attempting to initialize {NUM_SENSORS} TLV493D sensor(s)...")
for i in range(NUM_SENSORS):
    try:
        print(f"  Initializing sensor on TCA channel {i}...")
        # Each tca[i] is an I2C-like object for that specific channel
        sensor_on_channel = adafruit_tlv493d.TLV493D(tca[i])
        sensors.append(sensor_on_channel)
        print(f"  Sensor {i} initialized successfully on channel {i}.")
        # Test read
        mag_x, mag_y, mag_z = sensor_on_channel.magnetic
        print(f"    Initial reading Sensor {i}: X={mag_x:.2f} Y={mag_y:.2f} Z={mag_z:.2f} uT")

    except ValueError as e:
        # This can happen if no device responds on that channel's I2C address
        print(f"  Error initializing sensor on TCA channel {i}: {e}")
        print(f"  Ensure a TLV493D sensor is connected to channel {i} of the TCA9548A.")
        print(f"  Skipping sensor on channel {i}.")
    except Exception as e:
        print(f"  An unexpected error occurred initializing sensor on TCA channel {i}: {e}")
        print(f"  Skipping sensor on channel {i}.")

if not sensors:
    print("No sensors were successfully initialized. Exiting.")
    exit(1)

print(f"\nSuccessfully initialized {len(sensors)} out of {NUM_SENSORS} configured sensors.")

# --- Initialize UDP Socket ---
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"Sending UDP data to {HOST_IP}:{HOST_PORT}")

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
        
        message_parts = [] # To build the consolidated UDP message

        for i, sensor in enumerate(sensors):
            try:
                # The sensor object 'sensor' was initialized with tca[original_channel_index]
                # If sensors were skipped during init, 'i' here is the index in the 'sensors' list,
                # not necessarily the TCA channel. We need a way to map back or store original channel.
                # For simplicity, let's assume sensors are indexed 0 to N-1 corresponding to channels.
                # If sensors were skipped, this 'i' might not match the intended physical sensor.
                # A better approach would be to store (channel_idx, sensor_obj) tuples if skipping is common.
                # For now, we assume `sensors[i]` corresponds to `tca[i]` conceptually.

                mag_x, mag_y, mag_z = sensor.magnetic

                # Add data for this sensor to our message list
                # Using a unique name for each data point makes parsing easy in TouchDesigner
                message_parts.append(f"sensor{i}_x {mag_x:.3f}") # sensor ID corresponds to its index in the list
                message_parts.append(f"sensor{i}_y {mag_y:.3f}")
                message_parts.append(f"sensor{i}_z {mag_z:.3f}")

            except OSError as e:
                print(f"Error reading sensor {i}: {e}. I2C communication issue?")
                # Optionally, send placeholder values or skip this sensor for this cycle
                message_parts.append(f"sensor{i}_x 0.0")
                message_parts.append(f"sensor{i}_y 0.0")
                message_parts.append(f"sensor{i}_z 0.0")
            except Exception as e:
                print(f"Unexpected error reading sensor {i}: {e}")
                message_parts.append(f"sensor{i}_x 0.0")
                message_parts.append(f"sensor{i}_y 0.0")
                message_parts.append(f"sensor{i}_z 0.0")


        if message_parts:
            # Join all parts into a single string, separated by newlines
            udp_payload = "\n".join(message_parts)
            udp_socket.sendto(udp_payload.encode('utf-8'), (HOST_IP, HOST_PORT))
            packet_count += 1

        # Calculate time taken for this loop iteration
        loop_time_taken = time.monotonic() - loop_start_time
        
        # Optional: Control send frequency
        if desired_delay_s > 0:
            sleep_duration = desired_delay_s - loop_time_taken
            if sleep_duration > 0:
                time.sleep(sleep_duration)
        # elif desired_delay_s == 0 and loop_time_taken < 0.0001: # If running very fast, yield a tiny bit
            # time.sleep(0) # Yield thread, effectively ~1us or more depending on OS

        # Print performance stats occasionally (e.g., every 100 packets or every few seconds)
        if packet_count % 100 == 0 and packet_count > 0:
            current_run_time = time.monotonic() - start_time
            if current_run_time > 0:
                actual_freq = packet_count / current_run_time
                print(f"Sent {packet_count} packets. Avg Freq: {actual_freq:.2f} Hz. Last loop: {loop_time_taken*1000:.2f} ms")


except KeyboardInterrupt:
    print("\nProgram interrupted by user. Exiting.")
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