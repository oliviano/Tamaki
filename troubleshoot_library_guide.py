'''
Let's try a focused debug print within the TCA9548A_Channel.unlock method:
You'd have to edit the installed library file for this, which is not ideal for long term, but good for debugging.
Find where adafruit_tca9548a.py is installed (e.g., /usr/local/lib/python3.x/dist-packages/adafruit_tca9548a.py).
Modify its unlock method:
'''

    def unlock(self) -> bool:
        print(f"TCA CH UNLOCK: Writing 0x00 to TCA @ {hex(self.tca.address)} from channel {self.channel_switch}") # DEBUG PRINT
        self.tca.i2c.writeto(self.tca.address, b"\x00") # DESELECTS ALL CHANNELS
        return self.tca.i2c.unlock()

'''
Use code with caution.
Python
And maybe in try_lock:
'''
    def try_lock(self) -> bool:
        while not self.tca.i2c.try_lock():
            time.sleep(0)
        print(f"TCA CH LOCK: Selecting channel {self.channel_switch} on TCA @ {hex(self.tca.address)}") # DEBUG PRINT
        self.tca.i2c.writeto(self.tca.address, self.channel_switch)
        return True

'''
Use code with caution.
'''