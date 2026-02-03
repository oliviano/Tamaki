# SPDX-FileCopyrightText: 2026 Olivier Jean for PE JON BAXTER
# SPDX-License-Identifier: MIT
# Rotary Encoder version (no TCA9548A)

import time
import board
import socket
import json
import os
import threading
import logging
import configparser

from adafruit_seesaw import digitalio, rotaryio, seesaw

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
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

g_enable_system_commands = False

# Rotary globals
g_i2c = None
g_seesaw = None
g_encoder = None
g_button = None
g_last_position = None
g_button_held = False

# Optional: keep these for status compatibility
NUM_SENSORS = 0
g_initialized_sensor_count = 0


# --- Configuration Loading ---
def load_configuration():
    global HOST_IP_PC, HOST_PORT_PC, PI_COMMAND_PORT
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

        # Reuse your existing frequency setting
        g_send_frequency_hz = config.getfloat('Sensors', 'InitialSendFrequencyHz', fallback=60.0)

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
    logging.info(f"  Initial Send Frequency: {g_send_frequency_hz} Hz")


# --- Rotary Encoder Initialization ---
def initialize_hardware_and_rotary():
    global g_i2c, g_seesaw, g_encoder, g_button
    global g_last_position, g_initialized_sensor_count

    try:
        g_i2c = board.I2C()
    except RuntimeError as e:
        logging.error(f"Error initializing I2C: {e}. Ensure I2C is enabled (sudo raspi-config). Exiting.")
        exit(1)

    try:
        g_seesaw = seesaw.Seesaw(g_i2c, addr=0x36)
    except Exception as e:
        logging.error(f"Error initializing Seesaw rotary encoder at 0x36: {e}. Is it connected? Exiting.")
        exit(1)

    # Optional sanity check (matches Adafruit example)
    try:
        seesaw_product = (g_seesaw.get_version() >> 16) & 0xFFFF
        logging.info(f"Rotary Seesaw product ID: {seesaw_product}")
        if seesaw_product != 4991:
            logging.warning("Unexpected firmware/product ID. (Adafruit rotary typically expects 4991)")
    except Exception as e:
        logging.warning(f"Could not read Seesaw version/product ID: {e}")

    # Button on pin 24 with internal pullup
    try:
        g_seesaw.pin_mode(24, g_seesaw.INPUT_PULLUP)
        g_button = digitalio.DigitalIO(g_seesaw, 24)
    except Exception as e:
        logging.error(f"Error initializing rotary button: {e}")
        exit(1)

    # Encoder
    try:
        g_encoder = rotaryio.IncrementalEncoder(g_seesaw)
        # Initialize last_position
        g_last_position = -g_encoder.position  # negate so clockwise is positive (per your example)
    except Exception as e:
        logging.error(f"Error initializing rotary encoder: {e}")
        exit(1)

    g_initialized_sensor_count = 1
    logging.info("Rotary encoder initialized successfully (I2C direct, no TCA).")


# --- Rotary Reading and JSON Building ---
def read_rotary_and_build_json():
    """
    Sends a compact JSON payload suitable for TouchDesigner.

    Payload example:
    {
      "Rotary": {
        "position": 12,
        "delta": 1,
        "button": 0,
        "button_event": "pressed" | "released" | null
      }
    }
    """
    global g_last_position, g_button_held

    position = 0
    delta = 0
    button_val = 1  # pullup => 1 = not pressed, 0 = pressed
    button_event = None

    try:
        # Negate so clockwise rotation positive
        position = -g_encoder.position
        if g_last_position is None:
            g_last_position = position
        delta = position - g_last_position
        g_last_position = position
    except OSError as e:
        logging.warning(f"I2C error reading encoder position: {e}. Sending last/zeroed values.")
    except Exception as e:
        logging.error(f"Unexpected error reading encoder position: {e}. Sending last/zeroed values.")

    try:
        button_val = 1 if g_button.value else 0  # g_button.value True when not pressed
        # replicate your "pressed/released" logic
        if button_val == 0 and not g_button_held:
            g_button_held = True
            button_event = "pressed"
        elif button_val == 1 and g_button_held:
            g_button_held = False
            button_event = "released"
    except OSError as e:
        logging.warning(f"I2C error reading button: {e}")
    except Exception as e:
        logging.error(f"Unexpected error reading button: {e}")

    payload = {
        "Rotary": {
            "position": int(position),
            "delta": int(delta),
            "button": int(button_val),          # 0 pressed, 1 released
            "button_event": button_event        # "pressed"/"released"/None
        }
    }

    try:
        return json.dumps(payload)
    except TypeError as e:
        logging.error(f"Error serializing rotary data to JSON: {e}")
        logging.debug(f"Problematic data for JSON: {payload}")
        return None


