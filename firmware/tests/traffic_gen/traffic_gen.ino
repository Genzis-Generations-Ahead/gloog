// XIAO ESP32-C3 traffic generator: keeps the router transmitting at a STEADY rate so the
// Pi gets evenly spaced CSI (heart rate needs ~50-100 packets/s, evenly spaced).
//
// How: the band sends a small UDP broadcast RATE_HZ times per second. The router
// (AP) relays every broadcast to the cell, and that relayed frame comes from the
// router's MAC, which is exactly what the Pi captures CSI from.
// v1 hammered HTTP GETs as fast as possible: bursty, uneven packet timing.
//
// Set your router's Wi-Fi name/password below (don't commit real passwords).

#include <WiFi.h>
#include <WiFiUdp.h>

#define WIFI_SSID  "gloog"
#define WIFI_PASS  "CHANGE_ME"
#define RATE_HZ    100            // CSI packets per second you want

WiFiUDP udp;
uint32_t sent = 0, lastLog = 0;
uint32_t nextUs = 0;
const uint32_t periodUs = 1000000UL / RATE_HZ;

void setup() {
  Serial.begin(115200);
  delay(500);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[traffic] connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
  WiFi.setSleep(false);
  Serial.printf("\n[traffic] connected, %d packets/s\n", RATE_HZ);
  nextUs = micros();
}

void loop() {
  if ((int32_t)(micros() - nextUs) >= 0) {
    nextUs += periodUs;
    udp.beginPacket(IPAddress(255, 255, 255, 255), 5599);
    udp.write((const uint8_t*)"G", 1);
    udp.endPacket();
    sent++;
  }
  if (millis() - lastLog > 5000) {
    lastLog = millis();
    Serial.printf("[traffic] sent=%lu wifi=%s\n", (unsigned long)sent, WiFi.status() == WL_CONNECTED ? "ok" : "DOWN");
    if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
  }
}
