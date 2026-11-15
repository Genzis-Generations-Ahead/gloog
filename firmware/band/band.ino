// Gloog reference band v2 — Seeed XIAO ESP32-C3 + MAX30102
//
// - Wi-Fi setup from your phone: if no saved network (or it can't connect),
//   the band opens hotspot "Gloog-Band-Setup" -> connect -> setup page pops up
//   -> pick Wi-Fi, type password, Save. Remembered across power-off.
// - Hold the B (BOOT) button 3 s while running -> forget Wi-Fi, back to setup.
// - Finds the laptop by itself: receiver.py broadcasts "GLOOG_RX" on UDP 5601,
//   the band learns the laptop IP from it. No IP to type.
// - Streams raw PPG (seq,ms,ir,red) at ~100 Hz to laptop UDP 5600.
// - Runs without the sensor too (keeps retrying), so Wi-Fi can be tested first.
//
// Board: XIAO_ESP32C3, Tools -> USB CDC On Boot: Enabled
// Library: "SparkFun MAX3010x Pulse and Proximity Sensor Library"
// Wiring: MAX30102 VIN->3V3, GND->GND, SDA->D4 (GPIO6), SCL->D5 (GPIO7)

#include <Wire.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include "MAX30105.h"

#define BTN_PIN   9          // XIAO "B" button (BOOT), active LOW
#define SDA_PIN   6
#define SCL_PIN   7

const char*    AP_NAME    = "Gloog-Band-Setup";
const uint16_t DATA_PORT  = 5600;   // band -> laptop
const uint16_t DISC_PORT  = 5601;   // laptop -> band discovery beacon
const uint32_t CONNECT_TIMEOUT_MS = 15000;
const uint32_t RESET_HOLD_MS      = 3000;

Preferences prefs;
WebServer   web(80);
DNSServer   dns;
MAX30105    ppg;
WiFiUDP     udp, disc;

bool      setupMode = false, sensorOK = false, haveLaptop = false;
IPAddress laptopIP;
uint32_t  seq = 0, lastSensorTry = 0, lastStatus = 0, btnDownAt = 0;
String    networkOptions;
char      pkt[64];

// ---------------------------------------------------------------- helpers
String esc(const String& s) {
  String o; o.reserve(s.length() + 8);
  for (unsigned int i = 0; i < s.length(); i++) {
    char c = s.charAt(i);
    if (c == '&') o += "&amp;"; else if (c == '<') o += "&lt;";
    else if (c == '>') o += "&gt;"; else if (c == '"') o += "&quot;";
    else o += c;
  }
  return o;
}

String htmlPage(const String& body) {
  return String(F("<!doctype html><html><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width,initial-scale=1'>"
           "<title>Gloog Band Setup</title><style>"
           "body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:24px}"
           "h1{font-size:22px;margin:0 0 4px}p{color:#aaa;margin:0 0 20px}"
           "label{display:block;margin:14px 0 6px;font-weight:600}"
           "select,input{width:100%;box-sizing:border-box;padding:12px;font-size:16px;border-radius:10px;"
           "border:1px solid #444;background:#1c1c1c;color:#eee}"
           "button{margin-top:22px;width:100%;padding:14px;font-size:17px;font-weight:700;border:0;"
           "border-radius:10px;background:#b8ff5a;color:#111}"
           ".hint{font-size:13px;color:#888;margin-top:6px}"
           "</style></head><body>")) + body + F("</body></html>");
}

void scanNetworks() {
  Serial.println("[band] scanning Wi-Fi...");
  int n = WiFi.scanNetworks();
  networkOptions = "";
  for (int i = 0; i < n; i++) {
    String s = WiFi.SSID(i);
    if (s.length() == 0 || networkOptions.indexOf("value=\"" + esc(s) + "\"") >= 0) continue;
    networkOptions += "<option value=\"" + esc(s) + "\">" + esc(s) +
                      " (" + String(WiFi.RSSI(i)) + " dBm)</option>";
  }
  WiFi.scanDelete();
}

// ---------------------------------------------------------------- setup portal
void handleRoot() {
  String saved = prefs.getString("ssid", "");
  String body = F("<h1>Gloog Band</h1><p>Connect the band to Wi-Fi (2.4 GHz only).</p>"
                  "<form method='POST' action='/save'><label>Wi-Fi network</label><select name='pick'>");
  body += networkOptions;
  body += F("<option value=''>Other (type below)</option></select>"
            "<input name='manual' placeholder='Hidden / other network name' style='margin-top:8px'>"
            "<label>Password</label><input name='pass' type='password' placeholder='Leave empty if open'>"
            "<button type='submit'>Save &amp; connect</button></form>");
  if (saved.length()) body += "<div class='hint'>Currently saved: " + esc(saved) + "</div>";
  body += F("<div class='hint'>Laptop is found automatically when receiver.py is running.</div>");
  web.send(200, "text/html", htmlPage(body));
}

