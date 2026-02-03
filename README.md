# TREASURES OF TAMAKI

#### Discover Tamaki Through Interaction
This interactive table projection invites you to explore the Tamaki region by placing special objects onto a digital map. Each object contains a strong earth magnet embedded in its base. Hidden beneath the table, a network of magnetic field sensors detects the presence and position of these objects. When placed on designated locations, they trigger dynamic animations and video content—revealing stories, histories, and hidden layers of the Tamaki landscape.

## Tech Stack

**Sensors:** tlv493d, tca9548a.\
**MicroController:** Raspberry Pi 5.\
**Server:** Windows 11 Pro Workstation, TouchDesigner.

## 🛠️ Raspberry Pi Installation

This project uses Adafruit's Blinka and the following libraries:
- `adafruit-tlv493d`
- `adafruit-tca9548a`

### Install Dependencies

> *TODO:* fnish installation instructions here.

```bash
# Update Pi
sudo apt-get update
sudo apt-get -y upgrade
sudo apt-get install python3-pip
sudo apt install --upgrade python3-setuptools

# Create venv & Assign --system-site-packages
python3 -m venv env --system-site-packages
# activate venv "env"
source env/bin/activate
# install blinka with adafruit script:
cd ~
pip3 install --upgrade adafruit-python-shell
# Downloads blinka script
wget https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/master/raspi-blinka.py 
# Run blinka install script
sudo -E env PATH=$PATH python3 raspi-blinka.py

--> Refer to adafruit page for Raspberry Pi 5 Notes

# Test I2C Ports
ls /dev/i2c* /dev/spi*
# Test with blinkatest.py
# See https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/installing-circuitpython-on-raspberry-pi

# install libraries
# we have to be explicit about our venv / and use direct path to pip3.
sudo env/bin/pip3 install adafruit-circuitpython-tlv493d
sudo env/bin/pip3 install adafruit-circuitpython-tca9548a

# from guide:
sudo pip3 install adafruit-circuitpython-tlv493d
sudo pip3 install adafruit-circuitpython-tca9548a

# other install
sudo apt install screen
sudo apt install btop # optional fancy looking ressource monitor
sudo apt install htop # optional ressource monitor

```
### 🔄 Start the Project (Manual Method)
Activate the virtual environment and start the sender script:
```
source env/bin/activate
sudo env/bin/python3 tamaki_udp_sender.py
```
💡 Recommended: Run inside a screen session (especially when connected via SSH):
```
screen -S tamaki
# Then start your script within this screen
```
### 🚀 Auto Start Script 
Use the included starttamaki.sh script in this repository to start the project.
`./starttamaki.sh`
To check if the script is running ( as it's started inside a screen ), use the following:
```
screen -ls # will show a list of screens,
screen -r tamaki # will re-attached to the screen tamaki ( that is screen name created by starttamaki )
```

### 🔐 Allow Passwordless sudo for Script Execution

To enable features like remote shutdown or reboot, the script must be executed with `sudo`. This section shows how to configure passwordless `sudo` for the specific Python binary.

Edit the `sudoers` file:

```bash
sudo visudo
```

Add the following lines at the end of the file, replacing paths/usernames as needed:

```bash
# Example for user 'o2d'
o2d ALL=(ALL) NOPASSWD: /home/o2d/env/bin/python3

# Example for user 'youruser'
youruser ALL=(ALL) NOPASSWD: /full/path/to/env/bin/python3
```

Remember to make the script executable:
`chmod +x scriptname.sh`

> ⚠️ **Caution:** Only allow passwordless `sudo` for specific, trusted commands to avoid security risks.

## 🛠️ AutoRun (desktop mode ) on Pi Installation

Create the Autostart directory (if it doesn't exist):
`mkdir -p ~/.config/autostart`

Create a new .desktop file:
`nano ~/.config/autostart/SensorSender.desktop`

Edit the following content:
```
[Desktop Entry]
Type=Application
Name=Sensor Sender
Exec=/home/o2d/starttimemachine.sh
Terminal=false
```

Make sure our script startupscript.sh is executable ( chmod +x scriptname.sh)