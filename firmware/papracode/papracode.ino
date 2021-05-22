/*
  papracode
    - Reads battery voltage and lights up LEDs to mimic M12 battery fuel gauge
    - Reads user pot to control PWM of fan

  PCB is compatible with all 0/1/2-Series 14 pin ATtiny chips
  For chips with 2K flash (ATtiny204 & ATtiny404), the Preprocessor directive must be uncommented
*/
//#define TWOKFLASHCHIP //uncomment line when programming ATtiny204 or ATtiny214
  
// Compile with Arduino 1.8.13 or later.
// Install MegaTinyCore via the Boards Manager
// MegaTinyCore 2.3.2
// Note:bootloader not used, so many options below will not be relevent
//  Board: ATtiny 3224/1624/1614/1604/814/804/424/414/404/214/204
//  Chip or Board: Select your chip
//  Clock: 20MHz internal
//  millis()/micros() TCB0 (breaks tone() and Servo)
//  Startup Time: 8ms
//  BOD Voltage level: Any, BOD not used without bootloader
//  BOD Mode when Active/Sleeping: Any, BOD not used without bootloader
//  Save EEPROM: Any, not used without bootloader
//  UPDI/Reset Pin Function: Any, not used without bootloader 
//  Voltage Baud Correction: Closer to 5V

#ifdef MILLIS_USE_TIMERA0
#error "This sketch takes over TCA0 - please use a different timer for millis"
#endif

#ifndef MILLIS_USE_TIMERB0
#error "This sketch is written for use with TCB0 as the millis timing source"
#endif

// Pin connections per PAPR V0.5 PCB
// PA0 - UPDI/RESET
// PA1 - ADC - BATTERY
// PA2 - ADC = POTENTIOMETER
// PA3 - UNUSED
// PA4 - LED4 
// PA5 - LED1
// PA6 - LED2
// PA7 - LED3
// PB0 - PWM - FAN (uses Timer TCA0)
// PB1 - BUZZER
// PB2 - UART TX
// PB3 - UART RX

int analogBatt  = PIN_A1;  // AIN1 - 10 bit resolution on ADC 
int analogPot   = PIN_A2;  // AIN2 - Fan speed control POT with on/off switch
//int UNUSED    = PIN_PA3; //v0.5 change
int led4        = PIN_PA4; //v0.5 change
int led1        = PIN_PA5;
int led2        = PIN_PA6;
int led3        = PIN_PA7;
int PWMPin      = PIN_PB0; // W00 8 bit resolution with Arduino AnalogWrite (v0.3 change)
int buzzerPin   = PIN_PB1; //v0.5 change

// Battery Voltage to Fuel Gauge
// > 4.12V/Cell = 100% - 78% Battery  = 4 LEDs         => 899 > adc > 864
// > 3.95V/Cell =  77% - 55% Battery  = 3 LEDs         => 864 > adc > 816
// > 3.70V/Cell =  54% - 33% Battery  = 2 LEDs         => 816 > adc > 781
// > 3.54V/Cell =  32% - 10% Battery  = 1 LEDs         => 781 > adc > 712
// > 3.25V/Cell =  10% - 0%  Battery  = LEDS FLASHING  => 712 > adc > 618
// > 2.80V/Cell =  0%        Battery  = Shut Down

const int battADCMax  =  1023;
const int battADCFull =   899;
const int battADC78p  =   864;
const int battADC55p  =   816;
const int battADC33p  =   781;
const int battADC10p  =   712;
const int battADC0p   =   618;
const int battADCMin  =     0;


//Limits the min pot value     Voltage   Min PWM Percentage
const int minPWMfull =  50;  //11.85V      69     >77%
const int minPWM75p  =  55;  //11.10V      72     >54%
const int minPWM50p  =  61;  //10.62V      77     >33%
const int minPWM25p  =  70;  //9.75V       88     >10%
const int minPWM10p  = 126;  //8.40V      110     >0%
//These values were determined emperically by adjusting the input voltage and dialing the PWM down until motor stall

//State Machine states
const int batteryCheck = 7;
const int batteryFull  = 6;
const int battery75p   = 5;
const int battery50p   = 4;
const int battery25p   = 3;
const int battery10p   = 2;
const int batteryDead  = 1;

int batteryState = batteryCheck;

int offTime = 5; //ms
int onTime = 95;   //ms
int loopDelay = 25; //ms
int blinkCounter = 0;
const uint32_t numBatterySamples = 10;
uint32_t battery = 1023;
const uint32_t maxPot = 1023;
const uint32_t minPot = 0;
uint32_t fanPWM = 0;
uint32_t minPWM = minPWM10p;
uint32_t maxPWM = 255;
uint32_t rawADC = 0;

const int LEDFlashLoop  = 25; //decrease for 10% battery LED to blink faster

