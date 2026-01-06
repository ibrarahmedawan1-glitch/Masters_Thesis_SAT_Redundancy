
# SAT-Based Redundancy Removal Tool for Logic Circuits

## Abstract
This repository contains the source code and experimental data for the thesis **"SAT-Based Redundancy Removal in Digital Logic"**. The tool integrates multiple SAT solvers to detect stuck-at faults and redundant logic in ISCAS85 benchmark circuits.

## Key Features
* **Multi-Solver Support:** Integrates 7 state-of-the-art solvers including `Glucose 4`, `CaDiCaL`, and `Lingeling`.
* **Incremental Analysis:** Uses assumption-based solving for rapid fault injection.
* **MUS Extraction:** capable of extracting Minimal Unsatisfiable Sets to identify the root cause of logic conflicts.
* **Visualization:** Automated Python scripts to generate comparative performance plots.

## Repository Structure
* `generate_dataset_ultimate.py`: Main script to run benchmarks and detect redundancies.
* `thesis_plots.py`: Generates visualization charts from the CSV results.
* `benchmarks/`: Contains ISCAS85 `.aag` circuit files.
* `results/`: CSV outputs and performance graphs.

## How to Run
1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the Analysis:**
    ```bash
    python3 generate_dataset_ultimate.py
    ```

3.  **Generate Plots:**
    ```bash
    python3 thesis_plots.py
    ```

## Results
Experimental results demonstrate that **Glucose 4** offers the optimal balance of speed and stability for this specific domain, while **Lingeling** suffers from high initialization overhead on smaller combinational circuits.

## Author
* **Name:** [Ibrar Ahmed Awan]
* **Institution:** [University Of Freiburg]
* **Year:** 2026
