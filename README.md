# PAPRA-PCB

Notes for programming:
* Make a UPDI Programmer: https://create.arduino.cc/projecthub/john-bradnam/create-your-own-updi-programmer-1e55f1?ref=user&ref_id=466812&offset=6
* Setup Arduino: https://www.hackster.io/john-bradnam/using-the-new-attiny-processors-with-arduino-ide-612185
** ![Arduino Config](https://github.com/tetrabiodistributed/PAPRA-PCB/blob/main/firmware/papracode/ArduinoConfig.PNG)

Please note that there are a number of ATTiny SKUs that are compatible with this PCB and code, please refer to the below table when choosing an appropriate IC.

| Model number   | Confirmed   | Notes                             |
| -------------- | ----------- | --------------------------------- |
| ATtiny204SSN_, | Yes         |Support SerialEvent must be 'no'   |
| ATtiny404SSN_, | Yes         |    	                             |
| ATtiny804SSN_, | No          |                                   |
| ATtiny1604SSN_,| Yes         |    	                             |
| ATtiny214SSN_, | No          |Support SerialEvent must be 'no'   |
| ATtiny414SSN_, | No          |    	                             |
| ATtiny814SSN_, | No          |                                   |
| ATtiny1614SSN_,| No          |    	                             |
