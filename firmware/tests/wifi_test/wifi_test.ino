// XIAO ESP32-C3: Wi-Fi + antenna check. Expect RSSI -30..-60 near the router.
#include <WiFi.h>
void setup(){
  Serial.begin(115200); delay(2000);
  WiFi.begin("gloog","12345678");
  Serial.print("Connecting");
  while(WiFi.status()!=WL_CONNECTED){ delay(300); Serial.print("."); }
  Serial.printf("\nOK  IP=%s  RSSI=%d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
}
void loop(){ Serial.printf("RSSI=%d\n", WiFi.RSSI()); delay(2000); }
