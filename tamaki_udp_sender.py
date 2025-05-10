# SPDX-FileCopyrightText: 2025 Olivier Jean for Artifical Imagination
# SPDX-License-Identifier: MIT

# Adds Commands Function(s)

import time
import board
import socket
import adafruit_tca9548a
import adafruit_tlv493d
import json         # For parsing/creating JSON
import os           # For system commands like reboot/shutdown
import threading    # For running the command listener in a separate thread

# --- Configuration ---
HOST_IP_PC = "192.168.6.51" # IP address of the PC running TouchDesigner (for sensor data)
HOST_PORT_PC = 8000         # Port TouchDesigner is listening on (for sensor data)
NUM_SENSORS = 2             # Max number of TLV493D sensors.
PI_COMMAND_PORT = 8001      # Port the Raspberry Pi will listen on for commands

# Initial send frequency - can be changed by command
# This needs to be global to be changed by the command thread
# We'll use a list or a simple class wrapper for mutable global if needed,
# or just rely on 'global' keyword within functions. For a single value, 'global' is fine.
g_send_frequency_hz = 10.0  # Desired send frequency in Hz. 0 for max speed.
                           # Initialized here, can be changed by UDP command

# Event to signal the command listener thread to stop
g_stop_command_listener = threading.Event()


# --- Initialize I2C and Multiplexer ---
try:
    i2c = board.I2C()
except RuntimeError as e:
    print(f"Error initializing I2C: {e}")
    exit(1)
try:
    tca = adafruit_tca9548a.TCA9548A(i2c)
except Exception as e:
    print(f"Error initializing TCA9548A: {e}")
    exit(1)

# --- Initialize Sensors ---
sensor_configs = []
initialized_sensor_count = 0
print(f"Attempting to initialize up to {NUM_SENSORS} TLV493D sensor(s)...")
for i in range(NUM_SENSORS):
    sensor_id_str = f"Sensor_{i}"
    sensor_obj = None
    try:
        print(f"  Initializing sensor for TCA channel {i} (ID: '{sensor_id_str}')...")
        sensor_obj = adafruit_tlv493d.TLV493D(tca[i])
        initialized_sensor_count += 1
        print(f"  Sensor '{sensor_id_str}' initialized successfully on channel {i}.")
    except Exception as e:
        print(f"  Error initializing sensor '{sensor_id_str}' on TCA channel {i}: {e}")
    sensor_configs.append({'id_str': sensor_id_str, 'obj': sensor_obj, 'channel': i})

if initialized_sensor_count == 0 and NUM_SENSORS > 0:
    print("\nWarning: No sensors were successfully initialized.")
else:
    print(f"\nSuccessfully initialized {initialized_sensor_count}/{NUM_SENSORS} sensor(s).")


# --- UDP Command Listener Function (to be run in a thread) ---
def command_listener():
    global g_send_frequency_hz # Declare we are using the global variable

    listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Allow address reuse to prevent "address already in use" errors on quick restarts
    listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener_socket.bind(("", PI_COMMAND_PORT)) # Listen on all interfaces
        print(f"Command listener started on UDP port {PI_COMMAND_PORT}")
    except OSError as e:
        print(f"ERROR: Could not bind to command port {PI_COMMAND_PORT}: {e}")
        print("Another process might be using this port, or permissions issue.")
        return # Exit thread if cannot bind

    listener_socket.settimeout(1.0) # Timeout for recvfrom to allow checking g_stop_command_listener

    while not g_stop_command_listener.is_set():
        try:
            data, addr = listener_socket.recvfrom(1024) # Buffer size 1024 bytes
            command_str = data.decode('utf-8')
            print(f"Received command from {addr}: {command_str}")

            try:
                command_json = json.loads(command_str)
                action = command_json.get("command")

                if action == "reboot":
                    print("Executing REBOOT command.")
                    listener_socket.sendto("ACK: Rebooting...".encode('utf-8'), addr)
                    os.system("sudo reboot")
                elif action == "shutdown":
                    print("Executing SHUTDOWN command.")
                    listener_socket.sendto("ACK: Shutting down...".encode('utf-8'), addr)
                    os.system("sudo shutdown -h now")
                elif action == "set_frequency":
                    new_freq = command_json.get("hz")
                    if isinstance(new_freq, (int, float)) and new_freq >= 0:
                        g_send_frequency_hz = float(new_freq)
                        print(f"Frequency set to: {g_send_frequency_hz} Hz")
                        listener_socket.sendto(f"ACK: Frequency set to {g_send_frequency_hz} Hz".encode('utf-8'), addr)
                    else:
                        print(f"Invalid frequency value: {new_freq}")
                        listener_socket.sendto(f"NACK: Invalid frequency value '{new_freq}'".encode('utf-8'), addr)
                else:
                    print(f"Unknown command: {action}")
                    listener_socket.sendto(f"NACK: Unknown command '{action}'".encode('utf-8'), addr)

            except json.JSONDecodeError:
                print(f"Invalid JSON received: {command_str}")
                listener_socket.sendto("NACK: Invalid JSON".encode('utf-8'), addr)
            except Exception as e:
                print(f"Error processing command: {e}")
                listener_socket.sendto(f"NACK: Error processing command - {e}".encode('utf-8'), addr)

        except socket.timeout:
            continue # Allows checking g_stop_command_listener periodically
        except Exception as e:
            print(f"Command listener error: {e}")
            time.sleep(1) # Avoid busy-looping on persistent errors

    listener_socket.close()
    print("Command listener stopped.")