# --- UDP Command Listener Function ---
def command_listener():
    global g_send_frequency_hz, g_frequency_lock, g_enable_system_commands

    listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener_socket.bind(("", PI_COMMAND_PORT))
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
                    if g_enable_system_commands:
                        logging.warning("COMMAND_LISTENER: Executing REBOOT command.")
                        listener_socket.sendto(f"ACK: {CMD_REBOOT} initiated.".encode('utf-8'), addr)
                        os.system("sudo reboot")
                    else:
                        logging.warning(f"COMMAND_LISTENER: {CMD_REBOOT} disabled by configuration.")
                        listener_socket.sendto(f"NACK: {CMD_REBOOT} disabled by configuration.".encode('utf-8'), addr)

                elif action == CMD_SHUTDOWN:
                    if g_enable_system_commands:
                        logging.warning("COMMAND_LISTENER: Executing SHUTDOWN command.")
                        listener_socket.sendto(f"ACK: {CMD_SHUTDOWN} initiated.".encode('utf-8'), addr)
                        os.system("sudo shutdown -h now")
                    else:
                        logging.warning(f"COMMAND_LISTENER: {CMD_SHUTDOWN} disabled by configuration.")
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

                elif action == CMD_GET_STATUS:
                    with g_frequency_lock:
                        current_freq = g_send_frequency_hz
                    status_msg = {
                        "status": "OK",
                        "send_frequency_hz": current_freq,
                        "initialized_devices": g_initialized_sensor_count,
                        "device_type": "seesaw_rotary_encoder"
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
            continue
        except Exception as e:
            logging.error(f"COMMAND_LISTENER: Unexpected error in listener loop: {e}")
            time.sleep(0.1)

    listener_socket.close()
    logging.info("Command listener stopped.")


# --- Main Application ---
def main():
    load_configuration()
    initialize_hardware_and_rotary()

    command_thread = threading.Thread(target=command_listener, name="CmdListenerThread", daemon=True)
    command_thread.start()

    sensor_data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    logging.info(f"Sending rotary data as JSON to {HOST_IP_PC}:{HOST_PORT_PC}")

    packet_count = 0
    start_time = time.monotonic()

    try:
        while not g_stop_command_listener.is_set():
            with g_frequency_lock:
                current_target_freq = g_send_frequency_hz

            desired_delay_s = (1.0 / current_target_freq) if current_target_freq > 0 else 0.0

            loop_start_time = time.monotonic()

            udp_payload_json = read_rotary_and_build_json()
            if udp_payload_json:
                try:
                    sensor_data_socket.sendto(udp_payload_json.encode('utf-8'), (HOST_IP_PC, HOST_PORT_PC))
                    packet_count += 1
                except socket.error as e:
                    logging.error(f"MAIN_LOOP: Socket error sending rotary data: {e}")
                except Exception as e:
                    logging.error(f"MAIN_LOOP: Unexpected error sending rotary data: {e}")

            loop_time_taken = time.monotonic() - loop_start_time

            if desired_delay_s > 0:
                sleep_duration = desired_delay_s - loop_time_taken
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

            if packet_count > 0 and packet_count % (int(current_target_freq * 5) if current_target_freq > 0 else 200) == 0:
                current_run_time = time.monotonic() - start_time
                if current_run_time > 0:
                    actual_freq = packet_count / current_run_time
                    freq_target_str = f"{current_target_freq:.1f} Hz" if current_target_freq > 0 else "Max"
                    logging.info(
                        f"Sent {packet_count} rotary packets. Avg Freq: {actual_freq:.2f} Hz "
                        f"(Target: {freq_target_str}). Last loop: {loop_time_taken*1000:.3f} ms"
                    )

    except KeyboardInterrupt:
        logging.info("MAIN_LOOP: Program interrupted by user. Initiating shutdown.")
    except Exception as e:
        logging.error("MAIN_LOOP: An unhandled exception occurred:", exc_info=True)
    finally:
        logging.info("MAIN_LOOP: Stopping command listener thread...")
        g_stop_command_listener.set()
        if command_thread.is_alive():
            command_thread.join(timeout=2.0)
            if command_thread.is_alive():
                logging.warning("MAIN_LOOP: Command listener thread did not terminate gracefully.")

        logging.info("MAIN_LOOP: Closing UDP socket.")
        sensor_data_socket.close()

        current_run_time = time.monotonic() - start_time
        if current_run_time > 0 and packet_count > 0:
            actual_freq = packet_count / current_run_time
            logging.info(f"Total rotary packets sent: {packet_count}")
            logging.info(f"Total runtime: {current_run_time:.2f} seconds")
            logging.info(f"Average send frequency: {actual_freq:.2f} Hz")

        logging.info("Application finished.")


if __name__ == "__main__":
    main()