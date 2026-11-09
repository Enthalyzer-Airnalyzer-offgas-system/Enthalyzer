/******************************************************************************
 * @name        = Enthalyzer.ino
 * @description = ESP32 firmware for the Enthalyzer.
 *                Reads two MAX31865 Pt100 water temperatures and a pulse-type flow 
 *                sensor. Calculates the water-side heat gain and logs the 
 *                data every 10 s as semicolon-separated text.
 * @author      = [Ayur Jitendra Ghalot]
 * @contact     = [TU Dresden], [Chair of Bioprocess Engineering]
 * @email       = [ayur.ghalot@tu-dresden.de]
 * @license     = MIT License
 *
 * Copyright (c) 2026 [Ayur Jitendra Ghalot / TU Dresden]
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 *
 * @date        = [06.11.2026]
 * @maintainer  = [Ayur Jitendra Ghalot]
 * @imports     = Arduino-ESP32 core, Adafruit MAX31865 library [1.6.2]
 * @version     = 2.0.0 (Gas sensors removed)
 *****************************************************************************/

#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_MAX31865.h>

//
// PINOUT
//
#define FLOW_SENSOR_PIN 17
#define SPI_MOSI_PIN    23      // shared bus (WAGO clip) - both boards
#define SPI_MISO_PIN    19      // shared bus (WAGO clip) - both boards
#define SPI_CLK_PIN     18      // shared bus (WAGO clip) - both boards
#define SPI_CS_PIN      4       // MAX31865 #1 - water OUTLET (unique CS)
#define SPI_CS_PIN_2    5       // MAX31865 #2 - water INLET  (unique CS)

//
// Constant & Function Declarations
//
#define RNOMINAL  100.000
#define RREF      430.000

// Stabilization period — number of initial cycles to discard
// so the PT100 sensors settle before heat gain is computed.
const uint8_t STABILIZATION_CYCLES = 3;
uint8_t warmupCounter = 0;   // counts completed measurement cycles at startup

// ─────────────────────────────────────────────────────────────
// SENSOR CALIBRATION 
// Model:  corrected = A * raw^2 + B * raw + C     (2nd-order)
// Fitted 2026 from 8-pt thermostat sweep (5–40 °C), cal date 19.08
// ─────────────────────────────────────────────────────────────
struct Calib { float A; float B; float C; };

inline float applyCalib(const Calib &k, float raw) {
  return k.A * raw * raw + k.B * raw + k.C;
}

// Coefficients
const Calib CAL_WATER_IN  = { -0.00001410f, 1.189178f, -5.026825f };
const Calib CAL_WATER_OUT = {  0.00131830f, 1.132807f, -4.080799f };

// Thermodynamic Constants
const float CP_WATER   = 4.184;       // Water specific heat [kJ/kg·°C]

// Valid sensor ranges used to reject bad / disconnected readings.
const float T_MIN_VALID  = -40.0;   // °C
const float T_MAX_VALID  = 125.0;   // °C

const int Measurement_Interval = 10000;

// Two MAX31865 boards sharing the SPI bus, each with a unique chip-select pin.
Adafruit_MAX31865 PT100_OUT = Adafruit_MAX31865(SPI_CS_PIN,   SPI_MOSI_PIN, SPI_MISO_PIN, SPI_CLK_PIN);
Adafruit_MAX31865 PT100_IN  = Adafruit_MAX31865(SPI_CS_PIN_2, SPI_MOSI_PIN, SPI_MISO_PIN, SPI_CLK_PIN);

volatile uint32_t pulseCount = 0;
const float pulsesPerLiter = 13000.0;
unsigned long lastTime = 0;

// ─────────────────────────────────────────────────────────────
// Flow Sensor Rolling Average (window = 10 samples)
// ─────────────────────────────────────────────────────────────
const uint8_t FLOW_AVG_WINDOW = 10;
float   flowBuffer[FLOW_AVG_WINDOW] = {0.0};
uint8_t flowIndex = 0;
uint8_t flowCount = 0;
float   flowSum   = 0.0;

void IRAM_ATTR pulseCounter() { pulseCount++; }

float flowRollingAverage(float newValue) {
  flowSum -= flowBuffer[flowIndex];
  flowBuffer[flowIndex] = newValue;
  flowSum += newValue;
  flowIndex = (flowIndex + 1) % FLOW_AVG_WINDOW;
  if (flowCount < FLOW_AVG_WINDOW) flowCount++;
  return flowSum / flowCount;
}

// Simple range validator for temperature.
inline bool isValidTemp(float T)  { return (T >= T_MIN_VALID)  && (T <= T_MAX_VALID)  && !isnan(T); }

