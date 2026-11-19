// Gloog breathing phantom — servo moves a foil-covered board in a sine wave.
// Works on Arduino Uno/Nano (Servo.h). Servo signal -> D9.
// Power servo from a SEPARATE 5V supply (not the board's 5V pin), common GND.
//
// Serial (115200), one command per line:
//   15        -> 15 breaths per minute (0 = stop, max 60)
//   a25       -> amplitude 25 degrees (5..45, bigger = deeper "breath")
//   q         -> quiet: stop printing the ground-truth log
//
// Ground-truth log (for the paper): "GT,millis,bpm,angle" at 50 Hz.
//
// v2 fixes: a stray newline no longer stops the phantom (old parseFloat returned 0),
// and changing the rate no longer makes the servo jump (phase is accumulated).

#include <Servo.h>

Servo s;
float bpm = 15.0;          // default breathing rate
int   amp = 20;            // +/- degrees
const int CENTER = 90;     // servo center angle
float phase = 0;           // radians, accumulated so rate changes are smooth
unsigned long lastMs;
bool  logOn = true;
char  line[16];
uint8_t len = 0;

void handle(const char* cmd) {
  if (cmd[0] == 'q') { logOn = !logOn; return; }
  if (cmd[0] == 'a') {
    int a = atoi(cmd + 1);
    if (a >= 5 && a <= 45) { amp = a; Serial.print("amp="); Serial.println(amp); }
    return;
  }
  if ((cmd[0] >= '0' && cmd[0] <= '9') || cmd[0] == '.') {
    float v = atof(cmd);
    if (v >= 0 && v <= 60) { bpm = v; Serial.print("bpm="); Serial.println(bpm); }
  }
}

void setup() {
  Serial.begin(115200);
  s.attach(9);
  s.write(CENTER);
  lastMs = millis();
  Serial.println("phantom ready - send bpm (0 = stop), aNN = amplitude, q = log on/off");
}

void loop() {
  while (Serial.available()) {              // line-based input: ignores empty lines
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (len) { line[len] = 0; handle(line); len = 0; }
    } else if (len < sizeof(line) - 1) {
      line[len++] = c;
    }
  }

  unsigned long now = millis();
  if (now - lastMs < 20) return;            // 50 Hz
  float dt = (now - lastMs) / 1000.0;
  lastMs = now;

  phase += 2.0 * PI * (bpm / 60.0) * dt;
  if (phase > 2.0 * PI) phase -= 2.0 * PI;
  float angle = bpm > 0 ? CENTER + amp * sin(phase) : CENTER;
  s.write((int)angle);

  if (logOn) {
    Serial.print("GT,"); Serial.print(now); Serial.print(','); Serial.print(bpm); Serial.print(','); Serial.println(angle);
  }
}
