# Enthalyzer - A DIY Instrumentation for Bioprocess Exhaust Gas Condensation and Analysis
**Open-source 3D-printed condenser and ESP32-based sensor network for real-time thermodynamic monitoring of aerated bioprocesses.**

Reliable measurement inside compact, humid, condensing environments is challenging, as conventional instrumentation is bulky and unsuitable for smaller-scale setups. Additive manufacturing overcomes this by enabling complex internal geometries at a low cost, iteratively refining core designs. With this work, we present a live-monitored, 3D-printed, water-cooled condenser vessel for the dehumidification of gas streams. It is easily printable, assembled from off-the-shelf fittings, and purposed for real-time performance monitoring in compact and DIY-friendly applications for under €150.

### System Architecture
The condenser core is a helical, thin silicone coil (0.5 mm wall) through which chilled water flows while humid gas passes across it. A microcontroller reads all sensors every 10 s: 
* Two 4-wire RTDs for water inlet and outlet temperatures
* A flow sensor for water flow rate
* Two combined temperature–humidity sensors for the gas stream, from which moist-gas enthalpy is derived. 

From these live readings, the firmware computes the thermal duty (Q̇), the logarithmic mean enthalpy difference (LMED), effectiveness (%), and the overall enthalpy-based transfer coefficient (U), all streamed to a custom dashboard for continuous monitoring. This demonstrates that a low-cost sensor setup can track thermodynamic performance metrics that would otherwise require laboratory-grade instrumentation, while producing time-resolved data valuable for validating and calibrating simulation models.

### Dashboard & Sensor Network
The real-time performance dashboard aggregates data from:
* 2× SHT45 sensors (Sensirion, Stäfa, CH)
* 2× PT100 RTDs with Adafruit PT100 RTD Temperature Sensor Amplifiers - MAX31865, 4-wire (Adafruit, NY, USA)
* 1× Biotech FCH-m-POM mini flow meter (Biotech, Vilshofen, DE)

<br>

<p align="center">
  <img width="800" alt="<img width="849" height="479" alt="image" src="https://github.com/user-attachments/assets/9907be40-4054-4301-8081-aff6feed9008" />
" />
  <br>
  <em>Figure 1: Process and instrumentation schematic of the compact 3D-printed condenser with real-time performance dashboard.</em>
</p>

<p align="center">
  <img width="800" alt="Enthalyzer Circuit Connection" src="<img width="3000" height="2319" alt="Enthalyzer Circuit" src="https://github.com/user-attachments/assets/6fc2f99c-53df-49c9-81ef-0d6be8abe30c" />
" />
  <br>
  <em>Figure 2: Enthalyzer circuit connection wiring diagram.</em>
</p>
