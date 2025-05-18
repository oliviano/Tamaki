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

> *TODO:* Add installation commands here.

```bash
# Example placeholder
pip install adafruit-blinka 
pip install adafruit-circuitpython-tlv493d 
pip install adafruit-circuitpython-tca9548a
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

> ⚠️ **Caution:** Only allow passwordless `sudo` for specific, trusted commands to avoid security risks.