# --- Start Command Listener Thread ---
command_thread = threading.Thread(target=command_listener, daemon=True)
# daemon=True means thread will exit when main program exits
command_thread.start()


# --- Initialize UDP Socket for Sensor Data ---
sensor_data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"\nSending sensor data as JSON to {HOST_IP_PC}:{HOST_PORT_PC}")

# --- Main Sensor Loop ---
packet_count = 0
start_time = time.monotonic()
# This will be updated inside the loop based on g_send_frequency_hz
desired_delay_s = 0.0

try:
    while True:
        # Dynamically calculate delay based on global frequency setting
        if g_send_frequency_hz > 0:
            desired_delay_s = 1.0 / g_send_frequency_hz
        else:
            desired_delay_s = 0.0 # Max speed

        loop_start_time = time.monotonic()
        
        payload_dict = {"Sensor": {}}
        for config in sensor_configs:
            sensor_obj = config['obj']
            sensor_id_str = config['id_str']
            sensor_data_list = []
            mag_x, mag_y, mag_z = 0.0, 0.0, 0.0

            if sensor_obj:
                try:
                    mag_x, mag_y, mag_z = sensor_obj.magnetic
                except Exception as e:
                    print(f"Error reading {sensor_id_str} on ch {config['channel']}: {e}")
            
            sensor_data_list.append({"axis": "x", "val": round(mag_x, 3)})
            sensor_data_list.append({"axis": "y", "val": round(mag_y, 3)})
            sensor_data_list.append({"axis": "z", "val": round(mag_z, 3)})
            payload_dict["Sensor"][sensor_id_str] = sensor_data_list
        
        try:
            udp_payload = json.dumps(payload_dict)
            sensor_data_socket.sendto(udp_payload.encode('utf-8'), (HOST_IP_PC, HOST_PORT_PC))
            packet_count += 1
        except TypeError as e:
            print(f"Error serializing sensor data to JSON: {e}")
            continue
        except Exception as e:
            print(f"Error sending sensor data: {e}")


        loop_time_taken = time.monotonic() - loop_start_time
        
        if desired_delay_s > 0:
            sleep_duration = desired_delay_s - loop_time_taken
            if sleep_duration > 0:
                time.sleep(sleep_duration)
        # No sleep if desired_delay_s is 0 (max speed)

        if packet_count % 200 == 0 and packet_count > 0: # Print stats less frequently
            current_run_time = time.monotonic() - start_time
            if current_run_time > 0:
                actual_freq = packet_count / current_run_time
                print(f"Sent {packet_count} sensor packets. Avg Freq: {actual_freq:.2f} Hz (Target: {g_send_frequency_hz if g_send_frequency_hz > 0 else 'Max'} Hz). Last loop: {loop_time_taken*1000:.3f} ms")

except KeyboardInterrupt:
    print("\nProgram interrupted by user. Exiting.")
except Exception as e:
    print(f"An unhandled exception occurred in the main loop: {e}")
finally:
    print("Stopping command listener thread...")
    g_stop_command_listener.set() # Signal the command listener thread to stop
    if command_thread.is_alive():
        command_thread.join(timeout=2.0) # Wait for the thread to finish
        if command_thread.is_alive():
            print("Warning: Command listener thread did not terminate gracefully.")

    print("Closing sensor data UDP socket.")
    sensor_data_socket.close()
    
    current_run_time = time.monotonic() - start_time
    if current_run_time > 0 and packet_count > 0:
        actual_freq = packet_count / current_run_time
        print(f"Total sensor packets sent: {packet_count}")
        print(f"Total runtime: {current_run_time:.2f} seconds")
        print(f"Average sensor frequency: {actual_freq:.2f} Hz")
    print("Done.")