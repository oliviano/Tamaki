# SPDX-FileCopyrightText: 2025 Olivier Jean for AI / 02D
# SPDX-License-Identifier: MIT
# version 250518 from blackberry ( First Pi )

import time
import board
import socket
import adafruit_tca9548a
import adafruit_tlv493d
import json
import os
import threading
import logging
import configparser

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Output to console
    # Optionally add: logging.FileHandler("rpi_sensor_hub.log")
)

# --- Command Constants ---
CMD_REBOOT = "reboot"
CMD_SHUTDOWN = "shutdown"
CMD_SET_FREQUENCY = "set_frequency"
CMD_GET_STATUS = "get_status" # Example of a new potential command

# --- Global Variables & Shared Objects ---
g_send_frequency_hz = 0.0  # Will be set from config
g_frequency_lock = threading.Lock()
g_stop_command_listener = threading.Event()
g_sensor_configs = [] # To store sensor objects and their IDs
g_initialized_sensor_count = 0
g_enable_system_commands = False # Will be set from config

# --- Configuration Loading ---
def load_configuration():
    global HOST_IP_PC, HOST_PORT_PC, PI_COMMAND_PORT, NUM_SENSORS
    global g_send_frequency_hz, g_enable_system_commands

    config = configparser.ConfigParser()
    config_file_path = 'config.ini'

    if not os.path.exists(config_file_path):
        logging.error(f"Configuration file '{config_file_path}' not found. Exiting.")
        exit(1)
    
    try:
        config.read(config_file_path)

        HOST_IP_PC = config.get('Network', 'HostIPPC', fallback='127.0.0.1')
        HOST_PORT_PC = config.getint('Network', 'HostPortPC', fallback=8000)
        PI_COMMAND_PORT = config.getint('Network', 'PiCommandPort', fallback=8001)
        
        NUM_SENSORS = config.getint('Sensors', 'NumSensors', fallback=0)
        g_send_frequency_hz = config.getfloat('Sensors', 'InitialSendFrequencyHz', fallback=0.0)

        g_enable_system_commands = config.getboolean('System', 'EnableSystemCommands', fallback=False)
        logging.info(f"System commands (reboot/shutdown) enabled: {g_enable_system_commands}")

    except (configparser.Error) as e:
        logging.error(f"Error parsing configuration file '{config_file_path}': {e}. Exiting.")
        exit(1)
    except ValueError as e:
        logging.error(f"Configuration error: Invalid value in '{config_file_path}': {e}. Exiting.")
        exit(1)
    
    logging.info("Configuration loaded successfully.")
    logging.info(f"  Target PC IP: {HOST_IP_PC}, Port: {HOST_PORT_PC}")
    logging.info(f"  Pi Command Port: {PI_COMMAND_PORT}")
    logging.info(f"  Number of Sensors: {NUM_SENSORS}")
    logging.info(f"  Initial Send Frequency: {g_send_frequency_hz} Hz")

# --- Sensor Initialization ---
def initialize_hardware_and_sensors():
    global i2c, tca, g_sensor_configs, g_initialized_sensor_count, NUM_SENSORS

    try:
        i2c = board.I2C()
    except RuntimeError as e:
        logging.error(f"Error initializing I2C: {e}. Ensure I2C is enabled (sudo raspi-config). Exiting.")
        exit(1)
    
    try:
        tca = adafruit_tca9548a.TCA9548A(i2c)
    except Exception as e: # Broad exception for TCA init issues (e.g., not found)
        logging.error(f"Error initializing TCA9548A multiplexer: {e}. Is it connected? Exiting.")
        exit(1)

    logging.info(f"Attempting to initialize up to {NUM_SENSORS} TLV493D sensor(s)...")
    for i in range(NUM_SENSORS):
        sensor_id_str = f"Sensor_{i}"
        sensor_obj = None
        try:
            logging.debug(f"  Initializing sensor for TCA channel {i} (ID: '{sensor_id_str}')...")
            sensor_obj = adafruit_tlv493d.TLV493D(tca[i])
            g_initialized_sensor_count += 1
            logging.info(f"  Sensor '{sensor_id_str}' initialized successfully on channel {i}.")
        except ValueError as e: # Often due to no device on I2C address
            logging.warning(f"  Could not initialize sensor '{sensor_id_str}' on TCA channel {i}: {e}")
        except Exception as e:
            logging.error(f"  Unexpected error initializing sensor '{sensor_id_str}' on TCA channel {i}: {e}")
        
        g_sensor_configs.append({'id_str': sensor_id_str, 'obj': sensor_obj, 'channel': i})

    if g_initialized_sensor_count == 0 and NUM_SENSORS > 0:
        logging.warning("No sensors were successfully initialized. Will send 0s for all.")
    else:
        logging.info(f"Successfully initialized {g_initialized_sensor_count}/{NUM_SENSORS} sensor(s).")

