/*
  papracode
  Test code to confirm the hardware
  blink 4 LEDs
  Read POT via ADC
  Ouput PWM to fan
 */

int led1 = PIN_PA5;
int led2 = PIN_PA6;
int led3 = PIN_PA7;
int led4 = PIN_PB0;
int offTime = 100;
int onTime = 100;
int analogPin = PIN_A2; //10 bit resolution
int PWMPin = PIN_PA3;    //8 bit resolution with Arduino AnalogWrite
int val = 0; 

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
  digitalWrite(PWMPin, 0);
}

// the loop routine runs over and over again forever:
void loop() {
  val = analogRead(analogPin);  // read the input pin
  analogWrite(PWMPin, val/4);
  digitalWrite(led1, LOW);   // turn the LED on (LOW is the voltage level)
  delay(onTime);                 // wait for 50ms
  digitalWrite(led1, HIGH);  // turn the LED off by making the voltage HIGH
  delay(offTime);                // wait for 950ms
  digitalWrite(led2, LOW);   // turn the LED on (LOW is the voltage level)
  delay(onTime);                 // wait for 50ms
  digitalWrite(led2, HIGH);  // turn the LED off by making the voltage LOW
  delay(offTime);                // wait for 950ms
  digitalWrite(led3, LOW);   // turn the LED on (LOW is the voltage level)
  delay(onTime);                 // wait for 50ms
  digitalWrite(led3, HIGH);  // turn the LED off by making the voltage HIGH
  delay(offTime);                // wait for 950ms
  digitalWrite(led4, LOW);   // turn the LED on (LOW is the voltage level)
  delay(onTime);                 // wait for 50ms
  digitalWrite(led4, HIGH);  // turn the LED off by making the voltage HIGH
  delay(offTime);                // wait for 950ms

}
