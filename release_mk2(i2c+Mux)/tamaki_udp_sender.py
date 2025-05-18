# SPDX-FileCopyrightText: 2023 Your Name/Org for Adafruit Industries
# SPDX-License-Identifier: MIT

import time
import board
import socket
import adafruit_tca9548a
import adafruit_tlv493d # Make sure this matches the library name
import json
import os
import threading
import logging
import configparser

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO, # Change to logging.DEBUG for more verbose output
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# --- Command Constants ---
CMD_REBOOT = "reboot"
CMD_SHUTDOWN = "shutdown"
CMD_SET_FREQUENCY = "set_frequency"
CMD_GET_STATUS = "get_status"

# --- Global Variables & Shared Objects ---
g_send_frequency_hz = 0.0
g_frequency_lock = threading.Lock()
g_stop_command_listener = threading.Event()
g_sensor_configs_from_file = [] # Stores parsed sensor definitions from config
g_active_sensor_objects = [] # Stores successfully initialized sensor objects and their IDs
g_initialized_sensor_count = 0
g_enable_system_commands = False

# Configuration globals (set by load_configuration)
HOST_IP_PC = "127.0.0.1"
HOST_PORT_PC = 8000
PI_COMMAND_PORT = 8001
# TCA object will be global if at least one TCA sensor is defined
tca = None
i2c = None


# --- Configuration Loading ---
def load_configuration():
    global HOST_IP_PC, HOST_PORT_PC, PI_COMMAND_PORT
    global g_send_frequency_hz, g_enable_system_commands, g_sensor_configs_from_file
    
    # Get the absolute path of the directory where the script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Construct the full path to the config.ini file
    config_file_path = os.path.join(script_dir, 'config.ini')
    
    config = configparser.ConfigParser()

    if not os.path.exists(config_file_path):
        logging.error(f"Configuration file '{config_file_path}' not found. Exiting.")
        exit(1)
    
    try:
        config.read(config_file_path)

        HOST_IP_PC = config.get('Network', 'HostIPPC', fallback='127.0.0.1')
        HOST_PORT_PC = config.getint('Network', 'HostPortPC', fallback=8000)
        PI_COMMAND_PORT = config.getint('Network', 'PiCommandPort', fallback=8001)
        
        g_send_frequency_hz = config.getfloat('SensorsGeneral', 'InitialSendFrequencyHz', fallback=0.0)
        active_sensor_ids_str = config.get('SensorsGeneral', 'ActiveSensors', fallback='')
        active_sensor_ids = [s.strip() for s in active_sensor_ids_str.split(',') if s.strip()]

        g_enable_system_commands = config.getboolean('System', 'EnableSystemCommands', fallback=False)
        logging.info(f"System commands (reboot/shutdown) enabled: {g_enable_system_commands}")

        # Parse individual sensor definitions
        for sensor_id in active_sensor_ids:
            if not config.has_section(sensor_id):
                logging.warning(f"Sensor section '[{sensor_id}]' listed in ActiveSensors not found in config. Skipping.")
                continue
            
            sensor_def = {'id_str': sensor_id} # Use section name as id_str
            sensor_def['type'] = config.get(sensor_id, 'type', fallback='').lower()
            sensor_def['name'] = config.get(sensor_id, 'name', fallback=sensor_id) # Default name to id_str
            
            if sensor_def['type'] == 'direct_i2c':
                addr_str = config.get(sensor_id, 'address', fallback=None)
                sensor_def['address'] = int(addr_str, 0) if addr_str else None # int(x,0) handles 0x, 0o, decimal
            elif sensor_def['type'] == 'tca9548a':
                if not config.has_option(sensor_id, 'tca_channel'):
                    logging.error(f"Sensor '{sensor_id}' is type 'tca9548a' but 'tca_channel' is missing. Skipping.")
                    continue
                sensor_def['tca_channel'] = config.getint(sensor_id, 'tca_channel')
                addr_str = config.get(sensor_id, 'address', fallback=None)
                sensor_def['address'] = int(addr_str, 0) if addr_str else None
            else:
                logging.error(f"Unknown sensor type '{sensor_def['type']}' for sensor '{sensor_id}'. Skipping.")
                continue
            g_sensor_configs_from_file.append(sensor_def)

    except (configparser.Error) as e:
        logging.error(f"Error parsing configuration file '{config_file_path}': {e}. Exiting.")
        exit(1)
    except ValueError as e: # For getint/getfloat errors
        logging.error(f"Configuration error: Invalid value type in '{config_file_path}': {e}. Exiting.")
        exit(1)
    
    if not g_sensor_configs_from_file:
        logging.warning("No active sensors configured or parsed correctly.")

    logging.info("Configuration loaded successfully.")
    logging.info(f"  Target PC IP: {HOST_IP_PC}, Port: {HOST_PORT_PC}")
    logging.info(f"  Pi Command Port: {PI_COMMAND_PORT}")
    logging.info(f"  Initial Send Frequency: {g_send_frequency_hz} Hz")
    logging.info(f"  Parsed {len(g_sensor_configs_from_file)} active sensor configurations.")