# --- Sensor Reading and JSON Building ---
def read_sensors_and_build_json():
    payload_dict = {"Sensor": {}}
    for config in g_sensor_configs:
        sensor_obj = config['obj']
        sensor_id_str = config['id_str']
        sensor_data_list = []
        mag_x, mag_y, mag_z = 0.0, 0.0, 0.0 # Default to 0.0

        if sensor_obj:
            try:
                mag_x, mag_y, mag_z = sensor_obj.magnetic
            except OSError as e: # More specific for I2C communication issues
                logging.warning(f"I2C Error reading {sensor_id_str} on ch {config['channel']}: {e}. Sending 0s.")
            except Exception as e:
                logging.error(f"Unexpected error reading {sensor_id_str} on ch {config['channel']}: {e}. Sending 0s.")
        
        sensor_data_list.append({"axis": "x", "val": round(mag_x, 3)})
        sensor_data_list.append({"axis": "y", "val": round(mag_y, 3)})
        sensor_data_list.append({"axis": "z", "val": round(mag_z, 3)})
        payload_dict["Sensor"][sensor_id_str] = sensor_data_list
    
    try:
        return json.dumps(payload_dict)
    except TypeError as e:
        logging.error(f"Error serializing sensor data to JSON: {e}")
        logging.debug(f"Problematic data for JSON: {payload_dict}")
        return None # Indicate failure

# --- UDP Command Listener Function ---
def command_listener():
    global g_send_frequency_hz, g_frequency_lock, g_enable_system_commands

    listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener_socket.bind(("", PI_COMMAND_PORT)) # Listen on all interfaces
        logging.info(f"Command listener started on UDP port {PI_COMMAND_PORT}")
    except OSError as e:
        logging.error(f"COMMAND_LISTENER: Could not bind to command port {PI_COMMAND_PORT}: {e}. Thread exiting.")
        return

    listener_socket.settimeout(1.0) # Timeout to allow checking stop event

    while not g_stop_command_listener.is_set():
        try:
            data, addr = listener_socket.recvfrom(1024)
            command_str = data.decode('utf-8')
            logging.info(f"COMMAND_LISTENER: Received command from {addr}: {command_str}")

            try:
                command_json = json.loads(command_str)
                action = command_json.get("command")

                if action == CMD_REBOOT:
                    if g_enable_system_commands:
                        logging.warning("COMMAND_LISTENER: Executing REBOOT command.")
                        listener_socket.sendto(f"ACK: {CMD_REBOOT} initiated.".encode('utf-8'), addr)
                        os.system("sudo reboot") # Consider security implications
                    else:
                        logging.warning(f"COMMAND_LISTENER: {CMD_REBOOT} command received but system commands are disabled in config.")
                        listener_socket.sendto(f"NACK: {CMD_REBOOT} disabled by configuration.".encode('utf-8'), addr)
                
                elif action == CMD_SHUTDOWN:
                    if g_enable_system_commands:
                        logging.warning("COMMAND_LISTENER: Executing SHUTDOWN command.")
                        listener_socket.sendto(f"ACK: {CMD_SHUTDOWN} initiated.".encode('utf-8'), addr)
                        os.system("sudo shutdown -h now") # Consider security implications
                    else:
                        logging.warning(f"COMMAND_LISTENER: {CMD_SHUTDOWN} command received but system commands are disabled in config.")
                        listener_socket.sendto(f"NACK: {CMD_SHUTDOWN} disabled by configuration.".encode('utf-8'), addr)

                elif action == CMD_SET_FREQUENCY:
                    new_freq_val = command_json.get("hz")
                    if isinstance(new_freq_val, (int, float)) and new_freq_val >= 0:
                        with g_frequency_lock:
                            g_send_frequency_hz = float(new_freq_val)
                        logging.info(f"COMMAND_LISTENER: Send frequency set to: {g_send_frequency_hz} Hz")
                        listener_socket.sendto(f"ACK: Frequency set to {g_send_frequency_hz} Hz".encode('utf-8'), addr)
                    else:
                        logging.warning(f"COMMAND_LISTENER: Invalid frequency value received: {new_freq_val}")
                        listener_socket.sendto(f"NACK: Invalid frequency value '{new_freq_val}'".encode('utf-8'), addr)
                
                elif action == CMD_GET_STATUS: # Example new command
                    with g_frequency_lock:
                        current_freq = g_send_frequency_hz
                    status_msg = {
                        "status": "OK",
                        "send_frequency_hz": current_freq,
                        "initialized_sensors": g_initialized_sensor_count,
                        "total_configured_sensors": NUM_SENSORS
                    }
                    listener_socket.sendto(json.dumps(status_msg).encode('utf-8'), addr)

                else:
                    logging.warning(f"COMMAND_LISTENER: Unknown command received: {action}")
                    listener_socket.sendto(f"NACK: Unknown command '{action}'".encode('utf-8'), addr)

            except json.JSONDecodeError:
                logging.error(f"COMMAND_LISTENER: Invalid JSON received from {addr}: {command_str}")
                listener_socket.sendto("NACK: Invalid JSON format".encode('utf-8'), addr)
            except Exception as e:
                logging.error(f"COMMAND_LISTENER: Error processing command from {addr}: {e}")
                listener_socket.sendto(f"NACK: Error processing command - {e}".encode('utf-8'), addr)

        except socket.timeout:
            continue # Allows checking g_stop_command_listener periodically
        except Exception as e:
            logging.error(f"COMMAND_LISTENER: Unexpected error in listener loop: {e}")
            time.sleep(0.1) # Avoid rapid spamming on persistent errors

    listener_socket.close()
    logging.info("Command listener stopped.")

