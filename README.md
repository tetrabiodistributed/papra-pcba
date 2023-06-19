# papra-pcba

## PAPRa PCBA - printed circuit board assembly for the PAPRa M12 Controller

## PAPRa PCBA comes in 2 form factors

### Thru Hole Technology

* Part Number A-TET-001113
* Suitable for hand soldering
* Larger form factor
* Easy to assemble, intended for novice 
* BOM parts should be easy to source
* Uses Adafruit QT PY or Seeed Xiao microcontroller board
* Firmware: TBD

### SMT

* Part Number A-TET-001100
* Suitable for mass production
* Smallest form factor
* Machine assembly recommended, very difficult to hand solder
* Lowest BOM cost
* Uses ATTINY 0/1/2-Series 14pin SOIC
* Firmware found here: https://github.com/tetrabiodistributed/papra-pcb-firmware/tree/main/papracode

Notes for programming:
* Make a UPDI Programmer: https://create.arduino.cc/projecthub/john-bradnam/create-your-own-updi-programmer-1e55f1?ref=user&ref_id=466812&offset=6
* The board features a UPDI header on the top left of the PCB (top being the side with the battery connectors) the pins are top to bottom 5V, GND and data. 
* Setup Arduino: https://www.hackster.io/john-bradnam/using-the-new-attiny-processors-with-arduino-ide-612185
* You will need to use the megaTinyCore library by SpenceKonde: https://github.com/SpenceKonde/megaTinyCore

Upload settings can be found in the arduino program. 

Please note that there are a number of ATTiny SKUs that are compatible with this PCB and code, please refer to the below table when choosing an appropriate IC.

| Model number   | Confirmed   | Notes                             |
| -------------- | ----------- | --------------------------------- |
| ATtiny204SSN_, | Yes         | See Below(1)  |
| ATtiny404SSN_, | Yes         |    	                           |
| ATtiny804SSN_, | Yes         |                                   |
| ATtiny1604SSN_,| Yes         |    	                           |
| ATtiny214SSN_, | Yes         | See Below(1)  |
| ATtiny414SSN_, | Yes         |    	                           |
| ATtiny814SSN_, | Yes         |                                   |
| ATtiny1614SSN_,| Yes         |    	                           |
| ATtiny1624SSU, | Yes         |    	                           |

(1)ATtiny 204 and 214 have limited (2K) flash memory for program space, but the firmware can be made to fit by sacraficing the bootup LED sequence.