# --- Sensor Initialization ---
def initialize_hardware_and_sensors():
    global i2c, tca, g_active_sensor_objects, g_initialized_sensor_count

    try:
        i2c = board.I2C() # Initialize base I2C bus
        logging.info("Base I2C bus initialized.")
    except RuntimeError as e:
        logging.error(f"Error initializing base I2C: {e}. Ensure I2C is enabled (sudo raspi-config). Exiting.")
        exit(1)
    
    # Initialize TCA9548A only if at least one sensor uses it
    needs_tca = any(s_def['type'] == 'tca9548a' for s_def in g_sensor_configs_from_file)
    if needs_tca:
        try:
            tca = adafruit_tca9548a.TCA9548A(i2c)
            logging.info("TCA9548A multiplexer initialized.")
        except Exception as e:
            logging.error(f"Error initializing TCA9548A multiplexer: {e}. Is it connected? Check wiring. Some sensors may fail.")
            # Continue, sensors requiring TCA might fail gracefully later

    logging.info(f"Attempting to initialize configured active sensors...")
    for sensor_def in g_sensor_configs_from_file:
        sensor_id_str = sensor_def['id_str']
        sensor_type = sensor_def['type']
        friendly_name = sensor_def['name']
        sensor_obj = None
        i2c_interface_for_sensor = None
        address_arg = {} # For passing address to TLV493D constructor if specified

        if sensor_def.get('address') is not None:
            address_arg['address'] = sensor_def['address']
            logging.debug(f"  Sensor '{friendly_name}' ({sensor_id_str}) will use custom address: {hex(sensor_def['address'])}")


        logging.info(f"  Initializing '{friendly_name}' ({sensor_id_str}), type: {sensor_type}...")

        try:
            if sensor_type == 'direct_i2c':
                i2c_interface_for_sensor = i2c
                sensor_obj = adafruit_tlv493d.TLV493D(i2c_interface_for_sensor, **address_arg)
            
            elif sensor_type == 'tca9548a':
                if tca is None:
                    logging.error(f"    Cannot initialize '{friendly_name}' ({sensor_id_str}): TCA9548A multiplexer failed to initialize.")
                    continue # Skip this sensor
                channel = sensor_def['tca_channel']
                if not (0 <= channel <= 7): # TCA9548A has 8 channels (0-7)
                    logging.error(f"    Invalid TCA channel {channel} for '{friendly_name}' ({sensor_id_str}). Skipping.")
                    continue
                i2c_interface_for_sensor = tca[channel]
                sensor_obj = adafruit_tlv493d.TLV493D(i2c_interface_for_sensor, **address_arg)
            
            # If we reach here, sensor_obj should be valid
            g_active_sensor_objects.append({'id_str': sensor_id_str, 'name': friendly_name, 'obj': sensor_obj, 'original_def': sensor_def})
            g_initialized_sensor_count += 1
            logging.info(f"    Successfully initialized '{friendly_name}' ({sensor_id_str}).")

        except ValueError as e: 
            logging.warning(f"    Could not initialize '{friendly_name}' ({sensor_id_str}): {e} (Often means sensor not found at address).")
        except Exception as e:
            logging.error(f"    Unexpected error initializing '{friendly_name}' ({sensor_id_str}): {e}", exc_info=logging.getLogger().level == logging.DEBUG)
        
    if g_initialized_sensor_count == 0 and g_sensor_configs_from_file:
        logging.warning("No active sensors were successfully initialized. Will send empty 'Sensor' dict or 0s if placeholders are kept.")
    else:
        logging.info(f"Successfully initialized {g_initialized_sensor_count}/{len(g_sensor_configs_from_file)} configured active sensor(s).")