# --- Main Application ---
def main():
    load_configuration()
    initialize_hardware_and_sensors()

    # Start Command Listener Thread
    command_thread = threading.Thread(target=command_listener, name="CmdListenerThread", daemon=True)
    command_thread.start()

    # Initialize UDP Socket for Sensor Data
    sensor_data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    logging.info(f"Sending sensor data as JSON to {HOST_IP_PC}:{HOST_PORT_PC}")

    packet_count = 0
    start_time = time.monotonic()
    
    try:
        while not g_stop_command_listener.is_set(): # Check stop event for main loop too
            # Dynamically calculate delay based on global frequency setting
            with g_frequency_lock:
                current_target_freq = g_send_frequency_hz
            
            if current_target_freq > 0:
                desired_delay_s = 1.0 / current_target_freq
            else:
                desired_delay_s = 0.0 # Max speed

            loop_start_time = time.monotonic()
            
            udp_payload_json = read_sensors_and_build_json()
            
            if udp_payload_json:
                try:
                    sensor_data_socket.sendto(udp_payload_json.encode('utf-8'), (HOST_IP_PC, HOST_PORT_PC))
                    packet_count += 1
                except socket.error as e: # Catch specific socket errors
                    logging.error(f"MAIN_LOOP: Socket error sending sensor data: {e}")
                except Exception as e:
                    logging.error(f"MAIN_LOOP: Unexpected error sending sensor data: {e}")
            
            loop_time_taken = time.monotonic() - loop_start_time
            
            if desired_delay_s > 0:
                sleep_duration = desired_delay_s - loop_time_taken
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

            if packet_count > 0 and packet_count % (int(current_target_freq * 5) if current_target_freq > 0 else 200) == 0 : # Log roughly every 5s or 200 packets
                current_run_time = time.monotonic() - start_time
                if current_run_time > 0:
                    actual_freq = packet_count / current_run_time
                    freq_target_str = f"{current_target_freq:.1f} Hz" if current_target_freq > 0 else "Max"
                    logging.info(f"Sent {packet_count} sensor packets. Avg Freq: {actual_freq:.2f} Hz (Target: {freq_target_str}). Last loop: {loop_time_taken*1000:.3f} ms")

    except KeyboardInterrupt:
        logging.info("MAIN_LOOP: Program interrupted by user. Initiating shutdown.")
    except Exception as e:
        logging.error(f"MAIN_LOOP: An unhandled exception occurred: {e}", exc_info=True) # exc_info=True prints traceback
    finally:
        logging.info("MAIN_LOOP: Stopping command listener thread...")
        g_stop_command_listener.set() 
        if command_thread.is_alive():
            command_thread.join(timeout=2.0) 
            if command_thread.is_alive():
                logging.warning("MAIN_LOOP: Command listener thread did not terminate gracefully.")

        logging.info("MAIN_LOOP: Closing sensor data UDP socket.")
        sensor_data_socket.close()
        
        current_run_time = time.monotonic() - start_time
        if current_run_time > 0 and packet_count > 0:
            actual_freq = packet_count / current_run_time
            logging.info(f"Total sensor packets sent: {packet_count}")
            logging.info(f"Total runtime: {current_run_time:.2f} seconds")
            logging.info(f"Average sensor frequency: {actual_freq:.2f} Hz")
        logging.info("Application finished.")

if __name__ == "__main__":
    main()