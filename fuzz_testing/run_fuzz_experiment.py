def main():
    # 1. Setup
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    print("🚀 Starting AIG Fuzzing Experiment...")
    print(f"📂 Benchmarks will be saved in: {OUTPUT_DIR}/")
    
    # --- CONTROL TEST (The Proof) ---
    # We use yosys to convert your Verilog demo to AIG, then check it.
    # This proves the script is capable of finding redundancy.
    print("\n[Test] Running Control Group (redundant_demo.v)...")
    if os.path.exists("redundant_demo.v"):
        # Convert Verilog -> AIG using Yosys
        demo_aig = f"{OUTPUT_DIR}/control_demo.aig"
        subprocess.run(f"yosys -p 'read_verilog redundant_demo.v; aigmap; write_aiger {demo_aig}'", 
                       shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Check it
        before, after = check_redundancy(demo_aig)
        if before > after:
            print(f"✅ Control Test PASSED: Detected {before - after} redundant gates in demo.")
        else:
            print("⚠️ Control Test Warning: No redundancy found in demo (Check your demo file).")
    else:
        print("⚠️ Skipping Control Test: 'redundant_demo.v' not found.")
    print("-" * 40)

    # 2. Open CSV Report
    with open(REPORT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Inputs", "Gen_Gates", "Gates_Before", "Gates_After", "Removed", "Reduction_%"])
        
        # 3. Run Loop
        for i in range(1, 21):
            file_path, inputs, gen_gates = generate_circuit(i)
            before, after = check_redundancy(file_path)
            
            removed = before - after
            reduction = (removed / before * 100) if before > 0 else 0
            
            writer.writerow([i, inputs, gen_gates, before, after, removed, f"{reduction:.1f}"])
            print(f" Circuit {i}: {before} -> {after} gates (Removed {removed})")

    print(f"\n✅ Experiment Complete! Results saved to {REPORT_FILE}")