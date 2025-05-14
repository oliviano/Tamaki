# SPDX-FileCopyrightText: 2023 Your Name/Org
# SPDX-License-Identifier: MIT

import time
import board
import socket
import adafruit_tca9548a
import adafruit_tlv493d
import json
import logging

# --- Minimal Configuration ---
TARGET_HOST_IP = "192.168.6.51"  # <--- SET YOUR PC's IP ADDRESS
TARGET_HOST_PORT = 8000
SEND_INTERVAL_SECONDS = 0.1  # Send data every 0.1 seconds (10 Hz)

# --- Setup Logging (Basic) ---
logging.basicConfig(
    level=logging.DEBUG, # Use DEBUG to see detailed sensor read attempts
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# --- Global Hardware Objects ---
i2c = None
tca = None
sensor0_direct = None
sensor1_tca_ch0 = None

# --- Initialize Hardware ---
def initialize_sensors_minimal():
    global i2c, tca, sensor0_direct, sensor1_tca_ch0
    logging.info("--- Initializing Hardware (Minimal) ---")

    try:
        i2c = board.I2C()  # Uses board.SCL and board.SDA
        logging.info("I2C bus initialized.")
    except Exception as e:
        logging.error(f"Failed to initialize I2C bus: {e}")
        return False # Indicate failure

    # Initialize Sensor 0 (Direct I2C)
    try:
        logging.info("Attempting to initialize Sensor 0 (Direct I2C)...")
        # Assuming TLV493D default address 0x5E
        sensor0_direct = adafruit_tlv493d.TLV493D(i2c)
        logging.info("Sensor 0 (Direct I2C) initialized successfully.")
        # Test read
        x,y,z = sensor0_direct.magnetic
        logging.debug(f"  Initial read Sensor 0: X={x:.2f} Y={y:.2f} Z={z:.2f}")
    except Exception as e:
        logging.error(f"Failed to initialize Sensor 0 (Direct I2C): {e}")
        # We can choose to continue or exit if a sensor fails
        # For this test, we'll mark it as None and continue

    # Initialize TCA9548A Multiplexer
    try:
        logging.info("Attempting to initialize TCA9548A Multiplexer...")
        tca = adafruit_tca9548a.TCA9548A(i2c)
        logging.info("TCA9548A Multiplexer initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize TCA9548A: {e}")
        # If TCA fails, sensor1 cannot be initialized
        # tca will remain None

    # Initialize Sensor 1 (TCA Channel 0)
    if tca: # Only if TCA was initialized
        try:
            logging.info("Attempting to initialize Sensor 1 (TCA Channel 0)...")
            # Assuming TLV493D default address 0x5E
            sensor1_tca_ch0 = adafruit_tlv493d.TLV493D(tca[0]) # Use channel 0 of the multiplexer
            logging.info("Sensor 1 (TCA Channel 0) initialized successfully.")
            # Test read
            x,y,z = sensor1_tca_ch0.magnetic
            logging.debug(f"  Initial read Sensor 1: X={x:.2f} Y={y:.2f} Z={z:.2f}")
        except Exception as e:
            logging.error(f"Failed to initialize Sensor 1 (TCA Channel 0): {e}")
    else:
        logging.warning("Skipping Sensor 1 initialization because TCA Multiplexer is not available.")
        
    if sensor0_direct or sensor1_tca_ch0:
        return True # At least one sensor is somewhat available
    return False


# --- UDP Sender Function ---
def send_udp_data(udp_socket, data_dict):
    try:
        payload = json.dumps(data_dict)
        udp_socket.sendto(payload.encode('utf-8'), (TARGET_HOST_IP, TARGET_HOST_PORT))
        logging.debug(f"UDP Sent: {payload}")
    except Exception as e:
        logging.error(f"Error sending UDP data: {e}")

# --- Main ---
if __name__ == "__main__":
    if not initialize_sensors_minimal():
        logging.critical("Critical hardware initialization failed. Exiting.")
        exit()

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    logging.info(f"--- Starting Main Loop (Sending to {TARGET_HOST_IP}:{TARGET_HOST_PORT}) ---")

    try:
        while True:
            sensor_data_payload = {"Sensor": {}}
            
            # --- Read Sensor 0 (Direct I2C) ---
            if sensor0_direct:
                logging.debug("Reading Sensor 0 (Direct I2C)...")
                try:
                    s0_x, s0_y, s0_z = sensor0_direct.magnetic
                    sensor_data_payload["Sensor"]["Sensor_0"] = [
                        {"axis": "x", "val": round(s0_x, 3)},
                        {"axis": "y", "val": round(s0_y, 3)},
                        {"axis": "z", "val": round(s0_z, 3)}
                    ]
                    logging.debug(f"  Sensor 0 Data: X={s0_x:.3f}, Y={s0_y:.3f}, Z={s0_z:.3f}")
                except Exception as e:
                    logging.warning(f"  Error reading Sensor 0: {e}")
                    sensor_data_payload["Sensor"]["Sensor_0"] = [{"axis": "x", "val":0.0},{"axis": "y", "val":0.0},{"axis": "z", "val":0.0}] # Placeholder

            # --- Optional DELAY 1 ---
            # time.sleep(0.05) # <--- UNCOMMENT TO TEST DELAY AFTER DIRECT READ

            # --- Read Sensor 1 (TCA Channel 0) ---
            if sensor1_tca_ch0:
                logging.debug("Reading Sensor 1 (TCA Channel 0)...")
                try:
                    s1_x, s1_y, s1_z = sensor1_tca_ch0.magnetic
                    sensor_data_payload["Sensor"]["Sensor_1"] = [
                        {"axis": "x", "val": round(s1_x, 3)},
                        {"axis": "y", "val": round(s1_y, 3)},
                        {"axis": "z", "val": round(s1_z, 3)}
                    ]
                    logging.debug(f"  Sensor 1 Data: X={s1_x:.3f}, Y={s1_y:.3f}, Z={s1_z:.3f}")
                except Exception as e:
                    logging.warning(f"  Error reading Sensor 1: {e}")
                    sensor_data_payload["Sensor"]["Sensor_1"] = [{"axis": "x", "val":0.0},{"axis": "y", "val":0.0},{"axis": "z", "val":0.0}] # Placeholder

            # --- Optional DELAY 2 ---
            # time.sleep(0.05) # <--- UNCOMMENT TO TEST DELAY AFTER TCA READ

            # Send data if any sensor was read
            if sensor_data_payload["Sensor"]:
                send_udp_data(udp_sock, sensor_data_payload)
            
            time.sleep(SEND_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logging.info("Program terminated by user.")
    except Exception as e:
        logging.error(f"Unhandled exception in main loop: {e}", exc_info=True)
    finally:
        logging.info("Closing UDP socket.")
        if udp_sock:
            udp_sock.close()
        # No specific sensor close needed for these libraries
        logging.info("Application finished.")