/*
  papracode
    - Reads battery voltage and lights up LEDs to mimic M12 battery fuel gauge
    - Reads user pot to control PWM of fan
  to do
    - look at averaging battery voltage
    - set a MIN PWM value for fan output, vary with battery level
  current code flash: 1764/4096 bytes (43%) RAM: 16/256 (6%) bytes without debug enabled
               flash: 3169/4096 bytes (77%) with debug enabled  
 */

// PA0 - UPDI/RESET
// PA1 - ADC - BATTERY
// PA2 - ADC = POTENTIOMETER
// PA3 - PWM - FAN
// PA4 - FAN TACH INPUT
// PA5 - LED1
// PA6 - LED2
// PA7 - LED3
// PB0 - UART RX
// PB1 - UART TX
// PB2 - NC
// PB3 - LED4

// Battery Voltage to Fuel Gauge
// > 4.12V/Cell = 100% - 78% Battery  = 4 LEDs         => 960 > adc > 920
// > 3.95V/Cell =  77% - 55% Battery  = 3 LEDs         => 920 > adc > 862
// > 3.70V/Cell =  54% - 33% Battery  = 2 LEDs         => 862 > adc > 825
// > 3.54V/Cell =  32% - 10% Battery  = 1 LEDs         => 825 > adc > 757
// > 3.25V/Cell =  10% - 0%  Battery  = LEDS FLASHING  => 757 > adc > 652
// > 2.80V/Cell =  0%        Battery  = Shut Down

//be sure to go to Arduino >> tools >> Support SerialEvent "No(saves space)" or "yes"
//serial debug takes up about 1300 bytes of flash, out of 4096 available, not including print statements
//#define DEBUG_SERIAL   //uncomment line to enable serial debug

int led1 = PIN_PA5;
int led2 = PIN_PA6;
int led3 = PIN_PA7;
int led4 = PIN_PB0;
int analogBatt = PIN_A1; //10 bit resolution on ADC 
int analogPot = PIN_A2; 
int PWMPin = PIN_PA3;    //8 bit resolution with Arduino AnalogWrite
int offTime = 95; //ms
int onTime = 5;   //ms
int loopDelay = 25; //ms
int speedPot = 0;
int battery = 0;
int blinkCounter = 0;

//State Machine states
const int batteryCheck = 7;
const int batteryFull  = 6;
const int battery75p   = 5;
const int battery50p   = 4;
const int battery25p   = 3;
const int battery10p   = 2;
const int batteryDead  = 1;

int batteryState = batteryCheck;

const int LEDFlashLoop  = 25; //decrease for 10% battery LED to blink faster
const int maxPWM = 255;

// the setup routine runs once when you press reset:
void setup() {
  // initialize the digital pin as an output.
  pinMode(led1, OUTPUT);
  pinMode(led2, OUTPUT);
  pinMode(led3, OUTPUT);
  pinMode(led4, OUTPUT);
  pinMode(PWMPin, OUTPUT);

  digitalWrite(led1, HIGH);
  digitalWrite(led2, HIGH);
  digitalWrite(led3, HIGH);
  digitalWrite(led4, HIGH);
  digitalWrite(PWMPin, maxPWM); //Turn on fan 100%
#ifdef DEBUG_SERIAL
  Serial.begin(115200);
  Serial.println("Starting up");
#endif
  for (int i = 0; i <= 6; i++) { //startup knightrider 
    digitalWrite(led1, LOW);  delay(onTime);
    digitalWrite(led1, HIGH); delay(offTime);
    digitalWrite(led2, LOW);  delay(onTime);
    digitalWrite(led2, HIGH); delay(offTime);
    digitalWrite(led3, LOW);  delay(onTime);
    digitalWrite(led3, HIGH); delay(offTime);
    digitalWrite(led4, LOW);  delay(onTime);
    digitalWrite(led4, HIGH); delay(offTime);
    digitalWrite(led3, LOW);  delay(onTime);
    digitalWrite(led3, HIGH); delay(offTime);
    digitalWrite(led2, LOW);  delay(onTime);
    digitalWrite(led2, HIGH); delay(offTime);
    digitalWrite(led1, LOW);  delay(onTime);
    digitalWrite(led1, HIGH); delay(offTime);
  }
}

// the loop routine runs over and over again forever:
void loop() {
  delay(25);
  speedPot = analogRead(analogPot) >> 2;  // read the input pin, scale 10 bits to 8 bits
  battery = analogRead(analogBatt);
  switch (battery) {
    case 925 ... 1023: // Full = 78% - 100%
      if (batteryState > batteryFull) {
        batteryState = batteryFull;
        digitalWrite(led1, LOW);  //All LEDs ON
        digitalWrite(led2, LOW);
        digitalWrite(led3, LOW);
        digitalWrite(led4, LOW);
      }
      break;
    case 867 ... 924: // 75% = 55% - 77%
      if (batteryState > battery75p) {
        batteryState = battery75p;
        digitalWrite(led1, LOW);  //3 LEDs ON
        digitalWrite(led2, LOW);
        digitalWrite(led3, LOW);
        digitalWrite(led4, HIGH);
      }
      break;
    case 830 ... 866: // 50% = 33% - 54%
      if (batteryState > battery50p) {
        batteryState = battery50p;
        digitalWrite(led1, LOW);  //2 LEDs ON
        digitalWrite(led2, LOW);
        digitalWrite(led3, HIGH);
        digitalWrite(led4, HIGH);
      }
      break;
    case 762 ... 829: // 25% = 10% - 32%
      if (batteryState > battery25p) {
        batteryState = battery25p;
        digitalWrite(led1, LOW);  //1 LED on
        digitalWrite(led2, HIGH);
        digitalWrite(led3, HIGH);
        digitalWrite(led4, HIGH);
      }
      break;
    case 657 ... 761: // 10% - Need to blink LED
      if (batteryState > battery10p) {
        batteryState = battery10p;
        digitalWrite(led2, HIGH); //1 LED blinking
        digitalWrite(led3, HIGH);
        digitalWrite(led4, HIGH);
        digitalWrite(led1, LOW);
        blinkCounter = 0;  //reset the blink counter 
      }
      break;
    case 0 ... 652: // Shutdown
      if (batteryState > batteryDead) {
        batteryState = batteryDead;
        digitalWrite(led1, HIGH); //All LEDs off
        digitalWrite(led2, HIGH);
        digitalWrite(led3, HIGH);
        digitalWrite(led4, HIGH);
        speedPot = 0; // turn off fan - overrides the measuremnt from above
      }
      break;
  }
  analogWrite(PWMPin, speedPot);
  // For battery state of 0-10%, need to blink LED1 to indicate almost dead battery
  if (batteryState == battery10p){
    if (blinkCounter++ > LEDFlashLoop) {
      digitalWrite(led1, !digitalRead(led1));
      blinkCounter = 0;
    }
  }  
#ifdef DEBUG_SERIAL
  //Serial.print("Battery = ");
  //Serial.print(battery);
  //Serial.print(" pot =");
  //Serial.print(pot);
  //Serial.print(" Battery State =");
  //Serial.println(batteryState);
#endif
  //digitalWrite(PIN_PB1,!digitalRead(PIN_PB1)); //Toggle unused pin for debugging with scope 
}
