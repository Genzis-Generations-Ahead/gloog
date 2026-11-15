// Gloog breathing phantom — servo moves a foil-covered board in a sine wave.
// Works on Arduino Uno/Nano (Servo.h). Servo signal -> D9.
// Power servo from a SEPARATE 5V supply (not the board's 5V pin), common GND.
// Serial (115200): send a number = breaths per minute (e.g. "15"), "0" = stop.

#include <Servo.h>

Servo s;
float bpm = 15.0;          // default breathing rate
const int CENTER = 90;     // servo center angle
const int AMP = 20;        // +/- degrees (bigger = deeper "breath")
unsigned long t0;

void setup() {
  Serial.begin(115200);
  s.attach(9);
  s.write(CENTER);
  t0 = millis();
  Serial.println("phantom ready - send bpm (0 = stop)");
}

void loop() {
  if (Serial.available()) {
    float v = Serial.parseFloat();
    if (v >= 0 && v <= 60) { bpm = v; Serial.print("bpm="); Serial.println(bpm); }
  }
  if (bpm <= 0) { s.write(CENTER); delay(20); return; }

  float t = (millis() - t0) / 1000.0;
  float angle = CENTER + AMP * sin(2.0 * PI * (bpm / 60.0) * t);
  s.write((int)angle);
  // ground-truth log: millis,bpm,angle  (capture with serial monitor for the paper)
  Serial.print(millis()); Serial.print(','); Serial.print(bpm); Serial.print(','); Serial.println(angle);
  delay(20);  // 50 Hz
}
