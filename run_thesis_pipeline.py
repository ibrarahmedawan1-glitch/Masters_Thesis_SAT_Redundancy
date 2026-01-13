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
    # 1. PATHS
    "AIGFUZZ_PATH": "./aiger/aigfuzz",
    "AIGTOAIG_PATH": "./aiger/aigtoaig",
    "ABC_PATH": "./abc/abc",
    
    # 2. OUTPUT
    "OUTPUT_DIR": "thesis_benchmarks",
    "REPORT_FILE": "thesis_results_final.csv",
    
    # 3. YOUR REPO FOLDER (Point this to where your files are!)
    # Can contain .v, .aag, .aig, or .bench files
    "BENCHMARK_DIR": "verilog_files",  
    
    # 4. SIZES
    "NUM_RANDOM_TESTS": 10,
    "NUM_REDUNDANT_TESTS": 10,
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

    # --- CONVERTERS ---
    def convert_verilog_to_aig(self, v_path):
        """Yosys: .v -> .aig"""
        temp_aig = os.path.join(CONFIG["OUTPUT_DIR"], "temp_from_verilog.aig")
        yosys_cmd = f"yosys -p 'read_verilog {v_path}; aigmap; write_aiger {temp_aig}'"
        subprocess.run(yosys_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return temp_aig if os.path.exists(temp_aig) else None

    def convert_aag_to_aig(self, aag_path):
        """aigtoaig: .aag -> .aig (Cleans up formatting issues)"""
        temp_aig = os.path.join(CONFIG["OUTPUT_DIR"], "temp_from_aag.aig")
        cmd = f"{CONFIG['AIGTOAIG_PATH']} {aag_path} {temp_aig}"
        self.run_command(cmd)
        return temp_aig if os.path.exists(temp_aig) else None

    # --- GENERATORS ---
    def generate_random_aig(self, idx):
        name = f"random_sample_{idx}"
        aag_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{name}.aag")
        aig_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{name}.aig")
        inputs = random.randint(10, 30)
        gates = random.randint(50, 200)
        self.run_command(f"{CONFIG['AIGFUZZ_PATH']} {inputs} 0 1 {gates} > {aag_path}")
        self.run_command(f"{CONFIG['AIGTOAIG_PATH']} {aag_path} {aig_path}")
        return aig_path, "Random_Noise", gates

    def generate_redundant_ladder(self, idx):
        name = f"redundant_ladder_{idx}"
        aag_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{name}.aag")
        aig_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{name}.aig")
        depth = random.randint(20, CONFIG["MAX_LADDER_DEPTH"])
        num_inputs = depth + 2
        num_and_gates = depth * 2 
        max_var = num_inputs + num_and_gates
        with open(aag_path, "w") as f:
            f.write(f"aag {max_var} {num_inputs} 0 2 {num_and_gates}\n")
            for i in range(num_inputs): f.write(f"{2 * (i + 1)}\n")
            last_gate_A = 2 * num_inputs + 2 * (depth - 1) * 2
            f.write(f"{last_gate_A}\n")
            f.write(f"{last_gate_A + 2}\n")
            current_gate_idx = 2 * num_inputs + 2
            f.write(f"{current_gate_idx} 2 4\n")
            prev_A = current_gate_idx
            current_gate_idx += 2
            f.write(f"{current_gate_idx} 2 4\n")
            prev_B = current_gate_idx
            current_gate_idx += 2
            for d in range(1, depth):
                next_input = 2 * (d + 2) + 2
                f.write(f"{current_gate_idx} {prev_A} {next_input}\n")
                prev_A = current_gate_idx
                current_gate_idx += 2
                f.write(f"{current_gate_idx} {prev_B} {next_input}\n")
                prev_B = current_gate_idx
                current_gate_idx += 2
        self.run_command(f"{CONFIG['AIGTOAIG_PATH']} {aag_path} {aig_path}")
        return aig_path, "Redundant_Ladder", num_and_gates

    # --- ANALYZER ---
    def analyze_circuit(self, file_path):
        """
        Smart Analyzer: Detects file type and converts if necessary before ABC.
        """
        target_file = file_path
        is_temp = False

        # 1. SMART CONVERSION
        if file_path.endswith(".v"):
            converted = self.convert_verilog_to_aig(file_path)
            if converted:
                target_file = converted
                is_temp = True
            else:
                return 0, 0, 0 # Yosys failed
        
        elif file_path.endswith(".aag"):
            # ASCII AIGER: Convert to Binary first to avoid ABC parsing errors
            converted = self.convert_aag_to_aig(file_path)
            if converted:
                target_file = converted
                is_temp = True
            else:
                return 0, 0, 0 # aigtoaig failed

        # 2. RUN ABC
        # If .bench, use read_bench. For .aig (or converted files), use read_aiger.
        read_cmd = "read_bench" if target_file.endswith(".bench") else "read_aiger"
        cmd = f'{CONFIG["ABC_PATH"]} -c "{read_cmd} {target_file}; print_stats; strash; print_stats; quit"'
        output, duration = self.run_command(cmd)
        
        # 3. CLEANUP
        if is_temp and os.path.exists(target_file):
            os.remove(target_file)

        matches = re.findall(r"and\s*=\s*(\d+)", output)
        if len(matches) >= 2:
            return int(matches[0]), int(matches[1]), duration
        elif len(matches) == 1:
            return int(matches[0]), int(matches[0]), duration
        return 0, 0, duration

    def run(self):
        print(f"\n🔬 Starting Thesis Experiment at {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 115)
        print(f"{'Circuit Name':<30} {'Category':<18} {'Original':<10} {'Final':<10} {'Removed':<10} {'% Red.':<10} {'Status'}")
        print("-" * 115)

        csv_path = os.path.join(CONFIG["OUTPUT_DIR"], CONFIG["REPORT_FILE"])
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Circuit_Name", "Category", "Original_Gates", "Final_Gates", "Removed", "Reduction_%", "Time_Sec"])

            # 1. Random Tests
            for i in range(1, CONFIG["NUM_RANDOM_TESTS"] + 1):
                path, c_type, gen_gates = self.generate_random_aig(i)
                orig, final, dur = self.analyze_circuit(path)
                self.log_result(writer, os.path.basename(path), c_type, gen_gates, final, dur)

            # 2. Ladder Tests
            for i in range(1, CONFIG["NUM_REDUNDANT_TESTS"] + 1):
                path, c_type, gen_gates = self.generate_redundant_ladder(i)
                orig, final, dur = self.analyze_circuit(path)
                self.log_result(writer, os.path.basename(path), c_type, gen_gates, final, dur)

            # 3. FOLDER SCAN (The Universal Loader)
            if os.path.exists(CONFIG["BENCHMARK_DIR"]):
                print("-" * 115)
                print(f"📂 Scanning folder: {CONFIG['BENCHMARK_DIR']} ...")
                
                # We now accept ALL relevant formats
                valid_exts = ('.v', '.aag', '.aig', '.bench', '.blif')
                files = [f for f in os.listdir(CONFIG["BENCHMARK_DIR"]) if f.endswith(valid_exts)]
                
                if not files:
                    print(f"   ⚠️ No valid circuits {valid_exts} found.")
                
                for filename in files:
                    full_path = os.path.join(CONFIG["BENCHMARK_DIR"], filename)
                    orig, final, dur = self.analyze_circuit(full_path)
                    
                    # For real files, we use 'orig' as the baseline
                    self.log_result(writer, filename, "Real_Benchmark", orig, final, dur)
            else:
                print(f"⚠️ Folder not found: {CONFIG['BENCHMARK_DIR']}")

        print("=" * 115)
        print(f"✅ Experiment Complete. Data saved to: {csv_path}")

    def log_result(self, writer, name, c_type, orig, final, duration):
        removed = orig - final
        percent = (removed / orig * 100) if orig > 0 else 0.0
        status = "REDUCED! ✅" if removed > 0 else "Optimal"
        writer.writerow([name, c_type, orig, final, removed, f"{percent:.2f}", f"{duration:.4f}"])
        print(f"{name:<30} {c_type:<18} {orig:<10} {final:<10} {removed:<10} {percent:<10.1f} {status}")

if __name__ == "__main__":
    experiment = RedundancyExperiment()
    experiment.run()