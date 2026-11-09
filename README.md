# Enthalyzer - A DIY Instrumentation for Bioprocess Exhaust Gas Condensation and Analysis
**Open-source 3D-printed condenser and ESP32-based sensor network for real-time thermodynamic monitoring of aerated bioprocesses.**

Reliable measurement inside compact, humid, condensing environments is challenging, as conventional instrumentation is bulky and unsuitable for smaller-scale setups. Additive manufacturing overcomes this by enabling complex internal geometries at a low cost, iteratively refining core designs. With this work, we present a live-monitored, 3D-printed, water-cooled condenser vessel for the dehumidification of gas streams. It is easily printable, assembled from off-the-shelf fittings, and purposed for real-time performance monitoring in compact and DIY-friendly applications for under €125.

### System Architecture
The condenser core is a helical, thin silicone coil (0.5 mm wall) through which chilled water flows while humid gas passes across it. A microcontroller reads all sensors every 10 s: 
* Two 4-wire RTDs for water inlet and outlet temperatures
* A flow sensor for water flow rate

From these live readings, the firmware computes the real-time water-side heat gain (cooling duty, Q_water), which is streamed for continuous monitoring. This demonstrates that a low-cost sensor setup can track thermodynamic performance metrics that would otherwise require laboratory-grade instrumentation, while producing time-resolved data valuable for validating condenser performance and calibrating simulation models.

### Dashboard & Sensor Network
The real-time performance dashboard aggregates data from:
* 2× PT100 RTDs with Adafruit PT100 RTD Temperature Sensor Amplifiers - MAX31865, 4-wire (Adafruit, NY, USA)
* 1× Biotech FCH-m-POM mini flow meter (Biotech, Vilshofen, DE)

<br>

<p align="center">
  <img width="800" alt="Process and instrumentation schematic" src="https://github.com/user-attachments/assets/c73b02a5-5daa-41fa-a622-a07ecf301ecd" />
  <br>
  <em>Figure 1: Process and instrumentation schematic of the compact 3D-printed condenser with real-time performance.</em>
</p>