// ─────────────────────────────────────────────────────────────
// PT100 Helpers: read RAW then apply 2nd-order calibration
// ─────────────────────────────────────────────────────────────
inline float readOutletTemp() {
  float raw = PT100_OUT.temperature(RNOMINAL, RREF);
  return applyCalib(CAL_WATER_OUT, raw);
}
inline float readInletTemp() {
  float raw = PT100_IN.temperature(RNOMINAL, RREF);
  return applyCalib(CAL_WATER_IN, raw);
}

//
// SETUP
//
void setup()
{
  Serial.begin(115200);
  SPI.begin(SPI_CLK_PIN, SPI_MISO_PIN, SPI_MOSI_PIN, SPI_CS_PIN);
  Serial.println(); // Blank line for serial monitor separation

  // =========================================================================
  // SERIAL OUTPUT LOGIC: BOOT & INITIALIZATION
  // =========================================================================

  if (PT100_OUT.begin(MAX31865_4WIRE)) Serial.println("successfully initialized PT100 OUTLET (calibrated)");
  else Serial.println("ERROR: PT100 OUTLET could not be initialized");

  if (PT100_IN.begin(MAX31865_4WIRE)) Serial.println("successfully initialized PT100 INLET (calibrated)");
  else Serial.println("ERROR: PT100 INLET could not be initialized");

  pinMode(FLOW_SENSOR_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_SENSOR_PIN), pulseCounter, FALLING);

  // Configuration summary outputs
  Serial.println("successfully initialized flow sensor");
  Serial.println("Flow rolling average window: 10 samples");
  Serial.println("Calibration: 2nd-order");
  Serial.print("Stabilization period: first ");
  Serial.print(STABILIZATION_CYCLES);
  Serial.println(" measurement cycles will be discarded.");

  // =========================================================================
  // SERIAL OUTPUT LOGIC: CSV HEADER
  // Throws this 6-column header once at startup.
  // =========================================================================
  Serial.println(
    "Runtime [millis]; H2O_Flowrate_raw [L/min]; H2O_Flowrate [L/min]; H2O_Inlet_Temp [°C]; H2O_Outlet_Temp [°C]; Q_water_gain [W]"
  );
}

//
// LOOP
//
void loop(){
  // Only execute and throw output if the Measurement_Interval (10 seconds) has passed
  if (millis() - lastTime >= Measurement_Interval)
  {
    Serial.print(lastTime);
    lastTime = millis();
    noInterrupts();
    uint32_t pulses = pulseCount;
    pulseCount = 0;
    interrupts();

    // =========================================================================
    // SERIAL OUTPUT LOGIC: CONTINUOUS DATA LOGGING (Columns 1-5)
    // =========================================================================
    float litersPerMinuteRaw = (pulses / pulsesPerLiter) * (60000.0 / Measurement_Interval);
    float litersPerMinute    = flowRollingAverage(litersPerMinuteRaw);
    float mWater             = litersPerMinute / 60.0; // kg/s (assume 1 kg/L)

    float tWaterIn  = readInletTemp();
    float tWaterOut = readOutletTemp();

    Serial.print(" ; "); Serial.print(litersPerMinuteRaw, 3);
    Serial.print(" ; "); Serial.print(litersPerMinute, 3);
    Serial.print(" ; "); Serial.print(tWaterIn, 3);
    Serial.print(" ; "); Serial.print(tWaterOut, 3);

    // Check if any sensor is disconnected (NaN) or outputting impossible physics
    bool sensorsValid = isValidTemp(tWaterIn) && isValidTemp(tWaterOut);

    // =========================================================================
    // SERIAL OUTPUT LOGIC: BRANCHING PATHS (Column 6)
    // Depending on the state of the sensors, the code follows one of 3 paths:
    // =========================================================================

    // --- PATH A: WARMUP PHASE (STABILIZING) ---
    if (warmupCounter < STABILIZATION_CYCLES) {
      warmupCounter++;
      Serial.print(" ; STABILIZING");
      Serial.println(); // Completes the line
      return;           // Skips math and waits for next 10s
    }

    // --- PATH B: INVALID SENSOR DATA ---
    if (!sensorsValid) {
      Serial.print(" ; INVALID");
      Serial.println(); // Completes the line
      return;           // Skips math and waits for next 10s
    }

    // --- PATH C: NORMAL VALID OUTPUT ---
    // Calculate WATER-SIDE Heat Gain [W]
    // Formula: Q = m_dot * Cp * dT * 1000 (kW to W)
    float Q_water_gain = mWater * CP_WATER * (tWaterOut - tWaterIn) * 1000.0;

    // Throw the final math output into the serial stream
    Serial.print(" ; "); Serial.print(Q_water_gain, 3);

    Serial.println(); // End of Path C: Completes the line and waits 10s
  }
}