# --- Sensor Reading and JSON Building ---
def read_sensors_and_build_json():
    payload_dict = {"Sensor": {}} # Ensure "Sensor" key always exists
    
    for active_sensor_info in g_active_sensor_objects:
        sensor_obj = active_sensor_info['obj']
        sensor_id_str = active_sensor_info['id_str'] # This is the key for the JSON
        friendly_name = active_sensor_info['name']
        
        sensor_data_list = []
        mag_x, mag_y, mag_z = 0.0, 0.0, 0.0

        if sensor_obj: # Should always be true if it's in g_active_sensor_objects
            try:
                mag_x, mag_y, mag_z = sensor_obj.magnetic
            except OSError as e:
                logging.warning(f"I2C Error reading '{friendly_name}' ({sensor_id_str}): {e}. Sending 0s for this cycle.")
            except Exception as e:
                logging.error(f"Unexpected error reading '{friendly_name}' ({sensor_id_str}): {e}. Sending 0s.", exc_info=logging.getLogger().level == logging.DEBUG)
        
        sensor_data_list.append({"axis": "x", "val": round(mag_x, 3)})
        sensor_data_list.append({"axis": "y", "val": round(mag_y, 3)})
        sensor_data_list.append({"axis": "z", "val": round(mag_z, 3)})
        payload_dict["Sensor"][sensor_id_str] = sensor_data_list
    
    # If you want to include placeholders for sensors defined in config but FAILED to init:
    # You'd iterate g_sensor_configs_from_file and if an id_str is not in payload_dict["Sensor"], add it with 0s.
    # For now, only successfully initialized sensors are included.

    try:
        return json.dumps(payload_dict)
    except TypeError as e:
        logging.error(f"Error serializing sensor data to JSON: {e}")
        logging.debug(f"Problematic data for JSON: {payload_dict}")
        return None

# --- UDP Command Listener Function (largely unchanged, ensure logging uses new format) ---
def command_listener():
    global g_send_frequency_hz, g_frequency_lock, g_enable_system_commands
    # ... (rest of command_listener is mostly the same as before, ensure logging is updated) ...
    # For CMD_GET_STATUS, NUM_SENSORS should reflect number of *active configured* sensors
    # num_active_configured_sensors = len(g_sensor_configs_from_file)

    listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener_socket.bind(("", PI_COMMAND_PORT)) # Listen on all interfaces
        logging.info(f"Command listener started on UDP port {PI_COMMAND_PORT}")
    except OSError as e:
        logging.error(f"COMMAND_LISTENER: Could not bind to command port {PI_COMMAND_PORT}: {e}. Thread exiting.")
        return

    listener_socket.settimeout(1.0) 

    while not g_stop_command_listener.is_set():
        try:
            data, addr = listener_socket.recvfrom(1024)
            command_str = data.decode('utf-8')
            logging.info(f"COMMAND_LISTENER: Received command from {addr}: {command_str}")

            try:
                command_json = json.loads(command_str)
                action = command_json.get("command")

                if action == CMD_REBOOT:
                    # ... (same as before, check g_enable_system_commands)
                    if g_enable_system_commands:
                        logging.warning("COMMAND_LISTENER: Executing REBOOT command.")
                        listener_socket.sendto(f"ACK: {CMD_REBOOT} initiated.".encode('utf-8'), addr)
                        os.system("sudo reboot") 
                    else:
                        logging.warning(f"COMMAND_LISTENER: {CMD_REBOOT} command received but system commands are disabled in config.")
                        listener_socket.sendto(f"NACK: {CMD_REBOOT} disabled by configuration.".encode('utf-8'), addr)
                
                elif action == CMD_SHUTDOWN:
                    # ... (same as before, check g_enable_system_commands)
                    if g_enable_system_commands:
                        logging.warning("COMMAND_LISTENER: Executing SHUTDOWN command.")
                        listener_socket.sendto(f"ACK: {CMD_SHUTDOWN} initiated.".encode('utf-8'), addr)
                        os.system("sudo shutdown -h now") 
                    else:
                        logging.warning(f"COMMAND_LISTENER: {CMD_SHUTDOWN} command received but system commands are disabled in config.")
                        listener_socket.sendto(f"NACK: {CMD_SHUTDOWN} disabled by configuration.".encode('utf-8'), addr)

                elif action == CMD_SET_FREQUENCY:
                    # ... (same as before)
                    new_freq_val = command_json.get("hz")
                    if isinstance(new_freq_val, (int, float)) and new_freq_val >= 0:
                        with g_frequency_lock:
                            g_send_frequency_hz = float(new_freq_val)
                        logging.info(f"COMMAND_LISTENER: Send frequency set to: {g_send_frequency_hz} Hz")
                        listener_socket.sendto(f"ACK: Frequency set to {g_send_frequency_hz} Hz".encode('utf-8'), addr)
                    else:
                        logging.warning(f"COMMAND_LISTENER: Invalid frequency value received: {new_freq_val}")
                        listener_socket.sendto(f"NACK: Invalid frequency value '{new_freq_val}'".encode('utf-8'), addr)
                
                elif action == CMD_GET_STATUS:
                    with g_frequency_lock:
                        current_freq = g_send_frequency_hz
                    num_active_configured = len(g_sensor_configs_from_file)
                    status_msg = {
                        "status": "OK",
                        "send_frequency_hz": current_freq,
                        "initialized_sensors": g_initialized_sensor_count,
                        "active_configured_sensors": num_active_configured
                    }
                    listener_socket.sendto(json.dumps(status_msg).encode('utf-8'), addr)

                else:
                    logging.warning(f"COMMAND_LISTENER: Unknown command received: {action}")
                    listener_socket.sendto(f"NACK: Unknown command '{action}'".encode('utf-8'), addr)

            except json.JSONDecodeError:
                logging.error(f"COMMAND_LISTENER: Invalid JSON received from {addr}: {command_str}")
                listener_socket.sendto("NACK: Invalid JSON format".encode('utf-8'), addr)
            except Exception as e:
                logging.error(f"COMMAND_LISTENER: Error processing command from {addr}: {e}", exc_info=logging.getLogger().level == logging.DEBUG)
                listener_socket.sendto(f"NACK: Error processing command - {e}".encode('utf-8'), addr)

        except socket.timeout:
            continue 
        except Exception as e:
            logging.error(f"COMMAND_LISTENER: Unexpected error in listener loop: {e}", exc_info=logging.getLogger().level == logging.DEBUG)
            time.sleep(0.1) 

    listener_socket.close()
    logging.info("Command listener stopped.")


