The Teta PAPRA project requires 1 PCBAs for v.7

PaprControlPCB - this is a speed controller that allows for adjusting speed of blower

Note:
A PCB is a bare board.
A PCBA is an assembly of a PCB and OTS (off the shelf) components, which are typically a mix of surface mount and thru-hole components.

PCBA Bring-Up Instructions:

1. Connect power to the board via 2.5mm DC jack(H1) using 12V Nominal (7V min, 14V max) DC power, ideally current limitable. Do not connect to fan output.
   * Note polarity on connector is important, center pin is positive.
   * Insertion length on connector is 8.4mm, so body of mating jack should be at least this length.
   * For use with a bech power supply, a cut-end cable option is [Tensility CA-2185](https://www.digikey.com/en/products/detail/tensility-international-corp/CA-2185/568576) 
   * For a standalone power adapter, consier a [Tri-Mag L6R06H-120 12V/6W supply](https://www.digikey.com/en/products/detail/tri-mag-llc/L6R06H-120/7682617)
2. For adjustable power supply, set initial current limit to ~25mA, which should be sufficient to power up processor and drive LEDs.
3. Turn the potentiomenter/swith (POT1) to ON. 
4. Confirm the power LED (LED5) light up with 12V power.
5. Measure 5V regulator (U1) is outputting 5VDC. This can be inspected with a voltmeter measuring the UDPI header as follows:
   * Pin 2 is GND
   * Pin 3 is +5V
6. At this point, the board is powered and ready for programming via UPDI. Follow the instructions [here.](https://github.com/tetrabiodistributed/PAPRA-PCB/blob/main/README.md)
7. Upon successful completion of firmware installation, confirm the board powers up and the 4 LEDs (LED1 - LED4) light up at boot up in a sequence.
8. For boards with the buzzer installed, confirm the buzzer chirps at bootup.
9. In preparation for testing with a DC blower, power the board using the battery tabs and connecting to a [Milwaukee M12 Red Lithium Battery 48-11-2401](https://www.milwaukeetool.com/Products/Batteries-and-Chargers/M12-Batteries-and-Chargers/48-11-2401) or similar. 
   * WARNING: If the board is not installed in the battery housing, pay careful attention to the polarity
10. Connect DC power to BNC connector (H2)
11. Turn on potentiomenter (POT1) and adjust the fan speed from high to low, which checking the DC blower is working and speed is changing with potentiometer adjustments
