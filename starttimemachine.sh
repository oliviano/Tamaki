#!/bin/bash

# This will run the Python script in the virtualenv, inside the 'tamaki' screen
# This assume sudoers has been modified.
screen -S tamaki -dm bash -c "source env/bin/activate && python3 timemachine_udp_sender.py"