void handleSave() {
  String ssid = web.arg("manual"); ssid.trim();
  if (ssid.length() == 0) ssid = web.arg("pick");
  String pass = web.arg("pass");
  if (ssid.length() == 0) {
    web.send(200, "text/html", htmlPage(F("<h1>No network chosen</h1><p><a href='/' style='color:#b8ff5a'>Go back</a></p>")));
    return;
  }
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  web.send(200, "text/html", htmlPage("<h1>Saved</h1><p>Band is restarting and joining <b>" + esc(ssid) +
                                      "</b>. You can reconnect your phone to your normal Wi-Fi.</p>"));
  Serial.printf("[band] saved Wi-Fi '%s', restarting\n", ssid.c_str());
  delay(1500);
  ESP.restart();
}

void redirectToPortal() {          // makes phones pop the setup page automatically
  web.sendHeader("Location", "http://" + WiFi.softAPIP().toString() + "/", true);
  web.send(302, "text/plain", "");
}

void startSetupMode() {
  setupMode = true;
  WiFi.disconnect(true);
  WiFi.mode(WIFI_AP_STA);
  delay(100);
  scanNetworks();
  WiFi.softAP(AP_NAME);
  delay(200);
  dns.start(53, "*", WiFi.softAPIP());
  web.on("/", HTTP_GET, handleRoot);
  web.on("/save", HTTP_POST, handleSave);
  web.onNotFound(redirectToPortal);
  web.begin();
  Serial.printf("[band] SETUP MODE: join Wi-Fi '%s' on your phone (page opens, or go to http://%s)\n",
                AP_NAME, WiFi.softAPIP().toString().c_str());
}

// ---------------------------------------------------------------- normal mode
bool connectSaved() {
  String ssid = prefs.getString("ssid", "");
  String pass = prefs.getString("pass", "");
  if (ssid.length() == 0) { Serial.println("[band] no saved Wi-Fi"); return false; }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(ssid.c_str(), pass.c_str());
  Serial.printf("[band] connecting to '%s'", ssid.c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < CONNECT_TIMEOUT_MS) {
    delay(300); Serial.print(".");
    if (digitalRead(BTN_PIN) == LOW) break;          // let user bail to setup
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) { Serial.println("[band] could not connect"); return false; }

  WiFi.setSleep(false);   // steady packet rate (also feeds CSI traffic)
  Serial.printf("[band] connected  IP=%s  RSSI=%d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());
  return true;
}

void trySensor() {
  lastSensorTry = millis();
  if (!ppg.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("[band] MAX30102 not found (check wiring) - retrying");
    return;
  }
  // brightness, sampleAverage, ledMode(2=Red+IR), sampleRate, pulseWidth, adcRange -> ~100 Hz out
  ppg.setup(0x1F, 4, 2, 400, 411, 4096);
  sensorOK = true;
  Serial.println("[band] MAX30102 OK");
}

void checkDiscovery() {
  int n = disc.parsePacket();
  if (n <= 0) return;
  char buf[16] = {0};
  disc.read(buf, sizeof(buf) - 1);
  if (strncmp(buf, "GLOOG_RX", 8) != 0) return;
  IPAddress ip = disc.remoteIP();
  if (!haveLaptop || !(ip == laptopIP)) {
    laptopIP = ip; haveLaptop = true;
    Serial.printf("[band] laptop found at %s\n", laptopIP.toString().c_str());
  }
}

void checkResetButton() {
  if (digitalRead(BTN_PIN) == LOW) {
    if (btnDownAt == 0) btnDownAt = millis();
    else if (millis() - btnDownAt > RESET_HOLD_MS) {
      Serial.println("[band] button held: forgetting Wi-Fi");
      prefs.remove("ssid"); prefs.remove("pass");
      delay(300);
      ESP.restart();
    }
  } else {
    btnDownAt = 0;
  }
}

// ---------------------------------------------------------------- main
void setup() {
  Serial.begin(115200);
  delay(1500);
  pinMode(BTN_PIN, INPUT_PULLUP);
  prefs.begin("gloog", false);
  Wire.begin(SDA_PIN, SCL_PIN);

  Serial.println("\n[band] Gloog band v2");
  if (!connectSaved()) { startSetupMode(); return; }

  udp.begin(DATA_PORT);
  disc.begin(DISC_PORT);
  trySensor();
}

void loop() {
  checkResetButton();

  if (setupMode) {
    dns.processNextRequest();
    web.handleClient();
    return;
  }

  checkDiscovery();

  if (!sensorOK) {
    if (millis() - lastSensorTry > 2000) trySensor();
  } else {
    ppg.check();
    while (ppg.available()) {
      unsigned long red = ppg.getFIFORed();
      unsigned long ir  = ppg.getFIFOIR();
      ppg.nextSample();
      if (!haveLaptop || WiFi.status() != WL_CONNECTED) continue;
      int n = snprintf(pkt, sizeof(pkt), "%lu,%lu,%lu,%lu",
                       (unsigned long)seq++, (unsigned long)millis(), ir, red);
      udp.beginPacket(laptopIP, DATA_PORT);
      udp.write((const uint8_t*)pkt, n);
      udp.endPacket();
    }
  }

  if (millis() - lastStatus > 5000) {
    lastStatus = millis();
    Serial.printf("[band] wifi=%s rssi=%d laptop=%s sensor=%s sent=%lu\n",
                  WiFi.status() == WL_CONNECTED ? "ok" : "DOWN", WiFi.RSSI(),
                  haveLaptop ? laptopIP.toString().c_str() : "searching",
                  sensorOK ? "ok" : "missing", (unsigned long)seq);
  }
}
