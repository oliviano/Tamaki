# SPDX-FileCopyrightText: 2026 Olivier Jean for PE JON BAXTER
# SPDX-License-Identifier: MIT
# Rotary Encoder version (no TCA9548A) - SEND ON CHANGE

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

# last-known states (for change detection)
g_last_position = None
g_last_button_val = 1  # pullup => 1 = not pressed, 0 = pressed
g_button_held = False

# status compatibility
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

        # Reuse your existing frequency setting as POLL frequency now
        g_send_frequency_hz = config.getfloat('Sensors', 'InitialSendFrequencyHz', fallback=120.0)

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
    logging.info(f"  Poll Frequency: {g_send_frequency_hz} Hz")


# --- Rotary Encoder Initialization ---
def initialize_hardware_and_rotary():
    global g_i2c, g_seesaw, g_encoder, g_button
    global g_last_position, g_last_button_val, g_initialized_sensor_count

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

    # Optional sanity check
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
        g_last_position = -g_encoder.position  # negate so clockwise is positive
    except Exception as e:
        logging.error(f"Error initializing rotary encoder: {e}")
        exit(1)

    # Initial button state
    try:
        g_last_button_val = 1 if g_button.value else 0
    except Exception:
        g_last_button_val = 1

    g_initialized_sensor_count = 1
    logging.info("Rotary encoder initialized successfully (I2C direct, no TCA).")


# --- Rotary Reading (Change Detect) + JSON Building ---
def read_rotary_change_event():
    """
    Returns:
      (payload_json_str or None, changed_bool)

    changed_bool is True if either:
      - position changed
      - button edge occurred (pressed/released)
    """
    global g_last_position, g_last_button_val, g_button_held

    position = g_last_position if g_last_position is not None else 0
    delta = 0
    button_val = g_last_button_val
    button_event = None

    changed = False

    # Read encoder position
    try:
        position = -g_encoder.position
        if g_last_position is None:
            g_last_position = position

        delta = position - g_last_position
        if delta != 0:
            changed = True

        g_last_position = position

    except OSError as e:
        logging.warning(f"I2C error reading encoder position: {e}")
    except Exception as e:
        logging.error(f"Unexpected error reading encoder position: {e}")

    # Read button + edge detect
    try:
        button_val = 1 if g_button.value else 0  # 0 pressed, 1 released

        # edge detect -> set button_event
        if button_val == 0 and not g_button_held:
            g_button_held = True
            button_event = "pressed"
            changed = True
        elif button_val == 1 and g_button_held:
            g_button_held = False
            button_event = "released"
            changed = True

        g_last_button_val = button_val

    except OSError as e:
        logging.warning(f"I2C error reading button: {e}")
    except Exception as e:
        logging.error(f"Unexpected error reading button: {e}")

    if not changed:
        return None, False

    payload = {
        "Rotary": {
            "position": int(position),
            "delta": int(delta),
            "button": int(button_val),      # 0 pressed, 1 released
            "button_event": button_event    # "pressed"/"released"/None
        }
    }

    try:
        return json.dumps(payload), True
    except TypeError as e:
        logging.error(f"Error serializing rotary data to JSON: {e}")
        logging.debug(f"Problematic data for JSON: {payload}")
        return None, False


# --- UDP Command Listener Function ---
def command_listener():
    global g_send_frequency_hz, g_enable_system_commands

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
                        listener_socket.sendto(f"NACK: {CMD_REBOOT} disabled by configuration.".encode('utf-8'), addr)

                elif action == CMD_SHUTDOWN:
                    if g_enable_system_commands:
                        logging.warning("COMMAND_LISTENER: Executing SHUTDOWN command.")
                        listener_socket.sendto(f"ACK: {CMD_SHUTDOWN} initiated.".encode('utf-8'), addr)
                        os.system("sudo shutdown -h now")
                    else:
                        listener_socket.sendto(f"NACK: {CMD_SHUTDOWN} disabled by configuration.".encode('utf-8'), addr)

                elif action == CMD_SET_FREQUENCY:
                    new_freq_val = command_json.get("hz")
                    if isinstance(new_freq_val, (int, float)) and new_freq_val >= 0:
                        with g_frequency_lock:
                            g_send_frequency_hz = float(new_freq_val)
                        logging.info(f"COMMAND_LISTENER: Poll frequency set to: {g_send_frequency_hz} Hz")
                        listener_socket.sendto(f"ACK: Frequency set to {g_send_frequency_hz} Hz".encode('utf-8'), addr)
                    else:
                        listener_socket.sendto(f"NACK: Invalid frequency value '{new_freq_val}'".encode('utf-8'), addr)

                elif action == CMD_GET_STATUS:
                    with g_frequency_lock:
                        current_freq = g_send_frequency_hz
                    status_msg = {
                        "status": "OK",
                        "poll_frequency_hz": current_freq,
                        "initialized_devices": g_initialized_sensor_count,
                        "device_type": "seesaw_rotary_encoder",
                        "last_position": g_last_position,
                        "button": g_last_button_val
                    }
                    listener_socket.sendto(json.dumps(status_msg).encode('utf-8'), addr)

                else:
                    listener_socket.sendto(f"NACK: Unknown command '{action}'".encode('utf-8'), addr)

            except json.JSONDecodeError:
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

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    logging.info(f"Sending rotary data (on change) as JSON to {HOST_IP_PC}:{HOST_PORT_PC}")

    sent_count = 0
    start_time = time.monotonic()

    # OPTIONAL keepalive (uncomment if you want a heartbeat even when idle)
    # KEEPALIVE_SECONDS = 1.0
    # last_keepalive = time.monotonic()

    try:
        while not g_stop_command_listener.is_set():
            with g_frequency_lock:
                current_poll_hz = g_send_frequency_hz

            desired_delay_s = (1.0 / current_poll_hz) if current_poll_hz > 0 else 0.0
            loop_start = time.monotonic()

            payload_json, changed = read_rotary_change_event()

            if changed and payload_json:
                try:
                    udp_socket.sendto(payload_json.encode('utf-8'), (HOST_IP_PC, HOST_PORT_PC))
                    sent_count += 1
                except Exception as e:
                    logging.error(f"MAIN_LOOP: Error sending UDP: {e}")

            # OPTIONAL keepalive send (commented out by default)
            # now = time.monotonic()
            # if now - last_keepalive >= KEEPALIVE_SECONDS:
            #     last_keepalive = now
            #     keepalive_payload = json.dumps({"Rotary": {"keepalive": 1}})
            #     udp_socket.sendto(keepalive_payload.encode("utf-8"), (HOST_IP_PC, HOST_PORT_PC))

            loop_time = time.monotonic() - loop_start

            if desired_delay_s > 0:
                sleep_duration = desired_delay_s - loop_time
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

            # Light logging: every ~5 seconds of runtime, report send rate
            if (time.monotonic() - start_time) > 5 and sent_count % 50 == 0 and sent_count > 0:
                elapsed = time.monotonic() - start_time
                logging.info(f"Sent {sent_count} change packets over {elapsed:.1f}s (avg {sent_count/elapsed:.2f} pkt/s)")

    except KeyboardInterrupt:
        logging.info("MAIN_LOOP: Program interrupted by user.")
    except Exception:
        logging.error("MAIN_LOOP: Unhandled exception occurred:", exc_info=True)
    finally:
        logging.info("Shutting down...")
        g_stop_command_listener.set()

        if command_thread.is_alive():
            command_thread.join(timeout=2.0)

        udp_socket.close()
        logging.info("Application finished.")


if __name__ == "__main__":
    main()