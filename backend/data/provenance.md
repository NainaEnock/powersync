# Scenario provenance

Everything in `scenario.json` is **synthetic**. No real home was measured. Values are rounded from published US figures and are illustrative, not manufacturer cycles.

| Value | Used | Source / reasoning |
|---|---|---|
| EV charging | 7.2 kW for 3 h (21.6 kWh) | Typical Level 2 home charger, 7.2–7.7 kW ([EV Infrastructure News](https://www.evinfrastructurenews.com/ev-technology/level-2-charger-amperage-guide-ev-charging-business)) |
| Clothes dryer | 5.0 kW for 45 min (3.75 kWh) | Electric dryer heating element and cycle ([NPTRE](https://nptre.com/blog/which-household-appliances-use-the-most-electricity), [JouleIO](https://jouleio.com/blog/electricity-usage-by-appliance/)) |
| Dishwasher | 1.2 kW for 1 h (1.2 kWh) | Per-load energy ([JouleIO](https://jouleio.com/blog/electricity-usage-by-appliance/)) |
| Always-on use | 1.2 kW per home, every slot (~900 kWh/month) | Rounded US household average. Constant, so it leaves out evening air conditioning. |
| Shared limit | 15 kW | **Scenario assumption**, modeled on a 15 kVA pole transformer ([Elecbase](https://elecbase.net/how-many-houses-can-a-15kva-transformer-handle/), [UK SPARK Lab](https://sparklab.engr.uky.edu/sites/spark/files/2024-11/2024%20UK%20SPARK%20ECCE%20Loads%20Service%20Factors%20Transformers%20Heat%20Pump%20Solar%20PV%20EV.pdf), [three homes + EVs on 25 kVA](https://www.researchgate.net/figure/Load-profile-of-a-25-kVA-distribution-transformer-serving-three-homes-and-3-EVs-charging_fig5_224265921)) |
| Time-of-use tariff | $0.59/kWh 4–9 PM, $0.33/kWh otherwise | California summer TOU energy rates, without fees, taxes, or credits ([Temecula Solar Savings: SCE 2026](https://temeculasolarsavings.com/blog/sce-tou-rates-2026)). Labeled "Illustrative time-of-use tariff". |
| Flat tariff | $0.18/kWh | US residential average ([Electric Choice](https://www.electricchoice.com/electricity-prices-by-state/)). A correctness control: compare modes for behavior, not as bills. |
| Horizon | 6:00 PM 2026-07-15 to 6:00 PM 2026-07-16, America/New_York, 96 × 15 min | Chosen away from daylight-saving changes |

Money in this project is the **modeled energy charge** only. Moving a task never changes kWh, and under a flat rate it never changes cost.
