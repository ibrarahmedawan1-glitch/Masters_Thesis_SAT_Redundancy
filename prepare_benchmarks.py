import os
import glob
import subprocess

# --- CONFIGURATION ---
# Put your raw .v files here
SOURCE_FOLDER = 'verilog_files' 
# The script will put .aag and .log files here
OUTPUT_FOLDER = 'benchmarks'    

def run_yosys(verilog_file):
    # 1. Get the filename without folder (e.g., "c17.v")
    base_name = os.path.basename(verilog_file)
    name_no_ext = os.path.splitext(base_name)[0]
    
    # 2. Define output paths
    aag_file = os.path.join(OUTPUT_FOLDER, f"{name_no_ext}.aag")
    log_file = os.path.join(OUTPUT_FOLDER, f"{name_no_ext}.log")
    
    print(f"Synthesizing {base_name}...")
    
    # 3. The Yosys Command (Synthesize + ABC + Write AIGER)
    # We use -top {name_no_ext} assuming the module name matches the filename
    cmd = f'yosys -p "read_verilog {verilog_file}; synth -top {name_no_ext}; abc -g AND; write_aiger -ascii {aag_file}"'
    
    # 4. Run it and save the LOG to a file
    with open(log_file, "w") as log:
        # result captures the success/failure code
        result = subprocess.run(cmd, shell=True, stdout=log, stderr=subprocess.STDOUT)
    
    if result.returncode == 0:
        print(f"  [OK] Saved -> {aag_file}")
        print(f"  [OK] Log   -> {log_file}")
    else:
        print(f"  [ERROR] Yosys failed. Check {log_file}")

# --- MAIN SCRIPT ---
if __name__ == "__main__":
    # Create folders if they don't exist
    if not os.path.exists(SOURCE_FOLDER):
        os.makedirs(SOURCE_FOLDER)
        print(f"Created '{SOURCE_FOLDER}'. Please put your .v files there!")
        exit()
        
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    # Find all .v files in the source folder
    verilog_files = glob.glob(os.path.join(SOURCE_FOLDER, "*.v"))
    
    if not verilog_files:
        print(f"No .v files found in '{SOURCE_FOLDER}/'.")
    else:
        print(f"Found {len(verilog_files)} Verilog files. Starting batch synthesis...\n")
        for v_file in verilog_files:
            run_yosys(v_file)
            print("-" * 40)