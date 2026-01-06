import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import glob
import os

# --- CONFIGURATION ---
RESULTS_FOLDER = 'results'
PLOTS_FOLDER = 'thesis_plots'

# 1. Setup
if not os.path.exists(PLOTS_FOLDER):
    os.makedirs(PLOTS_FOLDER)

# 2. Load the LATEST CSV file automatically
list_of_files = glob.glob(os.path.join(RESULTS_FOLDER, '*.csv'))
if not list_of_files:
    print("Error: No CSV files found in 'results/'")
    exit()
latest_file = max(list_of_files, key=os.path.getctime)
print(f"Analyzing data from: {latest_file}")

df = pd.read_csv(latest_file)

# 3. Clean Data
# Convert 'TIMEOUT' status to a high numeric value for plotting visibility if needed
# But for stats, we separate them.
df_clean = df[df['Status'] != 'TIMEOUT'].copy()
timeout_count = df[df['Status'] == 'TIMEOUT'].shape[0]

print(f"Total Rows: {len(df)}")
print(f"Timeouts ignored in time stats: {timeout_count}")

# Set a professional style
sns.set_theme(style="whitegrid")

# ==========================================
# CHART 1: Total Execution Time (The Race)
# ==========================================
# Which solver is the fastest overall?
plt.figure(figsize=(10, 6))
solver_time = df_clean.groupby('Solver')['Time_Sec'].sum().sort_values()
ax = sns.barplot(x=solver_time.index, y=solver_time.values, palette="viridis")

plt.title('Total Execution Time across All Circuits (Lower is Better)', fontsize=14)
plt.xlabel('Solver', fontsize=12)
plt.ylabel('Total Time (Seconds)', fontsize=12)
plt.xticks(rotation=45)
for i in ax.containers:
    ax.bar_label(i, fmt='%.1fs')
plt.tight_layout()
plt.savefig(f'{PLOTS_FOLDER}/1_total_time_comparison.png', dpi=300)
print("Saved Chart 1: Total Time")

# ==========================================
# CHART 2: Redundancy Detection Count
# ==========================================
# How many "UNSAT" (Redundant) wires did each solver identify?
# This proves all solvers are accurate (they should find the same number).
plt.figure(figsize=(10, 6))
redundant_counts = df[df['Status'] == 'UNSAT'].groupby('Solver').size()
ax = sns.barplot(x=redundant_counts.index, y=redundant_counts.values, palette="magma")

plt.title('Total Redundant Wires Detected (Accuracy Check)', fontsize=14)
plt.xlabel('Solver')
plt.ylabel('Count of UNSAT Wires')
plt.ylim(bottom=redundant_counts.min() * 0.9, top=redundant_counts.max() * 1.05) # Zoom in to see diffs
for i in ax.containers:
    ax.bar_label(i, fmt='%d')
plt.tight_layout()
plt.savefig(f'{PLOTS_FOLDER}/2_redundancy_count.png', dpi=300)
print("Saved Chart 2: Redundancy Count")

# ==========================================
# CHART 3: Performance on the "Hardest" Circuit
# ==========================================
# Box Plots show consistency. A narrow box means the solver is predictable.
hardest_circuit = df_clean.groupby('Circuit')['Time_Sec'].sum().idxmax()
print(f"Hardest Circuit identified: {hardest_circuit}")

subset = df_clean[df_clean['Circuit'] == hardest_circuit]

plt.figure(figsize=(12, 6))
sns.boxplot(data=subset, x='Solver', y='Time_Sec', palette="coolwarm", showfliers=False)
plt.title(f'Solver Consistency on Hardest Circuit ({hardest_circuit})', fontsize=14)
plt.ylabel('Time per Wire (Seconds)')
plt.tight_layout()
plt.savefig(f'{PLOTS_FOLDER}/3_consistency_box_plot.png', dpi=300)
print("Saved Chart 3: Consistency Box Plot")

# ==========================================
# CHART 4: Solver Heatmap (The "Overview")
# ==========================================
# Which solver is best for which circuit?
pivot_table = df_clean.pivot_table(values='Time_Sec', index='Circuit', columns='Solver', aggfunc='sum')

plt.figure(figsize=(10, 8))
sns.heatmap(pivot_table, annot=True, fmt=".1f", cmap="YlGnBu", linewidths=.5)
plt.title('Heatmap: Total Time (s) per Circuit per Solver', fontsize=14)
plt.tight_layout()
plt.savefig(f'{PLOTS_FOLDER}/4_solver_heatmap.png', dpi=300)
print("Saved Chart 4: Heatmap")

print(f"\n[SUCCESS] Analysis Complete. Open the '{PLOTS_FOLDER}' folder to see your charts.")