# --- Main Application ---
def main():
    load_configuration() # Load config first
    initialize_hardware_and_sensors() # Then initialize hardware based on config

    if not g_active_sensor_objects and not g_sensor_configs_from_file:
        logging.warning("No sensors configured or initialized. The application might not send useful data.")
    elif not g_active_sensor_objects and g_sensor_configs_from_file:
        logging.warning("Sensors were configured but none initialized successfully. Check connections and sensor definitions in config.ini.")


    command_thread = threading.Thread(target=command_listener, name="CmdListenerThread", daemon=True)
    command_thread.start()

    sensor_data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    logging.info(f"Sending sensor data as JSON to {HOST_IP_PC}:{HOST_PORT_PC}")

    packet_count = 0
    start_time = time.monotonic()
    
    try:
        while not g_stop_command_listener.is_set():
            with g_frequency_lock:
                current_target_freq = g_send_frequency_hz
            
            if current_target_freq > 0:
                desired_delay_s = 1.0 / current_target_freq
            else:
                desired_delay_s = 0.0

            loop_start_time = time.monotonic()
            
            udp_payload_json = read_sensors_and_build_json()
            
            if udp_payload_json:
                try:
                    sensor_data_socket.sendto(udp_payload_json.encode('utf-8'), (HOST_IP_PC, HOST_PORT_PC))
                    packet_count += 1
                except socket.error as e:
                    logging.error(f"MAIN_LOOP: Socket error sending sensor data: {e}")
                except Exception as e:
                    logging.error(f"MAIN_LOOP: Unexpected error sending sensor data: {e}", exc_info=logging.getLogger().level == logging.DEBUG)
            
            loop_time_taken = time.monotonic() - loop_start_time
            
            if desired_delay_s > 0:
                sleep_duration = desired_delay_s - loop_time_taken
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

            # Log stats periodically
            log_interval_packets = (int(current_target_freq * 5) if current_target_freq > 0.1 else 200)
            if log_interval_packets < 1: log_interval_packets = 1 # Avoid division by zero or too frequent logging
            if packet_count > 0 and packet_count % log_interval_packets == 0 :
                current_run_time = time.monotonic() - start_time
                if current_run_time > 0:
                    actual_freq = packet_count / current_run_time
                    freq_target_str = f"{current_target_freq:.1f} Hz" if current_target_freq > 0 else "Max"
                    logging.info(f"Sent {packet_count} sensor packets. Avg Freq: {actual_freq:.2f} Hz (Target: {freq_target_str}). Loop: {loop_time_taken*1000:.3f} ms")

    except KeyboardInterrupt:
        logging.info("MAIN_LOOP: Program interrupted by user. Initiating shutdown.")
    except Exception as e:
        logging.error(f"MAIN_LOOP: An unhandled exception occurred: {e}", exc_info=True)
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