// the setup routine runs once when you press reset:
void setup() {
  // initialize the digital pin as an output.
  pinMode(led1, OUTPUT);
  pinMode(led2, OUTPUT);
  pinMode(led3, OUTPUT);
  pinMode(led4, OUTPUT);
  pinMode(buzzerPin, OUTPUT);
  pinMode(PWMPin, OUTPUT);  //PB0 - TCA0 WO0, pin9 on 14-pin parts
  //See http://ww1.microchip.com/downloads/en/Appnotes/TB3217-Getting-Started-with-TCA-DS90003217.pdf
  TCA0.SINGLE.CTRLB = ( TCA_SINGLE_CMP2EN_bm  | TCA_SINGLE_WGMODE_SINGLESLOPE_gc ); //Single PWM on WO0 singleslope
  TCA0.SINGLE.PER   = 0xFF; // Count down from 255 on WO0/WO1/WO2
  TCA0.SINGLE.CTRLA = ( TCA_SINGLE_CLKSEL_DIV4_gc | TCA_SINGLE_ENABLE_bm ); //enable the timer with prescaler of 4

  digitalWrite(led1, HIGH);
  digitalWrite(led2, HIGH);
  digitalWrite(led3, HIGH);
  digitalWrite(led4, HIGH);
  digitalWrite(buzzerPin,LOW);
  digitalWrite(PWMPin, maxPWM); //Turn on fan 100%
#ifdef TWOKFLASHCHIP
  delay(1000);
#else 
  Serial.begin(115200);
  Serial.println("Starting up");
  Serial.println("PAPRA 15MAY2021");
  Serial.println("PCB v0.5");
  Serial.println("AtTiny 0/1/2-Series 14 pin");
  Serial.println("Tetra Bio Distributed 2021");
  for (int i = 0; i <= 4; i++) { //startup knightrider 
    digitalWrite(led1, LOW);  delay(onTime);
    digitalWrite(led1, HIGH); 
    digitalWrite(led2, LOW);  delay(onTime);
    digitalWrite(led2, HIGH); 
    digitalWrite(led3, LOW);  delay(onTime);
    digitalWrite(led3, HIGH); 
    digitalWrite(led4, LOW);  delay(onTime); delay(onTime);
    digitalWrite(led4, HIGH); 
    digitalWrite(led3, LOW);  delay(onTime);
    digitalWrite(led3, HIGH); 
    digitalWrite(led2, LOW);  delay(onTime);
    digitalWrite(led2, HIGH); 
    digitalWrite(led1, LOW);  delay(onTime);
    digitalWrite(led1, HIGH); delay(offTime);
  }
#endif
}

// the loop routine runs over and over again forever:
void loop() {
  delay(25);
  //Clamp and rescale potentiometer input from a 10bit value to 8 bit
  if (maxPWM > 0) {
    rawADC = analogRead(analogPot);
    fanPWM = map( rawADC, minPot, maxPot, minPWM, maxPWM ); //scale knob, 10 bits to 8 bits (v0.3 change)
  } 
  else {
    fanPWM = maxPWM;
  }  
  analogWrite(PWMPin, fanPWM);
  battery = battery = ( ( battery * ( numBatterySamples - 1 ) ) + analogRead(analogBatt) ) / numBatterySamples;
  switch (battery) {
    case battADC78p ... battADCMax: // Full = 78% - 100%
      if (batteryState > batteryFull) {
        batteryState = batteryFull;
        digitalWrite(led1, LOW);  //All LEDs ON
        digitalWrite(led2, LOW);
        digitalWrite(led3, LOW);
        digitalWrite(led4, LOW);
        minPWM = minPWMfull;
      }
      break;
    case battADC55p ... ( battADC78p - 1 ): // 75% = 55% - 77%
      if (batteryState > battery75p) {
        batteryState = battery75p;
        digitalWrite(led1, LOW);  //3 LEDs ON
        digitalWrite(led2, LOW);
        digitalWrite(led3, LOW);
        digitalWrite(led4, HIGH);
        minPWM = minPWM75p;
      }
      break;
    case battADC33p ... ( battADC55p - 1 ): // 50% = 33% - 54%
      if (batteryState > battery50p) {
        batteryState = battery50p;
        digitalWrite(led1, LOW);  //2 LEDs ON
        digitalWrite(led2, LOW);
        digitalWrite(led3, HIGH);
        digitalWrite(led4, HIGH);
        minPWM = minPWM50p;
      }
      break;
    case battADC10p ... ( battADC33p -1 ): // 25% = 10% - 32%
      if (batteryState > battery25p) {
        batteryState = battery25p;
        digitalWrite(led1, LOW);  //1 LED on
        digitalWrite(led2, HIGH);
        digitalWrite(led3, HIGH);
        digitalWrite(led4, HIGH);
        minPWM = minPWM25p;
      }
      break;
    case battADC0p ... ( battADC10p - 1) : // 10% - Need to blink LED
      if (batteryState > battery10p) {
        batteryState = battery10p;
        digitalWrite(led2, HIGH); //1 LED blinking
        digitalWrite(led3, HIGH);
        digitalWrite(led4, HIGH);
        digitalWrite(led1, LOW);
        digitalWrite(buzzerPin, HIGH);
        minPWM = minPWM10p;
      }
      break;
    case battADCMin ... (battADC0p - 1 ): // Shutdown
      if (batteryState > batteryDead) {
        batteryState = batteryDead;
        digitalWrite(led1, HIGH); //All LEDs off
        digitalWrite(led2, HIGH);
        digitalWrite(led3, HIGH);
        digitalWrite(led4, HIGH);
        maxPWM = 0; // turn off fan - overrides the measuremnt from above
      }
      break;
  }
  // For battery state of 0-10%, need to blink LED1 to indicate almost dead battery
  if (batteryState == battery10p){
    if (blinkCounter++ > LEDFlashLoop) {
      digitalWrite(led1, !digitalRead(led1));
      blinkCounter = 0;
    }
  }  
#ifdef TWOKFLASHCHIP

#else
  Serial.print(" Battery = ");       Serial.print(battery);
  Serial.print(" rawADC = ");        Serial.print(rawADC);
  Serial.print(" pwm = ");           Serial.print(fanPWM);
  Serial.print(" Battery State = "); Serial.println(batteryState);
#endif
}
