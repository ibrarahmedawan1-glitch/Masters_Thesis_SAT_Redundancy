import subprocess
import os
import csv
import re
import random
import time
from datetime import datetime

# ==========================================
#        THESIS EXPERIMENT CONFIGURATION
# ==========================================
CONFIG = {
    "AIGFUZZ_PATH": "./aiger/aigfuzz",
    "AIGTOAIG_PATH": "./aiger/aigtoaig",
    "ABC_PATH": "./abc/abc",
    "OUTPUT_DIR": "thesis_benchmarks",
    "REPORT_FILE": "thesis_results_final.csv",
    "NUM_RANDOM_TESTS": 20,
    "NUM_REDUNDANT_TESTS": 20,
    "MAX_LADDER_DEPTH": 50
}

class RedundancyExperiment:
    def __init__(self):
        self.ensure_directories()

    def ensure_directories(self):
        if not os.path.exists(CONFIG["OUTPUT_DIR"]):
            os.makedirs(CONFIG["OUTPUT_DIR"])

    def run_command(self, cmd):
        start_time = time.time()
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return result.stdout, time.time() - start_time
        except Exception as e:
            return "", 0

    def generate_random_aig(self, idx):
        """Generates Random AIG"""
        name = f"random_sample_{idx}"
        aag_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{name}.aag")
        aig_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{name}.aig")
        
        inputs = random.randint(10, 30)
        gates = random.randint(100, 500)
        
        # Run aigfuzz
        self.run_command(f"{CONFIG['AIGFUZZ_PATH']} {inputs} 0 1 {gates} > {aag_path}")
        self.run_command(f"{CONFIG['AIGTOAIG_PATH']} {aag_path} {aig_path}")
        
        return aig_path, "Random_Noise", gates

    def generate_redundant_ladder(self, idx):
        """Generates Redundant Ladder Circuit"""
        name = f"redundant_ladder_{idx}"
        aag_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{name}.aag")
        aig_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{name}.aig")
        
        depth = random.randint(20, CONFIG["MAX_LADDER_DEPTH"])
        num_inputs = depth + 2
        # Exact number of AND gates we are writing
        num_and_gates = depth * 2 
        
        max_var = num_inputs + num_and_gates
        
        with open(aag_path, "w") as f:
            f.write(f"aag {max_var} {num_inputs} 0 2 {num_and_gates}\n")
            for i in range(num_inputs):
                f.write(f"{2 * (i + 1)}\n")
            last_gate_A = 2 * num_inputs + 2 * (depth - 1) * 2
            last_gate_B = last_gate_A + 2
            f.write(f"{last_gate_A}\n")
            f.write(f"{last_gate_B}\n")
            
            current_gate_idx = 2 * num_inputs + 2
            
            # Step 1
            f.write(f"{current_gate_idx} 2 4\n")
            prev_A = current_gate_idx
            current_gate_idx += 2
            
            f.write(f"{current_gate_idx} 2 4\n")
            prev_B = current_gate_idx
            current_gate_idx += 2
            
            # Step 2..Depth
            for d in range(1, depth):
                next_input = 2 * (d + 2) + 2
                f.write(f"{current_gate_idx} {prev_A} {next_input}\n")
                prev_A = current_gate_idx
                current_gate_idx += 2
                f.write(f"{current_gate_idx} {prev_B} {next_input}\n")
                prev_B = current_gate_idx
                current_gate_idx += 2

        # Convert
        self.run_command(f"{CONFIG['AIGTOAIG_PATH']} {aag_path} {aig_path}")
        
        return aig_path, "Redundant_Ladder", num_and_gates

    def analyze_circuit(self, file_path):
        """Runs ABC and captures stats before/after strash"""
        # We print stats TWICE: Once after loading (Pre-opt), Once after strash (Post-opt)
        cmd = f'{CONFIG["ABC_PATH"]} -c "read_aiger {file_path}; print_stats; strash; print_stats; quit"'
        output, duration = self.run_command(cmd)
        
        matches = re.findall(r"and\s*=\s*(\d+)", output)
        
        if len(matches) >= 2:
            binary_size = int(matches[0]) # What ABC saw when it opened the file
            final_size = int(matches[1])  # What remained after strash
            return binary_size, final_size, duration
        return 0, 0, duration

    def run(self):
        print(f"\n🔬 Starting Thesis Experiment at {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 105)
        print(f"{'ID':<25} {'Type':<18} {'Generated':<10} {'Binary':<10} {'Final':<10} {'Removed':<10} {'Status'}")
        print("-" * 105)

        csv_path = os.path.join(CONFIG["OUTPUT_DIR"], CONFIG["REPORT_FILE"])
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Type", "Generated_Gates", "Binary_File_Gates", "Final_Gates", "Total_Removed", "Reduction_%"])

            # 1. Random
            for i in range(1, CONFIG["NUM_RANDOM_TESTS"] + 1):
                path, c_type, gen_gates = self.generate_random_aig(i)
                bin_gates, fin_gates, _ = self.analyze_circuit(path)
                self.log_result(writer, os.path.basename(path), c_type, gen_gates, bin_gates, fin_gates)

            # 2. Ladder
            for i in range(1, CONFIG["NUM_REDUNDANT_TESTS"] + 1):
                path, c_type, gen_gates = self.generate_redundant_ladder(i)
                bin_gates, fin_gates, _ = self.analyze_circuit(path)
                self.log_result(writer, os.path.basename(path), c_type, gen_gates, bin_gates, fin_gates)

        print("=" * 105)
        print(f"✅ Experiment Complete. Data saved to: {csv_path}")

    def log_result(self, writer, name, c_type, gen, bin_g, fin):
        removed = gen - fin
        percent = (removed / gen * 100) if gen > 0 else 0.0
        
        status = "REDUCED! ✅" if removed > 0 else "-"
        
        writer.writerow([name, c_type, gen, bin_g, fin, removed, f"{percent:.2f}"])
        print(f"{name:<25} {c_type:<18} {gen:<10} {bin_g:<10} {fin:<10} {removed:<10} {status}")

if __name__ == "__main__":
    experiment = RedundancyExperiment()
    experiment.run()