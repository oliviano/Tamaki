## Notes ##
u: o2d
p: o2d

blueberry

### Autoboot ###
1) Test added to .profile
```
# Run Timemachine
/home/o2d/starttimemachine.sh
```
### Troubleshooting ###

#### BlueBerry ####
- adjusted bdrate to 100khz.
- config.txt
  ```
  dtparam=i2c_arm=on,i2c_baudrate=100000
  ```
