import smbus
import time
import RPi.GPIO as GPIO
import subprocess

# Define I2C bus and SCL pin
I2C_BUS = 1
SCL_PIN = 3  # Adjust according to your wiring

# Initialize GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(SCL_PIN, GPIO.OUT)

def toggle_scl(scl_pin, count):
    for _ in range(count):
        GPIO.output(scl_pin, GPIO.HIGH)
        time.sleep(0.1)  # Short delay
        GPIO.output(scl_pin, GPIO.LOW)
        time.sleep(0.1)  # Short delay

def set_scl_to_i2c():
    # Set GPIO3 back to SCL1 using pinctrl
    subprocess.run(["echo", "3", ">", "/sys/class/pinctrl/pinctrl0/pinmux"], shell=True)


def unstick_i2c_bus():
    # Toggle SCL line 8 to 16 times
    toggle_scl(SCL_PIN, 16)

    # Optionally, send a stop condition (not directly possible, but could be simulated)
    # or reset devices if they have a reset pin.
    print("Attempted to unstick the I2C bus.")
    set_scl_to_i2c() # reset pin3 to scl1
    print(" Reset Pin to SCL1 ")

try:
    unstick_i2c_bus()
finally:
    GPIO.cleanup()
