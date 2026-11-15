// XIAO ESP32-C3: keeps the router transmitting data frames so the Pi has CSI to capture.
// Loops HTTP GETs to the router admin page.
#include <WiFi.h>
WiFiClient c;
void setup(){
  WiFi.begin("gloog","12345678");
  while(WiFi.status()!=WL_CONNECTED) delay(300);
  WiFi.setSleep(false);
}
void loop(){
  if(c.connect("192.168.0.1",80)){
    c.print("GET / HTTP/1.0\r\n\r\n");
    unsigned long t=millis();
    while(c.connected()&&millis()-t<200) while(c.available()) c.read();
    c.stop();
  }
}
