/*
  papracode
  Test code to confirm the hardware
  blink 4 LEDs
  Read POT via ADC
  Ouput PWM to fan
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
// > 4.12V/Cell = 100% - 78% Battery = 4 LEDs         => 960 > adc > 920
// > 3.95V/Cell =  77% - 55% Battery  = 3 LEDs         => 920 > adc > 862
// > 3.70V/Cell =  54% - 33% Battery  = 2 LEDs         => 862 > adc > 825
// > 3.54V/Cell =  32% - 10% Battery  = 1 LEDs         => 825 > adc > 757
// > 3.25V/Cell =  10% - 0%  Battery  = LEDS FLASHING  => 757 > adc > 652
// > 2.80V/Cell =  0%        Battery  = Shut Down


int led1 = PIN_PA5;
int led2 = PIN_PA6;
int led3 = PIN_PA7;
int led4 = PIN_PB0;
int offTime = 50;
int onTime = 50;
int analogPot = PIN_A2; //10 bit resolution
int analogBatt = PIN_A1; 
int PWMPin = PIN_PA3;    //8 bit resolution with Arduino AnalogWrite
int pot = 0; 
int battery = 0;
int flashCounter = 0;

// the setup routine runs once when you press reset:
void setup() {
  // initialize the digital pin as an output.
  Serial.begin(115200);
  Serial.println("Starting up");

  pinMode(led1, OUTPUT);
  pinMode(led2, OUTPUT);
  pinMode(led3, OUTPUT);
  pinMode(led4, OUTPUT);
  pinMode(PWMPin, OUTPUT);
   
  digitalWrite(led1, HIGH);
  digitalWrite(led2, HIGH);
  digitalWrite(led3, HIGH);
  digitalWrite(led4, HIGH);
  digitalWrite(PWMPin, 255);
  for (int i = 0; i <= 6; i++) {
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
  pot = analogRead(analogPot) / 4;  // read the input pin, scale 10 bits to 8 bits
  battery = analogRead(analogBatt);
  switch (battery) {
    case 0 ... 652: // Shutdown
      digitalWrite(led1, HIGH);
      digitalWrite(led2, HIGH);
      digitalWrite(led3, HIGH);
      digitalWrite(led4, HIGH);
      pot = 0; // turn off fan     
      break;
    case 657 ... 757: // 10% - NEED TO FLASH 
      digitalWrite(led2, HIGH);
      digitalWrite(led3, HIGH);
      digitalWrite(led4, HIGH);
      if (flashCounter++ > 25) {
        digitalWrite(led1, !digitalRead(led1));
        flashCounter = 0; 
      }
      break;
    case 762 ... 825: // 10% - 32%
      digitalWrite(led1, LOW);
      digitalWrite(led2, HIGH);
      digitalWrite(led3, HIGH);
      digitalWrite(led4, HIGH);   
      break;
    case 830 ... 862: // 33% - 54%
      digitalWrite(led1, LOW);
      digitalWrite(led2, LOW);
      digitalWrite(led3, HIGH);
      digitalWrite(led4, HIGH);   
      break;
    case 867 ... 920: // 55% - 77%
      digitalWrite(led1, LOW);
      digitalWrite(led2, LOW);
      digitalWrite(led3, LOW);
      digitalWrite(led4, HIGH);   
      break;
    case 925 ... 1023: // 78% - 100%
      digitalWrite(led1, LOW);
      digitalWrite(led2, LOW);
      digitalWrite(led3, LOW);
      digitalWrite(led4, LOW);   
      break;
    default:
      // note: dead spots in case ranges are for hysteresis
      break;
  }
  analogWrite(PWMPin, pot);
  Serial.print("Battery = "); 
  Serial.print(battery); 
  Serial.print(" pot ="); 
  Serial.println(pot);
  delay(25);
  digitalWrite(PIN_PB1,!digitalRead(PIN_PB1));
}
