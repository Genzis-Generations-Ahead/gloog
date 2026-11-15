// XIAO ESP32-C3: I2C scan on SDA=D4(GPIO6), SCL=D5(GPIO7). MAX30102 shows as 0x57.
#include <Wire.h>
void setup(){ Serial.begin(115200); delay(2000); Wire.begin(6,7); }
void loop(){
  for(byte a=1;a<127;a++){ Wire.beginTransmission(a);
    if(Wire.endTransmission()==0){ Serial.print("Found 0x"); Serial.println(a,HEX);} }
  Serial.println("--"); delay(2000);
}
